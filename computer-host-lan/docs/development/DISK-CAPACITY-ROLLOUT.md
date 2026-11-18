# Adding total root/system filesystem capacity (GiB) — staged rollout

**Status (2026-11-18):** PR #13 merged; account-level capability definition already updated, and Linux test hub reported `diskTotalGiB = 431.8` after hub reboot. Not yet rolled out as a new public GitHub prerelease / channel driver. No migration or protocol change.

## Display

`oceancircle09600.computerDiskUsage` retains the existing **Disk usage** percentage and adds a second read-only `diskTotalGiB` attribute displayed as **Total filesystem capacity** (German: **Dateisystemgröße**) in GiB, alongside usage in the device detail view. Dashboard and percentage-based routine conditions remain unchanged.

The agent returns `disk_root_total_bytes` from the **same volume** used for `disk_root_usage_percent`. Linux measures the filesystem mounted at `/` with `statvfs`, including its logical filesystem allocation (not the sum of raw drives). Windows measures the volume containing the Windows folder. Both are optional; unavailable values are `null` or absent, never fabricated as zero.

Old agents that do not report the capacity continue working; the driver simply omits the new attribute. Old drivers ignore the additional JSON field. The existing percentage isn't recalculated by the hub.

## Important: the capability lives in SmartThings, not the driver ZIP

Updating Lua or installing a new Edge Driver **does not** update an account-level capability. Updating an already registered capability ID under `oceancircle09600` affects all devices that use that ID, not only the test hub. Confirm the capability is owned by this account, review its *current live* schema/presentation/translations and check for other consumers **before** applying the change. Do not delete and re-create it. The new attribute is additive; the old `diskUsage` schema and routines must remain untouched.

### Controlled testing and rollout

1. Before any cloud mutation, capture the existing live `oceancircle09600.computerDiskUsage` capability definition, presentation and translations as a rollback/reference. Compare with the repository versions. Do **not** overwrite unrelated live changes.
2. From the full integration source directory, update **only the disk capability**, in order (commands below are for an authorized namespace owner; they are not run automatically):

   ```sh
   cd computer-host-lan/edge-driver
   smartthings capabilities:update oceancircle09600.computerDiskUsage -i custom-capabilities/computerDiskUsage.json
   smartthings capabilities:translations:upsert oceancircle09600.computerDiskUsage -i custom-capabilities/computerDiskUsage.en.json
   smartthings capabilities:translations:upsert oceancircle09600.computerDiskUsage -i custom-capabilities/computerDiskUsage.de.json
   smartthings capabilities:presentation:update oceancircle09600.computerDiskUsage -i custom-capabilities/computerDiskUsage.presentation.json
   ```

   Inspect the results and the live presentation; some CLI versions require an explicit `1` capability version for the presentation update. **Stop if any API call fails.** Do not run `publish-presentations.sh --apply`, which also modifies other capabilities.

3. Package the new Edge Driver to a **private test channel/hub** before touching the existing public channel. If the app still shows the old display, allow for cache/presentation propagation and inspect the live device presentation; do not immediately delete or re-pair a working device.
4. Update the **Linux agent** on one test host from the matching branch/build using the installer and confirm `curl -fsS http://127.0.0.1:8765/v2/metrics` includes a positive `disk_root_total_bytes`. Existing installation identity, tokens and service configuration must be preserved. The old Linux agent cannot supply this field.
5. Check `smartthings devices:status <device-id>` and the app for `diskUsage` and `diskTotalGiB`. Verify the filesystem capacity against `df -B1 /` on Linux (filesystem semantics can differ on btrfs and mounts). Ensure the app labels and percent-based routines remain intact.
6. Independently verify the Windows ZIP/reinstalled agent on a Windows test system before making Windows capacity claims. Use the existing Windows tester or CI smoke; ensure the reported size belongs to the Windows system volume.
7. Only after successful testing, prepare new **versioned** release packages for both agents/driver; keep v0.5.1-beta.1 assets as rollback. Do not update current public assets in place.

If an account-level schema update is rejected or a presentation behaves unexpectedly, leave the production driver and agents unchanged and revisit the presentation design separately.

## Regression gates

- Existing `diskUsage` event and 0–100 routine conditions unchanged.
- New `diskTotalGiB` is emitted only for a finite, positive reported capacity and is rounded to one decimal place. An invalid/missing value must not emit zero.
- A missing or temporarily unavailable new attribute must not prevent existing telemetry or poison the emission cache. Retry on the next poll, as already done for `memoryTotalGiB`.
- Other Linux and Windows features, power authentication, wake, mDNS, profiles, security permissions and HTTP routes are untouched.
- This display is informational. A filesystem can be full without an equivalent raw disk failure; the total capacity isn't necessarily equal to the sum of all disks on the host.

## SmartThings hub registry synchronization — real test (2026-11-18)

On Gentoo `hydra`, the agent and Edge driver reported a correct 431.8 GiB value. The cloud API initially returned `null` despite the updated capability schema and a logcat emission. Restarting the SmartThings hub resolved it. If other testers experience this, check the local `disk_root_total_bytes` value and the installed Edge driver version, then try a normal hub reboot before deleting/re-pairing a device. This is one observed recovery, not a guarantee.
