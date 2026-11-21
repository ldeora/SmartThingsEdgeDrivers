# Native Windows Host Agent — v0.2.7-rc.2 (published prerelease)

**Published [Computer Host LAN v1.0.0-rc.2](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.2)** November 21, 2026 UTC (immutable commit `72e4a99c4b2e8f958ce771152826319318d0d537`), Windows **0.2.7-rc.2**, Linux/Edge **0.4.6-rc.2**, protocol v2. The older [rc.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.1) lacks post-tag security fixes; [v0.5.5-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.5-beta.1) is the last independently Windows 11 hardware-tested fallback. **Real Windows 11 rc.2 acceptance remains pending.** Use published unsigned Setup/ZIP rather than temporary CI artifacts.

Earlier Windows 11 testing of v0.5.5 confirmed graphical upgrades, identity/SmartThings device preservation, monitoring, service recovery and power/WOL on one host. rc.2 adds protected ProgramData directory creation and owner/ACL/reparse checks, synchronous native shutdown/reboot acceptance and error handling, Private-network firewall guidance and discovery/Wake fixes. CI passed on Windows Server; ARM64 remains cross-build-only.

**Historical rc.1 warning:** rc.1 lacks PR #58's ProgramData security hardening ([#32](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/32)), so do not enable authenticated power on shared rc.1 Windows hosts with untrusted local users. A one-time state-directory check cannot eliminate the old fresh-install race. See [rc.1 security issues](../SECURITY.md#known-issues-in-the-published-rc1).

## Build

```powershell
dotnet build .\ComputerHost.WindowsAgent\ComputerHost.WindowsAgent.csproj -c Release
dotnet run --project .\ComputerHost.WindowsAgent.Tests\ComputerHost.WindowsAgent.Tests.csproj -c Release
.\scripts\Publish-WindowsAgent.ps1 -Runtime win-x64
.\scripts\Smoke-WindowsAgent.ps1 -Executable "$PWD\publish\win-x64\ComputerHost.WindowsAgent.exe"
```

Builds use .NET 10. Published x64 binaries are self-contained, so ordinary testers do not need the SDK. The smoke test disables mDNS and never sends valid power commands.

## Recommended graphical Windows x64 Setup.exe

Download the matching **v1.0.0-rc.2** unsigned Setup.exe and `SHA256SUMS.txt` from the [published GitHub release](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.2). Verify hashes, then run Setup over the existing installation (no uninstall). The installer should preserve UUID, key, custom listener port/configuration and power opt-in; **do not delete/re-pair existing SmartThings devices**. ZIP/PowerShell remains available as a fallback. Channel version and hub installation must be checked separately.

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
