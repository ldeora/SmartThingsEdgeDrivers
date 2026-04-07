# Aqara H2 Wall Switches for SmartThings

SmartThings Edge driver for the **Aqara H2 Wall Switch** family in **Zigbee mode**.

This driver currently targets the following Zigbee models:

- `lumi.switch.agl009` — Aqara H2 **EU 1CH** (`WS-K07E`)
- `lumi.switch.agl010` — Aqara H2 **EU 2CH** (`WS-K08E`, `WS-K08D`)
- `lumi.switch.agl004` — Aqara H2 **US 1CH** (`WS-K02E`)
- `lumi.switch.agl005` — Aqara H2 **US 2CH** (`WS-K03E`)

## Highlights

- Parent + child device architecture
- Relay control via dedicated child switch devices
- Button handling on the parent device
- Power and energy reporting
- Aqara-specific preferences such as operation mode, power-on behavior, relay lock, LED indicator, and multi-click where applicable
- Support for both **EU** and **US** Zigbee H2 variants

## Supported models

| Region | Retail model | Zigbee model | Channels | Parent button layout | Child relays |
|---|---|---|---:|---|---:|
| EU | WS-K07E | `lumi.switch.agl009` | 1 | `main`, `up`, `down` | 1 |
| EU | WS-K08E / WS-K08D | `lumi.switch.agl010` | 2 | `main`, `left`, `right`, `leftDown`, `rightDown` | 2 |
| US | WS-K02E | `lumi.switch.agl004` | 1 | `main`, `top`, `bottom` | 1 |
| US | WS-K03E | `lumi.switch.agl005` | 2 | `main`, `top`, `bottom` | 2 |

## Button behavior currently modeled

The current driver metadata exposes the following button values in SmartThings:

| Model | Upper / main relay-backed buttons | Lower / secondary buttons | Aggregate `main` |
|---|---|---|---|
| `agl009` | `up`: `pushed` | `down`: `pushed`, `double`, `held` | `pushed`, `double`, `held` |
| `agl010` | `left` / `right`: `pushed` | `leftDown` / `rightDown`: `pushed`, `double`, `held` | `pushed`, `double`, `held` |
| `agl004` | `top`: `pushed`, `double`, `held` | `bottom`: `pushed`, `double`, `held` | `pushed`, `double`, `held` |
| `agl005` | `top`: `pushed`, `double`, `held` | `bottom`: `pushed`, `double`, `held` | `pushed`, `double`, `held` |

## Preferences by model

### Shared preferences

All parent profiles expose these core Aqara settings:

- LED indicator
- Flip LED
- Power-on mode

### EU 1CH — `agl009`

- Up mode
- Lock up relay
- Down multi-click

### EU 2CH — `agl010`

- Left mode
- Right mode
- Lock left relay
- Lock right relay
- Left-down multi-click
- Right-down multi-click

### US 1CH — `agl004`

- Top mode
- Lock top relay
- Bottom multi-click

### US 2CH — `agl005`

- Top mode
- Bottom mode
- Lock top relay
- Lock bottom relay

## Device architecture

This driver uses a **parent + child** layout.

### Parent device

The parent device is responsible for:

- button events
- preferences
- aggregate power reporting
- aggregate energy reporting
- refresh

### Child devices

Each real relay is exposed as its own child device with:

- `switch`
- `refresh`
- `healthCheck`

This keeps the SmartThings UI clean and makes automations easier to build.

## Zigbee details

The current driver uses the following key Zigbee clusters and Aqara-specific attributes:

### Standard clusters

- `0x0006` — On/Off
- `0x0012` — Multistate Input
- `0x000C` — Analog Input
- `0x0702` — Simple Metering
- `0x0B04` — Electrical Measurement

### Aqara manufacturer-specific cluster

- `0xFCC0` — Aqara / Opple-style vendor cluster
- manufacturer code: `0x115F`

### Important Aqara attributes currently handled

- `0x0200` — operation mode
- `0x0203` — LED indicator
- `0x00F0` — flip LED indicator
- `0x0285` — relay lock
- `0x0286` — multi-click
- `0x0517` — power-on mode

## Installation

### SmartThings channel install

Install the driver from the SmartThings invitation link:

<https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20>

Then enroll the target hub and install **Aqara H2 Wall Switches (EU/US - 1CH/2CH)**.

### Important

This driver is for the **Zigbee mode** of the Aqara H2 switches.

If the device is paired in **Matter / Thread** mode, SmartThings will not use this Zigbee Edge driver. Remove the Matter device first if necessary, then re-pair the switch in Zigbee mode.

## Repository structure

```text
AQARA-H2-WALL-SWITCHES/
├── config.yaml
├── fingerprints.yaml
├── profiles/
│   ├── aqara-h2-1ch.yaml
│   ├── aqara-h2-2ch.yaml
│   ├── aqara-h2-us-1ch.yaml
│   ├── aqara-h2-us-2ch.yaml
│   └── aqara-h2-relay-child.yaml
└── src/
    ├── init.lua
    └── aqara_h2/
        └── common.lua
```

## Notes

- EU models have been validated more thoroughly than the US models.
- US support is present in the current baseline, but may still benefit from additional hardware-side validation.
- The driver intentionally focuses on **practical SmartThings support**, not full parity with every attribute public Zigbee integrations may expose.

