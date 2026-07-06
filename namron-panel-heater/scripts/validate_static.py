#!/usr/bin/env python3
"""Lightweight static checks for the Namron Panel Heater Edge Driver."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "config.yml",
    "fingerprints.yml",
    "profiles/namron-panel-heater.yml",
    "src/init.lua",
    "README.md",
    "CHANGELOG.md",
]

EXPECTED_PACKAGE_KEY = "namron-panel-heater"
EXPECTED_PROFILE = "namron-panel-heater"
EXPECTED_MODELS = {str(model) for model in range(5401392, 5401400)}


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    for rel in REQUIRED_FILES:
        if not (ROOT / rel).is_file():
            fail(f"missing required file: {rel}")

    config = read("config.yml")
    fingerprints = read("fingerprints.yml")
    profile = read("profiles/namron-panel-heater.yml")
    init_lua = read("src/init.lua")

    if f"packageKey: '{EXPECTED_PACKAGE_KEY}'" not in config and f'packageKey: "{EXPECTED_PACKAGE_KEY}"' not in config:
        fail(f"config.yml does not contain expected packageKey {EXPECTED_PACKAGE_KEY!r}")

    if f"defaultProfile: '{EXPECTED_PROFILE}'" not in config and f'defaultProfile: "{EXPECTED_PROFILE}"' not in config:
        fail(f"config.yml does not contain expected defaultProfile {EXPECTED_PROFILE!r}")

    if not profile.lstrip().startswith(f"name: {EXPECTED_PROFILE}"):
        fail(f"profile name is not {EXPECTED_PROFILE!r}")

    referenced_profiles = set(re.findall(r"deviceProfileName:\s*([A-Za-z0-9_.-]+)", fingerprints))
    if referenced_profiles != {EXPECTED_PROFILE}:
        fail(f"fingerprints reference unexpected profiles: {sorted(referenced_profiles)}")

    models = set(re.findall(r'model:\s*"(540139[2-9])"', fingerprints))
    if models != EXPECTED_MODELS:
        fail(f"fingerprints do not cover expected 5401392-5401399 models: {sorted(models)}")

    for required in [
        "ThermostatMode",
        "ThermostatHeatingSetpoint",
        "PowerMeter",
        "EnergyMeter",
        "VoltageMeasurement",
        "CurrentMeasurement",
        "ContactSensor",
        "MFG_CODE = 0x1224",
        "ATTR_HYSTERESIS = 0x100A",
        "ATTR_WINDOW_OPEN = 0x100B",
    ]:
        if required not in init_lua:
            fail(f"src/init.lua is missing expected marker: {required}")

    stale_names = [
        "edge-driver-oceancircle09600-v0.1.4",
        "reviewed-v",
        "beta",
    ]
    for rel in ["README.md", "TESTING.md"]:
        text = read(rel)
        for stale in stale_names:
            if stale in text:
                fail(f"{rel} contains stale packaging/review marker: {stale}")

    print("Static validation passed.")


if __name__ == "__main__":
    main()
