#!/usr/bin/env python3
"""Root-side Linux installer lifecycle foundation (NO elevation or CLI).

This module is not callable by the Go wizard yet. A future independently
installed root-owned launcher must authenticate the payload manifest and
invoke the controller from protected code after explicit authorization.
Do not run/import this module as root from an untrusted checkout.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
import errno
import fcntl
import json
import os
import pwd
from pathlib import Path
import re
import stat
import subprocess
import time
import uuid
from typing import Mapping, Protocol, Callable

import install_core as core
import payload_staging as staging
import runtime_verify
from transaction_journal import ProtectedJournal, JournalConflict, _staged_payload_remains

_MANUAL_LOCK = Path('/run/lock/linux-host-agent-install.lock')
_PREAPPLY = frozenset(('INSPECTED', 'STAGED', 'SNAPSHOTTED'))
_APPLIED = frozenset(('APPLYING', 'ACTIVATING', 'VERIFYING'))
_ALLOWED_OPS = frozenset(('install', 'upgrade', 'repair'))
# Safe public pre-apply failure stage names, never raw exception details.
_ABORT_STAGES = frozenset(('payload', 'existing_state', 'plan', 'snapshot'))
_PYTHON_PATH = re.compile(r'/[A-Za-z0-9_./+-]+\Z')
# Keep in sync with the fixed PATH allowlist in installer-entry.sh.
_TRUSTED_PYTHON_PREFIXES = ('/usr/sbin/', '/usr/bin/', '/sbin/', '/bin/')
_IFNAME = re.compile(r'[A-Za-z0-9_.-]{1,15}\Z')


class ControllerError(RuntimeError):
    """All user-facing errors are fixed, sanitized codes."""

    def __init__(self, code: str, *, failure_stage: str | None = None):
        if code not in ('invalid_request', 'installation_busy', 'aborted',
                        'rolled_back', 'recovery_required',
                        'unsupported_environment', 'adoption_required',
                        'unsafe_lock'):
            code = 'recovery_required'
        # This is a deliberate, fixed message with no private paths or ID.
        # The future Go wizard may display it without needing privileged
        # access to the retained agent state.
        message = (
            'Retained agent state cannot be automatically identified. '
            'If you have verified it belongs to a previous v2 installation, '
            'use the manual installer with --adopt-retained-state.'
            if code == 'adoption_required' else code
        )
        super().__init__(message)
        self.code = code
        # Only a fixed pre-apply stage can appear in the public JSON.
        # No filesystem paths, source data, UUIDs or exception strings.
        self.failure_stage = (failure_stage
                              if code == 'aborted' and
                              failure_stage in _ABORT_STAGES else None)


@dataclass(frozen=True)
class InstallRequest:
    operation: str
    python_bin: str
    expected_version: str
    expected_identity: str | None = None
    enable_power: bool = False
    disable_power: bool = False
    wol_interface: str | None = None
    port: int = 8765

    def validate(self) -> None:
        if type(self.operation) is not str or self.operation not in _ALLOWED_OPS:
            raise ControllerError('invalid_request')
        if (not isinstance(self.python_bin, str) or
                not _PYTHON_PATH.fullmatch(self.python_bin) or
                '..' in Path(self.python_bin).parts or
                not self.python_bin.startswith(_TRUSTED_PYTHON_PREFIXES)):
            # Accept only the same four fixed, root-controlled PATH
            # directories as installer-entry.sh. On Gentoo, python-exec
            # may expose an /usr/sbin/python3 wrapper; rejecting it here
            # after the shell accepted it makes real upgrades fail.
            # Never accept an arbitrary user-provided Python path.
            raise ControllerError('invalid_request')
        if not runtime_verify.valid_version(self.expected_version):
            raise ControllerError('invalid_request')
        if self.expected_identity is not None:
            try:
                if str(uuid.UUID(self.expected_identity)) != self.expected_identity:
                    raise ValueError('noncanonical UUID')
            except (ValueError, TypeError, AttributeError):
                raise ControllerError('invalid_request') from None
        if type(self.enable_power) is not bool or type(self.disable_power) is not bool:
            raise ControllerError('invalid_request')
        if self.enable_power and self.disable_power:
            raise ControllerError('invalid_request')
        if self.wol_interface is not None and (
            not isinstance(self.wol_interface, str) or
            not _IFNAME.fullmatch(self.wol_interface) or
            self.wol_interface in ('.', '..')
        ):
            raise ControllerError('invalid_request')
        if self.port != 8765 or type(self.port) is not int:
            raise ControllerError('invalid_request')


@dataclass(frozen=True)
class InstallOutcome:
    status: str  # 'installed' or 'installed_cleanup_required'
    operation: str
    identity_preserved: str  # 'verified' or 'not_verified'
    source_verified: bool = True


@dataclass(frozen=True)
class RecoveryOutcome:
    """Public, redacted summary; never include journal IDs or secret state."""
    status: str       # aborted, rolled_back, cleaned
    previous_phase: str | None = None


_UNSAFE_LOCK_ERRNOS = frozenset((
    errno.ELOOP, errno.EACCES, errno.EPERM, errno.EISDIR,
    errno.ENOTDIR, errno.ENXIO,
))


@contextmanager
def manual_install_lock(path: Path = _MANUAL_LOCK, *,
                        owner_uid: int = 0):
    """Hold the existing shared flock across the entire privileged transaction.

    Explicitly reject unsafe lock inodes. Unexpected filesystem errors
    while acquiring the lock are unsupported_environment, not unsafe_lock.
    Errors raised by operations *inside* the lock must not be recategorized
    as lock errors.
    """
    fd = None
    try:
        try:
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC |
                         os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
            info = os.fstat(fd)
        except OSError as exc:
            code = ('unsafe_lock' if exc.errno in _UNSAFE_LOCK_ERRNOS
                    else 'unsupported_environment')
            raise ControllerError(code) from None

        if (not stat.S_ISREG(info.st_mode) or info.st_uid != owner_uid or
                info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o022):
            raise ControllerError('unsafe_lock')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ControllerError('installation_busy') from None
        except OSError:
            raise ControllerError('unsupported_environment') from None
        yield
    finally:
        if fd is not None:
            os.close(fd)


class ServiceOperations(Protocol):
    """Trusted systemd/health boundary, replaceable in fixture tests."""

    def capture_previous(self, transaction: core.InstallTransaction) -> dict: ...
    def ensure_agent_user(self) -> None: ...
    def activate(self, previous: dict, *, power_enabled: bool,
                 disable_power: bool) -> None: ...
    def verify_install(self, request: InstallRequest, previous: dict,
                       changes: list[core.Change], *,
                       power_enabled: bool, transaction: core.InstallTransaction) -> bool: ...
    def restore_services(self, previous: dict) -> None: ...
    def verify_restored_services(self, previous: dict) -> bool: ...


class SystemdOperations:
    """Existing systemd semantics plus PR #73's bounded runtime verifier.

    Only used after an independently trusted root launcher has been created.
    In particular an intentionally stopped agent is NEVER started for a
    health probe and does not need an HTTP response to pass verification.
    """

    def __init__(self, *, health_probe: Callable = runtime_verify.verify_runtime):
        self.health_probe = health_probe

    def capture_previous(self, transaction: core.InstallTransaction) -> dict:
        return dict(
            first_install=not transaction.location(core.SYSTEMD_PATHS[0]).exists(),
            agent_active=core.state('linux-host-agent.service', 'is-active'),
            agent_enabled=core.state('linux-host-agent.service', 'is-enabled'),
            socket_active=core.state('linux-host-agent-power.socket', 'is-active'),
            socket_enabled=core.state('linux-host-agent-power.socket', 'is-enabled'),
        )

    def ensure_agent_user(self) -> None:
        """Match install-agent.sh's idempotent linuxhost user preflight.

        Called only AFTER the durable APPLYING marker. The service account
        is intentionally retained even if installation is rolled back,
        exactly as in the existing manual shell installer.
        """
        query = subprocess.run(['getent', 'passwd', 'linuxhost'], check=False,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=5)
        if query.returncode == 0:
            return
        shell = next((path for path in
                      ('/usr/sbin/nologin', '/sbin/nologin', '/bin/false')
                      if os.access(path, os.X_OK)), None)
        if shell is None:
            raise ControllerError('unsupported_environment')
        subprocess.run([
            'useradd', '--system', '--user-group',
            '--home-dir', '/var/lib/linux-host-agent',
            '--shell', shell, 'linuxhost'
        ], check=True, stdin=subprocess.DEVNULL,
           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
           timeout=10)

    def activate(self, previous: dict, *, power_enabled: bool,
                 disable_power: bool) -> None:
        core.activate(previous, power_enabled=power_enabled,
                      disable_power=disable_power)

    def verify_install(self, request: InstallRequest, previous: dict,
                       changes: list[core.Change], *,
                       power_enabled: bool, transaction: core.InstallTransaction) -> bool:
        # This is both for stopped and active installs: check the bytes we
        # actually wrote, rather than assuming successful systemctl calls
        # imply an installed agent.
        for change in changes:
            target = transaction.location(change.path)
            transaction.refuse_links(target)
            if change.content is None:
                if target.exists():
                    return False
            elif (not target.is_file() or target.read_bytes() != change.content or
                  stat.S_IMODE(target.stat().st_mode) != change.mode):
                return False
        should_run = previous['first_install'] or previous['agent_active']
        should_enable = previous['first_install'] or previous['agent_enabled']
        socket_active, socket_enabled = core.expected_socket_state(
            previous, power_enabled=power_enabled)
        def services_match() -> bool:
            return (
                core.state('linux-host-agent.service', 'is-active') == should_run and
                core.state('linux-host-agent.service', 'is-enabled') == should_enable and
                core.state('linux-host-agent-power.socket', 'is-active') == socket_active and
                core.state('linux-host-agent-power.socket', 'is-enabled') == socket_enabled
            )
        if not should_run:
            # Preserve intentionally stopped/disabled units, without HTTP.
            return services_match()
        # systemctl --now can return before the listener is ready, or while
        # systemd is transitioning to active. Retry BOTH service state and
        # live health within the bounded deadline to avoid false rollback.
        deadline = time.monotonic() + 12.0
        while True:
            if services_match():
                result = self.health_probe(
                    port=request.port, expected_version=request.expected_version,
                    expected_identity=request.expected_identity,
                    expected_power=power_enabled, service_status='active',
                )
                if (isinstance(result, dict) and
                        result.get('status') == 'passed' and
                        result.get('runtime_verified') is True and
                        (request.expected_identity is None or
                         result.get('identity_preserved') == 'passed')):
                    return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.5, remaining))

    def restore_services(self, previous: dict) -> None:
        core.restore_services(previous)

    def verify_restored_services(self, previous: dict) -> bool:
        for unit, prefix in (('linux-host-agent.service', 'agent'),
                             ('linux-host-agent-power.socket', 'socket')):
            for method, suffix in (('is-active', '_active'),
                                   ('is-enabled', '_enabled')):
                if core.state(unit, method) != previous[prefix + suffix]:
                    return False
        return True


def read_saved_identity(root: Path = Path('/')) -> str | None:
    """Read only the host's protected UUID; never return it in public JSON.

    A missing identity on an agent that has never started is legitimate.
    An existing but invalid identity must never be silently replaced.
    """
    filename = root / 'var/lib/linux-host-agent/installation-id'
    if filename.is_symlink():
        raise ControllerError('unsupported_environment')
    try:
        fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW |
                     os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError:
        return None
    except OSError:
        raise ControllerError('unsupported_environment') from None
    try:
        info = os.fstat(fd)
        # The agent atomically publishes installation-id with a hard link
        # to its temporary file. A crash before unlinking the temporary
        # filename can legitimately leave st_nlink == 2: it is not damage.
        if (not stat.S_ISREG(info.st_mode) or
                info.st_size < 36 or info.st_size > 38 or
                stat.S_IMODE(info.st_mode) & 0o022):
            raise ControllerError('unsupported_environment')
        if root == Path('/') and os.geteuid() == 0:
            # On an actual systemd installation StateDirectory is owned
            # by the linuxhost service user, not the elevated wizard.
            try:
                expected_uid = pwd.getpwnam('linuxhost').pw_uid
            except KeyError:
                raise ControllerError('unsupported_environment') from None
            if info.st_uid != expected_uid:
                raise ControllerError('unsupported_environment')
        raw = os.read(fd, 64).decode('ascii').strip()
        if str(uuid.UUID(raw)) != raw:
            raise ControllerError('unsupported_environment')
        return raw
    except (UnicodeError, ValueError, OSError):
        raise ControllerError('unsupported_environment') from None
    finally:
        os.close(fd)


def _check_previous(previous: dict) -> None:
    required = {'first_install', 'agent_active', 'agent_enabled',
                'socket_active', 'socket_enabled'}
    if (type(previous) is not dict or not required.issubset(previous) or
            any(type(previous[k]) is not bool for k in required)):
        raise ControllerError('unsupported_environment')


def _sync_snapshot(backup: Path) -> None:
    """Durably finish the old engine snapshot BEFORE journal SNAPSHOTTED."""
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY | os.O_CLOEXEC
    directory = os.open(backup, flags)
    try:
        entries = os.listdir(directory)
        if 'manifest.json' not in entries:
            raise ControllerError('recovery_required')
        for name in entries:
            if not (name == 'manifest.json' or re.fullmatch(r'[0-9]+\.original', name)):
                raise ControllerError('recovery_required')
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC |
                         os.O_NONBLOCK, dir_fd=directory)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ControllerError('recovery_required')
                os.fsync(fd)
            finally:
                os.close(fd)
        os.fsync(directory)
    finally:
        os.close(directory)
    parent = os.open(backup.parent, flags)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)


def _sync_managed_directories(changes: list[core.Change],
                              transaction: core.InstallTransaction) -> None:
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY | os.O_CLOEXEC
    for parent in {transaction.location(c.path).parent for c in changes}:
        if not parent.exists():
            # An absent optional drop-in may be a valid no-op removal.
            continue
        fd = os.open(parent, flags)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _files_match_snapshot(backup: Path, transaction: core.InstallTransaction) -> bool:
    """Independent local comparison BEFORE accepting rollback as complete."""
    try:
        if backup.is_symlink() or (backup / 'manifest.json').is_symlink():
            return False
        data = json.loads((backup / 'manifest.json').read_text(encoding='utf-8'))
        if type(data) is not dict or data.get('schema') != 1:
            return False
        records = data.get('items')
        if type(records) is not list or len(records) > len(core.MANAGED_PATHS):
            return False
        seen = set()
        for record in records:
            if type(record) is not dict or record.get('path') not in core.MANAGED_PATHS:
                return False
            path = record['path']
            if path in seen or type(record.get('existed')) is not bool:
                return False
            seen.add(path)
            target = transaction.location(path)
            transaction.refuse_links(target)
            if record['existed']:
                filename = record.get('file')
                if (not isinstance(filename, str) or
                        not re.fullmatch(r'[0-9]+\.original', filename)):
                    return False
                original = backup / filename
                if (original.parent != backup or original.is_symlink() or
                        not original.is_file() or not target.is_file()):
                    return False
                if (target.read_bytes() != original.read_bytes() or
                        stat.S_IMODE(target.stat().st_mode) != record['mode']):
                    return False
                if os.geteuid() == 0 and (
                    target.stat().st_uid != record['uid'] or
                    target.stat().st_gid != record['gid']
                ):
                    return False
            elif target.exists():
                return False
        return True
    except (OSError, KeyError, TypeError, ValueError, core.InstallError):
        return False


class InstallerBackend:
    """Transactional install/upgrade/repair engine; no public root entrypoint."""

    def __init__(self, *, root: Path = Path('/'), owner_uid: int = 0,
                 manual_lock_path: Path = _MANUAL_LOCK,
                 services: ServiceOperations | None = None):
        self.root = Path(root)
        self.owner_uid = owner_uid
        self.manual_lock_path = Path(manual_lock_path)
        self.services = services if services is not None else SystemdOperations()

    def _check_context(self) -> None:
        if os.geteuid() != self.owner_uid:
            raise ControllerError('unsupported_environment')
        # Root and lock injection exist ONLY for nonroot temporary fixtures.
        if self.root == Path('/') and (self.owner_uid != 0 or
                                      self.manual_lock_path != _MANUAL_LOCK):
            raise ControllerError('unsupported_environment')

    def run(self, request: InstallRequest, source: Path,
            trusted_hashes: Mapping[str, str]) -> InstallOutcome:
        if not isinstance(request, InstallRequest):
            raise ControllerError('invalid_request')
        request.validate()
        self._check_context()
        with manual_install_lock(self.manual_lock_path, owner_uid=self.owner_uid):
            # Do not stage a v2 agent over a v1/partial installation.
            # Use the same read-only classification as the manual CLI.
            try:
                core.require_v2_or_clean(self.root)
            except core.InstallError:
                # The wizard cannot automatically adopt legacy private
                # state. Distinguish *orphan-only* retained state from v1
                # or partially installed files, so the future UI can give
                # the operator the existing manual recovery instruction.
                try:
                    adoptable = (core.require_v2_or_clean(
                        self.root, adopt_retained_state=True) == 'adopted')
                except (core.InstallError, OSError):
                    adoptable = False
                raise ControllerError(
                    'adoption_required' if adoptable else 'unsupported_environment'
                ) from None
            return self._run_locked(request, source, trusted_hashes)

    def _run_locked(self, request: InstallRequest, source: Path,
                    trusted_hashes: Mapping[str, str]) -> InstallOutcome:
        store = ProtectedJournal(root=self.root, owner_uid=self.owner_uid)
        transaction = core.InstallTransaction(self.root)
        with store.begin(request.operation) as journal:
            receipt = None
            backup = None
            previous = None
            failure_stage = 'payload'
            try:
                receipt = staging.stage_payload(source, trusted_hashes, journal,
                                                root=self.root, owner_uid=self.owner_uid)
                journal.advance('INSPECTED', 'STAGED')
                verified_source = receipt.verified_source_path(trusted_hashes)
                failure_stage = 'existing_state'
                previous = self.services.capture_previous(transaction)
                _check_previous(previous)
                if (request.operation == 'install') != previous['first_install']:
                    raise ControllerError('invalid_request')
                # Only root-side code reads the protected UUID. The wizard
                # cannot supply or read it. A provided internal hint must
                # match the actual persisted ID, or we reject pre-apply.
                saved_identity = read_saved_identity(self.root)
                if (request.expected_identity is not None and
                        request.expected_identity != saved_identity):
                    raise ControllerError('invalid_request')
                # No identity on a never-started agent is valid: keep
                # monitoring usable but report preservation not verified.
                effective_request = replace(request, expected_identity=saved_identity)
                identity_state = ('verified' if
                                  saved_identity is not None and
                                  (previous['first_install'] or previous['agent_active'])
                                  else 'not_verified')
                previous['newly_enabled_power'] = request.enable_power
                power_dropin = transaction.location(core.POWER_DROPIN)
                transaction.refuse_links(power_dropin)
                existing_power = power_dropin.exists()
                power_enabled = request.enable_power or (
                    existing_power and not request.disable_power)
                failure_stage = 'plan'
                changes = core.generate_plan(
                    verified_source, request.python_bin,
                    enable_power=request.enable_power,
                    disable_power=request.disable_power,
                    wol_interface=request.wol_interface,
                    is_existing_power=existing_power,
                    avahi_dir=(self.root / 'etc/avahi/services').is_dir(),
                )
                failure_stage = 'snapshot'
                backup = transaction.snapshot(changes, previous=previous)
                _sync_snapshot(backup)
                journal.advance('STAGED', 'SNAPSHOTTED',
                                snapshot_name=backup.name)
                # NO managed file or service may change before this marker.
                journal.advance('SNAPSHOTTED', 'APPLYING')
                # The existing manual installer creates the service user
                # before install_core. The backend must do so as well,
                # but only AFTER journaling the first system mutation.
                # The marker must precede account creation: if useradd
                # fails on a clean host, this transaction's first-install
                # snapshot is still demonstrably v2 and can be rolled back.
                core.write_owner_record(self.root)
                self.services.ensure_agent_user()
                transaction.apply(changes)
                _sync_managed_directories(changes, transaction)
                journal.advance('APPLYING', 'ACTIVATING')
                self.services.activate(previous, power_enabled=power_enabled,
                                       disable_power=request.disable_power)
                journal.advance('ACTIVATING', 'VERIFYING')
                if self.services.verify_install(
                    effective_request, previous, changes, power_enabled=power_enabled,
                    transaction=transaction
                ) is not True:
                    raise ControllerError('recovery_required')
                journal.advance('VERIFYING', 'COMMITTED')
            except Exception:
                # If a durable COMMITTED record was written before an fsync
                # exception, never run rollback against a successful install.
                try:
                    phase = journal._record()['phase']
                    if phase == 'COMMITTED':
                        return InstallOutcome('installed_cleanup_required',
                                              request.operation,
                                              identity_state if previous is not None and
                                              'identity_state' in locals() else 'not_verified')
                    if phase in _PREAPPLY:
                        # This controller has not touched managed targets.
                        journal.abort(lambda _: True)
                        outcome = 'aborted'
                    elif phase in _APPLIED and backup is not None and previous is not None:
                        core.validate_v2_backup(backup, root=self.root)
                        restored = transaction.restore(backup)
                        self.services.restore_services(restored)
                        verified = (_files_match_snapshot(backup, transaction) and
                                    self.services.verify_restored_services(restored) is True)
                        journal.mark_rolled_back(lambda _: verified)
                        outcome = 'rolled_back'
                    else:
                        raise ControllerError('recovery_required')
                    if receipt is not None:
                        staging.retire_ready(receipt, trusted_hashes)
                    else:
                        staging.finish_terminal_stage(
                            journal, root=self.root, owner_uid=self.owner_uid)
                    journal.clear_finished()
                except Exception:
                    raise ControllerError('recovery_required') from None
                raise ControllerError(
                    outcome,
                    failure_stage=failure_stage if outcome == 'aborted' else None
                ) from None
            finally:
                if receipt is not None:
                    receipt.close()

            # COMMITTED is the point of no rollback. A failure to clean up
            # staging afterward means installation succeeded but a later
            # wizard run must complete the journal's terminal cleanup.
            try:
                staging.finish_terminal_stage(
                    journal, root=self.root, owner_uid=self.owner_uid)
                journal.clear_finished()
            except Exception:
                return InstallOutcome('installed_cleanup_required', request.operation,
                                      identity_state)
        return InstallOutcome('installed', request.operation,
                              identity_state)

    def _recover_locked(self, journal, transaction: core.InstallTransaction) -> RecoveryOutcome:
        """Resolve a durable nonterminal transaction, never resume an install.

        Recovery restores the PREVIOUS installation rather than trying to
        reconstruct interrupted feature choices. Both locks remain held.
        """
        phase = journal._record()['phase']
        if phase in _PREAPPLY:
            # No managed mutation occurs before the APPLYING record was
            # durably written. Even an interrupted APPLYING journal temp
            # cannot authorize writes that the controller has not begun.
            journal.abort(lambda _snapshot_name: True)
            staging.finish_terminal_stage(journal, root=self.root,
                                          owner_uid=self.owner_uid)
            journal.clear_finished()
            return RecoveryOutcome('aborted', phase)

        if phase not in _APPLIED:
            raise ControllerError('recovery_required')

        snapshot_name = journal._record()['snapshot_name']
        backup_base = self.root / core.BACKUP_BASE.lstrip('/')
        if (not backup_base.is_dir() or backup_base.is_symlink() or
                stat.S_IMODE(backup_base.stat().st_mode) & 0o077 or
                (self.root == Path('/') and backup_base.stat().st_uid != 0)):
            raise ControllerError('recovery_required')
        backup = backup_base / snapshot_name
        # The protected APPLYING+ journal is the authority for the limited
        # first-install exception. An interruption may predate the v2 marker.
        core.validate_v2_backup(
            backup, root=self.root, journal_owned_fresh_install=True)
        manifest = json.loads(core._read_backup_file(
            backup / 'manifest.json', core.MAX_BACKUP_MANIFEST_BYTES))
        previous = manifest.get('previous')
        _check_previous(previous)
        if previous['first_install']:
            # A journal-bound v2 snapshot lets a first install be retried
            # even if systemd created private state before the crash.
            core.write_owner_record(self.root)

        restored = transaction.restore(backup)
        _check_previous(restored)
        self.services.restore_services(restored)
        changes = [core.Change(item['path'], None) for item in manifest['items']]
        _sync_managed_directories(changes, transaction)
        verified = (_files_match_snapshot(backup, transaction) and
                    self.services.verify_restored_services(restored) is True)
        journal.mark_rolled_back(lambda _snapshot_name: verified)
        staging.finish_terminal_stage(journal, root=self.root,
                                      owner_uid=self.owner_uid)
        journal.clear_finished()
        return RecoveryOutcome('rolled_back', phase)

    def recover_interrupted(self) -> RecoveryOutcome:
        """Explicitly recover after power loss, SIGKILL or helper crash.

        No implicit rollback on a new install request. The snapshot is
        independently checked as v2 before any managed file is overwritten.
        """
        self._check_context()
        with manual_install_lock(self.manual_lock_path, owner_uid=self.owner_uid):
            store = ProtectedJournal(root=self.root, owner_uid=self.owner_uid)
            if store.public_status()['privileged_transaction_state'] == 'none':
                return RecoveryOutcome('nothing_to_recover')
            try:
                handle = store.resume_recovery()
            except JournalConflict:
                # A terminal transaction may have died during cleanup.
                # Distinguish that from a failed FIRST journal write with
                # no durable record at all. Neither path reinstalls files.
                try:
                    handle = store.resume_finished_cleanup()
                except JournalConflict:
                    # begin() writes INSPECTED before staging, snapshot or
                    # managed changes. With no persistent journal, exactly
                    # one validated temp marker, and no staged payload,
                    # the initial journal write is the only eligible orphan.
                    # The journal rechecks these invariants under its lock.
                    try:
                        store.reconcile_orphaned_staging(
                            lambda: not _staged_payload_remains(
                                self.root, self.owner_uid))
                        return RecoveryOutcome('cleaned')
                    except Exception:
                        raise ControllerError('recovery_required') from None
                except Exception:
                    raise ControllerError('recovery_required') from None
                with handle as journal:
                    try:
                        staging.finish_terminal_stage(
                            journal, root=self.root, owner_uid=self.owner_uid)
                        journal.clear_finished()
                        return RecoveryOutcome('cleaned')
                    except Exception:
                        raise ControllerError('recovery_required') from None
            with handle as journal:
                try:
                    return self._recover_locked(journal, core.InstallTransaction(self.root))
                except Exception:
                    # Keep the journal/snapshot if rollback wasn't verified.
                    raise ControllerError('recovery_required') from None

    def finish_terminal_cleanup(self) -> None:
        """Finish COMMITTED/ABORTED/ROLLED_BACK staging without reinstalling."""
        self._check_context()
        with manual_install_lock(self.manual_lock_path, owner_uid=self.owner_uid):
            journal = ProtectedJournal(root=self.root, owner_uid=self.owner_uid)
            with journal.resume_finished_cleanup() as transaction:
                staging.finish_terminal_stage(transaction, root=self.root,
                                              owner_uid=self.owner_uid)
                transaction.clear_finished()
