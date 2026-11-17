# CPU temperature automation range — isolated experiment (2026-11-17)

**Status:** Experimental branch only. Not published to the public driver channel, not installed on the reference hub, and not verified in the SmartThings mobile routine editor.

## Problem

The Linux Computer Host profile reports CPU temperature through the standard `temperatureMeasurement` capability. Its current driver already accepts CPU readings from -40 °C through +150 °C; however, the SmartThings app's routine editor may default to an input range of -20 °C to +50 °C, preventing a rule such as "above 60 °C".

The documented standard `temperatureMeasurement.temperatureRange` attribute can report a supported range to SmartThings. The stock SmartThings Zigbee humidity-sensor driver publishes the same attribute.

References:

- https://developer.smartthings.com/docs/devices/capabilities/capabilities-reference
- https://github.com/SmartThingsCommunity/SmartThingsEdgeDrivers/blob/main/drivers/SmartThings/zigbee-humidity-sensor/src/init.lua
- https://community.smartthings.com/t/temperaturemeasurement-capability-and-new-temperaturerange-attribute/289104

## Experimental behavior

- `computerhost.telemetry` emits `temperatureMeasurement.temperatureRange` with `{value={minimum=-40, maximum=150}, unit="C"}` **before** the first valid CPU temperature reading.
- The range event is sent only once per live driver runtime/device, but is retried if the capability event cannot be emitted. This is a transient runtime field, not a persisted or remotely changed preference.
- Windows devices (no CPU temperature) and telemetry without a valid temperature cannot emit the range event.
- The original CPU temperature event, deadband (0.5 °C), monitoring, power handling, discovery, HMAC, WOL, Linux/Windows agents, device profiles, protocol and release assets are **unchanged**.
- No account-level capability definitions or presentations are modified.

## Test gates before merge

1. PR CI: Python/Lua tests and Linux/Windows workflows pass. Confirm no baseline monitoring, discovery or power regression.
2. Use **only a private/test driver installation**, not the public channel or a production device. Preserve the currently published `v0.5.1-beta.1` driver as rollback reference.
3. On a Linux device reporting a real temperature, confirm the standard `temperatureRange` state appears with minimum `-40`, maximum `150`, unit `C`. Confirm ordinary temperature continues updating.
4. Restart SmartThings and edit a new routine. Check whether a temperature condition **above 60 °C** can be entered and saved. The app may cache the range from initial device installation. Do **not** delete/re-pair a production device just to test UI behavior.
5. Confirm routine history/telemetry are unaffected; condition is not silently clamped to 50 °C. Test app versions, if possible.
6. Confirm an offline/unavailable Linux temperature doesn't emit fabricated readings, and Windows devices continue to have no temperature capability.
7. If the app ignores the range on existing devices, retain this branch as an experiment. Investigate initial installation timing or a CPU-specific custom capability separately; do **not** modify shared standard-capability presentations without a compelling reason.

This change does **not** implement an automatic thermal shutdown. A routine that switches off a computer is user-created, sampled periodically and should not substitute for CPU/firmware thermal protection.
