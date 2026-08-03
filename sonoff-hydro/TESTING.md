# Alpha29 hardware test plan

## 1. Mandatory regression test: basic control

Test this before changing any private setting.

1. Install alpha29 and enable **Debug logging**.
2. Open and close the valve using the **Valve** control.
3. Repeat using the **Switch** control.
4. Confirm immediate physical movement and no **Network Error**.
5. Where available, test SWV-ZNE firmware 1.1.0 and SWV-ZFE firmware 1.0.8 separately.
6. Confirm the log contains `standard On queued` and `standard Off queued` without a preceding requirement for `0x501D` verification.

A private-setting failure must never make this section fail.

## 2. Device-side watering limit and the ten-minute cutoff

Use an ordinary Valve Open for the measured run. Do not use the custom timed-watering action for this test, because its driver timer would test a different feature.

1. Close the valve.
2. Change **Device-side watering limit** to 15 or 20 minutes.
3. Save the device settings.
4. Press **Refresh** once.
5. Keep live driver logging running and look for:
   - synchronization start;
   - a fresh `0x501D` read;
   - the packed write;
   - a verification read;
   - `0x501D synchronization verified`.
6. For Hydro ONE or Hydro DUO, confirm the verified log shows the fail-safe at the same selected value.
7. Open the valve using the ordinary **Valve Open** control.
8. Measure the physical open-to-close time.
9. A 15-minute setting should remain open beyond ten minutes and close at approximately 15 minutes.
10. Repeat once after a driver or hub restart to confirm the selected non-default value is rechecked without affecting basic control.

If synchronization times out, operate the valve once or press Refresh again while logging. Alpha29 retries when the valve next proves it is awake. Do not judge the long-run test until the readback is verified.

## 3. Timed watering

1. Run a two-minute **Open valve for minutes** session.
2. Confirm immediate physical opening.
3. Confirm automatic physical closing after approximately two minutes.
4. Start another timed run and stop it with Valve Close or Switch Off.
5. Start a timed run, restart the driver or hub, and confirm recovery queues one standard Off.
6. Request a duration longer than ten minutes only after Section 2 has verified a device-side limit at least as long as the requested run.

## 4. Retry and isolation tests

1. Temporarily make the valve unavailable or sleepy and change the device-side limit.
2. Confirm the synchronization eventually times out instead of remaining permanently pending.
3. Confirm Valve Open and Close still work during and after the timeout.
4. Restore communication and press Refresh or operate the valve.
5. Confirm synchronization retries and can reach `verified`.

## 5. Retained features

Check that alpha28 behavior remains unchanged:

- Child lock
- Battery and firmware display
- Refresh and private telemetry
- Real-time and hourly irrigation duration
- Current and hourly volume on full and DUO models
- Alarm preferences and abnormal-state reports
- Water Sensor leakage mapping
- Both Hydro DUO channels and opposite-channel handling
- Routine actions and conditions already exposed by the existing custom capabilities

## Logs to share

For a failed duration test, include the complete log from before changing the setting through the verification attempt and the measured Open run. The essential lines are the original 12-byte readback, the outgoing payload, the verification readback, and the physical closing time.
