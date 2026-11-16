# Native Windows Host Agent — v0.2.0-alpha.1

Companion to **Computer Host LAN v0.5.1-beta.1**, sharing protocol v2 and `_computerhost._tcp` discovery with the Linux agent.

## Verified versus not verified

The source **compiles and runs** in GitHub Actions on Windows Server 2025 (x64 .NET 10). Contract tests, HMAC/replay protection, Win32 metrics, HTTP smoke, self-contained publishing, LocalService installation, protected state and PowerShell 5.1 opt-in/opt-out passed: [CI run](https://github.com/ldeora/SmartThingsEdgeDrivers/actions/runs/43827358333). ARM64 builds cross-publish but have not been executed. **No physical Windows 11 SmartThings hub pairing, native DNS-SD interoperability or real power-cycle test has yet passed.**

## Build

```powershell
dotnet build .\ComputerHost.WindowsAgent\ComputerHost.WindowsAgent.csproj -c Release
dotnet run --project .\ComputerHost.WindowsAgent.Tests\ComputerHost.WindowsAgent.Tests.csproj -c Release
.\scripts\Publish-WindowsAgent.ps1 -Runtime win-x64
.\scripts\Smoke-WindowsAgent.ps1 -Executable "$PWD\publish\win-x64\ComputerHost.WindowsAgent.exe"
```

Builds use .NET 10. Published x64 binaries are self-contained, so ordinary testers do not need the SDK. The smoke test disables mDNS and never sends valid power commands.

## Install (Windows 11 x64, elevated PowerShell)

From the same directory as the published bundle and installer scripts:

```powershell
.\scripts\Install-WindowsAgent.ps1 -WhatIf
.\scripts\Install-WindowsAgent.ps1 -HubIPv4 <YOUR_SMARTTHINGS_HUB_IPV4>
Get-Service ComputerHostAgent
Invoke-RestMethod http://127.0.0.1:8765/v2/info
.\scripts\Get-WolDiagnostics.ps1
```

Omit `-HubIPv4` to allow `LocalSubnet` on a Private Windows firewall profile. The installer **does not** configure Windows mDNS/UDP5353, firmware WOL or sleep policies. The service runs as `NT AUTHORITY\LocalService`, persists identity under `%ProgramData%\ComputerHostAgent` and does not enable power on a fresh install or ordinary reinstall.

## Optional power management

After SmartThings discovery and telemetry succeed, save all open work and ensure physical recovery is possible. Run the installer again with `-EnablePower`, read the 64-hex token **privately** from `%ProgramData%\ComputerHostAgent\control-token`, and enter it into the SmartThings `controlKey` preference with `allowPowerCommands` enabled. Never post the key, HMAC signatures, IP/MAC or raw logs publicly.

The Windows native operations are **best-effort** and hardware-dependent: reboot first, suspend/WOL second, shutdown/WOL last. A 202 response means accepted for scheduling, not confirmed completion. Windows S0/S3/S4/S5 support, Fast Startup and WOL depend on policy, NIC and firmware.

Reinstall **without** `-EnablePower` to disable remote power. Uninstall with `.\scripts\Uninstall-WindowsAgent.ps1`; add `-PurgeState` **only** to intentionally remove persistent identity and key. No binary is signed. The public-beta ZIP and permanent GitHub release are pending.

See [platform installation](../INSTALLATION.md), [tester checklist](docs/HARDWARE-TEST-MATRIX.md) and [security/privacy](../docs/beta/SECURITY-AND-PRIVACY.md).
