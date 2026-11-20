# Windows graphical installer (Inno Setup 7) — public-beta installation method

> **Next candidate: Computer Host LAN v0.5.6-beta.1 (not yet published).** This single hardening candidate combines installer recovery and runtime resilience. Current published/tested beta: [v0.5.5-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.5-beta.1). [Candidate release notes](../../docs/beta/RELEASE-NOTES-v0.5.6-beta.1.md).


**Source candidate v0.5.5-beta.1 (not yet published):** this setup source includes the merged PR #19 upgrade recovery changes. The currently downloadable installer remains the previous v0.5.4-beta.1. Read the [candidate release notes](../../docs/beta/RELEASE-NOTES-v0.5.5-beta.1.md).

The graphical Windows x64 Setup.exe is the **recommended** installation and upgrade method in the published Computer Host LAN v0.5.4-beta.1 prerelease. Its [permanent release asset](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.4-beta.1) is separate from the existing supported PowerShell ZIP, which remains a fallback for troubleshooting. Both are unsigned; verify SHA-256 before running. A Windows 11 Pro volunteer has now reported real GUI installation and upgrade with accurate monitoring; broader hub-discovery topologies and hardware wake remain beta objectives. The native Windows Server 2025 CI has verified complete graphical navigation, clipboard copying, service upgrades, uninstall safety and ZIP migration.

## SmartThings hub selection

The wizard searches for the DNS-SD/mDNS service `_smartthings._tcp.local.`
using a standalone .NET 10 Zeroconf helper (NuGet package Zeroconf 3.7.16).
One response pre-fills the hub address; multiple responses are displayed in a
selector. A **Search again** button retries discovery. Users can always enter
an IPv4 address manually; if nothing is found, the installer exposes the
explicit **Allow connections from devices on my local network** fallback.
When discovery succeeds, that option stays under **Advanced options**.
Its implementation still uses the firewall LocalSubnet scope on Private
networks only; it is never selected silently. It never assumes that the
computer's default gateway is a SmartThings hub.

Hub discovery requires local multicast (UDP 5353) and may not work across
isolated Wi-Fi networks, VLANs, multicast filters or all future hub models.
There is no cloud API or SmartThings login/token. The address is used only
for the local Windows Firewall rule, not an authenticated connection to the hub.
Discovery matches the advertised service, not cryptographic hub identity; the
user should confirm the suggested hub when the LAN isn't fully trusted.

## Installation and migration

Inno installs the agent to `%ProgramFiles%\Computer Host Agent`, runs the
existing PowerShell installation logic with `-UseExistingFiles`, and registers
an entry in Windows Installed apps. Service name `ComputerHostAgent`,
firewall rule `ComputerHostAgent-TCP8765` and state
`%ProgramData%\ComputerHostAgent` are unchanged. The installer recognizes
ZIP/PowerShell installations at the same path and adopts them without
purging the UUID, boot session or HMAC key. Existing `appsettings.json` is also preserved during Inno upgrades instead of being silently replaced with the package default; the selected `EnablePowerControl` setting is then applied by the existing service installer. It stops the service before file
replacement, performs an account/path ownership check, and reuses service
registration. The separate power-management page preserves the prior opt-in by default;
new installations start with monitoring only. On successful installation,
the **Connect to SmartThings** page confirms the local agent health and
provides an **Open driver channel** button, a copyable invitation link,
and instructions to add the computer through SmartThings > Add device >
Scan nearby. If power is enabled, an additional **Power control key**
page reads (without logging) the existing or newly generated 64-hex control
key, displays it masked by default, and allows revealing or copying it on
explicit request. A monitoring-only installation skips this page entirely. Clipboard copying is
opt-in, never automatic. A Start Menu link opens the installed
Docs/CONNECT-TO-SMARTTHINGS.html guide for later reference; it contains no
private key.

The uninstall path uses the existing PowerShell uninstaller with
`-KeepProgramFiles`, allowing Inno to remove tracked files while preserving
persistent UUID/control key in ProgramData. The legacy script itself remains
supported. No global execution-policy changes, firmware changes or dynamic
port forwarding. No automatic release, signing or channel update. Release publication remains a separate approved step.

## Building on Windows

```powershell
dotnet publish ..\HubDiscovery\ComputerHost.HubDiscovery.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:DebugType=none -o ..\publish\hub-discovery
# The agent already publishes to windows-agent/publish/win-x64.
iscc.exe .\ComputerHostLAN.iss
```

Run from `computer-host-lan/windows-agent/installer`. The CI job builds and
executes the discovery helper's self-test before invoking Inno Setup 7. A
GitHub Windows runner **cannot** confirm discovery of a real SmartThings hub.
Real Windows 11 beta testing remains an objective while Setup.exe is distributed in the public beta; stable-release certification is not implied.

## Merged upgrade recovery improvements (packaged in v0.5.5-beta.1 candidate)

The stabilization branch stages the previously installed application and its managed firewall configuration in an admin-protected sibling of the Program Files installation directory, before Inno replaces any files. On a detected post-install failure, a guarded helper restores the original application/configuration, firewall scope and stopped service. On success the snapshot is deleted. A CI failure-injection scenario checks recovery. This is an improvement over v0.5.4-beta.1 and is **not** a retroactive fix to its published Setup.exe. The helper must not touch the UUID or HMAC key in ProgramData. A canceled/aborted installation after preflight also attempts recovery, but power loss and unexpected Windows termination still require manual repair testing.

The enhanced installer reads a customized agent listener port for its local health check, and the PowerShell installer uses that same port for the Private-profile firewall rule. Both installation methods retain the previous settings; script-based upgrades still require an explicit `-EnablePower`. Dependency licensing is recorded in [third-party notices](../../docs/beta/THIRD-PARTY-NOTICES.md).
