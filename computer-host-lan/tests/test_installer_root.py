"""Pure schema/dispatch tests for the proposed installed-only root helper.

Never elevate, invoke sudo, read a live manifest or modify the host.
"""
from __future__ import annotations

import hashlib
import io
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
import credential_continuity as continuity


class FakeBackend:
    def __init__(self):
        self.calls = []
        self.recovered = mock.Mock(status='rolled_back', operation=None, credential_result=
                                   continuity.Result(reason='continuity_unverified_after_interruption'))
        self.removed = mock.Mock(status='uninstalled', identity_preserved='verified',
                                 credential_result=continuity.Result('verified', 'absent'))

    def run(self, request, source, files):
        self.calls.append((request, source, files))
        return mock.Mock(status='installed', operation=request.operation,
                         identity_preserved='not_verified', source_verified=True,
                         credential_result=continuity.Result('absent', 'newly_present'))

    def uninstall(self):
        self.calls.append('uninstall')
        return self.removed

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
                                           journal=self.journal,
                                           selected_python='/usr/bin/python3')
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

    def test_privileged_upgrade_uses_shell_path_not_gentoo_sys_executable(self):
        # Actual hydra result: shell selected /usr/sbin/python3, but
        # sys.executable under Gentoo python-exec is NOT in that location.
        # The trusted shell's explicit handoff must win, while the
        # transaction engine's fixed system-dir allowlist remains strict.
        with mock.patch.object(
                bridge.sys, 'executable',
                '/usr/lib/python-exec/python3.14/python3'):
            reply = bridge.dispatch(
                self.parse(action='upgrade', power='preserve',
                           wol_interface=None),
                self.manifest, backend=self.backend, journal=self.journal,
                selected_python='/usr/sbin/python3')
            self.assertEqual(reply['status'], 'installed')
            request, source, hashes = self.backend.calls[-1]
            request.validate()
            self.assertEqual(request.python_bin, '/usr/sbin/python3')
            self.assertEqual(request.expected_version, '0.4.6-rc.2')

    def test_selected_python_handoff_is_exact_and_required_for_install(self):
        names = ('python3', 'python3.14', 'python3.13',
                 'python3.12', 'python3.11', 'python3.10')
        for root in ('/usr/sbin', '/usr/bin', '/sbin', '/bin'):
            for name in names:
                path = root + '/' + name
                self.assertEqual(
                    bridge.selected_python_from_argv(
                        ['--request-stdin', '--selected-python', path]),
                    path)

        self.assertIsNone(bridge.selected_python_from_argv(
            ['--request-stdin']))  # read-only legacy status is still allowed
        bridge.validate_python_handoff({'action': 'status'}, None)
        for action in ('install', 'upgrade', 'repair', 'recover', 'uninstall'):
            with self.subTest(action=action), self.assertRaises(bridge.RequestError):
                bridge.validate_python_handoff({'action': action}, None)
        bridge.validate_python_handoff({'action': 'upgrade'}, '/usr/sbin/python3')
        for argv in (
            [], ['--selected-python', '/usr/sbin/python3'],
            ['--request-stdin', '--selected-python'],
            ['--request-stdin', '--selected-python',
             '/usr/lib/python-exec/python3.14/python3'],
            ['--request-stdin', '--selected-python', '/tmp/python3'],
            ['--request-stdin', '--selected-python', '/usr/local/bin/python3'],
            ['--request-stdin', '--selected-python', '/usr/bin/../sbin/python3'],
            ['--request-stdin', '--selected-python', '/usr/bin/python3',
             'extra'],
        ):
            with self.subTest(argv=argv), self.assertRaises(bridge.RequestError):
                bridge.selected_python_from_argv(argv)

        # An attacker or a stale direct root entry cannot trigger an
        # install using the legacy status-only argv mode.
        with self.assertRaises(bridge.RequestError):
            bridge.dispatch(self.parse(action='upgrade'),
                            self.manifest, backend=self.backend,
                            journal=self.journal)

        # Status and recovery are independent of Python systemd selection.
        self.assertEqual(
            bridge.dispatch({'action': 'status'}, self.manifest,
                            backend=self.backend, journal=self.journal)['status'],
            'passed')

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

    def test_recovery_wol_review_warning_is_fixed_and_optional(self):
        self.backend.recovered.wol_review_required = True
        result = bridge.dispatch({'action': 'recover'}, self.manifest,
                                 backend=self.backend, journal=self.journal)
        self.assertEqual(result['recovery_status'], 'rolled_back')
        self.assertIs(result['wol_review_required'], True)
        self.backend.recovered.wol_review_required = 'private network information'
        result = bridge.dispatch({'action': 'recover'}, self.manifest,
                                 backend=self.backend, journal=self.journal)
        self.assertNotIn('wol_review_required', result)

    def test_rollback_wol_review_warning_is_fixed(self):
        import installer_transaction as engine
        body = json.dumps(dict(schema_version=1, action='upgrade',
                               source='/usr/libexec/computer-host-lan/payload',
                               power='preserve', wol_interface=None)).encode()
        with mock.patch.object(bridge, '_read_root_manifest', return_value=self.manifest), \
                mock.patch.object(bridge, 'dispatch', side_effect=engine.ControllerError(
                    'rolled_back', wol_review_required=True)), \
                mock.patch.object(bridge.sys, 'stdin', mock.Mock(buffer=io.BytesIO(body))), \
                mock.patch.object(bridge, '_reply') as reply:
            rc = bridge.main(['--request-stdin', '--selected-python', '/usr/bin/python3'])
        self.assertEqual(rc, 3)
        payload = reply.call_args.args[0]
        self.assertEqual(payload['error_code'], 'rolled_back')
        self.assertIs(payload['wol_review_required'], True)

    def test_schema_v2_uninstall_is_exact_and_requires_trusted_python(self):
        request = bridge.parse_request(b'{"schema_version":2,"action":"uninstall"}')
        self.assertEqual(request, {'action': 'uninstall'})
        with self.assertRaises(bridge.RequestError):
            bridge.dispatch(request, self.manifest, backend=self.backend,
                            journal=self.journal)
        self.assertEqual(self.backend.calls, [])
        for status in ('uninstalled', 'uninstalled_cleanup_required'):
            self.backend.removed.status = status
            response = bridge.dispatch(
                request, self.manifest, backend=self.backend,
                journal=self.journal, selected_python='/usr/sbin/python3')
            self.assertEqual(response, dict(status=status, operation='uninstall',
                identity_preserved='verified', secrets_included=False,
                **continuity.Result('verified', 'absent').public()))
            self.assertEqual(self.backend.calls[-1], 'uninstall')
        for payload in (
                b'{"schema_version":1,"action":"uninstall"}',
                b'{"schema_version":2,"action":"install"}',
                b'{"schema_version":2,"action":"uninstall","power":""}',
                b'{"schema_version":2,"action":"uninstall","wol_interface":null}',
                b'{"schema_version":2,"action":"uninstall","source":"/tmp"}',
                b'{"schema_version":2,"action":"uninstall","action":"uninstall"}',
                b'{"schema_version":2,"Action":"uninstall"}',
                b'{"schema_version":2.0,"action":"uninstall"}'):
            with self.subTest(payload=payload), self.assertRaises(bridge.RequestError):
                bridge.parse_request(payload)

    def test_unexpected_uninstall_outcome_requires_recovery(self):
        from installer_transaction import ControllerError

        request = bridge.parse_request(b'{"schema_version":2,"action":"uninstall"}')
        for status, identity in (('unexpected', 'verified'),
                                 ('uninstalled', 'unexpected')):
            self.backend.removed.status = status
            self.backend.removed.identity_preserved = identity
            with self.subTest(status=status, identity=identity):
                with self.assertRaises(ControllerError) as error:
                    bridge.dispatch(request, self.manifest, backend=self.backend,
                                    journal=self.journal,
                                    selected_python='/usr/sbin/python3')
                self.assertEqual(error.exception.code, 'recovery_required')

    def test_recovery_exposes_only_fixed_operation(self):
        for operation in ('uninstall', 'upgrade', 'private-value', None):
            self.backend.recovered.operation = operation
            result = bridge.dispatch({'action': 'recover'}, self.manifest,
                                     backend=self.backend, journal=self.journal)
            self.assertEqual(result.get('recovery_operation'),
                             operation if operation in ('uninstall', 'upgrade') else None)

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

    def test_future_restore_and_adopt_requests_are_not_dispatched(self):
        for action in ('restore', 'adopt'):
            for schema in (1, 2, 3):
                for extras in ({}, {'snapshot': 'snapshot-abcdefgh'},
                               {'source': '/tmp/payload', 'power': 'preserve',
                                'wol_interface': None}):
                    with self.subTest(action=action, schema=schema, extras=extras):
                        raw = json.dumps(dict(schema_version=schema,
                                              action=action, **extras)).encode()
                        with self.assertRaises(bridge.RequestError):
                            bridge.parse_request(raw)

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

    def test_root_abort_response_has_only_fixed_preapply_stage(self):
        import installer_transaction as engine

        body = json.dumps(dict(schema_version=1, action='upgrade',
                               source='/usr/libexec/computer-host-lan/payload',
                               power='preserve', wol_interface=None)).encode()
        for stage in ('payload', 'existing_state', 'plan', 'snapshot'):
            with self.subTest(stage=stage), \
                    mock.patch.dict(os.environ, {}, clear=False), \
                    mock.patch.object(bridge, '_read_root_manifest',
                                      return_value=self.manifest), \
                    mock.patch.object(bridge, 'dispatch', side_effect=(
                        engine.ControllerError('aborted', failure_stage=stage))), \
                    mock.patch.object(bridge.sys, 'stdin',
                                      mock.Mock(buffer=io.BytesIO(body))), \
                    mock.patch.object(bridge, '_reply') as reply:
                rc = bridge.main(['--request-stdin', '--selected-python',
                                  '/usr/sbin/python3'])
                self.assertEqual(rc, 3)
                result = reply.call_args.args[0]
                self.assertEqual(result['error_code'], 'aborted')
                self.assertEqual(result['failure_stage'], stage)
                self.assertFalse(result['secrets_included'])
                self.assertNotIn('source', result)
                self.assertNotIn('identity', result)

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

    def test_installed_shell_entry_static_contract_and_syntax(self):
        # Fixed path and argv packaging guard. Selection and environment
        # behavior are tested by executing fixture launchers below.
        shell = (ROOT / 'scripts/installer-entry.sh').read_text()
        selector = (ROOT / 'scripts/python-selector.sh').read_text()
        order = 'python3 python3.14 python3.13 python3.12 python3.11 python3.10'
        self.assertIn('for candidate in ' + order + '; do', shell)
        self.assertIn('for candidate in ' + order + '; do', selector)
        self.assertIn('sys.version_info >= (3, 10)', shell)
        self.assertIn('sys.version_info >= (3, 10)', selector)
        self.assertIn(' -I -S -B -c ', shell)
        self.assertIn('exec "$PYTHON_BIN" -I -S -B', shell)
        self.assertIn('--request-stdin --selected-python "$PYTHON_BIN"', shell)
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

    def test_installed_entry_uses_fixed_path_and_scrubs_python_environment(self):
        # Execute the complete shell entry with private stand-ins for the
        # fixed system PATH/allowlist. Final Python is only an argv recorder.
        source = (ROOT / 'scripts/installer-entry.sh').read_text()
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            system = base / 'system'
            hostile = base / 'hostile'
            system.mkdir()
            hostile.mkdir()
            log = base / 'calls'

            def stub(folder, name, body):
                file = folder / name
                file.write_text('#!/bin/sh\n' + body + '\n')
                file.chmod(0o755)

            stub(hostile, 'id', 'printf "0\\n"')
            stub(hostile, 'python3', 'printf "HOSTILE\\n" >> "$CALL_LOG"; exit 99')
            stub(system, 'python3', 'printf "old:%s\\n" "$*" >> "$CALL_LOG"; exit 1')
            stub(system, 'python3.14', '''printf 'selected:%s\\n' "$*" >> "$CALL_LOG"
[ "${PYTHONPATH+x}${PYTHONHOME+x}${PYTHONSTARTUP+x}${PYTHONUSERBASE+x}" = "" ] || exit 99
exit 0''')
            fixed = 'PATH=/usr/sbin:/usr/bin:/sbin:/bin'
            allowed = '/usr/sbin/*|/usr/bin/*|/sbin/*|/bin/*)'
            self.assertEqual(source.count(fixed), 1)
            self.assertEqual(source.count(allowed), 1)
            fixture = base / 'entry.sh'
            fixture.write_text(source.replace(fixed, 'PATH=' + str(system))
                               .replace(allowed, str(system) + '/*)'))
            result = subprocess.run(['/bin/sh', str(fixture), '--request-stdin'],
                                    env={'PATH': str(hostile), 'CALL_LOG': str(log),
                                         'PYTHONPATH': 'bad', 'PYTHONHOME': 'bad',
                                         'PYTHONSTARTUP': 'bad', 'PYTHONUSERBASE': 'bad'},
                                    input='{}', text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = log.read_text().splitlines()
            self.assertEqual(len(calls), 3)
            self.assertTrue(calls[0].startswith('old:-I -S -B -c '))
            self.assertTrue(calls[1].startswith('selected:-I -S -B -c '))
            self.assertEqual(calls[2], 'selected:-I -S -B '
                             '/usr/libexec/computer-host-lan/installer_root.py '
                             '--request-stdin --selected-python ' + str(system / 'python3.14'))

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
