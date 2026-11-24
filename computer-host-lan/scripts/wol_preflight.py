#!/usr/bin/env python3
"""Read-only development preflight for a future protected WOL controller.

No CLI, write operation, approval token or root request. Private snapshots
are in-memory evidence only. A trusted controller must own the approval,
lock, filesystem identity, journal and live-path revalidation boundaries.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat

import wol_inspect as probe
import wol_plan as planner


_MIN_SYSTEMD = 248
_UDEV_VERSION = ('udevadm', '--version')
_SYSTEMD_VERSION = ('systemctl', '--version')
_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_MAX_BYTES = 65536


@dataclass(frozen=True, repr=False)
class ToolVersions:
    udev: int
    systemd: int
    systemd_line: str


@dataclass(frozen=True, repr=False)
class PolicySnapshot:
    interface: str
    nic: tuple[str, str, str]
    selected: str
    versions: ToolVersions
    directory: tuple
    inventory: tuple
    rules: tuple
    hardware: tuple


def tool_versions(run: probe.Runner = probe.query) -> ToolVersions | None:
    """Conservative installed-tool gate, not running-daemon attestation."""
    udev = run(_UDEV_VERSION)
    systemd = run(_SYSTEMD_VERSION)
    if not isinstance(udev, str) or not isinstance(systemd, str):
        return None
    u = re.fullmatch(r'([0-9]{1,6})\n?', udev)
    first = systemd.partition('\n')[0]
    s = re.fullmatch(r'systemd ([0-9]{1,6})(?: \([ -~]{1,512}\))?', first)
    if u is None or s is None:
        return None
    a, b = int(u[1]), int(s[1])
    if a != b or a < _MIN_SYSTEMD:
        return None
    return ToolVersions(a, b, first)


def _metadata(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, info.st_uid, info.st_gid,
            info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _protected(info: os.stat_result, uid: int, kind) -> bool:
    return kind(info.st_mode) and info.st_uid == uid and not info.st_mode & 0o022


def _directory(root: Path, relative: Path, uid: int) -> tuple[int, tuple]:
    """Open a fixed tree without following symlinks; return fd and evidence."""
    fd = os.open(root, _FLAGS)
    chain = []
    try:
        for part in relative.parts:
            if part in ('', '.', '..', '/'):
                raise ValueError('invalid policy component')
            info = os.fstat(fd)
            if not _protected(info, uid, stat.S_ISDIR):
                raise ValueError('unsafe policy directory')
            # Include ancestor identity/permissions but not timestamps:
            # unrelated activity under /etc or /run is not policy drift.
            chain.append((info.st_dev, info.st_ino, info.st_uid,
                          info.st_gid, info.st_mode))
            child = os.open(part, _FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        if not _protected(info, uid, stat.S_ISDIR):
            raise ValueError('unsafe policy directory')
        chain.append((info.st_dev, info.st_ino, info.st_uid,
                      info.st_gid, info.st_mode))
        result, fd = fd, -1
        return result, tuple(chain)
    finally:
        if fd >= 0:
            os.close(fd)


def _rule(root: Path, path: Path, uid: int) -> tuple[tuple, str | None]:
    """Read exact effective rule bytes and metadata, including mask evidence."""
    relative = path.relative_to(root)
    fd, chain = _directory(root, relative.parent, uid)
    try:
        before = os.stat(relative.name, dir_fd=fd, follow_symlinks=False)
        if before.st_uid != uid:
            raise ValueError('unsafe rule owner')
        if stat.S_ISLNK(before.st_mode):
            if os.readlink(relative.name, dir_fd=fd) != '/dev/null':
                raise ValueError('unsafe rule link')
            text, digest = None, 'mask'
        else:
            if (not _protected(before, uid, stat.S_ISREG) or
                    before.st_nlink != 1 or before.st_size > _MAX_BYTES):
                raise ValueError('unsafe rule file')
            with os.fdopen(os.open(relative.name, _FILE_FLAGS, dir_fd=fd), 'rb') as stream:
                opened = os.fstat(stream.fileno())
                if _metadata(opened) != _metadata(before):
                    raise ValueError('rule changed')
                raw = stream.read(_MAX_BYTES + 1)
                if (len(raw) != before.st_size or len(raw) > _MAX_BYTES or
                        _metadata(os.fstat(stream.fileno())) != _metadata(before)):
                    raise ValueError('rule changed')
            text = raw.decode('utf-8') if raw else None
            digest = hashlib.sha256(raw).hexdigest()
        after = os.stat(relative.name, dir_fd=fd, follow_symlinks=False)
        if _metadata(before) != _metadata(after):
            raise ValueError('rule changed')
        return (str(relative), chain, _metadata(after), digest), text
    finally:
        os.close(fd)


def _literal_permanent(text: str, *, selected: bool) -> str | None:
    """Narrow parser before any prospective write; not a systemd emulator.

    Reject escaping, continuations, non-ASCII and unknown sections. Earlier
    rules need only a literal permanent MAC mismatch; selected rules must
    also have no explicit nonempty WOL or password. Unknown Link settings
    are refused in this first implementation.
    """
    if not text.isascii() or any(c not in '\n\r\t' and not 32 <= ord(c) <= 126
                               for c in text) or '\\' in text or '\r' in text:
        return None
    sections = set()
    section = ''
    match = None
    keys = set()
    allowed = {'Name', 'NamePolicy', 'MACAddress', 'MACAddressPolicy',
               'AlternativeName', 'AlternativeNamesPolicy', 'WakeOnLan'}
    for raw in text.split('\n'):
        line = raw.strip(' \t')
        if not line or line.startswith(('#', ';')):
            continue
        if line.startswith('['):
            if line not in ('[Match]', '[Link]') or line in sections:
                return None
            sections.add(line)
            section = line
            continue
        key, sep, value = line.partition('=')
        key, value = key.strip(' \t'), value.strip(' \t')
        if not sep or not section or '"' in value or "'" in value:
            return None
        if section == '[Match]':
            if key != 'PermanentMACAddress' or match is not None or not probe.valid_mac(value):
                return None
            match = value.lower()
        elif selected:
            if key not in allowed or key in keys or (key == 'WakeOnLan' and value):
                return None
            keys.add(key)
    return match


def _sample(interface: str, root: Path, net: Path, uid: int,
            run: probe.Runner) -> PolicySnapshot | None:
    versions = tool_versions(run)
    if versions is None:
        return None
    nic = probe.read_identity(net, interface)
    if nic is None or nic[2] != 'ethernet':
        return None
    observed = None

    def query(args):
        nonlocal observed
        output = run(args)
        if args[0] == 'udevadm' and args[1:] != ('--version',):
            observed = probe.selected_link(output)
        return output

    plan = planner.plan(interface, root=root, net=net, owner_uid=uid, run=query)
    if (plan['recommendation'] != 'review_link_dropin' or
            plan['reason'] != 'protected_empty_local_dropin' or
            observed is None or observed[0] != 'local' or observed[1] is None or
            observed[2] != 'not_reported'):
        return None
    path = observed[1]
    listing = planner.inventory(root, uid)
    winners, dropins = listing
    if winners.get(path.name) != planner.rooted(root, str(path)):
        return None
    if planner.empty_local_dropin(root, path, uid, dropins) is None:
        return None
    fd, chain = _directory(root, Path(str(path).lstrip('/') + '.d'), uid)
    try:
        directory_before = _metadata(os.fstat(fd))
        with os.scandir(fd) as entries:
            if next(entries, None) is not None:
                return None
        rules = []
        for name, rule in sorted(winners.items()):
            if name > path.name:
                break
            evidence, text = _rule(root, rule, uid)
            rules.append(evidence)
            if text is None:
                if name == path.name:
                    return None
                continue
            mac = _literal_permanent(text, selected=name == path.name)
            if mac is None or (mac == nic[1]) != (name == path.name):
                return None
        if (_metadata(os.fstat(fd)) != directory_before or
                planner.inventory(root, uid) != listing or
                probe.read_identity(net, interface) != nic or
                tool_versions(run) != versions):
            return None
        visible = planner.empty_local_dropin(root, path, uid, dropins)
        if visible != (directory_before[0], directory_before[1],
                       directory_before[7], directory_before[8]):
            return None
        inventory = (tuple(sorted((n, str(p.relative_to(root))) for n, p in winners.items())),
                     tuple(sorted((n, tuple(str(p.relative_to(root)) for p in paths))
                                  for n, paths in dropins.items())))
        inspection = plan['inspection']
        hardware = tuple(inspection[k] for k in (
            'magic_packet_support', 'runtime_magic_packet', 'hardware_query',
            'permanent_mac_match', 'backend', 'networkmanager_state'))
        return PolicySnapshot(interface, nic, str(path), versions,
                              (chain, directory_before), inventory, tuple(rules), hardware)
    finally:
        os.close(fd)


def capture(interface: str, *, root: Path = Path('/'),
            net: Path = Path('/sys/class/net'), owner_uid: int = 0,
            run: probe.Runner = probe.query) -> PolicySnapshot | None:
    """Capture twice, require exact agreement. No atomic snapshot claim."""
    if (not isinstance(interface, str) or not probe._IFACE.fullmatch(interface)
            or interface in ('.', '..') or interface.startswith('-')):
        return None
    try:
        first = _sample(interface, root, net, owner_uid, run)
        if first is None:
            return None
        return first if _sample(interface, root, net, owner_uid, run) == first else None
    except (OSError, ValueError, UnicodeError, planner.UncertainPolicy):
        return None


def unchanged(approved: PolicySnapshot, **kwargs) -> bool:
    """Compare with a private snapshot retained by trusted caller.

    NOT proof of consent: no caller-provided JSON/hash is accepted by any
    installed code. A future controller must retain its own approved
    snapshot, revalidate under lock and keep an independently checked
    destination descriptor through application.
    """
    return (type(approved) is PolicySnapshot and
            capture(approved.interface, **kwargs) == approved)
