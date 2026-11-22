"""Filesystem-only Linux installer JSON API tests; no real systemd probes."""
from __future__ import annotations

import contextlib
from io import StringIO
import json
import os
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
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        # Fixture tests must be deterministic and never run the host selector.
        patch = mock.patch.object(api, 'select_python', return_value='/usr/bin/python3.11')
        patch.start()
        self.addCleanup(patch.stop)

    def put(self, absolute, content: bytes):
        dest = self.root / absolute.lstrip('/')
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        return dest

    def add_wol_interface(self, name='enp1s0f0'):
        (self.root / 'sys/class/net' / name).mkdir(parents=True)
        return name

    def inspect_fixture_cli(self, *, python_override=None):
        return api.inspection(root=self.root, python_override=python_override)

    def test_inspect_never_discloses_private_state(self):
        self.put(core.SYSTEMD_PATHS[0], b'previous service')
        self.put(core.POWER_DROPIN, b'[Service]\n')
        self.put('/var/lib/linux-host-agent/installation-id', b'confidential-uuid')
        self.put('/var/lib/linux-host-agent/control-token', b'confidential-token')
        result = self.inspect_fixture_cli()
        self.assertTrue(result['installation']['detected'])
        self.assertEqual(result['installation']['power_dropin'], 'present')
        self.assertEqual(result['installation']['agent_service_state'], 'unknown')
        self.assertEqual(result['installation']['agent_service_enabled'], 'unknown')
        self.assertEqual(result['privileged_transaction_state'], 'unknown')
        self.assertEqual(result['identity_preserved'], 'not_verified')
        self.assertEqual(result['python']['selected_interpreter'], '/usr/bin/python3.11')
        self.assertFalse(result['secrets_included'])
        raw = json.dumps(result)
        for bad in ('confidential-uuid', 'confidential-token', 'control-token', 'installation-id'):
            self.assertNotIn(bad, raw)

    def test_inspect_distinguishes_missing_systemd(self):
        result = self.inspect_fixture_cli()
        self.assertFalse(result['installation']['detected'])
        checks = {item['id']: item['status'] for item in result['checks']}
        self.assertEqual(checks['systemd_pid1'], 'blocked')
        self.assertEqual(checks['python_3_10_plus'], 'passed')
        self.assertEqual(result['installation']['avahi_service_file'], 'absent')
        self.assertEqual(result['installation']['agent_service_enabled'], 'unknown')

    def test_inspect_blocked_python_uses_selected_not_api_interpreter(self):
        with mock.patch.object(api, 'select_python', return_value=None):
            result = self.inspect_fixture_cli()
        checks = {item['id']: item['status'] for item in result['checks']}
        self.assertEqual(checks['python_3_10_plus'], 'blocked')
        self.assertFalse(result['python']['version_supported'])
        with mock.patch.object(api, 'select_python', return_value=None):
            with self.assertRaises(api.PrerequisiteMissing):
                api.change_plan(root=self.root, source=ROOT)

    def test_inspect_flags_managed_symlink(self):
        external = self.put('/not-an-app-file', b'external')
        link = self.root / core.SYSTEMD_PATHS[0].lstrip('/')
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(external)
        result = self.inspect_fixture_cli()
        self.assertEqual(result['installation']['service_file'], 'unsafe')
        self.assertIn({'id': 'managed_path_integrity', 'status': 'blocked'}, result['checks'])
        self.assertEqual(external.read_bytes(), b'external')

    def test_avahi_fresh_install_directory_without_agent_file(self):
        (self.root / 'etc/avahi/services').mkdir(parents=True)
        result = self.inspect_fixture_cli()
        checks = {item['id']: item['status'] for item in result['checks']}
        self.assertEqual(checks['avahi_discovery'], 'not_verified')
        self.assertEqual(result['avahi']['services_directory'], 'present')
        self.assertEqual(result['avahi']['daemon_state'], 'unknown')
        self.assertEqual(result['installation']['avahi_service_file'], 'absent')
        plan = api.change_plan(root=self.root, source=ROOT)
        self.assertIn(core.AVAHI_PATH, [c['path'] for c in plan['changes']])

    def test_avahi_no_directory_warns_without_assuming_installed(self):
        result = self.inspect_fixture_cli()
        checks = {item['id']: item['status'] for item in result['checks']}
        self.assertEqual(checks['avahi_discovery'], 'warning')
        self.assertEqual(result['avahi']['services_directory'], 'absent')

    def test_avahi_daemon_statuses(self):
        self.put(core.SYSTEMD_PATHS[0], b'dummy')
        (self.root / 'etc/avahi/services').mkdir(parents=True)
        with mock.patch.object(api, 'service_state', return_value='active') as state:
            # fixture root deliberately never executes real systemctl
            result = self.inspect_fixture_cli()
            state.assert_not_called()
        self.assertEqual(result['avahi']['daemon_state'], 'unknown')
        self.assertEqual(
            {c['id']: c['status'] for c in result['checks']}['avahi_discovery'],
            'not_verified',
        )

    def test_plan_monitoring_by_default_and_preserves_power(self):
        self.put(core.APP_FILES[0], b'PROTOCOL = "computer-host-agent"\n')
        old = self.put(core.POWER_DROPIN, b'CUSTOM=preserve\n')
        result = api.change_plan(root=self.root, source=ROOT)
        self.assertEqual(result['operation'], 'plan')
        self.assertEqual(result['mode'], 'read_only')
        self.assertEqual(result['power_option'], 'preserve')
        self.assertEqual(result['selected_python'], '/usr/bin/python3.11')
        self.assertFalse(result['changes_applied'])
        self.assertNotIn(core.POWER_DROPIN, [item['path'] for item in result['changes']])
        self.assertEqual(old.read_bytes(), b'CUSTOM=preserve\n')
        self.assertTrue(any(item['path'] == core.APP_FILES[0] and item['action'] == 'replace'
                            for item in result['changes']))
        self.assertEqual(result['privileged_transaction_state'], 'unknown')

    def test_plan_disabling_power_does_not_mutate(self):
        self.put(core.APP_FILES[0], b'PROTOCOL = "computer-host-agent"\n')
        old = self.put(core.POWER_DROPIN, b'old')
        result = api.change_plan(root=self.root, source=ROOT, disable_power=True)
        dropin = next(item for item in result['changes'] if item['path'] == core.POWER_DROPIN)
        self.assertEqual(dropin['action'], 'remove')
        self.assertEqual(old.read_bytes(), b'old')

    def test_plan_absent_remove_is_unchanged(self):
        result = api.change_plan(root=self.root, source=ROOT, disable_power=True)
        dropin = next(item for item in result['changes'] if item['path'] == core.POWER_DROPIN)
        self.assertEqual(dropin['action'], 'unchanged')

    def test_plan_rejects_unsafe_managed_path(self):
        external = self.put('/elsewhere', b'not overwritten')
        dest = self.root / core.APP_FILES[0].lstrip('/')
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.symlink_to(external)
        with self.assertRaises(api.UnsafeManagedPath):
            api.change_plan(root=self.root, source=ROOT)
        self.assertEqual(external.read_bytes(), b'not overwritten')

    def test_plan_rejects_conflicting_power(self):
        with self.assertRaises(api.InvalidArgument):
            api.change_plan(root=self.root, source=ROOT, enable_power=True, disable_power=True)

    def test_wol_requires_actual_interface_and_rejects_dot_paths(self):
        for name in ('eth0\nEnvironment=BAD', 'ethernet-interface-name-overlong', '', 'a/b',
                     '.', '..', 'enp9s9'):
            with self.subTest(name=name), self.assertRaises(api.InvalidArgument):
                api.change_plan(root=self.root, source=ROOT, wol_interface=name)
        nic = self.add_wol_interface()
        plan = api.change_plan(root=self.root, source=ROOT, wol_interface=nic)
        self.assertTrue(plan['wol_interface_requested'])
        self.assertIn(core.WOL_DROPIN, [c['path'] for c in plan['changes']])

    def test_plan_does_not_touch_protected_state(self):
        self.put(core.APP_FILES[0], b'PROTOCOL = "computer-host-agent"\n')
        secret = self.put('/var/lib/linux-host-agent/control-token', b'SECRET-EXISTING-CONTROL-TOKEN')
        uuid = self.put('/var/lib/linux-host-agent/installation-id', b'UUID-EXISTING')
        before = [(secret, secret.stat().st_mtime_ns), (uuid, uuid.stat().st_mtime_ns)]
        nic = self.add_wol_interface()
        result = api.change_plan(root=self.root, source=ROOT, enable_power=True, wol_interface=nic)
        self.assertTrue(result['wol_interface_requested'])
        self.assertEqual(result['power_option'], 'enable')
        serialized = json.dumps(result)
        self.assertNotIn('SECRET-EXISTING', serialized)
        self.assertNotIn('UUID-EXISTING', serialized)
        for path, mtime in before:
            self.assertEqual(path.stat().st_mtime_ns, mtime)


    def test_plan_refuses_legacy_or_orphaned_install_without_schema_change(self):
        old = self.put(core.APP_FILES[0], b'PROTOCOL = "linux-host-agent"\n')
        with self.assertRaises(api.PrerequisiteMissing):
            api.change_plan(root=self.root, source=ROOT)
        self.assertEqual(old.read_bytes(), b'PROTOCOL = "linux-host-agent"\n')
        old.unlink()
        self.put('/var/lib/linux-host-agent/installation-id', b'old-private-identity')
        with self.assertRaises(api.PrerequisiteMissing):
            api.change_plan(root=self.root, source=ROOT)
        self.assertEqual(api.SCHEMA_VERSION, 1)

    def test_service_probe_uses_only_read_only_systemctl(self):
        with mock.patch.object(api.shutil, 'which', return_value='/usr/bin/systemctl'), \
             mock.patch.object(api.subprocess, 'run') as run:
            run.side_effect = [
                subprocess.CompletedProcess([], 0, 'active\n', ''),
                subprocess.CompletedProcess([], 0, 'disabled\n', ''),
            ]
            self.assertEqual(api.service_state('linux-host-agent.service', 'is-active',
                                               systemd_present=True), 'active')
            self.assertEqual(api.service_state('linux-host-agent.service', 'is-enabled',
                                               systemd_present=True), 'disabled')
            self.assertEqual(run.call_args_list[0].args[0],
                             ['systemctl', 'is-active', 'linux-host-agent.service'])
            self.assertEqual(run.call_args_list[1].args[0],
                             ['systemctl', 'is-enabled', 'linux-host-agent.service'])
            self.assertEqual(run.call_args.kwargs['timeout'], 3)
        with mock.patch.object(api.subprocess, 'run') as run:
            self.assertEqual(api.service_state('linux-host-agent.service', 'is-active',
                                               systemd_present=False), 'unknown')
            run.assert_not_called()

    def test_json_cli_success_without_host_access(self):
        output = StringIO()
        fixture = self.inspect_fixture_cli()
        with mock.patch.object(api, 'inspection', return_value=fixture) as inspect, \
             contextlib.redirect_stdout(output):
            code = api.main(['inspect'])
        inspect.assert_called_once()
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result['schema_version'], 1)
        self.assertFalse(result['secrets_included'])
        self.assertEqual(result['privileged_transaction_state'], 'unknown')
        self.assertNotIn('error', result)

    def test_all_argument_failures_are_redacted_json(self):
        vectors = [
            (['plan', '--wol-interface', 'bad/name'], 'invalid_argument'),
            (['plan', '--enable-power', '--disable-power'], 'invalid_argument'),
            (['plan', '--bogus'], 'invalid_argument'),
            (['unknown-command'], 'invalid_argument'),
            ([], 'invalid_argument'),
            (['inspect', '--bogus'], 'invalid_argument'),
        ]
        for args, code in vectors:
            with self.subTest(args=args):
                out, err = StringIO(), StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    rc = api.main(args)
                self.assertEqual(rc, 2)
                self.assertEqual(out.getvalue(), '')
                obj = json.loads(err.getvalue())
                self.assertEqual(obj['error']['code'], code)
                self.assertEqual(err.getvalue().count('\n'), 1)
                self.assertNotIn('usage:', err.getvalue())
                self.assertNotIn('bad/name', err.getvalue())

    def test_bad_explicit_python_override_is_json(self):
        # A fake selector refusal keeps the test independent of the CI host.
        out, err = StringIO(), StringIO()
        with mock.patch.object(api, 'select_python',
                               side_effect=api.InvalidArgument('rejected')), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = api.main(['plan', '--python', 'python3'])
        self.assertEqual(rc, 2)
        self.assertEqual(out.getvalue(), '')
        self.assertEqual(json.loads(err.getvalue())['error']['code'], 'invalid_argument')

    def test_error_codes_distinguish_unsafe_from_source_missing(self):
        dest = self.root / core.APP_FILES[0].lstrip('/')
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.symlink_to(self.put('/external', b'external'))
        with self.assertRaises(api.UnsafeManagedPath) as context:
            api.change_plan(root=self.root, source=ROOT)
        self.assertEqual(context.exception.code, 'unsafe_managed_path')

        dest.unlink()
        with self.assertRaises(api.SourceUnavailable) as context:
            api.change_plan(root=self.root, source=self.root)
        self.assertEqual(context.exception.code, 'source_unavailable')
        for code in ('invalid_argument', 'unsafe_managed_path', 'source_unavailable',
                     'prerequisite_missing', 'internal_error'):
            self.assertEqual(json.loads(api.error_response('plan', code))['error']['code'], code)


