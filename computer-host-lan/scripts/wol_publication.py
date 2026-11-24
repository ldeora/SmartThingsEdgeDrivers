#!/usr/bin/env python3
"""Development-only WOL publication primitives; no CLI or installer caller.

Operate on already opened directories, never user-supplied target paths.
The future protected controller must validate the actual policy, bind
consent, hold the shared lock and durably record APPLYING before use.
This module does not grant that authority or implement journal cleanup.
"""
from __future__ import annotations

import json
import os
import re
import stat

TARGET = '90-computer-host-wol.conf'
CONTENT = b'[Link]\nWakeOnLan=magic\n'
_TXID = re.compile(r'[0-9a-f]{32}\Z')
_LIMIT = 2048
_READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_CREATE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC


class PublicationError(RuntimeError):
    """Fixed errors, no paths, identifiers or policy contents."""


def _names(txid: str) -> tuple[str, str]:
    if not isinstance(txid, str) or not _TXID.fullmatch(txid):
        raise PublicationError('invalid transaction reference')
    return '.computer-host-wol-' + txid + '.stage', 'wol-' + txid + '.json'


def _directory(fd: int, uid: int, *, private: bool = False) -> os.stat_result:
    info = os.fstat(fd)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or
            stat.S_IMODE(info.st_mode) & (0o077 if private else 0o022)):
        raise PublicationError('unsafe publication directory')
    return info


def _identity(info: os.stat_result) -> list[int]:
    return [info.st_dev, info.st_ino]


def _check_file(info: os.stat_result, uid: int, mode: int,
                links: tuple[int, ...]) -> None:
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != uid or
            stat.S_IMODE(info.st_mode) != mode or info.st_nlink not in links):
        raise PublicationError('unsafe publication file')


def _read(fd: int, name: str, uid: int, mode: int, links: tuple[int, ...],
          limit: int) -> tuple[bytes, os.stat_result]:
    with os.fdopen(os.open(name, _READ, dir_fd=fd), 'rb') as stream:
        before = os.fstat(stream.fileno())
        _check_file(before, uid, mode, links)
        if before.st_size > limit:
            raise PublicationError('oversized publication file')
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        _check_file(after, uid, mode, links)
        if (len(data) > limit or len(data) != after.st_size or
                (before.st_size, before.st_mtime_ns, before.st_ctime_ns,
                 before.st_nlink) !=
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_nlink)):
            raise PublicationError('publication file changed during read')
    visible = os.stat(name, dir_fd=fd, follow_symlinks=False)
    _check_file(visible, uid, mode, links)
    if (_identity(visible) != _identity(after) or
            visible.st_ctime_ns != after.st_ctime_ns):
        raise PublicationError('publication file replaced during read')
    return data, after


