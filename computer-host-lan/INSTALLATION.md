# Computer Host LAN — installation (protocol v2)

**Current state:** Development v0.5.1-dev.1, not yet a published GitHub prerelease. The host agent and SmartThings Edge Driver are installed separately. A verified developer-channel invitation for outside testers is **not yet available**.

## Before installation

Use a trusted private LAN and a SmartThings hub that supports LAN Edge drivers. Allow mDNS discovery (UDP 5353) and hub-to-host HTTP TCP 8765. Never forward TCP 8765 to the internet. Host and hub must be able to reach each other; multicast separation or client isolation can prevent discovery. Install the new `computer-host-lan` driver, not the original `linux-host-lan` driver. Publisher-owned `oceancircle09600` capabilities must be registered by the publisher; testers should not register any.

## Windows 11 x64 (first volunteers)

Download the **versioned Windows ZIP** from the future Computer Host LAN GitHub prerelease, verify the published SHA-256, and extract it without altering directories. The executable is self-contained (.NET runtime bundled); administrator rights are necessary to register a Windows Service.

From **elevated PowerShell** inside the extracted tester kit:

```powershell
.\scripts\Verify-Package.ps1
.\scripts\Install-WindowsAgent.ps1 -WhatIf
.\scripts\Install-WindowsAgent.ps1 -HubIPv4 <SMARTTHINGS_HUB_IPV4>
Get-Service ComputerHostAgent
Invoke-RestMethod http://127.0.0.1:8765/v2/info
Invoke-RestMethod http://127.0.0.1:8765/v2/health
Invoke-RestMethod http://127.0.0.1:8765/v2/metrics
```

Replace the placeholder with the actual hub IPv4 address. Omit `-HubIPv4` to permit `LocalSubnet` on **Private** Windows network profiles. The installer does not modify BIOS, Windows sleep/fast-startup options, WOL adapter configuration, or mDNS firewall policies. Windows DNS-SD discovery on real PC/hub networks still needs volunteer verification.

Once the SmartThings beta channel is published, enroll the hub, install the `Computer Host LAN` Edge Driver, and use SmartThings **Scan nearby**. The Windows profile omits CPU temperature and Linux load. If discovery fails, report it rather than disabling the firewall globally; `hostOverride` only works *after* first pairing.

**Optional authenticated power commands — test PC, saved work and physical recovery only:**

```powershell
.\scripts\Install-WindowsAgent.ps1 -EnablePower -HubIPv4 <SMARTTHINGS_HUB_IPV4>
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
