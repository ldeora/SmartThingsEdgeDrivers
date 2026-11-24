"""Experimental schema-2 journal persistence, disposable roots ONLY.

Shares the existing journal location and locks so legacy code refuses new
records. No production caller or live-root support. No service or managed
file mutation. Uncertain writes and abandoned stages are retained for a
future reviewed recovery controller, never guessed away.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import secrets
import stat

import installer_transaction as engine
import restore_adopt_contract as contract
import transaction_journal as legacy


def canonical(data):
    return (json.dumps(data, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')


def read_record(directory, uid):
    try:
        fd = os.open(legacy._JOURNAL, legacy._FILE_FLAGS, dir_fd=directory)
    except FileNotFoundError:
        return None
    except OSError:
        raise legacy.UnsafeJournal('unsafe journal record') from None
    try:
        legacy._checked_regular(fd, uid)
        size = os.fstat(fd).st_size
        raw = os.read(fd, legacy._MAX_BYTES + 1)
        if len(raw) != size or not 0 < size <= legacy._MAX_BYTES:
            raise legacy.UnsafeJournal('invalid journal length')
        return contract.decode_journal(raw)
    except (OSError, contract.ContractError):
        raise legacy.UnsafeJournal('invalid or unsupported journal record') from None
    finally:
        os.close(fd)


def _write(directory, record):
    data = canonical(contract.validate_record(record))
    if record['schema'] != 2 or len(data) > legacy._MAX_BYTES:
        raise legacy.UnsafeJournal('invalid v2 journal write')
    name = legacy._TEMP_PREFIX + secrets.token_hex(16)
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory)
        try:
            os.fchmod(fd, 0o600)
            offset = 0
            while offset < len(data):
                count = os.write(fd, data[offset:])
                if count <= 0:
                    raise OSError('short journal write')
                offset += count
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(name, legacy._JOURNAL, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    except OSError:
        # Same uncertainty namespace as legacy; never delete on failure.
        raise legacy.UnsafeJournal('durable v2 journal update failed') from None


def _entries(directory):
    fd = os.open('.', legacy._DIR_FLAGS, dir_fd=directory)
    try:
        return set(os.listdir(fd))
    finally:
        os.close(fd)


def _sync_ancestors(root, uid):
    # Sync fixed ancestry even on retry after an earlier mkdir.
    from contextlib import ExitStack
    with ExitStack() as stack:
        fd = os.open(root, legacy._DIR_FLAGS)
        stack.callback(os.close, fd)
        ancestors = [fd]
        for index, part in enumerate(legacy._COMPONENTS):
            fd = os.open(part, legacy._DIR_FLAGS, dir_fd=fd)
            stack.callback(os.close, fd)
            info = os.fstat(fd)
            if (info.st_uid != uid or
                    stat.S_IMODE(info.st_mode) & (0o077 if index >= 2 else 0o022)):
                raise legacy.UnsafeJournal('unsafe journal ancestor')
            ancestors.append(fd)
        for fd in reversed(ancestors):
            os.fsync(fd)


class Handle:
    """Single-use fixture capability; recovery handles cannot advance forward."""
    def __init__(self, root, uid, directory, record, *, recovering):
        self.root = root
        self.uid = uid
        self._directory = directory
        self._expected = canonical(record)
        self._pid = os.getpid()
        self._active = True
        self._recovering = recovering
        self._failed = False

    def record(self):
        if not self._active or self._failed or self._pid != os.getpid():
            raise legacy.JournalConflict('inactive v2 handle')
        record = read_record(self._directory, self.uid)
        if record is None or canonical(record) != self._expected:
            raise legacy.JournalConflict('stale v2 handle')
        return record

    def _clean(self):
        if _entries(self._directory) != {legacy._LOCK, legacy._JOURNAL}:
            raise legacy.JournalConflict('uncertain journal requires reconciliation')

    def advance(self, phase, *, evidence=None, snapshot_name=None,
                before_receipt_sha256=None, verify=None):
        old = self.record()
        self._clean()
        if self._recovering and phase not in ('ABORTED', 'ROLLED_BACK'):
            raise legacy.JournalConflict('recovery cannot resume forward work')
        new = dict(old, phase=phase)
        if phase == 'STAGED':
            new['evidence'] = evidence
        elif evidence is not None:
            raise legacy.JournalConflict('unexpected stage evidence')
        if phase == 'SNAPSHOTTED':
            new.update(snapshot_name=snapshot_name, before_receipt_sha256=before_receipt_sha256)
        elif snapshot_name is not None or before_receipt_sha256 is not None:
            raise legacy.JournalConflict('unexpected before-state evidence')
        contract.validate_transition(old, new)
        # Trusted fixture callback checks actual evidence; structural
        # validation is not proof. No live mutation controller exists.
        # Freeze the proposed record before calling a verifier. Neither
        # mutation of its argument nor caller-owned nested evidence can
        # rebind the journal after validation.
        frozen = canonical(new)
        if not callable(verify) or verify(json.loads(frozen)) is not True:
            raise legacy.JournalConflict('transition not independently verified')
        if canonical(new) != frozen:
            raise legacy.JournalConflict('proposed transition changed')
        new = contract.decode_journal(frozen)
        if canonical(self.record()) != canonical(old):
            raise legacy.JournalConflict('stale v2 handle')
        self._clean()
        # Poison the handle on any uncertain publication failure.
        self._failed = True
        _write(self._directory, new)
        self._expected = canonical(new)
        self._failed = False

    def clear_finished(self, verify):
        current = self.record()
        self._clean()
        if (current['phase'] not in contract._TERMINAL or
                legacy._staged_payload_remains(self.root, self.uid) or
                not callable(verify) or verify(current) is not True):
            raise legacy.JournalConflict('terminal cleanup not verified')
        self.record()
        self._clean()
        if legacy._staged_payload_remains(self.root, self.uid):
            raise legacy.JournalConflict('stage cleanup incomplete')
        self._failed = True
        os.unlink(legacy._JOURNAL, dir_fd=self._directory)
        os.fsync(self._directory)


class FixtureJournal:
    """Lock order: shared manual installer flock, then exclusive journal flock.

    Intentionally requires an absolute disposable root and rejects live
    root, including aliases. Future production integration is separate.
    """
    def __init__(self, root):
        self.root = Path(root)
        if (not self.root.is_absolute() or '..' in self.root.parts or
                self.root.resolve() == Path('/') or self.root.resolve() != self.root):
            raise legacy.JournalConflict('disposable root required')
        self.uid = os.geteuid()
        self.lock = self.root / engine._MANUAL_LOCK.relative_to('/')
        self._store = legacy.ProtectedJournal(root=self.root, owner_uid=self.uid)

    @contextmanager
    def transaction(self, intent=None):
        recovering = intent is None
        if not recovering:
            intent = contract.validate_new_intent(intent)
        with engine.manual_install_lock(self.lock, owner_uid=self.uid):
            directory, lock = self._store._acquire(create=not recovering)
            handle = None
            try:
                current = read_record(directory, self.uid)
                entries = _entries(directory)
                allowed = {legacy._LOCK} | ({legacy._JOURNAL} if current is not None else set())
                if entries != allowed:
                    raise legacy.JournalConflict('uncertain journal requires reconciliation')
                if recovering:
                    if current is None or current['schema'] != 2:
                        raise legacy.JournalConflict('compatible v2 journal required')
                    # A previous replace may have succeeded before its
                    # directory fsync failed. Establish durability again
                    # before returning a recovery capability.
                    _sync_ancestors(self.root, self.uid)
                else:
                    if current is not None or legacy._staged_payload_remains(self.root, self.uid):
                        raise legacy.JournalConflict('previous transaction requires cleanup')
                    current = dict(schema=2, transaction_id=secrets.token_hex(16),
                                   operation=intent['action'], phase='INSPECTED',
                                   snapshot_name=None, before_receipt_sha256=None,
                                   intent=intent, evidence=None)
                    _write(directory, current)
                    _sync_ancestors(self.root, self.uid)
                handle = Handle(self.root, self.uid, directory, current, recovering=recovering)
                yield handle
            finally:
                if handle is not None:
                    handle._active = False
                os.close(lock)
                os.close(directory)
