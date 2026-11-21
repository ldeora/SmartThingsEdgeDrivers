"""Power-helper acknowledgement and systemctl resolution tests."""
from pathlib import Path
import os
import socket
import threading
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))
import power_helper


class FakeConnection:
    def __init__(self, uid, payload, events):
        self.uid = uid
        self.payload = payload
        self.events = events

    def settimeout(self, seconds):
        self.events.append(("timeout", seconds))

    def getsockopt(self, level, option, length):
        assert level == socket.SOL_SOCKET
        assert option == socket.SO_PEERCRED
        assert length == struct.calcsize("3i")
        return struct.pack("3i", 1234, self.uid, self.uid)

    def recv(self, size):
        assert size == 33
        return self.payload

    def sendall(self, payload):
        self.events.append(("send", payload))


class SystemctlResolutionTests(unittest.TestCase):
    def test_resolves_absolute_executable_from_trusted_search_path(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "systemctl"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="ascii")
            executable.chmod(0o755)
            with mock.patch.object(power_helper.shutil, "which", return_value=str(executable)) as which:
                self.assertEqual(power_helper.resolve_systemctl(), str(executable.resolve()))
            which.assert_called_once_with(
                "systemctl", path=power_helper.SYSTEMCTL_SEARCH_PATH
            )

    def test_missing_systemctl_fails_closed(self):
        with mock.patch.object(power_helper.shutil, "which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "not found"):
                power_helper.resolve_systemctl()

    def test_non_executable_resolution_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "systemctl"
            candidate.write_text("not executable", encoding="ascii")
            candidate.chmod(0o600)
            with mock.patch.object(power_helper.shutil, "which", return_value=str(candidate)):
                with self.assertRaisesRegex(RuntimeError, "not an executable"):
                    power_helper.resolve_systemctl()


class HelperAcknowledgementTests(unittest.TestCase):
    @staticmethod
    def invoke(conn, executor, events, sleeper=None):
        # Tests must never execute a real power operation, or depend on the
        # test runner having systemctl installed at a specific path.
        with mock.patch.object(power_helper.Path, "is_file", return_value=True), \
             mock.patch.object(power_helper.os, "access", return_value=True):
            return power_helper.handle_connection(
                conn, 1001, "/usr/bin/systemctl", executor,
                sleeper or (lambda seconds: events.append(("sleep", seconds))),
            )

    def test_shutdown_acknowledged_before_delay_and_execution(self):
        events = []
        conn = FakeConnection(1001, b"shutdown\n", events)

        def executor(command):
            events.append(("execute", command))

        self.assertTrue(self.invoke(conn, executor, events))
        self.assertEqual(events[-3:], [
            ("send", b"OK\n"),
            ("sleep", power_helper.SHUTDOWN_ACK_GRACE_SECONDS),
            ("execute", ["/usr/bin/systemctl", "--no-block", "poweroff"]),
        ])
        self.assertGreaterEqual(power_helper.SHUTDOWN_ACK_GRACE_SECONDS, 0.5)

    def test_reboot_uses_the_same_acknowledgement_grace(self):
        events = []
        conn = FakeConnection(1001, b"reboot\n", events)

        def executor(command):
            events.append(("execute", command))

        self.assertTrue(self.invoke(conn, executor, events))
        self.assertEqual(events[-3:], [
            ("send", b"OK\n"),
            ("sleep", power_helper.SHUTDOWN_ACK_GRACE_SECONDS),
            ("execute", ["/usr/bin/systemctl", "--no-block", "reboot"]),
        ])

    def test_delayed_failure_cannot_be_turned_into_a_false_second_reply(self):
        events = []
        conn = FakeConnection(1001, b"reboot\n", events)

        def executor(command):
            events.append(("execute", command))
            raise FileNotFoundError("systemctl disappeared")

        self.assertFalse(self.invoke(conn, executor, events))
        self.assertEqual([item[1] for item in events if item[0] == "send"], [b"OK\n"])
        self.assertEqual(events[-2][0], "sleep")

    def test_suspend_is_confirmed_before_acknowledgement(self):
        events = []
        conn = FakeConnection(1001, b"suspend\n", events)

        def executor(command):
            events.append(("execute", command))

        self.assertTrue(self.invoke(conn, executor, events))
        self.assertEqual(events[-2:], [
            ("execute", ["/usr/bin/systemctl", "--no-block", "suspend"]),
            ("send", b"OK\n"),
        ])

    def test_suspend_nonzero_exit_returns_error_without_ok(self):
        events = []
        conn = FakeConnection(1001, b"suspend\n", events)

        def executor(command):
            raise subprocess.CalledProcessError(1, command)

        self.assertFalse(self.invoke(conn, executor, events))
        self.assertEqual([item[1] for item in events if item[0] == "send"], [b"ERROR\n"])

    def test_missing_systemctl_before_shutdown_is_rejected(self):
        events = []
        conn = FakeConnection(1001, b"shutdown\n", events)
        executor = mock.Mock()
        with mock.patch.object(power_helper.Path, "is_file", return_value=False):
            self.assertFalse(power_helper.handle_connection(
                conn, 1001, "/missing/systemctl", executor,
                sleeper=lambda seconds: events.append(("sleep", seconds)),
            ))
        self.assertIn(("send", b"ERROR\n"), events)
        executor.assert_not_called()
        self.assertFalse(any(item[0] == "sleep" for item in events))

    def test_unauthorized_peer_is_denied_without_running_systemctl(self):
        events = []
        conn = FakeConnection(2002, b"shutdown\n", events)
        executor = mock.Mock()
        self.assertFalse(self.invoke(conn, executor, events))
        self.assertIn(("send", b"DENIED\n"), events)
        executor.assert_not_called()

    def test_systemctl_runner_waits_for_job_acceptance_without_blocking_poweroff(self):
        with mock.patch.object(power_helper.subprocess, "run") as run:
            power_helper.run_systemctl([
                "/usr/bin/systemctl", "--no-block", "poweroff"
            ])
        self.assertEqual(power_helper.SYSTEMCTL_TIMEOUT_SECONDS, 2.5)
        run.assert_called_once_with(
            ["/usr/bin/systemctl", "--no-block", "poweroff"],
            check=True,
            timeout=power_helper.SYSTEMCTL_TIMEOUT_SECONDS,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )

class SocketAcknowledgementTests(unittest.TestCase):
    def test_agent_receives_shutdown_ok_before_systemctl_is_invoked(self):
        """Exercise the actual Unix socket handshake without powering off."""
        import linux_host_agent as agent

        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "power.sock")
            executable = Path(directory) / "systemctl"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="ascii")
            executable.chmod(0o755)

            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(path)
            listener.listen(1)
            sleeping = threading.Event()
            release = threading.Event()
            executed = []
            results = []

            def grace_period(seconds):
                self.assertEqual(seconds, power_helper.SHUTDOWN_ACK_GRACE_SECONDS)
                sleeping.set()
                if not release.wait(timeout=3):
                    raise AssertionError("test did not release the grace period")

            def run_helper():
                conn, _ = listener.accept()
                with conn:
                    results.append(power_helper.handle_connection(
                        conn, os.getuid(), str(executable),
                        executor=lambda command: executed.append(command),
                        sleeper=grace_period,
                    ))

            worker = threading.Thread(target=run_helper)
            worker.start()
            try:
                # The agent must complete the full OK handshake while the
                # helper's grace period still prevents systemctl invocation.
                agent.request_power(path, "shutdown", timeout=2)
                self.assertTrue(sleeping.wait(timeout=2))
                self.assertEqual(executed, [])
            finally:
                release.set()
                worker.join(timeout=3)
                listener.close()
            self.assertFalse(worker.is_alive())
            self.assertEqual(results, [True])
            self.assertEqual(executed, [[
                str(executable), "--no-block", "poweroff"
            ]])


if __name__ == "__main__":
    unittest.main()
