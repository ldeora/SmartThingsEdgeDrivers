#!/usr/bin/env python3
"""Unprivileged PTY startup/cancellation smoke for Linux wizard modes.

Uses only Python stdlib. The default installation wizard is cancelled at
its welcome page, before review or literal INSTALL consent. No elevation
or managed mutation is attempted. Does not replace manual acceptance.
"""
from __future__ import annotations

import fcntl
import os
import pty
import select
import signal
import struct
import sys
import termios
import time


def smoke(binary: str, width: int, height: int, *, mode: str) -> None:
    pid, master = pty.fork()
    if pid == 0:
        try:
            env = os.environ.copy()
            env.update(TERM='xterm-256color', NO_COLOR='1')
            args = {'demo': ['-demo'], 'live': ['-live'], 'install': []}[mode]
            os.execve(binary, [binary, *args], env)
        except Exception as exc:
            print(f'PTY exec failed: {exc}', file=sys.stderr)
            os._exit(127)

    os.set_blocking(master, False)
    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack('HHHH', height, width, 0, 0))
    collected = bytearray()
    child_status = None

    def pump_until(needle: bytes, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            readable, _, _ = select.select([master], [], [], 0.1)
            if readable:
                try:
                    chunk = os.read(master, 65536)
                    if chunk:
                        collected.extend(chunk)
                    elif needle in collected:
                        return True
                except BlockingIOError:
                    pass
                except OSError:
                    break
            if needle in collected:
                return True
        return needle in collected

    try:
        expected_page = b'1. Welcome'
        if not pump_until(expected_page, 15 if mode == 'demo' else 60):
            raise AssertionError(f'full-screen {expected_page!r} page never rendered')
        # Cancel before the installation review or authorization prompt.
        os.write(master, b'\x03')
        cancelled = {
            'demo': b'Cancelled; no changes made.',
            'live': b'Setup preview cancelled. No changes made.',
            'install': b'Cancelled. No changes made.',
        }[mode]
        if not pump_until(cancelled, 10):
            raise AssertionError('Ctrl+C did not produce a clean cancellation')
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            done, status = os.waitpid(pid, os.WNOHANG)
            if done == pid:
                child_status = status
                break
            time.sleep(0.05)
        if child_status is None or not os.WIFEXITED(child_status) or os.WEXITSTATUS(child_status) != 0:
            raise AssertionError(f'TUI did not exit with code 0: status={child_status}')
        if mode == 'install' and b'COMPUTER HOST LAN / LINUX INSTALLATION' not in collected:
            raise AssertionError('installation welcome heading missing')
        print(f'PASS {mode} TUI PTY startup/cancel at {width}x{height}')
    except Exception:
        print('Captured terminal tail:', bytes(collected[-6000:]).decode('utf-8', errors='replace'), file=sys.stderr)
        raise
    finally:
        if child_status is None:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
        os.close(master)


def main() -> int:
    if len(sys.argv) not in (2, 3) or not os.path.isabs(sys.argv[1]) or \
            (len(sys.argv) == 3 and sys.argv[2] not in ('--live', '--install')):
        print('Usage: python3 pty_smoke.py /absolute/path/to/binary [--live|--install]', file=sys.stderr)
        return 2
    mode = sys.argv[2][2:] if len(sys.argv) == 3 else 'demo'
    sizes = ((80, 24), (60, 20)) if mode == 'demo' else ((80, 24),)
    for width, height in sizes:
        smoke(sys.argv[1], width, height, mode=mode)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
