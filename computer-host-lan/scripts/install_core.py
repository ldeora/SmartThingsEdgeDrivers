#!/usr/bin/env python3
"""Transactional systemd installation of the Linux Host Agent (Python 3.10+).

No external Python dependencies. The installer never reads or backs up the
persistent installation ID and control token, and does not change firewalls,
networking, WOL rules or unrelated system units.

This tool is invoked by install-agent.sh after root/Python/user preflight. The
InstallTransaction class supports unprivileged filesystem fixture tests.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile

SYSTEMD_PATHS = (
    '/etc/systemd/system/linux-host-agent.service',
    '/etc/systemd/system/linux-host-agent-power.service',
    '/etc/systemd/system/linux-host-agent-power.socket',
)
POWER_DROPIN = '/etc/systemd/system/linux-host-agent.service.d/enable-power.conf'
WOL_DROPIN = '/etc/systemd/system/linux-host-agent.service.d/90-wol-interface.conf'
APP_FILES = (
    '/opt/linux-host-agent/linux_host_agent.py',
    '/opt/linux-host-agent/power_helper.py',
)
AVAHI_PATH = '/etc/avahi/services/linux-host-agent.service'
MANAGED_PATHS = frozenset((*SYSTEMD_PATHS, POWER_DROPIN, WOL_DROPIN, *APP_FILES, AVAHI_PATH))
BACKUP_BASE = '/var/backups/linux-host-agent'


@dataclass(frozen=True)
class Change:
    path: str
    content: bytes | None  # None means remove an app-owned file
    mode: int = 0o644


class InstallError(RuntimeError):
    pass


class InstallTransaction:
    def __init__(self, root: Path = Path('/')):
        self.root = root

    def location(self, absolute: str) -> Path:
        if absolute not in MANAGED_PATHS:
            raise InstallError(f'Not an approved managed path: {absolute}')
        return self.root / absolute.lstrip('/')

    @staticmethod
    def refuse_links(path: Path) -> None:
        if path.is_symlink():
            raise InstallError(f'Refusing to overwrite a symbolic link: {path}')
        if path.exists() and not path.is_file():
            raise InstallError(f'Refusing non-regular managed file: {path}')
        for parent in path.parents:
            if parent.is_symlink():
                raise InstallError(f'Refusing linked parent directory: {parent}')

    @staticmethod
    def atomic_file(path: Path, content: bytes, mode: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        fd, temporary = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def snapshot(self, changes: list[Change], *, previous: dict | None = None) -> Path:
        seen = set()
        for change in changes:
            if change.path in seen:
                raise InstallError(f'Duplicate managed file: {change.path}')
            seen.add(change.path)
            self.refuse_links(self.location(change.path))
        base = self.root / BACKUP_BASE.lstrip('/')
        base.mkdir(parents=True, exist_ok=True, mode=0o700)
        if base.is_symlink():
            raise InstallError('Refusing linked backup directory')
        os.chmod(base, 0o700)
        backup = Path(tempfile.mkdtemp(prefix='snapshot-', dir=base))
        os.chmod(backup, 0o700)
        records = []
        for index, change in enumerate(changes):
            destination = self.location(change.path)
            exists = destination.exists()
            record = {'path': change.path, 'existed': exists}
            if exists:
                source = backup / f'{index}.original'
                shutil.copy2(destination, source, follow_symlinks=False)
                st = destination.stat()
                record.update(file=f'{index}.original', mode=stat.S_IMODE(st.st_mode),
                              uid=st.st_uid, gid=st.st_gid)
            records.append(record)
        manifest = {'schema': 1, 'items': records, 'previous': previous or {}}
        (backup / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        (backup / 'manifest.json').chmod(0o600)
        return backup

    def apply(self, changes: list[Change]) -> None:
        for change in changes:
            destination = self.location(change.path)
            self.refuse_links(destination)
            if change.content is None:
                if destination.exists():
                    destination.unlink()
            else:
                self.atomic_file(destination, change.content, change.mode)

    def restore(self, backup: Path) -> dict:
        if backup.is_symlink() or (backup / 'manifest.json').is_symlink():
            raise InstallError('Refusing symlinked backup or manifest')
        data = json.loads((backup / 'manifest.json').read_text(encoding='utf-8'))
        if data.get('schema') != 1 or not isinstance(data.get('items'), list):
            raise InstallError('Unrecognized backup manifest')
        for record in data['items']:
            target = self.location(record['path'])
            self.refuse_links(target)
            if record['existed']:
                original = backup / record['file']
                if not original.is_file() or original.is_symlink() or original.parent != backup:
                    raise InstallError('Backup file missing or unsafe')
                self.atomic_file(target, original.read_bytes(), record['mode'])
                if os.geteuid() == 0:
                    os.chown(target, record['uid'], record['gid'])
            elif target.exists():
                target.unlink()
        return data.get('previous', {})


# v1 and v2 install into the SAME paths and use the same state account. A
# normal upgrade is only safe when the existing payload is clearly v2.
# These are read-only *identity hints*, not authentication of source code.
# Never read installation-id, control-token, or backup snapshot contents.
PROTOCOL_MARKER = re.compile(rb"""(?m)^\s*PROTOCOL\s*=\s*['"](linux-host-agent|computer-host-agent)['"]\s*(?:\#.*)?$""")
MAX_PROTOCOL_BYTES = 128 * 1024


