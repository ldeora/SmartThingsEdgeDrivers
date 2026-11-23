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
        self.user_preflights = 0
        self.verify_calls = 0
        self.fail_verify = False
        self.fail_restore = False
        self.received_request = None

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
        # The guard was already present in the CLI under its flock;
        # retain a cheap regression assertion rather than editing it.
        import inspect
        source = inspect.getsource(core.run_cli)
        under_lock = source[source.index("with lockfile.open('a+') as lock:"):]
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
