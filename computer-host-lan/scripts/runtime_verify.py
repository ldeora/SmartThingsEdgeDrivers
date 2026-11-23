#!/usr/bin/env python3
"""Bounded, unprivileged runtime verification for the Linux installer.

This is a *read-only probe*, not a privileged install, a proof of hub
connectivity, or a complete attestation of the service's on-disk identity.
Only connect to fixed IPv4 loopback, with two fixed v2 paths. Never print or
serialize the agent's UUID, key, addresses, hostname, raw errors, or headers.

The future transactional engine can call verify_runtime() with an expected
version and an in-memory expected identity obtained from a trusted privileged
snapshot. Neither value is read from private state by this module.
"""
from __future__ import annotations

import errno
import json
import re
import select
import socket
import time
import uuid
from typing import Callable

MAX_RESPONSE = 16 * 1024
MAX_HEADERS = 8 * 1024
REQUEST_DEADLINE_SECONDS = 3.0
_ALLOWED_SERVICE_STATES = frozenset(('active', 'inactive', 'failed', 'activating',
                                     'deactivating', 'unknown'))
_VERSION = re.compile(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9a-z]+(?:\.[0-9]+)?)?\Z')
_FIXED_PATHS = ('/v2/info', '/v2/health')


def valid_port(port: int) -> bool:
    # Privileged low ports are not offered by the existing agent/install
    # templates; fail consistently with the future configurable listener.
    return type(port) is int and 1024 <= port <= 65535


def valid_version(version: str) -> bool:
    return isinstance(version, str) and len(version) <= 40 and bool(_VERSION.fullmatch(version))


def _uuid(value: object) -> str | None:
    if not isinstance(value, str) or len(value) != 36:
        return None
    try:
        return value if str(uuid.UUID(value)) == value else None
    except (ValueError, AttributeError):
        return None


def _parse_http_json(raw: bytes) -> dict | None:
    # The agent explicitly sends Content-Length. Reject redirects, chunking,
    # missing/inconsistent lengths and all other representations. No proxy
    # headers, hostname or server-provided paths are ever followed.
    if not isinstance(raw, bytes) or len(raw) > MAX_HEADERS + MAX_RESPONSE:
        return None
    header, sep, body = raw.partition(b'\r\n\r\n')
    if not sep or len(header) > MAX_HEADERS:
        return None
    lines = header.split(b'\r\n')
    status = lines[0].split(b' ', 2)
    if len(status) < 2 or status[0] not in (b'HTTP/1.0', b'HTTP/1.1') or status[1] != b'200':
        return None
    fields: dict[bytes, bytes] = {}
    for line in lines[1:]:
        if b':' not in line:
            return None
        key, value = line.split(b':', 1)
        key = key.strip().lower()
        if not key or key in fields:
            return None
        fields[key] = value.strip()
    if fields.get(b'content-type', b'').split(b';', 1)[0].strip().lower() != b'application/json':
        return None
    if b'transfer-encoding' in fields or b'content-encoding' in fields:
        return None
    length = fields.get(b'content-length', b'')
    if not length or len(length) > 5 or any(c < 48 or c > 57 for c in length):
        return None
    n = int(length)
    if not 1 <= n <= MAX_RESPONSE or len(body) < n:
        return None
    try:
        value = json.loads(body[:n].decode('utf-8'))
        return value if isinstance(value, dict) else None
    except (ValueError, UnicodeError, TypeError):
        return None


def _exchange(port: int, path: str) -> bytes | None:
    """Send a fixed HTTP request using a nonblocking socket and HARD deadline.

    This avoids a slow-drip endpoint extending a per-recv timeout forever.
    No DNS, proxies, redirected URLs, subprocess or external addresses.
    """
    if not valid_port(port) or path not in _FIXED_PATHS:
        return None
    deadline = time.monotonic() + REQUEST_DEADLINE_SECONDS
    request = (b'GET ' + path.encode('ascii') +
               b' HTTP/1.1\r\nHost: 127.0.0.1\r\nAccept: application/json\r\n'
               b'Connection: close\r\n\r\n')
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setblocking(False)
            result = sock.connect_ex(('127.0.0.1', port))
            if result not in (0, errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY):
                return None
            if result:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([], [sock], [], remaining)[1]:
                    return None
                if sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR) != 0:
                    return None
            view = memoryview(request)
            while view:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([], [sock], [], remaining)[1]:
                    return None
                sent = sock.send(view)
                if sent <= 0:
                    return None
                view = view[sent:]

            response = bytearray()
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                if not select.select([sock], [], [], remaining)[0]:
                    return None
                part = sock.recv(4096)
                if not part:
                    return bytes(response) if _parse_http_json(bytes(response)) is not None else None
                response.extend(part)
                if len(response) > MAX_HEADERS + MAX_RESPONSE:
                    return None
                if _parse_http_json(bytes(response)) is not None:
                    return bytes(response)
            return None
    except (OSError, ValueError, TypeError):
        return None


