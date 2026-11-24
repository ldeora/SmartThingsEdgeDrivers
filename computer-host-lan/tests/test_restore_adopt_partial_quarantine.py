"""Shared partial receipt recovery tests for both fixture quarantine paths."""
import os
import unittest
from unittest import mock

import test_restore_adopt_quarantine as unbound
import test_restore_adopt_stage_quarantine as corrupt
import restore_adopt_quarantine as q

ADOPT = unbound.ADOPT
before = unbound.before
old = unbound.old


class PartialReceiptCases:
    def interrupted(self, handle, length):
        source = self.prepare_source(handle)
        dest, receipt = self.locations(handle)
        real_write = os.write
        original = before.storage._write_file
        captured = []

        def write_file(fd, name, content, digest, uid):
            captured.append(content)
            calls = []
            def short_write(target, raw):
                if not calls and length:
                    calls.append(True)
                    count = len(raw) - 1 if length == -1 else length
                    return real_write(target, raw[:count])
                raise OSError('injected short receipt write')
            with mock.patch.object(os, 'write', side_effect=short_write):
                return original(fd, name, content, digest, uid)

        with mock.patch.object(before.storage, '_write_file', side_effect=write_file):
            with self.assertRaises(before.BeforeStateError):
                self.move(handle)
        expected, = captured
        prefix = expected[:length] if length != -1 else expected[:-1]
        self.assertEqual(receipt.read_bytes(), prefix)
        self.assertTrue(source.exists())
        self.assertFalse(dest.exists())
        with self.assertRaises(old.JournalConflict):
            handle.record()
        return source, dest, receipt, expected

    def test_prefix_reconciliation_keeps_inode_and_does_not_move(self):
        for length in (0, 17, -1):
            with self.subTest(length=length):
                with self.store.transaction(ADOPT) as handle:
                    source, dest, receipt, expected = self.interrupted(handle, length)
                inode = receipt.stat().st_ino
                prefix = receipt.read_bytes()
                with self.store.transaction() as handle:
                    with self.assertRaises(before.BeforeStateError):
                        self.move(handle)
                    self.assertEqual(self.reconcile(handle), 'receipt_completed')
                    self.assertEqual(receipt.read_bytes(), expected)
                    self.assertEqual(receipt.stat().st_ino, inode)
                    self.assertTrue(expected.startswith(prefix))
                    self.assertTrue(source.exists())
                    self.assertFalse(dest.exists())
                    self.assertFalse(handle._stage_retirement_verified)
                    with self.assertRaises(before.BeforeStateError):
                        self.reconcile(handle)
                    self.assertEqual(self.move(handle), 'quarantined')
                    self.finish(handle)
                self.assertTrue(dest.exists())

    def test_reconciliation_refuses_mismatch_and_verifier_refusal(self):
        with self.store.transaction(ADOPT) as handle:
            source, dest, receipt, expected = self.interrupted(handle, 17)
        prefix = receipt.read_bytes()
        with self.store.transaction() as handle:
            with self.assertRaises(before.BeforeStateError):
                self.reconcile(handle, lambda _: False)
            self.assertEqual(receipt.read_bytes(), prefix)
            receipt.write_bytes(b'wrong')
            verifier = mock.Mock(return_value=True)
            with self.assertRaises(before.BeforeStateError):
                self.reconcile(handle, verifier)
            verifier.assert_not_called()
            self.assertEqual(receipt.read_bytes(), b'wrong')
            self.assertTrue(source.exists())
            self.assertFalse(dest.exists())

    def test_reconciliation_refuses_verifier_time_receipt_replacement(self):
        with self.store.transaction(ADOPT) as handle:
            source, dest, receipt, expected = self.interrupted(handle, 17)
        prefix = receipt.read_bytes()
        with self.store.transaction() as handle:
            def replace(_):
                receipt.rename(receipt.with_suffix('.saved'))
                receipt.write_bytes(prefix)
                receipt.chmod(0o600)
                return True
            with self.assertRaises(before.BeforeStateError):
                self.reconcile(handle, replace)
            self.assertEqual(receipt.read_bytes(), prefix)
            self.assertTrue(source.exists())
            self.assertFalse(dest.exists())

    def test_reconciliation_refuses_destination_only_and_unsafe_receipt(self):
        with self.store.transaction(ADOPT) as handle:
            source, dest, receipt, expected = self.interrupted(handle, 17)
        with self.store.transaction() as handle:
            link = self.root / 'receipt-link'
            os.link(receipt, link)
            with self.assertRaises(before.BeforeStateError):
                self.reconcile(handle)
            link.unlink()
            source.rename(dest)
            with self.assertRaises(before.BeforeStateError):
                self.reconcile(handle)
            self.assertEqual(receipt.read_bytes(), expected[:17])
            self.assertTrue(dest.exists())

    def test_append_interruption_requires_new_handle_and_can_retry(self):
        with self.store.transaction(ADOPT) as handle:
            source, dest, receipt, expected = self.interrupted(handle, 17)
        real_write = os.write
        calls = []
        def short_write(fd, raw):
            if not calls:
                calls.append(True)
                return real_write(fd, raw[:9])
            raise OSError('injected interrupted append')
        with self.store.transaction() as handle:
            with mock.patch.object(os, 'write', side_effect=short_write):
                with self.assertRaises(before.BeforeStateError):
                    self.reconcile(handle)
            self.assertEqual(receipt.read_bytes(), expected[:26])
            with self.assertRaises(old.JournalConflict):
                handle.record()
        with self.store.transaction() as handle:
            self.assertEqual(self.reconcile(handle), 'receipt_completed')
            self.assertEqual(receipt.read_bytes(), expected)
            self.assertTrue(source.exists())
            self.assertFalse(dest.exists())
            self.assertEqual(self.move(handle), 'quarantined')
            self.finish(handle)


    def test_completed_append_sync_failure_uses_normal_retry(self):
        with self.store.transaction(ADOPT) as handle:
            source, dest, receipt, expected = self.interrupted(handle, 17)
        identity = receipt.stat()
        real_sync = os.fsync

        def sync(fd):
            info = os.fstat(fd)
            if os.path.samestat(info, identity) and info.st_size == len(expected):
                raise OSError('injected completed receipt fsync failure')
            return real_sync(fd)

        with self.store.transaction() as handle:
            with mock.patch.object(os, 'fsync', side_effect=sync):
                with self.assertRaises(before.BeforeStateError):
                    self.reconcile(handle)
            self.assertEqual(receipt.read_bytes(), expected)
            self.assertTrue(source.exists())
            self.assertFalse(dest.exists())
            with self.assertRaises(old.JournalConflict):
                handle.record()
        with self.store.transaction() as handle:
            with self.assertRaises(before.BeforeStateError):
                self.reconcile(handle)
            self.assertEqual(self.move(handle), 'quarantined')
            self.finish(handle)

    def test_missing_receipt_and_forward_handle_refused(self):
        with self.store.transaction(ADOPT) as handle:
            source = self.prepare_source(handle)
            dest, receipt = self.locations(handle)
            verifier = mock.Mock(return_value=True)
            with self.assertRaises(before.BeforeStateError):
                self.reconcile(handle, verifier)
            verifier.assert_not_called()
            self.assertFalse(receipt.exists())
        with self.store.transaction() as handle:
            verifier = mock.Mock(return_value=True)
            with self.assertRaises(before.BeforeStateError):
                self.reconcile(handle, verifier)
            verifier.assert_not_called()
            self.assertTrue(source.exists())
            self.assertFalse(receipt.exists())
            self.assertFalse(dest.exists())


