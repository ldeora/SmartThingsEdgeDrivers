"""Retained-state file/account eligibility; no independent adoption authority.

No mutation. The protected caller must hold the shared
installer lock, establish service quiescence and journal eligibility,
and independently obtain explicit v2 provenance/consent. Valid formats
do not establish which protocol created these files.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, replace
import grp
import json
import os
from pathlib import Path
import pwd
import re
import stat
import uuid

import install_core as core
import installer_transaction as engine
import transaction_journal as journal

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


def _require_empty_journal(root: Path, owner_uid: int) -> None:
    """Stricter than public status: even a terminal record needs cleanup.

    Caller holds the shared installer lock. No journal/stage creation or
    cleanup; the existing journal lock, if any, is taken read-only.
    """
    try:
        with ExitStack() as stack:
            directory = journal._open_directory(root, owner_uid, create=False)
            if directory is not None:
                stack.callback(os.close, directory)
                lock = journal._open_lock(directory, owner_uid,
                                          create=False, read_only=True)
                if lock is not None:
                    stack.callback(os.close, lock)
                    journal._take_lock(lock, shared=True)
                # No unknown directory contents or terminal leftovers.
                fresh = os.open('.', _DIR, dir_fd=directory)
                stack.callback(os.close, fresh)
                if set(os.listdir(fresh)) - {'lock'}:
                    raise AdoptionEligibilityError('journal_not_empty')
            if journal._staged_payload_remains(root, owner_uid):
                raise AdoptionEligibilityError('journal_not_empty')
    except (OSError, journal.JournalError):
        raise AdoptionEligibilityError('journal_unavailable') from None


@contextmanager
def adoption_candidate(*, root: Path = Path('/'), owner_uid: int = 0,
                       manual_lock_path: Path = engine._MANUAL_LOCK,
                       services=None):
    """Yield momentary orphan/environment evidence while holding the flock.

    This is an experimental inspection boundary, not adoption authorization.
    May initialize the normal shared lock file; no other managed mutation.
    Real-host service queries cannot be overridden. A fixture may inject a
    fake service boundary only with a disposable root. No journal writes,
    account changes, service stops, or credential output. The caller must
    still independently establish v2 provenance and explicit consent.
    """
    root = Path(root)
    manual_lock_path = Path(manual_lock_path)
    if (not root.is_absolute() or '..' in root.parts or
            owner_uid != os.geteuid() or
            manual_lock_path != root / engine._MANUAL_LOCK.relative_to('/') or
            (root == Path('/') and (owner_uid != 0 or services is not None)) or
            (root != Path('/') and services is None)):
        raise AdoptionEligibilityError('unsupported_context')
    if services is None:
        services = engine.SystemdOperations()

    def require_quiescence():
        if (services.verify_uninstall_services() is not True or
                not engine._enablement_absent(core.InstallTransaction(root))):
            raise AdoptionEligibilityError('service_state_unconfirmed')

    with ExitStack() as stack:
        try:
            stack.enter_context(engine.manual_install_lock(
                manual_lock_path, owner_uid=owner_uid))
            _require_empty_journal(root, owner_uid)
            require_quiescence()
            evidence = inspect_retained_state(root, owner_uid=owner_uid)
            require_quiescence()
            _require_empty_journal(root, owner_uid)
        except engine.ControllerError:
            raise AdoptionEligibilityError(
                'installer_lock_or_environment_unavailable') from None
        yield replace(evidence, service_state='verified', journal_state='verified')


def require_v2_uninstall_evidence(root: Path, *, owner_uid: int) -> None:
    """Corroborate legacy v2 protocol with a complete private snapshot.

    The operator confirms ownership; the snapshot contains no credentials
    and cannot prove which UUID/token belongs to the backed-up agent.
    Nothing from the backup is restored or executed here.
    """
    base = root / core.BACKUP_BASE.lstrip('/')
    try:
        for path in (base, *base.parents):
            if path != root and root not in path.parents:
                continue
            info = path.lstat()
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != owner_uid
                    or info.st_mode & 0o022):
                raise AdoptionEligibilityError('unsafe_backup_parent')
        if base.stat().st_mode & 0o077:
            raise AdoptionEligibilityError('unsafe_backup_directory')
        candidates = sorted(base.iterdir(), key=lambda p: p.name)
        if len(candidates) > 1024:
            raise AdoptionEligibilityError('backup_review_required')
        for snapshot in candidates:
            if not snapshot.name.startswith('snapshot-'):
                continue
            try:
                info = snapshot.lstat()
                if (not stat.S_ISDIR(info.st_mode) or info.st_uid != owner_uid
                        or info.st_mode & 0o077):
                    continue
                manifest = snapshot / 'manifest.json'
                info = manifest.lstat()
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != owner_uid
                        or info.st_nlink != 1 or info.st_mode & 0o077):
                    continue
                data = json.loads(core._read_backup_file(
                    manifest, core.MAX_BACKUP_MANIFEST_BYTES))
                if (type(data) is not dict or set(data) != {'schema', 'items', 'previous'}
                        or type(data['schema']) is not int or data['schema'] != 1
                        or type(data['items']) is not list
                        or len(data['items']) != len(core.MANAGED_PATHS)
                        or type(data['previous']) is not dict
                        or data['previous'].get('first_install') is not False):
                    continue
                paths = set()
                expected = {'manifest.json'}
                agent_present = unit_present = False
                for index, item in enumerate(data['items']):
                    if (type(item) is not dict or item.get('path') not in core.MANAGED_PATHS
                            or item['path'] in paths or type(item.get('existed')) is not bool):
                        raise ValueError()
                    paths.add(item['path'])
                    if item['existed']:
                        name = f'{index}.original'
                        if item.get('file') != name:
                            raise ValueError()
                        info = (snapshot / name).lstat()
                        if (not stat.S_ISREG(info.st_mode) or info.st_uid != owner_uid
                                or info.st_nlink != 1 or info.st_mode & 0o022):
                            raise ValueError()
                        expected.add(name)
                        agent_present |= item['path'] == core.APP_FILES[0]
                        unit_present |= item['path'] == core.SYSTEMD_PATHS[0]
                if (paths != core.MANAGED_PATHS or not agent_present or not unit_present
                        or {p.name for p in snapshot.iterdir()} != expected):
                    continue
                core.validate_v2_backup(snapshot, root=root)
                return
            except (OSError, ValueError, TypeError, core.InstallError):
                continue
    except (OSError, core.InstallError):
        pass
    raise AdoptionEligibilityError('v2_backup_evidence_unavailable')
