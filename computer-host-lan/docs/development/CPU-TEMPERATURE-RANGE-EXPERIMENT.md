# CPU temperature automation range — isolated experiment (2026-11-17)

**Status (2026-11-17):** Merged in PR #9. The owner packaged and installed the updated Edge Driver on the Gentoo/SmartThings reference installation and **successfully created and saved routines with multiple CPU-temperature thresholds above 60 °C**. This validates mobile routine-editor acceptance on that installation; it does not prove that an above-threshold routine has actually fired or that other app/hub versions behave identically. The original v0.5.1-beta.1 release assets remain unchanged.

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

## Original test gates and results

1. **PASSED (CI):** Python/Lua tests and Linux/Windows workflows passed in PR #9. No intended changes to baseline monitoring, discovery or power.
2. **Compatibility note:** The owner installed the updated driver on the reference hub. Preserve the published `v0.5.1-beta.1` release as a rollback reference; a GitHub merge itself does not distribute an Edge Driver to all hubs.
3. **NOT EXPLICITLY REPORTED:** Confirm the standard `temperatureRange` state appears with minimum `-40`, maximum `150`, unit `C`; independently verify ordinary temperature updates.
4. **PASSED (owner hardware and mobile app):** Multiple temperature conditions **above 60 °C** could be entered and saved in SmartThings routines on the existing installation. No device deletion/re-pair was required.
5. **PARTIAL:** The routine editor accepted thresholds above 60 °C rather than enforcing the former 50 °C limit. Actual routine firing, telemetry/event-history regression and different app versions remain to be checked.
6. **CI only; hardware not explicitly retested:** Ensure an unavailable CPU-temperature value emits no fabricated range/readings and Windows devices retain no CPU-temperature capability.
7. **Not needed on the reference hub:** The app accepted the range on the existing device. Do not modify account-level standard-capability presentations.

This change does **not** implement an automatic thermal shutdown. A routine that switches off a computer is user-created, sampled periodically and should not substitute for CPU/firmware thermal protection.

## Outcome and next workstream

The temperature routine UI limitation is resolved on the owner's installed Linux/SmartThings combination. Keep the change as-is and avoid expanding the temperature feature before the next stable release. Windows interactive session locking is a separate optional research track and must not modify the published power-control path before hardware validation.
