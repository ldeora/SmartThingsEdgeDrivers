"""Experimental read-only historical snapshot candidate inspection.

No production caller, CLI, journal changes, restore, or signing authority.
The caller must independently authenticate expected manifest/file digests
and version, establish protected-engine provenance and hold the shared
installer lock for any future use. Computing expectations from the same
snapshot is not authentication. This module cannot authorize a restore.
"""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import stat

import install_core as core

_NAME = re.compile(r'snapshot-[A-Za-z0-9_-]{6,64}\Z')
_HASH = re.compile(r'[0-9a-f]{64}\Z')
_VERSION = re.compile(r'[A-Za-z0-9.+_-]{1,64}\Z')
_VERSION_LINE = re.compile(rb'''(?m)^VERSION\s*=\s*["']([A-Za-z0-9.+_-]{1,64})["']\s*$''')
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_MAX_FILE = 2 * 1024 * 1024
_MAX_TOTAL = 8 * 1024 * 1024
_REQUIRED = frozenset((*core.APP_FILES, *core.SYSTEMD_PATHS))
_PREVIOUS = frozenset(('first_install', 'agent_active', 'agent_enabled',
                       'socket_active', 'socket_enabled'))


class SnapshotEligibilityError(ValueError):
    """Fixed diagnostics only; never relay paths, contents or private data."""


@dataclass(frozen=True)
class CandidateFile:
    path: str
    content: bytes | None = field(repr=False)
    mode: int | None = None
    uid: int | None = None
    gid: int | None = None


@dataclass(frozen=True)
class SnapshotCandidate:
    """Pinned immutable evidence, NOT authority to execute historical code."""
    agent_version: str
    files: tuple[CandidateFile, ...]
    service_state: tuple[tuple[str, bool], ...]


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SnapshotEligibilityError('duplicate_manifest_key')
        result[key] = value
    return result


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _directory(fd, uid, *, private=False):
    info = os.fstat(fd)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or
            stat.S_IMODE(info.st_mode) & (0o077 if private else 0o022)):
        raise SnapshotEligibilityError('unsafe_snapshot_directory')
    return info


def _read(fd, name, uid, limit, *, private=False):
    item = os.open(name, _FILE_FLAGS, dir_fd=fd)
    with os.fdopen(item, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or
                before.st_uid != uid or before.st_size > limit or
                stat.S_IMODE(before.st_mode) & (0o7077 if private else 0o7022)):
            raise SnapshotEligibilityError('unsafe_snapshot_file')
        content = stream.read(limit + 1)
        if (len(content) != before.st_size or len(content) > limit or
                _stamp(before) != _stamp(os.fstat(stream.fileno()))):
            raise SnapshotEligibilityError('snapshot_changed')
    return content, before


