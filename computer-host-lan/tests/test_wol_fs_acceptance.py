"""Disposable acceptance-tool fixtures, no real network or reboot."""
import io
import json
import os
from contextlib import redirect_stdout
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
OTHER_UUID = bytes.fromhex('87654321876543218765432187654321')
BOOT1 = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
BOOT2 = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.link_directory = self.directory / 'systemd-network-fixture'
        self.link_directory.mkdir(mode=0o700)
        self.boot = BOOT1
        self.link_uuid = UUID

        def identify(fd):
            info = os.fstat(fd)
            fs_uuid = (self.link_uuid if info.st_ino == self.link_directory.stat().st_ino
                       else UUID)
            return identity.FilesystemIdentity('btrfs', fs_uuid, 256, info.st_ino)

        def open_link_directory(stack):
            fd = os.open(self.link_directory, acceptance._FLAGS)
            stack.callback(os.close, fd)
            return fd

        for patch in (
                mock.patch.object(acceptance.identity, 'identify', side_effect=identify),
                mock.patch.object(acceptance, '_boot', side_effect=lambda: self.boot),
                mock.patch.object(acceptance, '_open_link_directory',
                                  side_effect=open_link_directory)):
            patch.start()
            self.addCleanup(patch.stop)

    def run_fixture(self, action):
        result = acceptance._fixture_experiment(action, self.directory)
        encoded = json.dumps(result)
        self.assertNotIn(UUID.hex(), encoded)
        self.assertNotIn(OTHER_UUID.hex(), encoded)
        self.assertNotIn(BOOT1, encoded)
        self.assertNotIn(BOOT2, encoded)
        self.assertNotIn(str(self.directory), encoded)
        self.assertFalse(result['secrets_included'])
        return result

    def run_cli(self, action):
        output = io.StringIO()
        with mock.patch.object(sys, 'argv', ['wol_fs_acceptance.py', action,
                                             str(self.directory)]):
            with redirect_stdout(output):
                code = acceptance.main()
        return code, json.loads(output.getvalue())

    def test_prepare_compare_after_simulated_reboot_and_rollback(self):
        prepared = self.run_fixture('prepare')
        self.assertEqual(prepared['status'], 'prepared')
        self.assertTrue(prepared['persistent_identity_available'])
        self.assertTrue(prepared['link_directory_identity_available'])
        self.assertTrue(prepared['same_filesystem_and_subvolume_as_link_dir'])
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
                      'link_counts_unchanged', 'link_directory_identity_unchanged',
                      'same_filesystem_and_subvolume_as_link_dir',
                      'published_hardlinks_intact', 'schema2_publication_verified'):
            self.assertTrue(compared[field], field)
        self.assertEqual(baseline.read_bytes(), raw)
        result = self.run_fixture('rollback')
        self.assertEqual(result['status'], 'rolled_back')
        self.assertTrue(result['rollback_verified'])
        policy = self.directory / 'policy-fixture'
        self.assertFalse((policy / publication.TARGET).exists())
        self.assertTrue((policy / acceptance._ANCHOR).is_file())
        after_rollback = self.run_fixture('compare')
        self.assertEqual(after_rollback['status'], 'fixture_rolled_back')
        self.assertTrue(after_rollback['rollback_verified'])

    def test_reports_fixture_and_link_directory_filesystem_mismatch(self):
        self.link_uuid = OTHER_UUID
        prepared = self.run_fixture('prepare')
        self.assertTrue(prepared['link_directory_identity_available'])
        self.assertFalse(prepared['same_filesystem_and_subvolume_as_link_dir'])
        compared = self.run_fixture('compare')
        self.assertFalse(compared['link_directory_identity_unchanged'])
        self.assertFalse(compared['same_filesystem_and_subvolume_as_link_dir'])
        self.assertTrue(compared['persistent_identity_unchanged'])

    def test_link_directory_identity_unavailable_is_explicit(self):
        with mock.patch.object(acceptance, '_open_link_directory', return_value=None):
            prepared = self.run_fixture('prepare')
        self.assertFalse(prepared['link_directory_identity_available'])
        self.assertFalse(prepared['same_filesystem_and_subvolume_as_link_dir'])
        compared = self.run_fixture('compare')
        self.assertFalse(compared['link_directory_identity_available'])
        self.assertFalse(compared['link_directory_identity_unchanged'])
        self.assertFalse(compared['same_filesystem_and_subvolume_as_link_dir'])

    def test_missing_identity_refuses_before_creating_fixture(self):
        with mock.patch.object(acceptance.identity, 'identify', return_value=None):
            result = self.run_fixture('prepare')
        self.assertEqual(result['status'], 'identity_unavailable')
        self.assertEqual(list(self.directory.iterdir()), [self.link_directory])

    def test_nonempty_fixture_refused_without_overwriting(self):
        existing = self.directory / 'existing'
        existing.write_text('preserve')
        with self.assertRaises(acceptance.FixtureNotEmpty):
            self.run_fixture('prepare')
        self.assertEqual(existing.read_text(), 'preserve')

    def test_unsafe_fixture_mode_refused(self):
        self.directory.chmod(0o755)
        with self.assertRaises(acceptance.FixtureNotPrivate):
            self.run_fixture('prepare')
        self.assertEqual(list(self.directory.iterdir()), [self.link_directory])

    def test_public_entry_refuses_root_before_opening_directory(self):
        with mock.patch.object(acceptance.os, 'getuid', return_value=0), \
             mock.patch.object(acceptance, '_fixture_experiment') as run:
            with self.assertRaises(acceptance.RootRefused):
                acceptance.experiment('prepare', self.directory)
            run.assert_not_called()

    def test_changed_persistent_identity_does_not_authorize_rollback(self):
        self.run_fixture('prepare')
        with mock.patch.object(acceptance.identity, 'identify', side_effect=lambda fd:
                identity.FilesystemIdentity('btrfs', OTHER_UUID, 256, os.fstat(fd).st_ino)):
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

    def test_baseline_symlink_refused_as_invalid(self):
        self.run_fixture('prepare')
        baseline = self.directory / acceptance._BASELINE
        saved = baseline.with_name('saved')
        baseline.rename(saved)
        baseline.symlink_to(saved)
        with self.assertRaises(acceptance.BaselineInvalid):
            self.run_fixture('compare')

    def test_duplicate_baseline_keys_refused(self):
        self.run_fixture('prepare')
        baseline = self.directory / acceptance._BASELINE
        raw = baseline.read_text()
        baseline.write_text(raw.replace('"schema": 2', '"schema": 2, "schema": 2', 1))
        with self.assertRaises(acceptance.BaselineInvalid):
            self.run_fixture('compare')

    def test_cli_reports_fixed_status_codes_without_paths(self):
        cases = (
            (acceptance.RootRefused, 'root_refused'),
            (acceptance.FixtureNotPrivate, 'fixture_not_private'),
            (acceptance.FixtureNotEmpty, 'fixture_not_empty'),
            (acceptance.BaselineInvalid, 'baseline_invalid'),
        )
        for error, expected in cases:
            with self.subTest(expected=expected), \
                 mock.patch.object(acceptance, 'experiment', side_effect=error), \
                 mock.patch.object(acceptance.os, 'getuid', return_value=12345), \
                 mock.patch.object(acceptance.os, 'geteuid', return_value=12345):
                code, result = self.run_cli('compare')
                self.assertEqual(code, 1)
                self.assertEqual(result['status'], expected)
                self.assertNotIn(str(self.directory), json.dumps(result))
                self.assertFalse(result['secrets_included'])


if __name__ == '__main__':
    unittest.main()
