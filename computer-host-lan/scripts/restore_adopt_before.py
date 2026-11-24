"""Fixture-only receipt-bound current-before-state capture and verification.

Not a historical source or a legacy rollback manifest. No managed mutation,
service calls, credential reads or production integration. All observations
come from the disposable fixture and a trusted fixture service observer.
"""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import stat

import install_core as core
import historical_snapshot as historical
import payload_staging as storage
import restore_adopt_contract as contract
import restore_adopt_journal as journal
import restore_adopt_stage as stage

_LIMIT = 16 * 1024
_REQUIRED = frozenset((*core.APP_FILES, *core.SYSTEMD_PATHS))
_SERVICES = frozenset(('agent_active', 'agent_enabled', 'socket_active', 'socket_enabled'))
_DIR = historical._DIR_FLAGS
_FILE = historical._FILE_FLAGS


class BeforeStateError(ValueError):
    """Fixed diagnostics only."""


@dataclass(frozen=True)
class BeforeState:
    snapshot_name: str
    receipt_sha256: str
    files: tuple[historical.CandidateFile, ...] = field(repr=False)
    services: tuple[tuple[str, bool], ...]


def _require_fixture(handle):
    if (type(handle) is not journal.Handle or handle.root.resolve() == Path('/') or
            handle.root.resolve() != handle.root or handle.uid != os.geteuid()):
        raise BeforeStateError('fixture_transaction_required')
    return handle.record()


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _directory(fd, uid, *, private=False):
    info = os.fstat(fd)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or
            (stat.S_IMODE(info.st_mode) != 0o700 if private
             else bool(stat.S_IMODE(info.st_mode) & 0o7022))):
        raise BeforeStateError('unsafe_before_directory')


def _read(fd, name, uid, limit, *, mode, gid, installed=False):
    item = os.open(name, _FILE, dir_fd=fd)
    try:
        info = os.fstat(item)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                info.st_uid != uid or info.st_gid != gid or
                not 0 < info.st_size <= limit):
            raise BeforeStateError('unsafe_before_file')
        if stat.S_IMODE(info.st_mode) != mode:
            # Restore is not repair. Only otherwise safe installed regular
            # files receive the repair-oriented diagnostic; damaged backup
            # copies or unsafe objects retain the general refusal.
            raise BeforeStateError('current_state_permissions_damaged' if installed
                                   else 'unsafe_before_file')
        chunks = bytearray()
        while len(chunks) <= limit:
            block = os.read(item, min(65536, limit + 1 - len(chunks)))
            if not block:
                break
            chunks.extend(block)
        if (len(chunks) != info.st_size or
                historical._stamp(info) != historical._stamp(os.fstat(item)) or
                historical._stamp(info) != historical._stamp(
                    os.stat(name, dir_fd=fd, follow_symlinks=False))):
            raise BeforeStateError('before_file_changed')
        return bytes(chunks)
    finally:
        os.close(item)


def _current_file(handle, path):
    """Fixed allowlist, no-follow ancestor walk; ENOENT alone means absent."""
    if path not in core.MANAGED_PATHS:
        raise BeforeStateError('unexpected_managed_path')
    parts = Path(path.lstrip('/')).parts
    mode = 0o755 if path in core.APP_FILES else 0o644
    with ExitStack() as stack:
        fd = os.open(handle.root, _DIR)
        stack.callback(os.close, fd)
        _directory(fd, handle.uid)
        for component in parts[:-1]:
            try:
                fd = os.open(component, _DIR, dir_fd=fd)
            except FileNotFoundError:
                return historical.CandidateFile(path, None)
            stack.callback(os.close, fd)
            _directory(fd, handle.uid)
        try:
            os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            return historical.CandidateFile(path, None)
        data = _read(fd, parts[-1], handle.uid, stage._MAX_ITEM,
                     mode=mode, gid=os.getegid(), installed=True)
        return historical.CandidateFile(path, data, mode, handle.uid, os.getegid())


def _observe(handle, observer):
    # Never call systemd here. The controller must supply a verified
    # service observation, not infer active/absent from file presence.
    if not callable(observer):
        raise BeforeStateError('service_observation_required')
    data = observer()
    if (type(data) is not dict or set(data) != _SERVICES or
            any(type(value) is not bool for value in data.values())):
        raise BeforeStateError('invalid_service_observation')
    return dict(data)


