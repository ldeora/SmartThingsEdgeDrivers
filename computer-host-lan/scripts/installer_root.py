#!/usr/bin/env python3
"""Computer Host LAN privileged installer request boundary (NOT a bootstrap).

This file MUST be installed as root-owned code at the fixed _TRUSTED_DIR
before use. Never run via sudo from a checkout, extracted archive, /tmp,
or a writable Go wizard directory. This module is deliberately importable
for pure schema/dispatch tests without requiring root or systemd.

Expected production argv:
  /usr/bin/python3 -I -S -B /usr/libexec/computer-host-lan/installer_root.py --request-stdin

A future verified package/Go launcher must provision the trusted code and
manifest independently of the unprivileged wizard's mutable payload.
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
_MAX_REQUEST_BYTES = 4096
_MAX_MANIFEST_BYTES = 4096


class RequestError(ValueError):
    """No source paths or untrusted JSON contents are included in errors."""


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
    if not isinstance(payload, dict) or payload.get('schema_version') != 1 or (
            type(payload['schema_version']) is not int):
        raise RequestError('invalid_request')
    action = payload.get('action')
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


def _read_root_manifest() -> dict:
    """Only read AFTER verifying the fixed root-owned installation tree."""
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


def dispatch(request: dict, trusted_manifest: dict, *, backend, journal) -> dict:
    """Testable pure router. Caller must already be an authenticated root entrypoint."""
    action = request['action']
    if action == 'status':
        data = journal.public_status()
        return dict(status='passed', operation='status',
                    privileged_transaction_state=data['privileged_transaction_state'],
                    secrets_included=False)
    if action == 'recover':
        done = backend.recover_interrupted()
        return dict(status='passed', operation='recover',
                    recovery_status=done.status, secrets_included=False)
    from installer_transaction import InstallRequest
    power = request['power']
    options = InstallRequest(
        operation=action, python_bin=sys.executable,
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
    if argv != ['--request-stdin']:
        _reply(dict(status='error', error_code='invalid_request',
                    secrets_included=False))
        return 2
    try:
        manifest = _read_root_manifest()
        # Drop inherited environment before importing trusted project code
        # or making any subprocess/systemctl calls. The invoker MUST also
        # clear LD_* at sudo/exec boundary, before Python's loader starts.
        os.environ.clear()
        os.environ.update(PATH='/usr/sbin:/usr/bin:/sbin:/bin',
                          LANG='C', LC_ALL='C', HOME='/root')
        raw = sys.stdin.buffer.read(_MAX_REQUEST_BYTES + 1)
        request = parse_request(raw)
        sys.path.insert(0, str(_TRUSTED_DIR))
        from installer_transaction import InstallerBackend, ControllerError
        from transaction_journal import ProtectedJournal
        try:
            result = dispatch(request, manifest, backend=InstallerBackend(),
                              journal=ProtectedJournal())
        except ControllerError as exc:
            # 'adoption_required' is a fixed user-facing diagnostic; no
            # arbitrary traceback or file/identity metadata can escape.
            _reply(dict(status='error', error_code=exc.code,
                        adoption_hint=(
                            'Verify retained v2 state, then run the manual '
                            'installer with --adopt-retained-state.'
                            if exc.code == 'adoption_required' else None),
                        secrets_included=False))
            return 3
        _reply(result)
        return 0
    except (RequestError, OSError) as exc:
        code = str(exc) if isinstance(exc, RequestError) else 'untrusted_root_launcher'
        if code not in ('invalid_request', 'invalid_trusted_manifest',
                        'untrusted_root_launcher', 'duplicate_key'):
            code = 'invalid_request'
        _reply(dict(status='error', error_code=code, secrets_included=False))
        return 2
    except Exception:
        _reply(dict(status='error', error_code='recovery_required',
                    secrets_included=False))
        return 4


if __name__ == '__main__':
    raise SystemExit(main())
