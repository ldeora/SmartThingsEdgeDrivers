#!/usr/bin/env python3
"""Read-only Wake-on-LAN evidence for the Linux installer (development).

This is intentionally NOT a planner or authorization boundary. No command
changes a NIC, a NetworkManager connection, a .link file or a service.
The result cannot establish persistence or authorize a future write.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import uuid
from typing import Callable

_PATH = '/usr/sbin:/usr/bin:/sbin:/bin'
_IFACE = re.compile(r'[A-Za-z0-9_.-]{1,15}\Z')
_MAC = re.compile(r'[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}\Z')
_WOL_FLAGS = re.compile(r'[pumbagsfd]+\Z')
_LINK_DIRS = {
    '/etc/systemd/network': 'local',
    '/run/systemd/network': 'runtime',
    '/usr/local/lib/systemd/network': 'local_vendor',
    '/usr/lib/systemd/network': 'vendor',
    '/lib/systemd/network': 'vendor',
}
_MAX_OUTPUT = 65536
Runner = Callable[[tuple[str, ...]], str | None]


def query(args: tuple[str, ...]) -> str | None:
    """Fixed read-only commands are selected by the inspector, not callers."""
    executable = shutil.which(args[0], path=_PATH)
    if executable is None:
        return None
    try:
        done = subprocess.run(
            [executable, *args[1:]], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env={'PATH': _PATH, 'LANG': 'C', 'LC_ALL': 'C'},
            timeout=8, check=False)
        if done.returncode != 0 or len(done.stdout) > _MAX_OUTPUT:
            return None
        return done.stdout.decode('utf-8')
    except (OSError, UnicodeError, subprocess.TimeoutExpired):
        return None


def valid_mac(value: str) -> bool:
    return bool(_MAC.fullmatch(value) and
                value.lower() != '00:00:00:00:00:00' and
                not (int(value[:2], 16) & 1))


def read_identity(net: Path, interface: str) -> tuple[str, str, str] | None:
    path = net / interface
    try:
        index = (path / 'ifindex').read_text().strip()
        mac = (path / 'address').read_text().strip().lower()
        kind = (path / 'type').read_text().strip()
        if not index.isascii() or not index.isdecimal() or int(index) <= 0:
            return None
        if not valid_mac(mac):
            return None
        if (kind != '1' or not (path / 'device').exists() or
                (path / 'wireless').exists() or (path / 'phy80211').exists()):
            return index, mac, 'other'
        return index, mac, 'ethernet'
    except (OSError, UnicodeError, ValueError):
        return None


def parse_ethtool(output: str | None) -> tuple[str, str] | None:
    if output is None:
        return None
    values = {}
    for line in output.splitlines():
        line = line.strip()
        for key in ('Supports Wake-on:', 'Wake-on:'):
            if line.startswith(key):
                value = line[len(key):].strip()
                if (key in values or not _WOL_FLAGS.fullmatch(value) or
                        len(set(value)) != len(value) or
                        ('d' in value and value != 'd')):
                    return None
                values[key] = value
    if len(values) != 2:
        return None
    supports = values['Supports Wake-on:']
    current = values['Wake-on:']
    if current != 'd' and not set(current).issubset(supports):
        return None
    return ('supported' if 'g' in supports else 'unsupported',
            'enabled' if 'g' in current else 'disabled')


def parse_nm_policy(output: str | None) -> str:
    # nmcli versions may print a flag name, a number, or "64 (magic)".
    # Never infer an effective global policy from DEFAULT or IGNORE.
    if output is None:
        return 'not_verified'
    value = output.strip()
    names = {'default': 1, 'ignore': 0x8000, 'none': 0, 'phy': 2,
             'unicast': 4, 'multicast': 8, 'broadcast': 16,
             'arp': 32, 'magic': 64}
    if value in names:
        flags = names[value]
    else:
        match = re.fullmatch(r'(0x[0-9a-fA-F]{1,8}|[0-9]{1,10})(?: \([a-z, -]+\))?', value)
        if match is None:
            return 'not_verified'
        number = match.group(1)
        flags = int(number, 16 if number.startswith('0x') else 10)
    if flags == 1:
        return 'default'
    if flags == 0x8000:
        return 'ignore'
    if flags == 0:
        return 'none'
    if flags & ~0x7e:
        return 'not_verified'
    if flags == 64:
        return 'magic'
    if flags & 64:
        return 'magic_with_other_flags'
    return 'other_flags'


def properties(output: str | None, keys: tuple[str, ...]) -> dict[str, str] | None:
    if output is None:
        return None
    found = {}
    for line in output.splitlines():
        key, sep, value = line.partition('=')
        if key in keys:
            if not sep or key in found:
                return None
            found[key] = value
    return found if set(found) == set(keys) else None


def selected_link(output: str | None) -> tuple[str, Path | None]:
    # ID_NET_LINK_FILE is the observed udev selection, not proof of
    # the next selection after configuration changes or a reboot.
    props = properties(output, ('ID_NET_LINK_FILE',))
    if props is None:
        return 'not_verified', None
    raw = props['ID_NET_LINK_FILE']
    path = PurePosixPath(raw)
    if (str(path) != raw or str(path.parent) not in _LINK_DIRS or
            not re.fullmatch(r'[A-Za-z0-9_.+-]+\.link', path.name)):
        return 'not_verified', None
    return _LINK_DIRS[str(path.parent)], Path(raw)


def read_link(path: Path) -> str | None:
    # No symlink, FIFO, device or writable file is opened as a policy.
    # Do not display contents (a .link file can contain a SecureOn password).
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or
                    info.st_mode & 0o022 or info.st_size > _MAX_OUTPUT):
                return None
            raw = stream.read(_MAX_OUTPUT + 1)
        return raw.decode('utf-8') if len(raw) <= _MAX_OUTPUT else None
    except (OSError, UnicodeError):
        return None


def base_link_policy(output: str | None) -> str:
    """Only a declaration in the observed base file; never merged policy."""
    if output is None:
        return 'not_verified'
    section = ''
    link_sections = 0
    values = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith(('#', ';')):
            continue
        if line.endswith('\\'):
            return 'not_verified'
        if line.startswith('['):
            if not line.endswith(']'):
                return 'not_verified'
            section = line[1:-1]
            if section == 'Link':
                link_sections += 1
        elif section == 'Link':
            key, sep, value = line.partition('=')
            if not sep:
                return 'not_verified'
            if key.strip() == 'WakeOnLan':
                values.append(value.strip())
    if link_sections != 1 or len(values) > 1:
        return 'not_verified'
    if not values:
        return 'unspecified'
    flags = values[0].split()
    allowed = {'phy', 'unicast', 'multicast', 'broadcast', 'arp', 'magic',
               'secureon', 'off'}
    if (not flags or any(flag not in allowed for flag in flags) or
            ('off' in flags and flags != ['off'])):
        return 'not_verified'
    return 'magic_declared' if 'magic' in flags else 'other_declared'


def inspect(interface: str, *, net: Path = Path('/sys/class/net'),
            run: Runner = query, link_reader: Callable[[Path], str | None] = read_link) -> dict:
    result = dict(schema_version=1, operation='wol_inspect', mode='read_only',
                  interface_state='not_verified', magic_packet_support='not_verified',
                  runtime_magic_packet='not_verified', hardware_query='not_verified',
                  permanent_mac_match='not_verified', backend='not_verified',
                  nm_profile_policy='not_verified', observed_link='not_verified',
                  base_link_policy='not_verified', changes_applied=False,
                  persistence_verified=False, secrets_included=False)
    if (not isinstance(interface, str) or not _IFACE.fullmatch(interface) or
            interface in ('.', '..') or interface.startswith('-')):
        result['interface_state'] = 'invalid_interface'
        return result
    before = read_identity(net, interface)
    if before is None:
        return result
    if before[2] != 'ethernet':
        result['interface_state'] = 'unsupported_interface'
        return result
    baseline = result.copy()
    result['interface_state'] = 'ethernet'
    for method, args in (
            ('default', ('ethtool', interface)),
            ('ioctl', ('ethtool', '--disable-netlink', interface))):
        state = parse_ethtool(run(args))
        if state is not None:
            result['magic_packet_support'], result['runtime_magic_packet'] = state
            result['hardware_query'] = method
            break
    permanent = run(('ethtool', '-P', interface))
    if permanent is not None:
        match = re.fullmatch(r'Permanent address: ([0-9a-fA-F:]+)\s*', permanent)
        if match and valid_mac(match.group(1)):
            result['permanent_mac_match'] = (
                'matches' if match.group(1).lower() == before[1] else 'differs')

    nm = properties(run(('systemctl', 'show', '--all', '--no-pager',
                         '--property=LoadState,ActiveState', '--',
                         'NetworkManager.service')), ('LoadState', 'ActiveState'))
    if nm == {'LoadState': 'loaded', 'ActiveState': 'active'}:
        # Global NM activity alone does not prove this NIC has an active
        # profile. Do not fall back to udev if NM ownership is ambiguous.
        active = run(('nmcli', '--wait', '5', '--get-values',
                      'GENERAL.CON-UUID', 'device', 'show', interface))
        try:
            profile = str(uuid.UUID(active.strip())) if active is not None else ''
        except (ValueError, AttributeError):
            profile = ''
        if profile and active is not None and active.strip().lower() == profile:
            result['backend'] = 'networkmanager'
            result['nm_profile_policy'] = parse_nm_policy(run(
                ('nmcli', '--wait', '5', '--get-values',
                 '802-3-ethernet.wake-on-lan', 'connection', 'show', 'uuid', profile)))
            # Do not associate a stale result with a newly activated profile.
            again = run(('nmcli', '--wait', '5', '--get-values',
                         'GENERAL.CON-UUID', 'device', 'show', interface))
            if again is None or again.strip().lower() != profile:
                result['backend'] = result['nm_profile_policy'] = 'not_verified'
    elif nm in ({'LoadState': 'loaded', 'ActiveState': 'inactive'},
                {'LoadState': 'not-found', 'ActiveState': 'inactive'}):
        kind, path = selected_link(run(('udevadm', 'info', '--query=property',
                                       '--path=/sys/class/net/' + interface)))
        if path is not None:
            result['backend'] = 'systemd_udev'
            result['observed_link'] = kind
            result['base_link_policy'] = base_link_policy(link_reader(path))

    if read_identity(net, interface) != before:
        baseline['interface_state'] = 'interface_changed'
        return baseline
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Read-only WOL evidence (no configuration changes)')
    parser.add_argument('--interface', required=True)
    args = parser.parse_args(argv)
    result = inspect(args.interface)
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
