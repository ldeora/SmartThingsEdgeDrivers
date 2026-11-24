#!/usr/bin/env python3
"""Regenerate the Go installer's fixed embedded assets from source.

Developer checkout only, never an installer operation. No discovery of
source files, no deletion of unexpected files and no privileged commands.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import sys
import tempfile


# Destination executable bits are intentional; install_core.py is executable
# in the source tree but data-only in the bundle. Go tests independently
# check the union of its helper, preview and payload allowlists.
ASSETS = {
    'agent/linux_host_agent.py': 0o644,
    'agent/power_helper.py': 0o644,
    'agent/systemd/avahi-linux-host-agent.service': 0o644,
    'agent/systemd/enable-power.conf': 0o644,
    'agent/systemd/linux-host-agent-power.service': 0o644,
    'agent/systemd/linux-host-agent-power.socket': 0o644,
    'agent/systemd/linux-host-agent.service': 0o644,
    'scripts/install_core.py': 0o644,
    'scripts/installer-api.sh': 0o755,
    'scripts/installer-entry.sh': 0o644,
    'scripts/installer_api.py': 0o644,
    'scripts/installer_root.py': 0o644,
    'scripts/installer_transaction.py': 0o644,
    'scripts/credential_continuity.py': 0o644,
    'scripts/payload_staging.py': 0o644,
    'scripts/python-selector.sh': 0o755,
    'scripts/runtime_verify.py': 0o644,
    'scripts/transaction_journal.py': 0o644,
}


class BundleError(ValueError):
    pass


def directory(path: Path, *, missing_ok: bool = False) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        if missing_ok:
            return
        raise
    if not stat.S_ISDIR(mode):
        raise BundleError(f'Not a real directory: {path}')


def regular(path: Path, *, missing_ok: bool = False) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        if missing_ok:
            return False
        raise
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise BundleError(f'Not a single-link regular file: {path}')
    return True


def validate_parents(base: Path, relative: Path, *, missing_ok: bool = False) -> None:
    directory(base, missing_ok=missing_ok)
    for part in relative.parts[:-1]:
        base = base / part
        directory(base, missing_ok=missing_ok)


def inspect_bundle(bundle: Path) -> None:
    directory(bundle, missing_ok=True)
    if not bundle.exists():
        return
    expected_dirs = {p.as_posix() for name in ASSETS
                     for p in Path(name).parents if p != Path('.')}
    for path in sorted(bundle.rglob('*')):
        name = path.relative_to(bundle).as_posix()
        if name in expected_dirs:
            directory(path)
        elif name in ASSETS:
            regular(path)
        else:
            raise BundleError(f'Unexpected bundle entry: {name}; inspect manually')


def atomic_write(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.bundle-sync-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def synchronize(source_root: Path, bundle: Path, *, check: bool) -> list[str]:
    """Return changed or missing relative paths; --check never writes."""
    inspect_bundle(bundle)
    changes = []
    # Validate the entire fixed allowlist before the first write. This is
    # developer tooling for a trusted checkout, not concurrent hostile FS
    # protection or an elevated installation boundary.
    for name, mode in sorted(ASSETS.items()):
        relative = Path(name)
        source, dest = source_root / relative, bundle / relative
        validate_parents(source_root, relative)
        regular(source)
        data = source.read_bytes()
        validate_parents(bundle, relative, missing_ok=True)
        exists = regular(dest, missing_ok=True)
        # Only executable bits are tracked by Git. Do not create mode-only
        # churn from the developer's ordinary checkout umask.
        if (not exists or dest.read_bytes() != data or
                bool(dest.stat().st_mode & 0o111) != bool(mode & 0o111)):
            changes.append((name, data, mode))
    if not check:
        for name, data, mode in changes:
            atomic_write(bundle / name, data, mode)
    return [name for name, _, _ in changes]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true',
                        help='Report drift without changing any files')
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    try:
        changed = synchronize(here.parent, here / 'bundle', check=args.check)
    except (OSError, BundleError) as exc:
        print(f'Bundle synchronization refused: {exc}', file=sys.stderr)
        return 1
    if changed:
        for name in changed:
            print(('Out of date: ' if args.check else 'Updated: ') + name)
        if args.check:
            print('Run python3 sync_bundle.py from linux-installer and commit the bundle.')
            return 1
    else:
        print('Embedded bundle is up to date.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
