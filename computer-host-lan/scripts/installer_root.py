#!/usr/bin/env python3
"""Computer Host LAN privileged installer request boundary (NOT a bootstrap).

This file MUST be installed as root-owned code at the fixed _TRUSTED_DIR
before use. Never run via sudo from a checkout, extracted archive, /tmp,
or a writable Go wizard directory. This module is deliberately importable
for pure schema/dispatch tests without requiring root or systemd.

Expected production argv (selected by installed root-owned shell entry):
  /bin/sh /usr/libexec/computer-host-lan/installer-entry.sh --request-stdin

The trusted shell hands off the *selected system Python command* as
--selected-python. It may differ from sys.executable on Gentoo python-exec.
An older installed helper may still invoke --request-stdin alone for a
read-only 'status' call, but install/upgrade/repair require the handoff.

The root-owned entry script chooses the first compatible interpreter from
python3, python3.14 .. python3.10, using a fixed system PATH and -I -S -B.
The verified Go wizard's explicitly authorized bootstrap must provision
these trusted files and manifest on first install and every upgrade.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Mapping

_TRUSTED_DIR = Path('/usr/libexec/computer-host-lan')
_TRUSTED_MODULES = (
    'installer_root.py',
    'installer-entry.sh',
    'installer_transaction.py',
    'install_core.py',
    'payload_staging.py',
    'transaction_journal.py',
    'runtime_verify.py',
)
_MANIFEST_FILE = 'trusted-payload.json'
_MANIFEST_FILES = frozenset((
    'agent/linux_host_agent.py',
    'agent/power_helper.py',
    'agent/systemd/linux-host-agent.service',
    'agent/systemd/linux-host-agent-power.service',
    'agent/systemd/linux-host-agent-power.socket',
    'agent/systemd/enable-power.conf',
    'agent/systemd/avahi-linux-host-agent.service',
    'scripts/install_core.py',
    'scripts/runtime_verify.py',
    'scripts/transaction_journal.py',
))
_SHA256 = re.compile(r'[0-9a-f]{64}\Z')
_VERSION = re.compile(r'[0-9A-Za-z][0-9A-Za-z.+_-]{0,63}\Z')
_NIC = re.compile(r'[A-Za-z0-9_.-]{1,15}\Z')
_ACTIONS = frozenset(('status', 'recover', 'install', 'upgrade', 'repair'))
# Exact entries in the fixed PATH and candidate-name list of installer-entry.sh.
_SYSTEM_PYTHON_DIRS = ('/usr/sbin', '/usr/bin', '/sbin', '/bin')
_SYSTEM_PYTHON_NAMES = (
    'python3', 'python3.14', 'python3.13',
    'python3.12', 'python3.11', 'python3.10'
)
_SYSTEM_PYTHON_COMMANDS = frozenset(
    directory + '/' + name
    for directory in _SYSTEM_PYTHON_DIRS for name in _SYSTEM_PYTHON_NAMES
)
_MAX_REQUEST_BYTES = 4096
_MAX_MANIFEST_BYTES = 4096


class RequestError(ValueError):
    """No source paths or untrusted JSON contents are included in errors."""


def selected_python_from_argv(argv: list[str]) -> str | None:
    """Bounded internal shell-to-Python handoff, never from request JSON.

    Legacy root-owned helpers can call status with --request-stdin alone;
    this form MUST NOT authorize install/upgrade/repair operations.
    """
    if argv == ['--request-stdin']:
        return None
    if (len(argv) == 3 and argv[:2] == ['--request-stdin', '--selected-python']
            and argv[2] in _SYSTEM_PYTHON_COMMANDS):
        return argv[2]
    raise RequestError('invalid_request')


def validate_python_handoff(request: dict, selected_python: str | None) -> None:
    """The old single-argument form is reserved for read-only status only."""
    if selected_python is None and request['action'] != 'status':
        raise RequestError('invalid_request')
    if selected_python is not None and selected_python not in _SYSTEM_PYTHON_COMMANDS:
        raise RequestError('invalid_request')


def _unique_pairs(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise RequestError('duplicate_key')
        result[name] = value
    return result


def parse_request(raw: bytes) -> dict:
    """Exact versioned one-shot request; never accept arbitrary commands."""
    if not isinstance(raw, bytes) or not 0 < len(raw) <= _MAX_REQUEST_BYTES:
        raise RequestError('invalid_request')
    try:
        payload = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_pairs)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise RequestError('invalid_request') from exc
    if not isinstance(payload, dict) or type(payload.get('schema_version')) is not int:
        raise RequestError('invalid_request')
    action = payload.get('action')
    if payload['schema_version'] == 2:
        if action != 'uninstall' or set(payload) != {'schema_version', 'action'}:
            raise RequestError('invalid_request')
        return dict(action='uninstall')
    if payload['schema_version'] != 1:
        raise RequestError('invalid_request')
    if type(action) is not str or action not in _ACTIONS:
        raise RequestError('invalid_request')
    if action in ('status', 'recover'):
        if set(payload) != {'schema_version', 'action'}:
            raise RequestError('invalid_request')
        return dict(action=action)
    if set(payload) != {'schema_version', 'action', 'source', 'power', 'wol_interface'}:
        raise RequestError('invalid_request')
    source = payload['source']
    if (type(source) is not str or len(source) > 1024 or not source.startswith('/')
            or '\0' in source or any(ord(ch) < 32 for ch in source)
            or '..' in Path(source).parts):
        raise RequestError('invalid_request')
    # The unprivileged source is allowed to be writable; the *bytes* are
    # independently authenticated against the trusted root-owned manifest.
    power = payload['power']
    if type(power) is not str or power not in ('preserve', 'enable', 'disable'):
        raise RequestError('invalid_request')
    nic = payload['wol_interface']
    if nic is not None and (type(nic) is not str or not _NIC.fullmatch(nic)
                            or nic in ('.', '..')):
        raise RequestError('invalid_request')
    return dict(action=action, source=source, power=power, wol_interface=nic)


def validate_manifest(payload: object) -> dict:
    if not isinstance(payload, dict) or set(payload) != {
        'schema_version', 'agent_version', 'files'
    } or type(payload['schema_version']) is not int or payload['schema_version'] != 1:
        raise RequestError('invalid_trusted_manifest')
    version = payload['agent_version']
    files = payload['files']
    if (type(version) is not str or not _VERSION.fullmatch(version)
            or type(files) is not dict or set(files) != _MANIFEST_FILES
            or any(type(value) is not str or not _SHA256.fullmatch(value)
                   for value in files.values())):
        raise RequestError('invalid_trusted_manifest')
    return dict(agent_version=version, files=files)


def _root_owned_file(path: Path, *, directory: bool) -> None:
    """No-follow fixed-path traversal and exact final file type."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC |
                 (os.O_DIRECTORY if directory else os.O_NONBLOCK))
    try:
        st = os.fstat(fd)
        if (st.st_uid != 0 or st.st_mode & 0o022 or
                (not stat.S_ISDIR(st.st_mode) if directory
                 else not stat.S_ISREG(st.st_mode) or st.st_nlink != 1)):
            raise RequestError('untrusted_root_launcher')
    finally:
        os.close(fd)


