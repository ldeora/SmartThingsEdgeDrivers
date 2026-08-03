# SONOFF Hydro DUO implementation notes

Hydro DUO uses two SmartThings components mapped to two Zigbee endpoints:

- `main` / Channel 1 -> endpoint 1
- `channel2` / Channel 2 -> endpoint 2

## Implemented

- Fingerprints for `SWV-ZF2`, `SWV-ZF2E`, and `SWV-ZF2U`
- Separate Valve, Switch, timed-watering, work-state, and duration controls for both channels
- Shared battery, firmware, child lock, device-side watering limit, volume, leakage, and alarm settings on the main component
- Standard On/Off per endpoint
- Best-effort opposite-channel Off before opening the requested channel
- Independent driver timers and restart-recovery flags per channel
- Shared `0x501D` synchronization on endpoint 1
- Device-wide current and hourly volume on the main component
- Corrected abnormal-state bitmap:
  - bit 0: water shortage Channel 1
  - bit 1: leakage
  - bit 2: fail-safe Channel 1
  - bit 3: water shortage Channel 2
  - bit 4: fail-safe Channel 2
  - bit 5: frost Channel 1
  - bit 6: frost Channel 2
  - bit 7: high flow
- Conservative `0x5020` preference subset: shortage alarm, leak alarm, shortage auto-close, shortage duration, and leak duration

The current shared SmartThings alert capability aggregates channel-specific shortage, frost, and fail-safe bits. High flow is decoded in debug logs but is not yet exposed as a separate capability.

## Alpha29 device-side limit

Hydro DUO uses one shared manual-default aggregate. Alpha29 sets and verifies:

- both manual duration fields;
- the shared fail-safe timeout;
- while preserving mode, interval, unit, amount, and other unrelated bytes.

This synchronization is independent of both channels' standard On/Off commands.

## Not implemented

- Full irrigation plans
- Cyclic quantitative irrigation plans
- Rain delay
- Seasonal watering adjustment
- History retrieval
- Per-channel volume counters, because volume is treated as device-wide
- DUO frost-alarm, frost-threshold, and leak-auto-close writes until hardware evidence confirms their `0x5020` semantics
- A separate high-flow SmartThings capability

## First hardware checklist

1. Confirm both components appear.
2. Test Channel 1 Open/Close.
3. Test Channel 2 Open/Close.
4. Confirm opening one channel queues Off to the other and then On to the requested channel.
5. Test a short timed run independently on each channel.
6. Set the shared device-side limit to 15 or 20 minutes and obtain a verified readback.
7. Measure an ordinary Open run beyond ten minutes on each channel.
8. Press Refresh and capture endpoint-specific duration/work-state reports plus shared volume, alert, `0x501D`, and `0x5020` responses.

## Especially useful logs

- Zigbee endpoint list during pairing
- OnOff reports from endpoints 1 and 2
- Source endpoint of private-cluster reports
- Original and verified `0x501D` bytes
- Default/write response status for `0x501D` and `0x5020`
- Any unsupported-attribute or unsupported-cluster response
