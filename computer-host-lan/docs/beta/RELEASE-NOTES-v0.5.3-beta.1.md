# Computer Host LAN v0.5.3-beta.1 — four RAM and filesystem measurements

This beta expands **both** the RAM and root/system filesystem sections with
**Usage %**, **Total GiB**, **Used GiB** and **Available GiB**, while keeping
the existing dashboard percentages and SmartThings routine conditions intact.
The SmartThings mobile app determines its responsive arrangement (including 3+1
rows). No fixed 2×2 layout is required.

The change comes from [PR #15](https://github.com/ldeora/SmartThingsEdgeDrivers/pull/15).
Physical RAM: Linux uses `MemAvailable` and Windows uses `AvailPhys`;
used RAM is total minus available. Root/system filesystem: Linux
`statvfs("/")` / Windows `DriveInfo` expose separate allocated and
available bytes. **Used + Available may be less than Total** because of
reserved blocks or filesystem quotas. The original disk percentage calculation
is deliberately preserved.

The four additional protocol-v2 telemetry properties are:
`memory_used_bytes`, `memory_available_bytes`,
`disk_root_used_bytes`, `disk_root_available_bytes`. They are optional,
so older agents continue reporting the original readings. The existing
custom capabilities gained four read-only GiB attributes in total;
no profiles, discovery, UUID, control keys, power commands or service
privileges changed.

**Component versions:** Integration **v0.5.3-beta.1**;
Linux agent **v0.4.2-beta.1**, Windows agent **v0.2.2-beta.1**,
SmartThings Edge driver **v0.4.2-beta.1**; protocol **v2**.

## Validation and beta scope

- **Linux:** On 2026-11-18, Gentoo `hydra` plus real SmartThings hub:
  all eight values showed in the German Android detail view and
  `smartthings devices:status`; `/v2/metrics` returned plausible raw bytes.
  RAM total ~30.3 GiB; root filesystem total ~431.8 GiB.
- **Windows:** Windows Server 2025 GitHub CI validates the build, native
  telemetry contract, service install and unsigned Windows x64 packaging;
  **Windows 11 validation of the new four-value display and hardware-specific
  wake/recovery is still requested.** One beta tester has reported successful
  Windows 11 installation and basic suspend/reboot/shutdown previously.
- The publisher already updated the account-level SmartThings
  `computerMemoryUsage` and `computerDiskUsage` schemas,
  English/German translations and presentations while testing PR #15.
  The initial German memory translation attempt returned HTTP 422
  immediately after the schema update, but a retry succeeded.
  **Testers should not register or edit any capability.**
- All Linux, Windows and release-candidate CI checks must pass on the exact
  final v0.5.3-beta.1 source commit. Assets are unsigned and available via
  the GitHub prerelease after publisher verification.

## Download and install

Get the new Linux source ZIP or unsigned Windows x64 ZIP from
[Computer Host LAN v0.5.3-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.3-beta.1)
and verify the SHA-256 against `SHA256SUMS.txt`.
Install/update the matching Edge driver through the existing
[ARoedl SmartThings Edge Drivers channel](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20).
Do not install the separate legacy protocol-v1 Linux Host LAN driver.

**In-place upgrade:** Keep the SmartThings device, installation identity,
control token and existing driver settings. Do not uninstall, purge state,
delete the device or re-pair. Extract into a new directory.

Linux (from extracted source ZIP root):

```sh
./scripts/preflight.sh
./scripts/install-agent.sh --dry-run
sudo ./scripts/install-agent.sh
systemctl is-active linux-host-agent.service
curl -fsS http://127.0.0.1:8765/v2/metrics
```

Linux preserves its previous power opt-in during an in-place upgrade.

Windows 11 x64 (PowerShell **as Administrator**, from extracted Windows ZIP root):

```powershell
$hubIPv4 = '192.168.1.20'  # Replace with your real hub IPv4
.\scripts\Verify-Package.ps1
.\scripts\Install-WindowsAgent.ps1 -WhatIf
.\scripts\Install-WindowsAgent.ps1 -HubIPv4 $hubIPv4
Get-Service ComputerHostAgent
Invoke-RestMethod http://127.0.0.1:8765/v2/metrics
```

**Windows power-control upgrade:** If shutdown/reboot/suspend was previously
enabled, use
`.\scripts\Install-WindowsAgent.ps1 -HubIPv4 $hubIPv4 -EnablePower`
for the actual install. Without `-EnablePower` the installer deliberately
disables remote power; persistent identity and key are retained. Never use
`-PurgeState` when upgrading.

After upgrading, check all four values in **Memory** and **Root filesystem**
(or the Windows system volume). If the local JSON contains the new bytes but
the SmartThings app remains blank, first confirm that the newest driver is
installed. A normal hub reboot has previously refreshed stale capability
metadata without deleting the device.

The prior [v0.5.2-beta.1 prerelease](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.2-beta.1)
remains available as a rollback download.

## Safety and feedback

Windows packages are unsigned; use only trusted private LANs, do not forward
TCP 8765 to the internet, and keep power commands opt-in on machines you can
physically recover. Please report Windows 11 disk/RAM readouts, service
restart/recovery and in-place upgrade identity preservation in the
[Computer Host LAN beta discussion](https://community.smartthings.com/t/st-edge-computer-host-lan-bring-windows-and-linux-computers-into-smartthings-public-beta/312605).
Never post control keys, IP/MAC addresses or unredacted logs.
