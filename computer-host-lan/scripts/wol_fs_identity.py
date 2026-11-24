#!/usr/bin/env python3
"""Development-only descriptor-based filesystem identity experiment.

Private evidence, not a standalone authorization or proof of ownership.
No CLI, no writes, no subprocesses, no block-device scans, no fallback to
st_dev/f_fsid. No production receipt or installer integration yet.
"""
from __future__ import annotations

from dataclasses import dataclass
import fcntl
import os
import platform
import stat
import struct
import sys


# Linux asm-generic ioctl encoding on the explicitly supported ABIs below.
# fsuuid2: u8 len, u8 uuid[16], sizeof=17.
# btrfs_ioctl_ino_lookup_args: u64 treeid, u64 objectid, char name[4080].
_FS_IOC_GETFSUUID = 0x80111500
# Btrfs UAPI: _IOR(0x94, 31, struct btrfs_ioctl_fs_info_args).
_BTRFS_IOC_FS_INFO = 0x8400941f
_BTRFS_FS_INFO_FLAG_METADATA_UUID = 1 << 2
_BTRFS_IOC_INO_LOOKUP = 0xc0000000 | (4096 << 16) | (0x94 << 8) | 18
_SUPPORTED_ABIS = frozenset(('x86_64', 'aarch64', 'riscv64'))
_FILESYSTEMS = frozenset(('ext4', 'xfs', 'btrfs'))
_MAX_MOUNTINFO = 4 * 1024 * 1024
_MAX_FDINFO = 4096


@dataclass(frozen=True, repr=False)
class FilesystemIdentity:
    """Private comparison data; deliberately no public JSON or repr fields."""
    filesystem: str
    uuid: bytes
    subvolume: int | None
    inode: int


def _bounded_read(path: str, limit: int) -> bytes:
    with open(path, 'rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('identity source exceeds limit')
    return data


def _mount_id(data: bytes) -> bytes:
    matches = [line.partition(b':')[2].strip()
               for line in data.splitlines()
               if line.startswith(b'mnt_id:')]
    if (len(matches) != 1 or not matches[0].isdigit() or
            not 0 < int(matches[0]) < 2**64):
        raise ValueError('mount identity unavailable')
    return matches[0]


def _mount_record(data: bytes, mount_id: bytes) -> tuple[bytes, str]:
    # Match the mount ID of the *open descriptor*, never a path prefix
    # or st_dev. Btrfs subvolumes need not share st_dev with mountinfo.
    records = []
    for line in data.splitlines():
        left, separator, right = line.partition(b' - ')
        fields = left.split()
        if not fields or fields[0] != mount_id:
            continue
        fs = right.split()
        if not separator or len(fields) < 6 or len(fs) != 3:
            raise ValueError('invalid mount record')
        records.append((line, fs[0].decode('ascii')))
    if len(records) != 1:
        raise ValueError('mount identity ambiguous')
    return records[0]


def _mount(fd: int) -> tuple[bytes, bytes, str]:
    mount_id = _mount_id(_bounded_read('/proc/self/fdinfo/' + str(fd), _MAX_FDINFO))
    record, filesystem = _mount_record(
        _bounded_read('/proc/self/mountinfo', _MAX_MOUNTINFO), mount_id)
    return mount_id, record, filesystem


def _uuid(fd: int) -> bytes:
    buf = bytearray(17)
    if fcntl.ioctl(fd, _FS_IOC_GETFSUUID, buf, True) != 0:
        raise ValueError('filesystem UUID unavailable')
    if buf[0] != 16 or not any(buf[1:]):
        raise ValueError('filesystem UUID unavailable')
    return bytes(buf[1:])


def _btrfs_uuid(fd: int) -> bytes:
    """Native Btrfs evidence, limited to equal FSID and metadata UUID.

    A differing UUID may be legitimate (e.g. btrfstune) or temporary.
    Equality is not proof against cloned/restored filesystems.
    """
    buf = bytearray(1024)
    struct.pack_into('=Q', buf, 48, _BTRFS_FS_INFO_FLAG_METADATA_UUID)
    if fcntl.ioctl(fd, _BTRFS_IOC_FS_INFO, buf, True) != 0:
        raise ValueError('Btrfs filesystem identity unavailable')
    fsid = bytes(buf[16:32])
    flags = struct.unpack_from('=Q', buf, 48)[0]
    metadata_uuid = bytes(buf[64:80])
    if (flags != _BTRFS_FS_INFO_FLAG_METADATA_UUID or
            not any(fsid) or fsid != metadata_uuid):
        raise ValueError('Btrfs filesystem identity unavailable')
    return fsid


def _subvolume(fd: int) -> int:
    buf = bytearray(4096)
    # Special unprivileged query: treeid=0, objectid=256.
    struct.pack_into('=QQ', buf, 0, 0, 256)
    if fcntl.ioctl(fd, _BTRFS_IOC_INO_LOOKUP, buf, True) != 0:
        raise ValueError('subvolume identity unavailable')
    tree, objectid = struct.unpack_from('=QQ', buf)
    # 5 is the top-level filesystem tree. Normal subvolume IDs start
    # at 256; exclude the reserved high object IDs.
    if (tree != 5 and not 256 <= tree <= 2**64 - 256) or objectid != 256:
        raise ValueError('subvolume identity unavailable')
    if buf[16] != 0:
        raise ValueError('unexpected subvolume lookup response')
    return tree


def identify(fd: int) -> FilesystemIdentity | None:
    """Return private candidate evidence, or None on any unsupported query.

    Caller owns an already-open regular file/directory descriptor and must
    keep it open. No claim is made that cloned/restored filesystems, reused
    inodes or malicious privileged writers are distinguishable. The future
    controller must re-walk fixed paths, validate ownership and anchored
    hard-link evidence separately, and never serialize these values publicly.
    """
    if (sys.platform != 'linux' or platform.machine() not in _SUPPORTED_ABIS
            or struct.calcsize('P') != 8 or type(fd) is not int or fd < 0):
        return None
    try:
        before = os.fstat(fd)
        if (not (stat.S_ISREG(before.st_mode) or stat.S_ISDIR(before.st_mode))
                or before.st_ino <= 0 or before.st_nlink <= 0):
            return None
        mount = _mount(fd)
        filesystem = mount[2]
        if filesystem not in _FILESYSTEMS:
            return None
        read_uuid = _btrfs_uuid if filesystem == 'btrfs' else _uuid
        uuid = read_uuid(fd)
        subvolume = _subvolume(fd) if filesystem == 'btrfs' else None
        # Reject inconsistent observations rather than returning partial
        # evidence. No atomic snapshot of mounts is claimed.
        if (read_uuid(fd) != uuid or
                (filesystem == 'btrfs' and _subvolume(fd) != subvolume) or
                _mount(fd) != mount):
            return None
        after = os.fstat(fd)
        if (before.st_dev, before.st_ino, before.st_mode, before.st_nlink) != (
                after.st_dev, after.st_ino, after.st_mode, after.st_nlink):
            return None
        return FilesystemIdentity(filesystem, uuid, subvolume, after.st_ino)
    except (OSError, ValueError, OverflowError, UnicodeError):
        return None
