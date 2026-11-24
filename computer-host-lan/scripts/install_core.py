#!/usr/bin/env python3
"""Transactional systemd installation of the Linux Host Agent (Python 3.10+).

No external Python dependencies. The installer never reads or backs up the
persistent installation ID and control token, and does not change firewalls,
networking, WOL rules or unrelated system units.

Shared primitives for the protected installer and read-only source diagnostics.
The standalone CLI cannot mutate the host; InstallTransaction remains available
to the protected controller and unprivileged filesystem fixture tests.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import sys
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
OWNER_DIR = '/var/lib/linux-host-agent-installer'
OWNER_FILE = OWNER_DIR + '/protocol'
OWNER_CONTENT = b'v2\n'
MAX_BACKUP_MANIFEST_BYTES = 256 * 1024


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
        manifest = {'schema': 1, 'installer_protocol': 'v2', 'items': records, 'previous': previous or {}}
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
        names = PROTOCOL_MARKER.findall(agent)
        app_version = ({b'linux-host-agent': 'v1',
                        b'computer-host-agent': 'v2'}.get(names[0])
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
    if state.is_symlink() or (state.exists() and not state.is_dir()):
        raise InstallError('Unsafe existing agent state directory')
    # The owner record is only decisive if NO managed files remain. It can
    # never override a v1 marker, a mixed installation, or unknown files.
    if owner_record_exists(root):
        return 'v2'
    if state.exists() or (root / OWNER_DIR.lstrip('/')).exists():
        return 'unknown'
    return 'absent'


def _owner_paths(root: Path) -> tuple[Path, Path]:
    folder = root / OWNER_DIR.lstrip('/')
    file = root / OWNER_FILE.lstrip('/')
    InstallTransaction.refuse_links(file)
    if folder.exists() and not folder.is_dir():
        raise InstallError('Unsafe installer ownership directory')
    return folder, file


def owner_record_exists(root: Path = Path('/')) -> bool:
    """Read the non-secret v2 marker for normal-user preflight and planning.

    A missing marker is distinct from an unreadable or unsafe one: the
    latter must be an InstallError, never a traceback or silent adoption.
    """
    try:
        folder, file = _owner_paths(root)
        try:
            marker = os.lstat(file)
        except FileNotFoundError:
            return False
        directory = folder.stat()
        if (not stat.S_ISDIR(directory.st_mode) or
                not stat.S_ISREG(marker.st_mode) or
                stat.S_IMODE(directory.st_mode) & 0o022 or
                stat.S_IMODE(marker.st_mode) & 0o022):
            raise InstallError('Installer ownership marker has unsafe permissions or type')
        if root == Path('/') and (directory.st_uid != 0 or marker.st_uid != 0):
            raise InstallError('Installer ownership marker must be root-owned')
        # 0755/0644 allows an unprivileged read-only wizard to distinguish
        # a legitimate retained v2 installation after uninstall. The record
        # contains only the fixed string "v2", never the private UUID/key.
        fd = os.open(file, os.O_RDONLY | os.O_NOFOLLOW |
                     os.O_NONBLOCK | os.O_CLOEXEC)
        with os.fdopen(fd, 'rb') as inp:
            info = os.fstat(inp.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                    info.st_size != len(OWNER_CONTENT) or
                    stat.S_IMODE(info.st_mode) & 0o022 or
                    (root == Path('/') and info.st_uid != 0)):
                raise InstallError('Invalid installer ownership record')
            if inp.read(len(OWNER_CONTENT) + 1) != OWNER_CONTENT:
                raise InstallError('Unknown installer ownership record version')
    except OSError as exc:
        raise InstallError('Cannot inspect installer ownership record safely') from exc
    return True

def write_owner_record(root: Path = Path('/')) -> None:
    """Publish a complete v2 intent directory before activation.

    Caller must hold the shared installer lock and have authorized v2
    intent. Never repair or adopt a preexisting incomplete final marker.
    A killed writer may leave a private-named sibling, which is never an
    ownership record. Existing valid markers are synced again on retry.
    """
    folder, file = _owner_paths(root)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    uid = 0 if root == Path('/') else os.geteuid()

    def check_directory(fd):
        info = os.fstat(fd)
        if info.st_uid != uid or stat.S_IMODE(info.st_mode) & 0o022:
            raise InstallError('Unsafe installer ownership parent')

    try:
        with ExitStack() as stack:
            fd = os.open(root, flags)
            stack.callback(os.close, fd)
            check_directory(fd)
            ancestors = [fd]
            for component in folder.parent.relative_to(root).parts:
                created = False
                try:
                    child = os.open(component, flags, dir_fd=fd)
                except FileNotFoundError:
                    os.mkdir(component, 0o700, dir_fd=fd)
                    created = True
                    child = os.open(component, flags, dir_fd=fd)
                stack.callback(os.close, child)
                check_directory(child)
                if created:
                    os.fchmod(child, 0o755)
                ancestors.append(child)
                fd = child

            if owner_record_exists(root):
                published = os.open(folder.name, flags, dir_fd=fd)
                stack.callback(os.close, published)
                check_directory(published)
                marker = os.open(file.name, os.O_RDONLY | os.O_NOFOLLOW |
                                 os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=published)
                stack.callback(os.close, marker)
                # Retry must cover a crash after publication, before sync.
                os.fsync(marker)
                os.fsync(published)
            else:
                try:
                    os.stat(folder.name, dir_fd=fd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise InstallError(
                        'Installer ownership directory exists without a valid record')
                name = '.linux-host-agent-installer-pending-' + secrets.token_hex(16)
                os.mkdir(name, 0o700, dir_fd=fd)
                pending = None
                renamed = False
                try:
                    pending = os.open(name, flags, dir_fd=fd)
                    check_directory(pending)
                    marker = os.open(file.name, os.O_WRONLY | os.O_CREAT |
                                     os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                     0o600, dir_fd=pending)
                    with os.fdopen(marker, 'wb') as out:
                        os.fchmod(out.fileno(), 0o644)
                        out.write(OWNER_CONTENT)
                        out.flush()
                        os.fsync(out.fileno())
                    os.fchmod(pending, 0o755)
                    os.fsync(pending)
                    # The root-owned parent and shared installer lock
                    # exclude competing writers. Never replace an observed
                    # preexisting final entry, even if it is empty.
                    try:
                        os.stat(folder.name, dir_fd=fd, follow_symlinks=False)
                    except FileNotFoundError:
                        pass
                    else:
                        raise InstallError('Installer ownership entry already exists')
                    os.rename(name, folder.name, src_dir_fd=fd, dst_dir_fd=fd)
                    renamed = True
                finally:
                    if pending is not None:
                        if not renamed:
                            try:
                                os.unlink(file.name, dir_fd=pending)
                            except FileNotFoundError:
                                pass
                        os.close(pending)
                    if not renamed:
                        os.rmdir(name, dir_fd=fd)
            # Sync every existing ancestor, not only ones created in this
            # invocation: recovery may follow an interrupted mkdir/rename.
            for ancestor in reversed(ancestors):
                os.fsync(ancestor)
    except OSError as exc:
        raise InstallError('Cannot safely write installer ownership record') from exc


def _retained_state_only(root: Path) -> bool:
    """True only for legacy-ambiguous state WITHOUT any managed files."""
    if owner_record_exists(root):
        return False
    state = root / 'var/lib/linux-host-agent'
    if state.is_symlink() or not state.is_dir():
        return False
    trans = InstallTransaction(root)
    for managed in MANAGED_PATHS:
        target = trans.location(managed)
        trans.refuse_links(target)
        if target.exists():
            return False
    return True


def require_v2_or_clean(root: Path = Path('/'), *, classify_orphan_state: bool = False) -> str:
    """Classify existing state without adopting or mutating retained credentials."""
    state = detect_installed_protocol(root)
    if state == 'v1':
        raise InstallError(
            'Legacy v1 Linux Host LAN installation detected; refusing to replace it. '
            'An explicit, reviewed migration is required.')
    if state == 'unknown':
        if classify_orphan_state and _retained_state_only(root):
            return 'orphan_state'
        raise InstallError(
            'Retained agent state cannot be verified as a supported v2 installation. '
            'Adoption is not supported in v1.0. Preserve the retained state, identity, '
            'key and backups; do not delete or regenerate them. '
            'Seek recovery guidance before retrying.')
    if classify_orphan_state:
        raise InstallError('Orphan-state classification applies only when retained state '
                           'exists without managed files or a v2 ownership record')
    return state


def _read_backup_file(path: Path, limit: int) -> bytes:
    """Read only a regular root-controlled snapshot file, never a link/pipe."""
    if path.is_symlink() or not path.is_file():
        raise InstallError('Backup snapshot contains a linked or non-regular file')
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        with os.fdopen(fd, 'rb') as inp:
            if not stat.S_ISREG(os.fstat(inp.fileno()).st_mode):
                raise InstallError('Backup item is not a regular file')
            contents = inp.read(limit + 1)
    except OSError as exc:
        raise InstallError('Backup snapshot could not be inspected safely') from exc
    if len(contents) > limit:
        raise InstallError('Backup snapshot file exceeds inspection bound')
    return contents


def validate_v2_backup(backup: Path, *, root: Path = Path('/'),
                       journal_owned_fresh_install: bool = False) -> None:
    """Validate the RESTORE SOURCE, not the possibly damaged current install.

    Normal manual rollback requires a persistent v2 ownership record for an
    empty-agent backup. A trusted root-side controller may set the explicit
    exception ONLY after acquiring the matching protected APPLYING+ journal:
    first-install crashes can precede publication of the owner record.
    This exception still requires v2 snapshot provenance; it never adopts v1.
    """
    if backup.is_symlink() or not backup.is_dir() or backup.stat().st_mode & 0o077:
        raise InstallError('Backup snapshot folder is missing or insecure')
    if root == Path('/') and backup.stat().st_uid != 0:
        raise InstallError('Backup snapshot must be root-owned')
    manifest_path = backup / 'manifest.json'
    data_bytes = _read_backup_file(manifest_path, MAX_BACKUP_MANIFEST_BYTES)
    if manifest_path.stat().st_mode & 0o077 or (
            root == Path('/') and manifest_path.stat().st_uid != 0):
        raise InstallError('Backup manifest permissions or owner are unsafe')
    try:
        manifest = json.loads(data_bytes.decode('utf-8'))
    except (ValueError, UnicodeError) as exc:
        raise InstallError('Backup manifest is malformed') from exc
    if not isinstance(manifest, dict) or manifest.get('schema') != 1 or (
            not isinstance(manifest.get('items'), list)):
        raise InstallError('Unrecognized backup manifest')
    seen = set()
    existing = {}
    for index, item in enumerate(manifest['items']):
        if not isinstance(item, dict) or item.get('path') not in MANAGED_PATHS or (
                type(item.get('existed')) is not bool):
            raise InstallError('Invalid backup manifest item')
        path = item['path']
        if path in seen:
            raise InstallError('Duplicate backup manifest item')
        seen.add(path)
        if item['existed']:
            file_name = f'{index}.original'
            if item.get('file') != file_name or (
                    not isinstance(item.get('mode'), int)) or (
                    not isinstance(item.get('uid'), int)) or (
                    not isinstance(item.get('gid'), int)):
                raise InstallError('Invalid backed-up file metadata')
            source = backup / file_name
            # Read each payload before any rollback writes, to avoid a
            # partially restored host due to a missing source/special file.
            content = _read_backup_file(source, 2 * 1024 * 1024)
            existing[path] = content
        else:
            existing[path] = None
    if APP_FILES[0] not in seen:
        raise InstallError('Backup has no agent entry; origin cannot be established')
    agent = existing[APP_FILES[0]]
    if agent is None:
        # A first-install snapshot has NO agent to identify. We only accept
        # snapshots explicitly issued by this v2 engine with a durable
        # protected v2 owner record. Old v1 snapshots lack this provenance.
        if (manifest.get('installer_protocol') != 'v2' or
                not (owner_record_exists(root) or journal_owned_fresh_install)):
            raise InstallError('Unverifiable empty-agent backup; refusing v1 adoption')
    else:
        markers = PROTOCOL_MARKER.findall(agent)
        if markers != [b'computer-host-agent']:
            raise InstallError('Backup contains legacy v1 or unknown agent; refusing rollback')
    if AVAHI_PATH in existing and existing[AVAHI_PATH] is not None:
        avahi = existing[AVAHI_PATH]
        if b'_computerhost._tcp' not in avahi or b'_linuxhost._tcp' in avahi:
            raise InstallError('Backup contains legacy or unrecognized Avahi service')
    if not isinstance(manifest.get('previous', {}), dict):
        raise InstallError('Backup service-state metadata is invalid')


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


_SYSTEMCTL_TIMEOUT_SECONDS = 120  # Bounded per operation, not per transaction.




def systemctl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    # The Go bootstrap does not forcibly kill an APPLYING/rollback
    # transaction. Bound individual systemd calls instead so that Python
    # can handle failures and complete its own verified rollback.
    command = ['systemctl', *args]
    try:
        return subprocess.run(command, check=check, stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                              text=True, timeout=_SYSTEMCTL_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        # A timed-out systemctl is never successful. For best-effort
        # restore/disable/stop calls, preserve check=False semantics so
        # remaining units are still attempted; final service verification
        # determines whether rollback is actually complete.
        if not check:
            return subprocess.CompletedProcess(command, 124, stderr='')
        raise subprocess.CalledProcessError(124, command) from exc


def state(service: str, prop: str) -> bool:
    return systemctl(prop, '--quiet', service, check=False).returncode == 0


def expected_socket_state(previous: dict, *, power_enabled: bool) -> tuple[bool, bool]:
    """Effective socket active/enabled result of activate(), not its inputs."""
    if not power_enabled:
        return False, False
    if (previous['first_install'] or previous['socket_active'] or
            previous['socket_enabled'] or previous.get('newly_enabled_power')):
        # 'enable --now' activates AND enables, even if previously stopped.
        return True, True
    return bool(previous['socket_active']), bool(previous['socket_enabled'])


def activate(previous: dict, *, power_enabled: bool, disable_power: bool) -> None:
    systemctl('daemon-reload')
    # Establish the opt-in helper socket before restarting the HTTP agent.
    if not power_enabled:
        systemctl('disable', '--now', 'linux-host-agent-power.socket', check=False)
    elif expected_socket_state(previous, power_enabled=power_enabled) == (True, True):
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


def require_no_wizard_transaction(*, root: Path = Path('/'),
                                  owner_uid: int = 0) -> None:
    """Refuse manual writes until a wizard transaction is fully reconciled.

    Read-only and safe with no journal installed. Import at call time:
    install_core remains usable standalone during ordinary manual installs.
    """
    from transaction_journal import ProtectedJournal
    try:
        state = ProtectedJournal(root=root, owner_uid=owner_uid).public_status()
    except Exception:
        raise InstallError('Cannot verify protected wizard journal state') from None
    if state.get('privileged_transaction_state') != 'none':
        raise InstallError('An unfinished wizard installation requires recovery first')


def run_cli(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Read-only Linux Host installation diagnostics')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--install', action='store_true', help='retired; use verified release installer')
    action.add_argument('--plan', action='store_true', help='preview file changes; no root needed')
    action.add_argument('--check-wizard-journal', action='store_true',
                        help='read-only root journal diagnostic')
    action.add_argument('--check-existing', action='store_true',
                        help='read-only v1/v2 coexistence guard; no root needed')
    action.add_argument('--rollback', type=Path, help='historical restoration not supported')
    action.add_argument('--uninstall', action='store_true', help='retired; use verified release installer')
    parser.add_argument('--source', type=Path)
    parser.add_argument('--python', dest='python_bin')
    parser.add_argument('--enable-power', action='store_true')
    parser.add_argument('--disable-power', action='store_true')
    parser.add_argument('--wol-interface', default=None)
    parser.add_argument('--adopt-retained-state', action='store_true',
                        help='retired; retained-state adoption not supported')
    args = parser.parse_args(argv)
    if args.install or args.uninstall or args.rollback is not None:
        raise InstallError('Legacy mutation disabled; use the independently verified release installer wizard/CLI. Historical restore is not supported; preserve backups and seek recovery guidance.')
    if args.adopt_retained_state:
        raise InstallError('Retained agent state cannot be verified as a supported v2 installation. Adoption is not supported in v1.0. Preserve the retained state, identity, key and backups; do not delete or regenerate them. Seek recovery guidance before retrying.')
    if os.geteuid() != 0 and not (args.plan or args.check_existing):
        parser.error('must run as root')
    if args.plan and (not args.source or not args.python_bin):
        parser.error('plan needs --source and --python')
    if args.enable_power and args.disable_power:
        parser.error('power enable/disable flags conflict')
    if args.wol_interface and (len(args.wol_interface) > 15 or
            not args.wol_interface.replace('-', '').replace('_', '').replace('.', '').isalnum()):
        parser.error('invalid Ethernet interface name')

    if args.check_wizard_journal:
        require_no_wizard_transaction()
        return 0
    if args.check_existing:
        try:
            require_v2_or_clean()
        except InstallError as exc:
            print(f'Existing agent check failed: {exc}', file=sys.stderr)
            return 2
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

    raise InstallError('Unsupported read-only operation')


if __name__ == '__main__':
    try:
        raise SystemExit(run_cli())
    except (InstallError, OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f'Installation failed: {exc}')
