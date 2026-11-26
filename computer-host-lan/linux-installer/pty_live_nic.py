#!/usr/bin/env python3
"""End-to-end novice flow: preselected hub -> power -> Review -> cancel.

Uses a fake Avahi executable and read-only API, never real host services,
SmartThings hub packets or system changes.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import pty
import select
import signal
import struct
import sys
import tempfile
import termios
import time


INSPECT = ('{"schema_version":1,"operation":"inspect","mode":"read_only",'
           '"checks":[{"id":"linux","status":"passed"}],'
           '"python":{"selected_interpreter":"/usr/bin/python3","version_supported":true},'
           '"avahi":{"services_directory":"present","daemon_state":"active"},'
           '"installation":{"detected":true,"service_file":"present","power_dropin":"present",'
           '"avahi_service_file":"present","agent_service_state":"active",'
           '"agent_service_enabled":"enabled"},"privileged_transaction_state":"unknown",'
           '"identity_preserved":"not_verified","secrets_included":false}')
PLAN = ('{"schema_version":1,"operation":"plan","mode":"read_only",'
        '"changes":[{"path":"/etc/systemd/system/linux-host-agent.service","action":"replace"}],'
        '"selected_python":"/usr/bin/python3","power_option":"preserve",'
        '"wol_interface_requested":false,"privileged_transaction_state":"unknown",'
        '"runtime_verified":false,"changes_applied":false,"secrets_included":false}')

# Strict fake plan: the normal path must not select an advanced NIC.
SCRIPT = """#!/bin/sh
case "$1" in
inspect)
    cat <<'JSON'
%s
JSON
    ;;
plan)
    [ "$#" -eq 1 ] || exit 2
    cat <<'JSON'
%s
JSON
    ;;
*)
    exit 2
    ;;
esac
""" % (INSPECT, PLAN)


def exercise(binary: str, api: str, *, fresh: bool = False) -> None:
    pid, master = pty.fork()
    if pid == 0:
        try:
            env = os.environ.copy()
            env.update(TERM='xterm-256color', NO_COLOR='1',
                       PATH=str(Path(api).parent) + os.pathsep + env.get('PATH', ''))
            if fresh:
                env['COMPUTER_HOST_FRESH_WOL_PTY_API'] = api
                os.execve(binary, [binary, '-test.run=^TestFreshWOLPreviewPTY
        except Exception as exc:
            print(f'PTY execution failed: {exc}', file=sys.stderr)
            os._exit(127)

    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack('HHHH', 40, 110, 0, 0))
    os.set_blocking(master, False)
    captured = bytearray()
    child_status = None

    def wait_for(needle: bytes, from_pos: int = 0, timeout: float = 12.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if needle in captured[from_pos:]:
                return
            readable, _, _ = select.select([master], [], [], 0.05)
            if not readable:
                continue
            try:
                chunk = os.read(master, 65536)
            except BlockingIOError:
                continue
            except OSError:
                break
            if not chunk:
                break
            captured.extend(chunk)
        if needle not in captured[from_pos:]:
            raise AssertionError(f'Full-screen wizard did not display {needle!r}')

    def send(data: bytes) -> int:
        mark = len(captured)
        os.write(master, data)
        return mark

    try:
        wait_for(b'1. Welcome')
        mark = send(b'\r')
        wait_for(b'2. SmartThings hub', mark)
        wait_for(b'192.168.1.103', mark)

        # A single discovered hub must be preselected: Enter should advance,
        # not force a user to choose an IP or hunt for a network interface.
        mark = send(b'\r')
        wait_for(b'3. Power control', mark)
        # Both power choices and advanced-network choices are fields in
        # one Huh page. The second title is already rendered before we
        # advance past the first field.
        wait_for(b'Wake-on-LAN', mark)

        send(b'\r')  # Keep the existing (enabled) power-control state.
        time.sleep(0.15)
        mark = send(b'\r')  # Leave network settings unchanged.
        if fresh:
            wait_for(b'Network details', mark)
            wait_for(b'LAN0', mark)
            mark = send(b'\r')
        wait_for(b'4. Review', mark)
        wait_for(b'192.168.1.103 (found automatically)', mark)
        if fresh:
            wait_for(b'Wake-on-LAN: configure LAN0', mark)
        else:
            wait_for(b'Keep power control enabled', mark)

        mark = send(b'\x03')
        wait_for(b'Setup preview cancelled. No changes made.', mark, 6)
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            done, status = os.waitpid(pid, os.WNOHANG)
            if done == pid:
                child_status = status
                break
            time.sleep(0.05)
        if child_status is None or not os.WIFEXITED(child_status) or os.WEXITSTATUS(child_status):
            raise AssertionError(f'Expected clean cancellation, got status={child_status}')
        print('PASS novice live PTY: welcome -> preselected hub -> power -> Review -> cancel')
    except Exception:
        print('Captured terminal tail:', bytes(captured[-9000:]).decode(errors='replace'), file=sys.stderr)
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
    if len(sys.argv) != 3 or not all(os.path.isabs(p) for p in sys.argv[1:]):
        print('Usage: python3 pty_live_nic.py /absolute/wizard /absolute/go-test-binary', file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix='computer-host-nic-pty-') as directory:
        api = Path(directory) / 'installer-api.sh'
        api.write_text(SCRIPT, encoding='utf-8')
        api.chmod(0o755)
        avahi = Path(directory) / 'avahi-browse'
        avahi.write_text(
            '#!/bin/sh\n'
            'printf "=;eth0;IPv4;Test Hub;_smartthings._tcp;local;hub.local;192.168.1.103;5000;txt\\n"\n',
            encoding='utf-8')
        avahi.chmod(0o755)
        exercise(sys.argv[1], str(api))
        inspect = json.loads(INSPECT)
        inspect['installation'].update(detected=False, service_file='absent',
                                       power_dropin='absent', avahi_service_file='absent',
                                       agent_service_state='inactive',
                                       agent_service_enabled='disabled')
        plan = json.loads(PLAN)
        plan['changes'][0]['action'] = 'create'
        plan['wol_interface_requested'] = True
        plan['wol_policy'] = dict(
            action='configure', interface='LAN0', mac='02:11:22:33:44:55',
            backend='nm', profile='aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee',
            previous='1', link_name=None, link_text=None, digest='a' * 64,
            capability='unknown', connection_name='Wired connection 1')
        api.write_text("""#!/bin/sh
case "$1" in
inspect)
    cat <<'JSON'
%s
JSON
    ;;
plan)
    [ "$#" -eq 4 ] && [ "$2" = "--wol-interface" ] &&
      [ "$3" = "LAN0" ] && [ "$4" = "--configure-wol" ] || exit 2
    cat <<'JSON'
%s
JSON
    ;;
*) exit 2 ;;
esac
""" % (json.dumps(inspect), json.dumps(plan)), encoding='utf-8')
        exercise(sys.argv[2], str(api), fresh=True)
        print('PASS fresh live PTY: default Configure -> Network details -> Review -> cancel')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
