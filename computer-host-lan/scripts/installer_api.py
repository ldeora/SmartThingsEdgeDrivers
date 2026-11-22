#!/usr/bin/env python3
"""Read-only, redacted JSON inspector/planner for the future Linux TUI.

No installation, repairs, credential reads, protected-journal reads, network
connections, privilege escalation or filesystem writes. Uses the actual
installer's Python selection and core change-plan allowlist.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

import install_core as core

SCHEMA_VERSION = 1
DEFAULT_SOURCE = Path(__file__).resolve().parents[1]
REQUIRED_TOOLS = ('systemctl', 'useradd', 'getent', 'install', 'sed')
PYTHON_SELECTOR = DEFAULT_SOURCE / 'scripts/python-selector.sh'
INTERPRETER_COMMAND = (
    '. "$1"; linuxhost_select_python "$2" >/dev/null 2>&1 || exit 1; '
    'printf "%s\\n" "$LINUXHOST_PYTHON"'
)
ERROR_CODES = frozenset({
    'invalid_argument', 'unsafe_managed_path', 'source_unavailable',
    'prerequisite_missing', 'internal_error',
})


class InvalidArgument(ValueError):
    code = 'invalid_argument'


# Alias kept for existing internal callers/tests; not an exported API promise.
InvalidRequest = InvalidArgument


class UnsafeManagedPath(RuntimeError):
    code = 'unsafe_managed_path'


class SourceUnavailable(RuntimeError):
    code = 'source_unavailable'


class PrerequisiteMissing(RuntimeError):
    code = 'prerequisite_missing'


class JSONArgumentParser(argparse.ArgumentParser):
    """Never emit argparse's plain-text usage on invalid API requests."""
    def error(self, message: str) -> None:
        raise InvalidArgument('invalid CLI argument')


def select_python(*, explicit: str | None = None,
                  source: Path = DEFAULT_SOURCE,
                  env: dict[str, str] | None = None) -> str | None:
    """Call the SAME POSIX-shell selector used by install-agent.sh/preflight.sh.

    No user input is interpolated into the shell command; explicit paths are
    passed in argv and checked by linuxhost_select_python. Output is redacted
    to a single absolute interpreter path, or None for no compatible version.
    """
    selector = source / 'scripts/python-selector.sh'
    if not selector.is_file():
        raise SourceUnavailable('Python selector not included in source payload')
    try:
        outcome = subprocess.run(
            ['sh', '-c', INTERPRETER_COMMAND, 'linuxhost-select',
             str(selector), explicit or ''],
            capture_output=True, text=True, timeout=8, check=False, env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise PrerequisiteMissing('Python selection could not complete') from None
    if outcome.returncode:
        if explicit is not None:
            raise InvalidArgument('incompatible or unsafe --python override')
        return None
    selected = outcome.stdout.strip()
    # The selector guarantees an absolute safe executable path; revalidate
    # the returned string before embedding it into any generated unit plan.
    if not re.fullmatch(r'/[A-Za-z0-9_./+-]+', selected):
        raise SourceUnavailable('Python selection returned an invalid path')
    return selected


def valid_interface(value: str | None, *, root: Path = Path('/')) -> str | None:
    if value is None:
        return None
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,15}', value) or value in ('.', '..'):
        raise InvalidArgument('invalid Ethernet interface name')
    # Match install-agent.sh's read-only /sys/class/net existence check.
    # The sysfs interface entries are ordinarily symlinks; is_dir() is
    # intentional here, unlike the managed installation-path safety checks.
    if not (root / 'sys/class/net' / value).is_dir():
        raise InvalidArgument('Ethernet interface is not present')
    return value


def managed_file_status(transaction: core.InstallTransaction, path: str) -> str:
    """Never read or follow managed-file symlinks or protected file content."""
    target = transaction.location(path)
    try:
        transaction.refuse_links(target)
        if target.is_file():
            return 'present'
        return 'absent'
    except OSError:
        return 'unreadable'
    except core.InstallError:
        return 'unsafe'


