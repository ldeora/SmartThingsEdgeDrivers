"""Fixture tests for the development-only bundle synchronizer."""
import os
from pathlib import Path
import tempfile
import unittest

import sync_bundle as sync


class SyncBundleTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.source = root / 'source'
        self.bundle = root / 'bundle'
        for name in sync.ASSETS:
            p = self.source / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(name.encode())

    def run_sync(self, check=False):
        return sync.synchronize(self.source, self.bundle, check=check)

    def test_missing_bundle_check_does_not_write_and_generation_is_idempotent(self):
        self.assertEqual(self.run_sync(check=True), sorted(sync.ASSETS))
        self.assertFalse(self.bundle.exists())
        self.assertEqual(self.run_sync(), sorted(sync.ASSETS))
        self.assertEqual(self.run_sync(check=True), [])
        self.assertEqual(self.run_sync(), [])
        for name, mode in sync.ASSETS.items():
            p = self.bundle / name
            self.assertEqual(p.read_bytes(), (self.source / name).read_bytes())
            self.assertEqual(p.stat().st_mode & 0o777, mode)

    def test_drift_check_does_not_change_files_and_regenerates_only_drift(self):
        self.run_sync()
        name = 'scripts/install_core.py'
        dest = self.bundle / name
        original = dest.read_bytes()
        (self.source / name).write_bytes(b'updated')
        self.assertEqual(self.run_sync(check=True), [name])
        self.assertEqual(dest.read_bytes(), original)
        self.assertEqual(self.run_sync(), [name])
        self.assertEqual(dest.read_bytes(), b'updated')
        self.assertEqual(self.run_sync(check=True), [])

    def test_executable_bit_drift_and_missing_file(self):
        self.run_sync()
        first, second = 'scripts/installer-api.sh', 'scripts/python-selector.sh'
        (self.bundle / first).chmod(0o644)
        (self.bundle / second).unlink()
        self.assertEqual(self.run_sync(check=True), [first, second])
        self.assertEqual(self.run_sync(), [first, second])
        self.assertEqual(self.run_sync(check=True), [])

    def test_unexpected_asset_refused_without_removal_or_other_writes(self):
        self.run_sync()
        unexpected = self.bundle / 'unexpected.py'
        unexpected.write_bytes(b'keep')
        name = 'scripts/install_core.py'
        dest = self.bundle / name
        original = dest.read_bytes()
        (self.source / name).write_bytes(b'changed')
        for check in (True, False):
            with self.assertRaises(sync.BundleError):
                self.run_sync(check=check)
        self.assertEqual(unexpected.read_bytes(), b'keep')
        self.assertEqual(dest.read_bytes(), original)

    def test_missing_source_refused_before_any_writes(self):
        self.run_sync()
        first = 'agent/linux_host_agent.py'
        dest = self.bundle / first
        original = dest.read_bytes()
        (self.source / first).write_bytes(b'changed')
        (self.source / 'scripts/transaction_journal.py').unlink()
        with self.assertRaises(FileNotFoundError):
            self.run_sync()
        self.assertEqual(dest.read_bytes(), original)

    def test_symlink_and_hardlink_assets_refused(self):
        self.run_sync()
        name = 'scripts/install_core.py'
        dest = self.bundle / name
        source = self.source / name
        dest.unlink()
        dest.symlink_to(source)
        with self.assertRaises(sync.BundleError):
            self.run_sync()
        dest.unlink()
        os.link(source, dest)
        with self.assertRaises(sync.BundleError):
            self.run_sync()
        self.assertEqual(source.read_bytes(), name.encode())

    def test_symlinked_source_parent_refused(self):
        self.run_sync()
        parent = self.source / 'scripts'
        moved = parent.with_name('moved')
        parent.rename(moved)
        parent.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(sync.BundleError):
            self.run_sync()


if __name__ == '__main__':
    unittest.main()
