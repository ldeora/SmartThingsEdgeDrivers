# Aqara H2 Wall Outlet SmartThings Edge Driver

Dedicated SmartThings Zigbee Edge Driver for the **Aqara H2 Wall Outlet**.

This driver is intended for the EU wall outlet variant with Zigbee model `lumi.plug.aeu001`. It exposes the outlet as a locally controlled SmartThings plug with metering, electrical measurements, refresh, health check, and several Aqara-specific device preferences.

## Supported device

| Device | Retail model | Zigbee model | Known manufacturer strings |
|---|---:|---|---|
| Aqara H2 Wall Outlet EU | `WP-P01D` | `lumi.plug.aeu001` | `Aqara`, `LUMI` |

The driver also includes a conservative non-joinable generic fallback fingerprint so it can appear as a manual driver-change option for compatible metering outlet devices if the exact manufacturer string is not matched.

## Features

- Local Zigbee control through a SmartThings hub
- On/off control for the outlet relay
- Power reporting
- Energy reporting
- Voltage reporting
- Current reporting
- Device temperature reporting when usable data is available
- Manual refresh
- Health check capability
- Aqara manufacturer-specific preferences
- Defensive parser for Xiaomi/Aqara aggregate attributes on cluster `0xFCC0`

## SmartThings capabilities

The main component exposes:

- `switch`
- `powerMeter`
- `energyMeter`
- `voltageMeasurement`
- `currentMeasurement`
- `temperatureMeasurement`
- `refresh`
- `healthCheck`

## Device preferences

The driver exposes the following Aqara-specific settings as SmartThings device preferences:

- LED indicator
- Power-on behavior
- Button lock
- Charging protection
- Charging protection limit
- Overload protection

The driver also applies safe driver-side defaults after a fresh join, configure, or driver switch. This is especially important for charging protection, because some devices may otherwise keep an internal low-load auto-off setting.

## Endpoint assumptions

Based on public diagnostics for `lumi.plug.aeu001`, the driver uses this endpoint layout:

| Endpoint | Purpose |
|---:|---|
| 1 | Metering, electrical measurement, temperature cluster, Aqara manufacturer cluster `0xFCC0` |
| 2 | Primary controllable outlet relay via `OnOff` |
| 21 | Preferred `AnalogInput` power-reporting path |

The driver keeps endpoint 2 as the primary control endpoint and sends a cautious fallback command to endpoint 1 because public diagnostics show `OnOff` on both endpoints.

## Known limitations

- The driver is specific to the Aqara H2 Wall Outlet EU / `lumi.plug.aeu001` family.
- Some values are recovered from Xiaomi/Aqara aggregate attributes only when the device reports usable data.
- The driver intentionally ignores bogus standard `0 °C` temperature reports.
- `power_outage_count` may be logged from aggregate payloads, but is not exposed as a SmartThings capability.
- Real hub/device testing remains the final authority for endpoint behavior and firmware-specific quirks.

## Installation and testing

Package the driver with the SmartThings CLI from inside the driver directory:

```bash
smartthings edge:drivers:package .
```

After installing the driver on your hub, pair the device or switch the device to this driver in the SmartThings app if it appears as a compatible driver.

For debugging, use:

```bash
smartthings edge:drivers:logcat -a
```

Recommended checks:

1. Pairing and first configure.
2. Turn the outlet on and off from SmartThings.
3. Confirm that endpoint 2 controls the real outlet relay.
4. Change every preference once.
5. Connect a load and verify power, energy, voltage, and current reporting.
6. Check logs for Aqara aggregate reports on `0x00F7` or `0xFF01`.
7. Watch whether device temperature is recovered from real aggregate data instead of bogus standard `0 °C` reports.

## Repository notes

This repository version keeps the driver logic from the reviewed v12 build and only cleans up naming/documentation for GitHub publication. See `CHANGELOG.md` for the historical review notes.
