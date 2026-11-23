"""Legacy-v1 coexistence protections: filesystem fixtures only, never host services."""
from __future__ import annotations

from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import install_core as core


class InstalledProtocolTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def put(self, absolute, content: bytes):
        target = self.root / absolute.lstrip('/')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return target

    def classify(self):
        return core.detect_installed_protocol(self.root)

    def test_empty_host_and_existing_generic_avahi_directory_are_clean(self):
        self.assertEqual(self.classify(), 'absent')
        (self.root / 'etc/avahi/services').mkdir(parents=True)
        self.assertEqual(self.classify(), 'absent')
        self.assertFalse((self.root / 'var/backups/linux-host-agent').exists())

    def test_existing_real_v2_is_recognized_and_keeps_state_private(self):
        source = ROOT / 'agent/linux_host_agent.py'
        self.put(core.APP_FILES[0], source.read_bytes())
        self.put(core.AVAHI_PATH,
                 (ROOT / 'agent/systemd/avahi-linux-host-agent.service').read_bytes())
        secret = self.put('/var/lib/linux-host-agent/control-token', b'PRIVATE-KEY')
        self.assertEqual(self.classify(), 'v2')
        self.assertEqual(core.require_v2_or_clean(self.root), 'v2')
        self.assertEqual(secret.read_bytes(), b'PRIVATE-KEY')

    def test_legacy_v1_agent_and_avahi_are_blocked(self):
        self.put(core.APP_FILES[0], b'PROTOCOL = "linux-host-agent"\nAPI_VERSION = 1\n')
        self.put(core.AVAHI_PATH, b'<type>_linuxhost._tcp</type>\n')
        self.assertEqual(self.classify(), 'v1')
        with self.assertRaisesRegex(core.InstallError, 'Legacy v1'):
            core.require_v2_or_clean(self.root)

    def test_legacy_v1_single_marker_is_still_blocked(self):
        self.put(core.APP_FILES[0], b'PROTOCOL = "linux-host-agent"\n')
        self.assertEqual(self.classify(), 'v1')
        (self.root / core.APP_FILES[0].lstrip('/')).unlink()
        self.put(core.AVAHI_PATH, b'<type>_linuxhost._tcp</type>\n')
        self.assertEqual(self.classify(), 'v1')

    def test_mixed_v1_and_v2_protocol_markers_fail_closed(self):
        self.put(core.APP_FILES[0], b'PROTOCOL = "computer-host-agent"\n')
        self.put(core.AVAHI_PATH, b'<type>_linuxhost._tcp</type>\n')
        self.assertEqual(self.classify(), 'unknown')
        with self.assertRaisesRegex(core.InstallError, 'could not be identified'):
            core.require_v2_or_clean(self.root)
        self.put(core.AVAHI_PATH, b'<type>_computerhost._tcp</type>\n')
        self.assertEqual(self.classify(), 'v2')

    def test_unknown_agent_does_not_count_as_v2(self):
        self.put(core.APP_FILES[0], b'# PROTOCOL = "computer-host-agent"\n')
        self.assertEqual(self.classify(), 'unknown')
        self.put(core.APP_FILES[0], b'PROTOCOL = "computer-host-agent"\n'
                                    b'PROTOCOL = "linux-host-agent"\n')
        self.assertEqual(self.classify(), 'unknown')

    def test_abandoned_unit_helper_or_state_directory_blocks_fresh_install(self):
        for path in (core.SYSTEMD_PATHS[0], core.APP_FILES[1],
                     core.POWER_DROPIN, core.AVAHI_PATH):
            with self.subTest(path=path):
                target = self.put(path, b'old unrecognized content')
                self.assertEqual(self.classify(), 'unknown')
                target.unlink()
        secret = self.put('/var/lib/linux-host-agent/control-token', b'DO-NOT-READ')
        self.assertEqual(self.classify(), 'unknown')
        with self.assertRaisesRegex(core.InstallError, 'investigate'):
            core.require_v2_or_clean(self.root)
        self.assertEqual(secret.read_bytes(), b'DO-NOT-READ')

    def test_symlinks_and_oversized_marker_are_refused(self):
        outside = self.put('/somewhere/outside', b'PROTOCOL = "computer-host-agent"\n')
        target = self.root / core.APP_FILES[0].lstrip('/')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(outside)
        with self.assertRaises(core.InstallError):
            self.classify()
        target.unlink()
        self.put(core.APP_FILES[0], b'PROTOCOL = "computer-host-agent"\n' +
                 b'Z' * core.MAX_PROTOCOL_BYTES)
        with self.assertRaises(core.InstallError):
            self.classify()
        self.assertEqual(outside.read_bytes(), b'PROTOCOL = "computer-host-agent"\n')

    def test_read_only_guard_causes_no_file_or_directory_writes(self):
        agent = self.put(core.APP_FILES[0], b'PROTOCOL = "linux-host-agent"\n')
        old_mtime = agent.stat().st_mtime_ns
        with self.assertRaises(core.InstallError):
            core.require_v2_or_clean(self.root)
        self.assertEqual(agent.stat().st_mtime_ns, old_mtime)
        self.assertFalse((self.root / 'var/backups').exists())

    def test_every_mutating_cli_path_refuses_before_backup_or_services(self):
        for args in (
            ['--install', '--source', str(ROOT), '--python', '/usr/bin/python3'],
            ['--uninstall'],
        ):
            with self.subTest(args=args):
                with mock.patch.object(core.os, 'geteuid', return_value=0), \
                     mock.patch.object(core, 'require_v2_or_clean',
                                       side_effect=core.InstallError('Legacy v1')), \
                     mock.patch.object(core.Path, 'mkdir') as mkdir, \
                     mock.patch.object(core, 'systemctl') as systemctl:
                    with self.assertRaises(core.InstallError):
                        core.run_cli(args)
                    mkdir.assert_not_called()
                    systemctl.assert_not_called()

    def test_protected_v2_record_allows_uninstall_reinstall_with_retained_identity(self):
        agent = self.put(core.APP_FILES[0], b'PROTOCOL = "computer-host-agent"\n')
        secret = self.put('/var/lib/linux-host-agent/control-token', b'SECRET')
        identity = self.put('/var/lib/linux-host-agent/installation-id', b'UUID')
        core.write_owner_record(self.root)
        owner = self.root / core.OWNER_FILE.lstrip('/')
        self.assertEqual(owner.read_bytes(), b'v2\n')
        self.assertEqual(owner.stat().st_mode & 0o777, 0o600)
        self.assertEqual(owner.parent.stat().st_mode & 0o777, 0o700)
        agent.unlink()  # v2 uninstall leaves state and record, no app files.
        self.assertEqual(self.classify(), 'v2')
        self.assertEqual(core.require_v2_or_clean(self.root), 'v2')
        # Simulate reinstall source; state is preserved byte-for-byte.
        self.put(core.APP_FILES[0], b'PROTOCOL = "computer-host-agent"\n')
        self.assertEqual(self.classify(), 'v2')
        self.assertEqual(secret.read_bytes(), b'SECRET')
        self.assertEqual(identity.read_bytes(), b'UUID')

    def test_failed_first_install_cleanup_keeps_recoverable_owner_record(self):
        core.write_owner_record(self.root)
        self.put('/var/lib/linux-host-agent/control-token', b'preserve-this-token')
        partially_installed = self.put(core.APP_FILES[0],
                                       b'PROTOCOL = "computer-host-agent"\n')
        # A failed first activation rolls back files, but systemd has
        # already created the service StateDirectory and v2 key.
        partially_installed.unlink()
        self.assertEqual(self.classify(), 'v2')
        self.assertEqual(core.require_v2_or_clean(self.root), 'v2')

    def test_orphan_retained_state_needs_explicit_manual_adoption(self):
        secret = self.put('/var/lib/linux-host-agent/control-token', b'UNCHANGED')
        self.assertEqual(self.classify(), 'unknown')
        with self.assertRaises(core.InstallError):
            core.require_v2_or_clean(self.root)
        self.assertEqual(core.require_v2_or_clean(
            self.root, adopt_retained_state=True), 'adopted')
        self.assertEqual(secret.read_bytes(), b'UNCHANGED')
        core.write_owner_record(self.root)
        self.assertEqual(self.classify(), 'v2')
        # Explicit adoption is invalid when a record already exists.
        with self.assertRaises(core.InstallError):
            core.require_v2_or_clean(self.root, adopt_retained_state=True)

    def test_adoption_never_overrides_v1_or_partial_managed_files(self):
        self.put('/var/lib/linux-host-agent/control-token', b'SECRET')
        agent = self.put(core.APP_FILES[0], b'PROTOCOL = "linux-host-agent"\n')
        with self.assertRaises(core.InstallError):
            core.require_v2_or_clean(self.root, adopt_retained_state=True)
        agent.unlink()
        bad_unit = self.put(core.SYSTEMD_PATHS[0], b'ambiguous')
        with self.assertRaises(core.InstallError):
            core.require_v2_or_clean(self.root, adopt_retained_state=True)
        bad_unit.unlink()
        self.assertEqual(core.require_v2_or_clean(
            self.root, adopt_retained_state=True), 'adopted')

    def test_v2_marker_is_not_allowed_to_override_detectable_v1(self):
        core.write_owner_record(self.root)
        self.put(core.APP_FILES[0], b'PROTOCOL = "linux-host-agent"\n')
        self.assertEqual(self.classify(), 'v1')
        with self.assertRaises(core.InstallError):
            core.require_v2_or_clean(self.root)

    def test_marker_symlink_or_insecure_mode_is_refused(self):
        core.write_owner_record(self.root)
        marker = self.root / core.OWNER_FILE.lstrip('/')
        marker.chmod(0o666)
        with self.assertRaises(core.InstallError):
            self.classify()
        marker.chmod(0o600)
        marker.unlink()
        marker.symlink_to(self.put('/elsewhere', b'v2\n'))
        with self.assertRaises(core.InstallError):
            self.classify()

    def test_rollback_proven_v2_snapshot_with_damaged_current_files(self):
        self.put(core.APP_FILES[0], b'PROTOCOL = "computer-host-agent"\n')
        backup = core.InstallTransaction(self.root).snapshot([
            core.Change(core.APP_FILES[0], b'new v2 code')
        ])
        self.put(core.APP_FILES[0], b'BROKEN PARTIAL INSTALL')
        self.assertEqual(self.classify(), 'unknown')
        core.validate_v2_backup(backup, root=self.root)
        core.InstallTransaction(self.root).restore(backup)
        self.assertEqual(self.classify(), 'v2')

    def test_v1_and_unknown_rollback_snapshots_are_rejected(self):
        agent = self.put(core.APP_FILES[0], b'PROTOCOL = "linux-host-agent"\n')
        backup = core.InstallTransaction(self.root).snapshot([
            core.Change(core.APP_FILES[0], b'new code')
        ])
        with self.assertRaisesRegex(core.InstallError, 'legacy v1'):
            core.validate_v2_backup(backup, root=self.root)
        agent.write_bytes(b'NO PROTOCOL LINE')
        bad_backup = core.InstallTransaction(self.root).snapshot([
            core.Change(core.APP_FILES[0], b'new code')
        ])
        with self.assertRaisesRegex(core.InstallError, 'unknown'):
            core.validate_v2_backup(bad_backup, root=self.root)

    def test_empty_agent_backup_requires_new_v2_provenance_and_owner(self):
        backup = core.InstallTransaction(self.root).snapshot([
            core.Change(core.APP_FILES[0], b'first install')
        ])
        with self.assertRaises(core.InstallError):
            core.validate_v2_backup(backup, root=self.root)
        core.write_owner_record(self.root)
        core.validate_v2_backup(backup, root=self.root)
        # Old-format v1 backups never carried the v2 provenance field.
        manifest = backup / 'manifest.json'
        import json
        obj = json.loads(manifest.read_text())
        obj.pop('installer_protocol')
        manifest.write_text(json.dumps(obj))
        with self.assertRaises(core.InstallError):
            core.validate_v2_backup(backup, root=self.root)

    def test_rollback_does_not_depend_on_damaged_current_protocol(self):
        # A bad backup should be rejected BEFORE any lock or service writes,
        # and the current-host coexistence guard must not run.
        with mock.patch.object(core.os, 'geteuid', return_value=0), \
             mock.patch.object(core, 'require_v2_or_clean') as guard, \
             mock.patch.object(core, 'validate_v2_backup',
                               side_effect=core.InstallError('Invalid backup')):
            with self.assertRaises(core.InstallError):
                core.run_cli(['--rollback', '/var/backups/linux-host-agent/nonexistent'])
            guard.assert_not_called()

    def test_read_only_cli_guard_works_without_root(self):
        with mock.patch.object(core.os, 'geteuid', return_value=1000), \
             mock.patch.object(core, 'require_v2_or_clean', return_value='absent') as guard:
            self.assertEqual(core.run_cli(['--check-existing']), 0)
            guard.assert_called_once()
        with mock.patch.object(core, 'require_v2_or_clean',
                               side_effect=core.InstallError('Legacy v1')), \
             mock.patch.object(core.Path, 'mkdir') as mkdir:
            with self.assertRaises(core.InstallError):
                core.run_cli(['--plan', '--source', str(ROOT), '--python', '/usr/bin/python3'])
            mkdir.assert_not_called()

    def test_shell_checks_prior_to_account_creation(self):
        source = (ROOT / 'scripts/install-agent.sh').read_text()
        self.assertLess(source.index('--check-existing'), source.index('getent passwd linuxhost'))
        self.assertIn('--check-existing', (ROOT / 'scripts/preflight.sh').read_text())


if __name__ == '__main__':
    unittest.main()
