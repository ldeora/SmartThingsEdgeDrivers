**Computer Host LAN — beta update v0.5.2-beta.1**

The new beta adds **Total filesystem capacity** (GiB) alongside the existing disk-usage percentage, for both Linux (root filesystem) and Windows (system volume). Protocol v2, device identity and the existing power functions remain unchanged.

**Downloads:** [Computer Host LAN v0.5.2-beta.1 — GitHub Release](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.2-beta.1). Choose the new Linux source ZIP or Windows x64 ZIP and verify its SHA-256 against `SHA256SUMS.txt`. The updated **Computer Host LAN** Edge driver is installed from my [existing SmartThings channel](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20).

**Please update in place.** Don't delete/re-pair the SmartThings device, uninstall the old agent or purge its identity and key.

**Linux:** Extract the new source ZIP, enter its top-level folder and run:

```sh
./scripts/preflight.sh
./scripts/install-agent.sh --dry-run
sudo ./scripts/install-agent.sh
curl -fsS http://127.0.0.1:8765/v2/metrics
```

The Linux installer preserves an existing power opt-in.

**Windows 11 x64:** Extract the new Windows ZIP and open PowerShell **as Administrator** in that folder:

```powershell
$hubIPv4 = '192.168.1.20' # Replace with your actual hub IPv4 address
.\scripts\Verify-Package.ps1
.\scripts\Install-WindowsAgent.ps1 -WhatIf
.\scripts\Install-WindowsAgent.ps1 -HubIPv4 $hubIPv4
Get-Service ComputerHostAgent
Invoke-RestMethod http://127.0.0.1:8765/v2/metrics
```

**Windows power-control note:** If you'd previously enabled shutdown/reboot/suspend, add `-EnablePower` to the real installation command above. Without it, the Windows installer intentionally disables remote power; existing credentials and identity remain unchanged.

After the upgrade, the local `/v2/metrics` output should include `disk_root_total_bytes` and SmartThings should show **Total filesystem capacity**. On my test hub the cloud initially reported a blank value even though the updated capability was registered. **Rebooting the SmartThings hub solved it**, without deleting or re-pairing anything. Try that if the new local metric is present but the app remains blank.

I'd particularly appreciate Windows 11 reports about correct disk capacity, same device after upgrade, and continued monitoring and power behavior. Please mention your OS version and hub firmware, but never post control keys, IP/MAC addresses or unredacted logs. Thanks again for helping test!
