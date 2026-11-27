# Host Status on the device tile (#192) — test and rollout

**Status:** implemented in the repository, not yet tested on a hub. Requested by rc.2 testers.

## What changes

- **Driver (profiles only):** `computer-host-linux` and `computer-host-windows` embed a `deviceConfig`. The tile shows Host Status (Running, Stopped, Unreachable, …) instead of on/off. The tile button still switches the computer on and off. The basic `computer-host` profile is unchanged.
- **Account-level capability presentation:** in `oceancircle09600.computerHostStatus`, Unreachable is now shown as inactive (grey), like Stopped and Suspended. This is not part of the driver ZIP; see step 4.

An embedded `deviceConfig` replaces the presentation SmartThings would otherwise generate. Every component and capability must therefore be listed in `detailView` and `automation`; `tests/test_device_presentation.py` enforces this. No Lua, agent, protocol or preference change.

## Open questions this test answers

1. **Status on the tile with the switch as the tile button.** None of the 34 official SmartThings profiles with an embedded `deviceConfig` (SmartThingsCommunity/SmartThingsEdgeDrivers, checked 2026-11-27) combines a state from one capability with an action from another. If the button does not work or looks wrong, set `actions: []` in both profiles. The tile then shows the status only; on/off stays on the device page.
2. **Whether existing devices pick up the new presentation** after the driver update, and whether the app has to be closed or its cache cleared.
3. **The device page order and routine list** compared with the presentation SmartThings generated before.

## Test on the private channel

1. **Before the update**, save the current presentation of one Linux and one Windows device. This is the reference and the rollback:

   ```sh
   smartthings devices:presentation <linux-device-id> -j > linux-presentation-before.json
   smartthings devices:presentation <windows-device-id> -j > windows-presentation-before.json
   ```

   Compare their `detailView` and `automation` with the new profiles. If the generated presentation lists something the profiles do not (for example `refresh` as a routine action), add it to the profile and the test before continuing.

2. **Install the driver on the private channel only.** Do not touch the public channel. Refresh the devices; if the tile does not change, close and reopen the app before anything else. Do not delete or re-pair a working device.

3. **Check, in English and German, for Linux and Windows:**
   - [ ] The tile shows Host Status.
   - [ ] The tile button switches on/off as before (otherwise switch to `actions: []` and record it).
   - [ ] The device page shows switch, Host Status, all metrics, Refresh, and Wake, Restart and Sleep.
   - [ ] An existing routine using switch, Host Status, a metric or a Wake/Restart/Sleep button still runs.
   - [ ] A new routine offers all conditions (switch, Host Status, metrics) and all actions (switch, Wake, Restart, Sleep).

4. **Update the Host Status presentation** (account-level). It applies immediately to every device using the capability, including rc.2 installations, without a driver update. It only changes the colour of Unreachable.

   ```sh
   cd computer-host-lan/edge-driver
   smartthings capabilities:presentation oceancircle09600.computerHostStatus 1 -j > computerHostStatus.presentation.live-backup.json
   smartthings capabilities:presentation:update oceancircle09600.computerHostStatus 1 \
     -i custom-capabilities/computerHostStatus.presentation.json
   ```

   Compare the backup with the repository file first; stop if the live presentation contains changes that are not in the repository. Do not run `publish-presentations.sh --apply`, which also changes other capabilities. Stop if an API call fails.

   - [ ] An unreachable computer appears as inactive on the tile.

## Rollback

- Driver: install the previous driver version on the channel. The profiles, and with them the generated presentation, return with it.
- Presentation: `smartthings capabilities:presentation:update oceancircle09600.computerHostStatus 1 -i computerHostStatus.presentation.live-backup.json`.