def require_supported_python(version_info=None) -> None:
    """Refuse to run the backend on a distribution's unsupported default Python.

    RHEL 9's /usr/bin/python3 is commonly 3.9, while Leap 15.6 can
    default to 3.6. Selection occurs in the installed shell entry,
    and this guard makes a wrong/direct invocation fail before action.
    """
    if version_info is None:
        version_info = sys.version_info
    if tuple(version_info[:2]) < (3, 10):
        raise RequestError('unsupported_python')


def _read_root_manifest() -> dict:
    """Only read AFTER verifying the fixed root-owned installation tree."""
    require_supported_python()
    if (os.geteuid() != 0 or not sys.flags.isolated or
            not sys.flags.no_site or not sys.dont_write_bytecode or
            Path(__file__).absolute() != _TRUSTED_DIR / 'installer_root.py'):
        raise RequestError('untrusted_root_launcher')
    current = Path('/')
    _root_owned_file(current, directory=True)
    for part in _TRUSTED_DIR.parts[1:]:
        current = current / part
        _root_owned_file(current, directory=True)
    for name in _TRUSTED_MODULES:
        _root_owned_file(_TRUSTED_DIR / name, directory=False)
    path = _TRUSTED_DIR / _MANIFEST_FILE
    _root_owned_file(path, directory=False)
    with path.open('rb') as inp:
        raw = inp.read(_MAX_MANIFEST_BYTES + 1)
    if len(raw) > _MAX_MANIFEST_BYTES:
        raise RequestError('invalid_trusted_manifest')
    try:
        manifest = json.loads(raw.decode('ascii'), object_pairs_hook=_unique_pairs)
    except (ValueError, UnicodeError):
        raise RequestError('invalid_trusted_manifest') from None
    return validate_manifest(manifest)


