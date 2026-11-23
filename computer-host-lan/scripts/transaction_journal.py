#!/usr/bin/env python3
"""Durable protected Linux wizard journal primitives; no privileged CLI.

Deliberately NOT connected to the current installer, agent or Go wizard.
Only trusted root-owned code may eventually call this module as root.
Never execute this file as root from a user-writable source checkout.
"""
from __future__ import annotations

import errno
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import stat
import time
from typing import Callable

# root/owner_uid injection exists ONLY to exercise temporary filesystem fixtures.
_COMPONENTS = ('var', 'backups', 'linux-host-agent', 'wizard-transactions')
_JOURNAL = 'journal.json'
_LOCK = 'lock'
_TEMP_PREFIX = '.wizard-journal-'
_TEMP_NAME = re.compile(r'\.wizard-journal-[0-9a-f]{32}\Z')
_MAX_BYTES = 2048
_LOCK_WAIT_SECONDS = 1.25  # Short, bounded grace for concurrent status readers.
_LOCK_RETRY_SECONDS = 0.025
_PHASES = ('INSPECTED', 'STAGED', 'SNAPSHOTTED', 'APPLYING',
           'ACTIVATING', 'VERIFYING', 'COMMITTED')
_TERMINAL = frozenset(('COMMITTED', 'ABORTED', 'ROLLED_BACK'))
_OPERATIONS = frozenset(('install', 'upgrade', 'repair', 'uninstall'))
_SNAPSHOT = re.compile(r'snapshot-[A-Za-z0-9_-]{6,64}\Z')
_TXID = re.compile(r'[0-9a-f]{32}\Z')
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class JournalError(RuntimeError):
    """Fixed, non-sensitive errors only."""


class UnsafeJournal(JournalError):
    pass


class JournalConflict(JournalError):
    pass


def _unique_keys(pairs):
    obj = {}
    for name, value in pairs:
        if name in obj:
            raise ValueError('duplicate journal key')
        obj[name] = value
    return obj


def _validate(data: object) -> dict:
    if not isinstance(data, dict) or set(data) != {
        'schema', 'transaction_id', 'operation', 'phase', 'snapshot_name'
    }:
        raise UnsafeJournal('invalid journal structure')
    if type(data['schema']) is not int or data['schema'] != 1:
        raise UnsafeJournal('unsupported journal schema')
    if not isinstance(data['transaction_id'], str) or not _TXID.fullmatch(data['transaction_id']):
        raise UnsafeJournal('invalid transaction reference')
    if not isinstance(data['operation'], str) or data['operation'] not in _OPERATIONS:
        raise UnsafeJournal('invalid journal operation')
    if not isinstance(data['phase'], str) or (
        data['phase'] not in _PHASES and data['phase'] not in _TERMINAL
    ):
        raise UnsafeJournal('invalid journal phase')
    snapshot = data['snapshot_name']
    if snapshot is not None and (
        not isinstance(snapshot, str) or not _SNAPSHOT.fullmatch(snapshot)
    ):
        raise UnsafeJournal('invalid snapshot reference')
    needs_snapshot = data['phase'] in ('SNAPSHOTTED', 'APPLYING', 'ACTIVATING',
                                      'VERIFYING', 'COMMITTED', 'ROLLED_BACK')
    if needs_snapshot and snapshot is None:
        raise UnsafeJournal('missing snapshot reference')
    if data['phase'] in ('INSPECTED', 'STAGED') and snapshot is not None:
        raise UnsafeJournal('unexpected snapshot reference')
    # ABORTED may retain a pre-apply snapshot for forensic inspection.
    return data


def _checked_regular(fd: int, owner_uid: int) -> None:
    st = os.fstat(fd)
    if (not stat.S_ISREG(st.st_mode) or st.st_uid != owner_uid or
            st.st_nlink != 1 or stat.S_IMODE(st.st_mode) != 0o600):
        raise UnsafeJournal('unsafe private journal file')


