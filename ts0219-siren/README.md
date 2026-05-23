# TS0219 Siren SmartThings Edge Driver

SmartThings Edge Driver for TS0219-based Zigbee sirens.

This driver currently targets exact, known TS0219 fingerprints instead of using broad generic Tuya matching. It is based on the tested Woox R7051 control path and adds experimental support for the Immax NEO 07504L TS0219 variant.

## Supported devices

| Device | Manufacturer | Model | Status |
|---|---|---|---|
| Woox R7051 Smart Indoor Siren | `_TYZB01_ynsiasng` | `TS0219` | Tested / stable |
| Immax NEO 07504L Smart Siren | `_TYZB01_b6eaxdlh` | `TS0219` | Experimental beta |

The driver does **not** use a wildcard `_TYZB01_*` fingerprint. Additional TS0219 sirens should be added only after checking logs and confirming that their IAS WD behavior matches this driver.

## Features

### Standard SmartThings capabilities

- `alarm`
- `switch`
- `battery`
- `powerSource`
- `audioVolume`
- `refresh`

### Custom capabilities

The driver uses custom capabilities in the `oceancircle09600` namespace:

| Capability | Purpose |
|---|---|
| `oceancircle09600.sirenVolume` | Siren volume, 0-100 |
| `oceancircle09600.alarmDuration` | Alarm duration, 0-3600 seconds |
| `oceancircle09600.sirenLevel` | IAS WD siren level: low, medium, high, very_high |
| `oceancircle09600.strobe` | Request strobe during alarm |
| `oceancircle09600.strobeLevel` | IAS WD strobe level |
| `oceancircle09600.strobeDutyCycle` | IAS WD strobe duty cycle, 0-10 |
| `oceancircle09600.ledBrightness` | Experimental LED/strobe brightness attribute, 0-100 |
| `oceancircle09600.batteryVoltage` | Battery voltage in mV |
| `oceancircle09600.acConnected` | USB/AC power state derived from Basic `PowerSource` |

## Zigbee behavior

The primary control path is the Zigbee IAS Warning Device cluster:

- IAS Warning Device cluster `0x0502` / `StartWarning` for alarm control
- IAS Zone cluster `0x0500` / `ZoneStatus` and `ZoneStatusChangeNotification` for alarm feedback
- Power Configuration cluster `0x0001` for battery percentage and voltage
- Basic cluster `0x0000` / `PowerSource` for mains/battery state

The driver also reads and, when enabled, writes observed TS0219 IAS WD attributes:

| Attribute | Use |
|---|---|
| `0x0000` | MaxDuration / duration, Uint16 |
| `0x0001` | LED brightness / strobe intensity, Uint8, experimental |
| `0x0002` | Siren volume, Uint8 |
| `0x0003` | Observed diagnostic field, read-only/internal |

Some TS0219 firmware variants ignore parts of the IAS WD control surface. Volume, strobe, strobe level, strobe duty cycle, and LED brightness should therefore be treated as best-effort features outside the tested Woox R7051 baseline.

## Installation

Create or update the custom capabilities first:

```bash
./scripts/create_custom_capabilities.sh
```

If your SmartThings CLI default organization is not the organization that owns the `oceancircle09600` namespace, run:

```bash
smartthings organizations
SMARTTHINGS_ORGANIZATION_ID=<organization-id-for-oceancircle09600> ./scripts/create_custom_capabilities.sh
```

Then package the driver:

```bash
smartthings edge:drivers:package .
```

Install it through the SmartThings CLI or use the generated package in your normal Edge Driver channel workflow.

## Testing checklist

After pairing or switching the device to this driver, verify the following with live logs:

```bash
smartthings edge:drivers:logcat -a
```

Recommended checks:

1. Pair the siren and confirm that the correct exact fingerprint is selected.
2. Press Refresh and verify reads from PowerConfiguration, Basic, IAS Zone, and IAS WD.
3. Test `alarm.both`, `alarm.siren`, and `alarm.off`.
4. Test `switch.on` and `switch.off`.
5. Change the siren volume.
6. Change the alarm duration and verify whether the siren honors it.
7. Test siren level, strobe, strobe level, duty cycle, and LED brightness.
8. Unplug and reconnect USB power and verify `powerSource` and `oceancircle09600.acConnected`.
9. Wait for battery and battery-voltage reports; this device family can update slowly.

For the experimental Immax fingerprint, please capture logcat output for pairing, refresh, alarm on/off, switch on/off, duration changes, volume changes, LED brightness changes, USB power unplug/replug, battery reporting, and voltage reporting.

## Static validation

A small local validation helper is included:

```bash
python3 scripts/validate_static.py
```

This does not replace `smartthings edge:drivers:package .`, but it catches common local mistakes such as invalid JSON/YAML, missing custom capability definitions, missing presentations, profile/fingerprint mismatches, invalid preference names, and invalid presentation unit references.

## Notes for maintainers

- The package key is `ts0219-siren`.
- The embedded profile name is `ts0219Siren`, because SmartThings embedded profile names must follow the required naming pattern.
- The internal preference key `writeWooxAttrs` is intentionally preserved for compatibility with the known-good Woox-tested logic, even though the user-facing title and description are generic.
- The driver disables default ZCL responses for selected IAS WD commands/writes because the Woox R7051/TS0219 behaves more reliably that way.
- The driver emits optimistic command-side events immediately, but IAS Zone confirmations are still emitted separately so the SmartThings UI receives real device feedback.

## Release state

This repository version corresponds to the v12-beta4 driver line:

- Generic package and driver name: `TS0219 Siren`
- Generic package key: `ts0219-siren`
- Generic embedded profile name: `ts0219Siren`
- Stable tested Woox R7051 behavior retained
- Experimental Immax NEO 07504L exact fingerprint added
- v12-beta4 fix: restored the internal `writeWooxAttrs` preference key while keeping the visible preference text generic
