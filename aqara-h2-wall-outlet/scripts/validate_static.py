#!/usr/bin/env python3
"""Lightweight static checks for the Aqara H2 Wall Outlet Edge driver."""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def read_text(rel: str) -> str:
    path = ROOT / rel
    if not path.exists():
        fail(f"Missing required file: {rel}")
    return path.read_text(encoding="utf-8")


config = read_text("config.yaml")
fingerprints = read_text("fingerprints.yaml")
profile = read_text("profiles/aqara-h2-wall-outlet-eu.yaml")
init_lua = read_text("src/init.lua")
common_lua = read_text("src/aqara_h2_outlet/common.lua")
readme = read_text("README.md")
changelog = read_text("CHANGELOG.md")

expected = {
    "packageKey": "aqara-h2-outlet-eu",
    "profile": "aqara-h2-wall-outlet-eu",
    "driver_name": "aqara-h2-outlet-eu",
    "model": "lumi.plug.aeu001",
}

if f"packageKey: {expected['packageKey']}" not in config:
    fail("config.yaml packageKey changed unexpectedly")

if f"name: {expected['profile']}" not in profile:
    fail("profile name changed unexpectedly")

if expected["model"] not in fingerprints:
    fail("fingerprints.yaml does not contain the expected Zigbee model")

if fingerprints.count(f"deviceProfileName: {expected['profile']}") < 2:
    fail("fingerprints.yaml does not consistently reference the expected profile")

if f'ZigbeeDriver("{expected["driver_name"]}"' not in init_lua:
    fail("src/init.lua driver name changed unexpectedly")

if 'current_config_version = 12' not in init_lua:
    fail("current_config_version is not 12")

for required in [
    "local CONTROL_ENDPOINT = 2",
    "local FALLBACK_CONTROL_ENDPOINT = 1",
    "local ANALOG_POWER_ENDPOINT = 21",
    "local AQARA_CLUSTER_ID = 0xFCC0",
    "local MFG_CODE = 0x115F",
]:
    if required not in common_lua:
        fail(f"Missing expected runtime constant: {required}")

if "Aqara-H2-Wall-Outlet-EU-reviewed-v12" in readme:
    fail("README still contains the old archive/directory name")

if "## v12 review notes" in readme:
    fail("README still contains historical review notes that belong in CHANGELOG.md")

if "## v12 review notes" not in changelog:
    fail("CHANGELOG.md is missing the v12 historical notes")

# Basic syntax smoke checks for obvious accidental truncation.
if init_lua.count("{") != init_lua.count("}"):
    fail("src/init.lua has mismatched braces")

for rel in ["src/init.lua", "src/aqara_h2_outlet/common.lua"]:
    text = read_text(rel)
    if "TODO" in text or "FIXME" in text:
        fail(f"{rel} contains TODO/FIXME markers")

print("Static validation passed.")
