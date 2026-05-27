#!/usr/bin/env python3
"""Lightweight static validation for the Aqara Curtain Driver E1 Edge Driver.

This is not a replacement for SmartThings CLI packaging or real hub testing.
It only catches common repository/package mistakes before publishing.
"""

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "config.yml",
    "fingerprints.yml",
    "profiles/window-treatment-aqara-curtain-driver-e1.yml",
    "src/init.lua",
    "README.md",
    "CHANGELOG.md",
]

EXPECTED = {
    "package_key": "aqara-curtain-driver-e1",
    "driver_name": "Aqara Curtain Driver E1",
    "manufacturer": "LUMI",
    "model": "lumi.curtain.agl001",
    "profile": "window-treatment-aqara-curtain-driver-e1",
    "private_cluster": "0xFCC0",
    "light_attribute": "0x0429",
    "manufacturer_code": "0x115F",
}


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def require_contains(path: str, needle: str, description: str) -> None:
    text = read(path)
    if needle not in text:
        fail(f"{path} does not contain expected {description}: {needle}")


def main() -> None:
    missing = [path for path in REQUIRED_FILES if not (ROOT / path).is_file()]
    if missing:
        fail("missing required files: " + ", ".join(missing))

    config = read("config.yml")
    if f"packageKey: '{EXPECTED['package_key']}'" not in config and f'packageKey: "{EXPECTED["package_key"]}"' not in config:
        fail("config.yml does not contain the expected packageKey")
    require_contains("config.yml", EXPECTED["driver_name"], "driver name")

    fingerprints = read("fingerprints.yml")
    require_contains("fingerprints.yml", EXPECTED["manufacturer"], "manufacturer")
    require_contains("fingerprints.yml", EXPECTED["model"], "model")
    require_contains("fingerprints.yml", EXPECTED["profile"], "profile name")

    profile = read("profiles/window-treatment-aqara-curtain-driver-e1.yml")
    require_contains("profiles/window-treatment-aqara-curtain-driver-e1.yml", f"name: {EXPECTED['profile']}", "profile name")
    for capability in [
        "windowShade",
        "windowShadeLevel",
        "battery",
        "stse.chargingState",
        "stse.hookLockState",
        "illuminanceMeasurement",
        "refresh",
    ]:
        require_contains("profiles/window-treatment-aqara-curtain-driver-e1.yml", capability, f"capability {capability}")

    init_lua = read("src/init.lua")
    for token in [
        "PRIVATE_CLUSTER_ID = 0xFCC0",
        "PRIVATE_CURTAIN_LIGHT_LEVEL_ATTRIBUTE_ID = 0x0429",
        "MFG_CODE = 0x115F",
        "capabilities.illuminanceMeasurement",
        'ZigbeeDriver("aqara_curtain_driver_e1"',
    ]:
        require_contains("src/init.lua", token, f"runtime token {token}")

    junk_patterns = ["*.zip", "__MACOSX", ".DS_Store"]
    found_junk = []
    for pattern in junk_patterns:
        found_junk.extend(str(path.relative_to(ROOT)) for path in ROOT.rglob(pattern))
    if found_junk:
        fail("unexpected junk files found: " + ", ".join(found_junk))

    nested_git = [str(path.relative_to(ROOT)) for path in ROOT.rglob(".git") if path.is_dir()]
    if nested_git:
        fail("nested .git directories found: " + ", ".join(nested_git))

    print("Static validation passed.")


if __name__ == "__main__":
    main()
