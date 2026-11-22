#!/usr/bin/env python3
"""Read-only, redacted JSON inspector/planner for the future Linux TUI.

This preliminary *unprivileged* interface does not install, repair, elevate,
write files, access private identity/token material, or report protected backup
and transaction-journal contents. It deliberately reuses install_core's plan
generation and managed-path allowlist to avoid a second installation engine.

Schema 1 is experimental. Only inspect and plan are implemented.
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
READ_ONLY_ACTIONS = ('inspect', 'plan')
REQUIRED_TOOLS = ('systemctl', 'useradd', 'getent', 'install', 'sed')
ALLOWED_FILE_STATES = ('absent', 'present', 'unsafe', 'unreadable')


class InvalidRequest(ValueError):
    pass


def valid_interface(value: str | None) -> str | None:
    if value is None:
        return None
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,15}', value):
        raise InvalidRequest('invalid Ethernet interface name')
    return value


def python_executable(path: str) -> str:
    """Validate a preview interpreter path, not its future root trust."""
    if (not os.path.isabs(path) or any(ord(c) < 33 or ord(c) > 126 for c in path)
            or any(c in path for c in ('"', "'", '\\', ';', '#'))):
        raise InvalidRequest('Python executable must be an absolute path without shell/unit syntax')
    return path


def managed_file_status(transaction: core.InstallTransaction, path: str) -> str:
    """Do not follow linked managed paths, and never read their contents."""
    target = transaction.location(path)
    try:
        transaction.refuse_links(target)
        if target.is_file():
            return 'present'
        return 'absent'
    except (OSError, PermissionError):
        return 'unreadable'
    except core.InstallError:
        return 'unsafe'


def service_state(unit: str, *, systemd_present: bool) -> str:
    if not systemd_present or shutil.which('systemctl') is None:
        return 'unknown'
    try:
        result = subprocess.run(
            ['systemctl', 'is-active', unit], capture_output=True,
            text=True, timeout=3, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 'unknown'
    value = result.stdout.strip()
    return value if value in {'active', 'inactive', 'failed', 'activating', 'deactivating'} else 'unknown'


def inspection(*, root: Path = Path('/'), check_services: bool = True) -> dict:
    """Minimal allowlisted environment facts, without reading protected data."""
    trans = core.InstallTransaction(root)
    systemd_present = (root / 'run/systemd/system').is_dir()
    unit_state = managed_file_status(trans, core.SYSTEMD_PATHS[0])
    power_state = managed_file_status(trans, core.POWER_DROPIN)
    avahi_state = managed_file_status(trans, core.AVAHI_PATH)
    python_supported = sys.version_info >= (3, 10)
    checks = [
        {'id': 'linux', 'status': 'passed' if platform.system() == 'Linux' else 'blocked'},
        {'id': 'python_3_10_plus', 'status': 'passed' if python_supported else 'blocked'},
        {'id': 'systemd_pid1', 'status': 'passed' if systemd_present else 'blocked'},
    ]
    checks += [
        {'id': f'tool_{name}', 'status': 'passed' if shutil.which(name) else 'blocked'}
        for name in REQUIRED_TOOLS
    ]
    if avahi_state != 'present':
        checks.append({'id': 'avahi_advertisement', 'status': 'warning'})
    if any(state == 'unsafe' for state in (unit_state, power_state, avahi_state)):
        checks.append({'id': 'managed_path_integrity', 'status': 'blocked'})
    return {
        'schema_version': SCHEMA_VERSION,
        'operation': 'inspect',
        'mode': 'read_only',
        'checks': checks,
        'installation': {
            'detected': unit_state == 'present',
            'service_file': unit_state,
            'power_dropin': power_state,
            'avahi_service_file': avahi_state,
            'agent_service_state': service_state('linux-host-agent.service', systemd_present=systemd_present)
                                   if check_services and root == Path('/') else 'unknown',
        },
        # These facts live in root-private storage. They must be obtained later
        # via a separate authenticated/read-only privileged helper, not guessed.
        'privileged_transaction_state': 'unknown',
        'identity_preserved': 'not_verified',
        'secrets_included': False,
    }


def change_plan(*, source: Path = DEFAULT_SOURCE, root: Path = Path('/'),
                python_bin: str = sys.executable, enable_power: bool = False,
                disable_power: bool = False, wol_interface: str | None = None) -> dict:
    if enable_power and disable_power:
        raise InvalidRequest('power enable/disable flags conflict')
    valid_interface(wol_interface)
    python_executable(python_bin)
    trans = core.InstallTransaction(root)
    power_state = managed_file_status(trans, core.POWER_DROPIN)
    if power_state in ('unsafe', 'unreadable'):
        raise InvalidRequest('cannot safely determine existing power settings')
    avahi_state = managed_file_status(trans, core.AVAHI_PATH)
    if avahi_state in ('unsafe', 'unreadable'):
        raise InvalidRequest('cannot safely inspect Avahi path')
    # No copies of the installed persistent UUID, key or service credentials.
    changes = core.generate_plan(
        source, python_bin, enable_power=enable_power,
        disable_power=disable_power, wol_interface=wol_interface,
        is_existing_power=power_state == 'present',
        avahi_dir=(root / 'etc/avahi/services').is_dir(),
    )
    result = []
    for change in changes:
        status = managed_file_status(trans, change.path)
        if status in ('unsafe', 'unreadable'):
            raise InvalidRequest('managed path cannot be safely inspected')
        action = 'remove' if change.content is None else ('replace' if status == 'present' else 'create')
        # Don't say a missing removable file is actually being removed.
        if action == 'remove' and status == 'absent':
            action = 'unchanged'
        result.append({'path': change.path, 'action': action})
    return {
        'schema_version': SCHEMA_VERSION,
        'operation': 'plan',
        'mode': 'read_only',
        'changes': result,
        'power_option': 'enable' if enable_power else ('disable' if disable_power else 'preserve'),
        'wol_interface_requested': wol_interface is not None,
        'privileged_transaction_state': 'unknown',
        'runtime_verified': False,
        'changes_applied': False,
        'secrets_included': False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Experimental read-only Linux installer JSON API')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('inspect', help='redacted, unprivileged environment summary in JSON')
    plan = sub.add_parser('plan', help='redacted, read-only prospective managed-file changes in JSON')
    plan.add_argument('--enable-power', action='store_true')
    plan.add_argument('--disable-power', action='store_true')
    plan.add_argument('--wol-interface')
    args = parser.parse_args(argv)
    try:
        if args.command == 'inspect':
            result = inspection()
        elif args.command == 'plan':
            result = change_plan(
                enable_power=args.enable_power,
                disable_power=args.disable_power,
                wol_interface=args.wol_interface,
            )
        else:
            raise InvalidRequest('unsupported action')
    except (InvalidRequest, core.InstallError, OSError, UnicodeError, ValueError):
        # No raw paths or potentially sensitive exception data in the JSON API.
        print(json.dumps({
            'schema_version': SCHEMA_VERSION,
            'operation': args.command,
            'mode': 'read_only',
            'error': {'code': 'invalid_or_unsafe_request'},
        }, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
