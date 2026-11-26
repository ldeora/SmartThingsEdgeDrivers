#!/usr/bin/env python3
"""Root-side Linux installer transaction engine (no elevation or public CLI).

The Go bootstrap installs the root-owned launcher and verified manifest;
installer_root.py dispatches explicitly authorized wizard and CLI requests
to this controller. Do not run/import as root from an untrusted checkout.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, replace
import errno
import fcntl
import hashlib
import json
import os
import pwd
from pathlib import Path
import re
import secrets
import stat
import subprocess
import time
import uuid
from typing import Mapping, Protocol, Callable

import install_core as core
import payload_staging as staging
import runtime_verify
import credential_continuity as continuity
import wol_ownership
from persistent_wol import WolError
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

    def __init__(self, code: str, *, failure_stage: str | None = None,
                 credential_result: continuity.Result = continuity.Result(),
                 wol_review_required: bool = False):
        if code not in ('invalid_request', 'installation_busy', 'aborted',
                        'rolled_back', 'recovery_required',
                        'unsupported_environment', 'adoption_required',
                        'unsafe_lock', 'not_installed', 'wol_review_required'):
            code = 'recovery_required'
        # This is a deliberate, fixed message with no private paths or ID.
        # The Go wizard may display it without needing privileged
        # access to the retained agent state.
        message = (
            'Retained agent state cannot be verified as a supported v2 installation. '
            'Adoption is not supported in v1.0. Preserve the retained state, identity, '
            'key and backups; do not delete or regenerate them. '
            'Seek recovery guidance before retrying.'
            if code == 'adoption_required' else code
        )
        super().__init__(message)
        self.code = code
        self.credential_result = credential_result
        self.wol_review_required = (code == 'rolled_back' and wol_review_required is True)
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
    # Optional digest of the explicitly reviewed visible WOL policy.
    wol_plan_digest: str | None = None

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
        if self.wol_plan_digest is not None and (
                self.wol_interface is None or not isinstance(self.wol_plan_digest, str)
                or not re.fullmatch(r'[0-9a-f]{64}', self.wol_plan_digest)):
            raise ControllerError('invalid_request')
        if self.port != 8765 or type(self.port) is not int:
            raise ControllerError('invalid_request')


@dataclass(frozen=True)
class InstallOutcome:
    status: str  # 'installed' or 'installed_cleanup_required'
    operation: str
    identity_preserved: str  # 'verified' or 'not_verified'
    source_verified: bool = True
    credential_result: continuity.Result = continuity.Result()


@dataclass(frozen=True)
class UninstallOutcome:
    status: str  # 'uninstalled' or 'uninstalled_cleanup_required'
    identity_preserved: str  # 'verified' or 'not_verified'
    credential_result: continuity.Result = continuity.Result()


@dataclass(frozen=True)
class RecoveryOutcome:
    """Public, redacted summary; never include journal IDs or secret state."""
    status: str       # aborted, rolled_back, cleaned
    previous_phase: str | None = None
    operation: str | None = None  # fixed journal operation, never an identifier
    wol_review_required: bool = False

    @property
    def credential_result(self):
        return continuity.Result(reason=(
            '' if self.status == 'nothing_to_recover' else
            'continuity_unverified_after_interruption'))


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
    def prepare_restore(self, previous: dict) -> None: ...
    def restore_services(self, previous: dict) -> None: ...
    def verify_restored_services(self, previous: dict) -> bool: ...
    def stop_for_uninstall(self) -> None: ...
    def verify_uninstall_stopped(self) -> bool: ...
    def reload_after_uninstall(self) -> None: ...
    def verify_uninstall_services(self) -> bool: ...


class SystemdOperations:
    """Existing systemd semantics plus PR #73's bounded runtime verifier.

    Only used after an independently trusted root launcher has been created.
    In particular an intentionally stopped agent is NEVER started for a
    health probe and does not need an HTTP response to pass verification.
    """

    def __init__(self, *, health_probe: Callable = runtime_verify.verify_runtime):
        self.health_probe = health_probe

    def capture_previous(self, transaction: core.InstallTransaction) -> dict:
        first_install = not transaction.location(core.SYSTEMD_PATHS[0]).exists()
        result = dict(first_install=first_install)
        for unit, prefix in (('linux-host-agent.service', 'agent'),
                             ('linux-host-agent-power.socket', 'socket')):
            state = self._uninstall_unit_state(unit)
            # Failed/auto-restarting units are explicitly observed broken
            # units, not failed queries. Normalize their rollback state to
            # inactive; remember that an upgrade/repair should retry them.
            broken = (not first_install and state is not None and
                      state['LoadState'] == 'loaded' and
                      state['UnitFileState'] in ('enabled', 'disabled') and
                      (state['ActiveState'] == 'failed' or
                       (state['ActiveState'] == 'activating' and
                        state['SubState'] in ('auto-restart', 'auto-restart-queued'))))
            observed = ((False, state['UnitFileState'] == 'enabled') if broken
                        else self._stable_unit_state(state, absent=first_install))
            if observed is None:
                raise ControllerError('unsupported_environment')
            result[prefix + '_active'], result[prefix + '_enabled'] = observed
            if broken:
                result[prefix + '_retry'] = True
        if first_install and (
                self._stable_unit_state(self._uninstall_unit_state(
                    'linux-host-agent-power.service'), absent=True) is None or
                not _enablement_absent(transaction)):
            raise ControllerError('unsupported_environment')
        return result

    @staticmethod
    def _stable_unit_state(state: dict[str, str] | None, *,
                           absent: bool = False) -> tuple[bool, bool] | None:
        if state is None:
            return None
        if absent:
            if (state['LoadState'] == 'not-found' and
                    state['ActiveState'] == 'inactive' and
                    state['UnitFileState'] in ('', 'not-found')):
                return False, False
            return None
        if (state['LoadState'] != 'loaded' or
                state['ActiveState'] not in ('active', 'inactive') or
                state['UnitFileState'] not in ('enabled', 'disabled')):
            return None
        return (state['ActiveState'] == 'active',
                state['UnitFileState'] == 'enabled')

    def _services_match(self, agent: tuple[bool, bool],
                        socket: tuple[bool, bool], *, absent: bool = False) -> bool:
        # Query both units even if the first fails. None is never equal
        # to a valid expected pair, including (False, False).
        actual_agent = self._stable_unit_state(self._uninstall_unit_state(
            'linux-host-agent.service'), absent=absent)
        actual_socket = self._stable_unit_state(self._uninstall_unit_state(
            'linux-host-agent-power.socket'), absent=absent)
        return actual_agent == agent and actual_socket == socket

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
        effective = self._activation_previous(previous, power_enabled)
        # Stop an auto-restart loop and clear failure/start-limit counters
        # before attempting the reviewed repair. No changes before APPLYING.
        for unit, retry in (('linux-host-agent.service', previous.get('agent_retry')),
                            ('linux-host-agent-power.socket', previous.get('socket_retry'))):
            if retry:
                core.systemctl('stop', unit)
                core.systemctl('reset-failed', unit, check=False)
        core.activate(effective, power_enabled=power_enabled,
                      disable_power=disable_power)
        if not power_enabled:
            core.systemctl('reset-failed', 'linux-host-agent-power.socket', check=False)

    @staticmethod
    def _activation_previous(previous: dict, power_enabled: bool) -> dict:
        # Retry broken services, but do not start intentionally stopped
        # healthy agents. Rollback uses the original normalized booleans.
        effective = dict(previous)
        if previous.get('agent_retry') is True:
            effective['agent_active'] = True
        if power_enabled and previous.get('socket_retry') is True:
            effective['socket_active'] = True
        return effective

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
        previous = self._activation_previous(previous, power_enabled)
        should_run = previous['first_install'] or previous['agent_active']
        should_enable = previous['first_install'] or previous['agent_enabled']
        socket_active, socket_enabled = core.expected_socket_state(
            previous, power_enabled=power_enabled)
        def services_match() -> bool:
            return self._services_match((should_run, should_enable),
                                        (socket_active, socket_enabled))
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

    def stop_for_uninstall(self) -> None:
        # Stop socket activation first, then explicitly stop the static
        # power-helper service as well as the HTTP agent. Require successful
        # commands: a failed disable must not leave dangling wants links
        # after the corresponding unit file is removed.
        core.systemctl('disable', '--now', 'linux-host-agent-power.socket')
        core.systemctl('stop', 'linux-host-agent-power.service')
        core.systemctl('disable', '--now', 'linux-host-agent.service')
        for unit in ('linux-host-agent-power.socket', 'linux-host-agent-power.service',
                     'linux-host-agent.service'):
            core.systemctl('reset-failed', unit, check=False)

    @staticmethod
    def _uninstall_unit_state(unit: str) -> dict[str, str] | None:
        # Unlike a negated is-active/is-enabled return code, an explicit
        # state cannot mistake a timeout, missing bus, or query failure for
        # proof that a unit has stopped or is disabled. Request empty fields
        # too: after deletion systemd reports an empty UnitFileState.
        try:
            result = subprocess.run(
                ['systemctl', 'show', '--all', '--no-pager',
                 '--property=LoadState,ActiveState,SubState,UnitFileState', '--', unit],
                check=False, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0 or not isinstance(result.stdout, str):
            return None
        properties = {}
        for line in result.stdout.splitlines():
            key, separator, value = line.partition('=')
            if not separator or key in properties:
                return None
            properties[key] = value
        if set(properties) != {'LoadState', 'ActiveState', 'SubState', 'UnitFileState'}:
            return None
        return properties

    def verify_uninstall_stopped(self) -> bool:
        # Check enablement while the unit files still exist, before systemd
        # can report "not found" and obscure a failed disable operation.
        for unit, allowed in (
            ('linux-host-agent-power.socket', ('disabled',)),
            ('linux-host-agent.service', ('disabled',)),
            ('linux-host-agent-power.service', ('static', 'disabled')),
        ):
            state = self._uninstall_unit_state(unit)
            if (state is None or state['LoadState'] != 'loaded' or
                    state['ActiveState'] != 'inactive' or
                    state['UnitFileState'] not in allowed):
                return False
        return True

    def reload_after_uninstall(self) -> None:
        core.systemctl('daemon-reload')

    def verify_uninstall_services(self) -> bool:
        # After reload, all three removed unit files must be absent and
        # their runtime state explicitly inactive, including the helper.
        for unit in ('linux-host-agent-power.socket',
                     'linux-host-agent.service',
                     'linux-host-agent-power.service'):
            state = self._uninstall_unit_state(unit)
            if (state is None or state['LoadState'] != 'not-found' or
                    state['ActiveState'] != 'inactive' or
                    state['UnitFileState'] not in ('', 'not-found')):
                return False
        return True

    def prepare_restore(self, previous: dict) -> None:
        if not previous['first_install']:
            return
        # Load any partially installed files before disabling. Recovery
        # may resume after their removal, so also attempt stop independently.
        # Verify quiescence before removing files; postconditions also check
        # dangling links. Do not require disable/reset success on absent units.
        core.systemctl('daemon-reload')
        core.systemctl('disable', '--now', 'linux-host-agent-power.socket', check=False)
        core.systemctl('stop', 'linux-host-agent-power.socket', check=False)
        core.systemctl('stop', 'linux-host-agent-power.service', check=False)
        core.systemctl('disable', '--now', 'linux-host-agent.service', check=False)
        core.systemctl('stop', 'linux-host-agent.service', check=False)
        for unit in ('linux-host-agent-power.socket', 'linux-host-agent-power.service',
                     'linux-host-agent.service'):
            core.systemctl('reset-failed', unit, check=False)
        for unit, allowed in (
                ('linux-host-agent-power.socket', ('disabled',)),
                ('linux-host-agent.service', ('disabled',)),
                ('linux-host-agent-power.service', ('static', 'disabled'))):
            state = self._uninstall_unit_state(unit)
            if self._stable_unit_state(state, absent=True) is not None:
                continue
            if (state is None or state['LoadState'] != 'loaded' or
                    state['ActiveState'] != 'inactive' or
                    state['UnitFileState'] not in allowed):
                raise ControllerError('recovery_required')

    def restore_services(self, previous: dict) -> None:
        # Clear failed/start-limit state before restarting restored units;
        # clear it again after stopping inactive units. Keep attempting
        # the remaining units after a best-effort operation fails.
        core.systemctl('daemon-reload')
        for unit, prefix in (('linux-host-agent-power.socket', 'socket'),
                             ('linux-host-agent.service', 'agent')):
            if previous[prefix + '_enabled']:
                core.systemctl('enable', unit)
            else:
                core.systemctl('disable', unit, check=False)
            core.systemctl('reset-failed', unit, check=False)
            if previous[prefix + '_active']:
                core.systemctl('restart', unit)
            else:
                core.systemctl('stop', unit, check=False)
                core.systemctl('reset-failed', unit, check=False)
        if previous['first_install']:
            core.systemctl('stop', 'linux-host-agent-power.service', check=False)
            core.systemctl('reset-failed', 'linux-host-agent-power.service', check=False)

    def verify_restored_services(self, previous: dict) -> bool:
        if previous['first_install']:
            return self.verify_uninstall_services()
        return self._services_match(
            (previous['agent_active'], previous['agent_enabled']),
            (previous['socket_active'], previous['socket_enabled']))


def _enablement_absent(transaction: core.InstallTransaction) -> bool:
    """No managed unit name in persistent/runtime dependency directories.

    Check even dangling entries. Never follow or remove an ambiguous
    administrator-created directory or link; retain recovery if uncertain.
    """
    names = {Path(path).name for path in core.SYSTEMD_PATHS}
    # location()/refuse_links() are deliberately file-only. Do not expand
    # the managed-write allowlist merely to inspect a directory. Walk
    # fixed directory components with no-follow directory descriptors.
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC

    def check_tree(components: tuple[str, ...]) -> bool:
        fd = os.open(transaction.root, flags)
        try:
            for component in components:
                try:
                    child_fd = os.open(component, flags, dir_fd=fd)
                except FileNotFoundError:
                    return True
                os.close(fd)
                fd = child_fd
            for name in os.listdir(fd):
                if not name.endswith(('.wants', '.requires', '.upholds')):
                    continue
                child_fd = os.open(name, flags, dir_fd=fd)
                try:
                    if names.intersection(os.listdir(child_fd)):
                        return False
                finally:
                    os.close(child_fd)
            return True
        finally:
            os.close(fd)

    try:
        return all(check_tree(parts) for parts in (
            ('etc', 'systemd', 'system'), ('run', 'systemd', 'system')))
    except OSError:
        return False


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


# Separate record, not a modification of the schema-1 rollback manifest.
# An old helper can still recover its original snapshot. The dot prefix
# keeps receipts out of the legacy snapshot-* selection namespace.
_PROVENANCE_NAME = re.compile(r'snapshot-[A-Za-z0-9_-]{6,64}\Z')
_PROVENANCE_VERSION = re.compile(
    rb"""(?m)^VERSION[ \t]*=[ \t]*['"]([A-Za-z0-9.+_-]{1,64})['"][ \t]*\r?$""")
