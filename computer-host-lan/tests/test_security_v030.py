"""Black-box LAN security regression tests, all loopback-only and non-root."""
import http.client
import json
from pathlib import Path
import socket
import sys
import threading
import time
import unittest
from unittest import mock
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent'))
import linux_host_agent as agent


class NonceSecurityTests(unittest.TestCase):
    def test_capacity_never_invalidates_live_challenges(self):
        nonces = agent.Nonces(max_pending=2)
        one, two = nonces.issue(), nonces.issue()
        with self.assertRaises(agent.NonceCapacityError):
            nonces.issue()
        self.assertTrue(nonces.consume(one))
        self.assertTrue(nonces.consume(two))
        self.assertFalse(nonces.consume(one))

    def test_capacity_recovers_after_consumption(self):
        n = agent.Nonces(max_pending=1)
        token = n.issue()
        n.consume(token)
        self.assertNotEqual(n.issue(), token)

    def test_expired_challenges_are_reaped(self):
        n = agent.Nonces(max_pending=1, ttl=0.01)
        expired = n.issue()
        time.sleep(0.025)
        self.assertFalse(n.consume(expired))
        self.assertTrue(len(n.issue()) == 48)

    def test_per_ip_and_global_rate_limits(self):
        limiter = agent.ChallengeRateLimiter(per_ip=2, global_limit=3)
        self.assertTrue(limiter.permit('192.0.2.10'))
        self.assertTrue(limiter.permit('192.0.2.10'))
        self.assertFalse(limiter.permit('192.0.2.10'))
        self.assertTrue(limiter.permit('192.0.2.11'))
        self.assertFalse(limiter.permit('192.0.2.12'))

    def test_stale_rate_limit_window_resets(self):
        limiter = agent.ChallengeRateLimiter(per_ip=1, global_limit=1, window=0.01)
        self.assertTrue(limiter.permit('127.0.0.1'))
        self.assertFalse(limiter.permit('127.0.0.1'))
        time.sleep(0.025)
        self.assertTrue(limiter.permit('127.0.0.1'))

    def test_bounded_ip_cache_rejects_extra_addresses(self):
        limiter = agent.ChallengeRateLimiter(per_ip=5, global_limit=100, max_clients=1)
        self.assertTrue(limiter.permit('192.0.2.1'))
        self.assertFalse(limiter.permit('192.0.2.2'))
        self.assertTrue(limiter.permit('192.0.2.1'))


