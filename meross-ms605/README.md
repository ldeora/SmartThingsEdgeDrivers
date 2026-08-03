# Meross MS605 SmartThings Edge Driver

A dedicated SmartThings Matter Edge Driver for the Meross MS605 Matter-over-Thread multi-zone presence sensor.

The driver exposes the sensor's three occupancy zones as separate SmartThings components and combines genuinely reporting zone states into an aggregate presence state on the main component.

> **Development status:** Alpha. Core behavior is implemented and statically validated, but the physical mapping between Meross Zone 1/2/3 and Matter endpoints 2/3/4 still requires final confirmation on production hardware.

## Supported device

| Property | Value |
|---|---|
| Manufacturer | Meross |
| Model | MS605 |
| Matter Vendor ID | `0x1345` / `4933` |
| Matter Product ID | `0x4202` / `16898` |
| Connectivity | Matter over Thread |
| Device profile | `meross-ms605` |

No other devices are fingerprinted by this package.

## Features

- Aggregate presence on the main component
- Three independently displayed presence zones
- Illuminance measurement
- Battery percentage
- Firmware version/status through the standard SmartThings capability
- Manual refresh
- Local execution on a compatible SmartThings hub
- Delayed initialization of silent zone components to prevent permanent spinners in the SmartThings app

The driver uses only standard SmartThings capabilities. No custom capabilities need to be created.

## Components and Matter endpoints

| SmartThings component | Function | Matter endpoint |
|---|---|---:|
| `main` | Aggregate presence, illuminance, battery, firmware, refresh | 1 for illuminance and battery; aggregate presence is calculated by the driver |
| `zone1` | Presence zone | 2 |
| `zone2` | Presence zone | 3 |
| `zone3` | Presence zone | 4 |

The endpoint order is based on the device's observed Matter structure. The physical Meross Zone 1/2/3 ordering still needs final confirmation on production hardware.

## Presence handling

### Genuine zone states

Occupancy reports from endpoints 2, 3, and 4 update `zone1`, `zone2`, and `zone3`. The main component is calculated as the logical OR of zones that have supplied a genuine Matter report:

- if any known zone is occupied, `main` is `Present`;
- if all known zones are clear, `main` is `Not present`;
- zones that have never reported are ignored.

This prevents an unconfigured or silent zone from keeping aggregate presence stuck at `Present`.

### Silent-zone initialization

Some MS605 occupancy endpoints may remain silent until their corresponding outputs are configured in the Meross app. Without a visible initial state, SmartThings can show a spinner or warn that not all status information has been received.

After initialization, the driver:

1. installs endpoint mapping and Matter subscriptions;
2. sends one merged read for all occupancy zones, illuminance, and battery;
3. waits five seconds for genuine reports;
4. initializes any component that still has no state to `Not present` with `state_change = false`.

These synthetic defaults are UI-only. They do not count as genuine reports and do not participate in aggregate presence. A later real Matter report replaces the visible default normally.

## Sleepy-device behavior

The MS605 is a sleepy Matter-over-Thread device. The driver primarily relies on Matter subscriptions and combines refresh attributes into one Interaction Model request. Responses can still be delayed until the sensor wakes.

Configure all intended zones in the Meross app before evaluating SmartThings behavior. A visible `Not present` value does not prove that an endpoint has supplied a genuine report.

## Installation and validation

### Requirements

- Compatible SmartThings hub with Matter and Thread support
- SmartThings CLI with Edge Driver commands
- A SmartThings Driver Channel for installation

### Validate the source

From the driver directory:

```bash
python3 scripts/validate_static.py
texlua scripts/check_lua_syntax.lua src/init.lua
```

### Package the driver

```bash
smartthings edge:drivers:package .
```

To package and install interactively:

```bash
smartthings edge:drivers:package . --install
```

### View logs

```bash
smartthings edge:drivers:logcat -a
```

## Initial test checklist

1. Confirm that the device is assigned the `meross-ms605` profile.
2. Confirm that `main`, `zone1`, `zone2`, and `zone3` appear.
3. Trigger movement separately in each configured physical zone.
4. Verify the corresponding SmartThings component and note the endpoint shown in logs.
5. Confirm that `main` becomes present when any genuinely reporting zone is occupied.
6. Confirm that `main` clears when all known zones clear.
7. Verify illuminance and battery reporting.
8. Restart the driver or hub and verify state recovery.

A more focused checklist is available in [`TESTING.md`](TESTING.md).

## Known limitations

- The physical Meross zone-to-endpoint order still requires final hardware confirmation.
- Silent or unconfigured zones receive a UI-only `Not present` default after five seconds.
- Synthetic defaults do not prove that the corresponding endpoint is configured or reporting.
- Matter ICD sleep behavior can delay reads and reports.
- The driver is dedicated to one vendor/product fingerprint and is not intended as a generic Matter presence-sensor driver.

## Project structure

```text
meross-ms605/
├── config.yml
├── fingerprints.yml
├── profiles/
│   └── meross-ms605.yml
├── src/
│   └── init.lua
├── scripts/
│   ├── check_lua_syntax.lua
│   └── validate_static.py
├── TESTING.md
├── CHANGELOG.md
├── LICENSE
└── README.md
```

## License

Licensed under the Apache License 2.0. See [`LICENSE`](LICENSE).
