"""Read-only runtime verifier: fully mocked loopback, no host services or keys."""
from __future__ import annotations

import contextlib
from io import StringIO
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import installer_api as api
import runtime_verify as rv


UUID = '11111111-1111-4111-8111-111111111111'
DIFFERENT_UUID = '22222222-2222-4222-8222-222222222222'
INFO = {
    'protocol': 'computer-host-agent', 'api_version': 2,
    'platform': 'linux', 'id': UUID, 'agent_version': '0.4.6-rc.2',
    'hostname': 'private-hostname', 'wol_mac': 'private-mac',
    'features': ['health', 'metrics', 'wol-metadata', 'power-control'],
}
HEALTH = {
    'protocol': 'computer-host-agent', 'api_version': 2,
    'platform': 'linux', 'id': UUID, 'status': 'running',
    'boot_id': 'private-boot-id',
}


def fake_fetch(info=INFO, health=HEALTH):
    def fetch(port, path):
        assert port == 8765
        assert path in ('/v2/info', '/v2/health')
        return dict(info) if path == '/v2/info' and info is not None else (
            dict(health) if path == '/v2/health' and health is not None else None
        )
    return fetch


class FakeResponse:
    def __init__(self, *, status=200, mime='application/json; charset=utf-8',
                 data=b'{}'):
        self.status, self.mime, self.data = status, mime, data
        self.max_read = None

    def getheader(self, name, default=''):
        return self.mime if name == 'Content-Type' else default

    def read(self, limit):
        self.max_read = limit
        return self.data[:limit]


