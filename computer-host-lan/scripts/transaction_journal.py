#!/usr/bin/env python3
"""Private durable wizard journal primitives; NOT a privileged CLI or installer.

This module is deliberately unused by the production install/upgrade scripts.
Only trusted root-side code may call it in a future, reviewed transaction.
Never launch this file with sudo from a user-writable source checkout.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import stat

# Production calls always use root='/' and uid=0. Fixture injection is for tests.
_COMPONENTS = ('var', 'backups', 'linux-host-agent', 'wizard-transactions')
_JOURNAL = 'journal.json'
_LOCK = 'lock'
_TEMP_PREFIX = '.wizard-journal-'
_MAX_BYTES = 2048
_PHASES = ('INSPECTED', 'STAGED', 'SNAPSHOTTED', 'APPLYING',
           'ACTIVATING', 'VERIFYING', 'COMMITTED')
_OPERATIONS = frozenset(('install', 'upgrade', 'repair', 'uninstall'))
_SNAPSHOT = re.compile(r'snapshot-[A-Za-z0-9_-]{6,64}\Z')
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class JournalError(RuntimeError):
    """A static, non-sensitive journal failure."""


class UnsafeJournal(JournalError):
    pass


class JournalConflict(JournalError):
    pass


def _no_duplicates(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate field')
        value[key] = item
    return value


def _validate(data: object) -> dict:
    if not isinstance(data, dict) or set(data) != {
        'schema', 'operation', 'phase', 'snapshot_name'
    }:
        raise UnsafeJournal('invalid journal structure')
    if type(data['schema']) is not int or data['schema'] != 1:
        raise UnsafeJournal('unsupported journal schema')
    if data['operation'] not in _OPERATIONS or data['phase'] not in _PHASES:
        raise UnsafeJournal('invalid journal values')
    snapshot = data['snapshot_name']
    if snapshot is not None and (
        not isinstance(snapshot, str) or not _SNAPSHOT.fullmatch(snapshot)
    ):
        raise UnsafeJournal('invalid snapshot reference')
    if (_PHASES.index(data['phase']) >= _PHASES.index('SNAPSHOTTED')) != (snapshot is not None):
        raise UnsafeJournal('missing or unexpected snapshot reference')
    return data


class ProtectedJournal:
    """Root-owned, no-follow, fsynced state machine; does not execute installs.

    root/owner_uid are injectable solely for filesystem-only tests. Callers
    must NOT expose them as CLI arguments or derive them from wizard input.
    The journal stores a validated snapshot BASENAME, never an arbitrary path.
    No token, UUID, hub address, user input or environment is stored.
    """

    def __init__(self, *, root: Path = Path('/'), owner_uid: int = 0):
        self.root = Path(root)
        self.owner_uid = owner_uid

    @staticmethod
    def _check_regular(fd: int, uid: int) -> None:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != uid or
                info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077):
            raise UnsafeJournal('unsafe private journal file')

    @contextmanager
    def _directory(self, *, create: bool):
        """Traverse fixed components relative to a trusted directory fd."""
        fd = None
        try:
            fd = os.open(self.root, _DIR_FLAGS)
            base = os.fstat(fd)
            if (not stat.S_ISDIR(base.st_mode) or base.st_uid != self.owner_uid or
                    stat.S_IMODE(base.st_mode) & 0o022):
                raise UnsafeJournal('unsafe journal root')
            for index, component in enumerate(_COMPONENTS):
                try:
                    child = os.open(component, _DIR_FLAGS, dir_fd=fd)
                except FileNotFoundError:
                    if not create:
                        yield None
                        return
                    os.mkdir(component, 0o700, dir_fd=fd)
                    os.fsync(fd)
                    child = os.open(component, _DIR_FLAGS, dir_fd=fd)
                info = os.fstat(child)
                private = index >= 2
                if (not stat.S_ISDIR(info.st_mode) or
                        info.st_uid != self.owner_uid or
                        stat.S_IMODE(info.st_mode) & (0o077 if private else 0o022)):
                    os.close(child)
                    raise UnsafeJournal('unsafe journal directory')
                os.close(fd)
                fd = child
            yield fd
        except OSError:
            raise UnsafeJournal('journal filesystem cannot be trusted') from None
        finally:
            if fd is not None:
                os.close(fd)

    @staticmethod
    def _leftovers(directory: int) -> bool:
        # A crash between writing and renaming a temporary file is visible.
        return any(name.startswith(_TEMP_PREFIX) for name in os.listdir(directory))

    def _read(self, directory: int) -> dict | None:
        try:
            fd = os.open(_JOURNAL, _FILE_FLAGS, dir_fd=directory)
        except FileNotFoundError:
            return None
        try:
            self._check_regular(fd, self.owner_uid)
            content = os.read(fd, _MAX_BYTES + 1)
            if not content or len(content) > _MAX_BYTES:
                raise UnsafeJournal('invalid journal length')
            return _validate(json.loads(content.decode('utf-8'),
                                        object_pairs_hook=_no_duplicates))
        except (ValueError, UnicodeError, TypeError):
            raise UnsafeJournal('invalid journal encoding') from None
        finally:
            os.close(fd)

    @contextmanager
    def _exclusive(self, directory: int):
        fd = os.open(_LOCK, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=directory)
        try:
            self._check_regular(fd, self.owner_uid)
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    @staticmethod
    def _write(directory: int, data: dict) -> None:
        encoded = (json.dumps(data, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')
        if len(encoded) > _MAX_BYTES:
            raise UnsafeJournal('journal too large')
        name = _TEMP_PREFIX + secrets.token_hex(16)
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'wb', closefd=False) as handle:
                handle.write(encoded)
                handle.flush()
            os.fsync(fd)
            os.replace(name, _JOURNAL, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        finally:
            os.close(fd)
            # A write failure leaves a pending marker; do not auto-remove it.
            # The next status/transaction must treat it as recovery-required.

    def public_status(self) -> dict:
        """Read-only, redacted status for a future *trusted root* endpoint."""
        with self._directory(create=False) as directory:
            if directory is None:
                state = 'none'
            else:
                record = self._read(directory)
                if self._leftovers(directory):
                    state = 'recovery_required'
                elif record is None:
                    state = 'none'
                elif record['phase'] in ('INSPECTED', 'STAGED', 'SNAPSHOTTED', 'COMMITTED'):
                    state = 'incomplete'
                else:
                    state = 'recovery_required'
        return {
            'schema_version': 1,
            'operation': 'protected_status',
            'mode': 'privileged_read_only',
            'privileged_transaction_state': state,
            'secrets_included': False,
        }

    def begin(self, operation: str) -> None:
        if operation not in _OPERATIONS:
            raise JournalError('unsupported transaction operation')
        with self._directory(create=True) as directory:
            with self._exclusive(directory):
                if self._read(directory) is not None or self._leftovers(directory):
                    raise JournalConflict('unfinished transaction; recovery required')
                self._write(directory, {'schema': 1, 'operation': operation,
                                        'phase': 'INSPECTED', 'snapshot_name': None})

    def advance(self, expected_phase: str, next_phase: str,
                *, snapshot_name: str | None = None) -> None:
        if expected_phase not in _PHASES or next_phase not in _PHASES:
            raise JournalError('invalid transaction phase')
        if _PHASES.index(next_phase) != _PHASES.index(expected_phase) + 1:
            raise JournalError('phase transition must advance one step')
        with self._directory(create=False) as directory:
            if directory is None:
                raise JournalConflict('no active transaction')
            with self._exclusive(directory):
                record = self._read(directory)
                if record is None or self._leftovers(directory):
                    raise JournalConflict('missing or uncertain transaction')
                if record['phase'] != expected_phase:
                    raise JournalConflict('stale transaction phase')
                reference = snapshot_name if next_phase == 'SNAPSHOTTED' else record['snapshot_name']
                updated = dict(record, phase=next_phase, snapshot_name=reference)
                _validate(updated)
                self._write(directory, updated)

    def clear_committed(self) -> None:
        """Remove only an explicitly committed journal; never discard recovery."""
        with self._directory(create=False) as directory:
            if directory is None:
                raise JournalConflict('no active transaction')
            with self._exclusive(directory):
                record = self._read(directory)
                if (record is None or record['phase'] != 'COMMITTED' or
                        self._leftovers(directory)):
                    raise JournalConflict('cannot discard uncommitted state')
                os.unlink(_JOURNAL, dir_fd=directory)
                os.fsync(directory)
