"""Non-root filesystem fixtures for data-only Linux payload staging.

No sudo, systemd calls, agent execution, actual /var writes or hardware access.
"""
from __future__ import annotations

import fcntl
import hashlib
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
import payload_staging as staging


class PayloadStagingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / 'untrusted-source'
        self.source.mkdir()
        self.dest = self.root / 'var/lib/computer-host-installer/staging'
        self.contents: dict[str, bytes] = {}
        self.expected: dict[str, str] = {}
        for name in sorted(staging.PAYLOAD_FILES):
            data = ('trusted fixture bytes: ' + name).encode('utf-8')
            self.contents[name] = data
            self.expected[name] = hashlib.sha256(data).hexdigest()
            target = self.source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        self.expected_uid = os.geteuid()

    def stage(self, *, source=None, expected=None):
        return staging.stage_payload(
            source or self.source,
            self.expected if expected is None else expected,
            root=self.root,
            owner_uid=self.expected_uid,
        )

    def stage_files(self):
        pending = list(self.dest.glob('pending-*'))
        ready = list(self.dest.glob('ready-*'))
        return pending, ready

    def test_all_allowlisted_files_staged_privately_and_verified(self):
        with self.stage() as receipt:
            pending, ready = self.stage_files()
            self.assertFalse(pending)
            self.assertEqual(len(ready), 1)
            self.assertEqual(stat.S_IMODE(ready[0].stat().st_mode), 0o700)
            for name, data in self.contents.items():
                staged = ready[0] / name
                self.assertEqual(staged.read_bytes(), data)
                self.assertEqual(stat.S_IMODE(staged.stat().st_mode), 0o600)
            self.assertTrue(receipt.directory_fd >= 0)
            self.assertEqual(os.fstat(receipt.directory_fd).st_ino,
                             ready[0].stat().st_ino)
        with self.assertRaises(staging.StagingError):
            _ = receipt.directory_fd
        self.assertEqual(stat.S_IMODE((self.dest / 'stage.lock').stat().st_mode), 0o600)

    def test_manifest_mismatch_rejected_before_root_destination_write(self):
        invalid = dict(self.expected)
        name = sorted(invalid)[0]
        invalid[name] = '0' * 64
        with self.assertRaises(staging.StagingError):
            self.stage(expected=invalid)
        self.assertFalse((self.root / 'var').exists())

    def test_manifest_must_have_exact_allowlist_and_valid_digest(self):
        cases = [
            {},
            {k: v for k, v in self.expected.items() if k != sorted(self.expected)[0]},
            dict(self.expected, **{'../escape': '0' * 64}),
            dict(self.expected, **{sorted(self.expected)[0]: '0' * 63}),
            dict(self.expected, **{sorted(self.expected)[0]: 'Z' * 64}),
            dict(self.expected, **{sorted(self.expected)[0]: True}),
        ]
        for case in cases:
            with self.subTest(manifest_keys=len(case)):
                with self.assertRaises(staging.StagingError):
                    self.stage(expected=case)
        self.assertFalse((self.root / 'var').exists())

    def test_modified_untrusted_source_rejected_without_destination(self):
        name = sorted(self.expected)[0]
        (self.source / name).write_bytes(b'substituted executable code')
        with self.assertRaises(staging.StagingError):
            self.stage()
        self.assertFalse(self.dest.exists())

    def test_source_symlink_and_hardlink_are_refused(self):
        name = sorted(self.expected)[0]
        item = self.source / name
        item.unlink()
        outside = self.root / 'outside'
        outside.write_bytes(self.contents[name])
        item.symlink_to(outside)
        with self.assertRaises(staging.StagingError):
            self.stage()
        item.unlink()
        os.link(outside, item)
        with self.assertRaises(staging.StagingError):
            self.stage()
        self.assertFalse(self.dest.exists())

    def test_source_directory_symlink_and_parent_escape_are_refused(self):
        duplicate = self.root / 'source-link'
        duplicate.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(staging.StagingError):
            self.stage(source=duplicate)
        with self.assertRaises(staging.StagingError):
            self.stage(source=self.source / '..' / 'untrusted-source')
        with self.assertRaises(staging.StagingError):
            self.stage(source=Path('untrusted-source'))

    def test_source_fifo_is_rejected_without_blocking(self):
        name = sorted(self.expected)[0]
        item = self.source / name
        item.unlink()
        os.mkfifo(item)
        with self.assertRaises(staging.StagingError):
            self.stage()
        self.assertFalse(self.dest.exists())

    def test_oversize_file_is_rejected_before_dest_creation(self):
        name = sorted(self.expected)[0]
        data = b'A' * (staging._MAX_FILE_BYTES + 1)
        (self.source / name).write_bytes(data)
        self.expected[name] = hashlib.sha256(data).hexdigest()
        with self.assertRaises(staging.StagingError):
            self.stage()
        self.assertFalse(self.dest.exists())

    def test_source_changes_after_check_cannot_change_staged_bytes(self):
        original_walk = staging._walk_destination
        item = self.source / sorted(self.expected)[0]
        def mutate_after_verified(root, owner):
            item.write_bytes(b'evil mutation after source validation')
            return original_walk(root, owner)
        with mock.patch.object(staging, '_walk_destination',
                               side_effect=mutate_after_verified):
            with self.stage():
                _, ready = self.stage_files()
                self.assertEqual(len(ready), 1)
                self.assertEqual((ready[0] / sorted(self.expected)[0]).read_bytes(),
                                 self.contents[sorted(self.expected)[0]])

    def test_failed_staging_keeps_unsealed_pending_marker(self):
        with mock.patch.object(staging, '_write_file',
                               side_effect=OSError('simulated disk full')):
            with self.assertRaises(staging.StagingError):
                self.stage()
        pending, ready = self.stage_files()
        self.assertEqual(len(pending), 1)
        self.assertFalse(ready)
        with self.assertRaises(staging.StagingConflict):
            self.stage()

    def test_second_stage_rejected_until_ready_bundle_reconciled(self):
        with self.stage():
            pass
        with self.assertRaises(staging.StagingConflict):
            self.stage()
        self.assertEqual(len(self.stage_files()[1]), 1)

    def test_lock_contention_detected(self):
        with self.stage():
            pass
        # A fixture-only cleanup of the completed bundle, to exercise
        # concurrency without implementing any production cleanup API.
        _, ready = self.stage_files()
        for file in sorted(ready[0].rglob('*'), reverse=True):
            if file.is_file():
                file.unlink()
            else:
                file.rmdir()
        ready[0].rmdir()
        lockfd = os.open(self.dest / 'stage.lock', os.O_RDWR)
        try:
            fcntl.flock(lockfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(staging.StagingConflict):
                self.stage()
        finally:
            os.close(lockfd)

    def test_new_directory_modes_do_not_depend_on_umask(self):
        original_umask = os.umask(0o077)
        try:
            with self.stage():
                pass
        finally:
            os.umask(original_umask)
        self.assertEqual(stat.S_IMODE((self.root / 'var').stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE((self.root / 'var/lib').stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE((self.root / 'var/lib/computer-host-installer').stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.dest.stat().st_mode), 0o700)

    def test_reject_symlinked_destination_directory(self):
        (self.root / 'var').symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(staging.StagingError):
            self.stage()
        self.assertFalse((self.source / 'lib').exists())

    def test_reject_writable_system_parent_and_insecure_private_directory(self):
        system_parent = self.root / 'var'
        system_parent.mkdir()
        system_parent.chmod(0o777)
        with self.assertRaises(staging.StagingError):
            self.stage()
        system_parent.chmod(0o755)
        private_parent = self.root / 'var/lib/computer-host-installer'
        private_parent.mkdir(parents=True)
        private_parent.chmod(0o755)
        with self.assertRaises(staging.StagingError):
            self.stage()

    def test_existing_general_parent_mode_is_preserved(self):
        system_parent = self.root / 'var/lib'
        system_parent.mkdir(parents=True)
        system_parent.chmod(0o700)
        with self.stage():
            pass
        self.assertEqual(stat.S_IMODE(system_parent.stat().st_mode), 0o700)

    def test_readonly_result_has_no_secrets_or_raw_paths(self):
        with self.stage() as result:
            self.assertFalse(hasattr(result, 'execute'))
            self.assertFalse(hasattr(result, 'run'))
            self.assertFalse(hasattr(result, 'install'))
            self.assertFalse(hasattr(result, 'source'))
            self.assertFalse(hasattr(result, 'control_token'))
            self.assertFalse(hasattr(result, 'installation_id'))
        self.assertFalse(any('control-token' in item for item in staging.PAYLOAD_FILES))
        self.assertFalse(any('installation-id' in item for item in staging.PAYLOAD_FILES))


if __name__ == '__main__':
    unittest.main()
