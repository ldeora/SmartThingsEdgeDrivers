# Native Windows Host Agent — v0.2.5-beta.1 candidate

**Public and Windows 11 hardware-tested baseline:** [v0.5.5-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.5-beta.1). **Unpublished consolidated hardening candidate:** [v0.5.6-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.6-beta.1) in [PR #21](https://github.com/ldeora/SmartThingsEdgeDrivers/pull/21), Windows agent 0.2.5-beta.1, Linux and Edge 0.4.4-beta.1, protocol v2 unchanged.

The Windows 11 tester confirmed **v0.5.5**, not the new candidate: successful graphical upgrade, preserved identity/settings and SmartThings device, accurate CPU/memory/disk statistics, service recovery, Wake/Restart/Sleep controls and working WOL. Windows Server 2025 CI covers agent and native GUI scenarios; ARM64 is cross-built only. The v0.5.6 candidate introduces privilege preflight with monitoring-only fallback, service-SID ACL isolation, atomic identity creation, refreshed physical-NIC WOL metadata and resilient mDNS registration.

## Build

```powershell
dotnet build .\ComputerHost.WindowsAgent\ComputerHost.WindowsAgent.csproj -c Release
dotnet run --project .\ComputerHost.WindowsAgent.Tests\ComputerHost.WindowsAgent.Tests.csproj -c Release
.\scripts\Publish-WindowsAgent.ps1 -Runtime win-x64
.\scripts\Smoke-WindowsAgent.ps1 -Executable "$PWD\publish\win-x64\ComputerHost.WindowsAgent.exe"
```

Builds use .NET 10. Published x64 binaries are self-contained, so ordinary testers do not need the SDK. The smoke test disables mDNS and never sends valid power commands.

## Recommended graphical Windows x64 Setup.exe

Download the current [v0.5.5-beta.1 release](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.5-beta.1) and verify SHA256SUMS; do not use the proposed v0.5.6 link until published. The unsigned Setup preserves UUID, control key, custom configuration, listener port and power opt-in during an in-place upgrade. Existing SmartThings devices should not be deleted or re-paired.

## ZIP / elevated PowerShell fallback

From the version-matched ZIP use elevated PowerShell (replace the hub IP):

```powershell
.\scripts\Verify-Package.ps1
.\scripts\Install-WindowsAgent.ps1 -WhatIf
.\scripts\Install-WindowsAgent.ps1 -HubIPv4 192.168.1.20
Get-Service ComputerHostAgent
Invoke-RestMethod http://127.0.0.1:8765/v2/info
```

Power commands are disabled by default and require explicit -EnablePower and a 64-character private key entered in the SmartThings device preferences. A PowerShell upgrade requires -EnablePower again to retain consent; the graphical installer preserves the previous selection. On v0.5.6 a Windows policy denying shutdown privileges leaves monitoring enabled but power commands unavailable. The new Windows kit also includes Set-WindowsHubAddress.ps1 and Restore-WindowsAgentUpgrade.ps1 for guarded reconfiguration and recovery.

Do not expose the HTTP agent to the Internet or share the key. Real Windows WOL depends on NIC, firmware, and sleep/power state; one successful Windows 11 test is not a universal guarantee. Read [installation](../INSTALLATION.md), [installer details](installer/README.md), [test matrix](docs/HARDWARE-TEST-MATRIX.md) and [security notes](../docs/beta/SECURITY-AND-PRIVACY.md).