def _managed_bytes(transaction: InstallTransaction, absolute: str) -> bytes | None:
    target = transaction.location(absolute)
    transaction.refuse_links(target)
    if not target.exists():
        return None
    # A no-follow, non-blocking descriptor also refuses a symlink/special-file
    # swap between the initial path check and the read.
    try:
        fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise InstallError('Existing managed path is not a regular file')
            content = stream.read(MAX_PROTOCOL_BYTES + 1)
    except (OSError, ValueError) as exc:
        raise InstallError('Existing managed installation could not be inspected safely') from exc
    if len(content) > MAX_PROTOCOL_BYTES:
        raise InstallError('Existing managed installation marker is unexpectedly large')
    return content


def detect_installed_protocol(root: Path = Path('/')) -> str:
    """Return absent/v1/v2/unknown; do not trust ambiguous existing layouts.

    No state-directory *contents* are ever opened. The caller must re-check
    under the exclusive installation lock before mutating anything.
    """
    trans = InstallTransaction(root)
    agent = _managed_bytes(trans, APP_FILES[0])
    avahi = _managed_bytes(trans, AVAHI_PATH)
    if agent is None:
        app_version = None
    else:
        names = set(PROTOCOL_MARKER.findall(agent))
        app_version = ({b'linux-host-agent': 'v1',
                        b'computer-host-agent': 'v2'}.get(next(iter(names)))
                       if len(names) == 1 else 'unknown')
    if avahi is None:
        avahi_version = None
    else:
        old = b'_linuxhost._tcp' in avahi
        new = b'_computerhost._tcp' in avahi
        avahi_version = 'v1' if old and not new else 'v2' if new and not old else 'unknown'
    if app_version == 'unknown' or avahi_version == 'unknown':
        return 'unknown'
    if app_version is not None and avahi_version is not None and app_version != avahi_version:
        return 'unknown'
    if app_version == 'v1' or avahi_version == 'v1':
        return 'v1'
    if app_version == 'v2':
        return 'v2'
    # A leftover v2 advertisement without an agent is not a verified v2
    # install. Other managed files or a retained state directory may belong
    # to v1, so a fresh install is unsafe until explicitly investigated.
    if avahi_version is not None:
        return 'unknown'
    for path in MANAGED_PATHS - {APP_FILES[0], AVAHI_PATH}:
        target = trans.location(path)
        trans.refuse_links(target)
        if target.exists():
            return 'unknown'
    state = root / 'var/lib/linux-host-agent'
    try:
        if state.is_symlink() or state.exists():
            return 'unknown'
    except OSError as exc:
        raise InstallError('Cannot safely inspect existing agent state directory') from exc
    return 'absent'


def require_v2_or_clean(root: Path = Path('/')) -> str:
    """Fail closed before install, uninstall, rollback, or preview."""
    state = detect_installed_protocol(root)
    if state == 'v1':
        raise InstallError(
            'Legacy v1 Linux Host LAN installation detected; refusing to replace it. '
            'An explicit, reviewed migration is required.')
    if state == 'unknown':
        raise InstallError(
            'Existing Linux Host Agent files or state could not be identified as v2. '
            'Refusing automatic changes; investigate before migration or repair.')
    return state


