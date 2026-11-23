"""Read-only runtime verifier: fully mocked loopback, no host services or keys."""
from __future__ import annotations

import contextlib
from io import StringIO
import json
from pathlib import Path
import socket
import sys
import threading
import time
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
    'power_actions': ['reboot', 'shutdown', 'suspend'],
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


def http_response(payload: bytes, *, status: bytes = b'200 OK',
                  mime: bytes = b'application/json') -> bytes:
    return (b'HTTP/1.1 ' + status +
            b'\r\nContent-Type: ' + mime +
            b'\r\nContent-Length: ' + str(len(payload)).encode('ascii') +
            b'\r\nConnection: close\r\n\r\n' + payload)


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

    def test_invalid_agent_version_never_leaks_private_data(self):
        # A listener is not trusted, even when it answers from loopback.
        # Failed checks must not echo arbitrary JSON through agent_version.
        malicious_versions = [
            {'leak': UUID, 'nested': ['control-token', {'id': UUID}]},
            ['unexpected', UUID],
            UUID,
            'x' * 12000 + UUID,
            8675309,
            None,
            True,
        ]
        for untrusted in malicious_versions:
            with self.subTest(input_type=type(untrusted).__name__,
                              size=len(str(untrusted))):
                result = rv.verify_runtime(
                    service_status='active',
                    fetch=fake_fetch({**INFO, 'agent_version': untrusted}, HEALTH))
                self.assertEqual(result['status'], 'failed')
                self.assertFalse(result['runtime_verified'])
                self.assertIsNone(result['agent_version'])
                serialized = json.dumps(result)
                self.assertNotIn(UUID, serialized)
                self.assertNotIn('control-token', serialized)
                self.assertNotIn('nested', serialized)

    def test_shipped_agent_power_action_contract_matches_verifier(self):
        # If the agent adds/removes an action, CI must force a matching
        # update to the verifier's expected v2 protocol action set.
        import runpy
        shipped = runpy.run_path(str(ROOT / 'agent' / 'linux_host_agent.py'))
        self.assertEqual(sorted(shipped['ALLOWED_ACTIONS']),
                         sorted(rv.EXPECTED_POWER_ACTIONS))
        self.assertEqual(INFO['power_actions'],
                         sorted(rv.EXPECTED_POWER_ACTIONS))

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
                     {**INFO, 'features': ['power-control'] * 40},
                     {**INFO, 'power_actions': []},
                     {**INFO, 'power_actions': ['shutdown', 'reboot', 'suspend']}):
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

    def test_bounded_protocol_parser_requires_exact_headers_and_json(self):
        good = http_response(json.dumps(INFO).encode())
        self.assertEqual(rv._parse_http_json(good)['id'], UUID)
        self.assertIsNone(rv._parse_http_json(good[:40]))
        self.assertIsNone(rv._parse_http_json(good[:-4]))
        self.assertIsNone(rv._parse_http_json(http_response(b'{}', status=b'302 Found')))
        self.assertIsNone(rv._parse_http_json(http_response(b'{}', mime=b'text/html')))
        self.assertIsNone(rv._parse_http_json(http_response(b'not-json')))
        self.assertIsNone(rv._parse_http_json(http_response(b'[]')))
        self.assertIsNone(rv._parse_http_json(http_response(b'X' * (rv.MAX_RESPONSE + 1))))
        self.assertIsNone(rv._parse_http_json(good.replace(
            b'Connection: close', b'Content-Length: 2\r\nConnection: close')))
        self.assertIsNone(rv._parse_http_json(good.replace(
            b'Connection: close', b'Transfer-Encoding: chunked\r\nConnection: close')))
        self.assertIsNone(rv._parse_http_json(good.replace(
            b'Connection: close', b'Content-Encoding: gzip\r\nConnection: close')))
        self.assertIsNone(rv._parse_http_json(good.replace(
            b'Content-Length: ' + str(len(json.dumps(INFO).encode())).encode(),
            b'Content-Length: 99999999')))
        self.assertIsNone(rv._read_json(8765, 'http://unsafe.example/v2/info',
                                        exchange=lambda *a: good))
        self.assertIsNone(rv._read_json(80, '/v2/info', exchange=lambda *a: good))
        self.assertEqual(rv._read_json(8765, '/v2/info',
                                      exchange=lambda port, path: good)['id'], UUID)

    def test_real_loopback_transport_has_absolute_deadline_on_slow_drip(self):
        # This listener is created only inside the test, on loopback, with
        # an ephemeral port; it cannot contact a real hub or modify services.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            response = http_response(b'{}')
            error = []

            def server():
                try:
                    peer, _ = listener.accept()
                    with peer:
                        peer.settimeout(1)
                        request = peer.recv(4096)
                        if b'GET /v2/health HTTP/1.1' not in request:
                            error.append('wrong fixed path')
                        peer.sendall(response[:-1])
                        time.sleep(0.28)  # slower than the verifier deadline
                        try:
                            peer.sendall(response[-1:])
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                except OSError as exc:
                    error.append(type(exc).__name__)

            worker = threading.Thread(target=server, daemon=True)
            worker.start()
            start = time.monotonic()
            with mock.patch.object(rv, 'REQUEST_DEADLINE_SECONDS', 0.12):
                answer = rv._read_json(port, '/v2/health')
            elapsed = time.monotonic() - start
            worker.join(timeout=1.0)
            self.assertIsNone(answer)
            self.assertLess(elapsed, 0.40)
            self.assertFalse(error, error)

    def test_real_loopback_transport_accepts_correct_fixed_path(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            requests = []

            def server():
                peer, _ = listener.accept()
                with peer:
                    requests.append(peer.recv(4096))
                    peer.sendall(http_response(json.dumps(HEALTH).encode()))

            worker = threading.Thread(target=server, daemon=True)
            worker.start()
            result = rv._read_json(port, '/v2/health')
            worker.join(timeout=2)
            self.assertEqual(result['id'], UUID)
            self.assertIn(b'Host: 127.0.0.1', requests[0])
            self.assertIn(b'GET /v2/health HTTP/1.1', requests[0])

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