def _validate_layout(record, files, services):
    present = {item.path for item in files if item.content is not None}
    if record['operation'] == 'adopt' or not present:
        if present or any(services.values()):
            raise BeforeStateError('expected_empty_before_state')
    else:
        if not _REQUIRED <= present:
            raise BeforeStateError('partial_before_state')
        agent = next(item.content for item in files if item.path == core.APP_FILES[0])
        if core.PROTOCOL_MARKER.findall(agent) != [b'computer-host-agent']:
            raise BeforeStateError('unsupported_before_protocol')
        avahi = next(item.content for item in files if item.path == core.AVAHI_PATH)
        if avahi is not None and (b'_computerhost._tcp' not in avahi or b'_linuxhost._tcp' in avahi):
            raise BeforeStateError('unsupported_before_avahi')
        if ((services['socket_active'] or services['socket_enabled']) and
                core.POWER_DROPIN not in present):
            raise BeforeStateError('inconsistent_before_services')
    if sum(len(item.content or b'') for item in files) > stage._MAX_TOTAL:
        raise BeforeStateError('before_state_too_large')


def _capture(handle, record, observer):
    services = _observe(handle, observer)
    files = tuple(_current_file(handle, path) for path in sorted(core.MANAGED_PATHS))
    _validate_layout(record, files, services)
    if _observe(handle, observer) != services:
        raise BeforeStateError('before_services_changed')
    return files, tuple(sorted(services.items()))


def _base(handle, stack):
    # The journal has already durably created the private backup ancestry.
    fd = os.open(handle.root, _DIR)
    stack.callback(os.close, fd)
    _directory(fd, handle.uid)
    ancestors = [fd]
    parts = Path(core.BACKUP_BASE.lstrip('/')).parts
    for i, name in enumerate(parts):
        fd = os.open(name, _DIR, dir_fd=fd)
        stack.callback(os.close, fd)
        _directory(fd, handle.uid, private=i == len(parts) - 1)
        ancestors.append(fd)
    return fd, ancestors


def _name(record):
    return 'snapshot-v2-' + record['transaction_id']


def _manifest(record, files, services):
    items = []
    for item in files:
        items.append(dict(path=item.path, mode=item.mode, uid=item.uid, gid=item.gid,
                          size=None if item.content is None else len(item.content),
                          sha256=None if item.content is None else _hash(item.content)))
    # Intentionally not schema 1: legacy readers must refuse it.
    return dict(schema=2, origin='protected_v2_before_state',
                transaction_id=record['transaction_id'], operation=record['operation'],
                intent=record['intent'], items=items, services=dict(services))


def _receipt(record, name, manifest):
    return dict(schema_version=2, origin='protected_v2_before_state',
                snapshot_name=name, transaction_id=record['transaction_id'],
                operation=record['operation'], capture_phase='STAGED',
                staged_plan_sha256=record['evidence']['staged_plan_sha256'],
                manifest_sha256=_hash(manifest), release_authenticity='not_verified')


