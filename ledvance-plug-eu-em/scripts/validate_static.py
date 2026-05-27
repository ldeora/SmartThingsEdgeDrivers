#!/usr/bin/env python3
"""Lightweight static validation for the LEDVANCE Plug EU EM Edge Driver."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "config.yaml",
    "fingerprints.yaml",
    "profiles/ledvance-plug-eu-em.yaml",
    "src/init.lua",
    "src/ledvance_plug_eu_em/common.lua",
    "README.md",
]

EXPECTED_SNIPPETS = {
    "config.yaml": [
        "name: LEDVANCE Plug EU EM",
        "packageKey: ledvance-plug-eu-em",
        "permissions:",
        "zigbee: {}",
    ],
    "fingerprints.yaml": [
        "manufacturer: LEDVANCE",
        "model: PLUG EU EM T",
        "model: PLUG EU EM T, black",
        "deviceProfileName: ledvance-plug-eu-em",
    ],
    "profiles/ledvance-plug-eu-em.yaml": [
        "name: ledvance-plug-eu-em",
        "- id: switch",
        "- id: powerMeter",
        "- id: energyMeter",
        "- id: voltageMeasurement",
        "- id: currentMeasurement",
        "name: powerOnBehavior",
    ],
    "src/init.lua": [
        "require \"ledvance_plug_eu_em.common\"",
        "ZigbeeDriver(\"ledvance-plug-eu-em\"",
    ],
    "src/ledvance_plug_eu_em/common.lua": [
        "local STARTUP_ONOFF_ATTR_ID = 0x4003",
        "capabilities.powerMeter.power",
        "capabilities.energyMeter.energy",
        "capabilities.voltageMeasurement.voltage",
        "capabilities.currentMeasurement.current",
    ],
}


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    for rel in REQUIRED_FILES:
        path = ROOT / rel
        if not path.is_file():
            fail(f"Missing required file: {rel}")

    for rel, snippets in EXPECTED_SNIPPETS.items():
        text = (ROOT / rel).read_text(encoding="utf-8")
        for snippet in snippets:
            if snippet not in text:
                fail(f"Expected snippet not found in {rel}: {snippet}")

    junk_patterns = {".DS_Store", "__MACOSX"}
    for path in ROOT.rglob("*"):
        if path.name in junk_patterns:
            fail(f"Junk file/directory found: {path.relative_to(ROOT)}")
        if path.name == ".git" and path.is_dir():
            fail(f"Nested .git directory found: {path.relative_to(ROOT)}")

    print("Static validation passed.")


if __name__ == "__main__":
    main()
