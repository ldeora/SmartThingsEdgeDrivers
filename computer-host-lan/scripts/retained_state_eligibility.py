"""Experimental retained-state file/account eligibility; no adoption authority.

No production caller or mutation. A future caller must hold the shared
installer lock, establish service quiescence and journal eligibility,
and independently obtain explicit v2 provenance/consent. Valid formats
do not establish which protocol created these files.
"""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
import grp
import os
from pathlib import Path
import pwd
import re
import stat
import uuid

import install_core as core

_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_STATE = ('var', 'lib', 'linux-host-agent')
_NAMES = frozenset(('installation-id', 'control-token'))
_SHELLS = frozenset(('/usr/sbin/nologin', '/sbin/nologin',
                    '/usr/bin/nologin', '/bin/false', '/usr/bin/false'))


class AdoptionEligibilityError(ValueError):
    """Fixed codes only; no private path, credential, or account data."""


@dataclass(frozen=True)
class RetainedStateEvidence:
    status: str = 'candidate'
    identity_format: str = 'verified'
    key_format: str = 'verified'
    account_layout: str = 'verified'
    managed_files: str = 'absent'
    ownership_record: str = 'absent'
    protocol_provenance: str = 'not_verified'
    service_state: str = 'not_verified'
    journal_state: str = 'not_verified'
    secrets_included: bool = False


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _trusted_directory(fd, uid):
    info = os.fstat(fd)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or
            stat.S_IMODE(info.st_mode) & 0o7022):
        raise AdoptionEligibilityError('unsafe_parent')


def _parent(root_fd, parts, stack, uid):
    fd = root_fd
    for component in parts:
        try:
            fd = os.open(component, _DIR, dir_fd=fd)
        except FileNotFoundError:
            return None
        stack.callback(os.close, fd)
        _trusted_directory(fd, uid)
    return fd


def _absent(root_fd, parts, uid):
    with ExitStack() as stack:
        fd = _parent(root_fd, parts[:-1], stack, uid)
        if fd is None:
            return
        try:
            os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        raise AdoptionEligibilityError('conflicting_installation')


def _account():
    try:
        user = pwd.getpwnam('linuxhost')
        group = grp.getgrnam('linuxhost')
    except KeyError:
        raise AdoptionEligibilityError('account_unavailable') from None
    if (user.pw_uid <= 0 or user.pw_gid <= 0 or user.pw_gid != group.gr_gid or
            user.pw_name != 'linuxhost' or group.gr_name != 'linuxhost' or
            user.pw_dir != '/var/lib/linux-host-agent' or user.pw_shell not in _SHELLS):
        raise AdoptionEligibilityError('account_layout_unsupported')
    return user.pw_uid, user.pw_gid


def _read_value(directory, name, uid, gid, length):
    fd = os.open(name, _FILE, dir_fd=directory)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                info.st_uid != uid or info.st_gid != gid or
                stat.S_IMODE(info.st_mode) != 0o600 or info.st_size != length + 1):
            raise AdoptionEligibilityError('unsafe_private_file')
        raw = stream.read(length + 2)
        if (len(raw) != length + 1 or not raw.endswith(b'\n') or
                _stamp(info) != _stamp(os.fstat(stream.fileno()))):
            raise AdoptionEligibilityError('private_state_changed')
        return raw[:-1].decode('ascii'), _stamp(info)


def inspect_retained_state(root: Path = Path('/'), *,
                           owner_uid: int = 0) -> RetainedStateEvidence:
    """Inspect strictly shaped orphan state; return no values or digests.

    owner_uid/root overrides support unprivileged fixtures only. A real
    candidate needs existing non-root linuxhost account/group, exactly
    two canonical private files, no owner directory or managed entry.
    No service or protected-journal claim is made.
    """
    root = Path(root)
    if root == Path('/') and (owner_uid != 0 or os.geteuid() != 0):
        raise AdoptionEligibilityError('unsupported_context')
    try:
        uid, gid = _account()
        with ExitStack() as stack:
            root_fd = os.open(root, _DIR)
            stack.callback(os.close, root_fd)
            _trusted_directory(root_fd, owner_uid)
            paths = (*sorted(core.MANAGED_PATHS), core.OWNER_DIR)
            for path in paths:
                _absent(root_fd, Path(path.lstrip('/')).parts, owner_uid)
            parent = _parent(root_fd, _STATE[:-1], stack, owner_uid)
            if parent is None:
                raise AdoptionEligibilityError('retained_state_missing')
            directory = os.open(_STATE[-1], _DIR, dir_fd=parent)
            stack.callback(os.close, directory)
            info = os.fstat(directory)
            if (info.st_uid != uid or info.st_gid != gid or
                    stat.S_IMODE(info.st_mode) != 0o700 or
                    set(os.listdir(directory)) != _NAMES):
                raise AdoptionEligibilityError('unsafe_private_directory')
            identity, identity_stamp = _read_value(
                directory, 'installation-id', uid, gid, 36)
            key, key_stamp = _read_value(directory, 'control-token', uid, gid, 64)
            if str(uuid.UUID(identity)) != identity or not re.fullmatch(r'[0-9a-f]{64}', key):
                raise AdoptionEligibilityError('invalid_private_format')
            # State is agent-owned: verify both names still refer to the
            # inspected objects, and recheck layout before reporting.
            for name, stamp in (('installation-id', identity_stamp),
                                ('control-token', key_stamp)):
                if _stamp(os.stat(name, dir_fd=directory,
                                  follow_symlinks=False)) != stamp:
                    raise AdoptionEligibilityError('private_state_changed')
            if (_stamp(info) != _stamp(os.fstat(directory)) or
                    _stamp(info) != _stamp(os.stat(
                        _STATE[-1], dir_fd=parent, follow_symlinks=False)) or
                    set(os.listdir(directory)) != _NAMES):
                raise AdoptionEligibilityError('private_state_changed')
            for path in paths:
                _absent(root_fd, Path(path.lstrip('/')).parts, owner_uid)
            if _account() != (uid, gid):
                raise AdoptionEligibilityError('account_layout_changed')
            return RetainedStateEvidence()
    except (OSError, UnicodeError, ValueError) as exc:
        if isinstance(exc, AdoptionEligibilityError):
            raise
        raise AdoptionEligibilityError('retained_state_unavailable_or_invalid') from None
