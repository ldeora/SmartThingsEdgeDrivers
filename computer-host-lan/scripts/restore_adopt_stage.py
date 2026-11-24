"""Experimental complete managed-plan staging for schema-2 fixture journals.

Stage content is data only. The trusted caller must authenticate it before
staging. No production caller, historical source execution, managed writes,
or automatic cleanup of interrupted publications.
"""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import stat

import install_core as core
import payload_staging as legacy_stage
import restore_adopt_contract as contract
import restore_adopt_journal as journal

_MAX_MANIFEST = 16 * 1024
_MAX_ITEM = 2 * 1024 * 1024
_MAX_TOTAL = 8 * 1024 * 1024
_REQUIRED = frozenset((*core.APP_FILES, *core.SYSTEMD_PATHS))
_SERVICE = frozenset(('agent_active', 'agent_enabled', 'socket_active', 'socket_enabled'))


class PlanError(ValueError):
    """Fixed non-sensitive diagnostics."""


@dataclass(frozen=True)
class Plan:
    digest: str
    files: tuple[core.Change, ...] = field(repr=False)
    services: tuple[tuple[str, bool], ...]


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _validate_manifest(data, record):
    if (type(data) is not dict or set(data) != {
            'schema', 'transaction_id', 'operation', 'intent', 'items', 'services'} or
            type(data['schema']) is not int or data['schema'] != 1 or
            data['transaction_id'] != record['transaction_id'] or
            data['operation'] != record['operation'] or data['intent'] != record['intent'] or
            type(data['items']) is not list or len(data['items']) != len(core.MANAGED_PATHS)):
        raise PlanError('invalid_plan_manifest')
    services = data['services']
    if (type(services) is not dict or set(services) != _SERVICE or
            any(type(value) is not bool for value in services.values())):
        raise PlanError('invalid_plan_services')
    paths = sorted(core.MANAGED_PATHS)
    for i, (item, path) in enumerate(zip(data['items'], paths)):
        if (type(item) is not dict or set(item) != {'path', 'present', 'mode', 'size', 'sha256'} or
                item['path'] != path or type(item['present']) is not bool):
            raise PlanError('invalid_plan_item')
        if item['present']:
            mode = 0o755 if path in core.APP_FILES else 0o644
            if (type(item['mode']) is not int or item['mode'] != mode or
                    type(item['size']) is not int or not 0 < item['size'] <= _MAX_ITEM or
                    not contract._digest(item['sha256'])):
                raise PlanError('invalid_plan_item')
        elif (path in _REQUIRED or any(item[key] is not None for key in ('mode', 'size', 'sha256'))):
            raise PlanError('invalid_absent_item')
    present = {item['path'] for item in data['items'] if item['present']}
    if ((services['socket_active'] or services['socket_enabled']) and
            core.POWER_DROPIN not in present):
        raise PlanError('inconsistent_plan_services')
    if record['operation'] == 'adopt':
        power = record['intent']['power'] == 'enable'
        if (services != dict(agent_active=True, agent_enabled=True,
                             socket_active=power, socket_enabled=power) or
                (core.POWER_DROPIN in present) != power or
                (core.WOL_DROPIN in present) != (record['intent']['wol_interface'] is not None)):
            raise PlanError('adopt_plan_intent_mismatch')
    if sum(item['size'] or 0 for item in data['items']) > _MAX_TOTAL:
        raise PlanError('plan_too_large')
    return data


