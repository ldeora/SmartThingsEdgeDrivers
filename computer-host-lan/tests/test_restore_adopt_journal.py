"""Durable schema-2 journal fixtures, no root or host mutation."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import restore_adopt_journal as v2
import transaction_journal as old
from test_restore_adopt_contract import ADOPT, RESTORE, ADOPT_EVIDENCE, BEFORE, H

def verified(_):
    return True

class JournalTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / 'run/lock').mkdir(parents=True)
        self.store = v2.FixtureJournal(self.root)
        self.path = self.root / 'var/backups/linux-host-agent/wizard-transactions/journal.json'
        self.old = old.ProtectedJournal(root=self.root, owner_uid=os.geteuid())

    def test_persist_and_recover_without_forward_replay(self):
        with self.store.transaction(ADOPT) as handle:
            self.assertEqual(handle.record()['phase'], 'INSPECTED')
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
            handle.advance('STAGED', evidence=ADOPT_EVIDENCE, verify=verified)
            handle.advance('SNAPSHOTTED', snapshot_name=BEFORE,
                           before_receipt_sha256=H, verify=verified)
            handle.advance('APPLYING', verify=verified)
        with self.assertRaises(old.UnsafeJournal):
            self.old.public_status()
        with self.store.transaction() as recovery:
            with self.assertRaises(old.JournalConflict):
                recovery.advance('ACTIVATING', verify=verified)
            recovery.advance('ROLLED_BACK', verify=verified)
        with self.assertRaises(old.UnsafeJournal):
            self.old.finish_terminal()
        with self.store.transaction() as cleanup:
            cleanup.clear_finished(verified)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.old.public_status()['privileged_transaction_state'], 'none')

    def test_verified_transition_and_stale_handle(self):
        with self.store.transaction(ADOPT) as handle:
            before = self.path.read_bytes()
            with self.assertRaises(old.JournalConflict):
                handle.advance('STAGED', evidence=ADOPT_EVIDENCE, verify=lambda _: False)
            self.assertEqual(self.path.read_bytes(), before)
            with self.assertRaises(v2.engine.ControllerError):
                with self.store.transaction(RESTORE):
                    self.fail('concurrent transaction')
        with self.assertRaises(old.JournalConflict):
            handle.record()
        with self.store.transaction() as recovery:
            recovery.advance('ABORTED', verify=verified)
            recovery.clear_finished(verified)

    def test_verifier_cannot_rebind_nested_intent_or_evidence(self):
        with self.store.transaction(ADOPT) as handle:
            evidence = dict(ADOPT_EVIDENCE)
            before = self.path.read_bytes()

            def change_input(proposal):
                proposal['intent']['power'] = 'enable'
                proposal['evidence']['agent_version'] = '0.0.0'
                evidence['agent_version'] = '0.0.1'
                return True

            with self.assertRaises(old.JournalConflict):
                handle.advance('STAGED', evidence=evidence, verify=change_input)
            self.assertEqual(self.path.read_bytes(), before)

            def change_copy(proposal):
                proposal['intent']['power'] = 'enable'
                return True

            handle.advance('STAGED', evidence=ADOPT_EVIDENCE, verify=change_copy)
            self.assertEqual(handle.record()['intent'], ADOPT)

    def test_failed_replace_preserves_old_record_and_uncertainty(self):
        with self.store.transaction(ADOPT) as handle:
            before = self.path.read_bytes()
            with mock.patch.object(v2.os, 'replace', side_effect=OSError('fixture')):
                with self.assertRaises(old.UnsafeJournal):
                    handle.advance('STAGED', evidence=ADOPT_EVIDENCE, verify=verified)
            self.assertEqual(self.path.read_bytes(), before)
            with self.assertRaises(old.JournalConflict):
                handle.record()
        leftovers = list(self.path.parent.glob('.wizard-journal-*'))
        self.assertEqual(len(leftovers), 1)
        with self.assertRaises(old.JournalConflict):
            with self.store.transaction():
                self.fail('uncertain record accepted')
        self.assertTrue(leftovers[0].exists())
        self.assertEqual(self.path.read_bytes(), before)

    def test_reconcile_complete_temp_never_promotes_candidate(self):
        with self.store.transaction(ADOPT) as handle:
            before = self.path.read_bytes()
            with mock.patch.object(v2.os, 'replace', side_effect=OSError('fixture')):
                with self.assertRaises(old.UnsafeJournal):
                    handle.advance('STAGED', evidence=ADOPT_EVIDENCE, verify=verified)
        temp, = self.path.parent.glob('.wizard-journal-*')
        pending = temp.read_bytes()
        with self.assertRaises(old.JournalConflict):
            self.store.reconcile_complete_temp(lambda *_: False)
        self.assertEqual(temp.read_bytes(), pending)
        self.store.reconcile_complete_temp(
            lambda current, candidate: current['phase'] == 'INSPECTED' and
            candidate['phase'] == 'STAGED')
        self.assertFalse(temp.exists())
        self.assertEqual(self.path.read_bytes(), before)
        with self.store.transaction() as handle:
            handle.advance('ABORTED', verify=verified)
            handle.clear_finished(verified)

    def test_orphan_initial_write_requires_complete_record_and_no_stage(self):
        with mock.patch.object(v2.os, 'replace', side_effect=OSError('fixture')):
            with self.assertRaises(old.UnsafeJournal):
                with self.store.transaction(ADOPT):
                    self.fail('uncertain initial record returned a handle')
        temp, = self.path.parent.glob('.wizard-journal-*')
        raw = temp.read_bytes()
        temp.write_bytes(raw[:20])
        with self.assertRaises(old.UnsafeJournal):
            self.store.reconcile_complete_temp(lambda *_: True)
        self.assertEqual(temp.read_bytes(), raw[:20])
        temp.write_bytes(raw)
        self.store.reconcile_complete_temp(
            lambda current, candidate: current is None and candidate['phase'] == 'INSPECTED')
        self.assertFalse(temp.exists())
        self.assertFalse(self.path.exists())

    def test_conflicting_temp_is_preserved(self):
        with self.store.transaction(ADOPT) as handle:
            current = handle.record()
        temp = self.path.parent / ('.wizard-journal-' + 'f' * 32)
        raw = v2.canonical(dict(current, transaction_id='b' * 32))
        temp.write_bytes(raw)
        temp.chmod(0o600)
        with self.assertRaises(old.UnsafeJournal):
            self.store.reconcile_complete_temp(lambda *_: True)
        self.assertEqual(temp.read_bytes(), raw)

    def test_partial_transition_prefixes_reconcile_without_promotion(self):
        # Exercise empty, intermediate, and all-but-newline writes.
        for length in (0, 1, 20, -1):
            with self.subTest(length=length):
                with self.store.transaction(ADOPT) as handle:
                    current = handle.record()
                    candidate = dict(current, phase='STAGED', evidence=ADOPT_EVIDENCE)
                    before = self.path.read_bytes()
                temp = self.path.parent / ('.wizard-journal-' + 'a' * 32)
                raw = v2.canonical(candidate)[:length]
                temp.write_bytes(raw)
                temp.chmod(0o600)
                with self.assertRaises(old.JournalConflict):
                    self.store.reconcile_partial_temp(candidate, lambda *_: False)
                self.assertEqual(temp.read_bytes(), raw)
                self.store.reconcile_partial_temp(candidate, lambda durable, proposed:
                                                  durable == current and proposed == candidate)
                self.assertEqual(self.path.read_bytes(), before)
                self.assertFalse(temp.exists())
                with self.store.transaction() as recovery:
                    recovery.advance('ABORTED', verify=verified)
                    recovery.clear_finished(verified)

    def test_partial_wrong_prefix_or_transition_preserved(self):
        with self.store.transaction(ADOPT) as handle:
            current = handle.record()
        candidate = dict(current, phase='STAGED', evidence=ADOPT_EVIDENCE)
        temp = self.path.parent / ('.wizard-journal-' + 'b' * 32)
        temp.write_bytes(b'{"unexpected":')
        temp.chmod(0o600)
        with self.assertRaises(old.JournalConflict):
            self.store.reconcile_partial_temp(candidate, lambda *_: True)
        self.assertEqual(temp.read_bytes(), b'{"unexpected":')
        raw = v2.canonical(candidate)[:20]
        temp.write_bytes(raw)
        conflicting = dict(candidate, transaction_id='b' * 32)
        with self.assertRaises(old.UnsafeJournal):
            self.store.reconcile_partial_temp(conflicting, lambda *_: True)
        self.assertEqual(temp.read_bytes(), raw)
        temp.write_bytes(v2.canonical(candidate))
        with self.assertRaises(old.JournalConflict):
            self.store.reconcile_partial_temp(candidate, lambda *_: True)
        self.assertEqual(temp.read_bytes(), v2.canonical(candidate))

    def test_partial_orphan_is_not_identifiable(self):
        with mock.patch.object(v2.os, 'replace', side_effect=OSError('fixture')):
            with self.assertRaises(old.UnsafeJournal):
                with self.store.transaction(ADOPT):
                    self.fail('unexpected handle')
        temp, = self.path.parent.glob('.wizard-journal-*')
        candidate = v2.contract.decode_journal(temp.read_bytes())
        for raw in (b'', v2.canonical(candidate)[:-1]):
            temp.write_bytes(raw)
            with self.assertRaises(old.JournalConflict):
                self.store.reconcile_partial_temp(candidate, lambda *_: True)
            self.assertEqual(temp.read_bytes(), raw)
            self.assertFalse(self.path.exists())

    def test_partial_commit_reconciliation_still_requires_rollback(self):
        with self.store.transaction(ADOPT) as handle:
            handle.advance('STAGED', evidence=ADOPT_EVIDENCE, verify=verified)
            handle.advance('SNAPSHOTTED', snapshot_name=BEFORE,
                           before_receipt_sha256=H, verify=verified)
            for phase in ('APPLYING', 'ACTIVATING', 'VERIFYING'):
                handle.advance(phase, verify=verified)
            durable = handle.record()
        candidate = dict(durable, phase='COMMITTED')
        temp = self.path.parent / ('.wizard-journal-' + 'c' * 32)
        temp.write_bytes(v2.canonical(candidate)[:-1])
        temp.chmod(0o600)
        self.store.reconcile_partial_temp(candidate, lambda *_: True)
        with self.store.transaction() as recovery:
            self.assertEqual(recovery.record(), durable)
            with self.assertRaises(old.JournalConflict):
                recovery.advance('COMMITTED', verify=verified)
            recovery.advance('ROLLED_BACK', verify=verified)
            recovery.clear_finished(verified)

    def test_failed_directory_sync_poisoned_handle_new_record_preserved(self):
        with self.store.transaction(ADOPT) as handle:
            real_sync = os.fsync
            def sync(fd):
                if os.path.samestat(os.fstat(fd), self.path.parent.stat()):
                    raise OSError('fixture directory sync')
                real_sync(fd)
            with mock.patch.object(v2.os, 'fsync', side_effect=sync):
                with self.assertRaises(old.UnsafeJournal):
                    handle.advance('STAGED', evidence=ADOPT_EVIDENCE, verify=verified)
            with self.assertRaises(old.JournalConflict):
                handle.record()
        with self.store.transaction() as recovered:
            self.assertEqual(recovered.record()['phase'], 'STAGED')
            recovered.advance('ABORTED', verify=verified)
            recovered.clear_finished(verified)

    def test_legacy_record_never_overwritten_or_recovered(self):
        with self.old.begin('install'):
            pass
        before = self.path.read_bytes()
        for intent in (None, ADOPT):
            with self.assertRaises(old.JournalConflict):
                with self.store.transaction(intent):
                    self.fail('legacy journal accepted for mutation')
            self.assertEqual(self.path.read_bytes(), before)

    def test_unsafe_journal_and_live_root_refused(self):
        with self.assertRaises(old.JournalConflict):
            v2.FixtureJournal(Path('/'))
        with self.store.transaction(ADOPT):
            pass
        self.path.chmod(0o644)
        with self.assertRaises(old.UnsafeJournal):
            with self.store.transaction():
                self.fail('unsafe journal accepted')
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o644)

if __name__ == '__main__':
    unittest.main()