class LiveHTTPSecurityTests(unittest.TestCase):
    def setUp(self):
        self.state = agent.AgentState('33333333-3333-4333-8333-333333333333', '02'*32,
                                     True, '/nonexistent/power.sock', None, None)
        self.server = agent.BoundedHTTPServer(('127.0.0.1', 0), agent.make_handler(self.state),
                                              max_clients=4, io_timeout=0.5)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=3)

    def request(self, path, method='GET', headers=None, data=None):
        request = Request(self.base+path, method=method, headers=headers or {}, data=data)
        try:
            with urlopen(request, timeout=2) as resp:
                return resp.status, json.load(resp), resp.headers
        except HTTPError as exc:
            return exc.code, json.loads(exc.read()), exc.headers

    def test_signed_power_protocol_unchanged(self):
        status, body, _ = self.request('/v2/challenge')
        self.assertEqual(status, 200)
        nonce = body['nonce']
        path = '/v2/power/reboot'
        with mock.patch.object(agent, 'request_power') as invoke:
            headers = {'X-ComputerHost-Nonce': nonce,
                       'X-ComputerHost-Signature': agent.signature(self.state.secret, path, nonce)}
            self.assertEqual(self.request(path, method='POST', headers=headers)[0], 202)
            invoke.assert_called_once_with(self.state.helper_socket, 'reboot')
            self.assertEqual(self.request(path, method='POST', headers=headers)[0], 401)

    def test_invalid_signature_cannot_burn_a_valid_nonce(self):
        _, body, _ = self.request('/v2/challenge')
        nonce = body['nonce']
        path = '/v2/power/shutdown'
        invalid = {'X-ComputerHost-Nonce': nonce, 'X-ComputerHost-Signature': 'f'*64}
        self.assertEqual(self.request(path, method='POST', headers=invalid)[0], 401)
        valid = {'X-ComputerHost-Nonce': nonce,
                 'X-ComputerHost-Signature': agent.signature(self.state.secret, path, nonce)}
        with mock.patch.object(agent, 'request_power') as invoke:
            self.assertEqual(self.request(path, method='POST', headers=valid)[0], 202)
            invoke.assert_called_once()

    def test_challenge_rate_limit_exposes_retry_after(self):
        self.state.challenge_limits = agent.ChallengeRateLimiter(per_ip=2, global_limit=2)
        self.assertEqual(self.request('/v2/challenge')[0], 200)
        self.assertEqual(self.request('/v2/challenge')[0], 200)
        code, body, hdr = self.request('/v2/challenge')
        self.assertEqual((code, body['error'], hdr['Retry-After']),
                         (429, 'challenge rate limit exceeded', '30'))
        self.assertEqual(len(self.state.nonces.tokens), 2)

    def test_challenge_store_full_does_not_reset_tokens(self):
        self.state.nonces = agent.Nonces(max_pending=1)
        first = self.request('/v2/challenge')[1]['nonce']
        self.assertEqual(self.request('/v2/challenge')[0], 429)
        self.assertTrue(self.state.nonces.consume(first))
        self.assertEqual(self.request('/v2/challenge')[0], 200)

    def test_post_body_rejected_without_invoking_helper(self):
        _, challenge, _ = self.request('/v2/challenge')
        nonce = challenge['nonce']
        path = '/v2/power/reboot'
        headers = {'X-ComputerHost-Nonce': nonce,
                   'X-ComputerHost-Signature': agent.signature(self.state.secret, path, nonce)}
        with mock.patch.object(agent, 'request_power') as invoke:
            self.assertEqual(self.request(path, method='POST', headers=headers, data=b'something')[0], 400)
            invoke.assert_not_called()

    def test_unexpected_query_parameters_not_dispatched(self):
        self.assertEqual(self.request('/v2/health?debug=true')[0], 404)
        self.assertEqual(self.request('/v2/power/reboot?evil=true', 'POST')[0], 404)

    def test_response_disables_caching_and_is_not_keepalive(self):
        status, _, headers = self.request('/v2/health')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(headers['Connection'], 'close')

    def test_partial_header_read_expires_without_exhausting_threads(self):
        with socket.create_connection(('127.0.0.1', self.server.server_port), timeout=1) as conn:
            conn.sendall(b'GET /v2/health HTTP/1.1\r\nHost: ')  # intentional incomplete request
            time.sleep(0.8)
            self.assertEqual(conn.recv(2048), b'')
        self.assertEqual(self.request('/v2/health')[0], 200)

    def test_header_byte_budget_rejects_oversized_requests(self):
        with socket.create_connection(('127.0.0.1', self.server.server_port), timeout=2) as conn:
            conn.sendall(b'GET /v2/health HTTP/1.1\r\nHost: localhost\r\nX-Oversized: ' +
                         b'x' * (agent.MAX_HTTP_HEADER_BYTES + 100) + b'\r\n\r\n')
            response = conn.recv(4096)
            self.assertNotIn(b'HTTP/1.0 200', response)
        self.assertEqual(self.request('/v2/health')[0], 200)

    def test_total_header_deadline_even_with_regular_bytes(self):
        import io
        connection = mock.Mock()
        reader = agent.HeaderBudgetReader(io.BytesIO(b'GET /v2/health HTTP/1.0\r\n'),
                                           connection, io_timeout=10, deadline_seconds=0.01)
        time.sleep(0.025)
        with self.assertRaises(TimeoutError):
            reader.readline()

    def test_slow_byte_drip_cannot_hold_all_connection_slots(self):
        # The former reader only checked the deadline before readline(). A
        # client sending bytes faster than the inactivity timeout could keep
        # that single buffered readline blocked indefinitely.
        self.server.header_timeout = 0.25
        slow_clients = []
        try:
            for _ in range(4):  # exhaust this test server's four handler slots
                conn = socket.create_connection(
                    ('127.0.0.1', self.server.server_port), timeout=1
                )
                conn.settimeout(1)
                conn.sendall(b'GET /v2/health')  # deliberately no CRLF
                slow_clients.append(conn)

            end = time.monotonic() + 0.6
            while time.monotonic() < end:
                for conn in slow_clients:
                    try:
                        conn.sendall(b'a')
                    except OSError:
                        pass  # the absolute deadline should have closed it
                time.sleep(0.03)

            # All slow clients should have been closed and their handler slots
            # released; an ordinary hub-style request must succeed immediately.
            self.assertEqual(self.request('/v2/health')[0], 200)
        finally:
            for conn in slow_clients:
                conn.close()

    def test_hard_active_connection_bound(self):
        self.server._slots.acquire()
        self.server._slots.acquire()
        self.server._slots.acquire()
        self.server._slots.acquire()
        try:
            with self.assertRaises((OSError, URLError, http.client.RemoteDisconnected)):
                self.request('/v2/health')
        finally:
            for _ in range(4):
                self.server._slots.release()
        self.assertEqual(self.request('/v2/health')[0], 200)


if __name__ == '__main__':
    unittest.main()