def _read_json(port: int, path: str, *,
               exchange: Callable[[int, str], bytes | None] = _exchange) -> dict | None:
    if not valid_port(port) or path not in _FIXED_PATHS:
        return None
    try:
        raw = exchange(port, path)
        return _parse_http_json(raw) if raw is not None else None
    except (OSError, ValueError, TypeError):
        return None


def verify_runtime(*, port: int = 8765, expected_version: str | None = None,
                   expected_identity: str | None = None,
                   expected_power: bool | None = None,
                   service_status: str = 'unknown',
                   fetch: Callable[[int, str], dict | None] = _read_json) -> dict:
    """Check the live agent with zero filesystem mutations and no secret I/O.

    Results carry allowlisted states and a sanitized agent version only. An
    expected_identity is an internal comparison input, NEVER a CLI argument.
    When the service is intentionally stopped, the transaction engine should
    skip this running-agent check and verify installed files/unit state
    separately rather than requiring a restart.
    """
    if not valid_port(port):
        raise ValueError('port must be 1024..65535')
    if expected_version is not None and not valid_version(expected_version):
        raise ValueError('invalid expected agent version')
    if expected_identity is not None and _uuid(expected_identity) is None:
        raise ValueError('invalid expected identity')
    if expected_power is not None and type(expected_power) is not bool:
        raise ValueError('expected_power must be bool or None')
    if service_status not in _ALLOWED_SERVICE_STATES:
        raise ValueError('invalid service state')

    info = fetch(port, '/v2/info')
    health = fetch(port, '/v2/health')
    checks = []
    failed = False
    not_verified = False

    def check(name: str, state: str, *, required: bool = True) -> None:
        nonlocal failed, not_verified
        checks.append({'id': name, 'status': state})
        if required:
            failed |= state == 'failed'
            not_verified |= state == 'not_verified'

    check('systemd_agent_active', 'passed' if service_status == 'active' else
          'not_verified' if service_status == 'unknown' else 'failed')
    check('info_responding', 'passed' if info is not None else 'failed')
    check('health_responding', 'passed' if health is not None else 'failed')

    info_ok = (isinstance(info, dict)
               and info.get('protocol') == 'computer-host-agent'
               and type(info.get('api_version')) is int and info['api_version'] == 2
               and info.get('platform') == 'linux')
    health_ok = (isinstance(health, dict)
                 and health.get('protocol') == 'computer-host-agent'
                 and type(health.get('api_version')) is int and health['api_version'] == 2
                 and health.get('platform') == 'linux'
                 and health.get('status') == 'running')
    check('v2_linux_protocol', 'passed' if info_ok and health_ok else 'failed')

    info_id = _uuid(info.get('id')) if isinstance(info, dict) else None
    health_id = _uuid(health.get('id')) if isinstance(health, dict) else None
    consistent = bool(info_id and health_id and info_id == health_id)
    check('identity_consistent', 'passed' if consistent else 'failed')
    if expected_identity is not None:
        check('identity_preserved',
              'passed' if consistent and info_id == expected_identity else 'failed')
    else:
        check('identity_preserved', 'not_verified', required=False)

    version = info.get('agent_version') if isinstance(info, dict) else None
    version_valid = valid_version(version)
    check('agent_version', 'passed' if version_valid else 'failed')
    if expected_version is not None:
        check('expected_version', 'passed' if version_valid and version == expected_version else 'failed')
    else:
        check('expected_version', 'not_verified', required=False)

    features = info.get('features') if isinstance(info, dict) else None
    valid_features = (isinstance(features, list) and len(features) <= 32
                      and all(isinstance(f, str) and len(f) <= 64 for f in features))
    power_enabled = valid_features and 'power-control' in features
    actions = info.get('power_actions') if isinstance(info, dict) else None
    expected_actions = ['reboot', 'shutdown', 'suspend'] if power_enabled else []
    valid_configuration = valid_features and isinstance(actions, list) and actions == expected_actions
    check('power_configuration', 'passed' if valid_configuration else 'failed')
    if expected_power is not None:
        check('expected_power', 'passed' if valid_configuration and power_enabled == expected_power else 'failed')
    else:
        check('expected_power', 'not_verified', required=False)

    status = 'failed' if failed else 'not_verified' if not_verified else 'passed'
    return {
        'schema_version': 1,
        'operation': 'verify',
        'mode': 'read_only',
        'status': status,
        'checks': checks,
        'agent_version': version if valid_version else None,
        'power_control': ('enabled' if power_enabled else 'disabled') if valid_configuration else 'unknown',
        'identity_consistent': consistent,
        'identity_preserved': ('passed' if consistent and info_id == expected_identity else 'failed')
                              if expected_identity is not None else 'not_verified',
        'runtime_verified': status == 'passed',
        'secrets_included': False,
    }
