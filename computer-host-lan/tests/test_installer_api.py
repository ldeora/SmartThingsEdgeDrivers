"""Read-only Linux installer JSON API tests; never touch real system state."""
from __future__ import annotations

import contextlib
import importlib.util
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import installer_api as api
import install_core as core


class InstallerAPIReadOnlyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def put(self, absolute, content: bytes):
        dest = self.root / absolute.lstrip('/')
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        return dest

    def test_inspect_never_discloses_private_state(self):
        self.put(core.SYSTEMD_PATHS[0], b'previous service')
        self.put(core.POWER_DROPIN, b'[Service]\n')
        self.put('/var/lib/linux-host-agent/installation-id', b'confidential-uuid')
        self.put('/var/lib/linux-host-agent/control-token', b'confidential-token')
        result = api.inspection(root=self.root)
        self.assertTrue(result['installation']['detected'])
        self.assertEqual(result['installation']['power_dropin'], 'present')
        self.assertEqual(result['installation']['agent_service_state'], 'unknown')
        self.assertEqual(result['privileged_transaction_state'], 'unknown')
        self.assertEqual(result['identity_preserved'], 'not_verified')
        self.assertFalse(result['secrets_included'])
        raw = json.dumps(result)
        for bad in ('confidential-uuid', 'confidential-token', 'control-token', 'installation-id'):
            self.assertNotIn(bad, raw)

    def test_inspect_distinguishes_missing_systemd(self):
        result = api.inspection(root=self.root, check_services=False)
        self.assertFalse(result['installation']['detected'])
        checks = {item['id']: item['status'] for item in result['checks']}
        self.assertEqual(checks['systemd_pid1'], 'blocked')
        self.assertEqual(result['installation']['avahi_service_file'], 'absent')

    def test_inspect_flags_managed_symlink(self):
        external = self.put('/not-an-app-file', b'external')
        link = self.root / core.SYSTEMD_PATHS[0].lstrip('/')
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(external)
        result = api.inspection(root=self.root)
        self.assertEqual(result['installation']['service_file'], 'unsafe')
        self.assertIn({'id': 'managed_path_integrity', 'status': 'blocked'}, result['checks'])
        self.assertEqual(external.read_bytes(), b'external')

    def test_plan_monitoring_by_default_and_preserves_power(self):
        old = self.put(core.POWER_DROPIN, b'CUSTOM=preserve\n')
        result = api.change_plan(root=self.root, source=ROOT)
        self.assertEqual(result['operation'], 'plan')
        self.assertEqual(result['mode'], 'read_only')
        self.assertEqual(result['power_option'], 'preserve')
        self.assertFalse(result['changes_applied'])
        self.assertNotIn(core.POWER_DROPIN, [item['path'] for item in result['changes']])
        self.assertEqual(old.read_bytes(), b'CUSTOM=preserve\n')
        self.assertTrue(any(item['path'] == core.APP_FILES[0] and item['action'] == 'create'
                            for item in result['changes']))
        self.assertEqual(result['privileged_transaction_state'], 'unknown')

    def test_plan_disabling_power_does_not_mutate(self):
        old = self.put(core.POWER_DROPIN, b'old')
        result = api.change_plan(root=self.root, source=ROOT, disable_power=True)
        dropin = next(item for item in result['changes'] if item['path'] == core.POWER_DROPIN)
        self.assertEqual(dropin['action'], 'remove')
        self.assertEqual(old.read_bytes(), b'old')

    def test_plan_absent_remove_is_unchanged(self):
        result = api.change_plan(root=self.root, source=ROOT, disable_power=True)
        dropin = next(item for item in result['changes'] if item['path'] == core.POWER_DROPIN)
        self.assertEqual(dropin['action'], 'unchanged')

    def test_plan_rejects_symlink_and_conflicting_power(self):
        external = self.put('/elsewhere', b'not overwritten')
        dest = self.root / core.APP_FILES[0].lstrip('/')
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.symlink_to(external)
        with self.assertRaises(api.InvalidRequest):
            api.change_plan(root=self.root, source=ROOT, enable_power=True, disable_power=True)
        with self.assertRaises(api.InvalidRequest):
            api.change_plan(root=self.root, source=ROOT)
        self.assertEqual(external.read_bytes(), b'not overwritten')

    def test_plan_rejects_malicious_interface_and_python(self):
        for name in ('eth0\nEnvironment=BAD', 'ethernet-interface-name-overlong', '', 'a/b'):
            with self.subTest(name=name), self.assertRaises(api.InvalidRequest):
                api.change_plan(root=self.root, source=ROOT, wol_interface=name)
        for name in ('python3', '/usr/bin/python3\nExecStart=/bin/sh', '/tmp/p\"q', '/tmp/a;b'):
            with self.subTest(python=name), self.assertRaises(api.InvalidRequest):
                api.change_plan(root=self.root, source=ROOT, python_bin=name)

    def test_service_probe_uses_only_read_only_systemctl(self):
        with mock.patch.object(api.shutil, 'which', return_value='/usr/bin/systemctl'), \
             mock.patch.object(api.subprocess, 'run') as run:
            run.return_value = subprocess.CompletedProcess([], 0, 'active\n', '')
            self.assertEqual(api.service_state('linux-host-agent.service', systemd_present=True), 'active')
            args, kwargs = run.call_args
            self.assertEqual(args[0], ['systemctl', 'is-active', 'linux-host-agent.service'])
            self.assertEqual(kwargs['timeout'], 3)
        with mock.patch.object(api.subprocess, 'run') as run:
            self.assertEqual(api.service_state('linux-host-agent.service', systemd_present=False), 'unknown')
            run.assert_not_called()

    def test_inspect_cli_json_and_rejected_operation(self):
        output = StringIO()
        with contextlib.redirect_stdout(output):
            code = api.main(['inspect'])
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result['schema_version'], 1)
        self.assertFalse(result['secrets_included'])
        self.assertEqual(result['privileged_transaction_state'], 'unknown')
        self.assertNotIn('error', result)

        err = StringIO()
        with contextlib.redirect_stderr(err):
            code = api.main(['plan', '--wol-interface', 'bad/name'])
        self.assertEqual(code, 2)
        fault = json.loads(err.getvalue())
        self.assertEqual(fault['error']['code'], 'invalid_or_unsafe_request')
        self.assertNotIn('bad/name', err.getvalue())

    def test_plan_does_not_touch_protected_state(self):
        secret = self.put('/var/lib/linux-host-agent/control-token', b'SECRET-EXISTING-CONTROL-TOKEN')
        uuid = self.put('/var/lib/linux-host-agent/installation-id', b'UUID-EXISTING')
        before = [(secret, secret.stat().st_mtime_ns), (uuid, uuid.stat().st_mtime_ns)]
        result = api.change_plan(root=self.root, source=ROOT, enable_power=True, wol_interface='enp1s0f0')
        self.assertTrue(result['wol_interface_requested'])
        self.assertEqual(result['power_option'], 'enable')
        serialized = json.dumps(result)
        self.assertNotIn('SECRET-EXISTING', serialized)
        self.assertNotIn('UUID-EXISTING', serialized)
        for path, mtime in before:
            self.assertEqual(path.stat().st_mtime_ns, mtime)


if __name__ == '__main__':
    unittest.main()
