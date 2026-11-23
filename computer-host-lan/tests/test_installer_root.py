"""Pure schema/dispatch tests for the proposed installed-only root helper.

Never elevate, invoke sudo, read a live manifest or modify the host.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import installer_root as bridge


class FakeBackend:
    def __init__(self):
        self.calls = []
        self.recovered = mock.Mock(status='rolled_back')

    def run(self, request, source, files):
        self.calls.append((request, source, files))
        return mock.Mock(status='installed', operation=request.operation,
                         identity_preserved='not_verified', source_verified=True)

    def recover_interrupted(self):
        self.calls.append('recover')
        return self.recovered


class RootProtocolTests(unittest.TestCase):
    def setUp(self):
        self.files = {name: hashlib.sha256(name.encode()).hexdigest()
                      for name in bridge._MANIFEST_FILES}
        self.manifest = bridge.validate_manifest(dict(
            schema_version=1, agent_version='0.4.6-rc.2', files=self.files))
        self.backend = FakeBackend()
        self.journal = mock.Mock()
        self.journal.public_status.return_value = {
            'privileged_transaction_state': 'recovery_required',
        }

    def parse(self, **updates):
        obj = dict(schema_version=1, action='install',
                   source='/home/user/computer-host-lan',
                   power='preserve', wol_interface=None)
        obj.update(updates)
        return bridge.parse_request(json.dumps(obj).encode('utf-8'))

    def test_valid_install_upgrade_repair_and_previews(self):
        for action in ('install', 'upgrade', 'repair'):
            for power in ('preserve', 'enable', 'disable'):
                request = self.parse(action=action, power=power,
                                     wol_interface='enp1s0f0')
                response = bridge.dispatch(request, self.manifest,
                                           backend=self.backend,
                                           journal=self.journal)
                self.assertEqual(response['status'], 'installed')
                self.assertFalse(response['secrets_included'])
                saved, source, hashes = self.backend.calls[-1]
                self.assertEqual(saved.operation, action)
                self.assertEqual(saved.enable_power, power == 'enable')
                self.assertEqual(saved.disable_power, power == 'disable')
                self.assertEqual(saved.expected_identity, None)
                self.assertEqual(saved.expected_version, '0.4.6-rc.2')
                self.assertEqual(saved.wol_interface, 'enp1s0f0')
                self.assertEqual(source, Path('/home/user/computer-host-lan'))
                self.assertEqual(hashes, self.files)

    def test_status_and_recovery_never_include_private_journal_state(self):
        for action in ('status', 'recover'):
            req = bridge.parse_request(
                json.dumps({'schema_version': 1, 'action': action}).encode())
            response = bridge.dispatch(req, self.manifest,
                                       backend=self.backend,
                                       journal=self.journal)
            self.assertFalse(response['secrets_included'])
            text = json.dumps(response)
            self.assertNotIn('transaction_id', text)
            self.assertNotIn('snapshot_name', text)
            self.assertNotIn('installation-id', text)
            self.assertNotIn('control-token', text)
        self.assertEqual(self.backend.calls[-1], 'recover')
        self.assertEqual(response['recovery_status'], 'rolled_back')

    def test_untrusted_request_rejects_extra_options_and_unsafe_values(self):
        bad = [
            {'schema_version': True},
            {'schema_version': 2},
            {'action': 'uninstall'},
            {'action': 'shutdown'},
            {'source': '../foo'},
            {'source': '/tmp/../escape'},
            {'source': '/tmp/x\nroot'},
            {'source': 42},
            {'power': 'raw-systemctl-command'},
            {'power': True},
            {'wol_interface': 'eth0;id'},
            {'wol_interface': '..'},
            {'wol_interface': ['eth0']},
            {'expected_identity': 'secret'},
            {'python_bin': '/tmp/python'},
        ]
        for update in bad:
            with self.subTest(update=update), self.assertRaises(bridge.RequestError):
                self.parse(**update)

    def test_duplicate_json_keys_and_oversize_rejected(self):
        for payload in (
            b'{"schema_version":1,"schema_version":1,"action":"status"}',
            b'{"schema_version":1,"action":"status","source":"/tmp"}',
            b'{"schema_version":1,"action":"recover","power":"enable"}',
            b'null',
            b'',
            b'{',
            b'{' + b'a' * 4096 + b'}',
        ):
            with self.subTest(payload=payload[:48]):
                with self.assertRaises(bridge.RequestError):
                    bridge.parse_request(payload)

    def test_trusted_manifest_must_have_all_ten_lowercase_hashes(self):
        data = dict(schema_version=1, agent_version='0.4.6-rc.2',
                    files=self.files)
        self.assertEqual(bridge.validate_manifest(data)['files'], self.files)
        altered = [
            dict(data, files={}),
            dict(data, files={**self.files, 'extra': '0' * 64}),
            dict(data, files={**self.files,
                              sorted(self.files)[0]: 'A' * 64}),
            dict(data, agent_version='not valid version'),
            dict(data, schema_version=True),
            dict(data, unknown='extra'),
        ]
        for bad in altered:
            with self.subTest(manifest=str(bad)[:80]):
                with self.assertRaises(bridge.RequestError):
                    bridge.validate_manifest(bad)

    def test_packaging_generator_matches_real_agent_and_staging_allowlist(self):
        import generate_trusted_payload as generator
        import payload_staging as staging
        self.assertEqual(generator._MANIFEST_FILES, staging.PAYLOAD_FILES)
        manifest = generator.build_manifest(ROOT)
        source = (ROOT / 'agent/linux_host_agent.py').read_text()
        versions = [line.split('=', 1)[1].strip().strip('"').strip("'")
                    for line in source.splitlines()
                    if line.startswith('VERSION = ')]
        self.assertEqual(len(versions), 1)
        self.assertEqual(manifest['agent_version'], versions[0])
        self.assertEqual(set(manifest['files']), staging.PAYLOAD_FILES)
        self.assertEqual(manifest['files']['agent/linux_host_agent.py'],
                         hashlib.sha256((ROOT / 'agent/linux_host_agent.py')
                                        .read_bytes()).hexdigest())

    def test_root_launcher_rejects_unsupported_python_before_action(self):
        for major_minor in ((3, 6), (3, 9)):
            with self.subTest(version=major_minor):
                with self.assertRaisesRegex(bridge.RequestError, 'unsupported_python'):
                    bridge.require_supported_python(major_minor)
        for major_minor in ((3, 10), (3, 11), (3, 12), (3, 13), (3, 14), (3, 15)):
            with self.subTest(version=major_minor):
                self.assertIsNone(bridge.require_supported_python(major_minor))

    def test_all_trusted_launcher_files_exist_under_repository_scripts(self):
        # The privileged helper checks exactly these installed names.
        # A mismatch between the repository's shell file and this list
        # would make every real privileged request fail on first use.
        scripts = ROOT / 'scripts'
        names = bridge._TRUSTED_MODULES
        self.assertEqual(len(names), len(set(names)))
        for name in names:
            with self.subTest(name=name):
                self.assertEqual(Path(name).name, name)
                self.assertTrue((scripts / name).is_file(),
                                f'Trusted launcher packaging file missing: {name}')
        entry = [name for name in names if name.endswith('.sh')]
        self.assertEqual(entry, ['installer-entry.sh'])
        documentation = (ROOT / 'docs/development/LINUX-INSTALLER-PRIVILEGED-RECOVERY.md').read_text()
        self.assertIn('/usr/libexec/computer-host-lan/' + entry[0] + ' --request-stdin',
                      documentation)

    def test_installed_shell_entry_uses_manual_selector_precedence(self):
        shell = (ROOT / 'scripts/installer-entry.sh').read_text()
        selector = (ROOT / 'scripts/python-selector.sh').read_text()
        order = 'python3 python3.14 python3.13 python3.12 python3.11 python3.10'
        self.assertIn('for candidate in ' + order + '; do', shell)
        self.assertIn('for candidate in ' + order + '; do', selector)
        self.assertIn('sys.version_info >= (3, 10)', shell)
        self.assertIn('sys.version_info >= (3, 10)', selector)
        self.assertIn(' -I -S -B -c ', shell)
        self.assertIn('exec "$PYTHON_BIN" -I -S -B', shell)
        self.assertIn('/usr/libexec/computer-host-lan/installer_root.py', shell)
        # Actual POSIX-shell syntax check in CI, including Python 3.10 runner.
        check = subprocess.run(['/bin/sh', '-n', str(ROOT / 'scripts/installer-entry.sh')],
                               text=True, capture_output=True, timeout=5)
        self.assertEqual(check.returncode, 0, check.stderr)

    def test_shell_selector_skips_old_default_python_and_picks_compatible(self):
        # Execute the shell's actual selection loop with fake PATH executables.
        # A private test directory stands in for /usr/bin; no sudo or root.
        shell = (ROOT / 'scripts/installer-entry.sh').read_text()
        first = shell.index('for candidate in python3 ')
        last = shell.index('\n[ -n "$PYTHON_BIN" ]', first)
        allowlisted_system_dirs = '/usr/sbin/*|/usr/bin/*|/sbin/*|/bin/*)'
        self.assertIn(allowlisted_system_dirs, shell[first:last])
        selector = shell[first:last].replace(allowlisted_system_dirs, '/*)')
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            for name in ('python3', 'python3.14', 'python3.13', 'python3.12',
                         'python3.11', 'python3.10'):
                stub = folder / name
                stub.write_text('#!/bin/sh\nexit ' +
                                ('0' if name == 'python3.11' else '1') + '\n')
                stub.chmod(0o755)
            program = 'PATH=' + str(folder) + '; PYTHON_BIN=; ' + selector + '\n' + 'printf "%s" "$PYTHON_BIN"\n'
            run = subprocess.run(['/bin/sh', '-c', program], text=True,
                                 capture_output=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, str(folder / 'python3.11'))
            # When the distro default becomes valid, it is chosen first.
            (folder / 'python3').write_text('#!/bin/sh\nexit 0\n')
            (folder / 'python3').chmod(0o755)
            run = subprocess.run(['/bin/sh', '-c', program], text=True,
                                 capture_output=True, timeout=10)
            self.assertEqual(run.stdout, str(folder / 'python3'))

    def test_source_checkout_never_satisfies_root_entrypoint(self):
        # Even when CI itself runs as UID=0, the helper is not trusted
        # unless installed at the exact fixed root-owned path with -I -S -B.
        with self.assertRaises(bridge.RequestError):
            bridge._read_root_manifest()

    def test_invalid_cli_arguments_never_attempt_elevation(self):
        out = mock.Mock()
        with mock.patch.object(bridge, '_reply', out), \
             mock.patch.object(bridge, '_read_root_manifest') as manifest:
            self.assertEqual(bridge.main(['--source', '/tmp/foo']), 2)
            manifest.assert_not_called()
        self.assertEqual(out.call_args.args[0]['error_code'], 'invalid_request')


if __name__ == '__main__':
    unittest.main()
