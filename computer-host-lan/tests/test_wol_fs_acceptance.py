"""Disposable acceptance-tool fixtures, no real network or reboot."""
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
import wol_fs_acceptance as acceptance
import wol_fs_identity as identity
import wol_publication as publication

UUID = bytes.fromhex('12345678123456781234567812345678')
BOOT1 = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
BOOT2 = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.boot = BOOT1

        def identify(fd):
            return identity.FilesystemIdentity('btrfs', UUID, 256,
                                               os.fstat(fd).st_ino)

        for patch in (mock.patch.object(acceptance.identity, 'identify', side_effect=identify),
                      mock.patch.object(acceptance, '_boot', side_effect=lambda: self.boot)):
            patch.start()
            self.addCleanup(patch.stop)

    def run_fixture(self, action):
        result = acceptance._fixture_experiment(action, self.directory)
        self.assertNotIn(UUID.hex(), json.dumps(result))
        self.assertNotIn(BOOT1, json.dumps(result))
        self.assertNotIn(BOOT2, json.dumps(result))
        self.assertNotIn(str(self.directory), json.dumps(result))
        self.assertFalse(result['secrets_included'])
        return result

    def test_prepare_compare_after_simulated_reboot_and_rollback(self):
        prepared = self.run_fixture('prepare')
        self.assertEqual(prepared['status'], 'prepared')
        self.assertTrue(prepared['persistent_identity_available'])
        self.assertTrue(prepared['published_hardlinks_intact'])
        self.assertTrue(prepared['schema2_publication_verified'])
        baseline = self.directory / acceptance._BASELINE
        self.assertEqual(stat.S_IMODE(baseline.stat().st_mode), 0o600)
        raw = baseline.read_bytes()
        self.assertIn(UUID.hex().encode(), raw)
        self.assertFalse(self.run_fixture('compare')['different_boot'])
        self.boot = BOOT2
        compared = self.run_fixture('compare')
        self.assertTrue(compared['different_boot'])
        for field in ('persistent_identity_unchanged', 'device_numbers_unchanged',
                      'filesystem_ids_unchanged', 'inode_numbers_unchanged',
                      'link_counts_unchanged', 'published_hardlinks_intact',
                      'schema2_publication_verified'):
            self.assertTrue(compared[field], field)
        self.assertEqual(baseline.read_bytes(), raw)
        result = self.run_fixture('rollback')
        self.assertEqual(result['status'], 'rolled_back')
        self.assertTrue(result['rollback_verified'])
        policy = self.directory / 'policy-fixture'
        self.assertFalse((policy / publication.TARGET).exists())
        self.assertTrue((policy / acceptance._ANCHOR).is_file())

    def test_missing_identity_refuses_before_creating_fixture(self):
        with mock.patch.object(acceptance.identity, 'identify', return_value=None):
            result = self.run_fixture('prepare')
        self.assertEqual(result['status'], 'identity_unavailable')
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_nonempty_fixture_refused_without_overwriting(self):
        existing = self.directory / 'existing'
        existing.write_text('preserve')
        with self.assertRaises(ValueError):
            self.run_fixture('prepare')
        self.assertEqual(existing.read_text(), 'preserve')

    def test_unsafe_fixture_mode_refused(self):
        self.directory.chmod(0o755)
        with self.assertRaises(ValueError):
            self.run_fixture('prepare')
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_public_entry_refuses_root_before_opening_directory(self):
        with mock.patch.object(acceptance.os, 'getuid', return_value=0), \
             mock.patch.object(acceptance, '_fixture_experiment') as run:
            with self.assertRaises(ValueError):
                acceptance.experiment('prepare', self.directory)
            run.assert_not_called()

    def test_changed_persistent_identity_does_not_authorize_rollback(self):
        self.run_fixture('prepare')
        other = bytes.fromhex('87654321876543218765432187654321')
        with mock.patch.object(acceptance.identity, 'identify', side_effect=lambda fd:
                identity.FilesystemIdentity('btrfs', other, 256, os.fstat(fd).st_ino)):
            result = self.run_fixture('rollback')
        self.assertEqual(result['status'], 'rollback_refused')
        self.assertFalse(result['persistent_identity_unchanged'])
        self.assertTrue((self.directory / 'policy-fixture' / publication.TARGET).exists())

    def test_schema2_refusal_is_not_bypassed(self):
        self.run_fixture('prepare')
        with mock.patch.object(acceptance.publication, 'inspect',
                               side_effect=publication.PublicationError('fixture')), \
             mock.patch.object(acceptance.publication, 'rollback') as undo:
            result = self.run_fixture('rollback')
        self.assertEqual(result['status'], 'rollback_refused')
        self.assertTrue(result['persistent_identity_unchanged'])
        self.assertFalse(result['schema2_publication_verified'])
        undo.assert_not_called()

    def test_baseline_symlink_refused(self):
        self.run_fixture('prepare')
        baseline = self.directory / acceptance._BASELINE
        saved = baseline.with_name('saved')
        baseline.rename(saved)
        baseline.symlink_to(saved)
        with self.assertRaises(OSError):
            self.run_fixture('compare')


if __name__ == '__main__':
    unittest.main()
