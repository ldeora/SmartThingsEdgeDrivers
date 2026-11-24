#!/usr/bin/env python3
"""Conservative read-only WOL planning, NOT an authorization or write contract.

Only the narrow .link subset below is understood. Unknown matching rules,
drop-ins, unsafe paths and ambiguous state always require manual review.
Even a review candidate cannot be applied by this module.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
import types
from typing import Callable


def _load_inspector():
    """Import the sibling module in isolated mode from a trusted checkout.

    A development script is not a privileged installed helper. In
    particular, refuse to import from a user-owned checkout as root.
    Future integration must use the installed helper's fixed trust boundary.
    """
    directory = Path(__file__).absolute().parent
    uid = os.geteuid()
    if uid == 0 and not (sys.flags.isolated and sys.flags.no_site
                         and sys.dont_write_bytecode):
        raise RuntimeError('root inspection requires Python -I -S -B')
    # A normal developer may use a checkout they own, under root-owned
    # parents. Root requires every component to be root-owned.
    for parent in (*reversed(directory.parents), directory):
        info = parent.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, uid)
                or info.st_mode & 0o022):
            raise RuntimeError('unsafe inspector import directory')
    for name in ('wol_plan.py', 'wol_inspect.py'):
        info = (directory / name).lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid not in (0, uid)
                or info.st_mode & 0o022):
            raise RuntimeError('unsafe inspector source')
    # Load source from the checked sibling directly, not a writable
    # __pycache__ or another module on sys.path. No import search is added.
    source = directory / 'wol_inspect.py'
    fd = os.open(source, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid not in (0, uid)
                or info.st_mode & 0o022 or info.st_size > 262144):
            raise RuntimeError('unsafe inspector source')
        data = stream.read(262145)
    if len(data) > 262144:
        raise RuntimeError('oversized inspector source')
    module = types.ModuleType('wol_inspect')
    module.__file__ = str(source)
    exec(compile(data, str(source), 'exec'), module.__dict__)
    return module


# Normal module imports are used by fixture tests and the future installed
# helper, which owns its import boundary. Standalone isolated execution
# needs the explicit, checked sibling import.
if __name__ == '__main__':
    probe = _load_inspector()
else:
    import wol_inspect as probe

# Highest priority first for equal basenames. /lib is accepted only as
# an alias of /usr/lib, or when /usr/lib/systemd/network does not exist.
_DIRS = ('/etc/systemd/network', '/run/systemd/network',
         '/usr/local/lib/systemd/network', '/usr/lib/systemd/network',
         '/lib/systemd/network')
_MAX_ENTRIES = 4096
_MAX_BYTES = 65536


class UncertainPolicy(Exception):
    """An observation cannot justify a more specific recommendation."""


def rooted(root: Path, absolute: str) -> Path:
    return root / absolute.lstrip('/')


def protected_directory(root: Path, absolute: str, owner_uid: int) -> Path | None:
    """Do not traverse unexpected symlinks or writable directory parents."""
    current = root
    for part in Path(absolute).parts[1:]:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            return None
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != owner_uid or
                info.st_mode & 0o022):
            raise UncertainPolicy()
    return current


def policy_directories(root: Path, owner_uid: int) -> list[tuple[str, Path]]:
    result = []
    for absolute in _DIRS[:-1]:
        path = protected_directory(root, absolute, owner_uid)
        if path is not None:
            result.append((absolute, path))
    # Merged-/usr systems commonly have /lib -> usr/lib. Accept only
    # that known alias, never follow an arbitrary path. On split-/usr
    # systems treat simultaneous distinct vendor network dirs as unknown.
    legacy = rooted(root, '/lib')
    try:
        info = legacy.lstat()
    except FileNotFoundError:
        return result
    if stat.S_ISLNK(info.st_mode):
        if info.st_uid != owner_uid or os.readlink(legacy) not in ('usr/lib', '/usr/lib'):
            raise UncertainPolicy()
        return result
    path = protected_directory(root, _DIRS[-1], owner_uid)
    if path is not None:
        if any(name == _DIRS[-2] for name, _ in result):
            raise UncertainPolicy()
        result.append((_DIRS[-1], path))
    return result


def inventory(root: Path, owner_uid: int) -> tuple[dict[str, Path], dict[str, tuple[Path, ...]]]:
    """Select same-name winners; collect potentially relevant drop-in dirs.

    Masks count as winners and are handled separately. Keep every
    occurrence of a drop-in name, not just its precedence winner.
    No attempt is made to evaluate drop-in syntax or merge semantics.
    """
    winners = {}
    dropins = {}
    count = 0
    for _, directory in policy_directories(root, owner_uid):
        with os.scandir(directory) as entries:
            for entry in entries:
                count += 1
                if count > _MAX_ENTRIES:
                    raise UncertainPolicy()
                if entry.name.endswith('.link'):
                    winners.setdefault(entry.name, Path(entry.path))
                elif entry.name.endswith('.link.d') or entry.name == 'link.d':
                    dropins.setdefault(entry.name, []).append(Path(entry.path))
    return winners, {name: tuple(paths) for name, paths in dropins.items()}


def read_rule(path: Path, owner_uid: int) -> str | None:
    """Return None for a recognized mask, text for a protected base rule."""
    info = path.lstat()
    if info.st_uid != owner_uid:
        raise UncertainPolicy()
    if stat.S_ISLNK(info.st_mode):
        if os.readlink(path) == '/dev/null':
            return None
        raise UncertainPolicy()
    if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or
            info.st_size > _MAX_BYTES):
        raise UncertainPolicy()
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        after = os.fstat(stream.fileno())
        if (not stat.S_ISREG(after.st_mode) or after.st_uid != owner_uid or
                after.st_mode & 0o022 or
                (after.st_dev, after.st_ino) != (info.st_dev, info.st_ino)):
            raise UncertainPolicy()
        raw = stream.read(_MAX_BYTES + 1)
    if len(raw) > _MAX_BYTES:
        raise UncertainPolicy()
    if not raw:
        return None
    return raw.decode('utf-8')


def exact_match(text: str) -> tuple[str, str] | None:
    """Understand only one literal MAC/PermanentMAC match, no other keys.

    We do not emulate systemd's matching engine. In particular, no
    negations, lists, resets, continuation lines, quoting or conditions.
    """
    section = ''
    sections = 0
    matches = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(('#', ';')):
            continue
        if line.endswith('\\') or '\x00' in line:
            return None
        if line.startswith('['):
            if not line.endswith(']'):
                return None
            section = line[1:-1]
            if section == 'Match':
                sections += 1
        elif section == 'Match':
            key, sep, value = line.partition('=')
            value = value.strip().lower()
            if (not sep or key.strip() not in ('MACAddress', 'PermanentMACAddress')
                    or not probe.valid_mac(value)):
                return None
            matches.append((key.strip(), value))
        elif not section:
            return None
    if sections != 1 or len(matches) != 1:
        return None
    return matches[0]


def has_secureon(text: str) -> bool:
    # Deliberately over-detect: a password assignment (even empty) or
    # the secureon token anywhere in a non-comment line is a review gate.
    for line in text.splitlines():
        line = line.strip().lower()
        if line.startswith(('#', ';')):
            continue
        if 'wakeonlanpassword' in line or 'secureon' in line:
            return True
    return False


def empty_local_dropin(root: Path, observed: Path, owner_uid: int,
                       dropins: dict[str, tuple[Path, ...]]) -> tuple[int, int, int, int] | None:
    """Only an exact local selected-rule directory may qualify.

    Every entry, including a hidden file, mask or subdirectory, is a
    conflict. Walk all fixed components with directory descriptors.
    Return mount-local identity and timestamps for advisory resampling.
    No arbitrary directory is traversed and no contents are read.
    """
    if observed.parent != Path('/etc/systemd/network'):
        return None
    relevant = {name: paths for name, paths in dropins.items()
                if name == 'link.d' or name.removesuffix('.d') <= observed.name}
    name = observed.name + '.d'
    expected = rooted(root, str(observed) + '.d')
    if relevant != {name: (expected,)}:
        return None
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(root, flags)
    try:
        for component in ('etc', 'systemd', 'network', name):
            info = os.fstat(fd)
            if info.st_uid != owner_uid or info.st_mode & 0o022:
                return None
            child = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        before = os.fstat(fd)
        if before.st_uid != owner_uid or before.st_mode & 0o022:
            return None
        with os.scandir(fd) as entries:
            if next(entries, None) is not None:
                return None
        after = os.fstat(fd)
        def identity(st):
            return st.st_dev, st.st_ino, st.st_mtime_ns, st.st_ctime_ns
        if identity(before) != identity(after):
            return None
        visible = expected.lstat()
        if not stat.S_ISDIR(visible.st_mode) or identity(visible) != identity(after):
            return None
        return identity(after)
    finally:
        os.close(fd)


def inspect_link_tree(root: Path, observed: Path, mac: str,
                      owner_uid: int, *,
                      listing: tuple[dict[str, Path], dict[str, tuple[Path, ...]]] | None = None
                      ) -> tuple[str, str, str]:
    """Return fixed (tree evidence, scope, base policy) classifications.

    For an earlier rule, only a literal *permanent* MAC mismatch is
    sufficient to exclude it for future boots. Current-MAC matches can
    change during device initialization. No earlier rule is shadowed.
    """
    unknown = ('not_verified', 'not_verified', 'not_verified')
    try:
        winners, dropins = listing if listing is not None else inventory(root, owner_uid)
        selected = winners.get(observed.name)
        observed_path = str(observed)
        if observed_path.startswith('/lib/') and selected is not None:
            # The only allowed legacy alias has already been checked.
            if rooted(root, '/lib').is_symlink():
                observed_path = '/usr' + observed_path
        if selected is None or selected != rooted(root, observed_path):
            return 'selection_changed', 'not_verified', 'not_verified'
        relevant_dropins = ('link.d' in dropins or any(
            name.removesuffix('.d') <= observed.name for name in dropins))
        if relevant_dropins and empty_local_dropin(root, observed, owner_uid, dropins) is None:
            return 'dropins_require_review', 'not_verified', 'not_verified'
        for name, path in sorted(winners.items()):
            if name >= observed.name:
                break
            text = read_rule(path, owner_uid)
            if text is None:
                continue
            match = exact_match(text)
            if match is None or match[0] != 'PermanentMACAddress' or match[1] == mac:
                return 'earlier_rule_requires_review', 'not_verified', 'not_verified'
        text = read_rule(selected, owner_uid)
        if text is None:
            return 'selection_changed', 'not_verified', 'not_verified'
        match = exact_match(text)
        if match is not None and match[1] != mac:
            return 'selection_changed', 'not_verified', 'not_verified'
        scope = ('permanent_mac' if match and match[0] == 'PermanentMACAddress'
                 else 'current_mac' if match else 'shared_or_complex')
        policy = probe.base_link_policy(text)
        if has_secureon(text):
            policy = 'secureon_requires_review'
        if relevant_dropins:
            if scope != 'permanent_mac' or policy != 'unspecified':
                return 'dropins_require_review', 'not_verified', 'not_verified'
            return 'empty_local_dropin_observed', scope, policy
        return 'base_rule_observed', scope, policy
    except (OSError, UnicodeError, ValueError, UncertainPolicy):
        return unknown


def recommendation(evidence: dict, tree: str, scope: str,
                   policy: str, secureon_runtime: bool) -> tuple[str, str]:
    """No recommendation here is a writable plan or grant of permission."""
    if evidence['interface_state'] != 'ethernet':
        return 'unavailable', 'interface_not_verified'
    if evidence['magic_packet_support'] == 'unsupported':
        return 'unavailable', 'magic_packet_unsupported'
    if evidence['magic_packet_support'] != 'supported':
        return 'verify_hardware', 'hardware_not_verified'
    if secureon_runtime or policy == 'secureon_requires_review':
        return 'manual_review', 'secureon_requires_review'
    if evidence['permanent_mac_match'] != 'matches':
        return 'manual_review', 'interface_identity_not_verified'
    backend = evidence['backend']
    if backend == 'networkmanager':
        nm = evidence['nm_profile_policy']
        if nm in ('magic', 'magic_with_other_flags'):
            if evidence['runtime_magic_packet'] != 'enabled':
                return 'review_runtime', 'nm_magic_declared_runtime_differs'
            return 'preserve', 'nm_magic_declared'
        if nm in ('none', 'other_flags'):
            # Only a review candidate. Before any future mutation, verify
            # exact old flags, profile persistence, NIC binding, credential
            # status and administrator consent; no UUID/flags are emitted.
            reason = ('explicit_nm_wol_disabled' if nm == 'none'
                      else 'explicit_nm_flags_without_magic')
            return 'review_nm_add_magic', reason
        return 'manual_review', 'nm_policy_not_explicit'
    if backend != 'systemd_udev':
        return 'manual_review', 'network_backend_not_verified'
    if tree not in ('base_rule_observed', 'empty_local_dropin_observed'):
        return 'manual_review', 'link_precedence_not_verified'
    if evidence['observed_link'] not in ('local', 'vendor'):
        return 'manual_review', 'link_not_stable_persistent_location'
    if policy != evidence['base_link_policy']:
        return 'manual_review', 'link_observation_changed'
    if policy == 'magic_declared':
        if evidence['runtime_magic_packet'] != 'enabled':
            return 'review_runtime', 'link_magic_declared_runtime_differs'
        return 'preserve', 'link_magic_declared'
    if (policy == 'unspecified' and scope == 'permanent_mac' and
            evidence['observed_link'] == 'local'):
        # Existing exact permanent-MAC local rule only. Never create a
        # competing .link, override a shared rule or replace explicit WOL.
        if tree == 'empty_local_dropin_observed':
            return 'review_link_dropin', 'protected_empty_local_dropin'
        return 'review_link_dropin', 'scoped_local_rule_without_wol'
    return 'manual_review', 'link_policy_requires_review'


def plan(interface: str, *, root: Path = Path('/'),
         net: Path = Path('/sys/class/net'), owner_uid: int = 0,
         run: probe.Runner = probe.query,
         link_reader: Callable[[Path], str | None] | None = None) -> dict:
    # Record only the selected udev observation and whether runtime
    # SecureOn was seen. Raw command output is never part of the reply.
    observed = None
    secureon_runtime = False

    def record(args: tuple[str, ...]) -> str | None:
        nonlocal observed, secureon_runtime
        output = run(args)
        if args[0] == 'udevadm':
            observed = probe.selected_link(output)
        if args[0] == 'ethtool' and probe.parse_ethtool(output) is not None:
            secureon_runtime = any(
                line.strip().startswith('Wake-on:') and
                's' in line.split(':', 1)[1].strip()
                for line in output.splitlines())
        return output

    # Validate before reading sysfs, even when a fixture injects a runner.
    valid = (isinstance(interface, str) and probe._IFACE.fullmatch(interface)
             and interface not in ('.', '..') and not interface.startswith('-'))
    before = probe.read_identity(net, interface) if valid else None
    listing = None
    inventory_failed = False

    def protected_link_reader(path: Path) -> str | None:
        # Reuse one directory inventory for the subsequent precedence
        # check. File contents are read again, not assumed immutable.
        nonlocal listing, inventory_failed
        try:
            listing = inventory(root, owner_uid)
            winners, _ = listing
            actual = winners.get(path.name)
            absolute = str(path)
            if absolute.startswith('/lib/') and rooted(root, '/lib').is_symlink():
                absolute = '/usr' + absolute
            if actual is None or actual != rooted(root, absolute):
                return None
            return read_rule(actual, owner_uid)
        except (OSError, UnicodeError, ValueError, UncertainPolicy):
            if listing is None:
                inventory_failed = True
            return None

    evidence = probe.inspect(interface, net=net, run=record,
                             link_reader=link_reader or protected_link_reader)
    tree = scope = policy = 'not_verified'
    empty_identity = None
    if (evidence['backend'] == 'systemd_udev' and observed is not None
            and observed[1] is not None and before is not None):
        if observed[2] == 'present':
            tree = 'dropins_require_review'
        elif evidence['permanent_mac_match'] == 'matches' and not inventory_failed:
            # Capture the candidate directory before the tree check. The
            # second sample after udev/inventory must match, including
            # timestamps, so a replaced or populated directory is refused.
            if listing is not None:
                try:
                    empty_identity = empty_local_dropin(root, observed[1], owner_uid, listing[1])
                except (OSError, ValueError):
                    empty_identity = None
            tree, scope, policy = inspect_link_tree(
                root, observed[1], before[1], owner_uid, listing=listing)
            # The shared inventory is not an atomic snapshot. Recheck its
            # names and winning paths to catch changes during inspection.
            if listing is not None:
                try:
                    if inventory(root, owner_uid) != listing:
                        tree, scope, policy = 'selection_changed', 'not_verified', 'not_verified'
                except (OSError, UnicodeError, ValueError, UncertainPolicy):
                    tree = scope = policy = 'not_verified'
        again = probe.selected_link(run(
            ('udevadm', 'info', '--query=property', '--path=/sys/class/net/' + interface)))
        if again != observed:
            tree, scope, policy = 'selection_changed', 'not_verified', 'not_verified'
        if tree == 'empty_local_dropin_observed':
            try:
                final_listing = inventory(root, owner_uid)
                final_identity = empty_local_dropin(root, observed[1], owner_uid, final_listing[1])
                if (listing is None or final_listing != listing or
                        empty_identity is None or final_identity != empty_identity):
                    tree, scope, policy = 'selection_changed', 'not_verified', 'not_verified'
            except (OSError, ValueError, UncertainPolicy):
                tree = scope = policy = 'not_verified'
    if valid and probe.read_identity(net, interface) != before:
        # Do not retain observations from a different interface.
        evidence = probe.inspect('', net=net)
        evidence['interface_state'] = 'interface_changed'
        tree = scope = policy = 'not_verified'
        secureon_runtime = False
    action, reason = recommendation(evidence, tree, scope, policy, secureon_runtime)
    return dict(schema_version=1, operation='wol_plan', mode='read_only',
                inspection=evidence, link_tree=tree, link_scope=scope,
                link_policy_evidence=policy, recommendation=action, reason=reason,
                automatic_changes_allowed=False, changes_applied=False,
                persistence_verified=False, secrets_included=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Read-only WOL policy review (no configuration changes)')
    parser.add_argument('--interface', required=True)
    args = parser.parse_args(argv)
    print(json.dumps(plan(args.interface), sort_keys=True, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