def _open_directory(root: Path, owner_uid: int, *, create: bool) -> int | None:
    """No-follow walk of constant path components; caller owns returned fd."""
    fd = None
    try:
        fd = os.open(root, _DIR_FLAGS)
        root_stat = os.fstat(fd)
        if (root_stat.st_uid != owner_uid or
                stat.S_IMODE(root_stat.st_mode) & 0o022):
            raise UnsafeJournal('unsafe journal root')
        for index, component in enumerate(_COMPONENTS):
            created = False
            private = index >= 2
            intended_mode = 0o700 if private else 0o755
            try:
                child = os.open(component, _DIR_FLAGS, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    # The finally block releases the current directory fd.
                    return None
                os.mkdir(component, intended_mode, dir_fd=fd)
                os.fsync(fd)
                child = os.open(component, _DIR_FLAGS, dir_fd=fd)
                created = True
            info = os.fstat(child)
            if info.st_uid != owner_uid:
                os.close(child)
                raise UnsafeJournal('unsafe journal directory owner')
            if created:
                # mkdir's mode is filtered by umask. Set *new* directories
                # explicitly, without changing the administrator's existing
                # /var or /var/backups directory permissions.
                try:
                    os.fchmod(child, intended_mode)
                    os.fsync(child)
                except OSError:
                    os.close(child)
                    raise
                info = os.fstat(child)
            if stat.S_IMODE(info.st_mode) & (0o077 if private else 0o022):
                os.close(child)
                raise UnsafeJournal('unsafe journal directory')
            os.close(fd)
            fd = child
        result, fd = fd, None
        return result
    except JournalError:
        raise
    except OSError:
        raise UnsafeJournal('unsafe or unavailable journal directory') from None
    finally:
        if fd is not None:
            os.close(fd)


def _open_lock(directory: int, owner_uid: int, *, create: bool,
               read_only: bool = False) -> int | None:
    flags = (os.O_RDONLY if read_only else os.O_RDWR) | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        fd = os.open(_LOCK, flags | (os.O_CREAT if create else 0),
                     0o600, dir_fd=directory)
    except FileNotFoundError:
        if not create:
            return None
        raise
    except OSError:
        raise UnsafeJournal('unsafe journal lock') from None
    try:
        _checked_regular(fd, owner_uid)
        if os.fstat(fd).st_size:
            raise UnsafeJournal('nonempty journal lock')
    except Exception:
        os.close(fd)
        raise
    return fd


def _take_lock(fd: int, *, shared: bool = False) -> None:
    """Non-blocking flock. Read-only status uses SH; owners retain EX."""
    try:
        fcntl.flock(fd, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) |
                    fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
            raise JournalConflict('journal transaction already active') from None
        raise UnsafeJournal('journal lock failed') from None


def _read(directory: int, owner_uid: int) -> dict | None:
    try:
        fd = os.open(_JOURNAL, _FILE_FLAGS, dir_fd=directory)
    except FileNotFoundError:
        return None
    except OSError:
        raise UnsafeJournal('unsafe journal record') from None
    try:
        _checked_regular(fd, owner_uid)
        st = os.fstat(fd)
        if st.st_size < 1 or st.st_size > _MAX_BYTES:
            raise UnsafeJournal('invalid journal length')
        # One capped read is sufficient for a small regular file held under
        # the journal lock; never loop without the same hard total cap.
        raw = os.read(fd, _MAX_BYTES + 1)
        if not raw or len(raw) > _MAX_BYTES or len(raw) != st.st_size:
            raise UnsafeJournal('invalid journal length')
        return _validate(json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_keys))
    except (OSError, ValueError, UnicodeError, TypeError):
        raise UnsafeJournal('invalid journal encoding') from None
    finally:
        os.close(fd)


def _leftovers(directory: int) -> list[str]:
    try:
        return [entry for entry in os.listdir(directory) if entry.startswith(_TEMP_PREFIX)]
    except OSError:
        raise UnsafeJournal('unable to inspect journal staging') from None


