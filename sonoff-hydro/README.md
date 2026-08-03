# SONOFF Hydro SmartThings Edge Driver

Community SmartThings Edge Driver for the SONOFF Hydro Zigbee water-valve family:

- **Hydro ONE** — single outlet with flow meter
- **Hydro ONE Lite** — single outlet without flow meter
- **Hydro DUO** — two independently controlled outlets with a shared flow meter

The driver runs locally on a compatible SmartThings hub and combines standard Zigbee valve control with selected SONOFF/eWeLink private-cluster features.

> [!IMPORTANT]
> The current baseline is **v1.4.0-alpha29**. It has extensive static and mocked-runtime validation, but remains a supervised alpha while real-device validation continues—especially for the device-side watering limit and Hydro DUO.

## Supported devices

| Product | Zigbee model identifiers | Profile |
|---|---|---|
| SONOFF Hydro ONE | `SWV-ZFE`, `SWV-ZFU` | `sonoff-hydro-one` |
| SONOFF Hydro ONE Lite | `SWV-ZNE`, `SWV-ZNU` | `sonoff-hydro-one-lite` |
| SONOFF Hydro DUO | `SWV-ZF2`, `SWV-ZF2E`, `SWV-ZF2U` | `sonoff-hydro-duo` |

All fingerprints use Zigbee manufacturer `SONOFF`.

## Main features

- Standard SmartThings **Valve** Open/Close
- Standard **Switch** On/Off for compatibility with routines and voice control
- Battery level and Refresh
- Firmware-version display
- Driver-managed **Open valve for minutes** action
- Restart safety recovery for interrupted timed runs
- Device-side manual-watering limit synchronization
- Child lock
- Real-time and hourly irrigation duration
- Current and hourly volume on Hydro ONE and Hydro DUO
- Water-shortage, leakage, frost, and fail-safe states where supported
- Alarm and auto-close preferences on supported models
- Two SmartThings components for Hydro DUO:
  - `main` → Channel 1 / endpoint 1
  - `channel2` → Channel 2 / endpoint 2

## Reliability-first architecture

Ordinary Valve and Switch commands use the standard Zigbee On/Off cluster directly. They do not wait for, depend on, or verify a SONOFF private setting.

Private features—including the device-side watering limit—operate independently. A sleeping device, failed private read, or unsuccessful private write must not prevent normal Open or Close commands.

Custom timed watering also uses a standard Zigbee On command and schedules a driver-side Off through the SmartThings Edge timer API. If the driver or hub restarts during a timed run, the driver performs a safety recovery Close rather than trying to resume the remaining time.

## Device-side watering limit and the ten-minute issue

SONOFF Hydro valves may ship with a manual-watering limit of approximately ten minutes. A normal Zigbee On command can therefore be followed by a device-initiated Close even when SmartThings never sent Off.

Alpha29 synchronizes the 12-byte private attribute `0x501D` using a read-modify-write-verify sequence:

- both manual duration fields are updated;
- Hydro ONE and Hydro DUO also receive a matching fail-safe duration;
- Hydro ONE Lite preserves the separate fail-safe bytes because their semantics are not sufficiently proven;
- unrelated bytes are preserved;
- a fresh readback must confirm the requested values.

The selected SmartThings preference is a requested value, not proof that a sleepy device accepted it. Enable Debug logging and wait for a verification message before performing a long-run test.

> [!WARNING]
> The corrected alpha29 payload is implemented and covered by mocked tests, but the ten-minute issue must not be described as fully fixed until the selected model and firmware have passed a physically timed run.

## Feature differences

| Feature | Hydro ONE | Hydro ONE Lite | Hydro DUO |
|---|:---:|:---:|:---:|
| Controllable outlets | 1 | 1 | 2 |
| Flow meter | Yes | No | Shared |
| Current/hourly volume | Yes | No | Shared on `main` |
| Timed watering | Yes | Yes | Per channel |
| Device-side duration limit | Yes | Yes | Shared |
| Child lock | Yes | Yes | Shared |
| Water Sensor leakage mapping | Yes | No | Shared |
| Alarm preferences | Supported subset | No | Conservative subset |
| Private alerts | Yes | No | Aggregated/shared |

## Custom capabilities

The package uses custom capabilities in namespace `oceancircle09600`:

- `oceancircle09600.hydroTimedWatering`
- `oceancircle09600.hydroIrrigationStatus`
- `oceancircle09600.hydroLiteIrrigationStatus`
- `oceancircle09600.hydroValveAlerts`

The namespace is referenced in the Lua source, profiles, capability definitions, and presentations. Building under another namespace requires a complete and consistent migration; changing an environment variable alone is not sufficient.

## Installation

### Shared Driver Channel

Testers normally install the driver from a shared SmartThings Driver Channel:

1. Accept the channel invitation.
2. Enroll the target hub.
3. Install the driver from **Available Drivers**.
4. Pair the valve or switch an existing device to this driver.
5. Test ordinary Valve Open/Close before changing private preferences.

### Build from source

Requirements:

- compatible SmartThings hub;
- SmartThings CLI with Edge Driver commands;
- a Driver Channel;
- access to the SmartThings organization that owns namespace `oceancircle09600`, unless performing a complete namespace migration.

