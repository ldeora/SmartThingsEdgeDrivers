"""Pure schema/dispatch tests for the proposed installed-only root helper.

Never elevate, invoke sudo, read a live manifest or modify the host.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
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
