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

    def test_atomic_state_creation_and_corrupt_identity(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "installation-id"
            # A simulated interruption before atomic publish cannot leave
            # an empty final identity file or rotate an existing identity.
            with mock.patch.object(agent.os, "link", side_effect=OSError("simulated power loss")):
                with self.assertRaises(OSError):
                    agent.installation_id(p)
            self.assertFalse(p.exists())
            self.assertFalse(list(Path(d).glob(".installation-id.*.tmp")))
            original = agent.installation_id(p)
            self.assertEqual(original, agent.installation_id(p))
            p.write_text("")
            p.chmod(0o600)
            with self.assertRaises(RuntimeError):
                agent.installation_id(p)
            self.assertEqual(p.read_text(), "")

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
        self.assertEqual(agent.memory_details("MemTotal: 1000 kB\nMemAvailable: 200 kB\n"),
                         (1024000, 80.0, 819200, 204800))
        self.assertEqual(agent.memory_details("MemTotal: 1000 kB\nMemFree: 10 kB\nMemAvailable: 800 kB\n"),
                         (1024000, 20.0, 204800, 819200))
        self.assertEqual(agent.memory_details("MemTotal: 1000 kB\nMemAvailable: 1100 kB\n"),
                         (None, None, None, None))
        self.assertEqual(agent.memory_details("MemTotal: 1000 kB\n"), (None, None, None, None))
        self.assertIsNone(agent.parse_cpu_stat("bad"))
        self.assertEqual(agent.network_details(None)["wol_mac"], None)
        sample = agent.MetricsSampler(None).sample()
        self.assertIn("load_1m", sample)
        self.assertIn("memory_usage_percent", sample)
        self.assertIn("uptime_seconds", sample)

    def test_root_filesystem_capacity_and_missing_volume(self):
        fake = mock.Mock(f_blocks=1024, f_frsize=4096, f_bavail=256)
        with mock.patch.object(agent.os, "statvfs", return_value=fake):
            self.assertEqual(agent.disk_metrics("/"), (75.0, 4194304))
            self.assertEqual(agent.disk_used_percent("/"), 75.0)
            sample = agent.MetricsSampler(None).sample()
            self.assertEqual(sample["disk_root_usage_percent"], 75.0)
            self.assertEqual(sample["disk_root_total_bytes"], 4194304)
        with mock.patch.object(agent.os, "statvfs", side_effect=OSError):
            self.assertEqual(agent.disk_metrics("/"), (None, None))
        with mock.patch.object(agent.os, "statvfs", return_value=mock.Mock(f_blocks=0, f_frsize=4096, f_bavail=0)):
            self.assertEqual(agent.disk_metrics("/"), (None, None))

    def test_exact_filesystem_used_available_and_reserved_blocks(self):
        # Existing 50% is total minus available; used blocks are only 40%.
        fake = mock.Mock(f_blocks=1000, f_bfree=600, f_bavail=500, f_frsize=1024)
        with mock.patch.object(agent.os, "statvfs", return_value=fake):
            self.assertEqual(agent.disk_details("/"), (50.0, 1024000, 409600, 512000))
            self.assertEqual(agent.disk_metrics("/"), (50.0, 1024000))
            sample = agent.MetricsSampler(None).sample()
            self.assertEqual(sample["disk_root_used_bytes"], 409600)
            self.assertEqual(sample["disk_root_available_bytes"], 512000)
            self.assertEqual(sample["disk_root_usage_percent"], 50.0)
        with mock.patch.object(agent.os, "statvfs", return_value=mock.Mock(
                f_blocks=1000, f_bfree=0, f_bavail=0, f_frsize=1024)):
            self.assertEqual(agent.disk_details("/"), (100.0, 1024000, 1024000, 0))
        with mock.patch.object(agent.os, "statvfs", return_value=mock.Mock(
                f_blocks=1000, f_bfree=1100, f_bavail=500, f_frsize=1024)):
            self.assertEqual(agent.disk_details("/"), (50.0, 1024000, None, 512000))
        with mock.patch.object(agent.os, "statvfs", side_effect=OSError):
            self.assertEqual(agent.disk_details("/"), (None, None, None, None))

    def test_memory_sample_has_real_used_and_available_bytes(self):
        original = agent.read_first
        def sample_meminfo(path):
            if path == "/proc/meminfo":
                return "MemTotal: 1024 kB\nMemFree: 12 kB\nMemAvailable: 768 kB\n"
            return original(path)
        with mock.patch.object(agent, "read_first", side_effect=sample_meminfo):
            metrics = agent.MetricsSampler(None).sample()
            self.assertEqual(metrics["memory_total_bytes"], 1048576)
            self.assertEqual(metrics["memory_used_bytes"], 262144)
            self.assertEqual(metrics["memory_available_bytes"], 786432)
            self.assertEqual(metrics["memory_usage_percent"], 25.0)

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

    def test_helper_execution_error_returns_service_unavailable(self):
        _, challenge = self.http("/v2/challenge")
        nonce = challenge["nonce"]
        headers = {"X-ComputerHost-Nonce": nonce,
                   "X-ComputerHost-Signature": agent.signature(
                       self.state.secret, "/v2/power/shutdown", nonce)}
        with mock.patch.object(agent, "request_power", side_effect=RuntimeError("helper rejected")):
            status, body = self.http("/v2/power/shutdown", "POST", headers)
        self.assertEqual(status, 503)
        self.assertEqual(body["error"], "power helper unavailable")

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

    def test_agent_reads_fragmented_ok_reply(self):
        import socket
        import threading
        import time
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "power.sock")
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(path)
            listener.listen(1)
            received = []
            def responder():
                conn, _ = listener.accept()
                with conn:
                    received.append(conn.recv(64))
                    conn.sendall(b"O")
                    time.sleep(0.02)
                    conn.sendall(b"K\n")
            task = threading.Thread(target=responder)
            task.start()
            try:
                agent.request_power(path, "shutdown")
                task.join(timeout=2)
                self.assertEqual(received, [b"shutdown\n"])
            finally:
                listener.close()

    def test_agent_rejects_helper_error_acknowledgement(self):
        import socket
        import threading
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "power.sock")
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(path)
            listener.listen(1)
            def responder():
                conn, _ = listener.accept()
                with conn:
                    conn.recv(64)
                    conn.sendall(b"ERROR\n")
            task = threading.Thread(target=responder)
            task.start()
            try:
                with self.assertRaises(RuntimeError):
                    agent.request_power(path, "reboot")
                task.join(timeout=2)
            finally:
                listener.close()


if __name__ == "__main__":
    unittest.main()
