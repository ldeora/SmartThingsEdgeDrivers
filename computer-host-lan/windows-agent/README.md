# Windows Host Agent — 0.2.0-alpha.1 (SOURCE-ONLY, UNVALIDATED)

Companion to **Computer Host LAN v0.5.1-dev.1**, using protocol v2 with the
Linux-validated v0.4.0-dev.1 Edge Driver. The Windows agent adds **opt-in,
best-effort** reboot, shutdown and suspend; Wake is sent by the SmartThings
hub using a candidate Ethernet MAC and broadcast address, not by the agent.

**This source is not Windows-build-validated or real-device tested.** The
Linux agent, Linux installation scripts and Lua driver source are unchanged.

## Build on Windows 11 (or GitHub Actions Windows Server 2025)

Install .NET 10 SDK, then in `windows-agent/`:

```powershell
dotnet build .\ComputerHost.WindowsAgent\ComputerHost.WindowsAgent.csproj -c Release
dotnet run --project .\ComputerHost.WindowsAgent.Tests\ComputerHost.WindowsAgent.Tests.csproj -c Release
.\scripts\Publish-WindowsAgent.ps1 -Runtime win-x64
.\scripts\Smoke-WindowsAgent.ps1 -Executable "$PWD\publish\win-x64\ComputerHost.WindowsAgent.exe"
```

The smoke test deliberately exercises monitoring-only mode, opt-in challenges,
and *invalid* signatures. It never submits a valid power request and must never
restart or shut down the CI runner. Native DNS-SD is disabled during CI smoke.

## Install on a test Windows PC (elevated PowerShell)

```powershell
.\scripts\Install-WindowsAgent.ps1 -WhatIf
.\scripts\Install-WindowsAgent.ps1                  # MONITORING ONLY
Get-Service ComputerHostAgent
Invoke-RestMethod http://127.0.0.1:8765/v2/info
.\scripts\Get-WolDiagnostics.ps1                   # read-only
```

To **explicitly enable** power control, after verifying monitoring, run:

```powershell
.\scripts\Install-WindowsAgent.ps1 -EnablePower
# Read privately on the PC and enter as SmartThings controlKey preference:
Get-Content "$env:ProgramData\ComputerHostAgent\control-token"
```

The installer generates a 256-bit key once and preserves it across upgrades.
It does not print the key. The state directory is ACL-restricted to SYSTEM,
Administrators and LocalService; no user documents or other files are modified.
Installing **without** `-EnablePower` leaves power disabled, including upgrades.

In SmartThings, enable the device's `allowPowerCommands` preference and set
`controlKey` to the private 64-hex key. Keep the correct WOL MAC/broadcast; an
Ethernet device detected by Windows is only a *candidate*, not verified wake
hardware. The shared driver performs the HMAC challenge and sends WOL packets.

On Windows, reboot/shutdown call `InitiateSystemShutdownEx` with a 15-second
countdown and **no forced application termination**; suspend calls
`SetSuspendState(false,false,false)` preserving wake events. The response
HTTP 202 means command *scheduled*, not that the PC has shut down. Power
operations can fail due to permissions, policy, interactive applications,
Modern Standby or firmware. There is no guarantee of wake after shutdown,
Fast Startup or S5. Test suspend/WOL before shutdown/WOL with local physical
recovery available. Do not disable Fast Startup automatically.

## Troubleshooting and removal

```powershell
.\scripts\Get-WolDiagnostics.ps1
Get-Service ComputerHostAgent
.\scripts\Uninstall-WindowsAgent.ps1 -WhatIf
.\scripts\Uninstall-WindowsAgent.ps1
```

The service runs as `NT AUTHORITY\LocalService`. The installer creates a
Private/LocalSubnet TCP-8765 firewall rule. Narrow to the hub's IPv4 address
where practical. No TCP port forwarding. Native DNS-SD on UDP 5353 may need
additional firewall configuration; this has not yet been verified.

The Power control key is stored in `%ProgramData%\ComputerHostAgent\control-token`.
**Never paste it into public logs or GitHub issues.** Do not distribute this
unsigned source build as a finished public release.

## Known limitations

- No real Windows compilation or actual SmartThings hub discovery test yet.
- No CPU temperature or Linux load averages in Windows.
- Windows boot-session GUID uses a persisted uptime heuristic. Fast Startup,
  hibernate, sleep and major clock adjustments need physical validation.
- No automatic installer code signing; Win32 mDNS callback behavior is unverified.
- Windows power state is inferred from network checks, not electrically measured.
- WOL is hardware/firmware dependent, especially from Fast Startup or S5.
- No TLS on local telemetry; power uses HMAC-SHA256 with 30-second one-time
  challenges but the network remains observable. Trusted LAN only.

See `docs/ARCHITECTURE.md` and `docs/HARDWARE-TEST-MATRIX.md`.
