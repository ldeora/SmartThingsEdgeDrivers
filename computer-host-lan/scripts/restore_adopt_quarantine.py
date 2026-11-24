"""Explicit fixture-only quarantine for an unbound aborted before snapshot.

No production callers, journal clearing, managed mutation or credential reads.
A receipt is durable before the no-replace move; it is never rollback evidence.
"""
from contextlib import ExitStack
import ctypes
import os
import stat

import install_core as core
import restore_adopt_before as before
import restore_adopt_journal as journal
import restore_adopt_stage as stage

_NAMESPACE = 'quarantine-v2'
_ERROR = before.BeforeStateError


def _entry(parent, name, uid, limit, *, sync=False):
    fd = os.open(name, before._FILE, dir_fd=parent)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                info.st_uid != uid or info.st_gid != os.getegid() or
                stat.S_IMODE(info.st_mode) != 0o600 or not 0 <= info.st_size <= limit):
            raise _ERROR('unsafe_quarantine_entry')
        raw = bytearray()
        while len(raw) <= limit:
            chunk = os.read(fd, min(65536, limit + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        if sync:
            os.fsync(fd)
        stamp = before.historical._stamp(info)
        if (len(raw) != info.st_size or len(raw) > limit or
                stamp != before.historical._stamp(os.fstat(fd)) or
                stamp != before.historical._stamp(
                    os.stat(name, dir_fd=parent, follow_symlinks=False))):
            raise _ERROR('quarantine_entry_changed')
        return bytes(raw), stamp
    finally:
        os.close(fd)


def _inventory(fd, uid, *, sync=False):
    before._directory(fd, uid, private=True)
    stamp = before.historical._stamp(os.fstat(fd))
    names = journal._entries(fd)
    originals = {f'{i}.original' for i in range(len(core.MANAGED_PATHS))}
    if not names <= originals | {'manifest.json', 'receipt.json'}:
        raise _ERROR('unexpected_quarantine_entries')
    items, stamps, total = [], {}, 0
    for name in sorted(names):
        raw, stamps[name] = _entry(fd, name, uid,
                                   stage._MAX_ITEM if name in originals else before._LIMIT,
                                   sync=sync)
        if name in originals:
            total += len(raw)
        items.append(dict(name=name, size=len(raw), sha256=before._hash(raw)))
    if sync:
        os.fsync(fd)
    if (total > stage._MAX_TOTAL or journal._entries(fd) != names or
            stamp != before.historical._stamp(os.fstat(fd)) or
            any(s != before.historical._stamp(os.stat(n, dir_fd=fd, follow_symlinks=False))
                for n, s in stamps.items())):
        raise _ERROR('quarantine_tree_changed')
    return items


def _open_optional(stack, parent, name, uid):
    try:
        fd = os.open(name, before._DIR, dir_fd=parent)
    except FileNotFoundError:
        return None
    stack.callback(os.close, fd)
    before._directory(fd, uid, private=True)
    return fd


def _same_entry(parent, name, fd):
    if not os.path.samestat(os.fstat(fd),
                            os.stat(name, dir_fd=parent, follow_symlinks=False)):
        raise _ERROR('quarantine_directory_changed')


def _rename_noreplace(src_fd, src, dst_fd, dst):
    # Linux only. No check-then-rename or replacement fallback.
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        rename = libc.renameat2
    except AttributeError:
        raise _ERROR('quarantine_noreplace_unavailable') from None
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                       ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    if rename(src_fd, os.fsencode(src), dst_fd, os.fsencode(dst), 1) != 0:
        raise OSError(ctypes.get_errno(), 'quarantine rename failed')


def quarantine_unbound_before(handle, *, confirmation, verify):
    """Move only the exact unbound ABORTED snapshot, or verify a prior move.

    The trusted fixture verifier must independently establish the actual
    unchanged/restored terminal outcome and operator authorization. It is
    called on every attempt. The receipt binds journal and opaque bytes,
    not authenticity. No receipt or result authorizes journal clearing.
    """
    record = before._require_fixture(handle)
    handle._clean()
    if confirmation != 'QUARANTINE' or not callable(verify):
        raise _ERROR('quarantine_confirmation_required')
    if (record['phase'] != 'ABORTED' or record['snapshot_name'] is not None or
            record['before_receipt_sha256'] is not None or record['evidence'] is None):
        raise _ERROR('unbound_abort_required')
    source = before._name(record)
    if source == record['intent'].get('snapshot_name'):
        raise _ERROR('before_source_collision')
    name = 'unbound-' + record['transaction_id']
    receipt_name = name + '.json'
    frozen = journal.canonical(record)
    try:
        with ExitStack() as stack:
            base, ancestors = before._base(handle, stack)
            src = _open_optional(stack, base, source, handle.uid)
            q = _open_optional(stack, base, _NAMESPACE, handle.uid)
            dst = None if q is None else _open_optional(stack, q, name, handle.uid)
            if (src is None) == (dst is None):
                raise _ERROR('quarantine_source_destination_conflict')
            if src is not None:
                before.inspect_unbound_before(handle)
            fd = src if src is not None else dst
            items = _inventory(fd, handle.uid)
            receipt = journal.canonical(dict(
                schema=1, origin='unbound_before_quarantine',
                transaction_id=record['transaction_id'], operation=record['operation'],
                journal_sha256=before._hash(frozen), source=source, destination=name,
                items=items))
            if len(receipt) > before._LIMIT:
                raise _ERROR('quarantine_receipt_too_large')

            def check_receipt(*, sync=False):
                if q is None:
                    return False
                try:
                    raw, _ = _entry(q, receipt_name, handle.uid, before._LIMIT, sync=sync)
                except FileNotFoundError:
                    return False
                if raw != receipt:
                    raise _ERROR('quarantine_receipt_mismatch')
                return True

            had_receipt = check_receipt()
            if dst is not None and not had_receipt:
                raise _ERROR('quarantine_receipt_missing')
            # Do not permit the callback to mutate our expected journal.
            import json
            if verify(json.loads(frozen)) is not True:
                raise _ERROR('quarantine_outcome_not_verified')
            if journal.canonical(handle.record()) != frozen:
                raise _ERROR('quarantine_journal_changed')
            handle._clean()
            if q is not None:
                _same_entry(base, _NAMESPACE, q)
                if check_receipt() != had_receipt:
                    raise _ERROR('quarantine_receipt_changed')
            _same_entry(base if src is not None else q,
                        source if src is not None else name, fd)
            if _inventory(fd, handle.uid) != items:
                raise _ERROR('quarantine_tree_changed')
            # From the first possible publication/sync failure, require a
            # fresh recovery handle. Never remove a partial receipt.
            handle._failed = True
            if q is None:
                os.mkdir(_NAMESPACE, 0o700, dir_fd=base)
                q = _open_optional(stack, base, _NAMESPACE, handle.uid)
                if q is None:
                    raise _ERROR('quarantine_namespace_missing')
            _same_entry(base, _NAMESPACE, q)
            if os.fstat(q).st_dev != os.fstat(base).st_dev or os.fstat(fd).st_dev != os.fstat(q).st_dev:
                raise _ERROR('quarantine_cross_filesystem')
            if _inventory(fd, handle.uid, sync=True) != items:
                raise _ERROR('quarantine_tree_changed')
            if not had_receipt:
                before.storage._write_file(q, receipt_name, receipt,
                                           before._hash(receipt), handle.uid)
            if not check_receipt(sync=True):
                raise _ERROR('quarantine_receipt_missing')
            # Establish receipt and destination ancestry before moving.
            os.fsync(q)
            for ancestor in reversed(ancestors):
                os.fsync(ancestor)
            if src is not None:
                _same_entry(base, source, src)
                _same_entry(base, _NAMESPACE, q)
                if _inventory(src, handle.uid) != items:
                    raise _ERROR('quarantine_tree_changed')
                _rename_noreplace(base, source, q, name)
            _same_entry(q, name, fd)
            _same_entry(base, _NAMESPACE, q)
            if source in journal._entries(base):
                raise _ERROR('quarantine_source_destination_conflict')
            if _inventory(fd, handle.uid, sync=True) != items or not check_receipt(sync=True):
                raise _ERROR('quarantine_publication_changed')
            os.fsync(q)
            for ancestor in reversed(ancestors):
                os.fsync(ancestor)
            handle._failed = False
            handle.record()
            handle._clean()
            return 'quarantined' if src is not None else 'already_quarantined'
    except (OSError, before.storage.StagingError):
        raise _ERROR('quarantine_publication_failed') from None