class ShellSelectorParityTests(unittest.TestCase):
    """Test the actual shipped shell selector with fake candidate interpreters."""

    def test_default_selector_skips_old_python_and_finds_newer(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script = root / 'scripts/python-selector.sh'
            script.parent.mkdir()
            script.write_bytes((ROOT / 'scripts/python-selector.sh').read_bytes())
            bin_dir = root / 'bin'
            bin_dir.mkdir()
            # Mask the host candidates with deterministic fake executables.
            for name in ('python3', 'python3.14', 'python3.13', 'python3.12',
                         'python3.11', 'python3.10'):
                fake = bin_dir / name
                fake.write_text('#!/bin/sh\nexit ' + ('0' if name == 'python3.11' else '1') + '\n')
                fake.chmod(0o755)
            env = os.environ.copy()
            env['PATH'] = str(bin_dir) + os.pathsep + env.get('PATH', '')
            selected = api.select_python(source=root, env=env)
            self.assertEqual(selected, str(bin_dir / 'python3.11'))
            self.assertEqual(api.select_python(explicit=str(bin_dir / 'python3.11'),
                                               source=root, env=env), selected)
            with self.assertRaises(api.InvalidArgument):
                api.select_python(explicit='python3.11', source=root, env=env)
            with self.assertRaises(api.InvalidArgument):
                api.select_python(explicit=str(bin_dir / 'python3'), source=root, env=env)

    def test_shell_launcher_returns_json_when_no_compatible_python(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scripts = root / 'scripts'
            scripts.mkdir()
            for name in ('installer-api.sh', 'python-selector.sh'):
                (scripts / name).write_bytes((ROOT / 'scripts' / name).read_bytes())
            bin_dir = root / 'bin'
            bin_dir.mkdir()
            for name in ('python3', 'python3.14', 'python3.13', 'python3.12',
                         'python3.11', 'python3.10'):
                stub = bin_dir / name
                stub.write_text('#!/bin/sh\nexit 1\n')
                stub.chmod(0o755)
            env = os.environ.copy()
            env['PATH'] = str(bin_dir) + os.pathsep + env.get('PATH', '')
            result = subprocess.run(['sh', str(scripts / 'installer-api.sh'), 'plan'],
                                    text=True, capture_output=True, env=env, timeout=15)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(result.stdout, '')
            self.assertEqual(result.stderr.count('\n'), 1)
            self.assertEqual(json.loads(result.stderr)['error']['code'], 'prerequisite_missing')
            self.assertEqual(json.loads(result.stderr)['operation'], 'plan')

    def test_launcher_is_directly_executable(self):
        # GitHub must retain mode 100755. Running 'sh script' would conceal
        # a 100644 regression and break the Go wizard's direct exec call.
        self.assertTrue(os.access(ROOT / 'scripts/installer-api.sh', os.X_OK),
                        'installer-api.sh must have executable mode in Git')

    def test_launcher_python_equals_form_and_json_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scripts = root / 'scripts'
            scripts.mkdir()
            for name in ('installer-api.sh', 'python-selector.sh'):
                target = scripts / name
                target.write_bytes((ROOT / 'scripts' / name).read_bytes())
                target.chmod(0o755)
            bin_dir = root / 'bin'
            bin_dir.mkdir()
            # Default python3 is too old. A newer executable is available.
            # The compatible stub emits deterministic output on exec.
            old = bin_dir / 'python3'
            old.write_text('#!/bin/sh\nexit 1\n')
            old.chmod(0o755)
            # Mask all remaining selector candidates. Otherwise a newer
            # Python installed on a CI runner could win before our stub.
            for name in ('python3.14', 'python3.13', 'python3.12', 'python3.10'):
                unavailable = bin_dir / name
                unavailable.write_text('#!/bin/sh\nexit 1\n')
                unavailable.chmod(0o755)
            newer = bin_dir / 'python3.11'
            newer.write_text(
                '#!/bin/sh\n'
                'if [ "$1" = "-c" ]; then exit 0; fi\n'
                'printf \'{"selected":"python3.11","first_arg":"%s","second_arg":"%s"}\\n\' "$2" "$3"\n'
            )
            newer.chmod(0o755)
            env = os.environ.copy()
            env['PATH'] = str(bin_dir) + os.pathsep + env.get('PATH', '')
            for override in ([f'--python={newer}'], ['--python', str(newer)]):
                with self.subTest(override=override):
                    result = subprocess.run(
                        [str(scripts / 'installer-api.sh'), 'inspect', *override],
                        capture_output=True, text=True, env=env, timeout=15,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stderr, '')
                    output = json.loads(result.stdout)
                    self.assertEqual(output['selected'], 'python3.11')
                    self.assertEqual(output['first_arg'], 'inspect')
                    self.assertEqual(output['second_arg'], override[0])

            for override in ([f'--python={bin_dir / "missing"}'],
                             ['--python='], ['--python', '--enable-power']):
                with self.subTest(override=override):
                    result = subprocess.run(
                        [str(scripts / 'installer-api.sh'), 'plan', *override],
                        capture_output=True, text=True, env=env, timeout=15,
                    )
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertEqual(result.stdout, '')
                    self.assertEqual(result.stderr,
                                     api.error_response('plan', 'invalid_argument') + '\n')

    def test_missing_selector_is_source_error(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(api.SourceUnavailable):
                api.select_python(source=Path(temp))


if __name__ == '__main__':
    unittest.main()