def inspect_candidate(root: Path, name: str, *,
                      expected_manifest_sha256: str,
                      expected_file_hashes: dict[str, str],
                      expected_agent_version: str,
                      owner_uid: int = 0, owner_gid: int = 0) -> SnapshotCandidate:
    """Validate a conservative complete installed-state schema-1 candidate.

    Existing schema-1 snapshots alone cannot establish provenance. These
    expected values must come from an independently trusted source; no
    such production source or restore caller is implemented. Reject partial
    plans, empty installs, normalized broken service states and arbitrary
    metadata. Return bytes read through pinned descriptors, never paths to
    reread later. Fixture owner/root overrides are not production inputs.
    """
    root = Path(root)
    if (root == Path('/') and (owner_uid != 0 or owner_gid != 0) or
            type(name) is not str or not _NAME.fullmatch(name) or
            type(expected_manifest_sha256) is not str or
            not _HASH.fullmatch(expected_manifest_sha256) or
            type(expected_agent_version) is not str or
            not _VERSION.fullmatch(expected_agent_version) or
            type(expected_file_hashes) is not dict or
            not set(expected_file_hashes).issubset(core.MANAGED_PATHS) or
            any(type(value) is not str or not _HASH.fullmatch(value)
                for value in expected_file_hashes.values())):
        raise SnapshotEligibilityError('invalid_candidate_expectation')

    try:
        with ExitStack() as stack:
            fd = os.open(root, _DIR_FLAGS)
            stack.callback(os.close, fd)
            _directory(fd, owner_uid)
            parts = Path(core.BACKUP_BASE.lstrip('/')).parts + (name,)
            for index, component in enumerate(parts):
                fd = os.open(component, _DIR_FLAGS, dir_fd=fd)
                stack.callback(os.close, fd)
                _directory(fd, owner_uid, private=index >= len(parts) - 2)
            before = _stamp(os.fstat(fd))
            raw, _ = _read(fd, 'manifest.json', owner_uid,
                           core.MAX_BACKUP_MANIFEST_BYTES, private=True)
            if hashlib.sha256(raw).hexdigest() != expected_manifest_sha256:
                raise SnapshotEligibilityError('manifest_digest_mismatch')
            data = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique)
            if (type(data) is not dict or
                    set(data) != {'schema', 'installer_protocol', 'items', 'previous'} or
                    type(data['schema']) is not int or data['schema'] != 1 or
                    data['installer_protocol'] != 'v2' or
                    type(data['items']) is not list or
                    len(data['items']) != len(core.MANAGED_PATHS)):
                raise SnapshotEligibilityError('unsupported_snapshot_manifest')
            previous = data['previous']
            if (type(previous) is not dict or not _PREVIOUS.issubset(previous) or
                    not set(previous).issubset(_PREVIOUS | {'newly_enabled_power'}) or
                    any(type(value) is not bool for value in previous.values()) or
                    previous['first_install']):
                raise SnapshotEligibilityError('unsupported_service_state')
            seen = set()
            present = set()
            entries = {'manifest.json'}
            files = []
            total = 0
            for index, record in enumerate(data['items']):
                if (type(record) is not dict or type(record.get('path')) is not str or
                        record['path'] not in core.MANAGED_PATHS or
                        record['path'] in seen or type(record.get('existed')) is not bool):
                    raise SnapshotEligibilityError('invalid_snapshot_item')
                path = record['path']
                seen.add(path)
                if not record['existed']:
                    if set(record) != {'path', 'existed'} or path in _REQUIRED:
                        raise SnapshotEligibilityError('unsupported_absent_item')
                    files.append(CandidateFile(path, None))
                    continue
                filename = f'{index}.original'
                mode = 0o755 if path in core.APP_FILES else 0o644
                if (set(record) != {'path', 'existed', 'file', 'mode', 'uid', 'gid'} or
                        record['file'] != filename or
                        type(record['mode']) is not int or record['mode'] != mode or
                        type(record['uid']) is not int or record['uid'] != owner_uid or
                        type(record['gid']) is not int or record['gid'] != owner_gid):
                    raise SnapshotEligibilityError('invalid_snapshot_metadata')
                content, info = _read(fd, filename, owner_uid, _MAX_FILE)
                total += len(content)
                if (total > _MAX_TOTAL or not content or
                        stat.S_IMODE(info.st_mode) != mode or info.st_gid != owner_gid or
                        hashlib.sha256(content).hexdigest() != expected_file_hashes.get(path)):
                    raise SnapshotEligibilityError('item_digest_or_metadata_mismatch')
                if path == core.APP_FILES[0]:
                    versions = _VERSION_LINE.findall(content)
                    if (core.PROTOCOL_MARKER.findall(content) != [b'computer-host-agent'] or
                            versions != [expected_agent_version.encode('ascii')]):
                        raise SnapshotEligibilityError('unsupported_agent_version')
                if path == core.AVAHI_PATH and (
                        b'_computerhost._tcp' not in content or b'_linuxhost._tcp' in content):
                    raise SnapshotEligibilityError('unsupported_avahi_service')
                present.add(path)
                entries.add(filename)
                files.append(CandidateFile(path, content, mode, owner_uid, owner_gid))
            if (seen != core.MANAGED_PATHS or present != set(expected_file_hashes) or
                    set(os.listdir(fd)) != entries or before != _stamp(os.fstat(fd))):
                raise SnapshotEligibilityError('snapshot_entry_mismatch')
            if ((previous['socket_active'] or previous['socket_enabled']) and
                    core.POWER_DROPIN not in present):
                raise SnapshotEligibilityError('inconsistent_service_state')
            return SnapshotCandidate(expected_agent_version, tuple(files),
                                     tuple(sorted(previous.items())))
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, SnapshotEligibilityError):
            raise
        raise SnapshotEligibilityError('snapshot_unavailable_or_invalid') from None


