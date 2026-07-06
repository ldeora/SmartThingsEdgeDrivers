#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "config.yaml",
    "search-parameters.yml",
    "profiles/davis-airlink.yaml",
    "src/init.lua",
    "src/airlink/constants.lua",
    "src/airlink/util.lua",
    "src/airlink/parser.lua",
    "src/airlink/api.lua",
    "src/airlink/discovery.lua",
    "src/airlink/health.lua",
    "README.md",
    "CHANGELOG.md",
    "TESTING.md",
]

EXPECTED_SNIPPETS = {
    "config.yaml": [
        "name: Davis AirLink LAN",
        "packageKey: davis-airlink-lan",
        "lan: {}",
        "discovery: {}",
    ],
    "profiles/davis-airlink.yaml": [
        "name: davis-airlink",
        "temperatureMeasurement",
        "relativeHumidityMeasurement",
        "veryFineDustSensor",
        "fineDustSensor",
        "dustSensor",
        "airQualityHealthConcern",
        "pollInterval",
        "healthBasis",
        "hostOverride",
        "debugLogging",
    ],
    "search-parameters.yml": [
        "_airlink._tcp",
    ],
    "src/airlink/constants.lua": [
        'constants.DRIVER_NAME = "Davis AirLink LAN"',
        'constants.DRIVER_VERSION = "1.0.3"',
        'constants.PROFILE_NAME = "davis-airlink"',
        'constants.DNI_PREFIX = "davis-airlink:"',
        'constants.MDNS_SERVICE_TYPE = "_airlink._tcp"',
    ],
    "src/init.lua": [
        'require "st.driver"',
        'require "st.capabilities"',
        'Driver(constants.DRIVER_NAME, driver_template)',
        'davis_airlink_driver:run()',
    ],
}

FORBIDDEN_PATH_PARTS = {
    ".git",
    "__MACOSX",
}

FORBIDDEN_SUFFIXES = {
    ".zip",
    ".DS_Store",
}


def fail(message: str) -> None:
    print(f"Static validation failed: {message}", file=sys.stderr)
    sys.exit(1)


def read_text(rel: str) -> str:
    path = ROOT / rel
    if not path.exists():
        fail(f"missing required file: {rel}")
    return path.read_text(encoding="utf-8")


def main() -> None:
    for rel in REQUIRED_FILES:
        if not (ROOT / rel).exists():
            fail(f"missing required file: {rel}")

    for path in ROOT.rglob("*"):
        rel_parts = set(path.relative_to(ROOT).parts)
        if rel_parts & FORBIDDEN_PATH_PARTS:
            fail(f"forbidden path present: {path.relative_to(ROOT)}")
        if path.name in FORBIDDEN_SUFFIXES or path.suffix in FORBIDDEN_SUFFIXES:
            fail(f"forbidden file present: {path.relative_to(ROOT)}")

    for rel, snippets in EXPECTED_SNIPPETS.items():
        text = read_text(rel)
        for snippet in snippets:
            if snippet not in text:
                fail(f"expected snippet not found in {rel}: {snippet}")

    notes = ROOT / "NOTES.md"
    if notes.exists():
        fail("NOTES.md should be folded into CHANGELOG.md for the repo-ready package")

    print("Static validation passed.")


if __name__ == "__main__":
    main()
