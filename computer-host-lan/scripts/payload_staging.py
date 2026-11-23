#!/usr/bin/env python3
"""Isolated, no-execute protected Linux installer staging primitives.

Only an independently authenticated root-owned launcher may eventually call
this module. Never execute it with sudo from an untrusted source checkout.
No CLI, privilege escalation, subprocess, service or installer mutation.
"""
from __future__ import annotations

import fcntl
import hashlib
import hmac
import os
from pathlib import Path
import re
import stat
from typing import Mapping

from transaction_journal import TransactionHandle

PAYLOAD_FILES = frozenset((
    'agent/linux_host_agent.py',
    'agent/power_helper.py',
    'agent/systemd/linux-host-agent.service',
    'agent/systemd/linux-host-agent-power.service',
    'agent/systemd/linux-host-agent-power.socket',
    'agent/systemd/enable-power.conf',
    'agent/systemd/avahi-linux-host-agent.service',
    'scripts/install_core.py',
    'scripts/runtime_verify.py',
    'scripts/transaction_journal.py',
))
# This namespace is fixed for the installer lifecycle: it is NOT agent state.
_DEST = ('var', 'lib', 'computer-host-installer', 'staging')
_LOCK = 'stage.lock'
_PENDING = 'pending-'
_READY = 'ready-'
_SHA256 = re.compile(r'[0-9a-f]{64}\Z')
_TXID = re.compile(r'[0-9a-f]{32}\Z')
_MAX_FILE_BYTES = 1024 * 1024
_MAX_TOTAL_BYTES = 4 * 1024 * 1024
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_DIRS = frozenset(('agent', 'agent/systemd', 'scripts'))


class StagingError(RuntimeError):
    """Fixed, non-sensitive errors; never include source content or paths."""


class StagingConflict(StagingError):
    pass


def _safe_manifest(expected: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(expected, Mapping) or set(expected) != PAYLOAD_FILES:
        raise StagingError('invalid trusted payload manifest')
    if any(type(value) is not str or not _SHA256.fullmatch(value)
           for value in expected.values()):
        raise StagingError('invalid trusted payload digest')
    return dict(expected)


def _transaction_id(transaction: TransactionHandle, root: Path,
                    owner_uid: int, *, phases: tuple[str, ...]) -> str:
    if (not isinstance(transaction, TransactionHandle) or
            transaction._journal.root != root or
            transaction._journal.owner_uid != owner_uid):
        raise StagingError('validated journal owner required')
    # transaction_id consults the durable journal and checks that this
    # process still owns the exclusive transaction lifetime lock.
    identifier = transaction.transaction_id
    if not _TXID.fullmatch(identifier) or transaction._record()['phase'] not in phases:
        raise StagingConflict('journal phase does not permit staging operation')
    return identifier


def _check_directory(fd: int, uid: int, *, private: bool) -> None:
    info = os.fstat(fd)
    permissions = stat.S_IMODE(info.st_mode)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or
            (permissions != 0o700 if private else bool(permissions & 0o022))):
        raise StagingError('unsafe staging directory')