def _entry(fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _write_new(fd: int, name: str, data: bytes, mode: int,
               uid: int) -> os.stat_result:
    # Never clean up on an uncertain write. An interrupted initial write
    # can leave a partial anchor or receipt; no target was published.
    with os.fdopen(os.open(name, _CREATE, 0o600, dir_fd=fd), 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fchmod(stream.fileno(), mode)
        info = os.fstat(stream.fileno())
        _check_file(info, uid, mode, (1,))
        os.fsync(stream.fileno())
    os.fsync(fd)
    return info


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate receipt field')
        result[key] = value
    return result


def _valid_identity(value: object) -> bool:
    return (type(value) is list and len(value) == 2 and
            all(type(n) is int and 0 <= n <= 2**64 - 1 for n in value) and
            value[1] > 0)


def _receipt(policy_fd: int, private_fd: int, txid: str, uid: int) -> dict:
    _, name = _names(txid)
    policy = _directory(policy_fd, uid)
    private = _directory(private_fd, uid, private=True)
    if _identity(policy) == _identity(private):
        raise PublicationError('publication directories overlap')
    raw, _ = _read(private_fd, name, uid, 0o600, (1,), _LIMIT)
    try:
        record = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique)
    except (UnicodeError, ValueError, RecursionError):
        raise PublicationError('invalid publication receipt') from None
    if (type(record) is not dict or set(record) != {
            'schema', 'transaction_id', 'policy_directory', 'private_directory',
            'anchor', 'anchor_gid', 'anchor_mtime_ns', 'target_before'} or
            type(record['schema']) is not int or record['schema'] != 1 or
            record['transaction_id'] != txid or
            any(not _valid_identity(record[k]) for k in
                ('policy_directory', 'private_directory', 'anchor')) or
            type(record['anchor_gid']) is not int or
            not 0 <= record['anchor_gid'] <= 2**32 - 1 or
            type(record['anchor_mtime_ns']) is not int or
            not 0 <= record['anchor_mtime_ns'] <= 2**63 - 1 or
            record['target_before'] != 'absent'):
        raise PublicationError('invalid publication receipt')
    if (record['policy_directory'] != _identity(policy) or
            record['private_directory'] != _identity(private)):
        raise PublicationError('publication directory identity changed')
    return record


def _state(policy_fd: int, private_fd: int, txid: str, uid: int) -> str:
    anchor, _ = _names(txid)
    record = _receipt(policy_fd, private_fd, txid, uid)
    data, info = _read(policy_fd, anchor, uid, 0o644, (1, 2), len(CONTENT))
    if (data != CONTENT or record['anchor'] != _identity(info) or
            info.st_gid != record['anchor_gid'] or
            info.st_mtime_ns != record['anchor_mtime_ns']):
        raise PublicationError('publication anchor changed')
    target = _entry(policy_fd, TARGET)
    if target is None:
        if info.st_nlink != 1:
            raise PublicationError('unexpected publication links')
        return 'unpublished'
    _check_file(target, uid, 0o644, (2,))
    if (_identity(target) != _identity(info) or info.st_nlink != 2 or
            target.st_gid != info.st_gid or target.st_ctime_ns != info.st_ctime_ns):
        raise PublicationError('publication target not owned')
    return 'published'


def prepare(policy_fd: int, private_fd: int, txid: str, *, owner_uid: int = 0) -> None:
    """Create a durable hidden anchor and private before-state receipt.

    Caller already verified the scope, absence of conflicting policy and
    explicit consent, and recorded APPLYING. Neither name is overwritten.
    The existing policy directory is never created or removed here.
    """
    anchor, receipt = _names(txid)
    policy = _directory(policy_fd, owner_uid)
    private = _directory(private_fd, owner_uid, private=True)
    if _identity(policy) == _identity(private):
        raise PublicationError('publication directories overlap')
    if (_entry(policy_fd, TARGET) is not None or
            _entry(policy_fd, anchor) is not None or
            _entry(private_fd, receipt) is not None):
        raise PublicationError('publication already exists')
    info = _write_new(policy_fd, anchor, CONTENT, 0o644, owner_uid)
    record = dict(schema=1, transaction_id=txid,
                  policy_directory=_identity(policy),
                  private_directory=_identity(private),
                  anchor=_identity(info), anchor_gid=info.st_gid,
                  anchor_mtime_ns=info.st_mtime_ns, target_before='absent')
    raw = (json.dumps(record, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')
    _write_new(private_fd, receipt, raw, 0o600, owner_uid)
    if _state(policy_fd, private_fd, txid, owner_uid) != 'unpublished':
        raise PublicationError('unexpected publication state')


def inspect(policy_fd: int, private_fd: int, txid: str, *, owner_uid: int = 0) -> str:
    """Return a fixed state or raise. Never infer ownership from bytes alone."""
    return _state(policy_fd, private_fd, txid, owner_uid)


def _sync_effect(policy_fd: int, private_fd: int, txid: str, uid: int,
                 expected: str) -> None:
    if _state(policy_fd, private_fd, txid, uid) != expected:
        raise PublicationError('publication effect not verified')
    anchor, _ = _names(txid)
    record = _receipt(policy_fd, private_fd, txid, uid)
    fd = os.open(anchor, _READ, dir_fd=policy_fd)
    try:
        info = os.fstat(fd)
        _check_file(info, uid, 0o644, (2,) if expected == 'published' else (1,))
        if _identity(info) != record['anchor']:
            raise PublicationError('publication anchor changed before sync')
        os.fsync(fd)
    finally:
        os.close(fd)
    os.fsync(policy_fd)
    if _state(policy_fd, private_fd, txid, uid) != expected:
        raise PublicationError('publication effect not verified')


def publish(policy_fd: int, private_fd: int, txid: str, *, owner_uid: int = 0) -> None:
    """Atomically add only the fixed target; never replace another entry.

    Only call after prepare returned successfully, within the same
    authorized APPLYING operation. Never resume forward from an uncertain
    prepare. A failure after link() may mean publication happened; the retained
    anchor and receipt allow a fresh inspection. Recovery must roll back,
    not call publish again to complete an interrupted transaction.
    """
    anchor, _ = _names(txid)
    if _state(policy_fd, private_fd, txid, owner_uid) != 'unpublished':
        raise PublicationError('publication already applied')
    os.link(anchor, TARGET, src_dir_fd=policy_fd, dst_dir_fd=policy_fd,
            follow_symlinks=False)
    _sync_effect(policy_fd, private_fd, txid, owner_uid, 'published')


def rollback(policy_fd: int, private_fd: int, txid: str, *, owner_uid: int = 0) -> None:
    """Undo only the anchored target. Keep all evidence for the controller.

    This is not an atomic compare-and-unlink against arbitrary root
    writers. A future controller must hold its exclusion lock and verify
    the live directory binding and policy. Concurrent privileged policy
    writers that ignore the lock are outside this primitive's guarantee.
    """
    if _state(policy_fd, private_fd, txid, owner_uid) == 'published':
        # Recheck immediately before unlink; a hostile root writer is
        # outside the protection boundary, as with other installer writes.
        if _state(policy_fd, private_fd, txid, owner_uid) != 'published':
            raise PublicationError('publication changed before rollback')
        os.unlink(TARGET, dir_fd=policy_fd)
    _sync_effect(policy_fd, private_fd, txid, owner_uid, 'unpublished')
