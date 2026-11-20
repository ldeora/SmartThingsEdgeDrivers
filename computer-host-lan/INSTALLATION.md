# Computer Host LAN — installation (protocol v2)

> **Next candidate: Computer Host LAN v0.5.6-beta.1 (not yet published).** This single hardening candidate combines installer recovery and runtime resilience. Current published/tested beta: [v0.5.5-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.5-beta.1). [Candidate release notes](docs/beta/RELEASE-NOTES-v0.5.6-beta.1.md).


**Current published beta:** v0.5.5-beta.1. **Next consolidated candidate:** v0.5.6-beta.1 (unpublished). The v0.5.5 Windows 11 Pro GUI upgrade, telemetry, service recovery and WOL have been reported working; v0.5.6 changes still require validation.

## Before installation

Use a trusted private LAN and a SmartThings hub that supports LAN Edge drivers. Allow mDNS discovery (UDP 5353) and hub-to-host HTTP TCP 8765. Never forward TCP 8765 to the internet. Host and hub must be able to reach each other; multicast separation or client isolation can prevent discovery. Install the new `computer-host-lan` driver, not the original `linux-host-lan` driver. Publisher-owned `oceancircle09600` capabilities must be registered by the publisher; testers should not register any.

## Windows 11 x64 — recommended graphical installer

The **Windows x64 Setup.exe** is the recommended method beginning with the published [v0.5.4-beta.1 release](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.4-beta.1). Download `computer-host-lan-v0.5.4-beta.1-windows-x64-unsigned-setup.exe` and verify its SHA-256 using `SHA256SUMS.txt`. The installer is unsigned and needs administrator rights, but no separate .NET SDK.

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

## Upgrading from v0.5.3-beta.1

**Windows:** Run the v0.5.4 Setup.exe over your existing installation. It migrates the service and retains UUID, key, configuration and power setting. Alternatively use the new ZIP and rerun the script, specifying `-EnablePower` if it was previously enabled. Do not purge state or delete/re-pair the SmartThings device.

**Linux:** The Linux agent and Edge driver remain at v0.4.2-beta.1, so Linux users do not need an agent or driver upgrade just for this Windows-installer release. As always, `./scripts/preflight.sh` and `sudo ./scripts/install-agent.sh` remain available if reinstalling. The four RAM and filesystem measurements added in v0.5.3 remain unchanged.

**Release verification:** Download only from the published, versioned GitHub prerelease and compare SHA-256 checksums. Temporary GitHub Actions artifacts are development candidates, not permanent releases.

## Stabilization before the first stable release

[Merged PR #19](https://github.com/ldeora/SmartThingsEdgeDrivers/pull/19) adds safeguards for the Windows graphical upgrade failure path, existing authentication-key ACLs, runtime-version checks, and preservation of PowerShell-upgraded custom settings/ports. These changes are **not part of the published v0.5.4-beta.1 release**. They are included in the **planned v0.5.5-beta.1 candidate**, which must pass fresh CI and be explicitly published before installing. Do not install PR build artifacts on production computers. A failed upgrade must be treated as a support event; never delete the persistent UUID or secret to make it disappear.

Third-party components and redistribution: [notices](docs/beta/THIRD-PARTY-NOTICES.md). The clipboard can retain explicitly copied power-control keys through clipboard history or synchronization depending on Windows settings; clear that history and avoid sharing the key.

## Planned v0.5.5-beta.1 upgrade (only after publication)

Review the [versioned release notes](docs/beta/RELEASE-NOTES-v0.5.5-beta.1.md). Download and verify the **new** Setup.exe and `SHA256SUMS.txt` from the [v0.5.5-beta.1 release page](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.5-beta.1) after publication. Run Setup over v0.5.4 without uninstalling and confirm that UUID, token, custom port/configuration and power preferences remain unchanged. The new installer adds rollback safeguards for detectable errors; test service interruption/recovery on a recoverable machine. Linux should install from the matching new source ZIP. The publisher must build and assign the **updated Edge driver v0.4.3-beta.1** to the existing channel. The current published beta and driver remain usable until then.

## v0.5.6 hub address maintenance and interrupted upgrade recovery

Reserve the hub's IPv4 in your router's DHCP configuration. To update an existing Windows firewall allow-list without reinstalling, open an elevated PowerShell prompt and run `& "$env:ProgramFiles\Computer Host Agent\Installer\Set-WindowsHubAddress.ps1" -HubIPv4 192.168.1.20`, replacing the example with the hub's actual canonical IPv4. The rule remains Private-profile only. A public or domain-connected network may require an explicit network-profile correction; do not make the rule Public by default.

An abandoned `Computer Host Agent.upgrade-rollback` folder must **never** be deleted casually. Interactive Setup can offer an explicit recovery attempt. If Setup cannot recover, use `Restore-WindowsAgentUpgrade.ps1 -Mode Restore` from the same-version Windows ZIP in an elevated PowerShell session; preserve the snapshot and host identity in ProgramData. Silent installers refuse abandoned snapshots without stopping the service.