def _inspect(handle, record, name, expected_digest):
    if (name != _name(record) or name == record['intent'].get('snapshot_name') or
            not contract._digest(expected_digest)):
        raise BeforeStateError('invalid_before_reference')
    with ExitStack() as stack:
        base, _ = _base(handle, stack)
        fd = os.open(name, _DIR, dir_fd=base)
        stack.callback(os.close, fd)
        _directory(fd, handle.uid, private=True)
        before = historical._stamp(os.fstat(fd))
        gid = os.getegid()
        receipt = _read(fd, 'receipt.json', handle.uid, _LIMIT, mode=0o600, gid=gid)
        if _hash(receipt) != expected_digest:
            raise BeforeStateError('before_receipt_digest_mismatch')
        raw = _read(fd, 'manifest.json', handle.uid, _LIMIT, mode=0o600, gid=gid)
        if receipt != journal.canonical(_receipt(record, name, raw)):
            raise BeforeStateError('before_receipt_binding_mismatch')
        data = contract._decode(raw, _LIMIT)
        if (set(data) != {'schema', 'origin', 'transaction_id', 'operation',
                          'intent', 'items', 'services'} or
                type(data['schema']) is not int or data['schema'] != 2 or
                type(data['items']) is not list or
                len(data['items']) != len(core.MANAGED_PATHS)):
            raise BeforeStateError('invalid_before_manifest')
        services = data['services']
        if (type(services) is not dict or set(services) != _SERVICES or
                any(type(value) is not bool for value in services.values())):
            raise BeforeStateError('invalid_before_services')
        files = []
        entries = {'manifest.json', 'receipt.json'}
        total = 0
        for i, (path, item) in enumerate(zip(sorted(core.MANAGED_PATHS), data['items'])):
            if (type(item) is not dict or set(item) !=
                    {'path', 'mode', 'uid', 'gid', 'size', 'sha256'} or item['path'] != path):
                raise BeforeStateError('invalid_before_item')
            if item['sha256'] is None:
                if any(item[key] is not None for key in ('mode', 'uid', 'gid', 'size')):
                    raise BeforeStateError('invalid_absent_before_item')
                files.append(historical.CandidateFile(path, None))
                continue
            mode = 0o755 if path in core.APP_FILES else 0o644
            if (not contract._digest(item['sha256']) or
                    any(type(item[key]) is not int for key in ('mode', 'uid', 'gid', 'size')) or
                    (item['mode'], item['uid'], item['gid']) != (mode, handle.uid, gid) or
                    not 0 < item['size'] <= stage._MAX_ITEM):
                raise BeforeStateError('invalid_before_metadata')
            filename = f'{i}.original'
            content = _read(fd, filename, handle.uid, stage._MAX_ITEM, mode=0o600, gid=gid)
            total += len(content)
            if (total > stage._MAX_TOTAL or len(content) != item['size'] or
                    _hash(content) != item['sha256']):
                raise BeforeStateError('before_content_mismatch')
            files.append(historical.CandidateFile(path, content, mode, handle.uid, gid))
            entries.add(filename)
        files = tuple(files)
        _validate_layout(record, files, services)
        if (raw != journal.canonical(_manifest(record, files, services)) or
                journal._entries(fd) != entries or before != historical._stamp(os.fstat(fd)) or
                not os.path.samestat(os.fstat(fd), os.stat(name, dir_fd=base, follow_symlinks=False))):
            raise BeforeStateError('before_snapshot_changed')
        return BeforeState(name, expected_digest, files, tuple(sorted(services.items())))


def capture_before(handle, observer):
    """Publish a new protected receipt before the journal can bind it.

    The exact transaction-derived name is reserved; never replace it.
    Uncertain/partial snapshots are preserved, not reused. This fixture
    intentionally captures no identity, token, account or owner marker.
    """
    record = _require_fixture(handle)
    handle._clean()
    if handle._recovering or record['phase'] != 'STAGED':
        raise BeforeStateError('before_capture_requires_staged')
    stage.read_plan(handle)
    name = _name(record)
    if name == record['intent'].get('snapshot_name'):
        raise BeforeStateError('before_source_collision')
    try:
        files, services = _capture(handle, record, observer)
        raw = journal.canonical(_manifest(record, files, services))
        receipt = journal.canonical(_receipt(record, name, raw))
        if max(len(raw), len(receipt)) > _LIMIT:
            raise BeforeStateError('before_manifest_too_large')
        with ExitStack() as stack:
            base, ancestors = _base(handle, stack)
            # Exclusive mkdir plus fixed name: no overwrite, including
            # a previously interrupted capture for this transaction.
            handle._failed = True
            os.mkdir(name, 0o700, dir_fd=base)
            os.fsync(base)
            fd = os.open(name, _DIR, dir_fd=base)
            stack.callback(os.close, fd)
            os.fchmod(fd, 0o700)
            _directory(fd, handle.uid, private=True)
            for i, item in enumerate(files):
                if item.content is not None:
                    storage._write_file(fd, f'{i}.original', item.content,
                                        _hash(item.content), handle.uid)
            storage._write_file(fd, 'manifest.json', raw, _hash(raw), handle.uid)
            # Receipt published last; no journal digest until all syncs pass.
            storage._write_file(fd, 'receipt.json', receipt, _hash(receipt), handle.uid)
            os.fsync(fd)
            for ancestor in reversed(ancestors):
                os.fsync(ancestor)
            result = _inspect(handle, record, name, _hash(receipt))
            if _capture(handle, record, observer) != (result.files, result.services):
                raise BeforeStateError('before_state_changed_during_capture')
            handle._failed = False
            return result
    except (OSError, contract.ContractError, storage.StagingError):
        raise BeforeStateError('before_capture_failed') from None


