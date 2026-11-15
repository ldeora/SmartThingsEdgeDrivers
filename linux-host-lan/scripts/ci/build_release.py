#!/usr/bin/env python3
"""Build reproducible, versioned GitHub source and volunteer-agent artifacts.

Run from the project source tree; no network and no privileged operations.
All paths are allowlisted for the standalone agent package. Neither local
identity nor control key files are included. Requires only Python >=3.10.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
META = json.loads((ROOT / "release.json").read_text(encoding="utf8"))
VERSION = META["integration"]
SOURCE_NAME = f"linux-host-lan-github-ready-v{VERSION}"
BUNDLE_NAME = f"linux-host-agent-bundle-v{VERSION}"
ZIP_DATE = (2026, 11, 15, 12, 0, 0)
EPOCH = 1_700_000_000
OMIT_DIRS = {".git", "__pycache__", ".pytest_cache", ".venv", "venv", "build", "dist", "release-assets"}
OMIT_SUFFIXES = {".pyc", ".pyo", ".pem", ".key"}
OMIT_NAMES = {"FILES.sha256", ".DS_Store", "control-token", "installation-id", ".env"}

AGENT_SCRIPTS = {
    "install-agent.sh", "install_core.py", "python-selector.sh",
    "preflight.sh", "configure-wol.sh", "diagnose.sh",
    "rollback-agent.sh", "uninstall-agent.sh", "beta-report.sh",
}
AGENT_DOCS = {
    "README.md", "LICENSE", "INSTALLATION.md", "SECURITY.md", "release.json", "BETA-STATUS.md",
    "docs/beta/START-HERE.md", "docs/beta/TESTER-CHECKLIST.md",
    "docs/beta/FEEDBACK-AND-SUPPORT.md", "docs/beta/COMPATIBILITY-STATUS.md",
    "docs/beta/SECURITY-AND-PRIVACY.md", "docs/development/SECURITY-HARDENING.md",
}


def collect_source() -> dict[str, tuple[bytes, int]]:
    result: dict[str, tuple[bytes, int]] = {}
    for path in sorted(ROOT.rglob("*")):
        rel = path.relative_to(ROOT)
        if any(part in OMIT_DIRS for part in rel.parts):
            continue
        if path.is_symlink():
            raise RuntimeError(f"Refusing symlink in release: {rel}")
        if not path.is_file() or path.name in OMIT_NAMES or path.suffix in OMIT_SUFFIXES:
            continue
        if path.stat().st_size > 2_000_000:
            raise RuntimeError(f"Unexpected large source file: {rel}")
        mode = 0o755 if (path.stat().st_mode & stat.S_IXUSR) else 0o644
        result[rel.as_posix()] = (path.read_bytes(), mode)
    return result


def choose_agent(src: dict[str, tuple[bytes, int]]) -> dict[str, tuple[bytes, int]]:
    chosen = {
        name: data for name, data in src.items()
        if (name.startswith("agent/") or
            name in AGENT_DOCS or
            (name.startswith("scripts/") and name.split("/")[-1] in AGENT_SCRIPTS))
    }
    if not AGENT_DOCS.issubset(chosen) or not all(f"scripts/{s}" in chosen for s in AGENT_SCRIPTS):
        raise RuntimeError("Incomplete agent package (required docs/script missing)")
    if "agent/linux_host_agent.py" not in chosen or "agent/power_helper.py" not in chosen:
        raise RuntimeError("Incomplete agent package (runtime missing)")
    # Volunteers receive a self-contained README, not the source-repository
    # README (which links to developer-only folders excluded from this bundle).
    standalone_readme = f"""# Linux Host Agent Bundle v{VERSION} — Closed beta

Linux Host Agent **{META['agent']}** for SmartThings Linux Host LAN.
The companion SmartThings Edge Driver **{META['edge_driver']}** is installed
on your hub through the publisher's separate beta channel.

**Important:** This is an early technical beta tested on Gentoo hardware.
Other distributions, SELinux/AppArmor and wake hardware are not certified.
Run monitoring-only installation first and keep physical access to the PC.
Never expose agent TCP 8765 to the public Internet.

## Quick start (from this extracted bundle)

```sh
./scripts/preflight.sh
./scripts/install-agent.sh --dry-run
sudo ./scripts/install-agent.sh
systemctl status linux-host-agent.service
./scripts/beta-report.sh
```

Agent installer uses systemd and Python 3.10+, with no third-party runtime
Python modules. For mDNS discovery, run Avahi and permit multicast UDP 5353
between hub and Linux host. Restrict TCP 8765 to your trusted LAN/hub.
The installer does not change the firewall or WOL unless explicitly opted in.
Power actions require a separate opt-in and safe recovery plan.

For complete instructions, read [INSTALLATION.md](INSTALLATION.md) and
[tester guide](docs/beta/START-HERE.md). Read [SECURITY.md](SECURITY.md)
before enabling power operations; never share the authentication token.

**License:** Apache License, Version 2.0 (`LICENSE` included in this bundle).
Code provenance, beta-channel checks and distribution validation remain pending
before a wider public release.
"""
    chosen['README.md'] = (standalone_readme.encode('utf8'), 0o644)
    return chosen


def with_manifest(items: dict[str, tuple[bytes, int]]) -> dict[str, tuple[bytes, int]]:
    assert "FILES.sha256" not in items
    manifest = "".join(
        f"{hashlib.sha256(content).hexdigest()}  {name}\n"
        for name, (content, _) in sorted(items.items())
    ).encode("utf8")
    return {**items, "FILES.sha256": (manifest, 0o644)}


def write_zip(output: Path, dirname: str, items: dict[str, tuple[bytes, int]]) -> None:
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel, (data, mode) in sorted(items.items()):
            info = zipfile.ZipInfo(f"{dirname}/{rel}", date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | mode) << 16
            z.writestr(info, data)
    with zipfile.ZipFile(output) as z:
        if z.testzip() is not None:
            raise RuntimeError(f"Archive integrity failed: {output}")


def write_tar_gz(output: Path, dirname: str, items: dict[str, tuple[bytes, int]]) -> None:
    with output.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0, compresslevel=9) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as tar:
                for rel, (data, mode) in sorted(items.items()):
                    info = tarfile.TarInfo(f"{dirname}/{rel}")
                    info.size = len(data)
                    info.mtime = EPOCH
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mode = mode
                    tar.addfile(info, io.BytesIO(data))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    src = collect_source()
    agent = with_manifest(choose_agent(src))
    repo = with_manifest(src)
    artifacts = [
        (output / f"{SOURCE_NAME}.zip", lambda p: write_zip(p, "linux-host-lan", repo)),
        (output / f"{BUNDLE_NAME}.zip", lambda p: write_zip(p, BUNDLE_NAME, agent)),
        (output / f"{BUNDLE_NAME}.tar.gz", lambda p: write_tar_gz(p, BUNDLE_NAME, agent)),
    ]
    for path, builder in artifacts:
        builder(path)
        print(f"{path.name}: {path.stat().st_size} bytes")
    (output / "SHA256SUMS.txt").write_text("".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
        for path, _ in artifacts
    ), encoding="utf8")
    print(f"{len(repo)} repository files; {len(agent)} standalone-agent files")


if __name__ == "__main__":
    main()
