#!/usr/bin/env python3
"""Small static consistency checks for the Tuya Air Purifier Edge Driver."""
from __future__ import annotations

import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("ERROR: PyYAML is required for this validation script", file=sys.stderr)
    sys.exit(2)

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PACKAGE_KEY = "tuya-air-purifier"
EXPECTED_PROFILE = "tuya-air-purifier"
EXPECTED_NAMESPACE = "oceancircle09600"
CUSTOM_CAPS = [
    "airPurifierDisplayLight",
    "airPurifierTimer",
]


def load_yaml(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def require_file(path: Path) -> None:
    if not path.is_file():
        fail(f"Missing required file: {path.relative_to(ROOT)}")


def main() -> None:
    for rel in [
        "config.yml",
        "README.md",
        "CHANGELOG.md",
        "profiles/tuya-air-purifier.yaml",
        "src/init.lua",
        "scripts/create-custom-capabilities.sh",
    ]:
        require_file(ROOT / rel)

    config = load_yaml(ROOT / "config.yml")
    if config.get("packageKey") != EXPECTED_PACKAGE_KEY:
        fail(f"config.yml packageKey should be {EXPECTED_PACKAGE_KEY!r}")
    if config.get("permissions", {}).get("lan") is None:
        fail("config.yml should include lan permission")
    if config.get("permissions", {}).get("discovery") is None:
        fail("config.yml should include discovery permission")

    profile = load_yaml(ROOT / "profiles" / "tuya-air-purifier.yaml")
    if profile.get("name") != EXPECTED_PROFILE:
        fail(f"profile name should be {EXPECTED_PROFILE!r}")

    profile_text = (ROOT / "profiles" / "tuya-air-purifier.yaml").read_text(encoding="utf-8")
    init_text = (ROOT / "src" / "init.lua").read_text(encoding="utf-8")
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")

    for cap in CUSTOM_CAPS:
        cap_yaml = ROOT / "capabilities" / f"{cap}.yaml"
        pres_yaml = ROOT / "presentations" / f"{cap}.presentation.yaml"
        require_file(cap_yaml)
        require_file(pres_yaml)

        cap_doc = load_yaml(cap_yaml)
        if cap_doc.get("id") != cap:
            fail(f"{cap_yaml.relative_to(ROOT)} id should be {cap!r}")

        fqid = f"{EXPECTED_NAMESPACE}.{cap}"
        if fqid not in profile_text:
            fail(f"Profile does not reference {fqid}")
        if fqid not in init_text:
            fail(f"src/init.lua does not reference {fqid}")
        if fqid not in readme_text:
            fail(f"README.md does not mention {fqid}")

    if 'profile = "tuya-air-purifier"' not in init_text:
        fail("src/init.lua discovery metadata should use profile 'tuya-air-purifier'")
    if 'label = "Air Purifier"' not in init_text:
        fail("src/init.lua discovery metadata should create label 'Air Purifier'")
    if 'local DRIVER_NAME = "Tuya Air Purifier Local"' not in init_text:
        fail("src/init.lua should use generic driver name 'Tuya Air Purifier Local'")

    print("Static validation passed.")


if __name__ == "__main__":
    main()
