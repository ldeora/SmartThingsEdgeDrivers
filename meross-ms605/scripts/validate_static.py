#!/usr/bin/env python3
"""Small dependency-free static checks for the Meross MS605 Edge Driver."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def read(relative: str) -> str:
    path = ROOT / relative
    if not path.is_file():
        fail(f"missing required file: {relative}")
    return path.read_text(encoding="utf-8")


def require(text: str, pattern: str, description: str, *, regex: bool = False) -> None:
    found = re.search(pattern, text, re.MULTILINE) if regex else pattern in text
    if not found:
        fail(f"missing or unexpected {description}")


def main() -> None:
    config = read("config.yml")
    fingerprints = read("fingerprints.yml")
    profile = read("profiles/meross-ms605.yml")
    init_lua = read("src/init.lua")
    read("README.md")
    read("LICENSE")

    require(config, "packageKey: 'meross-ms605-presence-sensor'", "package key")
    require(config, "matter: {}", "Matter permission")

    require(fingerprints, 'vendorId: 0x1345', "Matter Vendor ID")
    require(fingerprints, 'productId: 0x4202', "Matter Product ID")
    require(fingerprints, 'deviceProfileName: meross-ms605', "fingerprint profile")

    component_ids = re.findall(r"^- id: (main|zone1|zone2|zone3)$", profile, re.MULTILINE)
    if component_ids != ["main", "zone1", "zone2", "zone3"]:
        fail(f"unexpected profile components: {component_ids!r}")

    if profile.count("- id: presenceSensor") != 4:
        fail("profile must expose presenceSensor on all four components")

    for capability in ("illuminanceMeasurement", "battery", "firmwareUpdate", "refresh"):
        require(profile, f"- id: {capability}", f"{capability} capability")

    require(init_lua, 'local DRIVER_NAME = "meross-ms605-presence-sensor"', "driver name")
    require(init_lua, 'local PROFILE_NAME = "meross-ms605"', "profile constant")
    require(init_lua, 'local ZONE_ENDPOINTS = { 2, 3, 4 }', "zone endpoint list")

    expected_mappings = {
        '[1] = "main"',
        '[2] = "zone1"',
        '[3] = "zone2"',
        '[4] = "zone3"',
    }
    for mapping in expected_mappings:
        require(init_lua, mapping, f"endpoint mapping {mapping}")

    for required_symbol in (
        "occupancy_handler",
        "emit_aggregate_presence",
        "build_refresh_request",
        "schedule_synthetic_initialization",
        "device:subscribe()",
        "shared_device_thread_enabled = true",
    ):
        require(init_lua, required_symbol, required_symbol)

    print("Static validation passed.")


if __name__ == "__main__":
    main()
