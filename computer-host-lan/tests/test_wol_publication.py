"""Filesystem-only tests. No live systemd, networking or privileged calls."""
import errno
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import wol_publication as pub

TX = 'a' * 32
OTHER = 'b' * 32


class WolPublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.policy = self.root / 'existing.link.d'
        self.private = self.root / 'private'
        self.policy.mkdir(mode=0o755)
        self.private.mkdir(mode=0o700)
        self.uid = os.geteuid()
        self.policy_fd = self.open_directory(self.policy)
        self.private_fd = self.open_directory(self.private)
        self.anchor = self.policy / ('.computer-host-wol-' + TX + '.stage')
        self.receipt = self.private / ('wol-' + TX + '.json')
        self.target = self.policy / pub.TARGET

    def open_directory(self, path):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.addCleanup(os.close, fd)
        return fd

    def invoke(self, function, txid=TX, *, policy_fd=None, private_fd=None):
        return function(self.policy_fd if policy_fd is None else policy_fd,
                        self.private_fd if private_fd is None else private_fd,
                        txid, owner_uid=self.uid)

    def prepare(self):
        self.invoke(pub.prepare)

    def publish(self):
        self.invoke(pub.publish)

    def rollback(self):
        self.invoke(pub.rollback)

    def state(self):
        return self.invoke(pub.inspect)

    def assert_absent(self, path):
        self.assertFalse(os.path.lexists(path))

    def test_prepare_records_durable_anchor_without_visible_policy(self):
        self.prepare()
        self.assert_absent(self.target)
        self.assertEqual(self.anchor.read_bytes(), pub.CONTENT)
        self.assertEqual(stat.S_IMODE(self.anchor.stat().st_mode), 0o644)
        self.assertEqual(stat.S_IMODE(self.receipt.stat().st_mode), 0o600)
        self.assertEqual(self.anchor.stat().st_nlink, 1)
        record = json.loads(self.receipt.read_bytes())
        self.assertEqual(record['anchor'],
                         [self.anchor.stat().st_dev, self.anchor.stat().st_ino])
        self.assertEqual(self.state(), 'unpublished')
        self.assertEqual(list(self.policy.iterdir()), [self.anchor])

    def test_publish_and_idempotent_rollback_keep_evidence(self):
        self.prepare()
        self.publish()
        self.assertEqual(self.state(), 'published')
        self.assertTrue(os.path.samefile(self.anchor, self.target))
        self.assertEqual(self.target.stat().st_nlink, 2)
        self.rollback()
        self.rollback()
        self.assertEqual(self.state(), 'unpublished')
        self.assert_absent(self.target)
        self.assertTrue(self.receipt.is_file())
        self.assertTrue(self.anchor.is_file())

    def test_rollback_before_publication_does_not_remove_unrelated_files(self):
        self.prepare()
        unrelated = self.policy / 'unrelated.txt'
        unrelated.write_bytes(b'keep')
        self.rollback()
        self.assertEqual(unrelated.read_bytes(), b'keep')
        self.assert_absent(self.target)

    def test_existing_target_even_identical_is_not_owned(self):
        for content in (pub.CONTENT, b'operator rule'):
            with self.subTest(content=content):
                self.target.write_bytes(content)
                with self.assertRaises(pub.PublicationError):
                    self.prepare()
                self.assertEqual(self.target.read_bytes(), content)
                self.assert_absent(self.anchor)
                self.assert_absent(self.receipt)
                self.target.unlink()

    def test_preexisting_dangling_target_is_never_followed(self):
        self.target.symlink_to(self.root / 'missing')
        with self.assertRaises(pub.PublicationError):
            self.prepare()
        self.assertTrue(self.target.is_symlink())
        self.assert_absent(self.anchor)

    def test_concurrent_identical_file_after_prepare_not_owned(self):
        self.prepare()
        self.target.write_bytes(pub.CONTENT)
        self.target.chmod(0o644)
        for action in (pub.inspect, pub.publish, pub.rollback):
            with self.subTest(action=action.__name__):
                with self.assertRaises(pub.PublicationError):
                    self.invoke(action)
        self.assertEqual(self.target.read_bytes(), pub.CONTENT)
        self.assertFalse(os.path.samefile(self.anchor, self.target))

    def test_atomic_no_clobber_race_at_link(self):
        self.prepare()
        real_link = os.link

        def racing_link(*args, **kwargs):
            self.target.write_bytes(pub.CONTENT)
            self.target.chmod(0o644)
            return real_link(*args, **kwargs)

        with mock.patch.object(pub.os, 'link', side_effect=racing_link):
            with self.assertRaises(FileExistsError):
                self.publish()
        self.assertFalse(os.path.samefile(self.anchor, self.target))
        with self.assertRaises(pub.PublicationError):
            self.rollback()
        self.assertEqual(self.target.read_bytes(), pub.CONTENT)

    def test_modified_owned_file_is_not_removed(self):
        self.prepare()
        self.publish()
        self.target.write_bytes(b'operator modified')
        with self.assertRaises(pub.PublicationError):
            self.rollback()
        self.assertEqual(self.target.read_bytes(), b'operator modified')
        self.assertTrue(self.receipt.exists())

    def test_replaced_target_even_identical_is_not_removed(self):
        self.prepare()
        self.publish()
        self.target.unlink()
        self.target.write_bytes(pub.CONTENT)
        self.target.chmod(0o644)
        with self.assertRaises(pub.PublicationError):
            self.rollback()
        self.assertFalse(os.path.samefile(self.anchor, self.target))
        self.assertTrue(self.target.exists())

    def test_missing_anchor_blocks_recovery_even_when_target_exists(self):
        self.prepare()
        self.publish()
        self.anchor.unlink()
        with self.assertRaises(FileNotFoundError):
            self.rollback()
        self.assertEqual(self.target.read_bytes(), pub.CONTENT)

    def test_extra_hardlink_blocks_recovery(self):
        self.prepare()
        self.publish()
        extra = self.root / 'extra'
        os.link(self.target, extra)
        with self.assertRaises(pub.PublicationError):
            self.rollback()
        self.assertTrue(self.target.exists())
        self.assertTrue(extra.exists())

    def test_symlinked_anchor_or_receipt_is_never_followed(self):
        self.prepare()
        self.anchor.unlink()
        self.anchor.symlink_to(self.root / 'missing')
        with self.assertRaises(OSError):
            self.publish()
        self.assert_absent(self.target)
        self.receipt.unlink()
        self.receipt.symlink_to(self.root / 'missing')
        with self.assertRaises(OSError):
            self.rollback()

    def test_directory_identity_binding_prevents_transplant(self):
        self.prepare()
        other = self.root / 'different.link.d'
        other.mkdir()
        os.link(self.anchor, other / self.anchor.name)
        other_fd = self.open_directory(other)
        with self.assertRaises(pub.PublicationError):
            self.invoke(pub.publish, policy_fd=other_fd)
        self.assert_absent(other / pub.TARGET)

    def test_unsafe_directories_and_overlapping_receipt_directory(self):
        self.policy.chmod(0o777)
        with self.assertRaises(pub.PublicationError):
            self.prepare()
        self.policy.chmod(0o700)
        self.private.chmod(0o755)
        with self.assertRaises(pub.PublicationError):
            self.prepare()
        self.private.chmod(0o700)
        with self.assertRaises(pub.PublicationError):
            self.invoke(pub.prepare, private_fd=self.policy_fd)
        self.assert_absent(self.anchor)

    def test_transaction_names_are_strict(self):
        for tx in ('../outside', '', 'a' * 31, 'A' * 32, None):
            with self.subTest(tx=tx):
                with self.assertRaises(pub.PublicationError):
                    self.invoke(pub.prepare, tx)
        self.assertEqual(list(self.policy.iterdir()), [])

    def test_duplicate_prepare_or_publish_does_not_overwrite(self):
        self.prepare()
        before = self.receipt.read_bytes()
        with self.assertRaises(pub.PublicationError):
            self.prepare()
        self.publish()
        with self.assertRaises(pub.PublicationError):
            self.publish()
        self.assertEqual(self.receipt.read_bytes(), before)
        self.assertEqual(self.state(), 'published')

    def test_invalid_receipt_fields_never_authorize_publication(self):
        self.prepare()
        original = json.loads(self.receipt.read_bytes())
        for changed in (dict(original, schema=True),
                        dict(original, transaction_id=OTHER),
                        dict(original, anchor=[True, 1]),
                        dict(original, anchor_gid=-1),
                        dict(original, target='/unexpected'),
                        dict(original, policy_directory=[1, 1])):
            with self.subTest(changed=changed):
                self.receipt.write_text(json.dumps(changed))
                with self.assertRaises(pub.PublicationError):
                    self.publish()
                self.assert_absent(self.target)
        self.receipt.write_text('{"schema":1,"schema":1}')
        with self.assertRaises(pub.PublicationError):
            self.publish()
        self.assert_absent(self.target)

    def test_missing_receipt_does_not_adopt_anchor(self):
        self.prepare()
        self.receipt.unlink()
        with self.assertRaises(FileNotFoundError):
            self.publish()
        with self.assertRaises(pub.PublicationError):
            self.prepare()
        self.assert_absent(self.target)
        self.assertTrue(self.anchor.exists())

    def test_failure_at_each_prepare_fsync_never_publishes(self):
        # First two fsyncs: anchor file and policy directory.
        # Next two: receipt file and private directory.
        real_sync = os.fsync
        for n in range(1, 5):
            with self.subTest(fsync=n):
                tx = format(n, '032x')
                count = 0
                def fail(fd):
                    nonlocal count
                    count += 1
                    if count == n:
                        raise OSError(errno.EIO, 'fixture')
                    return real_sync(fd)
                with mock.patch.object(pub.os, 'fsync', side_effect=fail):
                    with self.assertRaises(OSError):
                        self.invoke(pub.prepare, tx)
                self.assert_absent(self.target)

    def test_failed_link_leaves_unpublished_anchor(self):
        self.prepare()
        with mock.patch.object(pub.os, 'link', side_effect=OSError(errno.EXDEV, 'fixture')):
            with self.assertRaises(OSError):
                self.publish()
        self.assertEqual(self.state(), 'unpublished')
        self.rollback()
        self.assert_absent(self.target)

    def test_crash_after_link_before_directory_sync_is_recoverable(self):
        self.prepare()
        with mock.patch.object(pub.os, 'fsync', side_effect=OSError(errno.EIO, 'fixture')):
            with self.assertRaises(OSError):
                self.publish()
        self.assertEqual(self.state(), 'published')
        self.rollback()
        self.assertEqual(self.state(), 'unpublished')

    def test_crash_after_unlink_before_sync_can_retry_rollback(self):
        self.prepare()
        self.publish()
        with mock.patch.object(pub.os, 'fsync', side_effect=OSError(errno.EIO, 'fixture')):
            with self.assertRaises(OSError):
                self.rollback()
        self.assertEqual(self.state(), 'unpublished')
        self.rollback()
        self.assert_absent(self.target)

    def test_reopen_descriptors_recovers_published_target(self):
        self.prepare()
        self.publish()
        with mock.patch.object(pub.os, 'link', side_effect=AssertionError('no forward replay')):
            self.invoke(pub.rollback, policy_fd=self.open_directory(self.policy),
                        private_fd=self.open_directory(self.private))
        self.assertEqual(self.state(), 'unpublished')


if __name__ == '__main__':
    unittest.main()
