# Computer Host LAN — installation (protocol v2)

**Public beta v0.5.3-beta.1:** Obtain the host agent from the [official GitHub prerelease](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.3-beta.1) and install the Edge Driver separately from the verified [ARoedl SmartThings Edge Drivers channel](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20). Another account has successfully installed the driver.

## Before installation

Use a trusted private LAN and a SmartThings hub that supports LAN Edge drivers. Allow mDNS discovery (UDP 5353) and hub-to-host HTTP TCP 8765. Never forward TCP 8765 to the internet. Host and hub must be able to reach each other; multicast separation or client isolation can prevent discovery. Install the new `computer-host-lan` driver, not the original `linux-host-lan` driver. Publisher-owned `oceancircle09600` capabilities must be registered by the publisher; testers should not register any.

## Windows 11 x64 (first volunteers)

Download the **versioned Windows ZIP** from the [Computer Host LAN v0.5.3-beta.1 GitHub prerelease](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.3-beta.1), verify the published SHA-256, and extract it without altering directories. The executable is self-contained (.NET runtime bundled); administrator rights are necessary to register a Windows Service.

From **elevated PowerShell** inside the extracted tester kit, replace the example with your hub's actual IPv4 address:

```powershell
$hubIPv4 = '192.168.1.20'  # example only
.\scripts\Verify-Package.ps1
.\scripts\Install-WindowsAgent.ps1 -WhatIf
.\scripts\Install-WindowsAgent.ps1 -HubIPv4 $hubIPv4
Get-Service ComputerHostAgent
Invoke-RestMethod http://127.0.0.1:8765/v2/info
Invoke-RestMethod http://127.0.0.1:8765/v2/health
Invoke-RestMethod http://127.0.0.1:8765/v2/metrics
```

Use the actual hub IPv4 address in `$hubIPv4`. Omit `-HubIPv4` to permit `LocalSubnet` on **Private** Windows network profiles. The installer does not modify BIOS, Windows sleep/fast-startup options, WOL adapter configuration, or mDNS firewall policies. Windows DNS-SD discovery on real PC/hub networks still needs volunteer verification.

Open the [verified channel invitation](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20), sign in, accept, enroll your hub and install **Computer Host LAN** under **Available Drivers**. Then use SmartThings **Scan nearby**. The Windows profile omits CPU temperature and Linux load. If discovery fails, report it rather than disabling the firewall globally; `hostOverride` only works *after* first pairing.

**Optional authenticated power commands — test PC, saved work and physical recovery only:**

```powershell
.\scripts\Install-WindowsAgent.ps1 -EnablePower -HubIPv4 $hubIPv4
# Inspect the control key privately; NEVER paste into public reports.
Get-Content "$env:ProgramData\ComputerHostAgent\control-token"
```

Set SmartThings `allowPowerCommands` and `controlKey` preferences privately. Try reboot first, then suspend/WOL, then shutdown/WOL. Power operations are best effort. Re-running the installer **without** `-EnablePower` disables remote power again. See [Windows-specific details](windows-agent/README.md).

To uninstall: `.\scripts\Uninstall-WindowsAgent.ps1`. The optional `-PurgeState` permanently removes identity and the control key. Use the kit's `Collect-WindowsDiagnostics.ps1` for sanitized reports, and review every report before sharing.

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

## Upgrading from the previous beta (v0.5.2-beta.1)

After the v0.5.3-beta.1 GitHub prerelease and matching Edge driver are available, download the new ZIP and check its SHA-256. Extract to a new folder. **Do not uninstall or purge the existing agent, delete the SmartThings computer, or re-pair it.** Both agents preserve their installation identity and private control key. Update Computer Host LAN from the **same** SmartThings Edge channel.

**Linux:** In the new source ZIP's top-level directory run `./scripts/preflight.sh`, `./scripts/install-agent.sh --dry-run`, and `sudo ./scripts/install-agent.sh`. Existing Linux power opt-in and keys are retained unless explicitly disabled. Verify `systemctl is-active linux-host-agent.service` and `curl -fsS http://127.0.0.1:8765/v2/metrics`; the new JSON includes `memory_used_bytes`, `memory_available_bytes`, `disk_root_used_bytes` and `disk_root_available_bytes` where measurable, in addition to the existing total and percentage fields.

**Windows:** Open elevated PowerShell in the newly extracted Windows ZIP and run `.\\scripts\\Verify-Package.ps1`, `.\\scripts\\Install-WindowsAgent.ps1 -WhatIf`, then `.\\scripts\\Install-WindowsAgent.ps1 -HubIPv4 $hubIPv4` with the actual hub IP. **If power management was enabled previously, add `-EnablePower` on this new install**. The Windows installer intentionally disables remote power unless this switch is supplied, but preserves existing identity and key under `%ProgramData%\\ComputerHostAgent`.

The publisher's existing memory and disk capability definitions/translations/presentations were extended and **validated on a real hub** before preparing this release. Beta testers should **not** register/edit capabilities themselves. The first German translation upsert briefly returned HTTP 422 immediately after the schema update, but succeeded on retry. If an upgraded agent reports the new bytes but SmartThings still shows blank values, verify driver installation and try a normal hub reboot to refresh cached capability metadata before deleting/re-pairing anything.
