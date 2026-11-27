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
    detail = mode in ('inspect', 'backup-cancel', 'backup-review', 'backup-approve')
    operation = mode in ('configure', 'recover', 'uninstall')
    app = mode.startswith('app-')
    result = mode.startswith('result-')
    width, height = (60, 20) if mode == 'resize' else ((64, 22) if detail or operation or result else (110, 40) if app else (100, 28))
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
            if operation:
                env['COMPUTER_HOST_TEST_OPERATION_PTY'] = mode
                harness = 'TestOperationScreenPTYHarness'
            if app:
                env['COMPUTER_HOST_TEST_APP_PTY'] = mode
                harness = 'TestMaintenanceApplicationPTYHarness'
            if result:
                env['COMPUTER_HOST_TEST_RESULT_PTY'] = mode
                harness = 'TestResultScreenPTYHarness'
            os.execve(binary, [binary, f'-test.run=^{harness}$', '-test.v'], env)
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

        if result:
            pump_until(b'No intermediate progress is reported.')
            pump_until(b'COMPUTER HOST LAN / RESULT')
            if mode == 'result-failure':
                pump_until(b'Operation rolled back')
            else:
                pump_until(b'Cleanup required: choose Recover in the menu.')
            pump_until(b'Enter/Esc/Q Close')
            os.write(master, b'\r')
            pump_until(b'PTY RESULT CLOSED')
            attrs = termios.tcgetattr(master)
            if not attrs[3] & termios.ICANON or not attrs[3] & termios.ECHO:
                raise AssertionError('terminal still in raw/no-echo mode after result')
            if b'\x1b[?1049l' not in collected:
                raise AssertionError('result screen not restored')
            os.write(master, b'ordinary terminal input\n')
            pump_until(b'PTY RESULT INPUT PRESERVED')
        elif app:
            pump_until(b'(recommended)')
            if mode == 'app-recover':
                os.write(master, b'5\r')
                pump_until(b'Recover an interrupted operation')
                os.write(master, b'\r')
                pump_until(b'Type RECOVER to authorize:')
                pump_until(b'Enter Submit | Ctrl+U Clear')
                if b'\x1b[?1049l' in collected:
                    raise AssertionError('application exited before recovery consent')
                os.write(master, b'RECOVER\r')
                pump_until(b'PTY APP HANDOFF recover')
            elif mode == 'app-wol':
                os.write(master, b'2\r')
                pump_until(b'Choose what to configure')
                os.write(master, b'2\r')
                pump_until(b'LAN1 (suggested)')
                if b'\x1b[?1049l' in collected:
                    raise AssertionError('application exited before WOL interface choice')
                os.write(master, b'\r')
                pump_until(b'PTY APP HANDOFF wol')
            else:
                os.write(master, b'1\r')
                pump_until(b'Searching for SmartThings hubs')
                pump_until(b'1. Welcome')
                os.write(master, b'\r')
                pump_until(b'2. SmartThings hub')
                os.write(master, b'\r')
                pump_until(b'3. Power control')
                pump_until(b'Wake-on-LAN')
                os.write(master, b'\r')
                time.sleep(0.15)
                os.write(master, b'\r')
                pump_until(b'4. Review')
                pump_until(b'Continue to confirmation')
                os.write(master, b'\r')
                pump_until(b'Type INSTALL to authorize:')
                pump_until(b'Enter Submit | Ctrl+U Clear')
                if b'\x1b[?1049l' in collected:
                    raise AssertionError('application exited before setup consent')
                os.write(master, b'INSTAL\r')
                pump_until(b'exactly, or Esc to go back.')
                if b'\x1b[?1049l' in collected:
                    raise AssertionError('mistyped confirmation exited the application')
                os.write(master, b'L\r')
                pump_until(b'PTY APP HANDOFF install-reviewed')
            attrs = termios.tcgetattr(master)
            if not attrs[3] & termios.ICANON or not attrs[3] & termios.ECHO:
                raise AssertionError('application still owns terminal at handoff')
            if b'\x1b[?1049l' not in collected:
                raise AssertionError('alternate screen not restored')
            os.write(master, b'ordinary terminal input\n')
            pump_until(b'PTY APP INPUT PRESERVED')
        elif operation:
            pump_until(b'COMPUTER HOST LAN / ' + mode.upper().encode())
            pump_until(b'Enter Select | Esc/Q Cancel')
            os.write(master, b'2\r' if mode == 'configure' else b'1\r')
            if mode == 'configure':
                pump_until(b'PTY CONFIGURE HANDOFF wol')
            else:
                token = b'RECOVER' if mode == 'recover' else b'UNINSTALL'
                pump_until(b'Type ' + token + b' to authorize:')
                pump_until(b'Enter Submit | Ctrl+U Clear')
                os.write(master, b'NO\r')
                pump_until(b'exactly, or Esc to go back.')
                os.write(master, b'\x03')
                pump_until(b'PTY CONSENT CANCELLED')
                attrs = termios.tcgetattr(master)
                if not attrs[3] & termios.ICANON or not attrs[3] & termios.ECHO:
                    raise AssertionError('terminal still in raw/no-echo mode after consent')
            pump_until(b'PTY OPERATION CLOSED')
        elif mode == 'inspect':
            pump_until(b'Read-only snapshot')
            os.write(master, b'\x1b[F')  # End
            pump_until(b'Recovery not inspected; identity/key not read or verified.')
            os.write(master, b'q')
            pump_until(b'PTY INSPECTION CLOSED')
        elif mode.startswith('backup-'):
            pump_until(b'Backup 1 of 32')
            os.write(master, b'\x1b[F')  # End selects the oldest fixture
            # Bubble Tea updates the existing screen with cursor movement
            # and changed text, rather than retransmitting the whole row.
            # The unchanged "Backup " prefix need not be on the wire again.
            pump_until(b'32 of 32 | Enter opens review, not restore')
            if mode == 'backup-cancel':
                os.write(master, b'q')
            else:
                os.write(master, b'\r')
                pump_until(b'Type RESTORE to authorize:')
                pump_until(b'Enter Submit | Ctrl+U Clear')
                if b'\x1b[?1049l' in collected:
                    raise AssertionError('backup chooser exited before literal consent')
                os.write(master, b'RESTORE\r' if mode == 'backup-approve' else b'NO\r')
                if mode == 'backup-approve':
                    pump_until(b'Historical backup restored.')
                else:
                    pump_until(b'exactly, or Esc to go back.')
                    os.write(master, b'\x03')
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
    for mode in ('route', 'cancel', 'resize', 'inspect', 'backup-cancel', 'backup-review', 'backup-approve',
                 'configure', 'recover', 'uninstall', 'app-recover', 'app-wol', 'app-install', 'result-success', 'result-failure'):
        smoke(sys.argv[1], mode)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