_PROVENANCE_MAX_ITEM = 2 * 1024 * 1024
_PROVENANCE_MAX_TOTAL = 8 * 1024 * 1024


def _snapshot_provenance(root: Path, backup: Path, journal, previous: dict,
                         *, owner_uid: int) -> None:
    """Record protected before-state capture, not release authenticity.

    Called with the shared installer and journal locks held, after the
    original snapshot was synced and while the journal is STAGED.
    Existing recovery is deliberately independent of this sidecar.
    """
    record = journal._record()
    if (record['phase'] != 'STAGED' or
            record['operation'] not in ('install', 'upgrade', 'repair', 'uninstall') or
            not _PROVENANCE_NAME.fullmatch(backup.name) or
            backup.parent != root / core.BACKUP_BASE.lstrip('/')):
        raise ControllerError('recovery_required')
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY | os.O_CLOEXEC
    read_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC

    def check_directory(fd, private=False):
        info = os.fstat(fd)
        if (info.st_uid != owner_uid or
                stat.S_IMODE(info.st_mode) & (0o077 if private else 0o022)):
            raise ControllerError('recovery_required')

    def stamp(info):
        return (info.st_dev, info.st_ino, info.st_mode, info.st_uid,
                info.st_gid, info.st_nlink, info.st_size, info.st_mtime_ns,
                info.st_ctime_ns)

    def read(directory, name, limit, private=False):
        fd = os.open(name, read_flags, dir_fd=directory)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                    info.st_uid != owner_uid or info.st_size > limit or
                    (private and stat.S_IMODE(info.st_mode) & 0o077)):
                raise ControllerError('recovery_required')
            # copy2 preserves the original installed mode. The containing
            # directory is private and root-controlled, so capture even a
            # damaged mode; historical eligibility applies stricter rules.
            data = stream.read(limit + 1)
            if (len(data) != info.st_size or len(data) > limit or
                    stamp(info) != stamp(os.fstat(stream.fileno()))):
                raise ControllerError('recovery_required')
            return data, stat.S_IMODE(info.st_mode)

    with ExitStack() as stack:
        fd = os.open(root, flags)
        stack.callback(os.close, fd)
        check_directory(fd)
        ancestors = [fd]
        for component in Path(core.BACKUP_BASE.lstrip('/')).parts:
            fd = os.open(component, flags, dir_fd=fd)
            stack.callback(os.close, fd)
            check_directory(fd, component == Path(core.BACKUP_BASE).name)
            ancestors.append(fd)
        base = fd
        directory = os.open(backup.name, flags, dir_fd=base)
        stack.callback(os.close, directory)
        check_directory(directory, True)
        before = stamp(os.fstat(directory))
        raw, _ = read(directory, 'manifest.json',
                      core.MAX_BACKUP_MANIFEST_BYTES, True)

        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ControllerError('recovery_required')
                result[key] = value
            return result

        manifest = json.loads(raw, object_pairs_hook=unique)
        if (type(manifest) is not dict or
                set(manifest) != {'schema', 'installer_protocol', 'items', 'previous'} or
                type(manifest['schema']) is not int or manifest['schema'] != 1 or
                manifest['installer_protocol'] != 'v2' or
                manifest['previous'] != previous or type(manifest['items']) is not list or
                len(manifest['items']) > len(core.MANAGED_PATHS)):
            raise ControllerError('recovery_required')
        seen = set()
        entries = {'manifest.json'}
        digests = {}
        copy_modes = {}
        version = None
        total = 0
        for index, item in enumerate(manifest['items']):
            if (type(item) is not dict or type(item.get('path')) is not str or
                    item['path'] not in core.MANAGED_PATHS or item['path'] in seen or
                    type(item.get('existed')) is not bool):
                raise ControllerError('recovery_required')
            path = item['path']
            seen.add(path)
            if not item['existed']:
                if set(item) != {'path', 'existed'}:
                    raise ControllerError('recovery_required')
                continue
            filename = f'{index}.original'
            if (set(item) != {'path', 'existed', 'file', 'mode', 'uid', 'gid'} or
                    item['file'] != filename or
                    any(type(item[key]) is not int for key in ('mode', 'uid', 'gid'))):
                raise ControllerError('recovery_required')
            data, copy_mode = read(directory, filename, _PROVENANCE_MAX_ITEM)
            copy_modes[path] = copy_mode
            total += len(data)
            if total > _PROVENANCE_MAX_TOTAL:
                raise ControllerError('recovery_required')
            digests[path] = hashlib.sha256(data).hexdigest()
            entries.add(filename)
            if path == core.APP_FILES[0]:
                versions = _PROVENANCE_VERSION.findall(data)
                if (len(versions) == 1 and
                        core.PROTOCOL_MARKER.findall(data) == [b'computer-host-agent']):
                    version = versions[0].decode('ascii')
        if (set(os.listdir(directory)) != entries or
                before != stamp(os.fstat(directory))):
            raise ControllerError('recovery_required')
        receipt = {
            'schema_version': 1,
            'origin': 'protected_before_state',
            'snapshot_name': backup.name,
            'transaction_id': record['transaction_id'],
            'operation': record['operation'],
            'capture_phase': 'STAGED',
            'manifest_sha256': hashlib.sha256(raw).hexdigest(),
            'file_sha256': digests,
            'copy_modes': copy_modes,
            'coverage': 'complete' if seen == core.MANAGED_PATHS else 'partial',
            'captured_paths': sorted(seen),
            'agent_version': version,
            'service_observation': 'protected_capture_previous',
            'previous': previous,
            'release_authenticity': 'not_verified',
        }
        # Receipt is root-private and published without replacement.
        # The snapshot directory remains byte-compatible with old recovery.
        name = '.' + backup.name + '.protected.json'
        temporary = '.snapshot-provenance-' + secrets.token_hex(16)
        out_fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=base)
        try:
            with os.fdopen(out_fd, 'wb') as output:
                os.fchmod(output.fileno(), 0o600)
                output.write((json.dumps(receipt, sort_keys=True) + '\n').encode('ascii'))
                output.flush()
                os.fsync(output.fileno())
            os.link(temporary, name, src_dir_fd=base, dst_dir_fd=base,
                    follow_symlinks=False)
        finally:
            os.unlink(temporary, dir_fd=base)
        published = os.open(name, read_flags, dir_fd=base)
        try:
            info = os.fstat(published)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                    info.st_uid != owner_uid or stat.S_IMODE(info.st_mode) != 0o600):
                raise ControllerError('recovery_required')
            os.fsync(published)
        finally:
            os.close(published)
        for ancestor in reversed(ancestors):
            os.fsync(ancestor)