def service_state(unit: str, command: str, *, systemd_present: bool) -> str:
    if not systemd_present or shutil.which('systemctl') is None:
        return 'unknown'
    if command not in ('is-active', 'is-enabled'):
        raise InvalidArgument('unsupported service probe')
    try:
        result = subprocess.run(
            ['systemctl', command, unit], capture_output=True,
            text=True, timeout=3, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 'unknown'
    value = result.stdout.strip()
    allowed = (
        {'active', 'inactive', 'failed', 'activating', 'deactivating'}
        if command == 'is-active' else
        {'enabled', 'disabled', 'static', 'indirect', 'masked', 'linked',
         'linked-runtime', 'enabled-runtime', 'alias', 'generated', 'transient'}
    )
    return value if value in allowed else 'unknown'


def inspection(*, root: Path = Path('/'), check_services: bool = True,
               python_override: str | None = None,
               source: Path = DEFAULT_SOURCE) -> dict:
    """Unprivileged inspection; no reading root-private backups or identity."""
    trans = core.InstallTransaction(root)
    systemd_present = (root / 'run/systemd/system').is_dir()
    unit_state = managed_file_status(trans, core.SYSTEMD_PATHS[0])
    power_state = managed_file_status(trans, core.POWER_DROPIN)
    avahi_state = managed_file_status(trans, core.AVAHI_PATH)
    avahi_directory = (root / 'etc/avahi/services').is_dir()
    selected_python = select_python(explicit=python_override, source=source)
    probe_services = check_services and root == Path('/')
    def query(unit: str, command: str) -> str:
        if not probe_services:
            return 'unknown'
        return service_state(unit, command, systemd_present=systemd_present)

    avahi_daemon = query('avahi-daemon.service', 'is-active')
    if not avahi_directory or avahi_daemon in ('inactive', 'failed', 'deactivating'):
        avahi_status = 'warning'
    elif avahi_daemon == 'active':
        avahi_status = 'passed'
    else:
        avahi_status = 'not_verified'
    checks = [
        {'id': 'linux', 'status': 'passed' if platform.system() == 'Linux' else 'blocked'},
        {'id': 'python_3_10_plus', 'status': 'passed' if selected_python else 'blocked'},
        {'id': 'systemd_pid1', 'status': 'passed' if systemd_present else 'blocked'},
    ]
    checks.extend(
        {'id': f'tool_{name}', 'status': 'passed' if shutil.which(name) else 'blocked'}
        for name in REQUIRED_TOOLS
    )
    checks.append({'id': 'avahi_discovery', 'status': avahi_status})
    if any(state == 'unsafe' for state in (unit_state, power_state, avahi_state)):
        checks.append({'id': 'managed_path_integrity', 'status': 'blocked'})
    if any(state == 'unreadable' for state in (unit_state, power_state, avahi_state)):
        checks.append({'id': 'managed_path_visibility', 'status': 'not_verified'})
    return {
        'schema_version': SCHEMA_VERSION,
        'operation': 'inspect',
        'mode': 'read_only',
        'checks': checks,
        'python': {'selected_interpreter': selected_python, 'version_supported': bool(selected_python)},
        'avahi': {
            'services_directory': 'present' if avahi_directory else 'absent',
            'daemon_state': avahi_daemon,
        },
        'installation': {
            'detected': unit_state == 'present',
            'service_file': unit_state,
            'power_dropin': power_state,
            'avahi_service_file': avahi_state,
            'agent_service_state': query('linux-host-agent.service', 'is-active') if unit_state == 'present' else 'unknown',
            'agent_service_enabled': query('linux-host-agent.service', 'is-enabled') if unit_state == 'present' else 'unknown',
        },
        'privileged_transaction_state': 'unknown',
        'identity_preserved': 'not_verified',
        'secrets_included': False,
    }


def change_plan(*, source: Path = DEFAULT_SOURCE, root: Path = Path('/'),
                python_bin: str | None = None, enable_power: bool = False,
                disable_power: bool = False, wol_interface: str | None = None) -> dict:
    if enable_power and disable_power:
        raise InvalidArgument('power enable/disable flags conflict')
    valid_interface(wol_interface, root=root)
    selected_python = select_python(explicit=python_bin, source=source)
    if selected_python is None:
        raise PrerequisiteMissing('No supported Python interpreter available')
    trans = core.InstallTransaction(root)
    power_state = managed_file_status(trans, core.POWER_DROPIN)
    if power_state in ('unsafe', 'unreadable'):
        raise UnsafeManagedPath('cannot safely determine existing power settings')
    avahi_state = managed_file_status(trans, core.AVAHI_PATH)
    if avahi_state in ('unsafe', 'unreadable'):
        raise UnsafeManagedPath('cannot safely inspect managed Avahi path')
    try:
        changes = core.generate_plan(
            source, selected_python, enable_power=enable_power,
            disable_power=disable_power, wol_interface=wol_interface,
            is_existing_power=power_state == 'present',
            avahi_dir=(root / 'etc/avahi/services').is_dir(),
        )
    except (OSError, UnicodeError, core.InstallError) as exc:
        raise SourceUnavailable('Unable to generate a plan from the bundled source') from exc
    result = []
    for change in changes:
        status = managed_file_status(trans, change.path)
        if status in ('unsafe', 'unreadable'):
            raise UnsafeManagedPath('managed destination cannot be safely inspected')
        action = 'remove' if change.content is None else ('replace' if status == 'present' else 'create')
        if action == 'remove' and status == 'absent':
            action = 'unchanged'
        result.append({'path': change.path, 'action': action})
    return {
        'schema_version': SCHEMA_VERSION,
        'operation': 'plan',
        'mode': 'read_only',
        'changes': result,
        'selected_python': selected_python,
        'power_option': 'enable' if enable_power else ('disable' if disable_power else 'preserve'),
        'wol_interface_requested': wol_interface is not None,
        'privileged_transaction_state': 'unknown',
        'runtime_verified': False,
        'changes_applied': False,
        'secrets_included': False,
    }


def error_response(command: str, code: str) -> str:
    if code not in ERROR_CODES:
        code = 'internal_error'
    return json.dumps({
        'schema_version': SCHEMA_VERSION, 'operation': command,
        'mode': 'read_only', 'error': {'code': code},
    }, sort_keys=True, separators=(',', ':'))


def main(argv: list[str] | None = None) -> int:
    raw = list(argv) if argv is not None else sys.argv[1:]
    operation = raw[0] if raw and raw[0] in ('inspect', 'plan') else 'unknown'
    try:
        parser = JSONArgumentParser(description='Experimental read-only Linux installer JSON API')
        sub = parser.add_subparsers(dest='command', required=True, parser_class=JSONArgumentParser)
        inspect = sub.add_parser('inspect', help='redacted unprivileged environment summary')
        inspect.add_argument('--python')
        plan = sub.add_parser('plan', help='read-only prospective managed changes')
        plan.add_argument('--enable-power', action='store_true')
        plan.add_argument('--disable-power', action='store_true')
        plan.add_argument('--wol-interface')
        plan.add_argument('--python')
        args = parser.parse_args(raw)
        if args.command == 'inspect':
            result = inspection(python_override=args.python)
        else:
            result = change_plan(
                python_bin=args.python, enable_power=args.enable_power,
                disable_power=args.disable_power, wol_interface=args.wol_interface,
            )
    except (InvalidArgument, UnsafeManagedPath, SourceUnavailable, PrerequisiteMissing) as exc:
        print(error_response(operation, exc.code), file=sys.stderr)
        return 2
    except Exception:
        # Never include exception details, paths, injected input or secrets.
        print(error_response(operation, 'internal_error'), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