def read_before(handle, *, proposed=None):
    """Pin verified rollback bytes from the immutable journal receipt digest.

    At STAGED only the freshly produced capture reference is accepted.
    All later reads use the durable record and refuse caller overrides.
    """
    record = _require_fixture(handle)
    if record['phase'] == 'STAGED':
        if type(proposed) is not BeforeState:
            raise BeforeStateError('before_reference_required')
        name, digest = proposed.snapshot_name, proposed.receipt_sha256
    else:
        if proposed is not None:
            raise BeforeStateError('before_override_refused')
        name, digest = record['snapshot_name'], record['before_receipt_sha256']
    try:
        return _inspect(handle, record, name, digest)
    except (OSError, contract.ContractError):
        raise BeforeStateError('before_snapshot_unavailable') from None


def matches_current(handle, before, observer):
    """Compare actual fixture managed bytes, metadata and service observation.

    Not credential equality, service quiescence proof, owner-marker
    authorization, or successful recovery. No mutations.
    """
    record = _require_fixture(handle)
    try:
        return _capture(handle, record, observer) == (before.files, before.services)
    except (OSError, BeforeStateError):
        return False


@dataclass(frozen=True)
class UnboundBeforeObservation:
    """Internal layout observation, not a valid receipt or cleanup authority."""
    status: str
    manifest_present: bool = False
    receipt_present: bool = False
    original_count: int = 0


def inspect_unbound_before(handle):
    """Identify this verified-abort candidate's unbound forensic directory.

    Read-only, under the existing fixture locks. A complete-looking tree
    is not authenticated and cannot be rebound. No rename, deletion,
    new receipt, journal transition, or proof of unchanged managed state.
    A future explicit quarantine operation must independently verify
    the terminal outcome and publication durability.
    """
    record = _require_fixture(handle)
    handle._clean()
    if (record['phase'] != 'ABORTED' or record['snapshot_name'] is not None or
            record['before_receipt_sha256'] is not None):
        raise BeforeStateError('unbound_abort_required')
    name = _name(record)
    if name == record['intent'].get('snapshot_name'):
        raise BeforeStateError('before_source_collision')
    try:
        with ExitStack() as stack:
            base, _ = _base(handle, stack)
            try:
                fd = os.open(name, _DIR, dir_fd=base)
            except FileNotFoundError:
                return UnboundBeforeObservation('absent')
            stack.callback(os.close, fd)
            _directory(fd, handle.uid, private=True)
            # Capture cannot start before STAGED. An initial abort with
            # no stage evidence cannot explain this directory.
            if record['evidence'] is None:
                raise BeforeStateError('unbound_snapshot_conflicts_with_journal')
            before = historical._stamp(os.fstat(fd))
            names = journal._entries(fd)
            originals = {f'{i}.original' for i in range(len(core.MANAGED_PATHS))}
            if not names <= originals | {'manifest.json', 'receipt.json'}:
                raise BeforeStateError('unexpected_unbound_entries')
            total = 0
            for item in sorted(names):
                file_fd = os.open(item, _FILE, dir_fd=fd)
                try:
                    info = os.fstat(file_fd)
                    limit = stage._MAX_ITEM if item in originals else _LIMIT
                    # Truncated/empty files are expected forensic evidence.
                    # Never parse or trust their content in this path.
                    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                            info.st_uid != handle.uid or info.st_gid != os.getegid() or
                            stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > limit or
                            historical._stamp(info) != historical._stamp(
                                os.stat(item, dir_fd=fd, follow_symlinks=False))):
                        raise BeforeStateError('unsafe_unbound_entry')
                    if item in originals:
                        total += info.st_size
                finally:
                    os.close(file_fd)
            if (total > stage._MAX_TOTAL or journal._entries(fd) != names or
                    historical._stamp(os.fstat(fd)) != before or
                    not os.path.samestat(os.fstat(fd),
                        os.stat(name, dir_fd=base, follow_symlinks=False))):
                raise BeforeStateError('unbound_snapshot_changed')
            return UnboundBeforeObservation('preserved_unbound',
                                            'manifest.json' in names,
                                            'receipt.json' in names,
                                            len(names & originals))
    except OSError:
        raise BeforeStateError('unbound_snapshot_unavailable') from None
