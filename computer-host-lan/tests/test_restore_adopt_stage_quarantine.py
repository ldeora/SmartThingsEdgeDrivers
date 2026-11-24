"""Fixture corrupt terminal stage quarantine and journal cleanup guards."""
import os
import unittest
from unittest import mock

import test_restore_adopt_stage as fixtures
from test_restore_adopt_stage import ADOPT, ADOPT_EVIDENCE, BEFORE, H, SERVICES, files
import restore_adopt_before as before
import restore_adopt_stage as stage
import restore_adopt_stage_quarantine as quarantine
import transaction_journal as old


class StageQuarantineTests(unittest.TestCase):
    setUp = fixtures.StageTests.setUp

    def ready(self, handle, terminal='ABORTED', corrupt=True):
        digest = stage.stage_plan(handle, files(), SERVICES)
        handle.advance('STAGED', evidence=dict(ADOPT_EVIDENCE, staged_plan_sha256=digest),
                       verify=lambda _: True)
        if terminal != 'ABORTED':
            handle.advance('SNAPSHOTTED', snapshot_name=BEFORE,
                           before_receipt_sha256=H, verify=lambda _: True)
            handle.advance('APPLYING', verify=lambda _: True)
            if terminal == 'COMMITTED':
                handle.advance('ACTIVATING', verify=lambda _: True)
                handle.advance('VERIFYING', verify=lambda _: True)
        handle.advance(terminal, verify=lambda _: True)
        path, = self.base.glob('ready-plan-*')
        if corrupt:
            (path / 'manifest.json').write_bytes(b'')
        return path

    def locations(self, handle):
        name = 'corrupt-stage-' + handle.record()['transaction_id']
        namespace = self.root / 'var/backups/linux-host-agent/quarantine-v2'
        return namespace / name, namespace / (name + '.json')

    def move(self, handle, verify=lambda _: True):
        return quarantine.quarantine_corrupt_stage(handle, confirmation='QUARANTINE',
                                                   verify=verify)

    def test_all_terminal_phases_preserve_stage_and_allow_separately_verified_clear(self):
        for terminal in ('ABORTED', 'COMMITTED', 'ROLLED_BACK'):
            with self.subTest(terminal=terminal):
                with self.store.transaction(ADOPT) as handle:
                    source = self.ready(handle, terminal)
                    dest, receipt = self.locations(handle)
                    original = {p.name: p.read_bytes() for p in source.iterdir()}
                    with self.assertRaises(stage.PlanError):
                        stage.retire_terminal_plan(handle)
                    self.assertEqual(self.move(handle), 'quarantined')
                    self.assertFalse(source.exists())
                    self.assertEqual({p.name: p.read_bytes() for p in dest.iterdir()}, original)
                    self.assertTrue(receipt.exists())
                    with self.assertRaises(old.JournalConflict):
                        handle.clear_finished(lambda _: False)
                    handle.clear_finished(lambda _: True)
                self.assertTrue(dest.exists())
                self.assertTrue(receipt.exists())

    def test_healthy_stage_requires_normal_retirement(self):
        with self.store.transaction(ADOPT) as handle:
            source = self.ready(handle, corrupt=False)
            with self.assertRaisesRegex(before.BeforeStateError, 'healthy_stage'):
                self.move(handle)
            self.assertTrue(source.exists())
            self.assertFalse(quarantine.has_artifacts(handle))
            stage.retire_terminal_plan(handle)
            handle.clear_finished(lambda _: True)

    def test_nonterminal_unbound_and_missing_confirmation_refused(self):
        with self.store.transaction(ADOPT) as handle:
            stage.stage_plan(handle, files(), SERVICES)
            with self.assertRaises(before.BeforeStateError):
                self.move(handle)
            handle.advance('ABORTED', verify=lambda _: True)
            with self.assertRaises(before.BeforeStateError):
                self.move(handle)
            stage.retire_terminal_plan(handle)
            handle.clear_finished(lambda _: True)
        with self.store.transaction(ADOPT) as handle:
            source = self.ready(handle)
            with self.assertRaises(before.BeforeStateError):
                quarantine.quarantine_corrupt_stage(handle, confirmation='NO',
                                                     verify=lambda _: True)
            with self.assertRaises(before.BeforeStateError):
                self.move(handle, lambda _: False)
            self.assertTrue(source.exists())
            self.assertFalse(quarantine.has_artifacts(handle))

    def test_unsafe_and_foreign_entries_preserved(self):
        with self.store.transaction(ADOPT) as handle:
            source = self.ready(handle)
            foreign = self.base / 'pending-plan-foreign'
            foreign.mkdir()
            with self.assertRaises(before.BeforeStateError):
                self.move(handle)
            foreign.rmdir()
            extra = source / 'unknown'
            extra.write_bytes(b'preserve')
            with self.assertRaises(before.BeforeStateError):
                self.move(handle)
            self.assertEqual(extra.read_bytes(), b'preserve')
            extra.unlink()
            data = next(source.glob('*.data'))
            link = self.root / 'hardlink'
            os.link(data, link)
            with self.assertRaises(before.BeforeStateError):
                self.move(handle)
            self.assertTrue(link.exists())
            self.assertTrue(source.exists())

    def test_verifier_time_change_refused(self):
        with self.store.transaction(ADOPT) as handle:
            source = self.ready(handle)
            def change(_):
                (source / 'manifest.json').write_bytes(b'changed')
                return True
            with self.assertRaises(before.BeforeStateError):
                self.move(handle, change)
            self.assertTrue(source.exists())
            self.assertFalse(quarantine.has_artifacts(handle))

    def test_interrupted_move_requires_fresh_quarantine_verification(self):
        for after in (False, True):
            with self.subTest(after=after):
                with self.store.transaction(ADOPT) as handle:
                    source = self.ready(handle)
                    dest, receipt = self.locations(handle)
                    rename = quarantine.q._rename_noreplace
                    def interrupt(*args):
                        if after:
                            rename(*args)
                        raise OSError('injected interruption')
                    with mock.patch.object(quarantine.q, '_rename_noreplace', side_effect=interrupt):
                        with self.assertRaises(before.BeforeStateError):
                            self.move(handle)
                    with self.assertRaises(old.JournalConflict):
                        handle.record()
                self.assertEqual(dest.exists(), after)
                self.assertTrue(receipt.exists())
                with self.store.transaction() as handle:
                    with self.assertRaises(stage.PlanError):
                        stage.retire_terminal_plan(handle)
                    with self.assertRaises(old.JournalConflict):
                        handle.clear_finished(lambda _: True)
                    with self.assertRaises(before.BeforeStateError):
                        self.move(handle, lambda _: False)
                    self.assertEqual(self.move(handle),
                                     'already_quarantined' if after else 'quarantined')
                    handle.clear_finished(lambda _: True)
                self.assertFalse(source.exists())
                self.assertTrue(dest.exists())

    def test_cleanup_rechecks_bytes_after_callback(self):
        with self.store.transaction(ADOPT) as handle:
            self.ready(handle)
            dest, receipt = self.locations(handle)
            self.move(handle)
            def change(_):
                (dest / 'manifest.json').write_bytes(b'modified')
                return True
            with self.assertRaises(old.JournalConflict):
                handle.clear_finished(change)
            self.assertEqual(handle.record()['phase'], 'ABORTED')
            self.assertEqual((dest / 'manifest.json').read_bytes(), b'modified')
        with self.store.transaction() as handle:
            with self.assertRaises(before.BeforeStateError):
                self.move(handle)
            with self.assertRaises(old.JournalConflict):
                handle.clear_finished(lambda _: True)

    def test_partial_receipt_blocks_retirement_and_clear(self):
        with self.store.transaction(ADOPT) as handle:
            source = self.ready(handle)
            dest, receipt = self.locations(handle)
            receipt.parent.mkdir(mode=0o700)
            receipt.touch(mode=0o600)
            with self.assertRaises(before.BeforeStateError):
                self.move(handle)
            with self.assertRaises(stage.PlanError):
                stage.retire_terminal_plan(handle)
            with self.assertRaises(old.JournalConflict):
                handle.clear_finished(lambda _: True)
            self.assertEqual(receipt.read_bytes(), b'')
            self.assertTrue(source.exists())
            self.assertFalse(dest.exists())

    def test_missing_manifest_is_safe_corruption_but_io_error_is_not(self):
        with self.store.transaction(ADOPT) as handle:
            source = self.ready(handle)
            (source / 'manifest.json').unlink()
            with mock.patch.object(stage, '_inspect', side_effect=OSError('injected I/O')):
                with self.assertRaises(before.BeforeStateError):
                    self.move(handle)
            self.assertFalse(quarantine.has_artifacts(handle))
            self.assertEqual(self.move(handle), 'quarantined')
            handle.clear_finished(lambda _: True)

    def test_late_collision_preserves_both(self):
        with self.store.transaction(ADOPT) as handle:
            source = self.ready(handle)
            dest, receipt = self.locations(handle)
            rename = quarantine.q._rename_noreplace
            def collide(*args):
                dest.mkdir(mode=0o700)
                return rename(*args)
            with mock.patch.object(quarantine.q, '_rename_noreplace', side_effect=collide):
                with self.assertRaises(before.BeforeStateError):
                    self.move(handle)
            self.assertTrue(source.exists())
            self.assertEqual(list(dest.iterdir()), [])
            self.assertTrue(receipt.exists())
        with self.store.transaction() as handle:
            with self.assertRaises(before.BeforeStateError):
                self.move(handle)
            with self.assertRaises(old.JournalConflict):
                handle.clear_finished(lambda _: True)
