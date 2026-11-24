"""Development-only historical installed-byte expectation renderer.

The caller supplies an independently authenticated SHA-256 of the exact
release payload manifest and a reviewed compatible agent version. This
module does not acquire attestations or authenticate the publisher.
Never derive that expected digest from the candidate backup or from an
untrusted adjacent manifest. Historical source is data, never executed.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

import install_core as core
import installer_root as boundary
import payload_staging as staging

_RENDERER = 'v2_fixed_plan_1'
_VERSION_LINE = re.compile(rb'''(?m)^VERSION[ \t]*=[ \t]*["']([A-Za-z0-9.+_-]{1,64})["'][ \t]*\r?$''')


class HistoricalExpectationError(ValueError):
    """Fixed diagnostics only."""


@dataclass(frozen=True)
class HistoricalExpectations:
    agent_version: str
    renderer: str
    file_sha256: tuple[tuple[str, str], ...]
    absent_paths: tuple[str, ...]
    release_manifest_sha256: str


def derive_expectations(source: Path, manifest_bytes: bytes, *,
                        expected_manifest_sha256: str,
                        expected_agent_version: str,
                        renderer: str,
                        python_bin: str, power_enabled: bool,
                        wol_interface: str | None,
                        avahi_present: bool) -> HistoricalExpectations:
    """Render a complete fixed layout from independently pinned source bytes.

    The renderer identifier is an explicit compatibility assertion by a
    trusted caller; this code cannot establish compatibility of an arbitrary
    old release. Optional paths are explicit; preserve/customized files are
    not inferred or accepted. No host discovery or managed writes.
    """
    if (type(manifest_bytes) is not bytes or
            not 0 < len(manifest_bytes) <= boundary._MAX_MANIFEST_BYTES or
            type(expected_manifest_sha256) is not str or
            not boundary._SHA256.fullmatch(expected_manifest_sha256) or
            hashlib.sha256(manifest_bytes).hexdigest() != expected_manifest_sha256 or
            type(expected_agent_version) is not str or
            not boundary._VERSION.fullmatch(expected_agent_version) or
            renderer != _RENDERER or
            type(python_bin) is not str or python_bin not in boundary._SYSTEM_PYTHON_COMMANDS or
            type(power_enabled) is not bool or type(avahi_present) is not bool or
            (wol_interface is not None and
             (type(wol_interface) is not str or not boundary._NIC.fullmatch(wol_interface) or
              wol_interface in ('.', '..')))):
        raise HistoricalExpectationError('invalid_historical_expectation')
    try:
        manifest = boundary.validate_manifest(json.loads(
            manifest_bytes.decode('utf-8'), object_pairs_hook=boundary._unique_pairs))
        if manifest['agent_version'] != expected_agent_version:
            raise HistoricalExpectationError('historical_version_mismatch')
        hashes = staging._safe_manifest(manifest['files'])
        fd = staging._open_source_root(Path(source))
        try:
            # Reuse the existing bounded descriptor-relative payload
            # verifier. Freeze every authenticated byte before rendering.
            pinned = {}
            total = 0
            for name in sorted(hashes):
                data = staging._read_verified_file(fd, name, hashes[name])
                total += len(data)
                if total > staging._MAX_TOTAL_BYTES:
                    raise HistoricalExpectationError('historical_payload_too_large')
                pinned[name] = data
        finally:
            os.close(fd)
        agent = pinned['agent/linux_host_agent.py']
        if (_VERSION_LINE.findall(agent) != [expected_agent_version.encode('ascii')] or
                core.PROTOCOL_MARKER.findall(agent) != [b'computer-host-agent']):
            raise HistoricalExpectationError('historical_version_mismatch')
        # Use only the CURRENT reviewed planner, on verified frozen bytes
        # in a private disposable directory. No imports from historical source.
        with tempfile.TemporaryDirectory(prefix='computer-host-expectations-') as tmp:
            private = Path(tmp)
            for name, content in pinned.items():
                target = private / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            plan = core.generate_plan(
                private, python_bin, enable_power=power_enabled,
                disable_power=not power_enabled, wol_interface=wol_interface,
                is_existing_power=False, avahi_dir=avahi_present)
        by_path = {item.path: item.content for item in plan}
        if len(by_path) != len(plan) or not set(by_path).issubset(core.MANAGED_PATHS):
            raise HistoricalExpectationError('unsupported_historical_plan')
        # Only these two optional absent entries may be omitted by planner.
        missing = core.MANAGED_PATHS - set(by_path)
        allowed_missing = set()
        if wol_interface is None:
            allowed_missing.add(core.WOL_DROPIN)
        if not avahi_present:
            allowed_missing.add(core.AVAHI_PATH)
        if missing != allowed_missing:
            raise HistoricalExpectationError('unsupported_historical_plan')
        for name in missing:
            by_path[name] = None
        return HistoricalExpectations(
            expected_agent_version, renderer,
            tuple(sorted((name, hashlib.sha256(data).hexdigest())
                         for name, data in by_path.items() if data is not None)),
            tuple(sorted(name for name, data in by_path.items() if data is None)),
            expected_manifest_sha256)
    except (OSError, UnicodeError, ValueError, RecursionError,
            core.InstallError, staging.StagingError) as exc:
        if isinstance(exc, HistoricalExpectationError):
            raise
        raise HistoricalExpectationError('historical_source_invalid') from None
