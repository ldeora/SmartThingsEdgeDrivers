"""Legacy-v1 coexistence protections: filesystem fixtures only, never host services."""
from __future__ import annotations

from pathlib import Path
import os
import pwd
import subprocess
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
        self.assertEqual(owner.stat().st_mode & 0o777, 0o644)
        self.assertEqual(owner.parent.stat().st_mode & 0o777, 0o755)
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

    @unittest.skipUnless(os.geteuid() == 0 and hasattr(os, 'fork'),
                         'requires root CI process to switch to an unprivileged user')
    def test_owner_record_can_be_read_as_a_different_unprivileged_user(self):
        # A same-UID fixture cannot find the regression: it can traverse
        # a 0700 directory, whereas the actual Go wizard cannot.
        core.write_owner_record(self.root)
        self.root.chmod(0o755)  # TemporaryDirectory defaults to private.
        (self.root / 'var').chmod(0o755)
        (self.root / 'var/lib').chmod(0o755)
        try:
            other = pwd.getpwnam('nobody')
        except KeyError:
            self.skipTest('nobody account not available in fixture container')
        pid = os.fork()
        if pid == 0:
            try:
                try:
                    os.setgroups([])
                except PermissionError:
                    pass  # Rootless containers may restrict supplemental groups.
                try:
                    os.setgid(other.pw_gid)
                    os.setuid(other.pw_uid)
                except PermissionError:
                    os._exit(77)  # No CAP_SETUID in this CI container.
                if (core.owner_record_exists(self.root) and
                        core.require_v2_or_clean(self.root) == 'v2'):
                    os._exit(0)
            except Exception:
                os._exit(2)
            os._exit(1)
        _, status = os.waitpid(pid, 0)
        code = os.waitstatus_to_exitcode(status)
        if code == 77:
            self.skipTest('container cannot switch to another UID')
        self.assertEqual(code, 0)

    def test_owner_record_permission_error_is_a_clean_install_error(self):
        core.write_owner_record(self.root)
        with mock.patch.object(core.os, 'lstat',
                               side_effect=PermissionError('hidden marker')):
            with self.assertRaisesRegex(core.InstallError, 'Cannot inspect'):
                core.owner_record_exists(self.root)

    def test_owner_record_is_safe_under_umask_077(self):
        original_umask = os.umask(0o077)
        try:
            core.write_owner_record(self.root)
        finally:
            os.umask(original_umask)
        owner = self.root / core.OWNER_FILE.lstrip('/')
        self.assertEqual(owner.parent.stat().st_mode & 0o777, 0o755)
        self.assertEqual(owner.stat().st_mode & 0o777, 0o644)
        self.assertEqual(core.require_v2_or_clean(self.root), 'v2')

    def test_owner_record_publication_failure_before_rename_is_retryable(self):
        folder = self.root / core.OWNER_DIR.lstrip('/')
        with mock.patch.object(core.os, 'rename',
                               side_effect=OSError('fixture rename failure')):
            with self.assertRaises(core.InstallError):
                core.write_owner_record(self.root)
        self.assertFalse(folder.exists())
        self.assertFalse(core.owner_record_exists(self.root))
        self.assertEqual(list(folder.parent.iterdir()), [])
        core.write_owner_record(self.root)
        self.assertTrue(core.owner_record_exists(self.root))

    def test_owner_record_post_publication_sync_failure_retries_ancestors(self):
        folder = self.root / core.OWNER_DIR.lstrip('/')
        real_sync = os.fsync
        observed = []

        def sync(fd):
            info = os.fstat(fd)
            if folder.exists():
                for path in (folder, folder.parent, folder.parent.parent, self.root):
                    expected = path.stat()
                    if (info.st_dev, info.st_ino) == (expected.st_dev, expected.st_ino):
                        observed.append(path)
                        if path == folder.parent:
                            raise OSError('fixture parent sync failure')
            real_sync(fd)

        with mock.patch.object(core.os, 'fsync', side_effect=sync):
            with self.assertRaises(core.InstallError):
                core.write_owner_record(self.root)
        self.assertTrue(core.owner_record_exists(self.root))
        self.assertIn(folder.parent, observed)
        observed.clear()

        def record(fd):
            info = os.fstat(fd)
            for path in (folder, folder.parent, folder.parent.parent, self.root):
                expected = path.stat()
                if (info.st_dev, info.st_ino) == (expected.st_dev, expected.st_ino):
                    observed.append(path)
            real_sync(fd)

        with mock.patch.object(core.os, 'fsync', side_effect=record):
            core.write_owner_record(self.root)
        self.assertEqual(observed, [folder, folder.parent, folder.parent.parent, self.root])

    def test_owner_record_ignores_interrupted_pending_directory(self):
        folder = self.root / core.OWNER_DIR.lstrip('/')
        pending = folder.parent / ('.linux-host-agent-installer-pending-' + 'a' * 32)
        pending.mkdir(parents=True, mode=0o700)
        (pending / 'protocol').write_bytes(b'v2\\n')
        self.assertFalse(core.owner_record_exists(self.root))
        self.assertEqual(self.classify(), 'absent')
        core.write_owner_record(self.root)
        self.assertTrue(core.owner_record_exists(self.root))
        self.assertTrue(pending.is_dir())  # No scavenging arbitrary siblings.

    def test_owner_record_never_overwrites_incomplete_final_directory(self):
        folder = self.root / core.OWNER_DIR.lstrip('/')
        folder.mkdir(parents=True)
        self.assertFalse(core.owner_record_exists(self.root))
        with self.assertRaises(core.InstallError):
            core.write_owner_record(self.root)
        self.assertEqual(list(folder.iterdir()), [])

    def test_owner_record_refuses_writable_parent(self):
        parent = (self.root / core.OWNER_DIR.lstrip('/')).parent
        parent.mkdir(parents=True)
        parent.chmod(0o777)
        with self.assertRaises(core.InstallError):
            core.write_owner_record(self.root)
        self.assertFalse((parent / 'linux-host-agent-installer').exists())

    def test_marker_symlink_or_insecure_mode_is_refused(self):
        core.write_owner_record(self.root)
        marker = self.root / core.OWNER_FILE.lstrip('/')
        marker.chmod(0o666)
        with self.assertRaises(core.InstallError):
            self.classify()
        marker.chmod(0o644)
        marker.unlink()
        marker.symlink_to(self.put('/elsewhere', b'v2\n'))
        with self.assertRaises(core.InstallError):
            self.classify()

    def test_v2_filesystem_lifecycle_install_uninstall_reinstall_with_secret_retention(self):
        """Use the real snapshot/apply planner, not just unlinking one file."""
        trans = core.InstallTransaction(self.root)
        identity = self.put('/var/lib/linux-host-agent/installation-id', b'UUID-UNCHANGED')
        secret = self.put('/var/lib/linux-host-agent/control-token', b'SECRET-UNCHANGED')
        core.write_owner_record(self.root)

        plan = core.generate_plan(ROOT, '/usr/bin/python3',
                                  enable_power=False, disable_power=False,
                                  wol_interface=None, is_existing_power=False,
                                  avahi_dir=False)
        trans.snapshot(plan)
        trans.apply(plan)
        self.assertEqual(self.classify(), 'v2')

        uninstall = core.generate_plan(ROOT, '/usr/bin/python3',
                                       enable_power=False, disable_power=False,
                                       wol_interface=None, is_existing_power=False,
                                       avahi_dir=False, uninstall=True)
        trans.snapshot(uninstall)
        trans.apply(uninstall)
        self.assertEqual(self.classify(), 'v2')
        self.assertFalse((self.root / core.APP_FILES[0].lstrip('/')).exists())

        reinstall = core.generate_plan(ROOT, '/usr/bin/python3',
                                       enable_power=False, disable_power=False,
                                       wol_interface=None, is_existing_power=False,
                                       avahi_dir=False)
        trans.snapshot(reinstall)
        trans.apply(reinstall)
        self.assertEqual(self.classify(), 'v2')
        self.assertEqual(identity.read_bytes(), b'UUID-UNCHANGED')
        self.assertEqual(secret.read_bytes(), b'SECRET-UNCHANGED')

    def test_snapshot_without_v2_agent_blocks_legacy_restore_even_with_owner(self):
        """A v1 snapshot created before the new manifest tag cannot be adopted."""
        backup = core.InstallTransaction(self.root).snapshot([
            core.Change(core.APP_FILES[0], b'new app')
        ])
        core.write_owner_record(self.root)
        manifest = backup / 'manifest.json'
        import json
        data = json.loads(manifest.read_text())
        data.pop('installer_protocol')
        manifest.write_text(json.dumps(data))
        with self.assertRaises(core.InstallError):
            core.validate_v2_backup(backup, root=self.root)

    def test_backup_symlink_contents_fail_before_restore(self):
        self.put(core.APP_FILES[0], b'PROTOCOL = "computer-host-agent"\n')
        backup = core.InstallTransaction(self.root).snapshot([
            core.Change(core.APP_FILES[0], b'new app')
        ])
        item = backup / '0.original'
        item.unlink()
        item.symlink_to(self.put('/external/other', b'PROTOCOL = "computer-host-agent"\n'))
        with self.assertRaises(core.InstallError):
            core.validate_v2_backup(backup, root=self.root)

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
        backup_base = self.root / 'backup-base'
        bad_backup = backup_base / 'snapshot-bad'
        bad_backup.mkdir(parents=True)
        with mock.patch.object(core, 'BACKUP_BASE', str(backup_base)), \
             mock.patch.object(core.os, 'geteuid', return_value=0), \
             mock.patch.object(core, 'require_v2_or_clean') as guard, \
             mock.patch.object(core, 'validate_v2_backup',
                               side_effect=core.InstallError('Invalid backup')):
            with self.assertRaises(core.InstallError):
                core.run_cli(['--rollback', str(bad_backup)])
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
        # Run the entire legacy shell installer with harmless PATH stubs.
        # Only its systemd directory probe is redirected to the fixture.
        scripts = self.root / 'fixture' / 'scripts'
        scripts.mkdir(parents=True)
        bin_dir = self.root / 'bin'
        bin_dir.mkdir()
        active = self.root / 'systemd'
        active.mkdir()
        source = (ROOT / 'scripts/install-agent.sh').read_text()
        self.assertEqual(source.count('/run/systemd/system'), 1)
        entry = scripts / 'install-agent.sh'
        entry.write_text(source.replace('/run/systemd/system', str(active)))
        (scripts / 'python-selector.sh').write_bytes(
            (ROOT / 'scripts/python-selector.sh').read_bytes())
        log = self.root / 'calls'

        def stub(name, body):
            target = bin_dir / name
            target.write_text('#!/bin/sh\n' + body + '\n')
            target.chmod(0o755)
            return target

        stub('id', 'printf "0\\n"')
        stub('dirname', 'for arg do :; done; printf "%s\\n" "${arg%/*}"')
        stub('getent', 'printf "getent\\n" >> "$CALL_LOG"; exit 2')
        stub('useradd', 'printf "useradd\\n" >> "$CALL_LOG"')
        for name in ('systemctl', 'install', 'nologin'):
            stub(name, 'exit 99')
        interpreter = stub('python3', '''case "$1" in
  -c) exit 0 ;;
esac
shift
printf '%s\\n' "$*" >> "$CALL_LOG"
case "$1" in
  --check-existing|--check-wizard-journal)
    [ "$1" != "$BLOCK_AT" ] || exit 2 ;;
  --install|--plan) ;;
  *) exit 99 ;;
esac
exit 0''')

        for blocked, dry, adopt in (
                ('--check-existing', False, False),
                ('--check-wizard-journal', False, True),
                ('', False, True), ('', True, True)):
            with self.subTest(blocked=blocked, dry=dry, adopt=adopt):
                log.write_text('')
                args = ['/bin/sh', str(entry), '--python', str(interpreter)]
                if dry:
                    args.append('--dry-run')
                if adopt:
                    args.append('--adopt-retained-state')
                result = subprocess.run(args, env={
                    'PATH': str(bin_dir), 'CALL_LOG': str(log),
                    'BLOCK_AT': blocked, 'LANG': 'C',
                }, capture_output=True, text=True, timeout=10)
                calls = log.read_text().splitlines()
                check = '--check-existing' + (' --adopt-retained-state' if adopt else '')
                self.assertTrue(calls, result.stderr)
                self.assertEqual(calls[0], check)
                if blocked:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(calls, [check] if blocked == '--check-existing'
                                     else [check, '--check-wizard-journal'])
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    if dry:
                        self.assertEqual(len(calls), 2)
                        self.assertTrue(calls[-1].startswith('--plan '))
                    else:
                        self.assertEqual(calls[1:4], [
                            '--check-wizard-journal', 'getent', 'useradd'])
                        self.assertEqual(len(calls), 5)
                        self.assertTrue(calls[-1].startswith('--install '))
                    self.assertTrue(calls[-1].endswith(' --adopt-retained-state'))

    def test_preflight_source_guard_mentions_existing_protocol_check(self):
        # Static guard for the separate read-only script. Actual modifying
        # installer ordering is exercised by the behavioral fixture above.
        self.assertIn('--check-existing', (ROOT / 'scripts/preflight.sh').read_text())


if __name__ == '__main__':
    unittest.main()