class FakeConnection:
    def __init__(self, response):
        self.response = response
        self.requested = None
        self.closed = False

    def request(self, method, path, headers=None):
        self.requested = (method, path, headers)

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class RuntimeVerifierTests(unittest.TestCase):
    def test_complete_verified_agent_and_private_identity_comparison(self):
        result = rv.verify_runtime(
            service_status='active', expected_version='0.4.6-rc.2',
            expected_identity=UUID, expected_power=True,
            fetch=fake_fetch(),
        )
        self.assertEqual(result['status'], 'passed')
        self.assertTrue(result['runtime_verified'])
        self.assertEqual(result['identity_preserved'], 'passed')
        self.assertEqual(result['power_control'], 'enabled')
        self.assertEqual(result['agent_version'], '0.4.6-rc.2')
        encoded = json.dumps(result)
        for private in (UUID, 'private-hostname', 'private-mac', 'private-boot-id',
                        'control-token', 'installation-id'):
            self.assertNotIn(private, encoded)
        self.assertFalse(result['secrets_included'])
        self.assertEqual(result['schema_version'], 1)

    def test_public_probe_does_not_require_privileged_expected_uuid(self):
        result = rv.verify_runtime(service_status='active', fetch=fake_fetch())
        self.assertEqual(result['status'], 'passed')
        self.assertTrue(result['runtime_verified'])
        self.assertEqual(result['identity_preserved'], 'not_verified')
        self.assertNotIn(UUID, json.dumps(result))

    def test_missing_agent_invalid_protocol_and_wrong_version(self):
        vectors = [
            (None, HEALTH, 'missing info'),
            (INFO, None, 'missing health'),
            ({**INFO, 'protocol': 'linux-host-agent'}, HEALTH, 'legacy v1'),
            (INFO, {**HEALTH, 'platform': 'windows'}, 'wrong platform'),
            ({**INFO, 'api_version': '2'}, HEALTH, 'wrong API version type'),
            ({**INFO, 'agent_version': '1.2.3'}, HEALTH, 'wrong version'),
            (INFO, {**HEALTH, 'status': 'starting'}, 'not running'),
        ]
        for info, health, reason in vectors:
            with self.subTest(reason=reason):
                result = rv.verify_runtime(service_status='active',
                    expected_version='0.4.6-rc.2', expected_identity=UUID,
                    fetch=fake_fetch(info, health))
                self.assertEqual(result['status'], 'failed')
                self.assertFalse(result['runtime_verified'])
                self.assertNotIn(UUID, json.dumps(result))

    def test_agent_identity_mismatch_and_invalid_identity(self):
        for identity in (DIFFERENT_UUID, 'not-a-uuid', None):
            with self.subTest(identity=identity):
                health = {**HEALTH, 'id': identity}
                result = rv.verify_runtime(service_status='active',
                                           expected_identity=UUID,
                                           fetch=fake_fetch(INFO, health))
                self.assertFalse(result['identity_consistent'])
                self.assertEqual(result['identity_preserved'], 'failed')
                self.assertEqual(result['status'], 'failed')
        result = rv.verify_runtime(service_status='active',
                                   expected_identity=DIFFERENT_UUID,
                                   fetch=fake_fetch())
        self.assertTrue(result['identity_consistent'])
        self.assertEqual(result['identity_preserved'], 'failed')

    def test_power_expectation_and_untrusted_features(self):
        result = rv.verify_runtime(service_status='active', expected_power=False,
                                   fetch=fake_fetch())
        self.assertEqual(result['status'], 'failed')
        for info in ({**INFO, 'features': 'power-control'},
                     {**INFO, 'features': ['power-control'] * 40}):
            self.assertEqual(rv.verify_runtime(service_status='active',
                            fetch=fake_fetch(info, HEALTH))['status'], 'failed')

    def test_service_not_running_is_not_verified_as_success(self):
        for state in ('inactive', 'failed', 'activating'):
            result = rv.verify_runtime(service_status=state, fetch=fake_fetch())
            self.assertEqual(result['status'], 'failed')
            self.assertFalse(result['runtime_verified'])
        result = rv.verify_runtime(service_status='unknown', fetch=fake_fetch())
        self.assertEqual(result['status'], 'not_verified')
        self.assertFalse(result['runtime_verified'])

    def test_port_and_argument_rejection(self):
        for bad in (0, 80, 65536, True, -1, '8765'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                rv.verify_runtime(port=bad)
        with self.assertRaises(ValueError):
            rv.verify_runtime(expected_version='1.2.3\nFAKE')
        with self.assertRaises(ValueError):
            rv.verify_runtime(expected_identity='not-uuid')
        with self.assertRaises(ValueError):
            rv.verify_runtime(expected_power='true')
        with self.assertRaises(ValueError):
            rv.verify_runtime(service_status='spoofed')

    def test_http_client_is_local_fixed_path_bounded_and_not_redirected(self):
        fake = FakeResponse(data=json.dumps(INFO).encode())
        conn = FakeConnection(fake)
        result = rv._read_json(8765, '/v2/info', connection_factory=lambda host, port, timeout: (
            self.assertEqual((host, port, timeout), ('127.0.0.1', 8765, 2)) or conn
        ))
        self.assertEqual(result['id'], UUID)
        self.assertEqual(conn.requested[0:2], ('GET', '/v2/info'))
        self.assertTrue(conn.closed)
        self.assertEqual(fake.max_read, rv.MAX_RESPONSE + 1)
        self.assertIsNone(rv._read_json(8765, 'http://attacker.test', connection_factory=lambda *a: conn))
        self.assertIsNone(rv._read_json(80, '/v2/info', connection_factory=lambda *a: conn))
        for response in (FakeResponse(status=302), FakeResponse(status=401),
                         FakeResponse(mime='text/html'),
                         FakeResponse(mime=None),
                         FakeResponse(data=b'['),
                         FakeResponse(data=b'not-json'),
                         FakeResponse(data=b'X' * (rv.MAX_RESPONSE + 1))):
            with self.subTest(response=response):
                c = FakeConnection(response)
                self.assertIsNone(rv._read_json(8765, '/v2/info',
                                                connection_factory=lambda *a, **kw: c))
                self.assertTrue(c.closed)

    def test_json_api_verifier_sanitizes_every_output_and_validates_port(self):
        response = rv.verify_runtime(service_status='active', fetch=fake_fetch())
        out, err = StringIO(), StringIO()
        with mock.patch.object(api, 'verify_live', return_value=response) as verifier, \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = api.main(['verify', '--port', '8765', '--expected-version', '0.4.6-rc.2'])
        self.assertEqual(rc, 0)
        verifier.assert_called_once_with(port=8765, expected_version='0.4.6-rc.2')
        self.assertEqual(err.getvalue(), '')
        self.assertEqual(json.loads(out.getvalue())['operation'], 'verify')
        self.assertNotIn(UUID, out.getvalue())
        for args in (['verify', '--port', '80'], ['verify', '--port', 'abc'],
                     ['verify', '--expected-version', 'bad;command'],
                     ['verify', '--bogus']):
            with self.subTest(args=args):
                out, err = StringIO(), StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    rc = api.main(args)
                self.assertEqual(rc, 2)
                self.assertEqual(out.getvalue(), '')
                failure = json.loads(err.getvalue())
                self.assertEqual(failure['error']['code'], 'invalid_argument')
                self.assertEqual(failure['operation'], 'verify')
                self.assertEqual(err.getvalue().count('\n'), 1)

    def test_api_uses_only_service_state_probe_and_no_credential_reads(self):
        with mock.patch.object(api, 'service_state', return_value='active') as probe, \
             mock.patch.object(api.runtime_verify, 'verify_runtime',
                               return_value={'operation': 'verify'}) as verify, \
             mock.patch.object(api.Path, 'is_dir', return_value=True):
            self.assertEqual(api.verify_live(port=8765), {'operation': 'verify'})
        probe.assert_called_once_with('linux-host-agent.service', 'is-active',
                                      systemd_present=True)
        verify.assert_called_once_with(port=8765, expected_version=None,
                                       service_status='active')


if __name__ == '__main__':
    unittest.main()
