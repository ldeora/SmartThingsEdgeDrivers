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

import http.client
import json
import re
import uuid
from typing import Callable

MAX_RESPONSE = 16 * 1024
REQUEST_TIMEOUT_SECONDS = 2
_ALLOWED_SERVICE_STATES = frozenset(('active', 'inactive', 'failed', 'activating',
                                     'deactivating', 'unknown'))
_VERSION = re.compile(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9a-z]+(?:\.[0-9]+)?)?\Z')
_FIXED_PATHS = ('/v2/info', '/v2/health')


def valid_port(port: int) -> bool:
    # Privileged low ports are not offered by the existing agent/install
    # templates; fail consistently with the future configurable listener.
    return type(port) is int and 1024 <= port <= 65535


def _uuid(value: object) -> str | None:
    if not isinstance(value, str) or len(value) != 36:
        return None
    try:
        return value if str(uuid.UUID(value)) == value else None
    except (ValueError, AttributeError):
        return None


def _read_json(port: int, path: str, *,
               connection_factory: Callable = http.client.HTTPConnection) -> dict | None:
    if not valid_port(port) or path not in _FIXED_PATHS:
        return None
    # HTTPConnection deliberately does NOT follow redirects or use HTTP proxy
    # environment variables. The host and request paths are fixed literals.
    conn = None
    try:
        conn = connection_factory('127.0.0.1', port, timeout=REQUEST_TIMEOUT_SECONDS)
        conn.request('GET', path, headers={'Accept': 'application/json',
                                          'Connection': 'close'})
        response = conn.getresponse()
        if response.status != 200:
            return None
        content_type = response.getheader('Content-Type', '') or ''
        if not content_type.lower().startswith('application/json'):
            return None
        raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            return None
        obj = json.loads(raw.decode('utf-8'))
        return obj if isinstance(obj, dict) else None
    except (OSError, ValueError, TypeError, UnicodeError, json.JSONDecodeError,
            http.client.HTTPException):
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass


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
    if expected_version is not None and not _VERSION.fullmatch(expected_version):
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
    valid_version = isinstance(version, str) and len(version) <= 40 and bool(_VERSION.fullmatch(version))
    check('agent_version', 'passed' if valid_version else 'failed')
    if expected_version is not None:
        check('expected_version', 'passed' if valid_version and version == expected_version else 'failed')
    else:
        check('expected_version', 'not_verified', required=False)

    features = info.get('features') if isinstance(info, dict) else None
    valid_features = (isinstance(features, list) and len(features) <= 32
                      and all(isinstance(f, str) and len(f) <= 64 for f in features))
    power_enabled = valid_features and 'power-control' in features
    check('power_configuration', 'passed' if valid_features else 'failed')
    if expected_power is not None:
        check('expected_power', 'passed' if valid_features and power_enabled == expected_power else 'failed')
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
        'power_control': ('enabled' if power_enabled else 'disabled') if valid_features else 'unknown',
        'identity_consistent': consistent,
        'identity_preserved': ('passed' if consistent and info_id == expected_identity else 'failed')
                              if expected_identity is not None else 'not_verified',
        'runtime_verified': status == 'passed',
        'secrets_included': False,
    }
