"""Fixture-only end-to-end tests for the Linux installer lifecycle.

No privilege escalation, systemd, firewall, WOL, SmartThings or real host
files are modified. The existing install_core file writer is exercised only
inside a disposable private temporary root.
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
import install_core as core
import installer_transaction as installer
import payload_staging as staging
import transaction_journal as journal

UUID = '12345678-1234-4234-8234-123456789abc'


class FakeSystemd:
    def __init__(self, *, installed=False, active=False, enabled=False,
                 power_active=False, power_enabled=False):
        self.original = {
            'first_install': not installed,
            'agent_active': active,
            'agent_enabled': enabled,
            'socket_active': power_active,
            'socket_enabled': power_enabled,
        }
        self.states = dict(self.original)
        self.activations = []
        self.restore_calls = 0
        self.verify_calls = 0
        self.fail_verify = False
        self.fail_restore = False

    def capture_previous(self, transaction):
        return dict(self.original)

    def activate(self, previous, *, power_enabled, disable_power):
        self.activations.append((power_enabled, disable_power))
        self.states['agent_active'] = previous['first_install'] or previous['agent_active']
        self.states['agent_enabled'] = previous['first_install'] or previous['agent_enabled']
        if not power_enabled:
            self.states['socket_active'] = False
            self.states['socket_enabled'] = False
        elif previous['first_install'] or previous['newly_enabled_power']:
            self.states['socket_active'] = True
            self.states['socket_enabled'] = True

    def verify_install(self, request, previous, changes, *, power_enabled, transaction):
        self.verify_calls += 1
        for change in changes:
            target = transaction.location(change.path)
            if change.content is None:
                if target.exists():
                    return False
            elif not target.is_file() or target.read_bytes() != change.content:
                return False
        return not self.fail_verify

    def restore_services(self, previous):
        self.restore_calls += 1
        if self.fail_restore:
            raise RuntimeError('fake restore failed')
        self.states = {k: previous[k] for k in self.original}

    def verify_restored_services(self, previous):
        return self.states == {k: previous[k] for k in self.original}


class InstallerBackendTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.uid = os.geteuid()
        self.manual_lock = self.root / 'run/lock/linux-host-agent-install.lock'
        self.manual_lock.parent.mkdir(parents=True)
        self.services = FakeSystemd()
        self.backend = installer.InstallerBackend(
            root=self.root, owner_uid=self.uid,
            manual_lock_path=self.manual_lock,
            services=self.services)
        self.hashes = {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in staging.PAYLOAD_FILES
        }
        self.store = journal.ProtectedJournal(root=self.root, owner_uid=self.uid)
        self.staging_dir = self.root / 'var/lib/computer-host-installer/staging'

    @staticmethod
    def request(operation='install', **updates):
        kwargs = dict(operation=operation, python_bin='/usr/bin/python3',
                      expected_version='1.0.0', expected_identity=None)
        kwargs.update(updates)
        return installer.InstallRequest(**kwargs)

    def installed_paths(self):
        return core.InstallTransaction(self.root)

    def existing_install(self, *, active=True, enabled=True):
        self.services = FakeSystemd(installed=True, active=active, enabled=enabled)
        self.backend.services = self.services
        target = self.installed_paths().location(core.SYSTEMD_PATHS[0])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('ORIGINAL-UNIT-CONTENTS')
        target.chmod(0o644)
        return target

    def stage_entries(self):
        if not self.staging_dir.is_dir():
            return []
        return sorted(x.name for x in self.staging_dir.iterdir() if x.name != 'stage.lock')

    def test_install_applies_actual_plan_and_cleans_transaction(self):
        # The new agent files and the unit templates are REALLY installed
        # by install_core into the fake root, with no real systemd call.
        private = self.root / 'var/lib/linux-host-agent/installation-id'
        private.parent.mkdir(parents=True)
        private.write_text(UUID)
        result = self.backend.run(self.request(), ROOT, self.hashes)
        self.assertEqual(result.status, 'installed')
        self.assertEqual(result.identity_preserved, 'not_verified')
        self.assertTrue(result.source_verified)
        self.assertEqual(self.services.activations, [(False, False)])
        self.assertEqual(self.services.verify_calls, 1)
        self.assertEqual(private.read_text(), UUID)
        paths = self.installed_paths()
        for name in ('linux_host_agent.py', 'power_helper.py'):
            installed = paths.location('/opt/linux-host-agent/' + name)
            self.assertEqual(installed.read_bytes(), (ROOT / 'agent' / name).read_bytes())
            self.assertEqual(stat.S_IMODE(installed.stat().st_mode), 0o755)
        self.assertFalse(paths.location(core.POWER_DROPIN).exists())
        self.assertEqual(self.store.public_status()['privileged_transaction_state'], 'none')
        self.assertEqual(self.stage_entries(), [])
        self.assertEqual(len(list((self.root / core.BACKUP_BASE.lstrip('/')).glob(
            'snapshot-*'))), 1)

    def test_explicit_remote_power_option_only_changes_selected_feature(self):
        result = self.backend.run(self.request(enable_power=True), ROOT, self.hashes)
        self.assertEqual(result.status, 'installed')
        self.assertEqual(self.services.activations, [(True, False)])
        dropin = self.installed_paths().location(core.POWER_DROPIN)
        self.assertTrue(dropin.exists())
        self.assertIn(b'python3', dropin.read_bytes())
        self.assertFalse(self.installed_paths().location(core.WOL_DROPIN).exists())

    def test_upgrade_preserves_intentionally_stopped_and_disabled_state(self):
        old = self.existing_install(active=False, enabled=False)
        result = self.backend.run(
            self.request('upgrade', expected_identity=UUID), ROOT, self.hashes)
        self.assertEqual(result.status, 'installed')
        self.assertEqual(result.identity_preserved, 'verified')
        self.assertEqual(self.services.states['agent_active'], False)
        self.assertEqual(self.services.states['agent_enabled'], False)
        self.assertEqual(self.services.restore_calls, 0)
        self.assertNotEqual(old.read_text(), 'ORIGINAL-UNIT-CONTENTS')
        self.assertEqual(self.store.public_status()['privileged_transaction_state'], 'none')

    def test_repair_uses_same_transaction_and_preserves_identity(self):
        old = self.existing_install(active=True, enabled=True)
        result = self.backend.run(self.request('repair', expected_identity=UUID),
                                  ROOT, self.hashes)
        self.assertEqual(result.status, 'installed')
        self.assertEqual(self.services.verify_calls, 1)
        self.assertTrue(old.is_file())

    def test_failed_runtime_gate_restores_real_file_bytes_and_services(self):
        old = self.existing_install()
        before = old.read_bytes()
        self.services.fail_verify = True
        with self.assertRaises(installer.ControllerError) as error:
            self.backend.run(self.request('upgrade', expected_identity=UUID),
                             ROOT, self.hashes)
        self.assertEqual(error.exception.code, 'rolled_back')
        self.assertEqual(old.read_bytes(), before)
        self.assertEqual(self.services.restore_calls, 1)
        self.assertEqual(self.store.public_status()['privileged_transaction_state'], 'none')
        self.assertEqual(self.stage_entries(), [])

    def test_failed_restore_does_not_falsely_report_success(self):
        self.existing_install()
        self.services.fail_verify = True
        self.services.fail_restore = True
        with self.assertRaises(installer.ControllerError) as error:
            self.backend.run(self.request('upgrade', expected_identity=UUID),
                             ROOT, self.hashes)
        self.assertEqual(error.exception.code, 'recovery_required')
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'recovery_required')
        self.assertEqual(len(self.stage_entries()), 1)
        with self.assertRaises(journal.JournalConflict):
            self.store.begin('repair')

    def test_bad_payload_digest_aborts_without_installing(self):
        corrupted = dict(self.hashes)
        corrupted[sorted(corrupted)[0]] = '0' * 64
        with self.assertRaises(installer.ControllerError) as error:
            self.backend.run(self.request(), ROOT, corrupted)
        self.assertEqual(error.exception.code, 'aborted')
        self.assertEqual(self.store.public_status()['privileged_transaction_state'], 'none')
        self.assertFalse(self.installed_paths().location(core.SYSTEMD_PATHS[0]).exists())
        self.assertEqual(self.stage_entries(), [])

    def test_partial_pending_write_is_discarded_and_next_install_works(self):
        with mock.patch.object(staging, '_write_file',
                               side_effect=OSError('test-only interrupted write')):
            with self.assertRaises(installer.ControllerError) as error:
                self.backend.run(self.request(), ROOT, self.hashes)
        self.assertEqual(error.exception.code, 'aborted')
        self.assertEqual(self.stage_entries(), [])
        result = self.backend.run(self.request(), ROOT, self.hashes)
        self.assertEqual(result.status, 'installed')

    def test_snapshot_failure_happens_before_any_applied_mutation(self):
        with mock.patch.object(core.InstallTransaction, 'snapshot',
                               side_effect=OSError('fixture disk full')):
            with self.assertRaises(installer.ControllerError) as error:
                self.backend.run(self.request(), ROOT, self.hashes)
        self.assertEqual(error.exception.code, 'aborted')
        self.assertFalse(self.installed_paths().location(core.SYSTEMD_PATHS[0]).exists())
        self.assertEqual(self.store.public_status()['privileged_transaction_state'], 'none')

    def test_completed_install_with_interrupted_cleanup_does_not_reinstall(self):
        with mock.patch.object(staging, 'finish_terminal_stage',
                               side_effect=staging.StagingError('fixture failure')):
            result = self.backend.run(self.request(), ROOT, self.hashes)
        self.assertEqual(result.status, 'installed_cleanup_required')
        self.assertEqual(self.services.verify_calls, 1)
        self.assertEqual(len(self.stage_entries()), 1)
        with self.assertRaises(journal.JournalConflict):
            self.store.begin('upgrade')
        self.backend.finish_terminal_cleanup()
        self.assertEqual(self.store.public_status()['privileged_transaction_state'], 'none')
        self.assertEqual(self.stage_entries(), [])
        self.assertEqual(self.services.verify_calls, 1)  # No reinstallation.

    def test_manual_cli_lock_blocks_wizard_without_creating_journal(self):
        fd = os.open(self.manual_lock, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(installer.ControllerError) as error:
                self.backend.run(self.request(), ROOT, self.hashes)
            self.assertEqual(error.exception.code, 'installation_busy')
            self.assertFalse((self.root / 'var/backups/linux-host-agent').exists())
        finally:
            os.close(fd)
        result = self.backend.run(self.request(), ROOT, self.hashes)
        self.assertEqual(result.status, 'installed')

    def test_invalid_request_never_creates_state(self):
        bad = [
            self.request('uninstall'),
            self.request(python_bin='/tmp/python3'),
            self.request(python_bin='/usr/bin/../../tmp/python3'),
            self.request(expected_version='INVALID!'),
            self.request(expected_identity='not-a-uuid'),
            self.request(enable_power=True, disable_power=True),
            self.request(wol_interface='../wlan'),
            self.request(port=80),
        ]
        for request in bad:
            with self.subTest(request=str(request)):
                with self.assertRaises(installer.ControllerError) as error:
                    self.backend.run(request, ROOT, self.hashes)
                self.assertEqual(error.exception.code, 'invalid_request')
        self.assertFalse((self.root / 'var/backups').exists())

    def test_existing_install_requires_trusted_expected_identity(self):
        self.existing_install()
        with self.assertRaises(installer.ControllerError) as error:
            self.backend.run(self.request(), ROOT, self.hashes)
        self.assertEqual(error.exception.code, 'aborted')
        self.assertFalse(self.stage_entries())

    def test_stopped_agent_skips_http_but_checks_files_and_service_state(self):
        old = self.existing_install(active=False, enabled=False)
        ops = installer.SystemdOperations(
            health_probe=mock.Mock(side_effect=AssertionError('no HTTP for stopped unit')))
        trans = self.installed_paths()
        change = core.Change(core.SYSTEMD_PATHS[0], old.read_bytes())
        with mock.patch.object(core, 'state', return_value=False):
            self.assertTrue(ops.verify_install(
                self.request('upgrade', expected_identity=UUID),
                dict(first_install=False, agent_active=False, agent_enabled=False,
                     socket_active=False, socket_enabled=False),
                [change], power_enabled=False, transaction=trans))
        ops.health_probe.assert_not_called()

    def test_active_agent_requires_runtime_verifier_success(self):
        old = self.existing_install(active=True, enabled=True)
        probe = mock.Mock(return_value={
            'status': 'passed', 'runtime_verified': True,
            'identity_preserved': 'passed',
        })
        ops = installer.SystemdOperations(health_probe=probe)
        trans = self.installed_paths()
        change = core.Change(core.SYSTEMD_PATHS[0], old.read_bytes())
        def active_state(unit, command):
            if unit == 'linux-host-agent.service':
                return True
            return False
        with mock.patch.object(core, 'state', side_effect=active_state):
            self.assertTrue(ops.verify_install(
                self.request('upgrade', expected_identity=UUID),
                dict(first_install=False, agent_active=True, agent_enabled=True,
                     socket_active=False, socket_enabled=False),
                [change], power_enabled=False, transaction=trans))
        probe.assert_called_once()
        self.assertEqual(probe.call_args.kwargs['expected_identity'], UUID)

    def test_legacy_manual_lock_mode_0644_is_accepted(self):
        self.manual_lock.touch(mode=0o600)
        self.manual_lock.chmod(0o644)
        result = self.backend.run(self.request(), ROOT, self.hashes)
        self.assertEqual(result.status, 'installed')
        self.assertEqual(stat.S_IMODE(self.manual_lock.stat().st_mode), 0o644)


if __name__ == '__main__':
    unittest.main()
