#!/usr/bin/env python3
"""Build a checksummed, deterministic Windows tester ZIP from CI-published binaries.

This is a packaging step, not code signing or proof of Windows hardware behavior.
Do not bundle a developer's state directory, identities, keys or local data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
import stat
import zipfile

ROOT = Path(__file__).resolve().parents[2]
STAMP = (2026, 11, 16, 12, 0, 0)
HELPERS = ("Install-WindowsAgent.ps1", "Uninstall-WindowsAgent.ps1",
           "Get-WolDiagnostics.ps1", "Collect-WindowsDiagnostics.ps1",
           "Verify-Package.ps1", "Restore-WindowsAgentUpgrade.ps1",
    "Check-WindowsAgentHealth.ps1", "Set-WindowsHubAddress.ps1")
DOCUMENTS = {
    "docs/START-HERE.md": ROOT / "docs/beta/START-HERE.md",
    "docs/TEST-CHECKLIST.md": ROOT / "docs/beta/TESTER-CHECKLIST.md",
    "docs/FEEDBACK-AND-SUPPORT.md": ROOT / "docs/beta/FEEDBACK-AND-SUPPORT.md",
    "docs/SECURITY-AND-PRIVACY.md": ROOT / "docs/beta/SECURITY-AND-PRIVACY.md",
    "docs/THIRD-PARTY-NOTICES.md": ROOT / "docs/beta/THIRD-PARTY-NOTICES.md",
    "docs/HARDWARE-TEST-MATRIX.md": ROOT / "windows-agent/docs/HARDWARE-TEST-MATRIX.md",
}
DISALLOWED_PARTS = {"control-token", "installation-id", "boot-session.json", "appsettings.Development.json"}


def add_source(entries: dict[str, bytes], target: str, source: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"Missing or symlinked release input: {source}")
    if target in entries:
        raise ValueError(f"Duplicate archive member: {target}")
    entries[target] = source.read_bytes()


def release_kind(version: str) -> str:
    """Return the package stage; fail rather than publish an unknown version."""
    if re.fullmatch(r"\d+\.\d+\.\d+-beta\.\d+", version):
        return "beta"
    if re.fullmatch(r"\d+\.\d+\.\d+-rc\.\d+", version):
        return "rc"
    if re.fullmatch(r"\d+\.\d+\.\d+", version):
        return "stable"
    raise ValueError(f"Unsupported integration version: {version}")


def build(published: Path, output_dir: Path, runtime: str, commit: str) -> Path:
    release = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
    version = release["integration"]
    agent_version = release["windows_agent"]
    stage = release_kind(version)
    if release.get("release_stage") not in (
        f"{stage}-candidate-v{version}", f"{stage}-published-v{version}"
    ):
        raise ValueError("release_stage is incompatible with integration version")
    notes_directory = "beta" if stage == "beta" else "release"
    release_label = {"beta": "beta", "rc": "release candidate", "stable": "stable release"}[stage]
    if runtime not in ("win-x64", "win-arm64"):
        raise ValueError("Only win-x64 / win-arm64 builds are supported")
    if len(commit) != 40 or not all(c in "0123456789abcdef" for c in commit.lower()):
        raise ValueError("A full immutable 40-character Git commit SHA is required")
    if not (published / "ComputerHost.WindowsAgent.exe").is_file():
        raise ValueError("Published Windows executable missing")
    if not (published / "appsettings.json").is_file():
        raise ValueError("Published appsettings.json missing")
    entries: dict[str, bytes] = {}
    for src in sorted(published.rglob("*")):
        if src.is_symlink():
            raise ValueError(f"Symlinks forbidden in publication: {src}")
        if not src.is_file():
            continue
        if any(part.lower() in DISALLOWED_PARTS for part in src.relative_to(published).parts):
            raise ValueError(f"Refusing potential secret/state file: {src}")
        add_source(entries, f"publish/{runtime}/{src.relative_to(published).as_posix()}", src)

    for helper in HELPERS:
        add_source(entries, f"scripts/{helper}", ROOT / "windows-agent/scripts" / helper)
    for dst, src in DOCUMENTS.items():
        if stage != "beta":
            if dst == "docs/START-HERE.md":
                src = ROOT / ("docs/release/WINDOWS-QUICK-START.md" if "linux_installer" in release
                              else "docs/release/QUICK-START.md")
            elif dst == "docs/TEST-CHECKLIST.md":
                src = ROOT / ("docs/release/RC3-READINESS.md" if "linux_installer" in release
                              else "docs/release/RC-ACCEPTANCE.md")
        add_source(entries, dst, src)
    add_source(entries, "docs/RELEASE-NOTES.md", ROOT / "docs" / notes_directory / f"RELEASE-NOTES-v{version}.md")
    add_source(entries, "LICENSE", ROOT / "LICENSE")
    entries["README.md"] = (f"""# Computer Host LAN — Windows package