def inspect_protected_candidate(root: Path, name: str, *,
                                expected_file_hashes: dict[str, str],
                                expected_agent_version: str,
                                owner_uid: int = 0, owner_gid: int = 0) -> SnapshotCandidate:
    """Require protected capture evidence AND independent installed-byte expectations.

    The local receipt identifies the protected writer under the trusted-root
    threat model, not the publisher of the historical executable. The
    caller must independently establish version compatibility and expected
    hashes of rendered managed files, not just upstream source hashes.
    No production caller; no authorization to restore.
    """
    root = Path(root)
    if (root == Path('/') and (owner_uid != 0 or owner_gid != 0 or os.geteuid() != 0) or
            type(name) is not str or not _NAME.fullmatch(name)):
        raise SnapshotEligibilityError('invalid_candidate_expectation')
    try:
        with ExitStack() as stack:
            fd = os.open(root, _DIR_FLAGS)
            stack.callback(os.close, fd)
            _directory(fd, owner_uid)
            parts = Path(core.BACKUP_BASE.lstrip('/')).parts
            for index, component in enumerate(parts):
                fd = os.open(component, _DIR_FLAGS, dir_fd=fd)
                stack.callback(os.close, fd)
                _directory(fd, owner_uid, private=index == len(parts) - 1)
            receipt_name = '.' + name + '.protected.json'
            raw, info = _read(fd, receipt_name, owner_uid,
                              core.MAX_BACKUP_MANIFEST_BYTES, private=True)
            receipt = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique)
            keys = {'schema_version', 'origin', 'snapshot_name', 'transaction_id',
                    'operation', 'capture_phase', 'manifest_sha256', 'file_sha256',
                    'coverage', 'captured_paths', 'agent_version',
                    'service_observation', 'previous', 'release_authenticity'}
            if (type(receipt) is not dict or set(receipt) != keys or
                    type(receipt['schema_version']) is not int or receipt['schema_version'] != 1 or
                    receipt['origin'] != 'protected_before_state' or
                    receipt['snapshot_name'] != name or
                    type(receipt['transaction_id']) is not str or
                    not re.fullmatch(r'[0-9a-f]{32}', receipt['transaction_id']) or
                    receipt['operation'] not in ('upgrade', 'repair', 'uninstall') or
                    receipt['capture_phase'] != 'STAGED' or
                    receipt['coverage'] != 'complete' or
                    receipt['captured_paths'] != sorted(core.MANAGED_PATHS) or
                    receipt['agent_version'] != expected_agent_version or
                    receipt['service_observation'] != 'protected_capture_previous' or
                    receipt['release_authenticity'] != 'not_verified' or
                    receipt['file_sha256'] != expected_file_hashes or
                    type(receipt['previous']) is not dict or
                    any(type(value) is not bool for value in receipt['previous'].values())):
                raise SnapshotEligibilityError('protected_receipt_ineligible')
            candidate = inspect_candidate(
                root, name, expected_manifest_sha256=receipt['manifest_sha256'],
                expected_file_hashes=expected_file_hashes,
                expected_agent_version=expected_agent_version,
                owner_uid=owner_uid, owner_gid=owner_gid)
            if (dict(candidate.service_state) != receipt['previous'] or
                    _stamp(info) != _stamp(os.stat(
                        receipt_name, dir_fd=fd, follow_symlinks=False))):
                raise SnapshotEligibilityError('protected_receipt_mismatch')
            return candidate
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, SnapshotEligibilityError):
            raise
        raise SnapshotEligibilityError('protected_receipt_unavailable_or_invalid') from None
