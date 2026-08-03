# Meross MS605 hardware test checklist

Record the SmartThings hub model/firmware, MS605 firmware, driver version, and a complete logcat capture for each test.

## 1. Pairing and profile

- Pair or switch the MS605 to this driver.
- Confirm the `meross-ms605` profile is selected.
- Confirm four components appear: `main`, `zone1`, `zone2`, and `zone3`.
- Confirm no driver exception occurs during initialization or subscription.

## 2. Initial state handling

- Start logcat before initializing the device.
- Confirm one merged initial read is sent.
- Leave one or more zones unconfigured or inactive if possible.
- After five seconds, confirm components with no state display `Not present` rather than a spinner.
- Confirm logs identify the synthetic initialization.
- Confirm synthetic defaults do not cause aggregate presence to be calculated before a genuine zone report.

## 3. Zone and endpoint mapping

For each physical Meross zone:

- trigger occupancy only in that zone;
- record the reporting Matter endpoint;
- record the SmartThings component that changes;
- confirm whether physical Zone 1/2/3 maps to endpoint 2/3/4 respectively.

## 4. Aggregate presence

- Trigger one genuinely reporting zone and confirm `main` becomes `Present`.
- Clear all genuinely reporting zones and confirm `main` becomes `Not present`.
- Leave another zone silent/unconfigured and confirm it does not keep `main` present.
- Trigger two zones and clear them one at a time; `main` must remain present until the final occupied zone clears.

## 5. Illuminance and battery

- Confirm endpoint 1 illuminance updates the main component.
- Confirm battery values are plausible and within 0–100 percent.
- Confirm unavailable or invalid Matter values are ignored without errors.

## 6. Refresh and sleepy-device behavior

- Press Refresh while logcat is active.
- Confirm one merged Interaction Model request is sent.
- Allow time for the sleepy device to wake and respond.
- Confirm delayed responses do not cause duplicate or incorrect aggregate events.

## 7. Restart recovery

- Obtain genuine zone states.
- Restart the Edge driver or hub.
- Confirm previously genuine states can seed runtime state safely.
- Confirm synthetic states are not mistaken for genuine reporting zones.
- Confirm later real reports replace any visible default normally.