Integration {version} · Windows agent {agent_version} · {runtime}
Source commit: {commit}

**Unsigned PowerShell installation fallback. For a new Windows x64 installation prefer the graphical Setup.exe distributed alongside this ZIP. Verify downloads against SHA256SUMS.txt.**
This is a Computer Host LAN {release_label} package. CI verifies installation and
upgrade behavior, but cannot prove compatibility with every Windows computer or
SmartThings hub. Keep a known-good installer for rollback.
Physical recovery remains essential for optional power testing.
Use only on a trusted PRIVATE LAN; never forward TCP 8765 to the Internet.

## Start with monitoring only

1. Check the external release SHA-256 for this ZIP, then extract it.
2. From the extracted directory run in Windows PowerShell:
   .\\scripts\\Verify-Package.ps1
3. Open PowerShell as Administrator. Preview, then install:
   .\\scripts\\Install-WindowsAgent.ps1 -WhatIf -HubIPv4 YOUR_HUB_IPV4
   .\\scripts\\Install-WindowsAgent.ps1 -HubIPv4 YOUR_HUB_IPV4
   Get-Service ComputerHostAgent
   Invoke-RestMethod http://127.0.0.1:8765/v2/info
   Fresh installations require -HubIPv4 or explicit -LocalSubnet (Private only).
   Upgrades keep a validated existing scope and power preference unless explicitly changed.
4. Open the verified SmartThings Edge channel invitation:
   https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20
   Sign in, accept, enroll your hub and install Computer Host LAN under Available
   Drivers. Then use Scan nearby in the SmartThings app.
   Full instructions: docs/START-HERE.md.

## Optional power (after monitoring is working)

   .\\scripts\\Install-WindowsAgent.ps1 -EnablePower -HubIPv4 YOUR_HUB_IPV4

Keep the control-token PRIVATE; set it in the SmartThings device preferences
alongside allowPowerCommands=true. Reboot first, then suspend/WOL, then
shutdown/WOL only with physical access and saved work. Windows power behavior
varies across hardware and power states. Uninstall via
.\\scripts\\Uninstall-WindowsAgent.ps1 (retains state by default).

Release notes: docs/RELEASE-NOTES.md. For feedback use docs/TEST-CHECKLIST.md and the sanitized
.\\scripts\\Collect-WindowsDiagnostics.ps1; manually review reports before sharing.
No .NET SDK is required for the self-contained executable.

This archive is checksummed, not signed. Source and support:
https://github.com/ldeora/SmartThingsEdgeDrivers/tree/main/computer-host-lan
""").encode("utf-8")
    entries["BUILD-INFO.json"] = (json.dumps({
        "integration": version,
        "windows_agent": agent_version,
        "runtime": runtime,
        "source_commit": commit.lower(),
        "unsigned": True,
        "hardware_validated": False,
        "release_state": f"unsigned-{stage}-package",
    }, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

    manifest = "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n"
                       for name, data in sorted(entries.items())).encode("utf-8")
    entries["FILES.sha256"] = manifest
    output_dir.mkdir(parents=True, exist_ok=True)
    name = f"computer-host-lan-v{version}-windows-{runtime[4:]}-unsigned.zip"
    output = output_dir / name
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, content in sorted(entries.items()):
            zi = zipfile.ZipInfo(path, STAMP)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(zi, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)

    with zipfile.ZipFile(output) as archive:
        if archive.testzip():
            raise ValueError("ZIP corruption")
        member_names = set(archive.namelist())
        expected = set(entries)
        if member_names != expected:
            raise ValueError("ZIP member list mismatch")
        for entry_name, data in entries.items():
            if hashlib.sha256(archive.read(entry_name)).digest() != hashlib.sha256(data).digest():
                raise ValueError(f"ZIP content mismatch: {entry_name}")
        for line in archive.read("FILES.sha256").decode("utf-8").splitlines():
            digest, rel = line.split("  ", 1)
            if hashlib.sha256(archive.read(rel)).hexdigest() != digest:
                raise ValueError(f"ZIP manifest invalid: {rel}")

    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    (output_dir / f"{name}.sha256").write_text(f"{checksum}  {name}\n", encoding="ascii")
    print(f"Built {output} ({len(entries)} files, {output.stat().st_size} bytes)")
    print(f"Verified internal manifest and external SHA256: {checksum}")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--published-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--runtime", default="win-x64", choices=("win-x64", "win-arm64"))
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    build(args.published_dir.resolve(), args.output_dir.resolve(),
          args.runtime, args.source_commit)


if __name__ == "__main__":
    main()
