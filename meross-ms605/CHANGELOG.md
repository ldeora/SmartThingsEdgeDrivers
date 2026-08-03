# Changelog

## 0.1.0-alpha4

- Added delayed UI-only `Not present` initialization for presence components with no platform state.
- Kept synthetic defaults separate from genuine Matter zone states and aggregate-presence calculation.
- Added one merged initial read for all occupancy zones, illuminance, and battery.
- Added persistent markers that distinguish genuinely reporting zones from synthetic defaults and support safe restart recovery.
- Added migration handling for states created by alpha3.
- Separated general endpoint routing from valid Occupancy endpoint validation.
- Added focused debug logging for Occupancy reports, refresh requests, and synthetic initialization.
- Retained `PresenceSensor` categories on all profile components.

## 0.1.0-alpha3

- Fixed aggregate presence when one or more zones have never reported.
- Calculated main presence only from zones with a known genuine state.
- Kept aggregate presence unknown until the first genuine Occupancy report.

## 0.1.0-alpha2

- Audited the dedicated implementation against established SmartThings Matter sensor patterns.
- Restored the standard `firmwareUpdate` capability.
- Moved frequently changing zone states to runtime-only fields.
- Suppressed duplicate aggregate-presence events.
- Combined refresh reads into one Matter Interaction Model request.
- Separated profile and provisioning metadata updates.
- Avoided a redundant second Matter subscription during `doConfigure`.

## 0.1.0-alpha1

- Initial dedicated driver for Meross MS605 (`0x1345/0x4202`).
- Added three independent Occupancy Sensor endpoints.
- Added aggregate presence on the main component.
- Added illuminance, battery, and manual refresh support.
