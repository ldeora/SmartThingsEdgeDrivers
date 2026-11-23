#!/usr/bin/env python3
"""Isolated root-owned payload staging primitive; NOT an elevation endpoint.

No CLI and no subprocess/systemd execution. In production, only a separately
authenticated, root-owned launcher may supply the trusted manifest and call
stage_payload(). This file must NEVER be run via sudo from a writable checkout.
"""
from __future__ import annotations

import fcntl
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Mapping

# Exactly the minimal files needed by the existing Python engine plus its
# future health/journal gates. Not a general-purpose root file copier.
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
_DEST = ('var', 'lib', 'computer-host-installer', 'staging')
_LOCK = 'stage.lock'
_STAGE_PREFIX = 'pending-'
_READY_PREFIX = 'ready-'
_SHA256 = re.compile(r'[0-9a-f]{64}\Z')
_MAX_FILE_BYTES = 1024 * 1024
_MAX_TOTAL_BYTES = 4 * 1024 * 1024
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class StagingError(RuntimeError):
    """Static non-sensitive error; never echo source paths or bytes."""


class StagingConflict(StagingError):
    pass


def _safe_manifest(expected: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(expected, Mapping) or set(expected) != PAYLOAD_FILES:
        raise StagingError('invalid trusted payload manifest')
    if any(type(digest) is not str or not _SHA256.fullmatch(digest)
           for digest in expected.values()):
        raise StagingError('invalid trusted payload digest')
    return dict(expected)


def _check_directory(fd: int, uid: int, *, private: bool) -> None:
    info = os.fstat(fd)
    permissions = stat.S_IMODE(info.st_mode)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or
            (permissions != 0o700 if private else bool(permissions & 0o022))):
        raise StagingError('unsafe staging directory')


def _walk_destination(root: Path, uid: int) -> int:
    """Create only the fixed root-owned path using no-follow dirfds."""
    fd = None
    try:
        fd = os.open(root, _DIR_FLAGS)
        _check_directory(fd, uid, private=False)
        for index, part in enumerate(_DEST):
            private = index >= 2
            target_mode = 0o700 if private else 0o755
            created = False
            try:
                child = os.open(part, _DIR_FLAGS, dir_fd=fd)
            except FileNotFoundError:
                os.mkdir(part, target_mode, dir_fd=fd)
                os.fsync(fd)
                child = os.open(part, _DIR_FLAGS, dir_fd=fd)
                created = True
            try:
                # Check ownership BEFORE any chmod on a freshly created
                # directory; leave existing admin-owned directories alone.
                if os.fstat(child).st_uid != uid:
                    raise StagingError('unsafe staging directory owner')
                if created:
                    os.fchmod(child, target_mode)
                    os.fsync(child)
                _check_directory(child, uid, private=private)
            except Exception:
                os.close(child)
                raise
            os.close(fd)
            fd = child
        result, fd = fd, None
        return result
    except StagingError:
        raise
    except OSError:
        raise StagingError('unable to create trusted staging root') from None
    finally:
        if fd is not None:
            os.close(fd)


def _open_source_root(source: Path) -> int:
    """No-follow every source component; contents are still UNTRUSTED."""
    if not source.is_absolute() or '..' in source.parts:
        raise StagingError('invalid source location')
    fd = None
    try:
        fd = os.open('/', _DIR_FLAGS)
        for part in source.parts[1:]:
            child = os.open(part, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        result, fd = fd, None
        return result
    except OSError:
        raise StagingError('unsafe or unavailable source directory') from None
    finally:
        if fd is not None:
            os.close(fd)


def _read_verified_file(source_fd: int, relative: str, digest: str) -> bytes:
    """Open by fixed relative parts, refuse symlinks/hardlinks, hash bytes."""
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
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                    not 0 < info.st_size <= _MAX_FILE_BYTES):
                raise StagingError('unsafe payload source file')
            content = bytearray()
            while len(content) <= _MAX_FILE_BYTES:
                chunk = os.read(fd, min(65536, _MAX_FILE_BYTES + 1 - len(content)))
                if not chunk:
                    break
                content.extend(chunk)
            if (len(content) != info.st_size or len(content) > _MAX_FILE_BYTES or
                    not hmac.compare_digest(hashlib.sha256(content).hexdigest(), digest)):
                raise StagingError('payload digest mismatch')
            return bytes(content)
        finally:
            os.close(fd)
    except StagingError:
        raise
    except OSError:
        raise StagingError('unable to read safe payload source') from None
    finally:
        os.close(directory)


