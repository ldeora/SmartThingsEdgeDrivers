# Aqara Curtain Driver E1 Edge Driver

A minimal SmartThings Edge Driver for the **Aqara Curtain Driver E1** in Zigbee mode.

This driver is intentionally focused on one device:

- **Manufacturer:** `LUMI`
- **Model:** `lumi.curtain.agl001`
- **Device label:** Aqara Curtain Driver E1

It exists because the Curtain Driver E1 has useful device-specific behavior that is easier to maintain in a small, dedicated driver than in a broad, generic window-treatment package.

## Features

### Curtain control

- Open, close and pause/stop
- Set shade level from 0–100%
- Position reporting
- Open, closed and partially-open state updates
- Reverse curtain direction preference
- Soft touch preference

### Aqara-specific states

- Initialization state
- Hook lock state
- Charging state
- Battery reporting
- Refresh support
- Group cleanup during configuration

### Illuminance support

The Aqara Curtain Driver E1 includes a built-in light sensor. This driver exposes that value through the standard SmartThings `illuminanceMeasurement` capability.

The illuminance value is read from Aqara's manufacturer-specific Zigbee cluster:

| Item | Value |
|---|---:|
| Private cluster | `0xFCC0` |
| Attribute | `0x0429` |
| Manufacturer code | `0x115F` |

The reported value should be treated as the device's own light-level reading. It is useful for automation, but it is not a laboratory-grade lux meter.

## Why this driver exists

The stock SmartThings Zigbee window-treatment driver is a broad, multi-device package. That is useful for general compatibility, but it also means the code and profile structure need to support many different devices.

This driver takes the opposite approach:

- one device
- one fingerprint
- one profile
- one main Lua driver file
- no unrelated window-treatment devices
- no stock presentation binding that can hide added capabilities

The goal is to keep the Aqara Curtain Driver E1 easy to understand, test and maintain.

## Supported device

| Device | Manufacturer | Model |
|---|---|---|
| Aqara Curtain Driver E1 | `LUMI` | `lumi.curtain.agl001` |

This driver is not intended for other Aqara curtain models unless they use the same fingerprint and have been tested.

## Repository structure

```text
aqara-curtain-driver-e1/
├── config.yml
├── fingerprints.yml
├── profiles/
│   └── window-treatment-aqara-curtain-driver-e1.yml
├── src/
│   └── init.lua
├── scripts/
│   └── validate_static.py
├── CHANGELOG.md
└── README.md
```

## Installation

### Shared channel

If the driver is published through a SmartThings Edge Driver channel, install it from that channel and then pair or re-pair the device.

### Developer installation

From this directory:

```bash
smartthings edge:drivers:package .
```

Then install the packaged driver to your hub using the SmartThings CLI or your preferred SmartThings developer workflow.

## Validation

A small static validation helper is included:

```bash
python3 scripts/validate_static.py
```

This checks the expected package files, profile/fingerprint relationship and a few important driver constants. It does not replace real hub testing.

For live testing, use:

```bash
smartthings edge:drivers:logcat -a
```

## Pairing notes

If the device is already joined with another driver, exclude/remove it first and then pair it again after installing this driver.

After pairing, give the device time to complete initialization and configuration. Aqara devices can be sensitive to incomplete configuration or missed manufacturer-specific reads.

## Known limitations

- This is a dedicated driver for `LUMI / lumi.curtain.agl001`.
- Other Aqara curtain models are not covered unless explicitly tested.
- Illuminance handling uses Aqara manufacturer-specific data.
- SmartThings App UI behavior depends on the profile and generated presentation.
- Real-device testing is still required after packaging.

## Credits

This driver builds on practical testing, SmartThings Edge Driver experience, and public information from the Zigbee ecosystem around the Aqara Curtain Driver E1.

## Disclaimer

This is a community driver. Use it at your own risk. It is not an official Aqara or Samsung SmartThings product.
