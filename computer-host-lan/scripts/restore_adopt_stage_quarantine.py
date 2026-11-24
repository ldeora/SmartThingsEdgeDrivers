"""Fixture-only quarantine of a corrupt, journal-bound terminal ready stage.

The normal retirement path is unchanged for healthy stages. No production
dispatch, execution of staged data, managed mutation or credential reads.
"""
from contextlib import ExitStack
import json
import os

import restore_adopt_before as before
import restore_adopt_contract as contract
import restore_adopt_journal as journal
import restore_adopt_quarantine as q
import restore_adopt_stage as stage
import transaction_journal as legacy

_ERROR = before.BeforeStateError
_LOCK = stage.legacy_stage._LOCK


def _names(record):
    txid = record['transaction_id']
    return 'ready-plan-' + txid, 'corrupt-stage-' + txid, 'corrupt-stage-' + txid + '.json'


def _present(fd, name):
    try:
        os.stat(name, dir_fd=fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def _namespace(handle, stack):
    base, ancestors = before._base(handle, stack)
    namespace = q._open_optional(stack, base, q._NAMESPACE, handle.uid)
    return base, ancestors, namespace


def has_artifacts(handle):
    """Detect transaction-specific evidence without trusting receipt bytes."""
    record = before._require_fixture(handle)
    _, destination, receipt = _names(record)
    try:
        with ExitStack() as stack:
            _, _, namespace = _namespace(handle, stack)
            return (namespace is not None and
                    (_present(namespace, destination) or _present(namespace, receipt)))
    except OSError:
        raise _ERROR('stage_quarantine_namespace_unavailable') from None


def _check_active(handle, active, entries):
    # The stage lock belongs to this directory. Refuse a namespace
    # replacement rather than syncing an unrelated directory by pathname.
    current = stage.legacy_stage._walk_destination(handle.root, handle.uid, create=False)
    try:
        if (not os.path.samestat(os.fstat(active), os.fstat(current)) or
                journal._entries(active) != entries):
            raise _ERROR('stage_quarantine_active_changed')
    finally:
        os.close(current)


def _receipt(record, items):
    source, destination, _ = _names(record)
    return journal.canonical(dict(
        schema=1, origin='corrupt_terminal_stage_quarantine',
        transaction_id=record['transaction_id'], operation=record['operation'],
        terminal_phase=record['phase'],
        journal_sha256=before._hash(journal.canonical(record)),
        staged_plan_sha256=record['evidence']['staged_plan_sha256'],
        source=source, destination=destination, items=items))


def _read_receipt(namespace, name, uid, expected, *, sync=False):
    if namespace is None:
        return False
    try:
        raw, _ = q._entry(namespace, name, uid, before._LIMIT, sync=sync)
    except FileNotFoundError:
        return False
    if raw != expected:
        raise _ERROR('stage_quarantine_receipt_mismatch')
    return True


# Explicit allowlist: a new PlanError is not automatically evidence of
# corruption. Unstable reads/identity, operational failures and unknown
# codes must preserve the stage in place.
_CORRUPTION_CODES = frozenset((
    'invalid_plan_manifest', 'invalid_plan_services', 'invalid_plan_item',
    'invalid_absent_item', 'inconsistent_plan_services',
    'adopt_plan_intent_mismatch', 'plan_too_large', 'invalid_plan_file_size',
    'plan_manifest_digest_mismatch', 'noncanonical_plan_manifest',
    'plan_file_digest_mismatch', 'unexpected_plan_entries',
))


def _require_corrupt(fd, record, uid):
    # Safe opaque inventory is checked independently first. Only definite
    # structural/content validation failure or a missing required file is
    # corruption; permission, I/O, unsafe metadata and other errors refuse.
    try:
        stage._inspect(fd, record, uid, record['evidence']['staged_plan_sha256'])
    except stage.PlanError as exc:
        if str(exc) not in _CORRUPTION_CODES:
            raise _ERROR('stage_quarantine_corruption_not_established') from None
        return
    except (contract.ContractError, FileNotFoundError):
        return
    raise _ERROR('healthy_stage_requires_normal_retirement')


def quarantine_corrupt_stage(handle, *, confirmation, verify):
    """Explicitly preserve a corrupt bound ready stage under all three locks.

    The trusted verifier independently establishes the terminal outcome,
    including managed state, services, credential continuity and operator
    authorization, without relying on the corrupt plan. It must not call
    APIs that reacquire the stage lock. Called again on every retry.
    RECONCILE_RECEIPT appends a verified missing suffix without moving
    the stage or granting cleanup authority.
    """
    record = before._require_fixture(handle)
    handle._clean()
    reconcile = q._reconcile_confirmation(handle, confirmation, verify)
    if record['phase'] not in contract._TERMINAL or record['evidence'] is None:
        raise _ERROR('bound_terminal_stage_required')
    source, destination, receipt_name = _names(record)
    frozen = journal.canonical(record)
    try:
        with ExitStack() as stack:
            active, lock = stage._locked(handle, create=False)
            stack.callback(os.close, active)
            stack.callback(os.close, lock)
            base, ancestors, namespace = _namespace(handle, stack)
            entries = journal._entries(active)
            if entries not in ({_LOCK, source}, {_LOCK}):
                raise _ERROR('foreign_or_ambiguous_stage')
            src = q._open_optional(stack, active, source, handle.uid)
            dst = None if namespace is None else q._open_optional(
                stack, namespace, destination, handle.uid)
            if (src is None) == (dst is None):
                raise _ERROR('stage_quarantine_source_destination_conflict')
            fd = src if src is not None else dst
            items = q._inventory(fd, handle.uid, staged=True)
            _require_corrupt(fd, record, handle.uid)
            receipt = _receipt(record, items)
            if len(receipt) > before._LIMIT:
                raise _ERROR('quarantine_receipt_too_large')
            if reconcile:
                if src is None or dst is not None:
                    raise _ERROR('partial_quarantine_receipt_requires_source')
                observed = q._partial_receipt(namespace, receipt_name, handle.uid, receipt)
                had_receipt = True
            else:
                had_receipt = _read_receipt(namespace, receipt_name, handle.uid, receipt)
            if dst is not None and not had_receipt:
                raise _ERROR('stage_quarantine_receipt_missing')
            handle._stage_quarantine_verifying = True
            try:
                verified = verify(json.loads(frozen))
            finally:
                handle._stage_quarantine_verifying = False
            if verified is not True:
                raise _ERROR('quarantine_outcome_not_verified')
            if journal.canonical(handle.record()) != frozen:
                raise _ERROR('quarantine_journal_changed')
            handle._clean()
            _check_active(handle, active, entries)
            if namespace is not None:
                q._same_entry(base, q._NAMESPACE, namespace)
                if reconcile:
                    if q._partial_receipt(namespace, receipt_name, handle.uid, receipt) != observed:
                        raise _ERROR('partial_quarantine_receipt_changed')
                    if _present(namespace, destination):
                        raise _ERROR('stage_quarantine_source_destination_conflict')
                elif _read_receipt(namespace, receipt_name, handle.uid, receipt) != had_receipt:
                    raise _ERROR('quarantine_receipt_changed')
            q._same_entry(active if src is not None else namespace,
                          source if src is not None else destination, fd)
            if q._inventory(fd, handle.uid, staged=True) != items:
                raise _ERROR('quarantine_tree_changed')
            _require_corrupt(fd, record, handle.uid)
            handle._failed = True
            handle._stage_retirement_verified = False
            handle._stage_quarantine_receipt = None
            if namespace is None:
                os.mkdir(q._NAMESPACE, 0o700, dir_fd=base)
                namespace = q._open_optional(stack, base, q._NAMESPACE, handle.uid)
                if namespace is None:
                    raise _ERROR('quarantine_namespace_missing')
            q._same_entry(base, q._NAMESPACE, namespace)
            if len({os.fstat(x).st_dev for x in (active, fd, base, namespace)}) != 1:
                raise _ERROR('quarantine_cross_filesystem')
            if q._inventory(fd, handle.uid, sync=True, staged=True) != items:
                raise _ERROR('quarantine_tree_changed')
            if reconcile:
                _check_active(handle, active, entries)
                q._same_entry(active, source, src)
                if _present(namespace, destination):
                    raise _ERROR('stage_quarantine_source_destination_conflict')
                q._complete_partial_receipt(namespace, receipt_name, handle.uid, receipt, observed)
            elif not had_receipt:
                before.storage._write_file(namespace, receipt_name, receipt,
                                           before._hash(receipt), handle.uid)
            if not _read_receipt(namespace, receipt_name, handle.uid, receipt, sync=True):
                raise _ERROR('stage_quarantine_receipt_missing')
            os.fsync(namespace)
            for ancestor in reversed(ancestors):
                os.fsync(ancestor)
            if reconcile:
                _check_active(handle, active, entries)
                q._same_entry(active, source, src)
                q._same_entry(base, q._NAMESPACE, namespace)
                if (_present(namespace, destination) or
                        q._inventory(src, handle.uid, staged=True) != items or
                        not _read_receipt(namespace, receipt_name, handle.uid, receipt)):
                    raise _ERROR('quarantine_publication_changed')
                os.fsync(active)
                stage._sync_stage_ancestors(handle)
                _check_active(handle, active, entries)
                handle._failed = False
                try:
                    handle.record()
                    handle._clean()
                except BaseException:
                    handle._failed = True
                    raise
                # Neither retirement nor quarantine completion certified.
                return 'receipt_completed'
            if src is not None:
                q._same_entry(active, source, fd)
                q._same_entry(base, q._NAMESPACE, namespace)
                _check_active(handle, active, entries)
                if (q._inventory(fd, handle.uid, staged=True) != items or
                        not _read_receipt(namespace, receipt_name, handle.uid, receipt)):
                    raise _ERROR('quarantine_publication_changed')
                q._rename_noreplace(active, source, namespace, destination)
            q._same_entry(namespace, destination, fd)
            q._same_entry(base, q._NAMESPACE, namespace)
            _check_active(handle, active, {_LOCK})
            if (q._inventory(fd, handle.uid, sync=True, staged=True) != items or
                    not _read_receipt(namespace, receipt_name, handle.uid, receipt, sync=True)):
                raise _ERROR('quarantine_publication_changed')
            os.fsync(namespace)
            for ancestor in reversed(ancestors):
                os.fsync(ancestor)
            os.fsync(active)
            stage._sync_stage_ancestors(handle)
            _check_active(handle, active, {_LOCK})
            handle._failed = False
            try:
                handle.record()
                handle._clean()
            except BaseException:
                handle._failed = True
                raise
            handle._stage_quarantine_receipt = before._hash(receipt)
            handle._stage_retirement_verified = True
            return 'quarantined' if src is not None else 'already_quarantined'
    except (OSError, before.storage.StagingError):
        raise _ERROR('stage_quarantine_publication_failed') from None


def check_cleanup(handle):
    """Require a fresh verified quarantine and intact evidence before clear.

    An empty active stage is not sufficient after quarantine. This check
    runs both before and after the independent terminal cleanup verifier.
    No additional authorization is created by a receipt alone.
    """
    try:
        present = has_artifacts(handle)
        expected = handle._stage_quarantine_receipt
        if not present and expected is None:
            return
        if not present or expected is None:
            raise _ERROR('stage_quarantine_requires_reconciliation')
        record = before._require_fixture(handle)
        if record['phase'] not in contract._TERMINAL or record['evidence'] is None:
            raise _ERROR('bound_terminal_stage_required')
        _, destination, receipt_name = _names(record)
        with ExitStack() as stack:
            active, lock = stage._locked(handle, create=False)
            stack.callback(os.close, active)
            stack.callback(os.close, lock)
            base, _, namespace = _namespace(handle, stack)
            if namespace is None or journal._entries(active) != {_LOCK}:
                raise _ERROR('stage_quarantine_requires_reconciliation')
            fd = q._open_optional(stack, namespace, destination, handle.uid)
            if fd is None:
                raise _ERROR('stage_quarantine_requires_reconciliation')
            items = q._inventory(fd, handle.uid, staged=True)
            receipt = _receipt(record, items)
            if (before._hash(receipt) != expected or
                    not _read_receipt(namespace, receipt_name, handle.uid, receipt)):
                raise _ERROR('stage_quarantine_receipt_mismatch')
            q._same_entry(namespace, destination, fd)
            q._same_entry(base, q._NAMESPACE, namespace)
            _check_active(handle, active, {_LOCK})
    except (OSError, ValueError, before.storage.StagingError):
        raise legacy.JournalConflict('stage quarantine cleanup not verified') from None
