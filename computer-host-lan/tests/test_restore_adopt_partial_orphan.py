"""Narrow missing-newline orphan recovery, not arbitrary prefix deletion."""
import os
import unittest
from unittest import mock

import test_restore_adopt_journal as fixtures
from test_restore_adopt_contract import ADOPT, RESTORE, initial, stages

v2 = fixtures.v2
old = fixtures.old


class PartialOrphanTests(unittest.TestCase):
    setUp = fixtures.JournalTests.setUp

    def interrupted(self, intent=ADOPT):
        write = os.write
        calls = []
        def short(fd, data):
            if not calls:
                calls.append(True)
                return write(fd, data[:-1])
            raise OSError('injected missing final newline')
        with mock.patch.object(v2.os, 'write', side_effect=short):
            with self.assertRaises(old.UnsafeJournal):
                with self.store.transaction(intent):
                    self.fail('unexpected transaction handle')
        temp, = self.path.parent.glob('.wizard-journal-*')
        return temp

    def reconcile(self, verify=lambda *_: True):
        return self.store.reconcile_partial_orphan_temp(
            confirmation='RECONCILE_ORPHAN', verify=verify)

    def test_real_short_write_both_operations_no_promotion(self):
        for intent in (ADOPT, RESTORE):
            with self.subTest(action=intent['action']):
                temp = self.interrupted(intent)
                raw = temp.read_bytes()
                record = v2.contract.decode_journal(raw)
                self.assertEqual(v2.canonical(record), raw + b'\n')
                self.assertEqual(record['intent'], intent)
                with self.assertRaises(old.JournalConflict):
                    self.reconcile(lambda *_: False)
                self.assertEqual(temp.read_bytes(), raw)
                verifier = mock.Mock(return_value=True)
                self.assertIsNone(self.reconcile(verifier))
                verifier.assert_called_once_with(None, record)
                self.assertFalse(temp.exists())
                self.assertFalse(self.path.exists())
                with self.store.transaction(intent) as handle:
                    self.assertNotEqual(handle.record()['transaction_id'], record['transaction_id'])
                    handle.advance('ABORTED', verify=lambda _: True)
                    handle.clear_finished(lambda _: True)

    def test_shorter_prefixes_and_complete_records_preserved(self):
        temp = self.interrupted()
        raw = temp.read_bytes()
        verifier = mock.Mock(return_value=True)
        for data in (b'', raw[:1], raw[:20], raw[:-1], raw + b'\n', b' ' + raw):
            with self.subTest(length=len(data)):
                temp.write_bytes(data)
                with self.assertRaises(old.JournalError):
                    self.reconcile(verifier)
                self.assertEqual(temp.read_bytes(), data)
                self.assertFalse(self.path.exists())
        verifier.assert_not_called()
        temp.write_bytes(raw + b'\n')
        self.store.reconcile_complete_temp(lambda *_: True)
        self.assertFalse(temp.exists())

    def test_legacy_unknown_schema_and_noninitial_v2_refused(self):
        temp = self.interrupted()
        legacy = dict(schema=1, transaction_id='a'*32, operation='install',
                      phase='INSPECTED', snapshot_name=None)
        candidates = [legacy, dict(initial(ADOPT), schema=3),
                      *stages(ADOPT)[1:], dict(initial(ADOPT), phase='ABORTED')]
        verifier = mock.Mock(return_value=True)
        for candidate in candidates:
            with self.subTest(schema=candidate['schema'], phase=candidate['phase']):
                raw = v2.canonical(candidate)[:-1]
                temp.write_bytes(raw)
                with self.assertRaises(old.JournalError):
                    self.reconcile(verifier)
                self.assertEqual(temp.read_bytes(), raw)
        verifier.assert_not_called()

    def test_confirmation_and_durable_predecessor_refused(self):
        temp = self.interrupted()
        raw = temp.read_bytes()
        verifier = mock.Mock(return_value=True)
        with self.assertRaises(old.JournalConflict):
            self.store.reconcile_partial_orphan_temp(confirmation='NO', verify=verifier)
        self.path.write_bytes(raw + b'\n')
        self.path.chmod(0o600)
        with self.assertRaises(old.JournalConflict):
            self.reconcile(verifier)
        verifier.assert_not_called()
        self.assertEqual(temp.read_bytes(), raw)
        self.assertEqual(self.path.read_bytes(), raw + b'\n')

    def test_stage_before_or_during_verification_blocks_discard(self):
        temp = self.interrupted()
        raw = temp.read_bytes()
        stage = self.root / 'var/lib/computer-host-installer/staging'
        stage.mkdir(parents=True, mode=0o700)
        stage.parent.chmod(0o700)
        foreign = stage / 'ready-plan-foreign'
        foreign.mkdir(mode=0o700)
        verifier = mock.Mock(return_value=True)
        with self.assertRaises(old.JournalConflict):
            self.reconcile(verifier)
        verifier.assert_not_called()
        foreign.rmdir()
        def add_stage(*_):
            foreign.mkdir(mode=0o700)
            return True
        with self.assertRaises(old.JournalConflict):
            self.reconcile(add_stage)
        self.assertEqual(temp.read_bytes(), raw)
        self.assertTrue(foreign.exists())

    def test_temp_identity_change_and_multiple_entries_refused(self):
        temp = self.interrupted()
        raw = temp.read_bytes()
        extra = temp.with_name('.wizard-journal-' + 'f'*32)
        extra.write_bytes(raw)
        extra.chmod(0o600)
        verifier = mock.Mock(return_value=True)
        with self.assertRaises(old.JournalConflict):
            self.reconcile(verifier)
        verifier.assert_not_called()
        extra.unlink()
        def replace(*_):
            temp.rename(extra)
            temp.write_bytes(raw)
            temp.chmod(0o600)
            extra.unlink()
            return True
        with self.assertRaises(old.JournalConflict):
            self.reconcile(replace)
        self.assertEqual(temp.read_bytes(), raw)
        self.assertFalse(self.path.exists())

    def test_unsafe_hardlink_preserved(self):
        temp = self.interrupted()
        raw = temp.read_bytes()
        link = self.root / 'alias'
        os.link(temp, link)
        verifier = mock.Mock(return_value=True)
        with self.assertRaises(old.UnsafeJournal):
            self.reconcile(verifier)
        verifier.assert_not_called()
        self.assertEqual(temp.read_bytes(), raw)
        self.assertTrue(link.exists())

    def test_presync_failure_preserves_bytes(self):
        temp = self.interrupted()
        raw = temp.read_bytes()
        with mock.patch.object(v2, '_sync_ancestors', side_effect=OSError('injected')):
            with self.assertRaises(old.UnsafeJournal):
                self.reconcile()
        self.assertEqual(temp.read_bytes(), raw)
        self.assertFalse(self.path.exists())
        self.reconcile()
        self.assertFalse(temp.exists())

    def test_change_during_sync_is_refused(self):
        temp = self.interrupted()
        raw = temp.read_bytes()
        sync = v2._sync_ancestors
        def change(root, uid):
            sync(root, uid)
            temp.write_bytes(raw + b'\n')
        with mock.patch.object(v2, '_sync_ancestors', side_effect=change):
            with self.assertRaises(old.JournalConflict):
                self.reconcile()
        self.assertEqual(temp.read_bytes(), raw + b'\n')
        self.assertFalse(self.path.exists())
