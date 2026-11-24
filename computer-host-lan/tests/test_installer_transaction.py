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

    def prepare_restore(self, previous):
        pass

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
        # Fixture account, never an override of live account resolution.
        self.backend._observe_credentials = lambda: installer.continuity.observe(
            self.root, owner_uid=self.uid, account=(self.uid, os.getegid()))
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
        private.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        private.write_text(UUID + '\n')
        private.chmod(0o600)
        return target

    def stage_entries(self):
        if not self.staging_dir.is_dir():
            return []
        return sorted(x.name for x in self.staging_dir.iterdir() if x.name != 'stage.lock')

    def continuity_fixture(self, *, active=True):
        target = self.existing_install(active=active, enabled=active)
        token = self.root / 'var/lib/linux-host-agent/control-token'
        token.write_bytes(b'x' * 64)
        token.chmod(0o600)
        return target, token

    def test_continuity_rejects_token_rewrite_during_active_upgrade(self):
        target, token = self.continuity_fixture()
        activate = self.services.activate

        def rewrite(*args, **kwargs):
            activate(*args, **kwargs)
            token.write_bytes(b'y' * 64)

        with mock.patch.object(self.services, 'activate', side_effect=rewrite):
            with self.assertRaises(installer.ControllerError) as caught:
                self.backend.run(self.request('upgrade'), ROOT, self.hashes)
        self.assertEqual(caught.exception.code, 'recovery_required')
        self.assertEqual(caught.exception.credential_result.reason,
                         'credential_continuity_unverified')
        self.assertEqual(self.services.restore_calls, 1)
        self.assertEqual(target.read_text(), 'ORIGINAL-UNIT-CONTENTS')
        self.assertEqual(token.read_bytes(), b'y' * 64)
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'recovery_required')
        recovered = self.backend.recover_interrupted()
        self.assertEqual(recovered.status, 'rolled_back')
        self.assertEqual(recovered.credential_result.public(), dict(
            installation_id_continuity='not_verified',
            control_token_continuity='not_verified', credential_continuity='not_verified',
            continuity_reason='continuity_unverified_after_interruption'))
        self.assertEqual(token.read_bytes(), b'y' * 64)

    def test_continuity_rejects_uuid_rewrite_during_stopped_upgrade(self):
        self.continuity_fixture(active=False)
        identity = self.root / 'var/lib/linux-host-agent/installation-id'
        replacement = b'22345678-1234-4234-8234-123456789abc\n'
        with mock.patch.object(self.services, 'verify_install', side_effect=lambda *a, **kw:
                               bool(identity.write_bytes(replacement))):
            with self.assertRaises(installer.ControllerError) as caught:
                self.backend.run(self.request('upgrade'), ROOT, self.hashes)
        self.assertEqual(caught.exception.code, 'recovery_required')
        self.assertEqual(caught.exception.credential_result.reason,
                         'credential_continuity_unverified')
        self.assertEqual(identity.read_bytes(), replacement)
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'recovery_required')

    def test_continuity_rejects_token_rewrite_during_uninstall(self):
        target, token = self.continuity_fixture()
        with mock.patch.object(self.services, 'reload_after_uninstall',
                               side_effect=lambda: token.write_bytes(b'z' * 64)):
            with self.assertRaises(installer.ControllerError) as caught:
                self.backend.uninstall()
        self.assertEqual(caught.exception.code, 'recovery_required')
        self.assertEqual(caught.exception.credential_result.reason,
                         'credential_continuity_unverified')
        self.assertEqual(target.read_text(), 'ORIGINAL-UNIT-CONTENTS')
        self.assertEqual(token.read_bytes(), b'z' * 64)
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'recovery_required')

    def test_continuity_rejects_token_rewrite_during_rollback(self):
        target, token = self.continuity_fixture()
        self.services.fail_verify = True
        restore = self.services.restore_services

        def rewrite(previous):
            restore(previous)
            token.write_bytes(b'z' * 64)

        with mock.patch.object(self.services, 'restore_services', side_effect=rewrite):
            with self.assertRaises(installer.ControllerError) as caught:
                self.backend.run(self.request('upgrade'), ROOT, self.hashes)
        self.assertEqual(caught.exception.code, 'recovery_required')
        self.assertEqual(caught.exception.credential_result.reason,
                         'credential_continuity_unverified')
        self.assertEqual(target.read_text(), 'ORIGINAL-UNIT-CONTENTS')
        self.assertEqual(token.read_bytes(), b'z' * 64)
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'recovery_required')

    def test_continuity_preapply_mismatch_aborts_without_managed_mutation(self):
        target, token = self.continuity_fixture()
        sync = installer._sync_snapshot

        def rewrite(backup):
            sync(backup)
            token.chmod(0o400)

        with mock.patch.object(installer, '_sync_snapshot', side_effect=rewrite):
            with self.assertRaises(installer.ControllerError) as caught:
                self.backend.run(self.request('upgrade'), ROOT, self.hashes)
        self.assertEqual(caught.exception.code, 'aborted')
        self.assertEqual(caught.exception.credential_result.reason,
                         'credential_continuity_unverified')
        self.assertEqual(self.services.user_preflights, 0)
        self.assertEqual(target.read_text(), 'ORIGINAL-UNIT-CONTENTS')
        self.assertEqual(self.store.public_status()['privileged_transaction_state'], 'none')

    def test_continuity_stopped_upgrade_and_uninstall_verify_both(self):
        self.continuity_fixture(active=False)
        result = self.backend.run(self.request('upgrade'), ROOT, self.hashes)
        self.assertEqual(result.identity_preserved, 'not_verified')
        self.assertEqual(result.credential_result, installer.continuity.Result('verified', 'verified'))
        removed = self.backend.uninstall()
        self.assertEqual(removed.credential_result, installer.continuity.Result('verified', 'verified'))

    def test_continuity_private_executable_modes_survive_lifecycle(self):
        _, token = self.continuity_fixture(active=False)
        identity = token.with_name('installation-id')
        identity.chmod(0o500)
        token.chmod(0o700)
        for operation in ('upgrade', 'repair'):
            result = self.backend.run(self.request(operation), ROOT, self.hashes)
            self.assertEqual(result.credential_result,
                             installer.continuity.Result('verified', 'verified'))
        result = self.backend.uninstall()
        self.assertEqual(result.credential_result,
                         installer.continuity.Result('verified', 'verified'))
        self.assertEqual(stat.S_IMODE(identity.stat().st_mode), 0o500)
        self.assertEqual(stat.S_IMODE(token.stat().st_mode), 0o700)

    def test_continuity_first_start_reports_new_not_preserved(self):
        identity = self.root / 'var/lib/linux-host-agent/installation-id'
        token = identity.with_name('control-token')
        activate = self.services.activate

        def create(*args, **kwargs):
            activate(*args, **kwargs)
            identity.parent.mkdir(mode=0o700, parents=True)
            identity.write_text(UUID + '\n')
            identity.chmod(0o600)
            token.write_bytes(b'x' * 64)
            token.chmod(0o600)

        with mock.patch.object(self.services, 'activate', side_effect=create):
            result = self.backend.run(self.request(), ROOT, self.hashes)
        self.assertEqual(result.credential_result,
                         installer.continuity.Result('newly_present', 'newly_present'))
        self.assertEqual(result.credential_result.public()['credential_continuity'], 'not_verified')

    def test_continuity_clean_same_process_rollback_reports_metadata(self):
        self.continuity_fixture()
        self.services.fail_verify = True
        with self.assertRaises(installer.ControllerError) as caught:
            self.backend.run(self.request('upgrade'), ROOT, self.hashes)
        self.assertEqual(caught.exception.code, 'rolled_back')
        self.assertEqual(caught.exception.credential_result,
                         installer.continuity.Result('verified', 'verified'))
        self.assertEqual(self.store.public_status()['privileged_transaction_state'], 'none')

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
                call('reset-failed', 'linux-host-agent-power.socket', check=False),
                call('reset-failed', 'linux-host-agent-power.service', check=False),
                call('reset-failed', 'linux-host-agent.service', check=False),
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
                         'SubState=dead', 'UnitFileState=disabled', ''))
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

    def test_managed_directory_sync_walks_existing_ancestors_bottom_up(self):
        trans = self.installed_paths()
        changes = [core.Change(core.POWER_DROPIN, b'fixture'),
                   core.Change(core.WOL_DROPIN, None),
                   core.Change(core.APP_FILES[0], b'fixture'),
                   core.Change(core.AVAHI_PATH, None)]
        trans.apply(changes)
        expected = (
            'etc/systemd/system/linux-host-agent.service.d',
            'etc/systemd/system', 'opt/linux-host-agent',
            'etc/systemd', 'etc', 'opt', '.',
        )
        # Map descriptors by inode rather than assuming fd numbering.
        by_identity = {}
        for name in expected:
            info = (self.root / name).stat()
            by_identity[(info.st_dev, info.st_ino)] = name
        synced = []
        real_fsync = os.fsync

        def observe(fd):
            info = os.fstat(fd)
            synced.append(by_identity[(info.st_dev, info.st_ino)])
            real_fsync(fd)

        with mock.patch.object(installer.os, 'fsync', side_effect=observe):
            installer._sync_managed_directories(changes, trans)
        self.assertEqual(len(synced), len(expected))
        self.assertEqual(set(synced), set(expected))
        for name in expected:
            if name != '.':
                parent = str(Path(name).parent)
                self.assertLess(synced.index(name), synced.index(parent))
        self.assertFalse((self.root / 'etc/avahi').exists())

    def test_managed_directory_sync_refuses_symlink_even_if_dangling(self):
        trans = self.installed_paths()
        target = trans.location(core.POWER_DROPIN)
        target.parent.parent.mkdir(parents=True)
        target.parent.symlink_to(self.root / 'absent', target_is_directory=True)
        with self.assertRaises(OSError):
            installer._sync_managed_directories(
                [core.Change(core.POWER_DROPIN, None)], trans)
        self.assertTrue(target.parent.is_symlink())

    def test_forward_ancestor_sync_precedes_committed(self):
        ancestor = self.root / 'etc'
        synced = []
        real_fsync = os.fsync
        real_advance = journal.TransactionHandle.advance

        def observe_sync(fd):
            info = os.fstat(fd)
            if ancestor.exists():
                target = ancestor.stat()
                if (info.st_dev, info.st_ino) == (target.st_dev, target.st_ino):
                    synced.append(True)
            real_fsync(fd)

        def observe_advance(handle, previous, next_phase, **kwargs):
            if next_phase == 'COMMITTED':
                self.assertTrue(synced)
            return real_advance(handle, previous, next_phase, **kwargs)

        with (
            mock.patch.object(installer.os, 'fsync', side_effect=observe_sync),
            mock.patch.object(journal.TransactionHandle, 'advance',
                              new=observe_advance),
        ):
            result = self.backend.run(self.request(enable_power=True),
                                      ROOT, self.hashes)
        self.assertEqual(result.status, 'installed')
        self.assertTrue(synced)
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'none')

    def test_forward_ancestor_sync_failure_and_recovery_retry(self):
        # The service drop-in and app directories are new on this fixture.
        # Fail fsync specifically on the managed /etc ancestor, not a
        # file or a journal directory. The same failure during rollback
        # must retain the applied journal; explicit recovery retries it.
        ancestor = self.root / 'etc'
        real_fsync = os.fsync
        failures = []

        def fail_ancestor(fd):
            info = os.fstat(fd)
            if ancestor.exists():
                target = ancestor.stat()
                if (info.st_dev, info.st_ino) == (target.st_dev, target.st_ino):
                    failures.append(True)
                    raise OSError('fixture ancestor directory fsync failure')
            real_fsync(fd)

        with mock.patch.object(installer.os, 'fsync', side_effect=fail_ancestor):
            with self.assertRaises(installer.ControllerError) as error:
                self.backend.run(self.request(enable_power=True), ROOT, self.hashes)
            self.assertEqual(error.exception.code, 'recovery_required')
            self.assertGreaterEqual(len(failures), 2)
            self.assertFalse(self.services.activations)
            self.assertEqual(self.store.public_status()[
                'privileged_transaction_state'], 'recovery_required')
            self.assertEqual(len(self.stage_entries()), 1)
        self.assertEqual(self.backend.recover_interrupted().status, 'rolled_back')
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'none')
        self.assertEqual(self.stage_entries(), [])
        self.assertFalse(self.installed_paths().location(core.APP_FILES[0]).exists())

    def test_upgrade_rollback_syncs_snapshot_parents_before_terminal_record(self):
        old = self.existing_install()
        original = old.read_bytes()
        self.services.fail_verify = True
        real_sync = installer._sync_managed_directories
        real_mark = journal.TransactionHandle.mark_rolled_back
        synced = []

        def observe_sync(changes, transaction):
            real_sync(changes, transaction)
            if self.services.restore_calls:
                self.assertEqual(old.read_bytes(), original)
                synced.append({change.path for change in changes})

        def observe_mark(handle, verify_restored):
            record = handle._record()
            manifest = json.loads((self.root / core.BACKUP_BASE.lstrip('/') /
                                   record['snapshot_name'] /
                                   'manifest.json').read_text())
            self.assertEqual(synced, [{item['path'] for item in manifest['items']}])
            return real_mark(handle, verify_restored)

        with (
            mock.patch.object(installer, '_sync_managed_directories',
                              side_effect=observe_sync),
            mock.patch.object(journal.TransactionHandle, 'mark_rolled_back',
                              new=observe_mark),
        ):
            with self.assertRaises(installer.ControllerError) as error:
                self.backend.run(self.request('upgrade', expected_identity=UUID),
                                 ROOT, self.hashes)
        self.assertEqual(error.exception.code, 'rolled_back')
        self.assertEqual(len(synced), 1)
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'none')

    def test_rollback_directory_sync_failure_retains_journal_for_recovery(self):
        old = self.existing_install()
        original = old.read_bytes()
        self.services.fail_verify = True
        real_sync = installer._sync_managed_directories

        def fail_restored_sync(changes, transaction):
            if self.services.restore_calls:
                raise OSError('fixture directory fsync failure')
            real_sync(changes, transaction)

        with mock.patch.object(installer, '_sync_managed_directories',
                               side_effect=fail_restored_sync):
            with self.assertRaises(installer.ControllerError) as error:
                self.backend.run(self.request('upgrade', expected_identity=UUID),
                                 ROOT, self.hashes)
            self.assertEqual(error.exception.code, 'recovery_required')
            self.assertEqual(old.read_bytes(), original)
            self.assertEqual(self.store.public_status()[
                'privileged_transaction_state'], 'recovery_required')
            self.assertEqual(len(self.stage_entries()), 1)
            with self.assertRaises(installer.ControllerError) as error:
                self.backend.recover_interrupted()
            self.assertEqual(error.exception.code, 'recovery_required')
            self.assertEqual(self.store.public_status()[
                'privileged_transaction_state'], 'recovery_required')

        self.assertEqual(self.backend.recover_interrupted().status, 'rolled_back')
        self.assertEqual(old.read_bytes(), original)
        self.assertEqual(self.stage_entries(), [])
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'none')

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

    def test_protected_snapshot_provenance_is_durable_before_apply(self):
        self.existing_install()
        real_advance = journal.TransactionHandle.advance
        checked = []

        def advance(handle, previous, next_phase, **kwargs):
            if next_phase == 'SNAPSHOTTED':
                name = kwargs['snapshot_name']
                base = self.root / core.BACKUP_BASE.lstrip('/')
                backup = base / name
                path = base / ('.' + name + '.protected.json')
                evidence = json.loads(path.read_text())
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(evidence['origin'], 'protected_before_state')
                self.assertEqual(evidence['capture_phase'], 'STAGED')
                self.assertEqual(evidence['transaction_id'], handle.transaction_id)
                self.assertEqual(evidence['snapshot_name'], name)
                self.assertEqual(evidence['operation'], 'upgrade')
                self.assertEqual(evidence['coverage'], 'partial')
                self.assertEqual(evidence['release_authenticity'], 'not_verified')
                self.assertEqual(evidence['manifest_sha256'], hashlib.sha256(
                    (backup / 'manifest.json').read_bytes()).hexdigest())
                manifest = json.loads((backup / 'manifest.json').read_text())
                self.assertEqual(evidence['previous'], manifest['previous'])
                self.assertEqual(evidence['file_sha256'], {
                    item['path']: hashlib.sha256(
                        (backup / item['file']).read_bytes()).hexdigest()
                    for item in manifest['items'] if item['existed']})
                self.assertEqual(evidence['copy_modes'], {
                    item['path']: stat.S_IMODE((backup / item['file']).stat().st_mode)
                    for item in manifest['items'] if item['existed']})
                self.assertEqual(evidence['captured_paths'],
                                 sorted(item['path'] for item in manifest['items']))
                self.assertIsNotNone(evidence['agent_version'])
                self.assertFalse(any(p.name.endswith('.protected.json')
                                     for p in backup.iterdir()))
                checked.append(name)
            return real_advance(handle, previous, next_phase, **kwargs)

        with mock.patch.object(journal.TransactionHandle, 'advance', new=advance):
            result = self.backend.run(self.request('upgrade'), ROOT, self.hashes)
        self.assertEqual(result.status, 'installed')
        self.assertEqual(len(checked), 1)

    def test_provenance_does_not_prevent_repairing_loose_managed_modes(self):
        import historical_snapshot as historical
        for operation, mode in (('upgrade', 0o664), ('repair', 0o646)):
            with self.subTest(operation=operation, mode=oct(mode)):
                self.existing_install()
                avahi = self.installed_paths().location(core.AVAHI_PATH)
                avahi.parent.mkdir(parents=True, exist_ok=True)
                changes = core.generate_plan(
                    ROOT, '/usr/bin/python3', enable_power=True, disable_power=False,
                    wol_interface='eth0', is_existing_power=False, avahi_dir=True)
                self.assertEqual({change.path for change in changes}, core.MANAGED_PATHS)
                self.installed_paths().apply(changes)
                avahi.chmod(mode)
                expected = {change.path: hashlib.sha256(change.content).hexdigest()
                            for change in changes}
                version, = installer._PROVENANCE_VERSION.findall(
                    next(change.content for change in changes
                         if change.path == core.APP_FILES[0]))
                base = self.root / core.BACKUP_BASE.lstrip('/')
                before = set(base.glob('snapshot-*'))
                result = self.backend.run(self.request(
                    operation, enable_power=True, wol_interface='eth0'),
                    ROOT, self.hashes)
                self.assertEqual(result.status, 'installed')
                self.assertEqual(stat.S_IMODE(avahi.stat().st_mode), 0o644)
                backup, = set(base.glob('snapshot-*')) - before
                evidence = json.loads((base / ('.' + backup.name + '.protected.json')).read_text())
                self.assertEqual(evidence['coverage'], 'complete')
                self.assertEqual(evidence['copy_modes'][core.AVAHI_PATH], mode)
                manifest = json.loads((backup / 'manifest.json').read_text())
                item = next(item for item in manifest['items']
                            if item['path'] == core.AVAHI_PATH)
                self.assertEqual(item['mode'], mode)
                self.assertEqual(stat.S_IMODE((backup / item['file']).stat().st_mode), mode)
                core.validate_v2_backup(backup, root=self.root)
                with self.assertRaisesRegex(historical.SnapshotEligibilityError,
                                            'invalid_snapshot_metadata'):
                    historical.inspect_protected_candidate(
                        self.root, backup.name, expected_file_hashes=expected,
                        expected_agent_version=version.decode('ascii'),
                        owner_uid=self.uid, owner_gid=os.getegid())
                self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                                 'none')

    def test_uninstall_provenance_preserves_complete_coverage_not_eligibility(self):
        self.existing_install()
        self.assertEqual(self.backend.uninstall().status, 'uninstalled')
        base = self.root / core.BACKUP_BASE.lstrip('/')
        backup, = base.glob('snapshot-*')
        receipt = json.loads((base / ('.' + backup.name + '.protected.json')).read_text())
        self.assertEqual(receipt['operation'], 'uninstall')
        self.assertEqual(receipt['coverage'], 'complete')
        self.assertEqual(set(receipt['captured_paths']), core.MANAGED_PATHS)
        # Complete coverage does not imply every required installed file
        # was present or that old executable bytes are authenticated.
        self.assertNotIn(core.APP_FILES[1], receipt['file_sha256'])
        self.assertEqual(receipt['release_authenticity'], 'not_verified')
        core.validate_v2_backup(backup, root=self.root)

    def test_protected_writer_and_reader_agree_on_complete_snapshot(self):
        import historical_snapshot as historical
        self.existing_install()
        # Independent expected bytes come from the fixture's reviewed
        # source and rendered plan, not from the historical receipt.
        changes = core.generate_plan(
            ROOT, '/usr/bin/python3', enable_power=True, disable_power=False,
            wol_interface='eth0', is_existing_power=False, avahi_dir=True)
        self.assertEqual({change.path for change in changes}, core.MANAGED_PATHS)
        self.installed_paths().apply(changes)
        expected = {change.path: hashlib.sha256(change.content).hexdigest()
                    for change in changes}
        version, = installer._PROVENANCE_VERSION.findall(
            next(change.content for change in changes
                 if change.path == core.APP_FILES[0]))
        self.assertEqual(self.backend.uninstall().status, 'uninstalled')
        base = self.root / core.BACKUP_BASE.lstrip('/')
        backup, = base.glob('snapshot-*')
        candidate = historical.inspect_protected_candidate(
            self.root, backup.name, expected_file_hashes=expected,
            expected_agent_version=version.decode('ascii'),
            owner_uid=self.uid, owner_gid=os.getegid())
        self.assertEqual({item.path: item.content for item in candidate.files},
                         {change.path: change.content for change in changes})
        # Old rollback remains independent of the receipt.
        (base / ('.' + backup.name + '.protected.json')).unlink()
        core.validate_v2_backup(backup, root=self.root)
        with self.assertRaises(historical.SnapshotEligibilityError):
            historical.inspect_protected_candidate(
                self.root, backup.name, expected_file_hashes=expected,
                expected_agent_version=version.decode('ascii'),
                owner_uid=self.uid, owner_gid=os.getegid())

    def test_receipt_link_failure_leaves_only_original_snapshot(self):
        old = self.existing_install()
        original = old.read_bytes()
        real_link = os.link

        def refuse_receipt(src, dst, *args, **kwargs):
            if str(dst).endswith('.protected.json'):
                raise OSError('fixture receipt link failure')
            return real_link(src, dst, *args, **kwargs)

        with mock.patch.object(installer.os, 'link', side_effect=refuse_receipt):
            with self.assertRaises(installer.ControllerError) as caught:
                self.backend.run(self.request('upgrade'), ROOT, self.hashes)
        self.assertEqual(caught.exception.code, 'aborted')
        self.assertEqual(caught.exception.failure_stage, 'snapshot')
        base = self.root / core.BACKUP_BASE.lstrip('/')
        self.assertFalse(list(base.glob('.*.protected.json')))
        self.assertFalse(list(base.glob('.snapshot-provenance-*')))
        backup, = base.glob('snapshot-*')
        core.validate_v2_backup(backup, root=self.root)
        self.assertEqual(old.read_bytes(), original)
        self.assertFalse(self.services.activations)

    def test_provenance_publication_failure_aborts_before_managed_mutation(self):
        old = self.existing_install()
        original = old.read_bytes()
        with mock.patch.object(installer, '_snapshot_provenance',
                               side_effect=OSError('fixture receipt failure')):
            with self.assertRaises(installer.ControllerError) as caught:
                self.backend.run(self.request('upgrade'), ROOT, self.hashes)
        self.assertEqual(caught.exception.code, 'aborted')
        self.assertEqual(caught.exception.failure_stage, 'snapshot')
        self.assertEqual(old.read_bytes(), original)
        self.assertFalse(self.services.activations)
        self.assertEqual(self.services.user_preflights, 0)
        self.assertEqual(self.store.public_status()['privileged_transaction_state'], 'none')

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

    def test_capture_clean_host_requires_explicit_absence(self):
        ops = installer.SystemdOperations()
        absent = dict(LoadState='not-found', ActiveState='inactive', UnitFileState='')
        with mock.patch.object(ops, '_uninstall_unit_state', return_value=absent):
            result = ops.capture_previous(self.installed_paths())
        self.assertEqual(result, dict(first_install=True, agent_active=False,
                                     agent_enabled=False, socket_active=False,
                                     socket_enabled=False))
        for state in (None, dict(LoadState='loaded', ActiveState='inactive',
                                 UnitFileState='disabled')):
            with self.subTest(state=state):
                with mock.patch.object(ops, '_uninstall_unit_state', return_value=state):
                    with self.assertRaises(installer.ControllerError):
                        ops.capture_previous(self.installed_paths())

    def test_capture_existing_requires_stable_persistent_states(self):
        self.existing_install()
        ops = installer.SystemdOperations()
        active = dict(LoadState='loaded', ActiveState='active', UnitFileState='enabled')
        inactive = dict(LoadState='loaded', ActiveState='inactive', UnitFileState='disabled')
        with mock.patch.object(ops, '_uninstall_unit_state',
                               side_effect=[active, inactive]):
            self.assertEqual(ops.capture_previous(self.installed_paths()),
                             dict(first_install=False, agent_active=True,
                                  agent_enabled=True, socket_active=False,
                                  socket_enabled=False))
        for state in (None, dict(inactive, LoadState='not-found'),
                      dict(inactive, ActiveState='activating', SubState='start'),
                      dict(inactive, ActiveState='deactivating'),
                      dict(inactive, UnitFileState='masked'),
                      dict(inactive, UnitFileState='enabled-runtime'),
                      dict(inactive, UnitFileState='static'),
                      dict(inactive, UnitFileState='')):
            with self.subTest(state=state):
                with mock.patch.object(ops, '_uninstall_unit_state',
                                       side_effect=[active, state]):
                    with self.assertRaises(installer.ControllerError):
                        ops.capture_previous(self.installed_paths())

    def test_capture_failed_or_auto_restart_agent_retries_but_normalizes_rollback(self):
        self.existing_install()
        ops = installer.SystemdOperations()
        inactive = dict(LoadState='loaded', ActiveState='inactive',
                        SubState='dead', UnitFileState='disabled')
        for state, substate in (('failed', 'failed'),
                                ('activating', 'auto-restart'),
                                ('activating', 'auto-restart-queued')):
            for enabled in ('enabled', 'disabled'):
                broken = dict(inactive, ActiveState=state, SubState=substate,
                              UnitFileState=enabled)
                with self.subTest(state=state, enabled=enabled):
                    with mock.patch.object(ops, '_uninstall_unit_state',
                                           side_effect=[broken, inactive]):
                        previous = ops.capture_previous(self.installed_paths())
                    self.assertFalse(previous['agent_active'])
                    self.assertEqual(previous['agent_enabled'], enabled == 'enabled')
                    self.assertTrue(previous['agent_retry'])
                    with mock.patch.object(core, 'systemctl') as ctl:
                        ops.activate(previous, power_enabled=False, disable_power=False)
                    calls = ctl.call_args_list
                    self.assertLess(calls.index(mock.call('stop', 'linux-host-agent.service')),
                                    calls.index(mock.call('reset-failed', 'linux-host-agent.service',
                                                          check=False)))
                    self.assertIn(mock.call('restart', 'linux-host-agent.service'), calls)
                    self.assertFalse(previous['agent_active'])

    def test_fresh_rollback_disables_before_removal_and_clears_failed_units(self):
        ops = installer.SystemdOperations()
        stopped = dict(LoadState='loaded', ActiveState='inactive',
                       SubState='dead', UnitFileState='disabled')
        absent = dict(LoadState='not-found', ActiveState='inactive',
                      SubState='dead', UnitFileState='')
        previous = dict(first_install=True, agent_active=False, agent_enabled=False,
                        socket_active=False, socket_enabled=False)
        with mock.patch.object(core, 'systemctl') as ctl:
            with mock.patch.object(ops, '_uninstall_unit_state', return_value=stopped):
                ops.prepare_restore(previous)
            self.assertIn(mock.call('disable', '--now', 'linux-host-agent.service',
                                    check=False), ctl.call_args_list)
            self.assertIn(mock.call('reset-failed', 'linux-host-agent.service',
                                    check=False), ctl.call_args_list)
            ops.restore_services(previous)
            self.assertEqual(ctl.call_args_list.count(
                mock.call('reset-failed', 'linux-host-agent.service', check=False)), 3)
        with mock.patch.object(ops, '_uninstall_unit_state', return_value=absent):
            self.assertTrue(ops.verify_restored_services(previous))
        with mock.patch.object(ops, '_uninstall_unit_state',
                               return_value=dict(stopped, ActiveState='failed')):
            with mock.patch.object(core, 'systemctl'):
                with self.assertRaises(installer.ControllerError):
                    ops.prepare_restore(previous)

    def _failed_unit_fixture(self, *, existing, fail_activation=False):
        """Run the real controller and SystemdOperations against fake systemd.

        Model the troublesome case where stopping a failed unit does not
        clear failure state and disable only removes links while loaded.
        """
        agent, helper, socket = (Path(path).name for path in core.SYSTEMD_PATHS)
        paths = {Path(path).name: self.installed_paths().location(path)
                 for path in core.SYSTEMD_PATHS}
        if existing:
            self.existing_install()
            for unit in (helper, socket):
                paths[unit].write_text('fixture unit')
        states = {unit: 'inactive' for unit in paths}
        enabled = {unit: False for unit in paths}
        if existing:
            states[agent] = 'failed'
            enabled[agent] = True
            states[helper] = 'failed'
        link = self.root / 'etc/systemd/system/multi-user.target.wants' / agent

        def query(unit):
            loaded = paths[unit].exists()
            state = states[unit]
            return dict(LoadState='loaded' if loaded else 'not-found',
                        ActiveState=state,
                        SubState={'active': 'running', 'inactive': 'dead',
                                  'failed': 'failed'}[state],
                        UnitFileState=('static' if unit == helper else
                                       'enabled' if enabled[unit] else 'disabled')
                        if loaded else '')

        def ctl(*args, check=True):
            verb = args[0]
            if verb == 'daemon-reload':
                return
            unit = args[-1]
            if verb == 'enable':
                enabled[unit] = True
                if unit == agent:
                    link.parent.mkdir(parents=True, exist_ok=True)
                    if not link.is_symlink():
                        link.symlink_to('../' + agent)
                if '--now' in args:
                    if unit == agent and fail_activation:
                        states[unit] = 'failed'
                        raise core.subprocess.CalledProcessError(1, args)
                    states[unit] = 'active'
            elif verb == 'disable':
                if paths[unit].exists():
                    enabled[unit] = False
                    if unit == agent and link.is_symlink():
                        link.unlink()
                if '--now' in args and states[unit] != 'failed':
                    states[unit] = 'inactive'
            elif verb == 'stop':
                if states[unit] != 'failed':
                    states[unit] = 'inactive'
            elif verb == 'reset-failed':
                if states[unit] == 'failed':
                    states[unit] = 'inactive'
            elif verb == 'restart':
                self.assertNotEqual(states[unit], 'failed')
                states[unit] = 'active'
            else:
                self.fail('unexpected systemctl call')

        ops = installer.SystemdOperations(health_probe=mock.Mock(return_value={
            'status': 'passed', 'runtime_verified': True, 'identity_preserved': 'passed'}))
        self.backend.services = ops
        for target, attribute, replacement in (
                (ops, '_uninstall_unit_state', query),
                (ops, 'ensure_agent_user', mock.Mock()),
                (core, 'systemctl', ctl)):
            patcher = mock.patch.object(target, attribute, side_effect=replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        return states, enabled, link, agent

    def test_failed_fresh_install_rolls_back_and_removes_enablement(self):
        states, enabled, link, agent = self._failed_unit_fixture(
            existing=False, fail_activation=True)
        with self.assertRaises(installer.ControllerError) as error:
            self.backend.run(self.request(), ROOT, self.hashes)
        self.assertEqual(error.exception.code, 'rolled_back')
        self.assertEqual(states[agent], 'inactive')
        self.assertFalse(enabled[agent])
        self.assertFalse(link.is_symlink())
        self.assertFalse(self.installed_paths().location(core.SYSTEMD_PATHS[0]).exists())
        self.assertEqual(self.store.public_status()['privileged_transaction_state'], 'none')

    def test_failed_existing_agent_can_be_repaired(self):
        states, enabled, _, agent = self._failed_unit_fixture(existing=True)
        result = self.backend.run(self.request('repair'), ROOT, self.hashes)
        self.assertEqual(result.status, 'installed')
        self.assertEqual(states[agent], 'active')
        self.assertTrue(enabled[agent])

    def test_failed_existing_agent_can_be_uninstalled(self):
        states, enabled, link, agent = self._failed_unit_fixture(existing=True)
        result = self.backend.uninstall()
        self.assertEqual(result.status, 'uninstalled')
        self.assertTrue(all(state == 'inactive' for state in states.values()))
        self.assertFalse(enabled[agent])
        self.assertFalse(link.is_symlink())

    def test_enablement_scan_accepts_empty_trees_and_rejects_dangling_managed_entries(self):
        transaction = self.installed_paths()
        self.assertTrue(installer._enablement_absent(transaction))
        unrelated = self.root / 'etc/systemd/system/multi-user.target.wants/other.service'
        unrelated.parent.mkdir(parents=True)
        unrelated.symlink_to('/nonexistent/other.service')
        self.assertTrue(installer._enablement_absent(transaction))
        for base in ('etc', 'run'):
            for suffix in ('wants', 'requires', 'upholds'):
                with self.subTest(base=base, suffix=suffix):
                    entry = (self.root / base / 'systemd/system' /
                             ('example.target.' + suffix) / 'linux-host-agent-power.socket')
                    entry.parent.mkdir(parents=True, exist_ok=True)
                    entry.symlink_to('/nonexistent/managed.socket')
                    self.assertFalse(installer._enablement_absent(transaction))
                    entry.unlink()
                    self.assertTrue(installer._enablement_absent(transaction))

    def test_enablement_scan_refuses_symlinked_dependency_directory(self):
        directory = self.root / 'etc/systemd/system'
        directory.mkdir(parents=True)
        (directory / 'linked.target.wants').symlink_to(self.root)
        self.assertFalse(installer._enablement_absent(self.installed_paths()))

    def test_fresh_rollback_dangling_enablement_blocks_before_removing_files(self):
        link = self.root / 'etc/systemd/system/multi-user.target.wants/linux-host-agent.service'
        def fail_activation(*args, **kwargs):
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to('../linux-host-agent.service')
            raise RuntimeError('activation failure')
        with mock.patch.object(self.services, 'activate', side_effect=fail_activation):
            with self.assertRaises(installer.ControllerError) as error:
                self.backend.run(self.request(), ROOT, self.hashes)
        self.assertEqual(error.exception.code, 'recovery_required')
        self.assertTrue(link.is_symlink())
        self.assertTrue(self.installed_paths().location(core.SYSTEMD_PATHS[0]).is_file())
        # Simulate the successful disable on an explicit recovery.
        with mock.patch.object(self.services, 'prepare_restore',
                               side_effect=lambda previous: link.unlink()):
            self.assertEqual(self.backend.recover_interrupted().status, 'rolled_back')
        self.assertFalse(link.is_symlink())
        self.assertFalse(self.installed_paths().location(core.SYSTEMD_PATHS[0]).exists())

    def test_stopped_install_verification_never_accepts_failed_query(self):
        old = self.existing_install(active=False, enabled=False)
        ops = installer.SystemdOperations(health_probe=mock.Mock())
        before = dict(first_install=False, agent_active=False, agent_enabled=False,
                      socket_active=False, socket_enabled=False)
        inactive = dict(LoadState='loaded', ActiveState='inactive', UnitFileState='disabled')
        with mock.patch.object(ops, '_uninstall_unit_state',
                               side_effect=[inactive, None]):
            self.assertFalse(ops.verify_install(
                self.request('upgrade'), before,
                [core.Change(core.SYSTEMD_PATHS[0], old.read_bytes())],
                power_enabled=False, transaction=self.installed_paths()))
        ops.health_probe.assert_not_called()

    def test_rollback_requires_definite_matching_state(self):
        ops = installer.SystemdOperations()
        inactive = dict(LoadState='loaded', ActiveState='inactive', UnitFileState='disabled')
        absent = dict(LoadState='not-found', ActiveState='inactive', UnitFileState='')
        before = dict(first_install=False, agent_active=False, agent_enabled=False,
                      socket_active=False, socket_enabled=False)
        for first, state, expected in (
                (False, inactive, True), (False, absent, False),
                (False, None, False), (True, absent, True),
                (True, inactive, False), (True, None, False)):
            with self.subTest(first=first, state=state):
                with mock.patch.object(ops, '_uninstall_unit_state',
                                       return_value=state) as query:
                    self.assertEqual(ops.verify_restored_services(
                        dict(before, first_install=first)), expected)
                    self.assertEqual(query.call_count, 3 if first and expected else
                                     1 if first else 2)

    def test_stopped_agent_skips_http_but_checks_files_and_service_state(self):
        old = self.existing_install(active=False, enabled=False)
        ops = installer.SystemdOperations(
            health_probe=mock.Mock(side_effect=AssertionError('no HTTP for stopped unit')))
        trans = self.installed_paths()
        change = core.Change(core.SYSTEMD_PATHS[0], old.read_bytes())
        with mock.patch.object(ops, '_uninstall_unit_state',
                               return_value=dict(LoadState='loaded',
                                                 ActiveState='inactive',
                                                 UnitFileState='disabled')):
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
        def active_state(unit):
            active = unit == 'linux-host-agent.service'
            return dict(LoadState='loaded',
                        ActiveState='active' if active else 'inactive',
                        UnitFileState='enabled' if active else 'disabled')
        with mock.patch.object(ops, '_uninstall_unit_state', side_effect=active_state):
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
        leftover = saved.with_name('.installation-id.0123456789abcdef.tmp')
        os.link(saved, leftover)
        self.assertEqual(saved.stat().st_nlink, 2)
        self.assertEqual(installer.read_saved_identity(self.root), UUID)
        result = self.backend.run(self.request('upgrade'), ROOT, self.hashes)
        self.assertEqual(result.status, 'installed')
        self.assertEqual(result.identity_preserved, 'verified')
        self.assertEqual(leftover.read_text(), UUID + '\n')

    def test_legacy_rollback_never_enters_shared_lock_or_restore(self):
        # Historical restore is now deliberately unavailable from the CLI.
        # The protected recovery controller keeps its own lock/restore tests.
        with (mock.patch.object(core.os, 'geteuid', return_value=0),
              mock.patch.object(core, 'open_manual_install_lock') as lock,
              mock.patch.object(core, 'require_no_wizard_transaction') as guard,
              mock.patch.object(core, 'write_owner_record') as owner,
              mock.patch.object(core, 'InstallTransaction') as trans,
              mock.patch.object(core, 'restore_services') as services):
            with self.assertRaisesRegex(core.InstallError, 'Historical restore is not supported'):
                core.run_cli(['--rollback', '/missing/snapshot'])
            for operation in (lock, guard, owner, trans, services):
                operation.assert_not_called()

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
        private.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
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
        def state(unit):
            active = unit == 'linux-host-agent-power.socket'
            return dict(LoadState='loaded',
                        ActiveState='active' if active else 'inactive',
                        UnitFileState='enabled' if active else 'disabled')
        with mock.patch.object(ops, '_uninstall_unit_state', side_effect=state):
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

    def test_first_install_recovery_retries_failed_owner_publication(self):
        self._simulate_crash_at('APPLYING', fresh=True)
        marker = self.root / core.OWNER_FILE.lstrip('/')
        with mock.patch.object(core.os, 'rename',
                               side_effect=OSError('fixture publication failure')):
            with self.assertRaises(installer.ControllerError) as caught:
                self.backend.recover_interrupted()
            self.assertEqual(caught.exception.code, 'recovery_required')
        self.assertFalse(marker.exists())
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'recovery_required')
        self.assertTrue(self.stage_entries())
        self.assertEqual(self.backend.recover_interrupted().status, 'rolled_back')
        self.assertTrue(core.owner_record_exists(self.root))
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'none')
        self.assertFalse(self.stage_entries())

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