def _check_private_file(fd: int, uid: int) -> None:
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != uid or
            info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
        raise StagingError('unsafe staged file')


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
            position = 0
            while position < len(content):
                count = os.write(fd, content[position:])
                if count < 1:
                    raise StagingError('incomplete staged write')
                position += count
            os.fsync(fd)
            os.lseek(fd, 0, os.SEEK_SET)
            written = bytearray()
            while len(written) < len(content):
                block = os.read(fd, len(content) - len(written))
                if not block:
                    break
                written.extend(block)
            if (len(written) != len(content) or
                    not hmac.compare_digest(hashlib.sha256(written).hexdigest(), digest)):
                raise StagingError('staged payload verification failed')
        finally:
            os.close(fd)
        os.fsync(directory)
    finally:
        os.close(directory)


class StagedPayload:
    """Verified, still-open directory fd; NEVER an authorization to execute."""

    def __init__(self, directory_fd: int):
        self._fd = directory_fd

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        self.close()

    @property
    def directory_fd(self) -> int:
        if self._fd is None:
            raise StagingError('staged descriptor has been closed')
        return self._fd

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None


def stage_payload(source: Path, trusted_hashes: Mapping[str, str], *,
                  root: Path = Path('/'), owner_uid: int = 0) -> StagedPayload:
    """Data-only stage; caller must be trusted and have authenticated hashes.

    root/owner_uid injection is ONLY for temporary nonroot fixture tests.
    Production must call this module from a trusted root-owned process;
    there is no CLI/elevation path in this PR.
    """
    if os.geteuid() != owner_uid:
        raise StagingError('trusted staging owner required')
    hashes = _safe_manifest(trusted_hashes)
    source_fd = _open_source_root(Path(source))
    try:
        # Authenticate the ENTIRE payload into bounded memory before ANY
        # destination is created. Mutating source files after this point
        # cannot change the bytes we write into the protected directory.
        contents = {}
        total = 0
        for name in sorted(PAYLOAD_FILES):
            content = _read_verified_file(source_fd, name, hashes[name])
            total += len(content)
            if total > _MAX_TOTAL_BYTES:
                raise StagingError('trusted payload exceeds size budget')
            contents[name] = content
    finally:
        os.close(source_fd)
    base = _walk_destination(Path(root), owner_uid)
    lockfd = None
    staged_fd = None
    try:
        lockfd = os.open(_LOCK, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW |
                         os.O_NONBLOCK | os.O_CLOEXEC, 0o600, dir_fd=base)
        _check_private_file(lockfd, owner_uid)
        if os.fstat(lockfd).st_size:
            raise StagingError('invalid staging lock')
        try:
            fcntl.flock(lockfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise StagingConflict('payload staging already active') from None
        # No automatic cleanup: an incomplete payload must not be mistaken
        # for a safely verified one. A future trusted recovery engine owns
        # reconciliation before creating another staged payload.
        if any(name != _LOCK for name in os.listdir(base)):
            raise StagingConflict('existing payload needs reconciliation')
        identifier = secrets.token_hex(16)
        pending = _STAGE_PREFIX + identifier
        ready = _READY_PREFIX + identifier
        os.mkdir(pending, 0o700, dir_fd=base)
        os.fsync(base)
        staged_fd = os.open(pending, _DIR_FLAGS, dir_fd=base)
        os.fchmod(staged_fd, 0o700)
        os.fsync(staged_fd)
        _check_directory(staged_fd, owner_uid, private=True)
        for name in sorted(PAYLOAD_FILES):
            _write_file(staged_fd, name, contents[name], hashes[name], owner_uid)
        os.fsync(staged_fd)
        os.rename(pending, ready, src_dir_fd=base, dst_dir_fd=base)
        os.fsync(base)
        receipt, staged_fd = staged_fd, None
        return StagedPayload(receipt)
    except StagingError:
        raise
    except OSError:
        raise StagingError('protected payload staging failed') from None
    finally:
        if staged_fd is not None:
            os.close(staged_fd)
        if lockfd is not None:
            os.close(lockfd)
        os.close(base)
