#!/usr/bin/env python3
"""Collect review evidence from actual build inputs; not a legal sign-off.

Run only on trusted CI build outputs. Copy original license/notice bytes,
not guessed license texts. Missing texts remain explicit review items.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def notice_name(path: Path) -> bool:
    name = path.name.lower()
    return bool(re.match(r"^(licen[cs]e|copying|copyright|notice|third[-_ ]?party[-_ ]?notices|patents)([._ -]|$)", name))


def copy_texts(root: Path, dest: Path, declared: str | None = None,
               *, recursive: bool = False) -> list[dict]:
    files = set(root.rglob("*") if recursive else root.iterdir())
    if declared:
        candidate = root / declared.replace("\\", "/")
        if not candidate.resolve().is_relative_to(root.resolve()):
            raise ValueError("Declared license path escapes package")
        files.add(candidate)
    result = []
    for path in sorted(files):
        if not path.is_file() or path.is_symlink():
            continue
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Notice path escapes package")
        if not notice_name(path) and path != root / (declared or "").replace("\\", "/"):
            continue
        relative = path.relative_to(root)
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        data = path.read_bytes()
        target.write_bytes(data)
        result.append({"path": relative.as_posix(), "sha256": hashlib.sha256(data).hexdigest()})
    return result


def package_record(package: str, roots: list[Path], output: Path) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.+-]+", package):
        raise ValueError("Unexpected package identity")
    name, version = package.split("/")
    relative = Path(name.lower()) / version.lower()
    candidates = [root / relative for root in roots if (root / relative).is_dir()]
    if not candidates:
        return {"package": package, "status": "package_not_found", "notices": []}
    root = candidates[0]
    nuspecs = sorted(root.glob("*.nuspec"))
    declared = None
    license_metadata = {}
    if len(nuspecs) == 1:
        metadata = ET.parse(nuspecs[0]).getroot().find("{*}metadata")
        if metadata is not None:
            for key in ("license", "licenseUrl", "copyright", "repository"):
                node = metadata.find("{*}" + key)
                if node is not None:
                    license_metadata[key] = {"text": node.text, "attributes": node.attrib}
            license_node = license_metadata.get("license", {})
            if license_node.get("attributes", {}).get("type") == "file":
                declared = license_node.get("text")
    notices = copy_texts(root, output / "packages" / relative, declared, recursive=True)
    return {"package": package, "license_metadata": license_metadata,
            "status": "review_required" if notices else "missing_notice_text",
            "notices": notices}


def collect_dotnet(assets: Path, binary: Path, output: Path, runtime: str) -> None:
    graph = json.loads(assets.read_text(encoding="utf-8-sig"))
    targets = [key for key in graph["targets"] if key.endswith("/" + runtime)]
    if len(targets) != 1:
        raise ValueError("Expected exactly one resolved runtime target")
    target = graph["targets"][targets[0]]
    packages = {key for key, value in target.items() if value.get("type") == "package"}
    # Self-contained runtime packs may be downloadDependencies rather than
    # ordinary target libraries. Include them explicitly in the evidence.
    downloads = set()
    for framework in graph["project"]["frameworks"].values():
        for item in framework.get("downloadDependencies", []):
            version = item["version"]
            match = re.fullmatch(r"\[([^,\[\]]+)\]", version)
            if not match:
                raise ValueError("Unresolved runtime-pack version: " + version)
            downloads.add(item["name"] + "/" + match.group(1))
    if not packages:
        raise ValueError("No resolved runtime-target packages")
    # Some SDKs expose runtime packs through different restore metadata.
    # Keep an empty download list explicit for review, rather than treating
    # it as proof that no runtime redistribution obligations exist.
    roots = [Path(path) for path in graph["packageFolders"]]
    output.mkdir(parents=True, exist_ok=False)
    records = [package_record(key, roots, output) for key in sorted(packages | downloads)]
    write_json(output / "resolved.json", {
        "runtime_target": targets[0], "target_packages": sorted(packages),
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "download_dependencies": sorted(downloads), "packages": records,
        "review_status": "not_signed_off",
    })


def json_stream(data: str):
    decoder = json.JSONDecoder()
    while data.strip():
        data = data.lstrip()
        value, end = decoder.raw_decode(data)
        yield value
        data = data[end:]


def collect_go(binary: Path, output: Path) -> None:
    # Invoked in the module directory with the same GOOS/GOARCH/CGO_ENABLED
    # as the binary build. Do not use go list -m all (includes unused modules).
    modules = {}
    data = subprocess.check_output(["go", "list", "-deps", "-json", "."], text=True)
    for package in json_stream(data):
        mod = package.get("Module")
        if not mod or mod.get("Main"):
            continue
        if mod.get("Replace"):
            raise ValueError("Unexpected replaced module")
        modules[mod["Path"]] = mod
    if not modules:
        raise ValueError("No resolved Go dependencies")
    output.mkdir(parents=True, exist_ok=False)
    build_info = subprocess.check_output(["go", "version", "-m", str(binary)], text=True)
    linked = {}
    for line in build_info.splitlines():
        parts = line.strip().split("\t")
        if parts[0] == "dep":
            linked[parts[1]] = parts[2]
        elif parts[0] == "=>":
            raise ValueError("Unexpected replaced module in binary")
    if linked != {name: mod["Version"] for name, mod in modules.items()}:
        raise ValueError("Go dependency inventory differs from binary build info")
    records = []
    for index, (name, module) in enumerate(sorted(modules.items())):
        dest = output / "modules" / str(index)
        notices = copy_texts(Path(module["Dir"]), dest)
        records.append({"module": name, "version": module["Version"],
                        "directory": dest.relative_to(output).as_posix(),
                        "notices": notices,
                        "status": "review_required" if notices else "missing_notice_text"})
    goroot = Path(subprocess.check_output(["go", "env", "GOROOT"], text=True).strip())
    toolchain_notices = copy_texts(goroot, output / "toolchain")
    write_json(output / "resolved.json", {
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "go_version": subprocess.check_output(["go", "env", "GOVERSION"], text=True).strip(),
        "modules": records, "toolchain_notices": toolchain_notices,
        "review_status": "not_signed_off",
    })
    (output / "build-info.txt").write_text(build_info, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="kind", required=True)
    dotnet = sub.add_parser("dotnet")
    dotnet.add_argument("--assets", type=Path, required=True)
    dotnet.add_argument("--binary", type=Path, required=True)
    dotnet.add_argument("--runtime", default="win-x64")
    dotnet.add_argument("--output", type=Path, required=True)
    go = sub.add_parser("go")
    go.add_argument("--binary", type=Path, required=True)
    go.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.kind == "dotnet":
        collect_dotnet(args.assets, args.binary, args.output, args.runtime)
    else:
        collect_go(args.binary.resolve(), args.output)


if __name__ == "__main__":
    main()
