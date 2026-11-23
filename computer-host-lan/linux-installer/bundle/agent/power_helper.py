#!/usr/bin/env python3
"""Restricted root-side power helper, socket-activated via systemd.

Accepts only three hard-coded Linux power actions over a local Unix socket.
Caller must be the configured Linux user (checked with SO_PEERCRED). No shell.
"""
import os
import pwd
import socket
import struct
import subprocess
import sys
import shutil
import time
from pathlib import Path

ALLOWED = {"shutdown": "poweroff", "reboot": "reboot", "suspend": "suspend"}
SYSTEMCTL_SEARCH_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
SYSTEMCTL_TIMEOUT_SECONDS = 2.5
SHUTDOWN_ACK_GRACE_SECONDS = 1.0


def resolve_systemctl() -> str:
    """Resolve the trusted systemctl executable once, before accepting requests."""
    candidate = shutil.which("systemctl", path=SYSTEMCTL_SEARCH_PATH)
    if not candidate:
        raise RuntimeError("systemctl executable not found in standard system paths")
    try:
        resolved = Path(candidate).resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("systemctl executable cannot be resolved") from exc
    if not resolved.is_absolute() or not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise RuntimeError("resolved systemctl path is not an executable file")
    return str(resolved)


def run_systemctl(command):
    """Wait until systemd confirms the non-blocking power job was queued."""
    return subprocess.run(
        command, check=True, timeout=SYSTEMCTL_TIMEOUT_SECONDS,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
    )


def authorize_and_parse(peer_uid: int, allowed_uid: int, data: bytes) -> str | None:
    if peer_uid != allowed_uid or len(data) > 32 or not data.endswith(b"\n"):
        return None
    try:
        action = data.decode("ascii").rstrip("\n")
    except UnicodeDecodeError:
        return None
    return action if action in ALLOWED else None


def handle_connection(conn, allowed_uid, systemctl_path, executor=None, sleeper=None):
    if executor is None:
        executor = run_systemctl
    if sleeper is None:
        sleeper = time.sleep
    try:
        conn.settimeout(3.0)  # unprivileged peer must not stall this root helper
        peer = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _, uid, _ = struct.unpack("3i", peer)
        data = conn.recv(33)
        action = authorize_and_parse(uid, allowed_uid, data)
        if not action:
            conn.sendall(b"DENIED\n")
            return False
        # The executable was resolved at startup, but check for a removed or
        # inaccessible path before acknowledging an irreversible operation.
        if not Path(systemctl_path).is_file() or not os.access(systemctl_path, os.X_OK):
            conn.sendall(b"ERROR\n")
            return False

        command = [systemctl_path, "--no-block", ALLOWED[action]]
        if action in ("shutdown", "reboot"):
            # Starting the shutdown job can immediately SIGTERM this helper
            # AND the unprivileged HTTP agent (both systemd services have
            # default shutdown dependencies). Acknowledge first and leave
            # enough time for the agent's HTTP 202 to reach SmartThings.
            # This is acceptance for a delayed attempt, NOT confirmation that
            # systemd has accepted or completed the power operation.
            conn.sendall(b"OK\n")
            sleeper(SHUTDOWN_ACK_GRACE_SECONDS)
            try:
                executor(command)
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                # Execution failures after OK cannot be reported over this
                # socket. Log locally; never send a misleading second reply.
                print(f"Linux Host delayed power request failed: {type(exc).__name__}",
                      file=sys.stderr, flush=True)
                return False
            return True

        # Suspend normally does not stop the agent/helper services. Preserve
        # immediate error reporting for a rejected or unsupported suspend.
        try:
            executor(command)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            print(f"Linux Host suspend request failed: {type(exc).__name__}", file=sys.stderr, flush=True)
            try:
                conn.sendall(b"ERROR\n")
            except OSError:
                pass
            return False
        conn.sendall(b"OK\n")
        return True
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        # No secrets, full requests, or client-controlled bytes in journal logs.
        print(f"Linux Host power helper connection failed: {type(exc).__name__}", file=sys.stderr, flush=True)
        return False


def main():
    if os.geteuid() != 0:
        raise RuntimeError("power helper must run as root")
    try:
        systemctl_path = resolve_systemctl()
    except RuntimeError as exc:
        print(f"Linux Host power helper unavailable: {exc}", file=sys.stderr, flush=True)
        return 1
    permitted_uid = pwd.getpwnam("linuxhost").pw_uid
    # systemd passes the listening socket through fd 3 (Accept=no).
    listener = socket.socket(fileno=3)
    while True:
        conn, _ = listener.accept()
        with conn:
            handle_connection(conn, permitted_uid, systemctl_path)


if __name__ == "__main__":
    sys.exit(main())
