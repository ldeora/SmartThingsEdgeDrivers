"""Power-helper acknowledgement and systemctl resolution tests."""
from pathlib import Path
import socket
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
    def test_systemd_job_is_started_before_ok_acknowledgement(self):
        events = []
        connection = FakeConnection(1001, b"shutdown\n", events)

        def executor(command):
            events.append(("execute", command))

        self.assertTrue(power_helper.handle_connection(
            connection, 1001, "/usr/bin/systemctl", executor
        ))
        execute_index = next(i for i, item in enumerate(events) if item[0] == "execute")
        ack_index = events.index(("send", b"OK\n"))
        self.assertLess(execute_index, ack_index)
        self.assertEqual(events[execute_index][1], [
            "/usr/bin/systemctl", "--no-block", "poweroff"
        ])

    def test_executor_failure_returns_error_without_ok(self):
        events = []
        connection = FakeConnection(1001, b"reboot\n", events)

        def executor(command):
            events.append(("execute", command))
            raise FileNotFoundError("systemctl disappeared")

        self.assertFalse(power_helper.handle_connection(
            connection, 1001, "/usr/bin/systemctl", executor
        ))
        responses = [item[1] for item in events if item[0] == "send"]
        self.assertEqual(responses, [b"ERROR\n"])
        self.assertNotIn(b"OK\n", responses)

    def test_systemctl_nonzero_exit_is_an_operation_failure(self):
        events = []
        connection = FakeConnection(1001, b"suspend\n", events)

        def executor(command):
            raise subprocess.CalledProcessError(1, command)

        self.assertFalse(power_helper.handle_connection(
            connection, 1001, "/usr/bin/systemctl", executor
        ))
        self.assertIn(("send", b"ERROR\n"), events)

    def test_unauthorized_peer_is_denied_without_running_systemctl(self):
        events = []
        connection = FakeConnection(2002, b"poweroff\n", events)
        executor = mock.Mock()

        self.assertFalse(power_helper.handle_connection(
            connection, 1001, "/usr/bin/systemctl", executor
        ))
        self.assertIn(("send", b"DENIED\n"), events)
        executor.assert_not_called()

    def test_systemctl_runner_waits_for_job_acceptance_without_blocking_poweroff(self):
        with mock.patch.object(power_helper.subprocess, "run") as run:
            power_helper.run_systemctl([
                "/usr/bin/systemctl", "--no-block", "poweroff"
            ])
        run.assert_called_once_with(
            ["/usr/bin/systemctl", "--no-block", "poweroff"],
            check=True,
            timeout=2.5,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )


if __name__ == "__main__":
    unittest.main()
