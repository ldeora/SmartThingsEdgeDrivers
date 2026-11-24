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


def _stage_base_exists(root, uid):
    """Read-only guarded walk; existing empty stage still needs sync."""
    from contextlib import ExitStack
    with ExitStack() as stack:
        fd = os.open(root, legacy._DIR_FLAGS)
        stack.callback(os.close, fd)
        for i, name in enumerate(legacy._STAGE_COMPONENTS):
            try:
                fd = os.open(name, legacy._DIR_FLAGS, dir_fd=fd)
            except FileNotFoundError:
                return False
            stack.callback(os.close, fd)
            info = os.fstat(fd)
            if (info.st_uid != uid or
                    (stat.S_IMODE(info.st_mode) != 0o700 if i >= 2
                     else bool(stat.S_IMODE(info.st_mode) & 0o022))):
                raise legacy.UnsafeJournal('unsafe stage ancestor')
        return True


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid,
            info.st_gid, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _observed_file(fd, directory, name, uid):
    """Read exact bytes and stable private-file identity through a held fd."""
    legacy._checked_regular(fd, uid)
    initial = _stamp(os.fstat(fd))
    os.lseek(fd, 0, os.SEEK_SET)
    raw = os.read(fd, legacy._MAX_BYTES + 1)
    if (len(raw) != initial[6] or len(raw) > legacy._MAX_BYTES or
            _stamp(os.fstat(fd)) != initial or
            _stamp(os.stat(name, dir_fd=directory, follow_symlinks=False)) != initial):
        raise legacy.JournalConflict('journal evidence changed')
    return raw, initial


def _observe_current(directory, uid):
    try:
        fd = os.open(legacy._JOURNAL, legacy._FILE_FLAGS, dir_fd=directory)
    except FileNotFoundError:
        return None
    try:
        raw, stamp = _observed_file(fd, directory, legacy._JOURNAL, uid)
        if not raw:
            raise legacy.UnsafeJournal('invalid journal length')
        return raw, stamp
    finally:
        os.close(fd)


