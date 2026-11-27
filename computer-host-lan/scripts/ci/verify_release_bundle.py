#!/usr/bin/env python3
"""Validate that versioned release artifacts describe one immutable release.

SHA-256 integrity is checked separately by the release workflow. This verifier
prevents passing checksums for the *wrong* version or source commit.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from zipfile import ZipFile

if __package__:
    from .linux_release_metadata import notices_name, validate_metadata
else:
    from linux_release_metadata import notices_name, validate_metadata


def validate_bundle(directory: Path, manifest: dict, commit: str) -> None:
    version = manifest["integration"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("source commit must be a complete lowercase SHA-1")
    name = f"computer-host-lan-v{version}"
    expected_zips = {
        f"{name}-source.zip",
        f"{name}-documentation.zip",
        f"{name}-windows-x64-unsigned.zip",
    }
    found_zips = {item.name for item in directory.glob("*.zip")}
    if found_zips != expected_zips:
        raise ValueError(f"wrong versioned ZIP set: {sorted(found_zips)}")
    setups = sorted(item.name for item in directory.glob("*setup.exe"))
    if setups != [f"{name}-windows-x64-unsigned-setup.exe"]:
        raise ValueError(f"wrong versioned Windows installer: {setups}")
    for filename in expected_zips:
        with ZipFile(directory / filename) as archive:
            if archive.testzip():
                raise ValueError(f"corrupted ZIP: {filename}")
    with ZipFile(directory / f"{name}-windows-x64-unsigned.zip") as archive:
        metadata = json.loads(archive.read("BUILD-INFO.json"))
        expected = {
            "integration": version,
            "windows_agent": manifest["windows_agent"],
            "runtime": "win-x64",
            "source_commit": commit,
            "unsigned": True,
        }
        for key, value in expected.items():
            if metadata.get(key) != value:
                raise ValueError(f"Windows BUILD-INFO {key} mismatch: {metadata.get(key)!r} != {value!r}")
    source_name = f"{name}/release.json"
    docs_name = f"computer-host-lan-docs-v{version}/release.json"
    for filename, member in (
        (f"{name}-source.zip", source_name),
        (f"{name}-documentation.zip", docs_name),
    ):
        with ZipFile(directory / filename) as archive:
            embedded = json.loads(archive.read(member))
            if embedded != manifest:
                raise ValueError(f"version/release manifest mismatch inside {filename}")
    if "linux_installer" in manifest:
        validate_metadata(directory, manifest, commit)
        from hashlib import sha256
        installer = f"{name}-linux-x64-unsigned-installer"
        published = expected_zips | {setups[0], installer,
                                     installer + ".sha256",
                                     installer + ".build-info.json",
                                     notices_name(manifest)}
        sums = directory / "SHA256SUMS.txt"
        entries = {}
        for line in sums.read_text(encoding="ascii").splitlines():
            match = re.fullmatch(r"([a-f0-9]{64})  ([A-Za-z0-9._-]+)", line)
            if not match or match[2] in entries:
                raise ValueError("invalid or duplicate unified checksum entry")
            entries[match[2]] = match[1]
        if set(entries) != published:
            raise ValueError("unified checksum manifest does not cover exact release asset set")
        for filename, digest in entries.items():
            path = directory / filename
            if path.is_symlink() or not path.is_file() or sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError(f"unified checksum mismatch: {filename}")
    print(f"PASS exact release asset names, source commit {commit}, and all component versions ({version})")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    validate_bundle(args.directory, manifest, args.source_commit)


if __name__ == "__main__":
    main()