def _sync_managed_directories(changes: list[core.Change],
                              transaction: core.InstallTransaction) -> None:
    """Sync managed directory entries bottom-up, including mkdir ancestors.

    Reconstruct the fixed directory set on every call, including recovery
    after a crash: an already existing directory may not yet be durable.
    An absent optional subtree is a valid no-op, but its nearest existing
    ancestor still needs syncing. Walk from the trusted root descriptor;
    a symlink or non-directory is an error, not an absent subtree.
    """
    parents = {transaction.location(c.path).parent.relative_to(transaction.root)
               for c in changes}
    if not parents:
        return
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY | os.O_CLOEXEC
    with ExitStack() as stack:
        root_fd = os.open(transaction.root, flags)
        stack.callback(os.close, root_fd)
        opened = {(): root_fd}
        for parent in sorted(parents):
            parts = ()
            for component in parent.parts:
                child = (*parts, component)
                if child not in opened:
                    try:
                        fd = os.open(component, flags, dir_fd=opened[parts])
                    except FileNotFoundError:
                        # Only ENOENT is an acceptable absent subtree.
                        break
                    stack.callback(os.close, fd)
                    opened[child] = fd
                parts = child
        # Every existing directory on an allowlisted path is synced once.
        # In particular sync the root/opt/etc entries after their children.
        for parts in sorted(opened, key=lambda p: (-len(p), p)):
            os.fsync(opened[parts])


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
    """Transactional install/upgrade/repair/uninstall engine; no public root entrypoint."""

    def __init__(self, *, root: Path = Path('/'), owner_uid: int = 0,
                 manual_lock_path: Path = _MANUAL_LOCK,
                 services: ServiceOperations | None = None):
        self.root = Path(root)
        self.owner_uid = owner_uid
        self.manual_lock_path = Path(manual_lock_path)
        self.services = services if services is not None else SystemdOperations()
        self._wol = wol_ownership.Ownership(root=self.root, owner_uid=self.owner_uid)

    def _observe_credentials(self):
        # Live account resolution cannot be provided by the caller. Tests
        # replace this private method on their disposable backend only.
        if self.root != Path('/'):
            raise continuity.ContinuityError()
        return continuity.observe_live()

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
                # The wizard never adopts retained private state. Distinguish
                # an orphan-only layout from v1/partial managed files so the
                # UI can give precise, non-destructive v1.0 refusal guidance.
                try:
                    orphan_only = (core.require_v2_or_clean(
                        self.root, classify_orphan_state=True) == 'orphan_state')
                except (core.InstallError, OSError):
                    orphan_only = False
                raise ControllerError(
                    'adoption_required' if orphan_only else 'unsupported_environment'
                ) from None
            return self._run_locked(request, source, trusted_hashes)

    def wol_action(self, action, interface):
        """Independent explicit WOL inspection/removal under the shared lock."""
        self._check_context()
        if action not in ("wol-check", "wol-remove"):
            raise ControllerError("invalid_request")
        with manual_install_lock(self.manual_lock_path, owner_uid=self.owner_uid):
            if ProtectedJournal(root=self.root, owner_uid=self.owner_uid
                                ).public_status()["privileged_transaction_state"] != "none":
                raise ControllerError("recovery_required")
            try:
                if action == "wol-check":
                    return self._wol.inspect_owned(interface)
                return self._wol.remove_owned(interface)
            except (WolError, OSError):
                raise ControllerError("wol_review_required") from None

    def uninstall(self) -> UninstallOutcome:
        """Journaled v2 uninstall of managed files and services only.

        Called by the authenticated root request router after explicit
        wizard confirmation and administrator authorization.
        Retain the protected UUID/token, owner record, user, WOL NIC policy,
        recovery snapshots, and installed root helper (for -recover).
        """
        self._check_context()
        with manual_install_lock(self.manual_lock_path, owner_uid=self.owner_uid):
            try:
                # A retained v2 owner record after uninstall is NOT proof
                # that an agent remains installed. Refuse absent, v1 and
                # ambiguous states before starting any durable transaction.
                if ProtectedJournal(root=self.root, owner_uid=self.owner_uid
                                    ).public_status()['privileged_transaction_state'] != 'none':
                    raise ControllerError('recovery_required')
                protocol = core.require_v2_or_clean(self.root)
                transaction = core.InstallTransaction(self.root)
                agent = transaction.location(core.APP_FILES[0])
                transaction.refuse_links(agent)
                if not agent.exists():
                    raise ControllerError('not_installed')
                if protocol != 'v2' or not agent.is_file():
                    raise ControllerError('unsupported_environment')
            except core.InstallError:
                raise ControllerError('unsupported_environment') from None
            return self._uninstall_locked(transaction)

    def _uninstall_locked(self, transaction: core.InstallTransaction) -> UninstallOutcome:
        store = ProtectedJournal(root=self.root, owner_uid=self.owner_uid)
        changes = [core.Change(name, None) for name in sorted(core.MANAGED_PATHS)]
        with store.begin('uninstall') as journal:
            credential_check = continuity.Check(journal, self._observe_credentials)
            backup = None
            previous = None
            identity_state = 'not_verified'
            failure_stage = 'existing_state'
            try:
                # No embedded payload is needed: uninstall can only remove
                # the fixed managed-file allowlist. Keep the existing journal
                # phase ordering and recovery format, without staging files.
                journal.advance('INSPECTED', 'STAGED')
                previous = self.services.capture_previous(transaction)
                _check_previous(previous)
                if previous['first_install']:
                    raise ControllerError('unsupported_environment')
                credential_check.capture()
                saved_identity = read_saved_identity(self.root)
                identity_state = 'verified' if saved_identity else 'not_verified'
                failure_stage = 'snapshot'
                backup = transaction.snapshot(changes, previous=previous)
                _sync_snapshot(backup)
                _snapshot_provenance(self.root, backup, journal, previous,
                                     owner_uid=self.owner_uid)
                journal.advance('STAGED', 'SNAPSHOTTED',
                                snapshot_name=backup.name)
                # All changes, including stopping units and creating an
                # ownership marker, require this durable APPLYING entry.
                credential_check.verify(journal)
                journal.advance('SNAPSHOTTED', 'APPLYING')
                core.write_owner_record(self.root)
                self.services.stop_for_uninstall()
                if self.services.verify_uninstall_stopped() is not True:
                    raise ControllerError('recovery_required')
                transaction.apply(changes)
                _sync_managed_directories(changes, transaction)
                journal.advance('APPLYING', 'ACTIVATING')
                self.services.reload_after_uninstall()
                journal.advance('ACTIVATING', 'VERIFYING')
                if (self.services.verify_uninstall_services() is not True or
                        any(transaction.location(c.path).exists()
                            for c in changes) or
                        not _enablement_absent(transaction) or
                        not core.owner_record_exists(self.root) or
                        read_saved_identity(self.root) != saved_identity):
                    raise ControllerError('recovery_required')
                credential_check.verify(journal, allow_new=False)
                journal.advance('VERIFYING', 'COMMITTED')
            except Exception:
                try:
                    phase = journal._record()['phase']
                    if phase == 'COMMITTED':
                        return UninstallOutcome('uninstalled_cleanup_required',
                                                identity_state, credential_check.result)
                    wol_review_required = False
                    if phase in _PREAPPLY:
                        journal.abort(lambda _: True)
                        outcome = 'aborted'
                    elif phase in _APPLIED and backup is not None and previous is not None:
                        wol_review_required = self._restore_snapshot(
                            journal, transaction, backup, credential_check=credential_check)
                        outcome = 'rolled_back'
                    else:
                        raise ControllerError('recovery_required')
                    staging.finish_terminal_stage(
                        journal, root=self.root, owner_uid=self.owner_uid)
                    journal.clear_finished()
                except Exception:
                    raise ControllerError('recovery_required',
                                          credential_result=(credential_check.result if credential_check.failed
                                                             else continuity.Result())) from None
                raise ControllerError(
                    outcome,
                    failure_stage=failure_stage if outcome == 'aborted' else None,
                    wol_review_required=wol_review_required,
                    credential_result=(credential_check.result if credential_check.failed or outcome == 'rolled_back'
                                       else continuity.Result())
                ) from None

            # A committed uninstall is final; only clean its journal.
            # A crash here is resolved by -recover, never by reinstalling.
            try:
                staging.finish_terminal_stage(
                    journal, root=self.root, owner_uid=self.owner_uid)
                journal.clear_finished()
            except Exception:
                return UninstallOutcome('uninstalled_cleanup_required',
                                        identity_state, credential_check.result)
        return UninstallOutcome('uninstalled', identity_state, credential_check.result)

    def _run_locked(self, request: InstallRequest, source: Path,
                    trusted_hashes: Mapping[str, str]) -> InstallOutcome:
        store = ProtectedJournal(root=self.root, owner_uid=self.owner_uid)
        transaction = core.InstallTransaction(self.root)
        with store.begin(request.operation) as journal:
            credential_check = continuity.Check(journal, self._observe_credentials)
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
                credential_check.capture()
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
                if request.wol_plan_digest is not None:
                    intent = self._wol.prepare(request.wol_interface,
                                               request.wol_plan_digest,
                                               journal._record()['transaction_id'])
                    if intent is not None:
                        previous['persistent_wol'] = intent
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
                _snapshot_provenance(self.root, backup, journal, previous,
                                     owner_uid=self.owner_uid)
                journal.advance('STAGED', 'SNAPSHOTTED',
                                snapshot_name=backup.name)
                # NO managed file or service may change before this marker.
                credential_check.verify(journal)
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
                credential_check.verify(journal, allow_new=True)
                # Apply WOL last, with the durable before-state already
                # captured. An exception takes the same rollback path.
                if 'persistent_wol' in previous:
                    self._wol.apply(previous['persistent_wol'],
                                    journal._record()['transaction_id'])
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
                                              'identity_state' in locals() else 'not_verified',
                                              credential_result=credential_check.result)
                    wol_review_required = False
                    if phase in _PREAPPLY:
                        # This controller has not touched managed targets.
                        journal.abort(lambda _: True)
                        outcome = 'aborted'
                    elif phase in _APPLIED and backup is not None and previous is not None:
                        wol_review_required = self._restore_snapshot(
                            journal, transaction, backup, credential_check=credential_check)
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
                    raise ControllerError('recovery_required',
                                          credential_result=(credential_check.result if credential_check.failed
                                                             else continuity.Result())) from None
                raise ControllerError(
                    outcome,
                    failure_stage=failure_stage if outcome == 'aborted' else None,
                    wol_review_required=wol_review_required,
                    credential_result=(credential_check.result if credential_check.failed or outcome == 'rolled_back'
                                       else continuity.Result())
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
                                      identity_state, credential_result=credential_check.result)
        return InstallOutcome('installed', request.operation,
                              identity_state, credential_result=credential_check.result)

    def _restore_snapshot(self, journal, transaction: core.InstallTransaction,
                          backup: Path, *,
                          journal_owned_fresh_install: bool = False,
                          credential_check: continuity.Check | None = None) -> bool:
        """Restore and durably verify the snapshot before marking rollback complete.

        Only explicit recovery of the protected APPLYING+ journal may use
        the first-install exception: the crash can predate the owner record.
        All callers already hold the shared installer and journal locks.
        """
        core.validate_v2_backup(
            backup, root=self.root,
            journal_owned_fresh_install=journal_owned_fresh_install)
        manifest = json.loads(core._read_backup_file(
            backup / 'manifest.json', core.MAX_BACKUP_MANIFEST_BYTES))
        previous = manifest.get('previous')
        _check_previous(previous)
        if journal_owned_fresh_install and previous['first_install']:
            # A journal-bound v2 snapshot lets a first install be retried
            # even if systemd created private state before the crash.
            core.write_owner_record(self.root)

        self.services.prepare_restore(previous)
        if previous['first_install'] and not _enablement_absent(transaction):
            raise ControllerError('recovery_required')
        restored = transaction.restore(backup)
        _check_previous(restored)
        self.services.restore_services(restored)
        # Use the validated snapshot's allowlisted paths, including removals,
        # rather than the forward plan. A sync failure leaves the journal
        # nonterminal so explicit recovery can retry.
        changes = [core.Change(item['path'], None) for item in manifest['items']]
        _sync_managed_directories(changes, transaction)
        verified = (_files_match_snapshot(backup, transaction) and
                    self.services.verify_restored_services(restored) is True and
                    (not restored['first_install'] or
                     _enablement_absent(transaction)))
        wol_review_required = False
        if 'persistent_wol' in previous:
            try:
                self._wol.rollback(previous['persistent_wol'],
                                   journal._record()['transaction_id'])
            except (WolError, OSError):
                # Optional network policy must not strand managed recovery.
                # Preserve unresolved ownership evidence and do not retry
                # destructive WOL compensation automatically. The agent's
                # own file/service/credential verification still gates
                # the terminal record; never report an unverified rollback.
                wol_review_required = True
        if credential_check is not None:
            # Even after a known mismatch, perform the authorized managed
            # restoration above; never report terminal rollback success.
            credential_check.verify(journal, allow_new=True)
        journal.mark_rolled_back(lambda _: verified)
        return wol_review_required

    def _recover_locked(self, journal, transaction: core.InstallTransaction) -> RecoveryOutcome:
        """Resolve a durable nonterminal transaction, never resume an install.

        Recovery restores the PREVIOUS installation rather than trying to
        reconstruct interrupted feature choices. Both locks remain held.
        """
        record = journal._record()
        phase = record['phase']
        operation = record['operation']
        if phase in _PREAPPLY:
            # No managed mutation occurs before the APPLYING record was
            # durably written. Even an interrupted APPLYING journal temp
            # cannot authorize writes that the controller has not begun.
            journal.abort(lambda _snapshot_name: True)
            staging.finish_terminal_stage(journal, root=self.root,
                                          owner_uid=self.owner_uid)
            journal.clear_finished()
            return RecoveryOutcome('aborted', phase, operation)

        if phase not in _APPLIED:
            raise ControllerError('recovery_required')

        snapshot_name = journal._record()['snapshot_name']
        backup_base = self.root / core.BACKUP_BASE.lstrip('/')
        if (not backup_base.is_dir() or backup_base.is_symlink() or
                stat.S_IMODE(backup_base.stat().st_mode) & 0o077 or
                (self.root == Path('/') and backup_base.stat().st_uid != 0)):
            raise ControllerError('recovery_required')
        backup = backup_base / snapshot_name
        wol_review_required = self._restore_snapshot(
            journal, transaction, backup, journal_owned_fresh_install=True)
        staging.finish_terminal_stage(journal, root=self.root,
                                      owner_uid=self.owner_uid)
        journal.clear_finished()
        return RecoveryOutcome('rolled_back', phase, operation,
                               wol_review_required=wol_review_required)

    def recover_interrupted(self) -> RecoveryOutcome:
        """Explicitly recover after power loss, SIGKILL or helper crash.

        No implicit rollback on a new install request. The snapshot is
        independently checked as v2 before any managed file is overwritten.
        """
        self._check_context()
        with manual_install_lock(self.manual_lock_path, owner_uid=self.owner_uid):
            store = ProtectedJournal(root=self.root, owner_uid=self.owner_uid)
            if store.public_status()['privileged_transaction_state'] == 'none':
                # A payload-free COMMITTED uninstall may retain a terminal
                # journal even when public status is none. Explicit recovery
                # must finish that cleanup, not restore or resume deletion.
                try:
                    handle = store.resume_finished_cleanup()
                except JournalConflict:
                    if store.public_status()['privileged_transaction_state'] == 'none':
                        return RecoveryOutcome('nothing_to_recover')
                    raise ControllerError('recovery_required') from None
                with handle as journal:
                    try:
                        operation = journal._record()['operation']
                        staging.finish_terminal_stage(
                            journal, root=self.root, owner_uid=self.owner_uid)
                        journal.clear_finished()
                        return RecoveryOutcome('cleaned', operation=operation)
                    except Exception:
                        raise ControllerError('recovery_required') from None
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
                        operation = journal._record()['operation']
                        staging.finish_terminal_stage(
                            journal, root=self.root, owner_uid=self.owner_uid)
                        journal.clear_finished()
                        return RecoveryOutcome('cleaned', operation=operation)
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