def _walk_destination(root: Path, uid: int, *, create: bool) -> int:
    """Follow only constant no-link directory components from trusted root."""
    fd = None
    try:
        fd = os.open(root, _DIR_FLAGS)
        _check_directory(fd, uid, private=False)
        for index, component in enumerate(_DEST):
            private = index >= 2
            mode = 0o700 if private else 0o755
            created = False
            try:
                child = os.open(component, _DIR_FLAGS, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise StagingConflict('trusted staging root missing')
                os.mkdir(component, mode, dir_fd=fd)
                os.fsync(fd)
                child = os.open(component, _DIR_FLAGS, dir_fd=fd)
                created = True
            try:
                if os.fstat(child).st_uid != uid:
                    raise StagingError('unsafe staging directory owner')
                if created:
                    os.fchmod(child, mode)
                    os.fsync(child)
                _check_directory(child, uid, private=private)
            except Exception:
                os.close(child)
                raise
            os.close(fd)
            fd = child
        result, fd = fd, None
        return result
    except (StagingError, StagingConflict):
        raise
    except OSError:
        raise StagingError('unsafe or unavailable staging directory') from None
    finally:
        if fd is not None:
            os.close(fd)


def _open_source_root(source: Path) -> int:
    if not source.is_absolute() or '..' in source.parts:
        raise StagingError('invalid source location')
    fd = None
    try:
        fd = os.open('/', _DIR_FLAGS)
        for component in source.parts[1:]:
            child = os.open(component, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        result, fd = fd, None
        return result
    except OSError:
        raise StagingError('unsafe source directory') from None
    finally:
        if fd is not None:
            os.close(fd)


def _read_verified_file(source_fd: int, relative: str, digest: str) -> bytes:
    directory = os.dup(source_fd)
    try:
        parts = relative.split('/')
        for component in parts[:-1]:
            child = os.open(component, _DIR_FLAGS, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(parts[-1], _READ_FLAGS, dir_fd=directory)
        try:
            info = os.fstat(fd)
            # Source hard links are intentionally allowed: bytes are hashed
            # and frozen in memory. The PROTECTED output still requires nlink=1.
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= _MAX_FILE_BYTES:
                raise StagingError('unsafe payload source file')
            chunks = bytearray()
            while len(chunks) <= _MAX_FILE_BYTES:
                block = os.read(fd, min(65536, _MAX_FILE_BYTES + 1 - len(chunks)))
                if not block:
                    break
                chunks.extend(block)
            if (len(chunks) != info.st_size or len(chunks) > _MAX_FILE_BYTES or
                    not hmac.compare_digest(hashlib.sha256(chunks).hexdigest(), digest)):
                raise StagingError('payload digest mismatch')
            return bytes(chunks)
        finally:
            os.close(fd)
    except StagingError:
        raise
    except OSError:
        raise StagingError('unsafe payload source read') from None
    finally:
        os.close(directory)


def _check_private_file(fd: int, uid: int) -> None:
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != uid or
            info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
        raise StagingError('unsafe private staged file')


def _lock_stage(root: Path, uid: int, *, create: bool) -> tuple[int, int]:
    base = _walk_destination(root, uid, create=create)
    try:
        flags = os.O_RDWR | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC
        if create:
            flags |= os.O_CREAT
        lock = os.open(_LOCK, flags, 0o600, dir_fd=base)
        try:
            _check_private_file(lock, uid)
            if os.fstat(lock).st_size:
                raise StagingError('unsafe staging lock contents')
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise StagingConflict('another staging operation is active') from None
            return base, lock
        except Exception:
            os.close(lock)
            raise
    except (StagingError, StagingConflict):
        os.close(base)
        raise
    except OSError:
        os.close(base)
        raise StagingError('unsafe staging lock') from None


def _write_file(stage_fd: int, relative: str, content: bytes,
                digest: str, uid: int) -> None:
    directory = os.dup(stage_fd)
    try:
        parts = relative.split('/')
        for component in parts[:-1]:
            try:
                child = os.open(component, _DIR_FLAGS, dir_fd=directory)
            except FileNotFoundError:
                os.mkdir(component, 0o700, dir_fd=directory)
                os.fsync(directory)
                child = os.open(component, _DIR_FLAGS, dir_fd=directory)
                if os.fstat(child).st_uid != uid:
                    os.close(child)
                    raise StagingError('unsafe staged directory owner')
                os.fchmod(child, 0o700)
                os.fsync(child)
            _check_directory(child, uid, private=True)
            os.close(directory)
            directory = child
        fd = os.open(parts[-1], os.O_RDWR | os.O_CREAT | os.O_EXCL |
                     os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory)
        try:
            os.fchmod(fd, 0o600)
            _check_private_file(fd, uid)
            offset = 0
            while offset < len(content):
                count = os.write(fd, content[offset:])
                if count <= 0:
                    raise StagingError('incomplete staged payload write')
                offset += count
            os.fsync(fd)
            os.lseek(fd, 0, os.SEEK_SET)
            verified = bytearray()
            while len(verified) < len(content):
                block = os.read(fd, len(content) - len(verified))
                if not block:
                    break
                verified.extend(block)
            if (len(verified) != len(content) or
                    not hmac.compare_digest(hashlib.sha256(verified).hexdigest(), digest)):
                raise StagingError('staged payload digest mismatch')
        finally:
            os.close(fd)
        os.fsync(directory)
    finally:
        os.close(directory)


def _inspect_tree(directory: int, uid: int, trusted_hashes: Mapping[str, str] | None) -> None:
    """Validate allowlisted structure without following links.

    With hashes: require every file, complete verified bundle.
    Without hashes: permit partial files/dirs for interrupted pending cleanup,
    but still reject any unexpected name, unsafe file type, link or owner.
    """
    found = set()
    total = 0

    def walk(fd: int, prefix: str) -> None:
        nonlocal total
        _check_directory(fd, uid, private=True)
        for name in os.listdir(fd):
            if '/' in name or name in ('.', '..'):
                raise StagingError('unexpected staged entry')
            relative = prefix + name
            if relative in _DIRS:
                child = os.open(name, _DIR_FLAGS, dir_fd=fd)
                try:
                    walk(child, relative + '/')
                finally:
                    os.close(child)
            elif relative in PAYLOAD_FILES:
                file_fd = os.open(name, _READ_FLAGS, dir_fd=fd)
                try:
                    _check_private_file(file_fd, uid)
                    info = os.fstat(file_fd)
                    if info.st_size < 0 or info.st_size > _MAX_FILE_BYTES:
                        raise StagingError('unsafe staged file size')
                    total += info.st_size
                    if total > _MAX_TOTAL_BYTES:
                        raise StagingError('staged payload too large')
                    if trusted_hashes is not None:
                        data = bytearray()
                        while len(data) < info.st_size:
                            chunk = os.read(file_fd, min(65536, info.st_size - len(data)))
                            if not chunk:
                                break
                            data.extend(chunk)
                        if (len(data) != info.st_size or
                                not hmac.compare_digest(
                                    hashlib.sha256(data).hexdigest(),
                                    trusted_hashes[relative])):
                            raise StagingError('staged payload re-verification failed')
                    found.add(relative)
                finally:
                    os.close(file_fd)
            else:
                raise StagingError('unexpected staged entry')

    try:
        walk(directory, '')
    except StagingError:
        raise
    except OSError:
        raise StagingError('unsafe staged tree') from None
    if trusted_hashes is not None and found != PAYLOAD_FILES:
        raise StagingError('incomplete staged payload')


def _validate_identity(base: int, stage_fd: int, name: str, uid: int) -> None:
    if not (_TXID.fullmatch(name[len(_READY):]) if name.startswith(_READY) else False):
        raise StagingError('invalid ready payload identity')
    try:
        visible = os.stat(name, dir_fd=base, follow_symlinks=False)
        opened = os.fstat(stage_fd)
    except OSError:
        raise StagingError('ready payload is unavailable') from None
    _check_directory(stage_fd, uid, private=True)
    if (not stat.S_ISDIR(visible.st_mode) or visible.st_uid != uid or
            stat.S_IMODE(visible.st_mode) != 0o700 or
            (visible.st_dev, visible.st_ino) != (opened.st_dev, opened.st_ino)):
        raise StagingError('ready payload identity changed')


def _delete_tree(fd: int, uid: int, prefix: str = '') -> None:
    """Only call AFTER _inspect_tree preflight, with exclusive stage lock."""
    _check_directory(fd, uid, private=True)
    for name in os.listdir(fd):
        relative = prefix + name
        if relative in _DIRS:
            child = os.open(name, _DIR_FLAGS, dir_fd=fd)
            try:
                _delete_tree(child, uid, relative + '/')
            finally:
                os.close(child)
            os.rmdir(name, dir_fd=fd)
        elif relative in PAYLOAD_FILES:
            file_fd = os.open(name, _READ_FLAGS, dir_fd=fd)
            try:
                _check_private_file(file_fd, uid)
                current = os.stat(name, dir_fd=fd, follow_symlinks=False)
                opened = os.fstat(file_fd)
                if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
                    raise StagingError('staged file identity changed')
            finally:
                os.close(file_fd)
            os.unlink(name, dir_fd=fd)
        else:
            raise StagingError('unsafe staged entry during cleanup')
    os.fsync(fd)


class StagedPayload:
    """Process-bound receipt holding stage EX lock and identity-pinned fds.

    CLOEXEC intentionally prevents fd inheritance by an executed child.
    The future root launcher must use a separately authenticated, verified
    source path after checking the active journal binding.
    """

    def __init__(self, transaction: TransactionHandle, root: Path, uid: int,
                 stage_id: str, hashes: dict[str, str], base: int,
                 lock: int, directory: int):
        self._transaction = transaction
        self._root = root
        self._uid = uid
        self._stage_id = stage_id
        self._hashes = hashes
        self._base = base
        self._lock = lock
        self._fd = directory
        self._pid = os.getpid()

    def __enter__(self):
        self._assert_owner()
        return self

    def __exit__(self, _type, _value, _traceback):
        self.close()

    def _assert_owner(self) -> None:
        if self._fd is None or os.getpid() != self._pid:
            raise StagingConflict('stage receipt is not active in this process')
        if self._transaction.transaction_id != self._stage_id:
            raise StagingConflict('receipt no longer belongs to transaction')

    @property
    def stage_id(self) -> str:
        self._assert_owner()
        return self._stage_id

    @property
    def directory_fd(self) -> int:
        self._assert_owner()
        return self._fd

    def verify(self, trusted_hashes: Mapping[str, str]) -> None:
        """Reverify inode and every file against independently trusted hashes."""
        self._assert_owner()
        if _safe_manifest(trusted_hashes) != self._hashes:
            raise StagingError('trusted staging manifest changed')
        _validate_identity(self._base, self._fd, _READY + self._stage_id, self._uid)
        _inspect_tree(self._fd, self._uid, self._hashes)

    def verified_source_path(self, trusted_hashes: Mapping[str, str]) -> Path:
        """Return a path ONLY after rechecking the active protected receipt."""
        self.verify(trusted_hashes)
        return self._root.joinpath(*_DEST, _READY + self._stage_id)

    def close(self) -> None:
        # Close, never unlock using LOCK_UN: a forked child can share the
        # underlying open description with the parent.
        if self._fd is not None:
            os.close(self._fd)
            os.close(self._lock)
            os.close(self._base)
            self._fd = None


def stage_payload(source: Path, trusted_hashes: Mapping[str, str],
                  transaction: TransactionHandle, *, root: Path = Path('/'),
                  owner_uid: int = 0) -> StagedPayload:
    """Stage authenticated DATA in private storage; never execute it."""
    root = Path(root)
    if os.geteuid() != owner_uid:
        raise StagingError('trusted staging owner required')
    identifier = _transaction_id(transaction, root, owner_uid,
                                 phases=('INSPECTED',))
    hashes = _safe_manifest(trusted_hashes)
    source_fd = _open_source_root(Path(source))
    try:
        contents = {}
        total = 0
        for name in sorted(PAYLOAD_FILES):
            content = _read_verified_file(source_fd, name, hashes[name])
            total += len(content)
            if total > _MAX_TOTAL_BYTES:
                raise StagingError('payload exceeds size limit')
            contents[name] = content
    finally:
        os.close(source_fd)
    base, lock = _lock_stage(root, owner_uid, create=True)
    stage_fd = None
    try:
        if any(name != _LOCK for name in os.listdir(base)):
            raise StagingConflict('existing staged state needs reconciliation')
        pending = _PENDING + identifier
        ready = _READY + identifier
        os.mkdir(pending, 0o700, dir_fd=base)
        os.fsync(base)
        stage_fd = os.open(pending, _DIR_FLAGS, dir_fd=base)
        os.fchmod(stage_fd, 0o700)
        os.fsync(stage_fd)
        _check_directory(stage_fd, owner_uid, private=True)
        for name in sorted(PAYLOAD_FILES):
            _write_file(stage_fd, name, contents[name], hashes[name], owner_uid)
        _inspect_tree(stage_fd, owner_uid, hashes)
        os.fsync(stage_fd)
        os.rename(pending, ready, src_dir_fd=base, dst_dir_fd=base)
        os.fsync(base)
        _validate_identity(base, stage_fd, ready, owner_uid)
        result = StagedPayload(transaction, root, owner_uid, identifier, hashes,
                               base, lock, stage_fd)
        base = lock = stage_fd = None
        return result
    except (StagingError, StagingConflict):
        raise
    except OSError:
        raise StagingError('protected payload staging failed') from None
    finally:
        if stage_fd is not None:
            os.close(stage_fd)
        if lock is not None:
            os.close(lock)
        if base is not None:
            os.close(base)


def recover_ready(trusted_hashes: Mapping[str, str],
                  transaction: TransactionHandle, *, root: Path = Path('/'),
                  owner_uid: int = 0) -> StagedPayload:
    """Recover only the ready folder named by this active journal's txid."""
    root = Path(root)
    if os.geteuid() != owner_uid:
        raise StagingError('trusted staging owner required')
    identifier = _transaction_id(transaction, root, owner_uid,
                                 phases=('INSPECTED', 'STAGED', 'SNAPSHOTTED',
                                         'APPLYING', 'ACTIVATING', 'VERIFYING',
                                         'COMMITTED', 'ABORTED', 'ROLLED_BACK'))
    hashes = _safe_manifest(trusted_hashes)
    base, lock = _lock_stage(root, owner_uid, create=False)
    stage_fd = None
    try:
        name = _READY + identifier
        if any(n not in (_LOCK, name) for n in os.listdir(base)):
            raise StagingConflict('ambiguous staging state')
        stage_fd = os.open(name, _DIR_FLAGS, dir_fd=base)
        _validate_identity(base, stage_fd, name, owner_uid)
        _inspect_tree(stage_fd, owner_uid, hashes)
        result = StagedPayload(transaction, root, owner_uid, identifier, hashes,
                               base, lock, stage_fd)
        base = lock = stage_fd = None
        return result
    except (StagingError, StagingConflict):
        raise
    except OSError:
        raise StagingError('unavailable or unsafe ready payload') from None
    finally:
        if stage_fd is not None:
            os.close(stage_fd)
        if lock is not None:
            os.close(lock)
        if base is not None:
            os.close(base)


def discard_pending(transaction: TransactionHandle, *, root: Path = Path('/'),
                    owner_uid: int = 0) -> None:
    """Remove only this transaction's safe incomplete stage, under EX lock."""
    root = Path(root)
    if os.geteuid() != owner_uid:
        raise StagingError('trusted staging owner required')
    identifier = _transaction_id(transaction, root, owner_uid,
                                 phases=('INSPECTED', 'STAGED', 'ABORTED'))
    base, lock = _lock_stage(root, owner_uid, create=False)
    try:
        pending = _PENDING + identifier
        if any(name not in (_LOCK, pending) for name in os.listdir(base)):
            raise StagingConflict('unrelated stage blocks reconciliation')
        try:
            fd = os.open(pending, _DIR_FLAGS, dir_fd=base)
        except FileNotFoundError:
            # Safe replay after a crash following rmdir but before fsync.
            os.fsync(base)
            return
        try:
            _check_directory(fd, owner_uid, private=True)
            _inspect_tree(fd, owner_uid, None)
            visible = os.stat(pending, dir_fd=base, follow_symlinks=False)
            opened = os.fstat(fd)
            if (visible.st_dev, visible.st_ino) != (opened.st_dev, opened.st_ino):
                raise StagingError('pending payload identity changed')
            _delete_tree(fd, owner_uid)
        finally:
            os.close(fd)
        os.rmdir(pending, dir_fd=base)
        os.fsync(base)
    except (StagingError, StagingConflict):
        raise
    except OSError:
        raise StagingError('unsafe pending stage cleanup') from None
    finally:
        os.close(lock)
        os.close(base)


def retire_ready(receipt: StagedPayload, trusted_hashes: Mapping[str, str]) -> None:
    """Guardedly remove exactly this process-owned, terminal stage receipt."""
    if not isinstance(receipt, StagedPayload):
        raise StagingError('validated stage receipt required')
    receipt._assert_owner()
    if receipt._transaction._record()['phase'] not in ('COMMITTED', 'ABORTED', 'ROLLED_BACK'):
        raise StagingConflict('cannot retire stage before terminal journal state')
    receipt.verify(trusted_hashes)
    name = _READY + receipt._stage_id
    _delete_tree(receipt._fd, receipt._uid)
    _validate_identity(receipt._base, receipt._fd, name, receipt._uid)
    try:
        os.rmdir(name, dir_fd=receipt._base)
        os.fsync(receipt._base)
    except OSError:
        raise StagingError('unable to retire protected staged files') from None
    receipt.close()


def finish_retirement(transaction: TransactionHandle, *, root: Path = Path('/'),
                      owner_uid: int = 0) -> None:
    """Finish interrupted ready cleanup, never certify a payload for use.

    Only a terminal transaction may request this. Partial ready contents
    must have only owned, single-linked, known source names and directories.
    It intentionally never accepts or executes an incomplete ready bundle.
    """
    root = Path(root)
    if os.geteuid() != owner_uid:
        raise StagingError('trusted staging owner required')
    identifier = _transaction_id(transaction, root, owner_uid,
                                 phases=('COMMITTED', 'ABORTED', 'ROLLED_BACK'))
    base, lock = _lock_stage(root, owner_uid, create=False)
    try:
        name = _READY + identifier
        if any(value not in (_LOCK, name) for value in os.listdir(base)):
            raise StagingConflict('unrelated stage blocks retirement')
        try:
            fd = os.open(name, _DIR_FLAGS, dir_fd=base)
        except FileNotFoundError:
            # The last rmdir may already have completed before a crash,
            # while the containing directory's durability was uncertain.
            os.fsync(base)
            return
        try:
            _validate_identity(base, fd, name, owner_uid)
            _inspect_tree(fd, owner_uid, None)
            _delete_tree(fd, owner_uid)
            _validate_identity(base, fd, name, owner_uid)
        finally:
            os.close(fd)
        os.rmdir(name, dir_fd=base)
        os.fsync(base)
    except (StagingError, StagingConflict):
        raise
    except OSError:
        raise StagingError('unsafe interrupted retirement') from None
    finally:
        os.close(lock)
        os.close(base)
