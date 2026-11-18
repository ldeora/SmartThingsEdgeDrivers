# Computer Host LAN v0.5.2-beta.1 — beta update

**Release-candidate document.** Only publish after the GitHub prerelease and matching SmartThings channel driver are ready.

## What's new

[PR #13](https://github.com/ldeora/SmartThingsEdgeDrivers/pull/13) adds total filesystem capacity in GiB alongside existing disk usage %. Linux measures the filesystem mounted at /; Windows measures the system volume. Protocol v2, discovery, identity, keys, device profiles and power commands remain unchanged. The new metrics field is optional and older agents remain supported.

Versions: integration **0.5.2-beta.1**, Linux agent **0.4.1-beta.1**, Windows agent **0.2.1-beta.1**, Edge Driver **0.4.1-beta.1**.

After publication download the [new GitHub prerelease](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.2-beta.1), verify the ZIP against SHA256SUMS.txt, and install the updated driver through the [same SmartThings channel](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20). Keep v0.5.1-beta.1 available for rollback.

## In-place upgrade

**Do not delete the SmartThings computer device, uninstall the old agent or purge state.** Extract the new package in a separate directory and install over the existing service.

### Linux (systemd)

From the extracted source ZIP root:

```sh
./scripts/preflight.sh
./scripts/install-agent.sh --dry-run
sudo ./scripts/install-agent.sh
systemctl is-active linux-host-agent.service
curl -fsS http://127.0.0.1:8765/v2/info
curl -fsS http://127.0.0.1:8765/v2/metrics
```

The Linux installer preserves the installation identity, private control token and existing power opt-in.

### Windows 11 x64

From the extracted Windows x64 ZIP root, use **PowerShell as Administrator**:

```powershell
$hubIPv4 = '192.168.1.20' # Replace with your real SmartThings hub IPv4
.\scripts\Verify-Package.ps1
.\scripts\Install-WindowsAgent.ps1 -WhatIf
.\scripts\Install-WindowsAgent.ps1 -HubIPv4 $hubIPv4
Get-Service ComputerHostAgent
Invoke-RestMethod http://127.0.0.1:8765/v2/info
Invoke-RestMethod http://127.0.0.1:8765/v2/metrics
```

**If power control was enabled previously, include `-EnablePower` with the actual installation command** or the Windows installer intentionally disables remote power. The private token and identity under `%ProgramData%\ComputerHostAgent` are retained by default. Do not use `-PurgeState` for an upgrade.

## Verification and troubleshooting

`/v2/metrics` should include a positive `disk_root_total_bytes`. In SmartThings, expect **Total filesystem capacity** in GiB alongside **Disk usage**. On the publisher's Linux test hub the API initially showed null despite a correct event and schema; a **hub reboot resolved it**. Confirm agent data and driver update, then consider a normal hub restart before re-pairing (usually not needed).

Please report correct system/root volume capacity, device identity preservation, monitoring, opt-in power settings and whether a hub reboot was needed. Windows capacity and WOL across different machines remain beta test goals. The Windows executable is unsigned; use a trusted private LAN, never forward TCP 8765, and don't share tokens or private identifiers.
