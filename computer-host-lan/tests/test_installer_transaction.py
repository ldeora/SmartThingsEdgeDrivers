"""Fixture-only end-to-end tests for the Linux installer lifecycle.

No privilege escalation, systemd, firewall, WOL, SmartThings or real host
files are modified. The existing install_core file writer is exercised only
inside a disposable private temporary root.
"""
from __future__ import annotations

import errno
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
        self.user_preflights = 0
        self.verify_calls = 0
        self.fail_verify = False
        self.fail_restore = False
        self.received_request = None
        self.uninstall_stops = 0
        self.uninstall_reloads = 0
        self.fail_uninstall_stop = False
        self.fail_uninstall_disable = False
        self.power_helper_active = False
        self.fail_uninstall_helper_stop = False
        self.fail_uninstall_verify = False

    def capture_previous(self, transaction):
        return dict(self.original)

    def ensure_agent_user(self):
        self.user_preflights += 1

    def activate(self, previous, *, power_enabled, disable_power):
        self.activations.append((power_enabled, disable_power))
        self.states['agent_active'] = previous['first_install'] or previous['agent_active']
        self.states['agent_enabled'] = previous['first_install'] or previous['agent_enabled']
        socket_active, socket_enabled = core.expected_socket_state(
            previous, power_enabled=power_enabled)
        self.states['socket_active'] = socket_active
        self.states['socket_enabled'] = socket_enabled

    def verify_install(self, request, previous, changes, *, power_enabled, transaction):
        self.verify_calls += 1
        self.received_request = request
        for change in changes:
            target = transaction.location(change.path)
            if change.content is None:
                if target.exists():
                    return False
            elif not target.is_file() or target.read_bytes() != change.content:
                return False
        return not self.fail_verify

    def stop_for_uninstall(self):
        self.uninstall_stops += 1
        if not self.fail_uninstall_stop:
            for key in ('agent_active', 'socket_active'):
                self.states[key] = False
        if not self.fail_uninstall_disable:
            for key in ('agent_enabled', 'socket_enabled'):
                self.states[key] = False
        if not self.fail_uninstall_helper_stop:
            self.power_helper_active = False

    def verify_uninstall_stopped(self):
        return not self.power_helper_active and all(
            not self.states[key] for key in (
                'agent_active', 'agent_enabled',
                'socket_active', 'socket_enabled')
        )

    def reload_after_uninstall(self):
        self.uninstall_reloads += 1

    def verify_uninstall_services(self):
        return not self.fail_uninstall_verify and self.verify_uninstall_stopped()

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
        # Real v2 installation has an identifiable v2 Python agent.
        agent = self.installed_paths().location(core.APP_FILES[0])
        agent.parent.mkdir(parents=True, exist_ok=True)
        agent.write_bytes((ROOT / 'agent/linux_host_agent.py').read_bytes())
        agent.chmod(0o755)
        private = self.root / 'var/lib/linux-host-agent/installation-id'
        private.parent.mkdir(parents=True, exist_ok=True)
        private.write_text(UUID + '\n')
        private.chmod(0o600)
        return target

    def stage_entries(self):
        if not self.staging_dir.is_dir():
            return []
        return sorted(x.name for x in self.staging_dir.iterdir() if x.name != 'stage.lock')

    def test_privileged_request_accepts_exact_fixed_system_python_directories(self):
        # The shell root launcher trusts these same four system directories.
        # Gentoo python-exec may expose /usr/sbin/python3, while other
        # distributions may report /usr/bin/python3.N.
        allowed = (
            '/usr/sbin/python3', '/usr/bin/python3.14',
            '/sbin/python3.12', '/bin/python3.11',
        )
        for python in allowed:
            with self.subTest(python=python):
                self.request('upgrade', python_bin=python,
                             expected_version='0.4.6-rc.2').validate()

        forbidden = (
            '/tmp/python3', '/home/user/python3',
            '/usr/local/bin/python3', '/usr/bin/../tmp/python3',
            '/usr/sbin/../../tmp/python3', 'python3', '/usr/bin/python 3',
        )
        for python in forbidden:
            with self.subTest(python=python), self.assertRaises(
                    installer.ControllerError) as error:
                self.request('upgrade', python_bin=python).validate()
            self.assertEqual(error.exception.code, 'invalid_request')

    def test_gentoo_sbin_interpreter_completes_fixture_upgrade(self):
        # Regression for the first physical Gentoo upgrade that returned
        # invalid_request after shell bootstrap succeeded. All filesystem
        # writes and service calls stay within the disposable test fixture.
        self.existing_install(active=True, enabled=True)
        outcome = self.backend.run(self.request(
            'upgrade', python_bin='/usr/sbin/python3',
            expected_version='0.4.6-rc.2'), ROOT, self.hashes)
        self.assertEqual(outcome.status, 'installed')
        self.assertEqual(outcome.identity_preserved, 'verified')
        self.assertEqual(self.services.received_request.python_bin, '/usr/sbin/python3')
        self.assertEqual(self.store.public_status()['privileged_transaction_state'], 'none')
        self.assertEqual(self.stage_entries(), [])

    def test_journaled_uninstall_removes_only_managed_files(self):
        old = self.existing_install()
        agent = self.installed_paths().location(core.APP_FILES[0])
        previous_agent = agent.read_bytes()
        retained = self.root / 'var/lib/linux-host-agent'
        token = retained / 'control-token'
        token.write_text('FIXTURE-SECRET-NEVER-LOG')
        token.chmod(0o600)
        unrelated = self.root / 'etc/systemd/network/10-existing-wol.link'
        unrelated.parent.mkdir(parents=True, exist_ok=True)
        unrelated.write_text('operator-managed WOL configuration')
        power = self.installed_paths().location(core.POWER_DROPIN)
        power.parent.mkdir(parents=True, exist_ok=True)
        power.write_text('[Service]\\n')
        result = self.backend.uninstall()
        self.assertEqual(result.status, 'uninstalled')
        self.assertEqual(result.identity_preserved, 'verified')
        self.assertEqual(self.services.uninstall_stops, 1)
        self.assertEqual(self.services.uninstall_reloads, 1)
        self.assertEqual(self.services.user_preflights, 0)
        self.assertEqual(self.services.restore_calls, 0)
        self.assertEqual(self.services.states['agent_active'], False)
        for path in core.MANAGED_PATHS:
            self.assertFalse(self.installed_paths().location(path).exists(), path)
        self.assertTrue(core.owner_record_exists(self.root))
        self.assertEqual((retained / 'installation-id').read_text(), UUID + '\n')
        self.assertEqual(token.read_text(), 'FIXTURE-SECRET-NEVER-LOG')
        self.assertEqual(unrelated.read_text(), 'operator-managed WOL configuration')
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'none')
        self.assertFalse(self.stage_entries())
        snapshots = list((self.root / core.BACKUP_BASE.lstrip('/')).glob('snapshot-*'))
        self.assertEqual(len(snapshots), 1)
        # Snapshot authenticates the removed v2 application, and recovery
        # material is deliberately retained for expert restore.
        core.validate_v2_backup(snapshots[0], root=self.root)
        self.assertTrue(any(p.read_bytes() == previous_agent
                            for p in snapshots[0].glob('*.original')))
        with self.assertRaises(installer.ControllerError) as second:
            self.backend.uninstall()
        self.assertEqual(second.exception.code, 'not_installed')
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'none')
        # Normal reinstall after an owner-record-retaining uninstall remains
        # permitted through the established install transaction.
        self.services = FakeSystemd(installed=False)
        self.backend.services = self.services
        reinstalled = self.backend.run(self.request(), ROOT, self.hashes)
        self.assertEqual(reinstalled.status, 'installed')
        self.assertTrue(self.installed_paths().location(core.APP_FILES[0]).exists())

    def test_uninstall_clean_host_refused_without_transaction(self):
        with self.assertRaises(installer.ControllerError) as error:
            self.backend.uninstall()
        self.assertEqual(error.exception.code, 'not_installed')
        self.assertEqual(self.services.uninstall_stops, 0)
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'none')
        self.assertFalse(self.installed_paths().location(core.APP_FILES[0]).exists())

    def test_uninstall_pending_transaction_takes_priority_over_absent_agent(self):
        with self.store.begin('uninstall') as journal:
            journal.advance('INSPECTED', 'STAGED')
        with self.assertRaises(installer.ControllerError) as error:
            self.backend.uninstall()
        self.assertEqual(error.exception.code, 'recovery_required')
        self.assertEqual(self.services.uninstall_stops, 0)
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'incomplete')

    def test_journaled_uninstall_preserves_disabled_existing_state(self):
        self.existing_install(active=False, enabled=False)
        result = self.backend.uninstall()
        self.assertEqual(result.status, 'uninstalled')
        self.assertTrue(self.services.verify_uninstall_services())
        self.assertEqual(self.services.restore_calls, 0)

    def test_journaled_uninstall_refuses_unknown_and_v1_without_changes(self):
        for agent_marker in (b"PROTOCOL = 'linux-host-agent'\\n", b'unknown'):
            with self.subTest(agent_marker=agent_marker):
                old = self.existing_install()
                agent = self.installed_paths().location(core.APP_FILES[0])
                agent.write_bytes(agent_marker)
                before = old.read_bytes()
                with self.assertRaises(installer.ControllerError) as error:
                    self.backend.uninstall()
                self.assertEqual(error.exception.code, 'unsupported_environment')
                self.assertEqual(old.read_bytes(), before)
                self.assertEqual(self.services.uninstall_stops, 0)
                self.assertEqual(self.store.public_status()[
                    'privileged_transaction_state'], 'none')
                agent.write_bytes((ROOT / 'agent/linux_host_agent.py').read_bytes())

    def test_uninstall_stop_must_be_verified_before_removing_files(self):
        old = self.existing_install()
        original = old.read_bytes()
        self.services.fail_uninstall_stop = True
        with self.assertRaises(installer.ControllerError) as error:
            self.backend.uninstall()
        self.assertEqual(error.exception.code, 'rolled_back')
        self.assertEqual(old.read_bytes(), original)
        self.assertEqual(self.services.restore_calls, 1)
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'none')

    def test_journaled_uninstall_failed_verification_rolls_back(self):
        old = self.existing_install()
        original = old.read_bytes()
        self.services.fail_uninstall_verify = True
        with self.assertRaises(installer.ControllerError) as error:
            self.backend.uninstall()
        self.assertEqual(error.exception.code, 'rolled_back')
        self.assertEqual(old.read_bytes(), original)
        self.assertEqual(self.services.restore_calls, 1)
        self.assertTrue(self.services.verify_restored_services(
            self.services.original))
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'none')

    def test_journaled_uninstall_failed_rollback_requires_recovery(self):
        old = self.existing_install()
        original = old.read_bytes()
        self.services.fail_uninstall_verify = True
        self.services.fail_restore = True
        with self.assertRaises(installer.ControllerError) as error:
            self.backend.uninstall()
        self.assertEqual(error.exception.code, 'recovery_required')
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'recovery_required')
        self.assertEqual(old.read_bytes(), original)
        self.services.fail_restore = False
        outcome = self.backend.recover_interrupted()
        self.assertEqual(outcome.status, 'rolled_back')
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'none')

    def test_uninstall_crash_after_removal_recovers_original_files_and_services(self):
        old = self.existing_install()
        original = old.read_bytes()
        trans = self.installed_paths()
        changes = [core.Change(path, None) for path in sorted(core.MANAGED_PATHS)]
        with self.store.begin('uninstall') as journal:
            journal.advance('INSPECTED', 'STAGED')
            previous = self.services.capture_previous(trans)
            snapshot = trans.snapshot(changes, previous=previous)
            installer._sync_snapshot(snapshot)
            journal.advance('STAGED', 'SNAPSHOTTED',
                            snapshot_name=snapshot.name)
            journal.advance('SNAPSHOTTED', 'APPLYING')
            self.services.stop_for_uninstall()
            trans.apply(changes)
            journal.advance('APPLYING', 'ACTIVATING')
            # Simulated SIGKILL: only the kernel locks are released.
        self.assertFalse(old.exists())
        recovered = self.backend.recover_interrupted()
        self.assertEqual(recovered.status, 'rolled_back')
        self.assertEqual(recovered.operation, 'uninstall')
        self.assertEqual(old.read_bytes(), original)
        self.assertEqual(self.services.restore_calls, 1)
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'none')

    def test_uninstall_failure_after_removing_files_restores_snapshot(self):
        old = self.existing_install()
        original = old.read_bytes()
        trans_type = core.InstallTransaction
        original_apply = trans_type.apply

        def remove_then_fail(instance, changes):
            original_apply(instance, changes)
            raise OSError('simulated disk error after all deletes')

        with mock.patch.object(trans_type, 'apply', new=remove_then_fail):
            with self.assertRaises(installer.ControllerError) as error:
                self.backend.uninstall()
        self.assertEqual(error.exception.code, 'rolled_back')
        self.assertEqual(old.read_bytes(), original)
        self.assertEqual(self.services.restore_calls, 1)
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'none')

    def test_uninstall_committed_cleanup_failure_does_not_restore_agent(self):
        self.existing_install()
        with mock.patch.object(staging, 'finish_terminal_stage',
                               side_effect=staging.StagingError('fixture failure')):
            result = self.backend.uninstall()
        self.assertEqual(result.status, 'uninstalled_cleanup_required')
        self.assertFalse(self.installed_paths().location(core.APP_FILES[0]).exists())
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'none')
        # A finished COMMITTED journal requires explicit cleanup, not
        # reapplication or rollback. Public status may still say none
        # because COMMITTED is terminal, but it must remain on disk.
        folder = self.root / 'var/backups/linux-host-agent/wizard-transactions'
        self.assertTrue((folder / 'journal.json').exists())
        # The public recovery path must also clean this payload-free
        # terminal journal, despite read-only status being none.
        recovered = self.backend.recover_interrupted()
        self.assertEqual(recovered.status, 'cleaned')
        self.assertEqual(recovered.operation, 'uninstall')
        self.assertFalse((folder / 'journal.json').exists())
        self.assertFalse(self.installed_paths().location(core.APP_FILES[0]).exists())
        self.assertEqual(self.services.restore_calls, 0)

    def test_uninstall_preapply_crash_does_not_remove_managed_files(self):
        old = self.existing_install()
        previous_bytes = old.read_bytes()
        trans = self.installed_paths()
        changes = [core.Change(path, None) for path in sorted(core.MANAGED_PATHS)]
        with self.store.begin('uninstall') as journal:
            journal.advance('INSPECTED', 'STAGED')
            previous = self.services.capture_previous(trans)
            snapshot = trans.snapshot(changes, previous=previous)
            installer._sync_snapshot(snapshot)
            journal.advance('STAGED', 'SNAPSHOTTED', snapshot_name=snapshot.name)
        recovered = self.backend.recover_interrupted()
        self.assertEqual(recovered.status, 'aborted')
        self.assertEqual(old.read_bytes(), previous_bytes)
        self.assertEqual(self.services.uninstall_stops, 0)
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'none')

    def test_uninstall_systemd_stops_services_before_unlinking(self):
        ops = installer.SystemdOperations()
        from unittest.mock import call
        with mock.patch.object(core, 'systemctl') as ctl:
            ops.stop_for_uninstall()
            self.assertEqual(ctl.call_args_list, [
                call('disable', '--now', 'linux-host-agent-power.socket'),
                call('stop', 'linux-host-agent-power.service'),
                call('disable', '--now', 'linux-host-agent.service'),
            ])

    def test_uninstall_requires_disabled_and_inactive_before_any_unlink(self):
        for failure in ('disable', 'helper_stop'):
            with self.subTest(failure=failure):
                old = self.existing_install()
                original = old.read_bytes()
                if failure == 'disable':
                    self.services.fail_uninstall_disable = True
                else:
                    self.services.power_helper_active = True
                    self.services.fail_uninstall_helper_stop = True
                with mock.patch.object(core.InstallTransaction, 'apply') as apply:
                    with self.assertRaises(installer.ControllerError) as error:
                        self.backend.uninstall()
                    apply.assert_not_called()
                self.assertEqual(error.exception.code, 'rolled_back')
                self.assertEqual(old.read_bytes(), original)
                self.assertEqual(self.services.restore_calls, 1)
                self.assertEqual(self.store.public_status()[
                    'privileged_transaction_state'], 'none')

    def test_uninstall_systemd_checks_explicit_states_before_and_after_removal(self):
        ops = installer.SystemdOperations()

        def before(unit):
            return dict(LoadState='loaded', ActiveState='inactive',
                        UnitFileState=('static' if unit.endswith('power.service')
                                       else 'disabled'))

        with mock.patch.object(ops, '_uninstall_unit_state', side_effect=before):
            self.assertTrue(ops.verify_uninstall_stopped())
            self.assertFalse(ops.verify_uninstall_services())

        for failing_unit, field, value in (
                ('linux-host-agent.service', 'UnitFileState', 'enabled'),
                ('linux-host-agent-power.socket', 'UnitFileState', 'enabled-runtime'),
                ('linux-host-agent-power.service', 'ActiveState', 'active'),
                ('linux-host-agent-power.service', 'ActiveState', 'deactivating'),
                ('linux-host-agent.service', 'LoadState', 'not-found')):
            with self.subTest(unit=failing_unit, field=field, value=value):
                def bad_state(unit):
                    state = before(unit)
                    if unit == failing_unit:
                        state[field] = value
                    return state
                with mock.patch.object(ops, '_uninstall_unit_state',
                                       side_effect=bad_state):
                    self.assertFalse(ops.verify_uninstall_stopped())

        after = dict(LoadState='not-found', ActiveState='inactive',
                     UnitFileState='')
        with mock.patch.object(ops, '_uninstall_unit_state', return_value=after):
            self.assertTrue(ops.verify_uninstall_services())
            self.assertFalse(ops.verify_uninstall_stopped())

        def active_helper_after(unit):
            return dict(after, ActiveState=('active' if unit.endswith(
                'power.service') else 'inactive'))
        with mock.patch.object(ops, '_uninstall_unit_state',
                               side_effect=active_helper_after):
            self.assertFalse(ops.verify_uninstall_services())

    def test_uninstall_systemd_query_requires_complete_successful_response(self):
        ops = installer.SystemdOperations()
        import subprocess
        raw = '\n'.join(('LoadState=loaded', 'ActiveState=inactive',
                         'UnitFileState=disabled', ''))
        for code, output, expected in (
                (0, raw, True),
                (1, raw, False),
                (124, raw, False),
                (0, 'ActiveState=inactive', False),
                (0, raw + 'ActiveState=inactive\n', False),
                (0, '', False)):
            with self.subTest(code=code, output=output):
                result = subprocess.CompletedProcess([], code, stdout=output)
                with mock.patch.object(installer.subprocess, 'run',
                                       return_value=result):
                    self.assertEqual(ops._uninstall_unit_state(
                        'linux-host-agent.service') is not None, expected)
        for exc in (OSError('bus unavailable'),
                    subprocess.TimeoutExpired('systemctl', 10)):
            with mock.patch.object(installer.subprocess, 'run', side_effect=exc):
                self.assertFalse(ops.verify_uninstall_stopped())
                self.assertFalse(ops.verify_uninstall_services())

    def test_install_applies_actual_plan_and_cleans_transaction(self):
        # The new agent files and the unit templates are REALLY installed
        # by install_core into the fake root, with no real systemd call.
        private = self.root / 'var/lib/linux-host-agent/installation-id'
        result = self.backend.run(self.request(), ROOT, self.hashes)
        self.assertEqual(result.status, 'installed')
        self.assertEqual(result.identity_preserved, 'not_verified')
        self.assertTrue(result.source_verified)
        self.assertEqual(self.services.activations, [(False, False)])
        self.assertEqual(self.services.user_preflights, 1)
        self.assertEqual(self.services.verify_calls, 1)
        self.assertFalse(private.exists())  # Only the real started agent creates an ID.
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
        self.assertEqual(result.identity_preserved, 'not_verified')
        self.assertEqual(self.services.received_request.expected_identity, UUID)
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
        self.assertEqual(error.exception.failure_stage, 'payload')
        self.assertEqual(self.store.public_status()['privileged_transaction_state'], 'none')
        self.assertFalse(self.installed_paths().location(core.SYSTEMD_PATHS[0]).exists())
        self.assertEqual(self.stage_entries(), [])

    def test_partial_pending_write_is_discarded_and_next_install_works(self):
        with mock.patch.object(staging, '_write_file',
                               side_effect=OSError('test-only interrupted write')):
            with self.assertRaises(installer.ControllerError) as error:
                self.backend.run(self.request(), ROOT, self.hashes)
        self.assertEqual(error.exception.code, 'aborted')
        self.assertEqual(error.exception.failure_stage, 'payload')
        self.assertEqual(self.stage_entries(), [])
        result = self.backend.run(self.request(), ROOT, self.hashes)
        self.assertEqual(result.status, 'installed')

    def test_snapshot_failure_happens_before_any_applied_mutation(self):
        with mock.patch.object(core.InstallTransaction, 'snapshot',
                               side_effect=OSError('fixture disk full')):
            with self.assertRaises(installer.ControllerError) as error:
                self.backend.run(self.request(), ROOT, self.hashes)
        self.assertEqual(error.exception.code, 'aborted')
        self.assertEqual(error.exception.failure_stage, 'snapshot')
        self.assertFalse(self.installed_paths().location(core.SYSTEMD_PATHS[0]).exists())
        self.assertEqual(self.store.public_status()['privileged_transaction_state'], 'none')

    def test_preapply_failure_diagnostics_are_only_fixed_stage_codes(self):
        self.existing_install()
        scenarios = (
            ('existing_state', mock.patch.object(
                installer, 'read_saved_identity',
                side_effect=installer.ControllerError('unsupported_environment'))),
            ('plan', mock.patch.object(
                core, 'generate_plan',
                side_effect=core.InstallError('fixture internal path must stay private'))),
        )
        for stage, context in scenarios:
            with self.subTest(stage=stage), context:
                with self.assertRaises(installer.ControllerError) as error:
                    self.backend.run(self.request('upgrade'), ROOT, self.hashes)
                self.assertEqual(error.exception.code, 'aborted')
                self.assertEqual(error.exception.failure_stage, stage)
                self.assertNotIn('fixture internal path', str(error.exception))
                self.assertEqual(
                    self.store.public_status()['privileged_transaction_state'],
                    'none')
                self.assertEqual(self.stage_entries(), [])

        for code, stage, expected in (
            ('aborted', 'payload', 'payload'),
            ('aborted', '/etc/shadow', None),
            ('recovery_required', 'snapshot', None),
            ('invalid_request', 'plan', None),
            ('aborted', None, None),
        ):
            error = installer.ControllerError(code, failure_stage=stage)
            self.assertEqual(error.failure_stage, expected)

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

    def test_wizard_shared_lock_reports_fixed_unsafe_lock_code(self):
        # An invalid shared lock must be diagnosed as unsafe, rather than
        # conflated with unrelated unsupported Linux environments.
        target = self.root / 'existing-owned-lock'
        target.write_bytes(b'KEEP')
        target.chmod(0o600)
        self.manual_lock.symlink_to(target)
        with self.assertRaises(installer.ControllerError) as raised:
            with installer.manual_install_lock(self.manual_lock,
                                               owner_uid=self.uid):
                self.fail('Symlinked shared lock must never be acquired')
        self.assertEqual(raised.exception.code, 'unsafe_lock')
        self.assertEqual(target.read_bytes(), b'KEEP')
        self.manual_lock.unlink()

        self.manual_lock.touch(mode=0o600)
        self.manual_lock.chmod(0o666)
        with self.assertRaises(installer.ControllerError) as raised:
            with installer.manual_install_lock(self.manual_lock,
                                               owner_uid=self.uid):
                self.fail('World-writable lock must never be acquired')
        self.assertEqual(raised.exception.code, 'unsafe_lock')
        self.manual_lock.chmod(0o600)

        with self.assertRaises(installer.ControllerError) as raised:
            with installer.manual_install_lock(self.manual_lock,
                                               owner_uid=self.uid + 1):
                self.fail('Foreign-owned lock must never be acquired')
        self.assertEqual(raised.exception.code, 'unsafe_lock')
        self.assertEqual(str(raised.exception), 'unsafe_lock')

    def test_manual_and_wizard_lock_open_errors_are_classified_correctly(self):
        # Unsafe lock objects are actionable. Disk-full/read-only/missing
        # directories are not evidence of an attacker-planted lock.
        unsafe = (errno.ELOOP, errno.EACCES, errno.EPERM, errno.EISDIR,
                  errno.ENOTDIR, errno.ENXIO)
        operational = (errno.ENOSPC, errno.EROFS, errno.ENOENT, errno.EIO)
        for number in unsafe + operational:
            with self.subTest(errno=number):
                failure = OSError(number, 'simulated lock open failure')
                with mock.patch.object(core.os, 'open', side_effect=failure):
                    if number in unsafe:
                        with self.assertRaises(core.InstallError) as err:
                            core.open_manual_install_lock(self.manual_lock,
                                                          owner_uid=self.uid)
                        self.assertIn('Unsafe manual installer lock',
                                      str(err.exception))
                    else:
                        with self.assertRaises(OSError) as err:
                            core.open_manual_install_lock(self.manual_lock,
                                                          owner_uid=self.uid)
                        self.assertEqual(err.exception.errno, number)

                with mock.patch.object(installer.os, 'open', side_effect=failure):
                    with self.assertRaises(installer.ControllerError) as err:
                        with installer.manual_install_lock(self.manual_lock,
                                                           owner_uid=self.uid):
                            self.fail('Cannot acquire a mocked failing lock')
                self.assertEqual(err.exception.code, (
                    'unsafe_lock' if number in unsafe
                    else 'unsupported_environment'))

    def test_errors_inside_held_wizard_lock_are_not_mislabelled(self):
        # Only failure to OPEN or ACQUIRE the lock can be a lock error.
        # Runtime filesystem failures inside a transaction must propagate.
        with self.assertRaises(OSError) as err:
            with installer.manual_install_lock(self.manual_lock,
                                               owner_uid=self.uid):
                raise OSError(errno.ENOSPC, 'simulated disk full in payload')
        self.assertEqual(err.exception.errno, errno.ENOSPC)

    def test_manual_cli_lock_rejects_symlink_hardlink_and_fifo(self):
        # Manual and Go installs use the same lock in /run/lock. The manual
        # CLI must not follow a planted symlink even if its target is safe.
        target = self.root / 'manual-lock-target'
        target.write_text('KEEP')
        target.chmod(0o600)
        planted = self.root / 'planted-install.lock'
        planted.symlink_to(target)
        with self.assertRaises(core.InstallError) as raised:
            core.open_manual_install_lock(planted, owner_uid=self.uid)
        self.assertIn('/run/lock/linux-host-agent-install.lock',
                      str(raised.exception))
        self.assertIn('no installer is running', str(raised.exception))
        self.assertEqual(target.read_text(), 'KEEP')
        planted.unlink()

        os.link(target, planted)
        with self.assertRaises(core.InstallError):
            core.open_manual_install_lock(planted, owner_uid=self.uid)
        planted.unlink()

        os.mkfifo(planted, 0o600)
        with self.assertRaises(core.InstallError):
            core.open_manual_install_lock(planted, owner_uid=self.uid)
        planted.unlink()

        target.chmod(0o666)
        with self.assertRaises(core.InstallError):
            core.open_manual_install_lock(target, owner_uid=self.uid)

    def test_manual_cli_lock_accepts_existing_0644_without_chmod(self):
        lockfile = self.root / 'legacy-manual.lock'
        lockfile.touch(mode=0o600)
        lockfile.chmod(0o644)
        with core.open_manual_install_lock(lockfile, owner_uid=self.uid) as fd:
            self.assertTrue(stat.S_ISREG(os.fstat(fd.fileno()).st_mode))
            self.assertEqual(stat.S_IMODE(lockfile.stat().st_mode), 0o644)
        self.assertEqual(stat.S_IMODE(lockfile.stat().st_mode), 0o644)

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
            self.request(port=8766),
        ]
        for request in bad:
            with self.subTest(request=str(request)):
                with self.assertRaises(installer.ControllerError) as error:
                    self.backend.run(request, ROOT, self.hashes)
                self.assertEqual(error.exception.code, 'invalid_request')
        self.assertFalse((self.root / 'var/backups').exists())

    def test_upgrade_reads_private_uuid_without_exposing_it_to_wizard(self):
        self.existing_install()
        result = self.backend.run(self.request('upgrade'), ROOT, self.hashes)
        self.assertEqual(result.status, 'installed')
        self.assertEqual(result.identity_preserved, 'verified')
        self.assertEqual(self.services.received_request.expected_identity, UUID)
        self.assertEqual(
            (self.root / 'var/lib/linux-host-agent/installation-id').read_text(),
            UUID + '\n')

    def test_wrong_internal_identity_hint_is_rejected_before_applying(self):
        unit = self.existing_install()
        before = unit.read_bytes()
        with self.assertRaises(installer.ControllerError) as caught:
            self.backend.run(self.request('upgrade', expected_identity=
                'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'), ROOT, self.hashes)
        self.assertEqual(caught.exception.code, 'aborted')
        self.assertEqual(unit.read_bytes(), before)
        self.assertEqual(self.services.verify_calls, 0)

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

    def test_service_user_created_only_after_durable_applying_phase(self):
        observed = []
        def check_user():
            phases = list((self.root / 'var/backups/linux-host-agent/wizard-transactions').glob('journal.json'))
            self.assertEqual(len(phases), 1)
            record = json.loads(phases[0].read_text())
            observed.append(record['phase'])
        with mock.patch.object(self.services, 'ensure_agent_user', side_effect=check_user):
            self.assertEqual(self.backend.run(self.request(), ROOT, self.hashes).status,
                             'installed')
        self.assertEqual(observed, ['APPLYING'])

    def test_failure_to_create_service_user_restores_managed_files(self):
        old = self.existing_install()
        previous_bytes = old.read_bytes()
        with mock.patch.object(self.services, 'ensure_agent_user',
                               side_effect=RuntimeError('useradd unavailable')):
            with self.assertRaises(installer.ControllerError) as error:
                self.backend.run(self.request('upgrade', expected_identity=UUID),
                                 ROOT, self.hashes)
        self.assertEqual(error.exception.code, 'rolled_back')
        self.assertEqual(old.read_bytes(), previous_bytes)
        self.assertEqual(self.services.restore_calls, 1)

    def test_fresh_install_useradd_failure_rolls_back_and_can_retry(self):
        # Regression: without a v2 ownership record, validating the fresh
        # snapshot fails after useradd fails, and the wizard gets stuck in
        # APPLYING even though no managed installation was written.
        with mock.patch.object(self.services, 'ensure_agent_user',
                               side_effect=RuntimeError('useradd unavailable')):
            with self.assertRaises(installer.ControllerError) as caught:
                self.backend.run(self.request(), ROOT, self.hashes)
        self.assertEqual(caught.exception.code, 'rolled_back')
        self.assertEqual(self.services.restore_calls, 1)
        self.assertEqual(self.stage_entries(), [])
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'none')
        self.assertFalse(self.installed_paths().location(core.APP_FILES[0]).exists())
        self.assertFalse(self.installed_paths().location(core.SYSTEMD_PATHS[0]).exists())
        self.assertTrue(core.owner_record_exists(self.root))
        self.assertEqual(self.backend.run(self.request(), ROOT, self.hashes).status,
                         'installed')

    def test_saved_identity_allows_agent_crash_leftover_hardlink(self):
        self.existing_install()
        saved = self.root / 'var/lib/linux-host-agent/installation-id'
        leftover = saved.with_name('.installation-id.crashed.tmp')
        os.link(saved, leftover)
        self.assertEqual(saved.stat().st_nlink, 2)
        self.assertEqual(installer.read_saved_identity(self.root), UUID)
        result = self.backend.run(self.request('upgrade'), ROOT, self.hashes)
        self.assertEqual(result.status, 'installed')
        self.assertEqual(result.identity_preserved, 'verified')
        self.assertEqual(leftover.read_text(), UUID + '\n')

    def test_manual_rollback_path_checks_journal_under_shared_lock(self):
        # Retain the invariant: the manual CLI must check the wizard
        # journal only AFTER taking the same hardened cross-installer lock.
        import inspect
        source = inspect.getsource(core.run_cli)
        under_lock = source[source.index('with open_manual_install_lock(lockfile) as lock:'):]
        self.assertLess(under_lock.index('require_no_wizard_transaction()'),
                        under_lock.index('if args.rollback:'))

    def test_systemd_user_creation_matches_existing_shell_preflight(self):
        operations = installer.SystemdOperations()
        absent = mock.Mock(returncode=2)
        with mock.patch.object(installer.subprocess, 'run',
                               side_effect=[absent, mock.Mock(returncode=0)]) as calls:
            with mock.patch.object(installer.os, 'access', return_value=True):
                operations.ensure_agent_user()
        self.assertEqual(calls.call_count, 2)
        args = calls.call_args_list[1].args[0]
        self.assertEqual(args[0], 'useradd')
        self.assertEqual(args[-1], 'linuxhost')
        self.assertIn('/var/lib/linux-host-agent', args)
        with mock.patch.object(installer.subprocess, 'run',
                               return_value=mock.Mock(returncode=0)) as calls:
            operations.ensure_agent_user()
        self.assertEqual(calls.call_count, 1)

    def test_legacy_v1_installation_is_blocked_before_staging(self):
        app = self.installed_paths().location(core.APP_FILES[0])
        app.parent.mkdir(parents=True, exist_ok=True)
        app.write_bytes(b'PROTOCOL = "linux-host-agent"\nAPI_VERSION = 1\n')
        with self.assertRaises(installer.ControllerError) as caught:
            self.backend.run(self.request(), ROOT, self.hashes)
        self.assertEqual(caught.exception.code, 'unsupported_environment')
        self.assertEqual(app.read_bytes(),
                         b'PROTOCOL = "linux-host-agent"\nAPI_VERSION = 1\n')
        self.assertEqual(self.stage_entries(), [])
        self.assertFalse((self.root / 'var/backups').exists())

    def test_orphaned_state_is_blocked_but_v2_owner_record_allows_reinstall(self):
        private = self.root / 'var/lib/linux-host-agent/installation-id'
        private.parent.mkdir(parents=True, exist_ok=True)
        private.write_text(UUID + '\n')
        private.chmod(0o600)
        with self.assertRaises(installer.ControllerError) as caught:
            self.backend.run(self.request(), ROOT, self.hashes)
        self.assertEqual(caught.exception.code, 'adoption_required')
        self.assertIn('--adopt-retained-state', str(caught.exception))
        core.write_owner_record(self.root)  # Provenance from an earlier v2 install.
        self.assertEqual(self.backend.run(self.request(), ROOT, self.hashes).status,
                         'installed')
        self.assertEqual(private.read_text(), UUID + '\n')

    def test_manual_installer_guard_refuses_after_wizard_crash(self):
        self.assertEqual(core.require_no_wizard_transaction(
            root=self.root, owner_uid=self.uid), None)
        with self.store.begin('install') as transaction:
            with self.assertRaises(core.InstallError):
                core.require_no_wizard_transaction(root=self.root, owner_uid=self.uid)
            transaction.abort()
            transaction.clear_finished()
        self.assertIsNone(core.require_no_wizard_transaction(
            root=self.root, owner_uid=self.uid))

    def test_systemctl_timeout_is_per_operation_and_remains_recoverable(self):
        expired = core.subprocess.TimeoutExpired(
            ['systemctl', 'restart', 'linux-host-agent.service'], 120)
        with mock.patch.object(core.subprocess, 'run',
                               side_effect=expired) as runner:
            with self.assertRaises(core.subprocess.CalledProcessError) as raised:
                core.systemctl('restart', 'linux-host-agent.service')
        self.assertEqual(raised.exception.returncode, 124)
        self.assertEqual(runner.call_args.kwargs['timeout'], 120)
        self.assertEqual(runner.call_args.kwargs['stdin'], core.subprocess.DEVNULL)

    def test_systemctl_timeout_with_check_false_returns_failed_result(self):
        expired = core.subprocess.TimeoutExpired(
            ['systemctl', 'stop', 'linux-host-agent.service'], 120)
        with mock.patch.object(core.subprocess, 'run',
                               side_effect=expired) as runner:
            result = core.systemctl('stop', 'linux-host-agent.service',
                                    check=False)
        self.assertEqual(result.returncode, 124)
        self.assertEqual(result.args,
                         ['systemctl', 'stop', 'linux-host-agent.service'])
        self.assertEqual(result.stderr, '')
        self.assertEqual(runner.call_args.kwargs['timeout'], 120)
        self.assertFalse(runner.call_args.kwargs['check'])

    def test_restore_services_attempts_remaining_units_after_optional_timeout(self):
        calls = []

        def systemd_call(command, **kwargs):
            calls.append(tuple(command))
            self.assertEqual(kwargs['timeout'], 120)
            if command[1:3] == ['disable', 'linux-host-agent.service']:
                raise core.subprocess.TimeoutExpired(command, 120)
            return core.subprocess.CompletedProcess(command, 0, stderr='')

        previous = dict(first_install=False, agent_active=False,
                        agent_enabled=False, socket_active=False,
                        socket_enabled=False)
        with mock.patch.object(core.subprocess, 'run', side_effect=systemd_call):
            core.restore_services(previous)

        self.assertEqual(calls, [
            ('systemctl', 'daemon-reload'),
            ('systemctl', 'disable', 'linux-host-agent.service'),
            ('systemctl', 'stop', 'linux-host-agent.service'),
            ('systemctl', 'disable', 'linux-host-agent-power.socket'),
            ('systemctl', 'stop', 'linux-host-agent-power.socket'),
        ])

    def test_activation_systemctl_timeout_triggers_verified_rollback(self):
        # Transaction-level regression: emulate an actual subprocess timeout
        # DURING activation, after managed files were applied. The durable
        # APPLYING+ journal must drive full file and service restoration.
        old = self.existing_install(active=True, enabled=True)
        before = old.read_bytes()
        original_activate = self.services.activate
        expired = core.subprocess.TimeoutExpired(
            ['systemctl', 'restart', 'linux-host-agent.service'], 120)

        def activate_then_timeout(previous, *, power_enabled, disable_power):
            original_activate(previous, power_enabled=power_enabled,
                              disable_power=disable_power)
            core.systemctl('restart', 'linux-host-agent.service')

        with mock.patch.object(self.services, 'activate',
                               side_effect=activate_then_timeout):
            with mock.patch.object(core.subprocess, 'run',
                                   side_effect=expired):
                with self.assertRaises(installer.ControllerError) as raised:
                    self.backend.run(
                        self.request('upgrade', expected_identity=UUID),
                        ROOT, self.hashes)

        self.assertEqual(raised.exception.code, 'rolled_back')
        self.assertEqual(old.read_bytes(), before)
        self.assertEqual(self.services.restore_calls, 1)
        self.assertTrue(self.services.verify_restored_services(
            self.services.original))
        self.assertEqual(self.store.public_status()[
            'privileged_transaction_state'], 'none')
        self.assertEqual(self.stage_entries(), [])

    def test_shared_core_power_activation_matches_socket_verification(self):
        from unittest.mock import call
        # Enabled but intentionally stopped power socket: enable --now
        # activates AND enables, rather than preserving an inactive socket.
        before = dict(first_install=False, agent_active=False,
                      agent_enabled=False, socket_active=False,
                      socket_enabled=True, newly_enabled_power=False)
        self.assertEqual(core.expected_socket_state(before, power_enabled=True),
                         (True, True))
        with mock.patch.object(core, 'systemctl') as systemctl:
            core.activate(before, power_enabled=True, disable_power=False)
        self.assertIn(call('enable', '--now', 'linux-host-agent-power.socket'),
                      systemctl.call_args_list)
        # A first install with a leftover enabled-power drop-in follows
        # the same rule; the coexistence guard decides if such a partial
        # installation is safe before a real transaction reaches activation.
        fresh = dict(before, first_install=True, socket_enabled=False)
        self.assertEqual(core.expected_socket_state(fresh, power_enabled=True),
                         (True, True))
        with mock.patch.object(core, 'systemctl') as systemctl:
            core.activate(fresh, power_enabled=True, disable_power=False)
        self.assertIn(call('enable', '--now', 'linux-host-agent-power.socket'),
                      systemctl.call_args_list)

    def test_verifier_accepts_existing_enabled_but_stopped_power_socket(self):
        old = self.existing_install(active=False, enabled=False)
        before = dict(first_install=False, agent_active=False,
                      agent_enabled=False, socket_active=False,
                      socket_enabled=True, newly_enabled_power=False)
        ops = installer.SystemdOperations(
            health_probe=mock.Mock(side_effect=AssertionError('stopped agent must not be probed')))
        change = core.Change(core.SYSTEMD_PATHS[0], old.read_bytes())
        def state(unit, command):
            if unit == 'linux-host-agent-power.socket':
                return True
            return False
        with mock.patch.object(core, 'state', side_effect=state):
            self.assertTrue(ops.verify_install(
                self.request('upgrade'), before, [change],
                power_enabled=True, transaction=self.installed_paths()))
        ops.health_probe.assert_not_called()

    def _simulate_crash_at(self, phase, *, fresh=False):
        """Create an authentic, protected journal/stage/snapshot then exit.

        The test process does NOT fork or execute a real installer; closing
        the handles reproduces abrupt process exit and released flocks.
        """
        if not fresh:
            old = self.existing_install(active=True, enabled=True)
            original = old.read_bytes()
            action = 'upgrade'
        else:
            old = None
            original = None
            action = 'install'
        trans = self.installed_paths()
        with self.store.begin(action) as journal:
            receipt = staging.stage_payload(
                ROOT, self.hashes, journal, root=self.root, owner_uid=self.uid)
            try:
                journal.advance('INSPECTED', 'STAGED')
                if phase == 'STAGED':
                    return (old, original, None)
                previous = self.services.capture_previous(trans)
                source = receipt.verified_source_path(self.hashes)
                plan = core.generate_plan(source, '/usr/bin/python3',
                                          enable_power=False, disable_power=False,
                                          wol_interface=None,
                                          is_existing_power=False, avahi_dir=False)
                snapshot = trans.snapshot(plan, previous=previous)
                installer._sync_snapshot(snapshot)
                journal.advance('STAGED', 'SNAPSHOTTED',
                                snapshot_name=snapshot.name)
                if phase == 'SNAPSHOTTED':
                    return (old, original, snapshot)
                journal.advance('SNAPSHOTTED', 'APPLYING')
                # Crash window: first install may NOT have written owner
                # record before the power loss, despite APPLYING journal.
                trans.apply(plan)
                if phase == 'APPLYING':
                    return (old, original, snapshot)
                journal.advance('APPLYING', 'ACTIVATING')
                if phase == 'ACTIVATING':
                    return (old, original, snapshot)
                journal.advance('ACTIVATING', 'VERIFYING')
                return (old, original, snapshot)
            finally:
                receipt.close()

    def test_recovery_on_clean_host_is_an_explicit_no_op(self):
        result = self.backend.recover_interrupted()
        self.assertEqual(result.status, 'nothing_to_recover')
        self.assertFalse((self.root / 'var/backups').exists())

    def test_recover_orphaned_first_journal_write_cleans_without_mutation(self):
        # Failed first INSPECTED write leaves a root-owned temp but no
        # journal.json. Nothing has been staged or applied. -recover must
        # make progress without requiring manual deletion of protected files.
        old = self.existing_install()
        original = old.read_bytes()
        with mock.patch.object(journal.os, 'replace',
                               side_effect=OSError('simulated initial EIO')):
            with self.assertRaises(journal.UnsafeJournal):
                self.store.begin('upgrade')
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'recovery_required')
        self.assertFalse((self.store.root /
                          'var/backups/linux-host-agent/wizard-transactions/journal.json'
                          ).exists())
        result = self.backend.recover_interrupted()
        self.assertEqual(result.status, 'cleaned')
        self.assertEqual(old.read_bytes(), original)
        self.assertEqual(self.services.activations, [])
        self.assertEqual(self.services.restore_calls, 0)
        self.assertEqual(self.services.verify_calls, 0)
        self.assertEqual(self.stage_entries(), [])
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'none')
        # Recovery is idempotent and new explicit upgrades are permitted.
        self.assertEqual(self.backend.recover_interrupted().status,
                         'nothing_to_recover')
        self.assertEqual(self.backend.run(
            self.request('upgrade', expected_identity=UUID),
            ROOT, self.hashes).status, 'installed')

    def test_recover_rejects_orphaned_applied_phase_without_journal(self):
        # A corrupted state containing a valid APPLYING temp record but no
        # journal.json cannot be cleared just because staging is empty.
        old = self.existing_install()
        previous = old.read_bytes()
        with mock.patch.object(journal.os, 'replace',
                               side_effect=OSError('simulated initial EIO')):
            with self.assertRaises(journal.UnsafeJournal):
                self.store.begin('upgrade')
        directory = self.root / 'var/backups/linux-host-agent/wizard-transactions'
        marker, = directory.glob('.wizard-journal-*')
        record = dict(schema=1, transaction_id='a' * 32, operation='upgrade',
                      phase='APPLYING', snapshot_name='snapshot-abcdefgh')
        marker.write_text(json.dumps(record, sort_keys=True,
                                     separators=(',', ':')) + '\n')

        with self.assertRaises(installer.ControllerError) as error:
            self.backend.recover_interrupted()
        self.assertEqual(error.exception.code, 'recovery_required')
        self.assertTrue(marker.exists())
        self.assertEqual(old.read_bytes(), previous)
        self.assertEqual(self.services.restore_calls, 0)
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'recovery_required')

    def test_orphaned_journal_with_staged_payload_remains_blocked(self):
        with mock.patch.object(journal.os, 'replace',
                               side_effect=OSError('simulated initial EIO')):
            with self.assertRaises(journal.UnsafeJournal):
                self.store.begin('install')
        stage_parent = self.root / 'var/lib/computer-host-installer'
        stage_parent.mkdir(parents=True, mode=0o700)
        stage_parent.chmod(0o700)
        stage_dir = stage_parent / 'staging'
        stage_dir.mkdir(mode=0o700)
        retained = stage_dir / ('pending-' + 'a' * 32)
        retained.mkdir(mode=0o700)
        with self.assertRaises(installer.ControllerError) as err:
            self.backend.recover_interrupted()
        self.assertEqual(err.exception.code, 'recovery_required')
        self.assertTrue(retained.is_dir())
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'recovery_required')

    def test_multiple_orphaned_journal_markers_remain_ambiguous(self):
        with mock.patch.object(journal.os, 'replace',
                               side_effect=OSError('simulated initial EIO')):
            with self.assertRaises(journal.UnsafeJournal):
                self.store.begin('install')
        directory = self.root / 'var/backups/linux-host-agent/wizard-transactions'
        extra = directory / ('.wizard-journal-' + 'c' * 32)
        extra.write_bytes(b'invalid extra marker')
        extra.chmod(0o600)
        with self.assertRaises(installer.ControllerError) as err:
            self.backend.recover_interrupted()
        self.assertEqual(err.exception.code, 'recovery_required')
        self.assertTrue(extra.exists())
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'recovery_required')

    def test_recover_staged_preapply_does_not_mutate_managed_files(self):
        old, original, _ = self._simulate_crash_at('STAGED')
        result = self.backend.recover_interrupted()
        self.assertEqual(result.status, 'aborted')
        self.assertEqual(result.previous_phase, 'STAGED')
        self.assertEqual(old.read_bytes(), original)
        self.assertFalse(self.stage_entries())
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'none')

    def test_recover_snapshotted_preapply(self):
        old, original, _ = self._simulate_crash_at('SNAPSHOTTED')
        result = self.backend.recover_interrupted()
        self.assertEqual(result.status, 'aborted')
        self.assertEqual(old.read_bytes(), original)
        self.assertFalse(self.stage_entries())
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'none')

    def test_recover_applied_interruption_restores_previous_files(self):
        for phase in ('APPLYING', 'ACTIVATING', 'VERIFYING'):
            with self.subTest(phase=phase):
                old, original, _ = self._simulate_crash_at(phase)
                self.assertNotEqual(old.read_bytes(), original)
                with self.assertRaises(journal.JournalConflict):
                    self.store.begin('repair')
                result = self.backend.recover_interrupted()
                self.assertEqual(result.status, 'rolled_back')
                self.assertEqual(result.previous_phase, phase)
                self.assertEqual(old.read_bytes(), original)
                self.assertEqual(self.services.restore_calls, 1)
                self.assertEqual(self.stage_entries(), [])
                self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                                 'none')

    def test_recover_first_install_crash_before_owner_record(self):
        _, _, _ = self._simulate_crash_at('APPLYING', fresh=True)
        self.assertFalse(core.owner_record_exists(self.root))
        self.assertTrue(self.installed_paths().location(core.APP_FILES[0]).exists())
        done = self.backend.recover_interrupted()
        self.assertEqual(done.status, 'rolled_back')
        self.assertFalse(self.installed_paths().location(core.APP_FILES[0]).exists())
        self.assertTrue(core.owner_record_exists(self.root))
        self.assertFalse(self.stage_entries())
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'none')
        # Retry is permitted without adopting an unknown retained state.
        self.assertEqual(self.backend.run(self.request(), ROOT, self.hashes).status,
                         'installed')

    def test_recovery_refuses_missing_or_unsafe_snapshot_without_mutating(self):
        old, _, snapshot = self._simulate_crash_at('ACTIVATING')
        damaged = old.read_bytes()
        (snapshot / 'manifest.json').unlink()
        with self.assertRaises(installer.ControllerError) as error:
            self.backend.recover_interrupted()
        self.assertEqual(error.exception.code, 'recovery_required')
        self.assertEqual(old.read_bytes(), damaged)
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'recovery_required')
        self.assertEqual(len(self.stage_entries()), 1)

    def test_recovery_failure_does_not_clear_applied_journal(self):
        old, original, _ = self._simulate_crash_at('VERIFYING')
        damaged = old.read_bytes()
        self.services.fail_restore = True
        with self.assertRaises(installer.ControllerError) as error:
            self.backend.recover_interrupted()
        self.assertEqual(error.exception.code, 'recovery_required')
        # File restoration may have succeeded before systemd restoration
        # failed. It must retain the journal until BOTH are verified.
        self.assertNotEqual(damaged, original)
        self.assertEqual(old.read_bytes(), original)
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'recovery_required')
        self.services.fail_restore = False
        self.assertEqual(self.backend.recover_interrupted().status, 'rolled_back')
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'none')

    def test_recovery_only_cleans_terminal_stage_without_reinstalling(self):
        with mock.patch.object(staging, 'finish_terminal_stage',
                               side_effect=staging.StagingError('fixture failure')):
            result = self.backend.run(self.request(), ROOT, self.hashes)
        self.assertEqual(result.status, 'installed_cleanup_required')
        before = self.services.verify_calls
        completed = self.backend.recover_interrupted()
        self.assertEqual(completed.status, 'cleaned')
        self.assertEqual(self.services.verify_calls, before)
        self.assertFalse(self.stage_entries())

    def test_legacy_manual_lock_mode_0644_is_accepted(self):
        self.manual_lock.touch(mode=0o600)
        self.manual_lock.chmod(0o644)
        result = self.backend.run(self.request(), ROOT, self.hashes)
        self.assertEqual(result.status, 'installed')
        self.assertEqual(stat.S_IMODE(self.manual_lock.stat().st_mode), 0o644)


if __name__ == '__main__':
    unittest.main()
