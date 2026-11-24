"""Receipt and phase-specific evidence fixtures. No real service calls."""
from dataclasses import replace
import hashlib
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import install_core as core
import restore_adopt_before as before
import restore_adopt_journal as journal
import restore_adopt_stage as stage
import restore_adopt_verify as verify
import transaction_journal as old
from test_restore_adopt_contract import ADOPT, ADOPT_EVIDENCE, RESTORE, RESTORE_EVIDENCE
from test_restore_adopt_stage import SERVICES, files

EMPTY = dict(agent_active=False, agent_enabled=False, socket_active=False, socket_enabled=False)


class BeforeStateTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / 'run/lock').mkdir(parents=True)
        self.store = journal.FixtureJournal(self.root)
        self.base = self.root / core.BACKUP_BASE.lstrip('/')
        self.trans = core.InstallTransaction(self.root)

    def prepare(self, handle, *, intent=ADOPT):
        planned = files()
        digest = stage.stage_plan(handle, planned, SERVICES)
        evidence = ADOPT_EVIDENCE if intent == ADOPT else RESTORE_EVIDENCE
        verify.bind_stage(handle, digest=digest,
                          evidence=dict(evidence, staged_plan_sha256=digest),
                          expected_files=planned, expected_services=SERVICES)
        return planned

    def existing(self):
        result = tuple(core.Change(f.path,
                        b'PROTOCOL = "computer-host-agent"\nVERSION = "0.4.6-rc.2"\n'
                        if f.path == core.APP_FILES[0] else f.content, f.mode)
                       for f in files())
        self.trans.apply(list(result))
        return result

    def test_adoption_empty_before_state_and_bound_read(self):
        with self.store.transaction(ADOPT) as handle:
            planned = self.prepare(handle)
            captured = before.capture_before(handle, lambda: EMPTY)
            self.assertTrue(all(f.content is None for f in captured.files))
            self.assertEqual(dict(captured.services), EMPTY)
            self.assertEqual(captured, before.read_before(handle, proposed=captured))
            verify.bind_before(handle, captured, lambda: EMPTY)
            self.assertEqual(handle.record()['snapshot_name'], captured.snapshot_name)
            self.assertEqual(handle.record()['before_receipt_sha256'], captured.receipt_sha256)
            plan, rollback = verify.check_apply_evidence(
                handle, expected_files=planned, expected_services=SERVICES,
                observer=lambda: EMPTY)
            self.assertEqual(rollback, captured)
            self.assertEqual(plan.files, planned)
            with self.assertRaises(before.BeforeStateError):
                before.read_before(handle, proposed=captured)
            with self.assertRaises(core.InstallError):
                core.validate_v2_backup(self.base / captured.snapshot_name, root=self.root)

    def test_restore_before_state_is_distinct_and_checks_actual_restoration(self):
        installed = self.existing()
        with self.store.transaction(RESTORE) as handle:
            self.prepare(handle, intent=RESTORE)
            captured = before.capture_before(handle, lambda: SERVICES)
            self.assertNotEqual(captured.snapshot_name, RESTORE['snapshot_name'])
            self.assertEqual({f.path: f.content for f in captured.files},
                             {f.path: f.content for f in installed})
            verify.bind_before(handle, captured, lambda: SERVICES)
            handle.advance('APPLYING', verify=lambda _: True)
            path = self.trans.location(core.APP_FILES[0])
            original = path.read_bytes()
            path.write_bytes(b'changed')
            self.assertFalse(verify.check_rollback_evidence(handle, lambda: SERVICES))
            path.write_bytes(original)
            self.assertFalse(verify.check_rollback_evidence(handle, lambda: EMPTY))
            path.chmod(0o775)
            self.assertFalse(verify.check_rollback_evidence(handle, lambda: SERVICES))
            path.chmod(0o755)
            self.assertTrue(verify.check_rollback_evidence(handle, lambda: SERVICES))
            self.assertEqual(handle.record()['phase'], 'APPLYING')

    def test_independent_plan_mismatch_prevents_stage_binding(self):
        with self.store.transaction(ADOPT) as handle:
            digest = stage.stage_plan(handle, files(), SERVICES)
            changed = tuple(core.Change(f.path, b'wrong' if f.path == core.APP_FILES[0]
                                        else f.content, f.mode) for f in files())
            with self.assertRaises(stage.PlanError):
                verify.bind_stage(handle, digest=digest,
                                  evidence=dict(ADOPT_EVIDENCE, staged_plan_sha256=digest),
                                  expected_files=changed, expected_services=SERVICES)
            self.assertEqual(handle.record()['phase'], 'INSPECTED')

    def test_snapshot_binding_refuses_state_change_and_tampered_receipt(self):
        with self.store.transaction(ADOPT) as handle:
            self.prepare(handle)
            captured = before.capture_before(handle, lambda: EMPTY)
            with self.assertRaises(old.JournalConflict):
                verify.bind_before(handle, captured, lambda: SERVICES)
            self.assertEqual(handle.record()['phase'], 'STAGED')
            receipt = self.base / captured.snapshot_name / 'receipt.json'
            receipt.write_bytes(receipt.read_bytes() + b' ')
            with self.assertRaises(before.BeforeStateError):
                verify.bind_before(handle, captured, lambda: EMPTY)
            self.assertEqual(handle.record()['phase'], 'STAGED')

    def test_receipt_cannot_be_rebound_even_with_new_digest(self):
        with self.store.transaction(ADOPT) as handle:
            self.prepare(handle)
            captured = before.capture_before(handle, lambda: EMPTY)
            directory = self.base / captured.snapshot_name
            receipt = directory / 'receipt.json'
            original = receipt.read_bytes()
            # Model a receipt taken from a different transaction. A
            # caller who can calculate the modified digest still cannot
            # make it agree with the held transaction and manifest.
            altered = original.replace(handle.record()['transaction_id'].encode(),
                                       b'f' * 32)
            self.assertNotEqual(original, altered)
            receipt.write_bytes(altered)
            forged = replace(captured, receipt_sha256=hashlib.sha256(altered).hexdigest())
            with self.assertRaises(before.BeforeStateError):
                verify.bind_before(handle, forged, lambda: EMPTY)
            self.assertEqual(handle.record()['phase'], 'STAGED')

    def test_preapply_rechecks_bound_stage_bytes(self):
        with self.store.transaction(ADOPT) as handle:
            planned = self.prepare(handle)
            captured = before.capture_before(handle, lambda: EMPTY)
            verify.bind_before(handle, captured, lambda: EMPTY)
            staging = self.root / 'var/lib/computer-host-installer/staging'
            ready, = staging.glob('ready-plan-*')
            next(ready.glob('*.data')).write_bytes(b'tampered')
            with self.assertRaises(stage.PlanError):
                verify.check_apply_evidence(handle, expected_files=planned,
                                            expected_services=SERVICES, observer=lambda: EMPTY)
            self.assertEqual(handle.record()['phase'], 'SNAPSHOTTED')

    def test_snapshot_payload_tampering_and_extra_entry_refused(self):
        self.existing()
        with self.store.transaction(RESTORE) as handle:
            self.prepare(handle, intent=RESTORE)
            captured = before.capture_before(handle, lambda: SERVICES)
            verify.bind_before(handle, captured, lambda: SERVICES)
            directory = self.base / captured.snapshot_name
            extra = directory / 'extra'
            extra.write_bytes(b'extra')
            with self.assertRaises(before.BeforeStateError):
                before.read_before(handle)
            extra.unlink()
            original = next(directory.glob('*.original'))
            raw = original.read_bytes()
            original.write_bytes(b'damaged')
            with self.assertRaises(before.BeforeStateError):
                before.read_before(handle)
            original.write_bytes(raw)
            original.chmod(0o644)
            with self.assertRaises(before.BeforeStateError):
                before.read_before(handle)

    def test_adoption_refuses_nonempty_before_and_restore_refuses_partial(self):
        self.existing()
        with self.store.transaction(ADOPT) as handle:
            self.prepare(handle)
            with self.assertRaises(before.BeforeStateError):
                before.capture_before(handle, lambda: SERVICES)
            self.assertEqual(handle.record()['phase'], 'STAGED')

    def test_damaged_installed_mode_requires_repair_not_restore(self):
        self.existing()
        avahi = self.trans.location(core.AVAHI_PATH)
        avahi.parent.mkdir(parents=True, exist_ok=True)
        avahi.write_bytes(b'<type>_computerhost._tcp</type>\n')
        avahi.chmod(0o664)
        with self.store.transaction(RESTORE) as handle:
            self.prepare(handle, intent=RESTORE)
            with self.assertRaisesRegex(before.BeforeStateError,
                                        r'^current_state_permissions_damaged$'):
                before.capture_before(handle, lambda: SERVICES)
            self.assertEqual(avahi.stat().st_mode & 0o777, 0o664)
            self.assertEqual(handle.record()['phase'], 'STAGED')
            self.assertFalse(list(self.base.glob('snapshot-v2-*')))
            other = self.root / 'linked-avahi'
            os.link(avahi, other)
            with self.assertRaisesRegex(before.BeforeStateError, r'^unsafe_before_file$'):
                before.capture_before(handle, lambda: SERVICES)
            other.unlink()
            handle.advance('ABORTED', verify=lambda _: True)
            stage.retire_terminal_plan(handle)
            handle.clear_finished(lambda _: True)
        # Simulate a separately authorized repair after transaction cleanup.
        avahi.chmod(0o644)
        with self.store.transaction(RESTORE) as handle:
            self.prepare(handle, intent=RESTORE)
            captured = before.capture_before(handle, lambda: SERVICES)
            verify.bind_before(handle, captured, lambda: SERVICES)

    def test_partial_restore_refused(self):
        self.existing()
        self.trans.location(core.APP_FILES[1]).unlink()
        with self.store.transaction(RESTORE) as handle:
            self.prepare(handle, intent=RESTORE)
            with self.assertRaises(before.BeforeStateError):
                before.capture_before(handle, lambda: SERVICES)
            self.assertEqual(handle.record()['phase'], 'STAGED')

    def test_clean_restore_before_state_is_empty(self):
        with self.store.transaction(RESTORE) as handle:
            self.prepare(handle, intent=RESTORE)
            captured = before.capture_before(handle, lambda: EMPTY)
            self.assertTrue(all(f.content is None for f in captured.files))
            verify.bind_before(handle, captured, lambda: EMPTY)

    def test_service_observation_change_refuses_capture(self):
        with self.store.transaction(ADOPT) as handle:
            self.prepare(handle)
            observer = mock.Mock(side_effect=[EMPTY, SERVICES])
            with self.assertRaises(before.BeforeStateError):
                before.capture_before(handle, observer)
            self.assertFalse(list(self.base.glob('snapshot-v2-*')))
            self.assertEqual(handle.record()['phase'], 'STAGED')

    def test_failed_capture_leaves_staged_journal_and_preserves_evidence(self):
        with self.store.transaction(ADOPT) as handle:
            self.prepare(handle)
            original = before.storage._write_file

            def write(fd, name, content, digest, uid):
                if name == 'receipt.json':
                    raise OSError('fixture receipt write')
                return original(fd, name, content, digest, uid)

            with mock.patch.object(before.storage, '_write_file', side_effect=write):
                with self.assertRaises(before.BeforeStateError):
                    before.capture_before(handle, lambda: EMPTY)
            directory, = self.base.glob('snapshot-v2-*')
            self.assertTrue((directory / 'manifest.json').exists())
            self.assertFalse((directory / 'receipt.json').exists())
            with self.assertRaises(old.JournalConflict):
                handle.record()
        with self.store.transaction() as recovery:
            self.assertEqual(recovery.record()['phase'], 'STAGED')
            with self.assertRaises(before.BeforeStateError):
                before.capture_before(recovery, lambda: EMPTY)
            recovery.advance('ABORTED', verify=lambda _: True)
            stage.retire_terminal_plan(recovery)
            # Retiring a stage does not remove or certify an unbound
            # before-state directory. Preserve it for forensic review.
            self.assertTrue(directory.is_dir())
            self.assertTrue((directory / 'manifest.json').exists())
            self.assertFalse((directory / 'receipt.json').exists())
            recovery.clear_finished(lambda _: True)
        self.assertTrue(directory.is_dir())

    def test_unbound_inspection_distinguishes_absent_partial_and_complete_shape(self):
        with self.store.transaction(ADOPT) as handle:
            self.prepare(handle)
            captured = before.capture_before(handle, lambda: EMPTY)
            directory = self.base / captured.snapshot_name
            with self.assertRaises(before.BeforeStateError):
                before.inspect_unbound_before(handle)
            handle.advance('ABORTED', verify=lambda _: True)
            observation = before.inspect_unbound_before(handle)
            self.assertEqual(observation.status, 'preserved_unbound')
            self.assertTrue(observation.manifest_present)
            self.assertTrue(observation.receipt_present)
            self.assertEqual(observation.original_count, 0)
            # Even a complete unbound capture is not a recovery source.
            with self.assertRaises(before.BeforeStateError):
                before.read_before(handle)
            receipt = directory / 'receipt.json'
            receipt.unlink()
            (directory / 'manifest.json').write_bytes(b'')
            observed = before.inspect_unbound_before(handle)
            self.assertTrue(observed.manifest_present)
            self.assertFalse(observed.receipt_present)
            self.assertEqual((directory / 'manifest.json').read_bytes(), b'')
            extra = directory / 'foreign'
            extra.write_bytes(b'preserve')
            with self.assertRaises(before.BeforeStateError):
                before.inspect_unbound_before(handle)
            self.assertEqual(extra.read_bytes(), b'preserve')
            extra.unlink()
            (directory / 'manifest.json').unlink()
            directory.rmdir()
            self.assertEqual(before.inspect_unbound_before(handle).status, 'absent')

    def test_unbound_inspection_refuses_bound_abort_and_unsafe_entries(self):
        with self.store.transaction(ADOPT) as handle:
            self.prepare(handle)
            captured = before.capture_before(handle, lambda: EMPTY)
            directory = self.base / captured.snapshot_name
            manifest = directory / 'manifest.json'
            other = self.root / 'manifest-hardlink'
            os.link(manifest, other)
            handle.advance('ABORTED', verify=lambda _: True)
            with self.assertRaises(before.BeforeStateError):
                before.inspect_unbound_before(handle)
            self.assertTrue(other.exists())
            other.unlink()
            stage.retire_terminal_plan(handle)
            handle.clear_finished(lambda _: True)
        with self.store.transaction(ADOPT) as handle:
            self.prepare(handle)
            captured = before.capture_before(handle, lambda: EMPTY)
            verify.bind_before(handle, captured, lambda: EMPTY)
            handle.advance('ABORTED', verify=lambda _: True)
            with self.assertRaises(before.BeforeStateError):
                before.inspect_unbound_before(handle)
            self.assertEqual(before.read_before(handle), captured)

    def test_current_state_change_after_binding_refuses_preapply(self):
        with self.store.transaction(ADOPT) as handle:
            planned = self.prepare(handle)
            captured = before.capture_before(handle, lambda: EMPTY)
            verify.bind_before(handle, captured, lambda: EMPTY)
            path = self.trans.location(core.APP_FILES[0])
            path.parent.mkdir(parents=True)
            path.symlink_to('/missing')
            with self.assertRaises(before.BeforeStateError):
                verify.check_apply_evidence(handle, expected_files=planned,
                                            expected_services=SERVICES, observer=lambda: EMPTY)
            self.assertEqual(handle.record()['phase'], 'SNAPSHOTTED')


if __name__ == '__main__':
    unittest.main()
