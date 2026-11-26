#!/usr/bin/env python3
"""Compare two exact-source unsigned Go builds and emit release metadata."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil


def asset_name(manifest: dict) -> str:
    version = manifest["integration"]
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-rc\.\d+|-beta\.\d+)?", version):
        raise ValueError("invalid integration version")
    return f"computer-host-lan-v{version}-linux-x64-unsigned-installer"


def file_hash(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing or unsafe asset: {path.name}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_fields(manifest: dict, commit: str, digest: str) -> dict:
    policy = manifest["linux_installer"]
    if (policy.get("runtime") != "linux-amd64" or
            policy.get("unsigned") is not True or
            policy.get("reproducible_build_required") is not True or
            not re.fullmatch(r"1\.\d+\.\d+", policy.get("go_version", "")) or
            not re.fullmatch(r"[a-f0-9]{40}", commit)):
        raise ValueError("invalid Linux release policy or source commit")
    return {
        "integration": manifest["integration"],
        "agent": manifest["agent"],
        "edge_driver": manifest["edge_driver"],
        "agent_protocol": manifest["agent_protocol"],
        "source_commit": commit,
        "runtime": policy["runtime"],
        "go_version": policy["go_version"],
        "unsigned": True,
        "attested": False,
        "reproducible": True,
        "sha256": digest,
    }


def check_build_info(raw: str, expected: dict) -> None:
    lines = raw.splitlines()
    if not lines or not lines[0].endswith("go" + expected["go_version"]):
        raise ValueError("Go toolchain version mismatch")
    # go version -m prints tab-delimited build settings, one per line.
    required = {
        "GOOS": "linux", "GOARCH": "amd64", "GOAMD64": "v1",
        "CGO_ENABLED": "0", "-trimpath": "true",
        "vcs": "git", "vcs.revision": expected["source_commit"],
        "vcs.modified": "false",
    }
    settings = {}
    for line in lines[1:]:
        parts = line.strip().split("\t")
        if len(parts) == 2 and parts[0] == "build" and "=" in parts[1]:
            key, value = parts[1].split("=", 1)
            if key in settings:
                raise ValueError("duplicate Go build setting")
            settings[key] = value
    for key, value in required.items():
        if settings.get(key) != value:
            raise ValueError(f"Go build setting mismatch: {key}")


def check_checksum(path: Path, name: str, digest: str) -> None:
    if path.is_symlink() or not path.is_file() or path.read_text(
            encoding="ascii") != f"{digest}  {name}\n":
        raise ValueError("Linux executable checksum mismatch")


def assemble(a: Path, b: Path, output: Path, manifest: dict, commit: str) -> None:
    name = asset_name(manifest)
    digest = file_hash(a / name)
    expected = expected_fields(manifest, commit, digest)
    if file_hash(b / name) != digest or (a / name).read_bytes() != (b / name).read_bytes():
        raise ValueError("Linux replicas differ")
    info = (a / "go-build-info.txt").read_text(encoding="utf-8")
    if info != (b / "go-build-info.txt").read_text(encoding="utf-8"):
        raise ValueError("Linux replica build information differs")
    check_build_info(info, expected)
    for replica in (a, b):
        check_checksum(replica / f"{name}.sha256", name, digest)
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(a / name, output / name)
    (output / name).chmod(0o755)
    shutil.copyfile(a / f"{name}.sha256", output / f"{name}.sha256")
    (output / f"{name}.build-info.json").write_text(
        json.dumps({**expected, "go_build_info": info}, indent=2) + "\n",
        encoding="utf-8")
    validate_metadata(output, manifest, commit)
    print(f"PASS independently reproduced unsigned Linux installer: {digest}")


def validate_metadata(directory: Path, manifest: dict, commit: str) -> None:
    name = asset_name(manifest)
    digest = file_hash(directory / name)
    expected = expected_fields(manifest, commit, digest)
    check_checksum(directory / f"{name}.sha256", name, digest)
    info_path = directory / f"{name}.build-info.json"
    if info_path.is_symlink() or not info_path.is_file():
        raise ValueError("missing Linux build metadata")
    metadata = json.loads(info_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict) or set(metadata) != set(expected) | {"go_build_info"}:
        raise ValueError("unexpected Linux metadata fields")
    for key, value in expected.items():
        if type(metadata[key]) is not type(value) or metadata[key] != value:
            raise ValueError(f"Linux BUILD-INFO {key} mismatch")
    check_build_info(metadata["go_build_info"], expected)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--replica-a", type=Path, required=True)
    parser.add_argument("--replica-b", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    assemble(args.replica_a, args.replica_b, args.output_dir,
             json.loads(args.manifest.read_text(encoding="utf-8")), args.source_commit)


if __name__ == "__main__":
    main()