def _check_reconciliation(root, uid, directory, lock, lock_stamp, entries,
                          current, name, fd, observed):
    """Use the same pre/post-sync guard for every uncertainty discard."""
    live = legacy._open_directory(root, uid, create=False)
    try:
        if live is None or not os.path.samestat(os.fstat(directory), os.fstat(live)):
            raise legacy.JournalConflict('journal directory changed')
    finally:
        if live is not None:
            os.close(live)
    if (_stamp(os.fstat(lock)) != lock_stamp or
            _stamp(os.stat(legacy._LOCK, dir_fd=directory, follow_symlinks=False)) != lock_stamp):
        raise legacy.JournalConflict('journal lock changed')
    legacy._checked_regular(lock, uid)
    if _stamp(os.fstat(fd)) != observed[1]:
        raise legacy.JournalConflict('uncertain record changed')
    if (_observe_current(directory, uid) != current or
            _observed_file(fd, directory, name, uid) != observed or
            _entries(directory) != entries):
        raise legacy.JournalConflict('journal uncertainty changed')
    if current is None and legacy._staged_payload_remains(root, uid):
        raise legacy.JournalConflict('orphan stage requires recovery')


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
        self._stage_retirement_verified = False
        self._stage_quarantine_receipt = None
        self._stage_quarantine_verifying = False

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
        import restore_adopt_stage_quarantine as quarantine
        quarantine.check_cleanup(handle=self)
        if (current['phase'] not in contract._TERMINAL or
                legacy._staged_payload_remains(self.root, self.uid) or
                (not self._stage_retirement_verified and
                 _stage_base_exists(self.root, self.uid)) or
                not callable(verify) or verify(current) is not True):
            raise legacy.JournalConflict('terminal cleanup not verified')
        self.record()
        self._clean()
        if (legacy._staged_payload_remains(self.root, self.uid) or
                (not self._stage_retirement_verified and
                 _stage_base_exists(self.root, self.uid))):
            raise legacy.JournalConflict('stage cleanup incomplete')
        quarantine.check_cleanup(handle=self)
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


    def reconcile_complete_temp(self, verify):
        """Discard one complete, known v2 interrupted write after verification.

        Never promote a temp or derive forward authority from it. Partial
        bytes, unknown versions, multiple entries and missing proof remain
        untouched. The callback is fixture-only: it must establish the
        actual unchanged/restored state required by the durable record,
        including the absence of stage for an orphan initial write.
        """
        self._reconcile_temp(verify, expected=None)

    def reconcile_partial_temp(self, expected, verify):
        """Reconcile a strict prefix of an independently reconstructed v2 record.

        Only a durable v2 transaction is supported here. Empty/short orphan
        writes do not establish schema or intent, and are preserved. Expected
        is a trusted fixture input, not a candidate parsed from partial bytes.
        The verifier must independently establish that proposal under the
        locks, including any new evidence, as well as actual host state.
        No candidate is ever promoted; the durable phase controls recovery.
        """
        frozen = canonical(contract.validate_record(expected))
        candidate = contract.decode_journal(frozen)
        if candidate['schema'] != 2:
            raise legacy.JournalConflict('compatible v2 candidate required')
        self._reconcile_temp(verify, expected=frozen)

    def reconcile_partial_orphan_temp(self, *, confirmation, verify):
        """Discard a fully identifiable initial record missing only its LF.

        No durable predecessor exists. Do not reconstruct an unknown
        writer, intent or phase from incomplete JSON. The trusted verifier
        must independently establish prior authority/host state and that
        no transaction work started; merely healthy current state is not
        enough. No candidate is promoted and no handle is returned.
        """
        if confirmation != 'RECONCILE_ORPHAN' or not callable(verify):
            raise legacy.JournalConflict('explicit orphan reconciliation required')
        self._reconcile_temp(verify, expected=None, orphan_missing_newline=True)

    def _reconcile_temp(self, verify, *, expected, orphan_missing_newline=False):
        with engine.manual_install_lock(self.lock, owner_uid=self.uid):
            directory, lock = self._store._acquire(create=False)
            try:
                durable = _observe_current(directory, self.uid)
                current = None if durable is None else contract.decode_journal(durable[0])
                lock_stamp = _stamp(os.fstat(lock))
                if orphan_missing_newline and current is not None:
                    raise legacy.JournalConflict('durable journal exists')
                entries = _entries(directory)
                normal = {legacy._LOCK} | ({legacy._JOURNAL} if current is not None else set())
                extras = entries - normal
                if not normal <= entries or len(extras) != 1:
                    raise legacy.JournalConflict('ambiguous journal uncertainty')
                name, = extras
                if not legacy._TEMP_NAME.fullmatch(name):
                    raise legacy.JournalConflict('unknown journal uncertainty')
                fd = os.open(name, legacy._FILE_FLAGS, dir_fd=directory)
                try:
                    observed = _observed_file(fd, directory, name, self.uid)
                    raw, _ = observed
                    if expected is None:
                        if not raw:
                            raise legacy.JournalConflict('incomplete journal uncertainty')
                        candidate = contract.decode_journal(raw)
                        proposed = canonical(candidate)
                        if (candidate['schema'] != 2 or
                                len(proposed) > legacy._MAX_BYTES or
                                (proposed[:-1] if orphan_missing_newline else proposed) != raw):
                            raise legacy.JournalConflict('unsupported journal uncertainty')
                    else:
                        # No inference from an empty or ambiguous orphan.
                        # With a durable v2 record, even a zero-byte failed
                        # write can be reconciled, but only against a valid
                        # independently reconstructed next transition and
                        # an actual unchanged/restored-state verifier.
                        if current is None or current['schema'] != 2:
                            raise legacy.JournalConflict('partial orphan or legacy uncertainty')
                        if len(raw) >= len(expected) or not expected.startswith(raw):
                            raise legacy.JournalConflict('not a canonical transition prefix')
                        candidate = contract.decode_journal(expected)
                        proposed = expected
                    if current is None:
                        if (candidate['phase'] != 'INSPECTED' or
                                legacy._staged_payload_remains(self.root, self.uid)):
                            raise legacy.JournalConflict('not an orphan initial write')
                    else:
                        if current['schema'] != 2:
                            raise legacy.JournalConflict('legacy journal uncertainty')
                        contract.validate_transition(current, candidate)
                    # Freeze both arguments; never use callback-modified data.
                    before = canonical(current)
                    if not callable(verify) or verify(json.loads(before), json.loads(proposed)) is not True:
                        raise legacy.JournalConflict('uncertainty not independently reconciled')
                    _check_reconciliation(self.root, self.uid, directory, lock,
                                          lock_stamp, entries, durable, name, fd, observed)
                    # Re-establish durable current record/ancestry BEFORE
                    # retiring uncertainty evidence, then check again.
                    _sync_ancestors(self.root, self.uid)
                    _check_reconciliation(self.root, self.uid, directory, lock,
                                          lock_stamp, entries, durable, name, fd, observed)
                    os.unlink(name, dir_fd=directory)
                    os.fsync(directory)
                finally:
                    os.close(fd)
            except (OSError, contract.ContractError):
                raise legacy.UnsafeJournal('unreconciled journal uncertainty') from None
            finally:
                os.close(lock)
                os.close(directory)
