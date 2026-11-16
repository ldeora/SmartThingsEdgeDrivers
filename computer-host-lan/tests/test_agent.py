import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))
import linux_host_agent as agent
import power_helper as helper


class StateTests(unittest.TestCase):
    def test_persistent_identity_and_private_secret(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            id1 = agent.installation_id(p / "installation-id")
            id2 = agent.installation_id(p / "installation-id")
            self.assertEqual(id1, id2)
            token = agent.control_secret(p / "control-token")
            self.assertEqual(len(token), 64)
            self.assertEqual(token, agent.control_secret(p / "control-token"))
            self.assertEqual((p / "control-token").stat().st_mode & 0o777, 0o600)
            self.assertNotEqual(id1, token)

    def test_rejects_world_readable_secret(self):
        with tempfile.TemporaryDirectory() as d:
            token = Path(d) / "control-token"
            token.write_text("a" * 64)
            token.chmod(0o644)
            with self.assertRaises(RuntimeError):
                agent.control_secret(token)

    def test_metrics_parsing(self):
        self.assertEqual(agent.parse_cpu_stat("cpu 10 1 2 20 3 0 0 0 0 0\n"), (36, 23))
        self.assertEqual(agent.memory_metrics("MemTotal: 1000 kB\nMemAvailable: 200 kB\n"), (1024000, 80.0))
        self.assertIsNone(agent.parse_cpu_stat("bad"))
        self.assertEqual(agent.network_details(None)["wol_mac"], None)
        sample = agent.MetricsSampler(None).sample()
        self.assertIn("load_1m", sample)
        self.assertIn("memory_usage_percent", sample)
        self.assertIn("uptime_seconds", sample)

    def test_route_can_appear_after_service_start(self):
        """Agent must not permanently cache a missing default route."""
        state = agent.AgentState("22222222-2222-4222-8222-222222222222",
                                 "01" * 32, False, "", None, None)
        good = {"wol_interface": "enp3s0", "wol_mac": "02:42:ac:11:00:05",
                "wol_broadcast": "192.168.50.255"}
        missing = {"wol_interface": None, "wol_mac": None, "wol_broadcast": None}
        with mock.patch.object(agent, "default_interface", side_effect=[None, "enp3s0"]), \
             mock.patch.object(agent, "network_details", side_effect=lambda iface: good if iface else missing):
            self.assertIsNone(state.info()["wol_mac"])
            recovered = state.info()
            self.assertEqual(recovered["wol_mac"], good["wol_mac"])
            self.assertEqual(recovered["wol_broadcast"], "192.168.50.255")

    def test_explicit_wol_interface_overrides_autodetection(self):
        state = agent.AgentState("22222222-2222-4222-8222-222222222222",
                                 "01" * 32, True, "", "enp3s0", None)
        with mock.patch.object(agent, "default_interface", side_effect=AssertionError("should not autodetect")), \
             mock.patch.object(agent, "network_details", return_value={
                 "wol_interface": "enp3s0", "wol_mac": "02:42:ac:11:00:05",
                 "wol_broadcast": "192.168.50.255"}) as details:
            self.assertEqual(state.info()["wol_interface"], "enp3s0")
            details.assert_called_once_with("enp3s0")

    def test_default_route_prefers_physical_interface_and_lowest_metric(self):
        routes = ("Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\n"
                  "tailscale0 00000000 00000000 0001 0 0 0 00000000 0 0 0\n"
                  "enp3s0 00000000 0132A8C0 0003 0 0 100 00000000 0 0 0\n")
        with mock.patch.object(agent, "read_first", return_value=routes), \
             mock.patch.object(Path, "exists", autospec=True,
                               side_effect=lambda p: str(p) == "/sys/class/net/enp3s0/device"), \
             mock.patch.object(agent, "network_details", return_value={
                 "wol_mac": "02:42:ac:11:00:05", "wol_broadcast": "192.168.50.255",
                 "wol_interface": "enp3s0"}):
            self.assertEqual(agent.default_interface(), "enp3s0")

    def test_isolated_physical_lan_fallback_without_default_route(self):
        with mock.patch.object(agent, "read_first", return_value="Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\n"), \
             mock.patch.object(Path, "iterdir", autospec=True, return_value=[Path("/sys/class/net/enp3s0")]), \
             mock.patch.object(Path, "exists", autospec=True, return_value=True), \
             mock.patch.object(agent, "network_details", return_value={
                 "wol_mac": "02:42:ac:11:00:05", "wol_broadcast": "192.168.50.255",
                 "wol_interface": "enp3s0"}):
            self.assertEqual(agent.default_interface(), "enp3s0")

    def test_hmac_vector(self):
        key = bytes.fromhex("01" * 32)
        message = b"POST\n/v2/power/reboot\n" + b"a" * 48 + b"\n"
        expected = hmac.new(key, message, hashlib.sha256).hexdigest()
        self.assertEqual(agent.signature(key.hex(), "/v2/power/reboot", "a" * 48), expected)

    def test_nonce_consumed_only_once(self):
        nonce = agent.Nonces()
        challenge = nonce.issue()
        self.assertTrue(nonce.consume(challenge))
        self.assertFalse(nonce.consume(challenge))

    def test_power_helper_actions(self):
        self.assertEqual(helper.authorize_and_parse(22, 22, b"suspend\n"), "suspend")
        self.assertIsNone(helper.authorize_and_parse(22, 22, b"/bin/sh\n"))
        self.assertIsNone(helper.authorize_and_parse(33, 22, b"reboot\n"))
        self.assertIsNone(helper.authorize_and_parse(22, 22, b"shutdown;rm -rf /\n"))


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.state = agent.AgentState("22222222-2222-4222-8222-222222222222", "01" * 32,
                                     True, "/nonexistent/helper.sock", None, None)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), agent.make_handler(cls.state))
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=3)

    def http(self, path, method="GET", headers=None):
        req = Request(self.url + path, headers=headers or {}, method=method)
        try:
            with urlopen(req, timeout=3) as response:
                return response.status, json.load(response)
        except HTTPError as err:
            return err.code, json.loads(err.read())

    def test_info_health_metrics(self):
        info_code, info = self.http("/v2/info")
        self.assertEqual(info_code, 200)
        self.assertIn("metrics", info["features"])
        self.assertEqual(info["protocol"], "computer-host-agent")
        for path in ("/v2/health", "/v2/metrics"):
            code, data = self.http(path)
            self.assertEqual(code, 200)
            self.assertEqual(data["id"], info["id"])

    def test_authenticated_post_and_replay_rejection(self):
        _, challenge = self.http("/v2/challenge")
        nonce = challenge["nonce"]
        signature = agent.signature(self.state.secret, "/v2/power/reboot", nonce)
        headers = {"X-ComputerHost-Nonce": nonce, "X-ComputerHost-Signature": signature}
        with mock.patch.object(agent, "request_power") as rp:
            status, body = self.http("/v2/power/reboot", "POST", headers)
            self.assertEqual(status, 202)
            self.assertEqual(body["action"], "reboot")
            rp.assert_called_once_with(self.state.helper_socket, "reboot")
        status, body = self.http("/v2/power/reboot", "POST", headers)
        self.assertEqual(status, 401)

    def test_wrong_signature_rejected(self):
        _, challenge = self.http("/v2/challenge")
        headers = {"X-ComputerHost-Nonce": challenge["nonce"], "X-ComputerHost-Signature": "0" * 64}
        self.assertEqual(self.http("/v2/power/shutdown", "POST", headers)[0], 401)

    def test_wrong_action_rejected(self):
        self.assertEqual(self.http("/v2/power/run", "POST")[0], 404)

    def test_missing_helper_refused(self):
        _, challenge = self.http("/v2/challenge")
        nonce = challenge["nonce"]
        headers = {"X-ComputerHost-Nonce": nonce,
                   "X-ComputerHost-Signature": agent.signature(self.state.secret, "/v2/power/suspend", nonce)}
        self.assertEqual(self.http("/v2/power/suspend", "POST", headers)[0], 503)

    def test_disabled_control(self):
        disabled = agent.AgentState(self.state.identifier, self.state.secret, False, "", None, None)
        with ThreadingHTTPServer(("127.0.0.1", 0), agent.make_handler(disabled)) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                with self.assertRaises(HTTPError) as ctx:
                    urlopen(f"http://127.0.0.1:{server.server_port}/v2/challenge", timeout=3)
                self.assertEqual(ctx.exception.code, 403)
            finally:
                server.shutdown()
                worker.join(timeout=3)


if __name__ == "__main__":
    unittest.main()

class HelperSocketTests(unittest.TestCase):
    def test_agent_to_socket_action(self):
        import socket
        import threading
        with tempfile.TemporaryDirectory() as d:
            path=str(Path(d)/'power.sock')
            listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
            listener.bind(path)
            listener.listen(1)
            collected=[]
            def responder():
                conn,_=listener.accept()
                with conn:
                    collected.append(conn.recv(64))
                    conn.sendall(b'OK\n')
            task=threading.Thread(target=responder)
            task.start()
            try:
                agent.request_power(path,'suspend')
                task.join(timeout=2)
                self.assertEqual(collected,[b'suspend\n'])
            finally:
                listener.close()
