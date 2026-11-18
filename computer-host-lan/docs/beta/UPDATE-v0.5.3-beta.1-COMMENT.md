**Computer Host LAN — beta update v0.5.3-beta.1**

A new beta adds **Used** and **Available** in GiB to **both RAM and the root/system filesystem**. Each SmartThings section now provides four measurements: Usage %, Total GiB, Used GiB and Available GiB. The layout adapts to your screen. Linux has been validated on my Gentoo machine with a real SmartThings hub; Windows is implemented and CI-tested, and I would particularly appreciate Windows 11 reports.

**Downloads:** [Computer Host LAN v0.5.3-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.3-beta.1). Select the updated Linux source ZIP or Windows x64 ZIP and compare its hash with `SHA256SUMS.txt`. The matching **Computer Host LAN** Edge driver is distributed through [my existing SmartThings Edge channel](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20).

**Please upgrade in place.** There's no need to delete the SmartThings computer, re-pair, uninstall the old agent or reset credentials.

**Linux:** From the new extracted source ZIP:

```sh
./scripts/preflight.sh
./scripts/install-agent.sh --dry-run
sudo ./scripts/install-agent.sh
curl -fsS http://127.0.0.1:8765/v2/metrics
```

The Linux installer retains the existing installation ID, control key and power opt-in.

**Windows 11 x64:** From the new extracted Windows ZIP, run PowerShell **as Administrator**:

```powershell
$hubIPv4 = '192.168.1.20'  # Replace with your actual hub IPv4
.\scripts\Verify-Package.ps1
.\scripts\Install-WindowsAgent.ps1 -WhatIf
.\scripts\Install-WindowsAgent.ps1 -HubIPv4 $hubIPv4
Get-Service ComputerHostAgent
Invoke-RestMethod http://127.0.0.1:8765/v2/metrics
```

**Important for Windows power users:** If you had enabled shutdown/reboot/suspend, add `-EnablePower` to the installation command (`.\scripts\Install-WindowsAgent.ps1 -HubIPv4 $hubIPv4 -EnablePower`); otherwise those commands are intentionally disabled on reinstall. Your identity and control key are preserved. Don't use `-PurgeState` during an upgrade.

Check for `memory_used_bytes`, `memory_available_bytes`, `disk_root_used_bytes` and `disk_root_available_bytes` in the local metrics response and the four readings in SmartThings. **Used + Available may be less than Total** for filesystems with reserved blocks/quotas; that is expected.

The existing custom capabilities have already been extended by the publisher—testers should not register anything. If the local agent reports values but the app remains empty, verify the driver update and try a normal hub reboot before re-pairing.

As before, protocol v2, persistent IDs, existing routines and power commands are unchanged. I'd welcome Windows 11 feedback about the new values and in-place upgrades, with OS and hub firmware details. Please redact private tokens, IP/MAC addresses and IDs. Thank you for testing!
