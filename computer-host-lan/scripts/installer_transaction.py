#!/usr/bin/env python3
"""Root-side Linux installer lifecycle foundation (NO elevation or CLI).

This module is not callable by the Go wizard yet. A future independently
installed root-owned launcher must authenticate the payload manifest and
invoke the controller from protected code after explicit authorization.
Do not run/import this module as root from an untrusted checkout.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import time
import uuid
from typing import Mapping, Protocol, Callable

import install_core as core
import payload_staging as staging
import runtime_verify
from transaction_journal import ProtectedJournal

_MANUAL_LOCK = Path('/run/lock/linux-host-agent-install.lock')
_PREAPPLY = frozenset(('INSPECTED', 'STAGED', 'SNAPSHOTTED'))
_APPLIED = frozenset(('APPLYING', 'ACTIVATING', 'VERIFYING'))
_ALLOWED_OPS = frozenset(('install', 'upgrade', 'repair'))
_PYTHON_PATH = re.compile(r'/[A-Za-z0-9_./+-]+\Z')
_IFNAME = re.compile(r'[A-Za-z0-9_.-]{1,15}\Z')


class ControllerError(RuntimeError):
    """All user-facing errors are fixed, sanitized codes."""

    def __init__(self, code: str):
        if code not in ('invalid_request', 'installation_busy', 'aborted',
                        'rolled_back', 'recovery_required',
                        'unsupported_environment'):
            code = 'recovery_required'
        super().__init__(code)
        self.code = code


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
                not self.python_bin.startswith(('/usr/bin/', '/bin/'))):
            # The future root launcher must pin an independently selected
            # trusted system interpreter, never an arbitrary user path.
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
        if not runtime_verify.valid_port(self.port):
            raise ControllerError('invalid_request')


@dataclass(frozen=True)
class InstallOutcome:
    status: str  # 'installed' or 'installed_cleanup_required'
    operation: str
    identity_preserved: str  # 'verified' or 'not_verified'
    source_verified: bool = True


@contextmanager
def manual_install_lock(path: Path = _MANUAL_LOCK, *,
                        owner_uid: int = 0):
    """Share the EXISTING shell install_core.py flock, not a second mutex.

    No chmod on an existing manual lock. Normal manual installs use a+ and
    permit 0600/0644. The lock is held over journal, staging, writes, service
    activation, verification, rollback and terminal cleanup.
    """
    fd = None
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC |
                     os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != owner_uid or
                info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o022):
            raise ControllerError('unsupported_environment')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ControllerError('installation_busy') from None
        yield
    except ControllerError:
        raise
    except OSError:
        raise ControllerError('unsupported_environment') from None
    finally:
        if fd is not None:
            os.close(fd)


class ServiceOperations(Protocol):
    """Trusted systemd/health boundary, replaceable in fixture tests."""

    def capture_previous(self, transaction: core.InstallTransaction) -> dict: ...
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
        if power_enabled:
            socket_active = bool(request.enable_power or previous['socket_active'])
            socket_enabled = bool(request.enable_power or previous['socket_enabled'])
        else:
            socket_active = socket_enabled = False
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
            return self._run_locked(request, source, trusted_hashes)

    def _run_locked(self, request: InstallRequest, source: Path,
                    trusted_hashes: Mapping[str, str]) -> InstallOutcome:
        store = ProtectedJournal(root=self.root, owner_uid=self.owner_uid)
        transaction = core.InstallTransaction(self.root)
        with store.begin(request.operation) as journal:
            receipt = None
            backup = None
            previous = None
            try:
                receipt = staging.stage_payload(source, trusted_hashes, journal,
                                                root=self.root, owner_uid=self.owner_uid)
                journal.advance('INSPECTED', 'STAGED')
                verified_source = receipt.verified_source_path(trusted_hashes)
                previous = self.services.capture_previous(transaction)
                _check_previous(previous)
                if (request.operation == 'install') != previous['first_install']:
                    raise ControllerError('invalid_request')
                if not previous['first_install'] and request.expected_identity is None:
                    # Never claim to preserve a SmartThings device identity
                    # without an authenticated expected value in memory.
                    raise ControllerError('invalid_request')
                previous['newly_enabled_power'] = request.enable_power
                power_dropin = transaction.location(core.POWER_DROPIN)
                transaction.refuse_links(power_dropin)
                existing_power = power_dropin.exists()
                power_enabled = request.enable_power or (
                    existing_power and not request.disable_power)
                changes = core.generate_plan(
                    verified_source, request.python_bin,
                    enable_power=request.enable_power,
                    disable_power=request.disable_power,
                    wol_interface=request.wol_interface,
                    is_existing_power=existing_power,
                    avahi_dir=(self.root / 'etc/avahi/services').is_dir(),
                )
                backup = transaction.snapshot(changes, previous=previous)
                _sync_snapshot(backup)
                journal.advance('STAGED', 'SNAPSHOTTED',
                                snapshot_name=backup.name)
                # NO managed file or service may change before this marker.
                journal.advance('SNAPSHOTTED', 'APPLYING')
                transaction.apply(changes)
                _sync_managed_directories(changes, transaction)
                journal.advance('APPLYING', 'ACTIVATING')
                self.services.activate(previous, power_enabled=power_enabled,
                                       disable_power=request.disable_power)
                journal.advance('ACTIVATING', 'VERIFYING')
                if self.services.verify_install(
                    request, previous, changes, power_enabled=power_enabled,
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
                                              'verified' if request.expected_identity else 'not_verified')
                    if phase in _PREAPPLY:
                        # This controller has not touched managed targets.
                        journal.abort(lambda _: True)
                        outcome = 'aborted'
                    elif phase in _APPLIED and backup is not None and previous is not None:
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
                raise ControllerError(outcome) from None
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
                                      'verified' if request.expected_identity else 'not_verified')
        return InstallOutcome('installed', request.operation,
                              'verified' if request.expected_identity else 'not_verified')

    def finish_terminal_cleanup(self) -> None:
        """Finish COMMITTED/ABORTED/ROLLED_BACK staging without reinstalling."""
        self._check_context()
        with manual_install_lock(self.manual_lock_path, owner_uid=self.owner_uid):
            journal = ProtectedJournal(root=self.root, owner_uid=self.owner_uid)
            with journal.resume_finished_cleanup() as transaction:
                staging.finish_terminal_stage(transaction, root=self.root,
                                              owner_uid=self.owner_uid)
                transaction.clear_finished()