def generate_plan(source: Path, python_bin: str, *, enable_power: bool,
                  disable_power: bool, wol_interface: str | None,
                  is_existing_power: bool, avahi_dir: bool,
                  uninstall: bool = False) -> list[Change]:
    if uninstall:
        return [Change(path, None) for path in sorted(MANAGED_PATHS)]
    if enable_power and disable_power:
        raise InstallError('--enable-power and --disable-power are mutually exclusive')
    plan = []
    for name in ('linux_host_agent.py', 'power_helper.py'):
        plan.append(Change(f'/opt/linux-host-agent/{name}',
                           (source / 'agent' / name).read_bytes(), 0o755))
    unit_root = source / 'agent' / 'systemd'
    for absolute in SYSTEMD_PATHS:
        text = (unit_root / Path(absolute).name).read_text()
        if absolute.endswith('.service'):
            if '/usr/bin/python3' not in text:
                raise InstallError(f'Expected Python template placeholder in {absolute}')
            text = text.replace('/usr/bin/python3', python_bin)
        plan.append(Change(absolute, text.encode()))
    if enable_power:
        text = (unit_root / 'enable-power.conf').read_text().replace('/usr/bin/python3', python_bin)
        plan.append(Change(POWER_DROPIN, text.encode()))
    elif disable_power:
        plan.append(Change(POWER_DROPIN, None))
    elif is_existing_power:
        # Retain any locally customized power drop-in byte for byte. The
        # operator may explicitly refresh it with --enable-power.
        pass
    if wol_interface:
        plan.append(Change(WOL_DROPIN, f'[Service]\nEnvironment="LINUX_HOST_WOL_INTERFACE={wol_interface}"\n'.encode()))
    if avahi_dir:
        plan.append(Change(AVAHI_PATH, (unit_root / 'avahi-linux-host-agent.service').read_bytes()))
    return plan


def systemctl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(['systemctl', *args], check=check,
                          stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)


def state(service: str, prop: str) -> bool:
    return systemctl(prop, '--quiet', service, check=False).returncode == 0


def activate(previous: dict, *, power_enabled: bool, disable_power: bool) -> None:
    systemctl('daemon-reload')
    # Establish the opt-in helper socket before restarting the HTTP agent.
    if not power_enabled:
        systemctl('disable', '--now', 'linux-host-agent-power.socket', check=False)
    elif previous['first_install'] or previous['socket_active'] or previous['socket_enabled'] or previous.get('newly_enabled_power'):
        systemctl('enable', '--now', 'linux-host-agent-power.socket')
    if previous['first_install']:
        systemctl('enable', '--now', 'linux-host-agent.service')
    elif previous['agent_active']:
        systemctl('restart', 'linux-host-agent.service')
    # Preserve intentionally stopped/disabled existing services.


def restore_services(previous: dict) -> None:
    systemctl('daemon-reload')
    for unit, prefix in (('linux-host-agent.service', 'agent'),
                         ('linux-host-agent-power.socket', 'socket')):
        if previous.get(prefix + '_enabled'):
            systemctl('enable', unit)
        else:
            systemctl('disable', unit, check=False)
        if previous.get(prefix + '_active'):
            systemctl('restart', unit)
        else:
            systemctl('stop', unit, check=False)


