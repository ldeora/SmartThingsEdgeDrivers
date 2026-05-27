# LEDVANCE Plug EU EM Edge Driver

SmartThings Edge driver for the **LEDVANCE SMART+ Plug EU with energy metering**.

This driver is intended for the Zigbee 3.0 LEDVANCE indoor plug variants that expose standard On/Off, Simple Metering, and Electrical Measurement clusters.

## Supported devices

| Manufacturer | Model |
| --- | --- |
| `LEDVANCE` | `PLUG EU EM T` |
| `LEDVANCE` | `PLUG EU EM T, black` |

## Features

- Switch on/off control
- Power measurement in watts
- Energy measurement in kWh
- Voltage measurement in volts
- Current measurement in amps
- Refresh command
- Power-on behavior preference

## Power-on behavior

The driver exposes a preference for the Zigbee `StartUpOnOff` attribute:

| Preference | Meaning |
| --- | --- |
| `Off` | Device stays off after power is restored |
| `On` | Device turns on after power is restored |
| `Toggle` | Device toggles state after power is restored |
| `Previous` | Device restores the previous state |

The driver does **not** force a startup behavior during onboarding. It reads the device state first and only writes the preference when the user changes it.

## Driver design

This is a single-endpoint Zigbee driver. The supported device functions are handled on endpoint 1:

- On/Off cluster
- Simple Metering cluster
- Electrical Measurement cluster
- On/Off `StartUpOnOff` attribute for power-on behavior

The driver follows a standards-first approach and does not use manufacturer-specific LEDVANCE commands for normal operation.

## Repository structure

```text
ledvance-plug-eu-em/
├── config.yaml
├── fingerprints.yaml
├── profiles/
│   └── ledvance-plug-eu-em.yaml
├── src/
│   ├── init.lua
│   └── ledvance_plug_eu_em/
│       └── common.lua
└── scripts/
    └── validate_static.py
```

## Validation

Run the included static validator:

```bash
python3 scripts/validate_static.py
```

Package the driver with the SmartThings CLI:

```bash
smartthings edge:drivers:package .
```

For live hub testing:

```bash
smartthings edge:drivers:logcat -a
```

## Notes and limitations

- Reporting intervals are configured for switch state, energy, power, voltage, and current, but actual reporting behavior may still depend on device firmware.
- The standard Zigbee `onWithTimedOff` command is not surfaced in the SmartThings app because there is no stock SmartThings capability that maps cleanly to it in this driver-only package.
- Packaging success does not replace real hub testing with the actual device.

## Status

GitHub-ready cleanup of the existing working driver package. Runtime driver logic has not been changed during this cleanup pass.