def _encode_plan(record, files, services):
    if type(files) is not tuple or any(type(item) is not core.Change for item in files):
        raise PlanError('invalid_plan_files')
    by_path = {item.path: item for item in files}
    if len(files) != len(by_path) or set(by_path) != core.MANAGED_PATHS:
        raise PlanError('incomplete_plan')
    items = []
    contents = {}
    for i, path in enumerate(sorted(by_path)):
        item = by_path[path]
        if item.content is None:
            items.append(dict(path=path, present=False, mode=None, size=None, sha256=None))
        elif type(item.content) is bytes and 0 < len(item.content) <= _MAX_ITEM:
            items.append(dict(path=path, present=True, mode=item.mode,
                              size=len(item.content), sha256=_hash(item.content)))
            contents[f'{i}.data'] = item.content
        else:
            raise PlanError('invalid_plan_content')
    manifest = _validate_manifest(dict(schema=1, transaction_id=record['transaction_id'],
                                      operation=record['operation'], intent=record['intent'],
                                      items=items, services=services), record)
    raw = journal.canonical(manifest)
    if len(raw) > _MAX_MANIFEST:
        raise PlanError('plan_manifest_too_large')
    return raw, contents


def _read(directory, name, uid, limit):
    fd = os.open(name, legacy_stage._READ_FLAGS, dir_fd=directory)
    try:
        legacy_stage._check_private_file(fd, uid)
        before = os.fstat(fd)
        if not 0 < before.st_size <= limit:
            raise PlanError('invalid_plan_file_size')
        data = bytearray()
        while len(data) <= limit:
            chunk = os.read(fd, min(65536, limit + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        after = os.fstat(fd)
        def stamp(st):
            return (st.st_dev, st.st_ino, st.st_size, st.st_mode, st.st_uid,
                    st.st_gid, st.st_nlink, st.st_mtime_ns, st.st_ctime_ns)
        if len(data) != before.st_size or stamp(before) != stamp(after):
            raise PlanError('plan_file_changed')
        return bytes(data)
    finally:
        os.close(fd)


def _inspect(directory, record, uid, expected_digest):
    legacy_stage._check_directory(directory, uid, private=True)
    raw = _read(directory, 'manifest.json', uid, _MAX_MANIFEST)
    if _hash(raw) != expected_digest:
        raise PlanError('plan_manifest_digest_mismatch')
    data = _validate_manifest(contract._decode(raw, _MAX_MANIFEST), record)
    if journal.canonical(data) != raw:
        raise PlanError('noncanonical_plan_manifest')
    expected = {'manifest.json'}
    files = []
    for i, item in enumerate(data['items']):
        if not item['present']:
            files.append(core.Change(item['path'], None))
            continue
        name = f'{i}.data'
        content = _read(directory, name, uid, _MAX_ITEM)
        if len(content) != item['size'] or _hash(content) != item['sha256']:
            raise PlanError('plan_file_digest_mismatch')
        expected.add(name)
        files.append(core.Change(item['path'], content, item['mode']))
    if journal._entries(directory) != expected:
        raise PlanError('unexpected_plan_entries')
    return Plan(expected_digest, tuple(files), tuple(sorted(data['services'].items())))


def _locked(handle, *, create):
    # Fixed staging base, same lock and visibility to the v1 journal guard.
    if type(handle) is not journal.Handle:
        raise PlanError('fixture_transaction_required')
    handle.record()
    return legacy_stage._lock_stage(handle.root, handle.uid, create=create)


def _sync_stage_ancestors(handle):
    with ExitStack() as stack:
        fd = os.open(handle.root, legacy_stage._DIR_FLAGS)
        stack.callback(os.close, fd)
        legacy_stage._check_directory(fd, handle.uid, private=False)
        ancestors = [fd]
        for i, component in enumerate(legacy_stage._DEST):
            fd = os.open(component, legacy_stage._DIR_FLAGS, dir_fd=fd)
            stack.callback(os.close, fd)
            legacy_stage._check_directory(fd, handle.uid, private=i >= 2)
            ancestors.append(fd)
        for fd in reversed(ancestors):
            os.fsync(fd)


def stage_plan(handle, files, services):
    """Publish complete pinned data before STAGED; return manifest digest.

    A killed writer leaves pending-plan-ID or ready-plan-ID in the same
    protected namespace. A second stage is refused, not overwritten.
    """
    record = handle.record()
    if record['phase'] != 'INSPECTED' or handle._recovering:
        raise PlanError('stage_requires_forward_inspected')
    raw, contents = _encode_plan(record, files, services)
    digest = _hash(raw)
    base, lock = _locked(handle, create=True)
    try:
        if journal._entries(base) != {legacy_stage._LOCK}:
            raise PlanError('existing_stage_requires_recovery')
        pending = 'pending-plan-' + record['transaction_id']
        ready = 'ready-plan-' + record['transaction_id']
        # A failed publication is uncertain even if the final name
        # became visible. Poison this forward handle until a new recovery
        # context is opened. Never proceed to STAGED on a failed fsync.
        handle._failed = True
        os.mkdir(pending, 0o700, dir_fd=base)
        os.fsync(base)
        directory = os.open(pending, legacy_stage._DIR_FLAGS, dir_fd=base)
        try:
            os.fchmod(directory, 0o700)
            for name, content in sorted(contents.items()):
                legacy_stage._write_file(directory, name, content, _hash(content), handle.uid)
            legacy_stage._write_file(directory, 'manifest.json', raw, digest, handle.uid)
            _inspect(directory, record, handle.uid, digest)
            os.fsync(directory)
            if journal._entries(base) != {legacy_stage._LOCK, pending}:
                raise PlanError('unexpected_stage_entries')
            os.rename(pending, ready, src_dir_fd=base, dst_dir_fd=base)
            _sync_stage_ancestors(handle)
            handle._failed = False
            return digest
        finally:
            os.close(directory)
    except OSError:
        raise PlanError('stage_publication_failed') from None
    finally:
        os.close(lock)
        os.close(base)


def read_plan(handle, *, initial_digest=None):
    """Return checked immutable bytes, never a path to execute or reopen.

    At INSPECTED the caller must pass the independently produced stage
    digest; later the immutable journal supplies it. Recovery callers
    may inspect but never resume forward work.
    """
    record = handle.record()
    if record['phase'] == 'INSPECTED':
        digest = initial_digest
    else:
        evidence = record['evidence']
        digest = evidence['staged_plan_sha256'] if evidence is not None else None
        if initial_digest is not None:
            raise PlanError('unexpected_stage_digest')
    if not contract._digest(digest):
        raise PlanError('missing_stage_digest')
    base, lock = _locked(handle, create=False)
    try:
        ready = 'ready-plan-' + record['transaction_id']
        if journal._entries(base) != {legacy_stage._LOCK, ready}:
            raise PlanError('unexpected_stage_entries')
        directory = os.open(ready, legacy_stage._DIR_FLAGS, dir_fd=base)
        try:
            plan = _inspect(directory, record, handle.uid, digest)
            if not os.path.samestat(os.fstat(directory),
                                    os.stat(ready, dir_fd=base, follow_symlinks=False)):
                raise PlanError('stage_identity_changed')
            return plan
        finally:
            os.close(directory)
    except OSError:
        raise PlanError('stage_unavailable') from None
    finally:
        os.close(lock)
        os.close(base)


def _retirement_entries(directory, record, uid, *, partial):
    """Validate the entire flat tree before deleting any entry.

    Incomplete publications/deletions can have truncated files. Their
    names, types, ownership, permissions, link count and sizes must still
    be safe. Complete ready stages with journal evidence are checked by
    _inspect before the irreversible rename.
    """
    legacy_stage._check_directory(directory, uid, private=True)
    names = journal._entries(directory)
    allowed = {'manifest.json'} | {f'{i}.data' for i in range(len(core.MANAGED_PATHS))}
    if not names <= allowed:
        raise PlanError('unexpected_retirement_entries')
    total = 0
    stamps = {}
    for name in sorted(names):
        fd = os.open(name, legacy_stage._READ_FLAGS, dir_fd=directory)
        try:
            legacy_stage._check_private_file(fd, uid)
            info = os.fstat(fd)
            limit = _MAX_MANIFEST if name == 'manifest.json' else _MAX_ITEM
            if info.st_size > limit or (not partial and info.st_size == 0):
                raise PlanError('invalid_retirement_file_size')
            if name != 'manifest.json':
                total += info.st_size
            stamps[name] = info
        finally:
            os.close(fd)
    if total > _MAX_TOTAL or journal._entries(directory) != names:
        raise PlanError('retirement_entries_changed')
    return stamps


def retire_terminal_plan(handle):
    """Retire only this terminal transaction's private stage.

    No forward work, recursive traversal, or deletion of foreign entries.
    A ready stage with a journal digest must pass complete validation
    before rename. A pending stage or an unbound ready stage can only
    belong to an ABORTED transaction with no stage evidence. Retiring
    directories are retryable, including partially deleted contents.
    """
    record = handle.record()
    handle._clean()
    if record['phase'] not in contract._TERMINAL:
        raise PlanError('terminal_stage_required')
    try:
        base, lock = _locked(handle, create=False)
    except legacy_stage.StagingConflict as exc:
        if str(exc) == 'trusted staging root missing':
            return
        raise
    try:
        entries = journal._entries(base) - {legacy_stage._LOCK}
        if not entries:
            _sync_stage_ancestors(handle)
            return
        txid = record['transaction_id']
        pending, ready, retiring = (prefix + txid for prefix in
                                    ('pending-plan-', 'ready-plan-', 'retiring-plan-'))
        if len(entries) != 1 or not entries <= {pending, ready, retiring}:
            raise PlanError('foreign_or_ambiguous_stage')
        name, = entries
        evidence = record['evidence']
        if name == pending and (record['phase'] != 'ABORTED' or evidence is not None):
            raise PlanError('pending_stage_conflicts_with_journal')
        if evidence is None and record['phase'] != 'ABORTED':
            raise PlanError('unbound_terminal_stage')
        directory = os.open(name, legacy_stage._DIR_FLAGS, dir_fd=base)
        try:
            if name == ready and evidence is not None:
                _inspect(directory, record, handle.uid, evidence['staged_plan_sha256'])
            stamps = _retirement_entries(directory, record, handle.uid,
                                         partial=name != ready or evidence is None)
            if (not os.path.samestat(os.fstat(directory),
                                    os.stat(name, dir_fd=base, follow_symlinks=False)) or
                    journal._entries(base) != {legacy_stage._LOCK, name}):
                raise PlanError('stage_identity_changed')
            # Retiring is a durable authorization boundary: no content
            # is removed until the new name is synced. Retry also syncs
            # an already-visible retiring name after an uncertain rename.
            if name != retiring:
                os.rename(name, retiring, src_dir_fd=base, dst_dir_fd=base)
            _sync_stage_ancestors(handle)
            for filename, before in sorted(stamps.items()):
                now = os.stat(filename, dir_fd=directory, follow_symlinks=False)
                if (not os.path.samestat(before, now) or
                        (before.st_mode, before.st_uid, before.st_nlink, before.st_size,
                         before.st_mtime_ns, before.st_ctime_ns) !=
                        (now.st_mode, now.st_uid, now.st_nlink, now.st_size,
                         now.st_mtime_ns, now.st_ctime_ns)):
                    raise PlanError('retirement_file_changed')
                os.unlink(filename, dir_fd=directory)
            os.fsync(directory)
            if (journal._entries(directory) or
                    not os.path.samestat(os.fstat(directory),
                        os.stat(retiring, dir_fd=base, follow_symlinks=False))):
                raise PlanError('retirement_directory_changed')
            os.rmdir(retiring, dir_fd=base)
            _sync_stage_ancestors(handle)
        finally:
            os.close(directory)
    except OSError:
        raise PlanError('stage_retirement_failed') from None
    finally:
        os.close(lock)
        os.close(base)
