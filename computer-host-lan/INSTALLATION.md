# Computer Host LAN — installation (protocol v2)

**Published prerelease:** [v0.5.6-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.6-beta.1) (Windows agent 0.2.5-beta.1; Linux/Edge 0.4.4-beta.1; protocol v2). **Hardware-validated rollback baseline:** [v0.5.5-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.5-beta.1). v0.5.6 hardware validation is still pending.

## Before installation

Use a trusted private LAN and a SmartThings hub that supports LAN Edge drivers. Allow mDNS discovery (UDP 5353) and hub-to-host HTTP TCP 8765. Never forward TCP 8765 to the internet. Host and hub must be able to reach each other; multicast separation or client isolation can prevent discovery. Install the new `computer-host-lan` driver, not the original `linux-host-lan` driver. Publisher-owned `oceancircle09600` capabilities must be registered by the publisher; testers should not register any.

## Windows 11 x64 — recommended graphical installer

Use the Windows x64 Setup.exe from the **published [v0.5.6-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.6-beta.1)**, verifying SHA-256 using SHA256SUMS.txt. The installer is unsigned, requires administrator rights and is self-contained. New v0.5.6 recovery paths still require physical Windows 11 testing.

1. Run Setup.exe. On the **SmartThings hub** page, select a discovered hub, retry **Search again**, or enter the hub's IPv4 manually. When discovery fails, the explicit **Allow connections from devices on my local network** option configures a Private-only LocalSubnet firewall rule; when discovery works, find this choice under **Advanced options**. It does not repair blocked mDNS between networks.
2. Choose whether to enable optional **Power management**. A new installation defaults to monitoring only. A Setup upgrade or conversion from the existing ZIP/PowerShell installation retains the previous power preference unless you change it.
3. On **Connect to SmartThings**, follow the [driver channel invitation](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20): sign in, enroll your hub if needed, install **Computer Host LAN** under **Available Drivers**, then use **Add device → Scan nearby** in SmartThings. These instructions remain accessible from the Start Menu.
4. If power was enabled, the optional **Power control key** page offers Show/Hide and Copy. Enter that private 64-character key in the SmartThings device's `controlKey` setting, and enable `allowPowerCommands`. Keep it confidential.
5. Verify the service using `Get-Service ComputerHostAgent` and check `http://127.0.0.1:8765/v2/metrics` (replace 8765 if you configured another port). Test reboot/suspend/shutdown only with saved work and physical recovery available.

**Upgrading:** Launch the new Setup.exe over the existing ZIP- or Setup-installed agent. Do not first uninstall, delete the SmartThings device or purge `%ProgramData%\ComputerHostAgent`. Inno Setup preserves the installation ID, control token, custom `appsettings.json` and previous power selection. Normal removal through Windows **Installed apps** removes the service, application files and firewall rule, but intentionally retains ProgramData state. Windows ARM64 is not supported by this x64 installer.

### Fallback: ZIP and elevated PowerShell

If graphical Setup fails, download the version-matched **Windows x64 unsigned ZIP** from the same release, verify its checksum, extract it, and run PowerShell **as Administrator** from the extracted directory:

```powershell
$hubIPv4 = '192.168.1.20'  # Replace with your actual SmartThings hub IPv4
.\scripts\Verify-Package.ps1
.\scripts\Install-WindowsAgent.ps1 -WhatIf
.\scripts\Install-WindowsAgent.ps1 -HubIPv4 $hubIPv4
Get-Service ComputerHostAgent
Invoke-RestMethod http://127.0.0.1:8765/v2/metrics
```

Omit `-HubIPv4` to allow LocalSubnet on Private Windows profiles. **Unlike Setup.exe, PowerShell upgrades require `-EnablePower` again if you want to retain remote power actions.** Without that flag, the script disables them; persistent identity and key remain unchanged. Private key inspection: `Get-Content "$env:ProgramData\ComputerHostAgent\control-token"`. For the script installation use `.\scripts\Uninstall-WindowsAgent.ps1` without `-PurgeState` when preserving your identity.


## Linux (systemd)

Requires Python 3.10+, systemd as PID1, Avahi/mDNS for automatic discovery and administrator rights to install. From the *matching* Computer Host LAN source directory:

```sh
./scripts/preflight.sh
./scripts/install-agent.sh --dry-run
sudo ./scripts/install-agent.sh
systemctl status linux-host-agent.service
curl -fsS http://127.0.0.1:8765/v2/info
avahi-browse -rt _computerhost._tcp
```

Power control is separate and opt-in: `sudo ./scripts/install-agent.sh --enable-power --wol-interface YOUR_ETHERNET_INTERFACE`. Do not change persistent WOL configuration unless deliberately choosing the existing `--configure-wol` path. Keep the key in `/var/lib/linux-host-agent/control-token` private. Read [Linux parity acceptance](docs/development/LINUX-PARITY-ACCEPTANCE.md) before physical tests.

The earlier Linux Host LAN uses protocol v1 and a different discovery namespace; do not install it alongside the new agent on the same listener. Record a rollback snapshot and the driver choice before migration.

## Updates and caveats

A GitHub Actions artifact is temporary and is **not** a permanent published prerelease. Install only assets associated with a fixed release/tag and matching checksums. Package signing has not been implemented. Keep applications saved before power tests. Do not use production or workplace computers for initial hardware experiments.

## Current upgrade and recovery guidance

The v0.5.5 Windows 11 tester confirmed a successful in-place GUI upgrade, preserved SmartThings device/settings, accurate CPU/RAM/disk statistics, service stop/restart recovery and functioning WOL. This does not validate new v0.5.6 changes.

Run the version-matched newer Setup.exe over the existing installation. Do not uninstall, delete the SmartThings device or purge the persistent UUID and control token. Setup preserves the prior power preference; ZIP/PowerShell upgrades require -EnablePower again. Install only from a **published release** after checking SHA-256 hashes, not from temporary PR artifacts.

The published v0.5.6 beta adds an interrupted-upgrade recovery option and checks health, version and existing identity before committing. Never delete the rollback snapshot or ProgramData files to bypass a failure. Keep a router DHCP reservation for the SmartThings hub. Review the [published beta release notes](docs/beta/RELEASE-NOTES-v0.5.6-beta.1.md) before any new hardware tests.

## v0.5.6 hub address maintenance and interrupted upgrade recovery

Reserve the hub's IPv4 in your router's DHCP configuration. To update an existing Windows firewall allow-list without reinstalling, open an elevated PowerShell prompt and run `& "$env:ProgramFiles\Computer Host Agent\Installer\Set-WindowsHubAddress.ps1" -HubIPv4 192.168.1.20`, replacing the example with the hub's actual canonical IPv4. The rule remains Private-profile only. A public or domain-connected network may require an explicit network-profile correction; do not make the rule Public by default.

An abandoned `Computer Host Agent.upgrade-rollback` folder must **never** be deleted casually. Interactive Setup can offer an explicit recovery attempt. If Setup cannot recover, use `Restore-WindowsAgentUpgrade.ps1 -Mode Restore` from the same-version Windows ZIP in an elevated PowerShell session; preserve the snapshot and host identity in ProgramData. Silent installers refuse abandoned snapshots without stopping the service.
