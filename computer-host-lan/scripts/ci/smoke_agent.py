#!/usr/bin/env python3
"""Disposable loopback smoke test for the Linux Host Agent, no root/systemd.

Confirms the shipped source works with the current distribution's Python and
procfs. Neither the persistent state nor the local system's services are used.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "agent" / "linux_host_agent.py"


def request_json(base: str, endpoint: str):
    with urlopen(base + endpoint, timeout=3) as result:
        return result.status, json.loads(result.read().decode("utf-8"))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="linux-host-smoke-") as state:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        args = [sys.executable, str(AGENT), "--bind", "127.0.0.1",
                "--port", str(port), "--state-dir", state]
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True)
        base = f"http://127.0.0.1:{port}"
        try:
            for attempt in range(40):
                if process.poll() is not None:
                    err = process.stderr.read()
                    raise AssertionError(f"Agent exited ({process.returncode}): {err[:500]}")
                try:
                    _, info = request_json(base, "/v2/info")
                    break
                except (OSError, URLError):
                    time.sleep(0.1)
            else:
                raise AssertionError("Agent did not listen within 4 seconds")
            _, health = request_json(base, "/v2/health")
            _, metrics = request_json(base, "/v2/metrics")
            assert info["protocol"] == "computer-host-agent"
            assert info["api_version"] == 2
            assert info["agent_version"] == "0.4.0-dev.1"
            assert info["platform"] == "linux"
            assert health["platform"] == "linux" and metrics["platform"] == "linux"
            assert info["power_actions"] == []
            assert "power-control" not in info["features"]
            assert health["id"] == info["id"]
            assert health["status"] == "running"
            assert metrics["id"] == info["id"]
            try:
                request_json(base, "/v2/challenge")
            except HTTPError as err:
                assert err.code == 403, f"Expected 403 when power disabled; got {err.code}"
            else:
                raise AssertionError("Power-control challenge unexpectedly enabled")
            print(f"PASS: agent loopback, health, metrics, power-disabled default (Python {sys.version_info.major}.{sys.version_info.minor}, uid {os.getuid()})")
        finally:
            process.terminate()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=5)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (AssertionError, OSError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
