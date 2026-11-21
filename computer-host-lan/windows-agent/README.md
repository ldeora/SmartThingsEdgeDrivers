# Native Windows Host Agent — v0.2.6-rc.1

**Published GitHub prerelease:** [Integration v1.0.0-rc.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.1) (November 20, 2026, UTC), Windows agent 0.2.6-rc.1 and Linux/Edge 0.4.5-rc.1; protocol v2 unchanged. The [previous v0.5.6-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.6-beta.1) remains available, while [v0.5.5-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.5-beta.1) is the tested rollback baseline. GitHub publication and SmartThings driver deployment are separate, and rc.1 still needs new Windows 11 hardware acceptance.

Windows 11 testing previously confirmed a v0.5.5 graphical upgrade, preserved identity and SmartThings device, accurate metrics, service recovery and working power/WOL controls on one computer. The v0.5.6 hardening and new RC still require physical validation. Windows Server CI covers agent and native GUI tests; ARM64 is cross-built only. The RC includes the v0.5.6 privilege/ACL, NIC and mDNS improvements plus first-search display and rescan usability fixes.

**rc.1 versus `main`:** The published rc.1 Setup.exe and ZIP were built before PRs #56–#59. In particular, **rc.1 does not contain the Windows ProgramData/control-token hardening from PR #58** ([#32](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/32)); those changes are on `main` and planned for rc.2, which has not been published. Do not enable rc.1 power control on shared Windows machines with untrusted local user accounts. See the [rc.1 known issues and precautions](../SECURITY.md#known-issues-in-the-published-rc1). Checking for an unexpected existing state folder helps identify concerns but cannot eliminate the fresh-install race.

## Build

```powershell
dotnet build .\ComputerHost.WindowsAgent\ComputerHost.WindowsAgent.csproj -c Release
dotnet run --project .\ComputerHost.WindowsAgent.Tests\ComputerHost.WindowsAgent.Tests.csproj -c Release
.\scripts\Publish-WindowsAgent.ps1 -Runtime win-x64
.\scripts\Smoke-WindowsAgent.ps1 -Executable "$PWD\publish\win-x64\ComputerHost.WindowsAgent.exe"
```

Builds use .NET 10. Published x64 binaries are self-contained, so ordinary testers do not need the SDK. The smoke test disables mDNS and never sends valid power commands.

## Recommended graphical Windows x64 Setup.exe

Download the matching **v1.0.0-rc.1** Setup.exe from the [published GitHub prerelease](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.1) and verify its `SHA256SUMS.txt`; do not install ephemeral CI artifacts. The unsigned Setup is designed to preserve UUID, control key, custom configuration, listener port and power opt-in during in-place upgrades. **Do not delete or re-pair existing SmartThings devices.**

## ZIP / elevated PowerShell fallback

From the version-matched ZIP use elevated PowerShell (replace the hub IP):

```powershell
.\scripts\Verify-Package.ps1
.\scripts\Install-WindowsAgent.ps1 -WhatIf
.\scripts\Install-WindowsAgent.ps1 -HubIPv4 192.168.1.20
Get-Service ComputerHostAgent
Invoke-RestMethod http://127.0.0.1:8765/v2/info
```

Power commands are disabled by default and require explicit -EnablePower and a 64-character private key entered in the SmartThings device preferences. A PowerShell upgrade requires -EnablePower again to retain consent; the graphical installer preserves the previous selection. If Windows policy denies shutdown privileges, the agent keeps monitoring available but does not advertise power commands. The new Windows kit also includes Set-WindowsHubAddress.ps1 and Restore-WindowsAgentUpgrade.ps1 for guarded reconfiguration and recovery.

Do not expose the HTTP agent to the Internet or share the key. Real Windows WOL depends on NIC, firmware, and sleep/power state; one successful Windows 11 test is not a universal guarantee. Read [installation](../INSTALLATION.md), [installer details](installer/README.md), [test matrix](docs/HARDWARE-TEST-MATRIX.md) and [security notes](../docs/beta/SECURITY-AND-PRIVACY.md).
