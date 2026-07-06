# Namron Panel Heater Edge Driver

Community SmartThings Edge Driver for **Namron 540139X Zigbee panel heaters**.

This driver adds thermostat and metering support for Namron Zigbee panel heaters that may otherwise pair as a generic power or metering device in SmartThings.

## Supported devices

The driver includes fingerprints for the following Namron panel heater models:

| Model | Variant |
|---|---|
| `5401392` | 400 W white |
| `5401393` | 600 W white |
| `5401394` | 800 W white |
| `5401395` | 1000 W white |
| `5401396` | 400 W black |
| `5401397` | 600 W black |
| `5401398` | 800 W black |
| `5401399` | 1000 W black |

Primary manufacturer fingerprint:

```text
NAMRON AS
```

A fallback `Namron` manufacturer spelling is also included for the same model numbers.

## Features

- Thermostat mode: `off` / `heat`
- Switch on/off mapped to thermostat heat/off
- Heating setpoint control from 5 °C to 35 °C
- Local temperature reporting
- Thermostat operating state reporting
- Power, energy, voltage and current reporting
- Open-window state exposed as `contactSensor`
- Device preferences for:
  - local temperature calibration
  - child lock
  - hysteresis
  - display brightness
  - display auto-off
  - power-up behavior
  - built-in window detection
  - debug logging

## Important notes

The open-window state is exposed as SmartThings `contactSensor`, but it does **not** represent a separate physical contact sensor. It reflects the heater's internal open-window detection state when the device reports it.

The proprietary Namron/Sunricher settings are implemented as manufacturer-specific attributes on Zigbee Thermostat cluster `0x0201` with manufacturer code `0x1224`.

This driver intentionally does not implement the heater's local weekly schedule / auto-program feature. That behavior should only be added if real-device reports confirm the exact attribute layout and command behavior.

## Installation

1. Install the driver package to your SmartThings Edge Driver channel.
2. Install the driver on your hub.
3. Remove the heater from SmartThings if it was previously paired as a generic meter or power device.
4. Factory-reset or pairing-reset the heater.
5. Pair it again with SmartThings.
6. Confirm that it joins with the **Namron Panel Heater** driver.

## Validation

A small static validation helper is included:

```bash
python3 scripts/validate_static.py
```

Package the driver with the SmartThings CLI:

```bash
smartthings edge:drivers:package .
```

For live debugging on a hub:

```bash
smartthings edge:drivers:logcat -a
```

## Test checklist

After pairing the heater, verify:

1. The device uses this driver and no longer joins as a generic meter.
2. Refresh updates temperature, setpoint, mode and electrical values.
3. Thermostat mode can be changed between `off` and `heat`.
4. Switch on/off mirrors the thermostat mode.
5. Heating setpoints such as 19.0 °C, 20.5 °C and 21.0 °C are accepted.
6. Power rises while the heater is actively heating.
7. Preferences can be changed one at a time and survive refresh/readback.
8. Open-window detection changes the contact state if the heater reports it.

Useful log terms while testing:

```text
NAMRON
5401399
0x0201
0x1224
Unsupported Attribute
Malformed Command
ConfigureReporting
```

## Repository contents

```text
config.yml
fingerprints.yml
profiles/namron-panel-heater.yml
src/init.lua
scripts/validate_static.py
README.md
```

## Status

Community driver. Tested behavior depends on the exact device firmware and SmartThings hub firmware.
