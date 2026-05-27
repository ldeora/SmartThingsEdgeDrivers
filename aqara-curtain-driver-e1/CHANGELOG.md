# Changelog

## GitHub-ready cleanup

- Renamed the repository directory to `aqara-curtain-driver-e1`.
- Rewrote the README as concise GitHub-facing documentation.
- Kept the driver focused on the Aqara Curtain Driver E1 (`LUMI / lumi.curtain.agl001`).
- Added a lightweight static validation script.
- Preserved runtime driver behavior.

## Driver scope

- Dedicated SmartThings Edge Driver for the Aqara Curtain Driver E1.
- Supports standard curtain control through SmartThings capabilities.
- Exposes battery, charging state, hook lock state and initialization state.
- Adds illuminance reporting from Aqara's manufacturer-specific private cluster `0xFCC0`, attribute `0x0429`, manufacturer code `0x115F`.

## Notes

This package is intentionally minimal. It is not a general-purpose Zigbee window-treatment driver and does not attempt to support unrelated Aqara curtain models.