def _write(directory: int, data: dict) -> None:
    _validate(data)
    encoded = (json.dumps(data, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')
    if len(encoded) > _MAX_BYTES:
        raise UnsafeJournal('journal too large')
    name = _TEMP_PREFIX + secrets.token_hex(16)
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory)
        try:
            os.fchmod(fd, 0o600)
            offset = 0
            while offset < len(encoded):
                written = os.write(fd, encoded[offset:])
                if written <= 0:
                    raise OSError('incomplete journal write')
                offset += written
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(name, _JOURNAL, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    except OSError:
        # Intentionally leave any unrenamed temp file as a recovery marker.
        raise UnsafeJournal('durable journal update failed') from None


def _remove_leftovers(directory: int, owner_uid: int) -> None:
    for name in _leftovers(directory):
        if not _TEMP_NAME.fullmatch(name):
            raise UnsafeJournal('unexpected journal staging entry')
        fd = os.open(name, _FILE_FLAGS, dir_fd=directory)
        try:
            _checked_regular(fd, owner_uid)
        finally:
            os.close(fd)
        os.unlink(name, dir_fd=directory)
    os.fsync(directory)


class TransactionHandle:
    """Capability for a single transaction, held under a lifetime flock.

    The owner must keep this handle in a with block until the operation
    completes or the process exits. An interrupted operation leaves its
    journal intact and automatically releases the kernel flock on exit.
    Do not fork while holding a handle: a child inherits the open file
    description and can keep the lock after its parent exits. If unavoidable,
    the child must CLOSE its inherited handle immediately (never LOCK_UN,
    which would also unlock the parent's shared open file description).
    """

    def __init__(self, journal: 'ProtectedJournal', directory: int,
                 lockfd: int, transaction_id: str):
        self._journal = journal
        self._directory = directory
        self._lockfd = lockfd
        self._transaction_id = transaction_id
        self._pid = os.getpid()
        self._closed = False

    def __enter__(self):
        self._require_open()
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        self.close()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            os.close(self._lockfd)
            os.close(self._directory)

    def _require_open(self) -> None:
        if self._closed or os.getpid() != self._pid:
            raise JournalConflict('transaction handle is not active')

    def _record(self) -> dict:
        self._require_open()
        current = _read(self._directory, self._journal.owner_uid)
        if current is None or current['transaction_id'] != self._transaction_id:
            raise JournalConflict('transaction identity changed')
        return current

    def advance(self, expected_phase: str, next_phase: str,
                *, snapshot_name: str | None = None) -> None:
        if expected_phase not in _PHASES or next_phase not in _PHASES:
            raise JournalError('invalid transaction phase')
        if _PHASES.index(next_phase) != _PHASES.index(expected_phase) + 1:
            raise JournalError('transaction phase must advance one step')
        current = self._record()
        if current['phase'] != expected_phase or _leftovers(self._directory):
            raise JournalConflict('stale or interrupted transaction')
        new_snapshot = snapshot_name if next_phase == 'SNAPSHOTTED' else current['snapshot_name']
        _write(self._directory, dict(current, phase=next_phase,
                                     snapshot_name=new_snapshot))

    def abort(self, verify_unmodified: Callable[[str | None], bool] | None = None) -> None:
        """Abort before APPLYING, only after resolving uncertain writes.

        With interrupted temporary journal writes, trusted recovery code
        must first confirm that managed state is unchanged; a boolean alone
        is not accepted as a proof. No source/tree mutation is performed.
        """
        current = self._record()
        if current['phase'] not in ('INSPECTED', 'STAGED', 'SNAPSHOTTED'):
            raise JournalConflict('only a pre-apply transaction can be aborted')
        if _leftovers(self._directory) and (
            not callable(verify_unmodified) or
            verify_unmodified(current['snapshot_name']) is not True
        ):
            raise JournalConflict('interrupted write has not been reconciled')
        _write(self._directory, dict(current, phase='ABORTED'))

    def mark_rolled_back(self, verify_restored: Callable[[str], bool]) -> None:
        """Record a completed rollback ONLY after trusted verification.

        The callback is a future privileged engine responsibility. It must
        validate snapshot ownership/content AND restored managed files,
        identity and services. This module does not perform the rollback.
        """
        current = self._record()
        if current['phase'] not in ('APPLYING', 'ACTIVATING', 'VERIFYING'):
            raise JournalConflict('this transaction has no applied phase to restore')
        # A leftover staging file is an uncertainty, not automatically proof
        # of failure once trusted rollback verification has succeeded.
        if not callable(verify_restored) or (
            verify_restored(current['snapshot_name']) is not True
        ):
            raise JournalConflict('rollback has not been verified')
        _write(self._directory, dict(current, phase='ROLLED_BACK'))

    def clear_finished(self) -> None:
        """Remove terminal journal, plus validated interrupted temp markers."""
        # This is the explicit point that removes leftover staging files
        # after the trusted controller has recorded a terminal outcome.
        current = self._record()
        if current['phase'] not in _TERMINAL:
            raise JournalConflict('cannot clear unfinished transaction')
        _remove_leftovers(self._directory, self._journal.owner_uid)
        try:
            os.unlink(_JOURNAL, dir_fd=self._directory)
            os.fsync(self._directory)
        except OSError:
            raise UnsafeJournal('journal cleanup failed') from None


class ProtectedJournal:
    """A private journal primitive, not a privileged execution boundary.

    Production may use only root='/' and owner_uid=0 from trusted code. The
    injection parameters are for non-root filesystem fixture tests exclusively.
    """

    def __init__(self, *, root: Path = Path('/'), owner_uid: int = 0):
        self.root = Path(root)
        self.owner_uid = owner_uid

    def _acquire(self, *, create: bool) -> tuple[int, int]:
        directory = _open_directory(self.root, self.owner_uid, create=create)
        if directory is None:
            raise JournalConflict('no protected journal available')
        try:
            lockfd = _open_lock(directory, self.owner_uid, create=create)
            if lockfd is None:
                raise JournalConflict('missing protected journal lock')
            try:
                # A status poll briefly holds a shared lock. Retry for a
                # bounded interval so it cannot spuriously defeat begin(),
                # while an actual exclusive transaction still fails promptly.
                deadline = time.monotonic() + _LOCK_WAIT_SECONDS
                while True:
                    try:
                        _take_lock(lockfd)
                        return directory, lockfd
                    except JournalConflict:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise
                        time.sleep(min(remaining, _LOCK_RETRY_SECONDS))
            except Exception:
                os.close(lockfd)
                raise
        except Exception:
            os.close(directory)
            raise

    def public_status(self) -> dict:
        """Read-only status. Never creates the lock or any directories."""
        directory = _open_directory(self.root, self.owner_uid, create=False)
        state = 'none'
        if directory is not None:
            try:
                lockfd = _open_lock(directory, self.owner_uid, create=False, read_only=True)
                if lockfd is None:
                    # Absence of a lock with an existing journal/temp is an
                    # anomaly, never evidence of a safely completed install.
                    state = ('recovery_required'
                             if _read(directory, self.owner_uid) or _leftovers(directory)
                             else 'none')
                else:
                    try:
                        try:
                            _take_lock(lockfd, shared=True)
                        except JournalConflict:
                            # Only an exclusive transaction owner should
                            # prevent readers from taking a shared lock.
                            state = 'in_progress'
                        else:
                            current = _read(directory, self.owner_uid)
                            if _leftovers(directory):
                                state = 'recovery_required'
                            elif current is None or current['phase'] in _TERMINAL:
                                state = 'none'
                            elif current['phase'] in ('INSPECTED', 'STAGED', 'SNAPSHOTTED'):
                                state = 'incomplete'
                            else:
                                state = 'recovery_required'
                    finally:
                        os.close(lockfd)
            finally:
                os.close(directory)
        return {
            'schema_version': 1,
            'operation': 'protected_status',
            'mode': 'privileged_read_only',
            'privileged_transaction_state': state,
            'secrets_included': False,
        }

    def begin(self, operation: str) -> TransactionHandle:
        if not isinstance(operation, str) or operation not in _OPERATIONS:
            raise JournalError('unsupported transaction operation')
        directory, lockfd = self._acquire(create=True)
        try:
            current = _read(directory, self.owner_uid)
            if _leftovers(directory):
                raise JournalConflict('uncertain journal write requires recovery')
            if current is not None:
                if current['phase'] not in _TERMINAL:
                    raise JournalConflict('unfinished transaction; recovery required')
                # Reap only known-complete terminal state while holding lock.
                os.unlink(_JOURNAL, dir_fd=directory)
                os.fsync(directory)
            transaction_id = secrets.token_hex(16)
            record = {'schema': 1, 'transaction_id': transaction_id,
                      'operation': operation, 'phase': 'INSPECTED',
                      'snapshot_name': None}
            _write(directory, record)
            return TransactionHandle(self, directory, lockfd, transaction_id)
        except Exception:
            os.close(lockfd)
            os.close(directory)
            raise

    def reconcile_orphaned_staging(self, verify_no_changes: Callable[[], bool]) -> None:
        """Resolve an interrupted *first journal write*, after trusted checks.

        Only valid with NO persistent journal and with leftover staged files.
        The future root-side recovery engine must prove no managed mutation
        occurred. No unverified or automatic cleanup is permitted.
        """
        directory, lockfd = self._acquire(create=False)
        try:
            if _read(directory, self.owner_uid) is not None or not _leftovers(directory):
                raise JournalConflict('not an orphaned initial journal write')
            if not callable(verify_no_changes) or verify_no_changes() is not True:
                raise JournalConflict('unchanged installation has not been verified')
            _remove_leftovers(directory, self.owner_uid)
        finally:
            os.close(lockfd)
            os.close(directory)

    def finish_terminal(self) -> None:
        """Complete interrupted cleanup for a previously terminal journal.

        This does NOT certify recovery; ABORTED/ROLLED_BACK/COMMITTED was
        already durably recorded by a trusted transaction owner.
        """
        directory, lockfd = self._acquire(create=False)
        try:
            current = _read(directory, self.owner_uid)
            if current is None or current['phase'] not in _TERMINAL:
                raise JournalConflict('cannot clean an unfinished transaction')
            _remove_leftovers(directory, self.owner_uid)
            try:
                os.unlink(_JOURNAL, dir_fd=directory)
                os.fsync(directory)
            except OSError:
                raise UnsafeJournal('journal cleanup failed') from None
        finally:
            os.close(lockfd)
            os.close(directory)

    def resume_recovery(self) -> TransactionHandle:
        """Trusted caller obtains exclusive recovery ownership after crash."""
        directory, lockfd = self._acquire(create=False)
        try:
            current = _read(directory, self.owner_uid)
            if current is None:
                raise JournalConflict('no recorded transaction to recover')
            if current['phase'] in _TERMINAL:
                raise JournalConflict('completed journal needs no recovery')
            return TransactionHandle(self, directory, lockfd, current['transaction_id'])
        except Exception:
            os.close(lockfd)
            os.close(directory)
            raise
