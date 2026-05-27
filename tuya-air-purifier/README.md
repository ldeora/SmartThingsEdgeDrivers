# Tuya Air Purifier Local Edge Driver

SmartThings Edge Driver for Tuya / Smart Life Wi-Fi air purifiers that expose a compatible Tuya v3.3 local LAN DPS interface.

This driver is intentionally generic. It is not tied to one retail brand name. It was developed from a Tuya white-label air purifier implementation and is intended for devices that use the same local Tuya DPS mapping.

## What this driver provides

- Local LAN control via the Tuya v3.3 TCP protocol on port `6668`
- SmartThings device label: **Air Purifier**
- Main on/off control
- Air purifier fan mode: `auto`, `high`, `sleep`, `off`
- PM2.5 reporting via `fineDustSensor`
- Air quality health concern reporting via `airQualityHealthConcern`
- Filter life reporting and filter reset via `filterState`
- Separate ionizer switch component
- Separate UV switch component
- Display light control: `off`, `soft`, `standard`
- Timer control: `off`, `2 hours`, `4 hours`
- Timer remaining state in minutes
- Scheduled polling
- Async/optimistic command handling with Tuya verification
- TCP-based IP rediscovery after repeated LAN failures
- Optional verbose Tuya packet logging for debugging

## Compatibility

This is a local Tuya LAN driver, not a cloud integration and not a universal Tuya driver.

The device must support the Tuya v3.3 local protocol and must use the same DPS mapping expected by this driver. The driver was originally tested with a Tuya white-label air purifier sold as the KLAMER 500i, but the repo/package naming is generic because the underlying device is not KLAMER-specific.

If another air purifier uses a different DPS map, it may need a dedicated variant or an extended mapping layer.

## Driver identity

```yaml
name: Tuya Air Purifier Local
packageKey: tuya-air-purifier
profile: tuya-air-purifier
label: Air Purifier
manufacturer: Tuya
model: Air Purifier v3.3
```

The internal device network ID is intentionally kept stable as `tuya-air-purifier-local` for continuity with earlier local builds.

## Custom capabilities

The driver uses two custom capabilities in the `oceancircle09600` namespace:

```text
oceancircle09600.airPurifierDisplayLight
oceancircle09600.airPurifierTimer
```

The capability and presentation definitions are included in:

```text
capabilities/
presentations/
```

Create or update them before packaging/installing the driver:

```bash
./scripts/create-custom-capabilities.sh
```

The driver is currently wired to the `oceancircle09600` namespace in the profile and Lua code. If you fork this driver for a different namespace, update the profile, Lua capability references, capability creation script, and validation script together. Changing only the capability creation namespace is not enough.

If the capabilities already exist, the create step may return a non-zero result. That is usually fine. The important part is that the presentation creation succeeds.

## Required device information

You need the following values from the Tuya / Smart Life device:

- Device IP address or hostname
- Tuya Device ID
- Tuya Local Key

TinyTuya can be used to retrieve the Device ID and Local Key from a Tuya / Smart Life account.

## Recommended network setup

Use a DHCP reservation for the air purifier. The driver includes conservative TCP-based IP rediscovery, but rediscovery is a recovery fallback, not a replacement for stable addressing.

The driver only probes TCP port `6668` and only after repeated communication failures.

## Preferences

The SmartThings device exposes these preferences:

| Preference | Purpose |
|---|---|
| Host / IP address | Static or reserved LAN IP address of the air purifier |
| Device ID | Tuya Device ID |
| Local key | Tuya local key |
| Poll interval seconds | Scheduled refresh interval; 15–30 seconds is usually reasonable |
| Auto rediscover IP | Probe the same `/24` subnet after repeated host failures |
| Verbose Tuya packet logging | Log raw Tuya JSON send/receive packets for debugging |

Verbose Tuya packet logging should stay disabled for normal use.

## Packaging

From the driver directory:

```bash
smartthings edge:drivers:package .
```

Optionally install during packaging:

```bash
smartthings edge:drivers:package . --install
```

## Validation

A small static validation helper is included:

```bash
python3 scripts/validate_static.py
```

This does not replace real hub testing. It only checks obvious repo/package consistency issues.

For runtime testing, use SmartThings Edge logcat:

```bash
smartthings edge:drivers:logcat -a
```

## Troubleshooting

Useful log lines include:

```text
Air purifier command ingress seq=N queued for async Tuya verification: ...
Air purifier command handler returning immediately seq=N: ...
Air purifier async Tuya verification start seq=N: ...
Air purifier command complete seq=N: ...
Air purifier async Tuya verification complete seq=N: ...
```

If the SmartThings app shows a spinner or network error but the log shows no `Received event with handler capability`, the command did not reach this Edge driver.

If the command reaches the driver, the handler returns quickly and Tuya verification continues asynchronously.

## Release notes

See [`CHANGELOG.md`](CHANGELOG.md).