Create or update the custom capabilities:

```bash
smartthings organizations
SMARTTHINGS_ORGANIZATION_ID=<organization-id-for-oceancircle09600> \
  ./scripts/create_custom_capabilities.sh
```

Validate the package:

```bash
python3 scripts/validate_static.py
texlua scripts/check_lua_syntax.lua src/init.lua src/sonoff_utils.lua
texlua scripts/test_alpha29_runtime.lua
```

The Lua helpers may also work with another compatible Lua environment, but the included comments and current test setup use `texlua`.

Package the driver:

```bash
smartthings edge:drivers:package .
```

Package and install interactively:

```bash
smartthings edge:drivers:package . --install
```

## First test sequence

1. Enable **Debug logging** temporarily.
2. Test Valve Open and Close.
3. Test Switch On and Off.
4. Confirm immediate physical movement and no **Network Error**.
5. Test a short **Open valve for minutes** run.
6. Only then test child lock, alerts, alarm preferences, and the device-side watering limit.
7. For a limit test, obtain a verified `0x501D` readback before timing an ordinary Valve Open run.

The detailed hardware procedure is in [TESTING.md](TESTING.md).

## Logging

Start live Edge Driver logging before reproducing an issue:

```bash
smartthings edge:drivers:logcat --hub-address=<HUB_IP_ADDRESS>
```

Useful alpha29 messages include:

```text
standard On queued component=main
standard Off queued component=main
starting independent 0x501D synchronization target=20 reason=...
0x501D synchronization verified target=20 failSafe=20
```

A failed private synchronization should explicitly state that basic Open/Close is unaffected.

## Known limitations

- Complete alpha29 hardware validation is still pending.
- The app does not expose pending/verified/failed status for the device-side limit; logs are required.
- Hydro DUO requires additional two-channel hardware testing.
- DUO alerts are shared/aggregated rather than channel-specific.
- High-flow state on Hydro DUO is logged but not exposed as a capability.
- Flow-unit detection is stored, but custom volume capabilities currently display litres.
- Hourly telemetry does not yet use the adaptive byte-order handling used for current values.
- Private telemetry can be stale because the driver deliberately avoids configuring broad private reporting on a sleepy battery device.
- The custom timed-water command defines `stop`, but the presentation currently relies on standard Valve Close or Switch Off.
- Advanced irrigation schedules, rain delay, seasonal adjustment, history, and OTA firmware updates are not implemented.

See [TECHNICAL_DOCUMENTATION.md](TECHNICAL_DOCUMENTATION.md) for the complete limitations and confidence matrix.

## Project documentation

- [TECHNICAL_DOCUMENTATION.md](TECHNICAL_DOCUMENTATION.md) — complete architecture, protocol mapping, behavior, limitations, and source-code map
- [CODE_REVIEW.md](CODE_REVIEW.md) — alpha29 review and validation findings
- [TESTING.md](TESTING.md) — supervised hardware test plan
- [HYDRO_DUO.md](HYDRO_DUO.md) — two-channel implementation notes and test checklist

## Package structure

```text
sonoff-hydro/
├── config.yml
├── fingerprints.yml
├── README.md
├── TECHNICAL_DOCUMENTATION.md
├── CODE_REVIEW.md
├── TESTING.md
├── HYDRO_DUO.md
├── profiles/
├── custom-capabilities/
├── src/
└── scripts/
```

The repository directory is named `sonoff-hydro`. The SmartThings package key remains `sonoff-hydro-one` to preserve the established driver identity.

## Development policy

Future changes should preserve the reliability boundary:

- never gate standard On or Off on a private transaction;
- make one evidence-based private-cluster change at a time;
- preserve unknown bytes in packed values;
- add a regression test for each behavioral change;
- distinguish implementation confidence from real-device proof;
- prioritize reliable control and hardware validation before feature parity with other integrations.

## References

- [SmartThings Community discussion](https://community.smartthings.com/t/st-edge-sonoff-hydro-one-duo-family-swv-zfe-swv-zfu-swv-zne-swv-znu-swv-zf2e-swv-zf2u/309672)
- [SONOFF Hydro ONE](https://sonoff.tech/en-de/products/sonoff-hydro-series-hydro-one-zigbee-smart-water-valve-swv-zfu-swv-zfe)
- [SONOFF Hydro ONE Lite](https://sonoff.tech/en-de/products/sonoff-hydro-series-hydro-one-lite-zigbee-smart-water-valve-swv-znu-swv-zne)
- [SONOFF Hydro DUO](https://sonoff.tech/en-de/products/sonoff-hydro-duo-dual-channel-zigbee-smart-water-valve-swv-zf2e-swv-zf2u)
- [SONOFF/eWeLink enhanced ZHA announcement](https://forum.ewelink.cc/t/hydro-one-series-water-valves-now-updated-with-enhanced-zha-script-for-more-powerful-features/208644)
- [ZHA device-handler PR #4927](https://github.com/zigpy/zha-device-handlers/pull/4927)
- [SmartThings Edge Driver architecture](https://developer.smartthings.com/docs/devices/hub-connected/edge-architecture)