def run_cli(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Install/rollback Linux Host systemd agent')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--install', action='store_true')
    action.add_argument('--plan', action='store_true', help='preview file changes; no root needed')
    action.add_argument('--check-existing', action='store_true',
                        help='read-only v1/v2 coexistence guard; no root needed')
    action.add_argument('--rollback', type=Path)
    action.add_argument('--uninstall', action='store_true')
    parser.add_argument('--source', type=Path)
    parser.add_argument('--python', dest='python_bin')
    parser.add_argument('--enable-power', action='store_true')
    parser.add_argument('--disable-power', action='store_true')
    parser.add_argument('--wol-interface', default=None)
    args = parser.parse_args(argv)
    if os.geteuid() != 0 and not (args.plan or args.check_existing):
        parser.error('must run as root')
    if (args.install or args.plan) and (not args.source or not args.python_bin):
        parser.error('installation needs --source and --python')
    if args.enable_power and args.disable_power:
        parser.error('power enable/disable flags conflict')
    if args.wol_interface and (len(args.wol_interface) > 15 or not args.wol_interface.replace('-', '').replace('_', '').replace('.', '').isalnum()):
        parser.error('invalid Ethernet interface name')
    if args.check_existing:
        require_v2_or_clean()
        return 0
    if args.plan:
        require_v2_or_clean()
        trans = InstallTransaction()
        changes = generate_plan(args.source, args.python_bin, enable_power=args.enable_power,
                                disable_power=args.disable_power, wol_interface=args.wol_interface,
                                is_existing_power=trans.location(POWER_DROPIN).exists(),
                                avahi_dir=Path('/etc/avahi/services').is_dir())
        for change in changes:
            target = trans.location(change.path)
            trans.refuse_links(target)
            operation = 'remove' if change.content is None else ('replace' if target.exists() else 'create')
            print(f'[PLAN] {operation}: {change.path}')
        print('Dry run only: no files, services, firewall or WOL settings changed.')
        return 0
    # Check before creating/chmodding the backup directory or lockfile. The
    # read-only guard must not itself mutate a legacy or unknown installation.
    require_v2_or_clean()
    backup_base = Path(BACKUP_BASE).resolve()
    backup_base.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(backup_base, 0o700)
    trans = InstallTransaction()
    lockfile = Path('/run/lock/linux-host-agent-install.lock')
    lockfile.parent.mkdir(parents=True, exist_ok=True)
    with lockfile.open('a+') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        # Check again after acquiring the lock. Nothing is removed, backed up,
        # or restarted if the payload is v1 or its owner is ambiguous.
        require_v2_or_clean()
        if args.rollback:
            # Reject symlink input *before* resolving it, and constrain the
            # resulting path to a direct child of the root-only backup base.
            if args.rollback.is_symlink():
                raise InstallError('Refusing symlinked backup path')
            target = args.rollback.resolve(strict=True)
            if target.parent != backup_base or target.is_symlink():
                raise InstallError('Backup must be a direct child of ' + str(backup_base))
            previous = trans.restore(target)
            restore_services(previous)
            print(f'Restored backup {target}; persistent ID, token and WOL unchanged.')
            return 0
        previous = dict(first_install=not trans.location(SYSTEMD_PATHS[0]).exists(),
                        agent_active=state('linux-host-agent.service','is-active'),
                        agent_enabled=state('linux-host-agent.service','is-enabled'),
                        socket_active=state('linux-host-agent-power.socket','is-active'),
                        socket_enabled=state('linux-host-agent-power.socket','is-enabled'),
                        newly_enabled_power=args.enable_power)
        is_existing_power = trans.location(POWER_DROPIN).exists()
        changes = generate_plan(args.source, args.python_bin, enable_power=args.enable_power,
                                disable_power=args.disable_power, wol_interface=args.wol_interface,
                                is_existing_power=is_existing_power,
                                avahi_dir=Path('/etc/avahi/services').is_dir(),
                                uninstall=args.uninstall)
        backup = trans.snapshot(changes, previous=previous)
        print(f'Recovery snapshot: {backup}', flush=True)
        try:
            if args.uninstall:
                systemctl('disable', '--now', 'linux-host-agent.service', check=False)
                systemctl('disable', '--now', 'linux-host-agent-power.socket', check=False)
            trans.apply(changes)
            if args.uninstall:
                systemctl('daemon-reload')
            else:
                activate(previous, power_enabled=args.enable_power or (is_existing_power and not args.disable_power),
                         disable_power=args.disable_power)
        except Exception as exc:
            print(f'Activation/install error: {type(exc).__name__}; restoring {backup}', flush=True)
            try:
                trans.restore(backup)
                restore_services(previous)
            except Exception as recovery_error:
                raise InstallError(f'Auto-rollback failed ({type(recovery_error).__name__}). Restore manually from {backup}') from exc
            raise
        print(f'Backup saved: {backup}')
        if args.uninstall:
            print('Managed files removed; user, persistent UUID, control token, WOL and backups retained.')
        else:
            print('Agent installed/upgraded; persistent UUID and key retained.')
        return 0


if __name__ == '__main__':
    try:
        raise SystemExit(run_cli())
    except (InstallError, OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f'Installation failed: {exc}')
