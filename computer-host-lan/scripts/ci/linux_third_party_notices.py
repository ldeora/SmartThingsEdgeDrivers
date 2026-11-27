#!/usr/bin/env python3
"""Generate and check the Linux installer's third-party notices (#190).

The Linux installer is a statically linked Go program. Every module compiled
into it, and the Go standard library and runtime, ships under a licence that
requires its notice to accompany the binary. This script builds the notices
file from the module graph of the release build target, using the licence
files in the verified module cache, and checks that the committed file is
current. It never infers a licence it does not recognise: an unknown licence
fails the check and needs a manual decision.

Usage, from the repository root or anywhere:

  linux_third_party_notices.py generate   # rewrite the committed file
  linux_third_party_notices.py check      # fail if it is out of date
  linux_third_party_notices.py check --build-info go-build-info.txt
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = ROOT / "linux-installer"
NOTICES = MODULE_DIR / "THIRD-PARTY-NOTICES.txt"
STDLIB = "Go standard library and runtime"
# Release target; see the Linux installer job in computer-host-release.yml.
BUILD_ENV = {"GOOS": "linux", "GOARCH": "amd64", "CGO_ENABLED": "0",
             "GOFLAGS": "-mod=readonly"}
LICENCE_FILE = re.compile(r"(?i)^(licen[cs]e|copying|notice|patents)(\.(md|txt))?$")
MODULE_LINE = re.compile(r"^Module: (\S+) (\S+)$")
RULE = "=" * 78


class NoticeError(ValueError):
    pass


def classify(text: str) -> str:
    """Return the SPDX identifier for the licence texts handled here."""
    flat = " ".join(text.split())
    if "Permission is hereby granted, free of charge" in flat:
        return "MIT"
    if "Redistribution and use in source and binary forms" in flat:
        if "Neither the name" in flat or "may be used to endorse" in flat:
            return "BSD-3-Clause"
        return "BSD-2-Clause"
    if "Apache License" in flat and "Version 2.0" in flat:
        return "Apache-2.0"
    if "Permission to use, copy, modify, and/or distribute" in flat:
        return "ISC"
    raise NoticeError("unrecognised licence text; review it manually")


def licence_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        raise NoticeError(f"module directory missing: {directory}")
    files = sorted((p for p in directory.iterdir()
                    if p.is_file() and not p.is_symlink() and LICENCE_FILE.match(p.name)),
                   key=lambda p: p.name.lower())
    if not files:
        raise NoticeError(f"no licence file in {directory}")
    return files


def read_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    return text.rstrip() + "\n"


def licence_of(files: list[Path]) -> str:
    # PATENTS and NOTICE accompany a licence; they do not name one.
    names = {classify(read_text(p)) for p in files
             if not re.match(r"(?i)^(patents|notice)", p.name)}
    if len(names) != 1:
        raise NoticeError(f"expected one licence, found {sorted(names) or 'none'}")
    return names.pop()


def go(*args: str, cwd: Path) -> str:
    env = {**os.environ, **BUILD_ENV}
    result = subprocess.run(["go", *args], cwd=cwd, env=env, check=True,
                            capture_output=True, text=True)
    return result.stdout


def module_graph(module_dir: Path) -> list[tuple[str, str, Path]]:
    """Modules linked into the release target, from the Go module graph."""
    template = ("{{with .Module}}{{if not .Main}}{{.Path}}\t{{.Version}}\t{{.Dir}}"
                "\t{{if .Replace}}replaced{{end}}{{end}}{{end}}")
    modules = set()
    for line in go("list", "-deps", "-f", template, ".", cwd=module_dir).splitlines():
        if not line:
            continue
        path, version, directory, replaced = line.split("\t")
        if replaced:
            raise NoticeError(f"replaced module needs manual review: {path}")
        if not version or not directory:
            raise NoticeError(f"module without version or source: {path}")
        modules.add((path, version, Path(directory)))
    return sorted(modules)


def render(modules: list[tuple[str, str, Path]], goroot: Path) -> str:
    stdlib_files = licence_files(goroot)
    entries = [(STDLIB, "", licence_of(stdlib_files), stdlib_files)]
    entries += [(path, version, licence_of(files), files)
                for path, version, directory in modules
                for files in [licence_files(directory)]]
    width = max(len(f"{name} {version}".strip()) for name, version, _, _ in entries)
    out = [
        "Computer Host LAN Linux installer: third-party notices",
        "",
        "The Linux installer is a statically linked Go program. It contains the",
        "components below, each under its own licence, reproduced in full in this",
        "file. Computer Host LAN itself is licensed under Apache-2.0 (LICENSE in",
        "the source archive). The exact Go toolchain version and module checksums",
        "are recorded in the release's build-info.json.",
        "",
        "Generated by computer-host-lan/scripts/ci/linux_third_party_notices.py",
        "from the module graph of the linux/amd64 release build. Do not edit by",
        "hand; run the script's generate command after a dependency change.",
        "",
        f"Components ({len(entries)}):",
        "",
    ]
    out += [f"  {f'{name} {version}'.strip():<{width}}  {spdx}"
            for name, version, spdx, _ in entries]
    for name, version, spdx, files in entries:
        out += ["", RULE,
                f"Module: {name} {version}" if version else name,
                f"License: {spdx}", RULE]
        for path in files:
            out += ["", f"--- {path.name} ---", "", read_text(path).rstrip("\n")]
    return "\n".join(out) + "\n"


def listed_modules(text: str) -> set[tuple[str, str]]:
    """Module path and version pairs named in a notices file."""
    found = [m.groups() for line in text.splitlines() if (m := MODULE_LINE.match(line))]
    if len(found) != len(set(found)):
        raise NoticeError("duplicate module in notices")
    if STDLIB not in text.splitlines():
        raise NoticeError("Go standard library notice missing")
    return set(found)


def build_info_modules(raw: str) -> set[tuple[str, str]]:
    """Linked modules from `go version -m` output."""
    modules = set()
    for line in raw.splitlines():
        parts = line.strip().split("\t")
        if parts[0] == "=>":
            raise NoticeError("replaced module in build info needs manual review")
        if parts[0] == "dep":
            if len(parts) < 3:
                raise NoticeError("malformed dependency line in build info")
            modules.add((parts[1], parts[2]))
    return modules


def check_build_info(notices: str, raw: str) -> None:
    listed, linked = listed_modules(notices), build_info_modules(raw)
    if listed != linked:
        missing = sorted(f"{p} {v}" for p, v in linked - listed)
        extra = sorted(f"{p} {v}" for p, v in listed - linked)
        raise NoticeError(f"notices do not match the binary: missing {missing}, extra {extra}")


def generate(module_dir: Path) -> str:
    goroot = Path(go("env", "GOROOT", cwd=module_dir).strip())
    return render(module_graph(module_dir), goroot)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("generate", "check"))
    parser.add_argument("--module-dir", type=Path, default=MODULE_DIR)
    parser.add_argument("--notices", type=Path, default=NOTICES)
    parser.add_argument("--build-info", type=Path,
                        help="also compare with `go version -m` output of the built binary")
    args = parser.parse_args(argv)
    try:
        expected = generate(args.module_dir)
        if args.command == "generate":
            args.notices.write_text(expected, encoding="utf-8")
            print(f"Wrote {args.notices}")
            return 0
        current = args.notices.read_text(encoding="utf-8") if args.notices.is_file() else ""
        if current != expected:
            print(f"{args.notices} is out of date. Run: python3 "
                  "computer-host-lan/scripts/ci/linux_third_party_notices.py generate",
                  file=sys.stderr)
            return 1
        if args.build_info:
            check_build_info(current, args.build_info.read_text(encoding="utf-8"))
        print(f"PASS third-party notices cover {len(listed_modules(current))} modules "
              "and the Go standard library")
        return 0
    except (NoticeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