class UnboundPartialReceiptTests(PartialReceiptCases, unittest.TestCase):
    setUp = unbound.UnboundQuarantineTests.setUp
    prepare = unbound.UnboundQuarantineTests.prepare
    prepare_source = unbound.UnboundQuarantineTests.prepare_unbound
    locations = unbound.UnboundQuarantineTests.locations
    move = unbound.UnboundQuarantineTests.move

    def reconcile(self, handle, verify=lambda _: True):
        return q.quarantine_unbound_before(handle, confirmation='RECONCILE_RECEIPT',
                                           verify=verify)

    def finish(self, handle):
        before.stage.retire_terminal_plan(handle)
        handle.clear_finished(lambda _: True)


class StagePartialReceiptTests(PartialReceiptCases, unittest.TestCase):
    setUp = corrupt.StageQuarantineTests.setUp
    prepare_source = corrupt.StageQuarantineTests.ready
    locations = corrupt.StageQuarantineTests.locations
    move = corrupt.StageQuarantineTests.move

    def reconcile(self, handle, verify=lambda _: True):
        return corrupt.quarantine.quarantine_corrupt_stage(
            handle, confirmation='RECONCILE_RECEIPT', verify=verify)

    def finish(self, handle):
        handle.clear_finished(lambda _: True)

    def test_completed_receipt_still_blocks_cleanup(self):
        with self.store.transaction(ADOPT) as handle:
            source, dest, receipt, expected = self.interrupted(handle, 17)
        with self.store.transaction() as handle:
            self.assertEqual(self.reconcile(handle), 'receipt_completed')
            with self.assertRaises(before.stage.PlanError):
                before.stage.retire_terminal_plan(handle)
            with self.assertRaises(old.JournalConflict):
                handle.clear_finished(lambda _: True)
            self.assertTrue(source.exists())
            self.assertFalse(dest.exists())
            self.assertEqual(receipt.read_bytes(), expected)
