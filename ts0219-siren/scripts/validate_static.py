#!/usr/bin/env python3
"""Local static validation for the TS0219 Siren SmartThings Edge driver.

This does not replace `smartthings edge:drivers:package .`, but it catches
schema and consistency mistakes that can be detected without access to
SmartThings' backend.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("PyYAML is required: python3 -m pip install pyyaml") from exc

ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = "oceancircle09600"
EXPECTED_PROFILE_NAME = "ts0219Siren"
UNIT_REF_RE = re.compile(r"(^[a-z]*([A-Z][a-z]*)*){1,36}(\.unit)$")
PROFILE_NAME_RE = re.compile(r"^[a-z][a-zA-Z0-9]+$")
PREFERENCE_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9]*$")

errors: list[str] = []


def fail(message: str) -> None:
    errors.append(message)


def load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        fail(f"Invalid JSON: {path.relative_to(ROOT)}: {exc}")
        return None


def load_yaml(path: Path):
    try:
        return yaml.safe_load(path.read_text())
    except Exception as exc:
        fail(f"Invalid YAML: {path.relative_to(ROOT)}: {exc}")
        return None


for path in ROOT.rglob("*.json"):
    load_json(path)

for path in list(ROOT.rglob("*.yml")) + list(ROOT.rglob("*.yaml")):
    load_yaml(path)

profiles_dir = ROOT / "profiles"
profiles = {}
for profile_path in profiles_dir.glob("*.yml"):
    profile = load_yaml(profile_path)
    if not profile:
        continue

    profile_name = profile.get("name", "")
    profiles[profile_name] = profile_path

    if not 3 <= len(profile_name) <= 24:
        fail(f"Profile name must be 3-24 chars: {profile_name!r} ({len(profile_name)})")
    if not PROFILE_NAME_RE.fullmatch(profile_name):
        fail(f"Profile name does not match SmartThings embedded profile pattern: {profile_name!r}")

    for pref in profile.get("preferences", []):
        name = pref.get("name", "")
        if not 3 <= len(name) <= 24:
            fail(f"Preference name must be 3-24 chars: {name!r} ({len(name)})")
        if not PREFERENCE_NAME_RE.fullmatch(name):
            fail(f"Preference name should be alphanumeric camelCase: {name!r}")

    custom_profile_caps = {
        cap.get("id")
        for comp in profile.get("components", [])
        for cap in comp.get("capabilities", [])
        if isinstance(cap.get("id"), str) and cap.get("id", "").startswith(NAMESPACE + ".")
    }

    capability_defs = {
        f"{NAMESPACE}.{path.stem}"
        for path in (ROOT / "custom-capabilities" / "capabilities").glob("*.json")
    }
    presentations = {
        f"{NAMESPACE}.{path.stem}"
        for path in (ROOT / "custom-capabilities" / "presentations").glob("*.json")
    }

    for cap_id in sorted(custom_profile_caps - capability_defs):
        fail(f"Missing custom capability definition for profile capability: {cap_id}")
    for cap_id in sorted(custom_profile_caps - presentations):
        fail(f"Missing custom capability presentation for profile capability: {cap_id}")

if EXPECTED_PROFILE_NAME not in profiles:
    fail(f"Expected profile {EXPECTED_PROFILE_NAME!r} not found in profiles/*.yml")

fingerprints_path = ROOT / "fingerprints.yml"
fingerprints = load_yaml(fingerprints_path)
if fingerprints:
    allowed_top = {
        "zigbeeManufacturer",
        "zigbeeGeneric",
        "matterManufacturer",
        "matterGeneric",
        "zwaveManufacturer",
        "zwaveGeneric",
    }
    for key in fingerprints.keys():
        if key not in allowed_top:
            fail(f"Unknown fingerprint section: {key}")

    for i, fp in enumerate(fingerprints.get("zigbeeManufacturer", []) or []):
        for required in ("id", "manufacturer", "model", "deviceProfileName"):
            if fp.get(required) in (None, ""):
                fail(f"zigbeeManufacturer[{i}] missing required field: {required}")
        profile_name = fp.get("deviceProfileName")
        if profile_name not in profiles:
            fail(f"zigbeeManufacturer[{i}] references missing profile: {profile_name!r}")

    for i, fp in enumerate(fingerprints.get("zigbeeGeneric", []) or []):
        has_ids = bool(fp.get("deviceIdentifiers"))
        clusters = fp.get("clusters") or {}
        has_server = bool((clusters.get("server") if isinstance(clusters, dict) else None))
        has_client = bool((clusters.get("client") if isinstance(clusters, dict) else None))
        if not (has_ids or has_server or has_client):
            fail(f"zigbeeGeneric[{i}] must set one of deviceIdentifiers, clusters.server, or clusters.client")
        if "manufacturer" in fp or "model" in fp:
            fail(f"zigbeeGeneric[{i}] contains manufacturer/model; use zigbeeManufacturer for exact manufacturer/model matches")


def walk_for_units(obj, path: Path, location=""):
    if isinstance(obj, dict):
        nf = obj.get("numberField")
        if isinstance(nf, dict) and "unit" in nf:
            unit = nf["unit"]
            if not isinstance(unit, str) or not UNIT_REF_RE.fullmatch(unit):
                fail(
                    f"Invalid numberField.unit in {path.relative_to(ROOT)}{location}: "
                    f"{unit!r}; use an attribute reference like volume.unit or omit it"
                )
        for key, value in obj.items():
            walk_for_units(value, path, f"{location}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            walk_for_units(value, path, f"{location}[{i}]")


for path in (ROOT / "custom-capabilities" / "presentations").glob("*.json"):
    obj = load_json(path)
    if obj:
        expected_id = f"{NAMESPACE}.{path.stem}"
        if obj.get("id") != expected_id:
            fail(f"Presentation {path.name} has id {obj.get('id')!r}, expected {expected_id!r}")
        walk_for_units(obj, path)

if errors:
    print("Static validation failed:", file=sys.stderr)
    for err in errors:
        print(f" - {err}", file=sys.stderr)
    raise SystemExit(1)

print("Static validation passed.")
