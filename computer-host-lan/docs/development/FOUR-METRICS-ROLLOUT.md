# Four readouts for RAM and filesystem — staged beta experiment

**Status (2026-11-18):** PR #15 merged into `main`. On real Gentoo
`hydra` and a SmartThings hub, all eight values appeared in the German
app and `devices:status`, with consistent `/v2/metrics` payloads.
A memory translation upsert briefly returned HTTP 422 immediately after the
schema update; retry succeeded. Public `v0.5.2-beta.1` remains the rollback.
Stage the next `v0.5.3-beta.1` release from a final verified commit.

## Display and accounting

Both existing capabilities gain read-only **Used GiB** and **Available GiB**,
giving each four detail-view values: Usage %, Total GiB, Used GiB and
Available GiB. The existing dashboard and usage-percent automation condition
remain unchanged. A strict 2×2 arrangement is not guaranteed by SmartThings.

Physical RAM: Linux `MemAvailable` (not `MemFree`), Windows
`GlobalMemoryStatusEx.AvailPhys`; Used = Total − Available. This preserves
the current memory percentage semantics.

Filesystem: selected Linux root mount `/` or Windows system volume.
Allocated/used = `f_blocks - f_bfree` on Linux or `TotalSize -
TotalFreeSpace` on Windows. Available = `f_bavail` / `AvailableFreeSpace`.
They may not sum to total with reserved blocks, btrfs or Windows quotas.
**Do not modify existing disk-usage percentage semantics**: its definition
is currently Total − Available rather than the allocated block count.

Metrics are optional additions to protocol v2; older agents continue to
work, just without the new four values. No new network ports, privileges,
credentials, profiles, identities or power-control changes.

## Owner-only test rollout (after PR and CI review)

1. Review the live account-level memory/disk capability schemas,
   translations and presentations. Back them up and check for shared
   consumers; do not overwrite unrelated changes.
2. In `computer-host-lan/edge-driver`, the namespace owner may update the
   existing capabilities. **Never** create duplicate capabilities.

```sh
smartthings capabilities:update oceancircle09600.computerMemoryUsage -i custom-capabilities/computerMemoryUsage.json
smartthings capabilities:translations:upsert oceancircle09600.computerMemoryUsage -i custom-capabilities/computerMemoryUsage.en.json
smartthings capabilities:translations:upsert oceancircle09600.computerMemoryUsage -i custom-capabilities/computerMemoryUsage.de.json
smartthings capabilities:presentation:update oceancircle09600.computerMemoryUsage -i custom-capabilities/computerMemoryUsage.presentation.json

smartthings capabilities:update oceancircle09600.computerDiskUsage -i custom-capabilities/computerDiskUsage.json
smartthings capabilities:translations:upsert oceancircle09600.computerDiskUsage -i custom-capabilities/computerDiskUsage.en.json
smartthings capabilities:translations:upsert oceancircle09600.computerDiskUsage -i custom-capabilities/computerDiskUsage.de.json
smartthings capabilities:presentation:update oceancircle09600.computerDiskUsage -i custom-capabilities/computerDiskUsage.presentation.json
```

3. **Completed on Linux test hub:** four values per card rendered in the SmartThings app with German labels. Verified raw bytes and capability events. Linux CI, Windows Server CI and unsigned release-candidate assembly for PR #15 passed. **Still needed:** Windows 11 hardware feedback for the newly added values and preservation of upgrade state.
4. If new capability attributes are missing in SmartThings, verify the
   account-level schema, agent fields and driver version first. When
   `diskTotalGiB` was introduced, a normal **hub reboot** refreshed stale
   hub capability metadata. Avoid deleting and re-pairing a working device.
5. Publish the separately numbered beta using **verified same-commit** Linux, Windows x64 and documentation ZIPs. This remains a beta: Windows 11 hardware measurements require testers. Update the existing Computer Host LAN channel driver, preserving its driver ID. Preserve the published v0.5.2-beta.1 tag/assets for rollback.

## Required regression checks

- Dashboard states, percent-based routines and power operations unchanged
- GiB events rounded to one decimal; quiet events do not flood history
- Zero is valid; absent/invalid metric does not emit a fabricated value
- Static values retry when a capability attribute becomes available later
- Legacy agents missing all four new fields remain compatible
- Linux systemd/Windows service reinstall retains identity and control keys
