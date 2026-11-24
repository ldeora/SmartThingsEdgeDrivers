"""Receipt and phase-specific evidence fixtures. No real service calls."""
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

    def test_partial_restore_refused(self):
        self.existing()
        self.trans.location(core.APP_FILES[1]).unlink()
        with self.store.transaction(RESTORE) as handle:
            self.prepare(handle, intent=RESTORE)
            with self.assertRaises(before.BeforeStateError):
                before.capture_before(handle, lambda: SERVICES)
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