def dispatch(request: dict, trusted_manifest: dict, *, backend, journal,
             selected_python: str | None = None) -> dict:
    """Testable pure router. Caller must already be an authenticated root entrypoint."""
    action = request['action']
    if action == 'status':
        data = journal.public_status()
        return dict(status='passed', operation='status',
                    privileged_transaction_state=data['privileged_transaction_state'],
                    secrets_included=False)
    if action == 'recover':
        done = backend.recover_interrupted()
        result = dict(status='passed', operation='recover',
                      recovery_status=done.status, secrets_included=False)
        if done.operation in ('install', 'upgrade', 'repair', 'uninstall'):
            result['recovery_operation'] = done.operation
        return result
    # The installed root-owned shell has already selected and version-checked
    # this executable from fixed system paths. sys.executable is *not*
    # reliable on Gentoo's python-exec wrappers: it can instead be
    # /usr/lib/python-exec/python3.14/python3. Never broaden the backend
    # allowlist to accept all of /usr/lib.
    if selected_python not in _SYSTEM_PYTHON_COMMANDS:
        raise RequestError('invalid_request')
    if action == 'uninstall':
        if set(request) != {'action'}:
            raise RequestError('invalid_request')
        done = backend.uninstall()
        if (done.status not in ('uninstalled', 'uninstalled_cleanup_required') or
                done.identity_preserved not in ('verified', 'not_verified')):
            raise RequestError('invalid_request')
        return dict(status=done.status, operation='uninstall',
                    identity_preserved=done.identity_preserved,
                    secrets_included=False)
    from installer_transaction import InstallRequest
    power = request['power']
    options = InstallRequest(
        operation=action, python_bin=selected_python,
        expected_version=trusted_manifest['agent_version'],
        enable_power=(power == 'enable'),
        disable_power=(power == 'disable'),
        wol_interface=request['wol_interface'],
    )
    done = backend.run(options, Path(request['source']), trusted_manifest['files'])
    return dict(status=done.status, operation=action,
                identity_preserved=done.identity_preserved,
                source_verified=done.source_verified, secrets_included=False)


def _reply(payload: dict) -> None:
    # Never echo request bytes, source paths, UUIDs, tokens, traceback, or logs.
    sys.stdout.write(json.dumps(dict(schema_version=1, **payload),
                                sort_keys=True, separators=(',', ':')) + '\n')
    sys.stdout.flush()


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    try:
        selected_python = selected_python_from_argv(argv)
    except RequestError:
        _reply(dict(status='error', error_code='invalid_request',
                    secrets_included=False))
        return 2
    try:
        require_supported_python()
        manifest = _read_root_manifest()
        # Drop inherited environment before importing trusted project code
        # or making any subprocess/systemctl calls. The invoker MUST also
        # clear LD_* at sudo/exec boundary, before Python's loader starts.
        os.environ.clear()
        os.environ.update(PATH='/usr/sbin:/usr/bin:/sbin:/bin',
                          LANG='C', LC_ALL='C', HOME='/root')
        raw = sys.stdin.buffer.read(_MAX_REQUEST_BYTES + 1)
        request = parse_request(raw)
        validate_python_handoff(request, selected_python)
        sys.path.insert(0, str(_TRUSTED_DIR))
        from installer_transaction import InstallerBackend, ControllerError
        from transaction_journal import ProtectedJournal
        try:
            result = dispatch(request, manifest, backend=InstallerBackend(),
                              journal=ProtectedJournal(),
                              selected_python=selected_python)
        except ControllerError as exc:
            # 'adoption_required' and pre-apply failure_stage are fixed
            # public codes; never serialize exception text, paths, IDs
            # or contents of the privileged journal/snapshot.
            envelope = dict(
                status='error', error_code=exc.code,
                secrets_included=False,
                adoption_hint=(
                    'Verify retained v2 state, then run the manual '
                    'installer with --adopt-retained-state.'
                    if exc.code == 'adoption_required' else None))
            if exc.code == 'aborted' and exc.failure_stage is not None:
                envelope['failure_stage'] = exc.failure_stage
            _reply(envelope)
            return 3
        _reply(result)
        return 0
    except (RequestError, OSError) as exc:
        code = str(exc) if isinstance(exc, RequestError) else 'untrusted_root_launcher'
        if code not in ('invalid_request', 'invalid_trusted_manifest',
                        'untrusted_root_launcher', 'duplicate_key',
                        'unsupported_python'):
            code = 'invalid_request'
        _reply(dict(status='error', error_code=code, secrets_included=False))
        return 2
    except Exception:
        _reply(dict(status='error', error_code='recovery_required',
                    secrets_included=False))
        return 4


if __name__ == '__main__':
    raise SystemExit(main())
