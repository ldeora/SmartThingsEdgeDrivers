"""Filesystem-only upgrade/rollback tests. Never touch real systemd or /opt."""
from pathlib import Path
import importlib.util
import json
import os
import stat
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('install_core', ROOT/'scripts/install_core.py')
core = importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name] = core
SPEC.loader.exec_module(core)


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.trans = core.InstallTransaction(self.root)

    def put(self, path, data, mode=0o644):
        target = self.root/path.lstrip('/')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(mode)
        return target

    def test_upgrade_and_explicit_rollback_restore_original(self):
        old = self.put(core.APP_FILES[0], b'old agent', 0o755)
        uuid = self.put('/var/lib/linux-host-agent/installation-id', b'HOST-UUID\n', 0o600)
        secret = self.put('/var/lib/linux-host-agent/control-token', b'private key!\n', 0o600)
        changes = [core.Change(core.APP_FILES[0], b'new agent', 0o755),
                   core.Change(core.SYSTEMD_PATHS[0], b'new unit')]
        backup = self.trans.snapshot(changes, previous={'agent_active': True})
        self.trans.apply(changes)
        self.assertEqual(old.read_bytes(), b'new agent')
        self.assertTrue((self.root/core.SYSTEMD_PATHS[0].lstrip('/')).exists())
        previous = self.trans.restore(backup)
        self.assertEqual(previous['agent_active'], True)
        self.assertEqual(old.read_bytes(), b'old agent')
        self.assertEqual(stat.S_IMODE(old.stat().st_mode), 0o755)
        self.assertFalse((self.root/core.SYSTEMD_PATHS[0].lstrip('/')).exists())
        self.assertEqual(uuid.read_bytes(), b'HOST-UUID\n')
        self.assertEqual(secret.read_bytes(), b'private key!\n')

    def test_snapshot_is_private(self):
        change = core.Change(core.APP_FILES[0], b'safe')
        backup = self.trans.snapshot([change])
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((backup/'manifest.json').stat().st_mode), 0o600)
        self.assertNotIn('control-token', (backup/'manifest.json').read_text())

    def test_symlink_is_never_overwritten(self):
        external = self.put('/somewhere/important', b'stay intact')
        link = self.root/core.APP_FILES[0].lstrip('/')
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(external)
        with self.assertRaises(core.InstallError):
            self.trans.snapshot([core.Change(core.APP_FILES[0], b'bad')])
        self.assertEqual(external.read_bytes(), b'stay intact')

    def test_partial_failure_can_be_rolled_back(self):
        first = self.put(core.APP_FILES[0], b'v0.2.2', 0o755)
        second = self.put(core.APP_FILES[1], b'old helper', 0o755)
        changes = [core.Change(core.APP_FILES[0], b'v0.3.0', 0o755),
                   core.Change(core.APP_FILES[1], b'new helper', 0o755)]
        backup = self.trans.snapshot(changes)
        original_atomic = core.InstallTransaction.atomic_file
        calls = []
        def fail_second(*args):
            calls.append(1)
            if len(calls) == 2:
                raise OSError('disk full or injected fault')
            return original_atomic(*args)
        with mock.patch.object(core.InstallTransaction, 'atomic_file', side_effect=fail_second):
            with self.assertRaises(OSError):
                self.trans.apply(changes)
        self.trans.restore(backup)
        self.assertEqual(first.read_bytes(), b'v0.2.2')
        self.assertEqual(second.read_bytes(), b'old helper')

    def test_rollback_refuses_path_outside_allowlist(self):
        with self.assertRaises(core.InstallError):
            self.trans.location('/var/lib/linux-host-agent/control-token')

    def test_uninstall_plan_retains_identity_and_wol_rules(self):
        plan = core.generate_plan(ROOT, '/usr/bin/python3', enable_power=False,
                                  disable_power=False, wol_interface=None,
                                  is_existing_power=False, avahi_dir=False,
                                  uninstall=True)
        self.assertTrue(all(p.content is None for p in plan))
        self.assertFalse(any('/var/lib/' in p.path for p in plan))
        self.assertFalse(any(p.path.endswith('.link') for p in plan))

    def test_power_dropin_preserved_by_default(self):
        plan = core.generate_plan(ROOT, '/usr/bin/python3', enable_power=False,
                                  disable_power=False, wol_interface=None,
                                  is_existing_power=True, avahi_dir=False)
        self.assertNotIn(core.POWER_DROPIN, [x.path for x in plan])

    def test_explicit_power_optin_generates_compatible_service(self):
        plan = core.generate_plan(ROOT, '/usr/bin/python3.11', enable_power=True,
                                  disable_power=False, wol_interface='enp3s0',
                                  is_existing_power=False, avahi_dir=True)
        mapping = {c.path:c.content for c in plan}
        self.assertIn(b'/usr/bin/python3.11', mapping[core.POWER_DROPIN])
        self.assertIn(b'--enable-power-control', mapping[core.POWER_DROPIN])
        self.assertIn(b'enp3s0', mapping[core.WOL_DROPIN])
        self.assertIn(core.AVAHI_PATH, mapping)
        self.assertNotIn(b'/usr/bin/python3 ', mapping[core.SYSTEMD_PATHS[0]])

    def test_explicit_power_optout_removes_dropin(self):
        plan = core.generate_plan(ROOT, '/usr/bin/python3', enable_power=False,
                                  disable_power=True, wol_interface=None,
                                  is_existing_power=True, avahi_dir=False)
        self.assertIsNone(next(x.content for x in plan if x.path == core.POWER_DROPIN))

    def test_first_install_service_lifecycle_is_explicit(self):
        previous={'first_install':True, 'agent_active':False, 'agent_enabled':False,
                  'socket_active':False, 'socket_enabled':False, 'newly_enabled_power':False}
        with mock.patch.object(core, 'systemctl') as service:
            core.activate(previous, power_enabled=False, disable_power=False)
        commands = [call.args for call in service.call_args_list]
        self.assertIn(('enable','--now','linux-host-agent.service'),commands)
        self.assertIn(('disable','--now','linux-host-agent-power.socket'),commands)
        self.assertNotIn(('enable','--now','linux-host-agent-power.socket'),commands)

    def test_upgrade_keeps_existing_enabled_power(self):
        previous={'first_install':False, 'agent_active':True, 'agent_enabled':True,
                  'socket_active':True, 'socket_enabled':True, 'newly_enabled_power':False}
        with mock.patch.object(core, 'systemctl') as service:
            core.activate(previous, power_enabled=True, disable_power=False)
        commands = [call.args for call in service.call_args_list]
        self.assertIn(('enable','--now','linux-host-agent-power.socket'),commands)
        self.assertIn(('restart','linux-host-agent.service'),commands)
        self.assertLess(commands.index(('enable','--now','linux-host-agent-power.socket')),
                        commands.index(('restart','linux-host-agent.service')))

    def test_duplicate_change_and_invalid_ancestor_rejected(self):
        change = core.Change(core.APP_FILES[0], b'a')
        with self.assertRaises(core.InstallError):
            self.trans.snapshot([change, change])
        (self.root/'opt').symlink_to(self.root/'somewhere')
        with self.assertRaises(core.InstallError):
            self.trans.snapshot([change])


if __name__ == '__main__':
    unittest.main()
