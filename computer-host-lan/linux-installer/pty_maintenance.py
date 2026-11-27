#!/usr/bin/env python3
"""Exercise the actual maintenance chooser and its terminal handoff.

The Go test harness has a fake dispatcher. It never uses the live installer,
requests elevation, or reads or changes managed installation state.
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


def resize(fd: int, width: int, height: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', height, width, 0, 0))


def smoke(binary: str, mode: str) -> None:
    detail = mode in ('inspect', 'backup-cancel', 'backup-review')
    width, height = (60, 20) if mode == 'resize' else ((64, 22) if detail else (100, 28))
    pid, master = pty.fork()
    if pid == 0:
        try:
            resize(0, width, height)
            env = os.environ.copy()
            env.update(TERM='xterm-256color', NO_COLOR='1',
                       COMPUTER_HOST_TEST_MAINTENANCE_PTY='1')
            harness = 'TestMaintenanceScreenPTYHarness'
            if detail:
                env['COMPUTER_HOST_TEST_DETAIL_PTY'] = mode
                harness = 'TestDetailScreenPTYHarness'
            os.execve(binary, [binary, f'-test.run=^{harness}
        except Exception as exc:
            print(f'PTY exec failed: {exc}', file=sys.stderr)
            os._exit(127)

    collected = bytearray()
    child_status = None
    os.set_blocking(master, False)

    def pump_until(needle: bytes, timeout: float = 10) -> None:
        deadline = time.monotonic() + timeout
        while needle not in collected and time.monotonic() < deadline:
            readable, _, _ = select.select([master], [], [], 0.1)
            if readable:
                try:
                    chunk = os.read(master, 65536)
                except BlockingIOError:
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                collected.extend(chunk)
        if needle not in collected:
            raise AssertionError(f'missing terminal output: {needle!r}')

    try:
        if mode == 'resize':
            pump_until(b'Enlarge terminal to 64x22 (now 60x20). Q quits.')
            # The model tests cover selection while too small. Here we
            # exercise the actual SIGWINCH/render path without an input race.
            resize(master, 100, 28)

        if mode == 'inspect':
            pump_until(b'Read-only snapshot')
            os.write(master, b'\x1b[F')  # End
            pump_until(b'Credentials and identity: Not accessed or verified')
            os.write(master, b'q')
            pump_until(b'PTY INSPECTION CLOSED')
        elif mode.startswith('backup-'):
            pump_until(b'Backup 1 of 32')
            os.write(master, b'\x1b[F')  # End selects the oldest fixture
            pump_until(b'Backup 32 of 32')
            if mode == 'backup-cancel':
                os.write(master, b'q')
            else:
                os.write(master, b'\r')
                pump_until(b'Type RESTORE to authorize this backup')
                if b'Restore agent 0.4.6-rc.2 from snapshot-test32' not in collected:
                    raise AssertionError('selected backup changed at terminal handoff')
                attrs = termios.tcgetattr(master)
                if not attrs[3] & termios.ICANON or not attrs[3] & termios.ECHO:
                    raise AssertionError('restore review still in raw/no-echo mode')
                os.write(master, b'NO\n')
                pump_until(b'No agent changes made.')
            pump_until(b'PTY RESTORE CLOSED')
        elif mode == 'cancel':
            pump_until(b'(recommended)')
            os.write(master, b'q')
            pump_until(b'Exited without changes.')
            if b'PTY HANDOFF' in collected:
                raise AssertionError('cancel dispatched a task')
        else:
            pump_until(b'(recommended)')
            # Numeric shortcut then explicit selection; the fake dispatch
            # receives a normal line prompt after Bubble Tea exits.
            os.write(master, b'6\r')
            pump_until(b'PTY HANDOFF inspect')
            attrs = termios.tcgetattr(master)
            if not attrs[3] & termios.ICANON or not attrs[3] & termios.ECHO:
                raise AssertionError('terminal still in raw/no-echo mode at handoff')
            os.write(master, b'Q typed into ordinary prompt\n')
            pump_until(b'PTY INPUT PRESERVED')

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            done, status = os.waitpid(pid, os.WNOHANG)
            if done == pid:
                child_status = status
                break
            time.sleep(0.05)
        if child_status is None or not os.WIFEXITED(child_status) or os.WEXITSTATUS(child_status) != 0:
            raise AssertionError(f'unexpected exit status: {child_status}')
        print(f'PASS maintenance PTY: {mode}')
    except Exception:
        print(bytes(collected[-6000:]).decode('utf-8', errors='replace'), file=sys.stderr)
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
        print('Usage: python3 pty_maintenance.py /absolute/path/to/Go-test-binary', file=sys.stderr)
        return 2
    for mode in ('route', 'cancel', 'resize', 'inspect', 'backup-cancel', 'backup-review'):
        smoke(sys.argv[1], mode)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
, '-test.v'], env)
        except Exception as exc:
            print(f'PTY exec failed: {exc}', file=sys.stderr)
            os._exit(127)

    collected = bytearray()
    child_status = None
    os.set_blocking(master, False)

    def pump_until(needle: bytes, timeout: float = 10) -> None:
        deadline = time.monotonic() + timeout
        while needle not in collected and time.monotonic() < deadline:
            readable, _, _ = select.select([master], [], [], 0.1)
            if readable:
                try:
                    chunk = os.read(master, 65536)
                except BlockingIOError:
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                collected.extend(chunk)
        if needle not in collected:
            raise AssertionError(f'missing terminal output: {needle!r}')

    try:
        if mode == 'resize':
            pump_until(b'Enlarge terminal to 64x22 (now 60x20). Q quits.')
            # The model tests cover selection while too small. Here we
            # exercise the actual SIGWINCH/render path without an input race.
            resize(master, 100, 28)

        pump_until(b'(recommended)')
        if mode == 'cancel':
            os.write(master, b'q')
            pump_until(b'Exited without changes.')
            if b'PTY HANDOFF' in collected:
                raise AssertionError('cancel dispatched a task')
        else:
            # Numeric shortcut then explicit selection; the fake dispatch
            # receives a normal line prompt after Bubble Tea exits.
            os.write(master, b'6\r')
            pump_until(b'PTY HANDOFF inspect')
            attrs = termios.tcgetattr(master)
            if not attrs[3] & termios.ICANON or not attrs[3] & termios.ECHO:
                raise AssertionError('terminal still in raw/no-echo mode at handoff')
            os.write(master, b'Q typed into ordinary prompt\n')
            pump_until(b'PTY INPUT PRESERVED')

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            done, status = os.waitpid(pid, os.WNOHANG)
            if done == pid:
                child_status = status
                break
            time.sleep(0.05)
        if child_status is None or not os.WIFEXITED(child_status) or os.WEXITSTATUS(child_status) != 0:
            raise AssertionError(f'unexpected exit status: {child_status}')
        print(f'PASS maintenance PTY: {mode}')
    except Exception:
        print(bytes(collected[-6000:]).decode('utf-8', errors='replace'), file=sys.stderr)
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
        print('Usage: python3 pty_maintenance.py /absolute/path/to/Go-test-binary', file=sys.stderr)
        return 2
    for mode in ('route', 'cancel', 'resize'):
        smoke(sys.argv[1], mode)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
