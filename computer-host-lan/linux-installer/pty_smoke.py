#!/usr/bin/env python3
"""Real pseudo-terminal smoke for the *inert* Linux installer UX experiment.

Uses only Python stdlib, no root and no real device/network access. Checks
that the full-screen Bubble Tea form starts in a tty and Ctrl+C exits cleanly.
This does NOT replace manual terminal/screen-reader acceptance.
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


def smoke(binary: str, width: int, height: int) -> None:
    pid, master = pty.fork()
    if pid == 0:
        try:
            env = os.environ.copy()
            env.update(TERM='xterm-256color', NO_COLOR='1')
            os.execve(binary, [binary], env)
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
        if not pump_until(b'1. Welcome', 15):
            raise AssertionError('full-screen Welcome page never rendered')
        # This is an inert demo. Cancel should not print an error or run work.
        os.write(master, b'\x03')
        if not pump_until(b'Cancelled; no changes made.', 10):
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
        print(f'PASS inert TUI PTY startup/cancel at {width}x{height}')
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
    if len(sys.argv) != 2 or not os.path.isabs(sys.argv[1]):
        print('Usage: python3 pty_smoke.py /absolute/path/to/demo-binary', file=sys.stderr)
        return 2
    for width, height in ((80, 24), (60, 20)):
        smoke(sys.argv[1], width, height)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
