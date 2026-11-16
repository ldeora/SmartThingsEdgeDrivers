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

ALLOWED = {"shutdown": "poweroff", "reboot": "reboot", "suspend": "suspend"}


def authorize_and_parse(peer_uid: int, allowed_uid: int, data: bytes) -> str | None:
    if peer_uid != allowed_uid or len(data) > 32 or not data.endswith(b"\n"):
        return None
    try:
        action = data.decode("ascii").rstrip("\n")
    except UnicodeDecodeError:
        return None
    return action if action in ALLOWED else None


def handle_connection(conn, allowed_uid, executor=None):
    if executor is None:
        executor = lambda command: subprocess.Popen(command, close_fds=True,
                                                     start_new_session=True)
    try:
        conn.settimeout(3.0)  # unprivileged peer must not stall this root helper
        peer = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _, uid, _ = struct.unpack("3i", peer)
        data = conn.recv(33)
        action = authorize_and_parse(uid, allowed_uid, data)
        if not action:
            conn.sendall(b"DENIED\n")
            return False
        # Report acceptance before the machine begins to shut down.
        conn.sendall(b"OK\n")
        executor(["/usr/bin/systemctl", ALLOWED[action]])
        return True
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        # No secrets, full requests, or client-controlled bytes in journal logs.
        print(f"Linux Host power helper operation failed: {type(exc).__name__}", file=sys.stderr, flush=True)
        return False


def main():
    if os.geteuid() != 0:
        raise RuntimeError("power helper must run as root")
    permitted_uid = pwd.getpwnam("linuxhost").pw_uid
    # systemd passes the listening socket through fd 3 (Accept=no).
    listener = socket.socket(fileno=3)
    while True:
        conn, _ = listener.accept()
        with conn:
            handle_connection(conn, permitted_uid)


if __name__ == "__main__":
    sys.exit(main())
