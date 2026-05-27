# Changelog

## GitHub-ready cleanup

- Renamed the repository directory to `aqara-h2-wall-outlet`.
- Rewrote `README.md` as clean user-facing documentation.
- Moved historical review notes out of the README.
- Added a lightweight static validation script.
- Preserved the v12 driver logic.

## v12 review notes

- Bumped `current_config_version` to `12`.
- Added driver-side preference defaults for deterministic device state after fresh join, configure, and driver switch.
- The driver now actively writes the effective preference values on `added`, `doConfigure`, and `driverSwitched`, using the SmartThings preference value when present and a safe driver default otherwise.
- This is especially important for `chargingProtection = false`, because the physical outlet can otherwise keep an internal low-load auto-off setting and switch itself off after about 30 minutes with no load.
- `powerOnBehavior` is marked as required in the profile and still defaults to `previous`.
- Endpoint routing, switch control, metering, aggregate parsing, and confirmed working preference encodings were not changed.

## v11 parser hardening review

- Kept the confirmed v10 behavior.
- Hardened the Xiaomi/Aqara aggregate parser.
- Bumped `current_config_version` to `11`.
- Added support for additional fixed-size ZCL numeric types including semi-precision and double-precision floats.
- Skips unsupported fixed-size values without losing alignment.
- Suppresses bogus standard `TemperatureMeasurement` values when aggregate temperature is preferred.
- Keeps button lock working and treats `0 W` as a valid fresh outlet power reading.

## v10 final pre-test review

- Bumped `current_config_version` to `10`.
- Made the Xiaomi/Aqara aggregate parser skip/handle wider integer data types such as `0x27` instead of stopping early.
- Added safer current extraction from public plug-family aggregate tag candidates `0x97`/`0x95`, preferring the value closest to the `power / voltage` estimate when available.
- Kept SimpleMetering as the authoritative energy source.

## v9 measurement update

- Added a defensive parser for Xiaomi/Aqara aggregate attributes `0x00F7` and `0xFF01` on cluster `0xFCC0`.
- Intended to recover reported-only values such as device temperature, voltage, and current when standard reads are not usable.
- Emits device temperature from aggregate tag `0x03`.
- Emits voltage from aggregate tag `0x96`.
- Emits current from aggregate tag `0x97`.
- Emits power from aggregate tag `0x98` only if the preferred endpoint-21 `AnalogInput` power path is stale.
- Logs power outage count tag `0x05`, but does not emit it as a custom capability.

## v8 robustness build

- Kept confirmed working outlet control and metering logic from v7.
- Added a `driverSwitched` lifecycle handler for manual migration from a generic SmartThings driver.
- Bumped `current_config_version` to `8`.
- Reads OnOff state from endpoint 2 and endpoint 1 during refresh.
- Leaves endpoint 2 as the primary control endpoint.
- Keeps the endpoint-1 fallback command from v7.
- Does not change Aqara preference attributes, metering conversion, voltage/current conversion, or aggregate parsing behavior.

## v7 no-log tester recovery build

- Uses the official SmartThings Zigbee `OnOff.commands.server.On/Off(device)` command constructor.
- Sends outlet switch commands to endpoint 2 and a cautious fallback command to endpoint 1.
- Keeps all Aqara preference attributes and metering logic unchanged.

## v6 matching note

- Changed the fingerprint file to the current SmartThings `zigbeeManufacturer` / `zigbeeGeneric` structure.
- Keeps the exact Aqara and LUMI manufacturer/model fingerprints.
- Adds a non-joinable generic metering fallback so the driver can appear as a manual driver-change option if SmartThings does not match the manufacturer/model string exactly.
- No Lua logic, profile capabilities, endpoint routing, or preference attributes were changed.

## v5 note

- Fingerprint-only compatibility update for external testing.
- Adds an additional exact fingerprint for devices that report the manufacturer as `LUMI` instead of `Aqara` while keeping the same model string `lumi.plug.aeu001`.
- No Lua logic, endpoint routing, profile capabilities, preferences, or metering behavior were changed.

## v4 recommended external-test build

- Bumped `current_config_version` to `4`.
- Kept endpoint routing unchanged: endpoint 2 remains the controllable outlet switch.
- Kept endpoint 21 as the preferred `AnalogInput` power source.
- Kept Aqara aggregate attributes `0x00F7` and `0xFF01` as diagnostic logging only.
- Added clearer logs for outlet on/off commands and preference write/read-back cycles.
- Kept numeric preference bounds in the profile:
  - charging protection limit: `0.1–2 W`
  - overload protection: `100–3840 W`

## v2 review notes

- Fixed the Zigbee `SinglePrecisionFloat` encoder used for `chargingLimit` and `overloadProtection`.
- Added ConfigureReporting entries for voltage and current.
- Ignores bogus zero values from the standard `TemperatureMeasurement` cluster.
- Logs Xiaomi/Aqara aggregate attributes `0x00F7` and `0xFF01` for external tester diagnostics.
