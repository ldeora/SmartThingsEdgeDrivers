"""Fixture quarantine publication, refusal, and interrupted move retries."""
import os
import unittest
from unittest import mock

import test_restore_adopt_before as fixtures
from test_restore_adopt_before import ADOPT, EMPTY, before, old
import restore_adopt_quarantine as quarantine


class UnboundQuarantineTests(unittest.TestCase):
    setUp = fixtures.BeforeStateTests.setUp
    prepare = fixtures.BeforeStateTests.prepare
    def prepare_unbound(self, handle):
        self.prepare(handle)
        captured = before.capture_before(handle, lambda: EMPTY)
        handle.advance('ABORTED', verify=lambda _: True)
        path = self.base / captured.snapshot_name
        (path / 'manifest.json').write_bytes(b'partial')
        (path / 'receipt.json').write_bytes(b'')
        return path

    def move(self, handle, verify=lambda _: True):
        return quarantine.quarantine_unbound_before(handle, confirmation='QUARANTINE',
                                                   verify=verify)

    def locations(self, handle):
        q = self.base / 'quarantine-v2'
        name = 'unbound-' + handle.record()['transaction_id']
        return q / name, q / (name + '.json')

    def test_quarantine_preserves_bytes_and_is_idempotent(self):
        with self.store.transaction(ADOPT) as handle:
            source = self.prepare_unbound(handle)
            dest, receipt = self.locations(handle)
            self.assertEqual(self.move(handle), 'quarantined')
            self.assertFalse(source.exists())
            self.assertEqual((dest / 'manifest.json').read_bytes(), b'partial')
            self.assertEqual((dest / 'receipt.json').read_bytes(), b'')
            self.assertTrue(receipt.is_file())
            self.assertEqual(handle.record()['phase'], 'ABORTED')
        with self.store.transaction() as handle:
            self.assertEqual(self.move(handle), 'already_quarantined')
            self.assertEqual(handle.record()['phase'], 'ABORTED')
            with self.assertRaises(before.BeforeStateError):
                before.read_before(handle)

    def test_quarantine_requires_verifier_and_confirmation(self):
        with self.store.transaction(ADOPT) as handle:
            source = self.prepare_unbound(handle)
            with self.assertRaises(before.BeforeStateError):
                quarantine.quarantine_unbound_before(handle, confirmation='NO',
                                                      verify=lambda _: True)
            with self.assertRaises(before.BeforeStateError):
                self.move(handle, lambda _: False)
            self.assertTrue(source.exists())
            self.assertFalse((self.base / 'quarantine-v2').exists())

    def test_quarantine_refuses_verifier_time_change(self):
        with self.store.transaction(ADOPT) as handle:
            source = self.prepare_unbound(handle)
            def change(_):
                (source / 'manifest.json').write_bytes(b'changed')
                return True
            with self.assertRaises(before.BeforeStateError):
                self.move(handle, change)
            self.assertEqual((source / 'manifest.json').read_bytes(), b'changed')
            self.assertFalse((self.base / 'quarantine-v2').exists())

    def test_quarantine_refuses_destination_collision(self):
        with self.store.transaction(ADOPT) as handle:
            source = self.prepare_unbound(handle)
            dest, receipt = self.locations(handle)
            dest.parent.mkdir(mode=0o700)
            dest.mkdir(mode=0o700)
            with self.assertRaises(before.BeforeStateError):
                self.move(handle)
            self.assertTrue(source.exists())
            self.assertTrue(dest.exists())
            self.assertFalse(receipt.exists())

    def test_quarantine_retry_after_move_or_before_move(self):
        for after in (False, True):
            with self.subTest(after=after):
                # Each transaction needs cleanup before the next.
                with self.store.transaction(ADOPT) as handle:
                    source = self.prepare_unbound(handle)
                    dest, receipt = self.locations(handle)
                    original = quarantine._rename_noreplace
                    def interrupted(*args):
                        if after:
                            original(*args)
                        raise OSError('injected')
                    with mock.patch.object(quarantine, '_rename_noreplace', side_effect=interrupted):
                        with self.assertRaises(before.BeforeStateError):
                            self.move(handle)
                    with self.assertRaises(old.JournalConflict):
                        handle.record()
                self.assertTrue(receipt.exists())
                self.assertEqual(dest.exists(), after)
                self.assertEqual(source.exists(), not after)
                with self.store.transaction() as handle:
                    self.assertEqual(self.move(handle),
                                     'already_quarantined' if after else 'quarantined')
                    before.stage.retire_terminal_plan(handle)
                    handle.clear_finished(lambda _: True)
                self.assertEqual((dest / 'manifest.json').read_bytes(), b'partial')

    def test_quarantine_refuses_partial_receipt(self):
        with self.store.transaction(ADOPT) as handle:
            source = self.prepare_unbound(handle)
            dest, receipt = self.locations(handle)
            dest.parent.mkdir(mode=0o700)
            receipt.write_bytes(b'')
            receipt.chmod(0o600)
            with self.assertRaises(before.BeforeStateError):
                self.move(handle)
            self.assertTrue(source.exists())
            self.assertEqual(receipt.read_bytes(), b'')
            self.assertFalse(dest.exists())

    def test_quarantine_refuses_unsafe_tree_and_bound_snapshot(self):
        with self.store.transaction(ADOPT) as handle:
            source = self.prepare_unbound(handle)
            os.link(source / 'manifest.json', self.root / 'link')
            with self.assertRaises(before.BeforeStateError):
                self.move(handle)
            self.assertTrue(source.exists())
            (self.root / 'link').unlink()
            before.stage.retire_terminal_plan(handle)
            handle.clear_finished(lambda _: True)
        with self.store.transaction(ADOPT) as handle:
            self.prepare(handle)
            captured = before.capture_before(handle, lambda: EMPTY)
            from restore_adopt_verify import bind_before
            bind_before(handle, captured, lambda: EMPTY)
            handle.advance('ABORTED', verify=lambda _: True)
            with self.assertRaises(before.BeforeStateError):
                self.move(handle)
            self.assertEqual(before.read_before(handle), captured)
