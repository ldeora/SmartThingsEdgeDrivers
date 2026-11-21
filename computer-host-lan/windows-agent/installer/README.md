# Windows graphical installer (Inno Setup 7) — x64

**Unpublished rc.2 source candidate:** integration v1.0.0-rc.2, Windows agent 0.2.7-rc.2, Linux/Edge 0.4.6-rc.2, protocol v2 unchanged. **Latest published prerelease:** [v1.0.0-rc.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.1), which lacks the rc.2 Windows ProgramData and native power-acknowledgment fixes. **Windows 11 hardware-tested rollback baseline:** [v0.5.5-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.5-beta.1). Do not distribute temporary rc.2 CI artifacts.

Windows 11 Pro testing verified the v0.5.5 graphical upgrade, telemetry, recovery, power controls and Wake-on-LAN on one system. The RC includes the later upgrade-recovery and first-search display/rescan improvements; those changes still need physical Windows confirmation. Setup and ZIP remain unsigned. Firewall access is restricted to Private-profile hub connections by default; public Internet exposure is unsupported.

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
Real Windows 11 testing of the RC, including the original first-search rendering report, remains essential; passing CI is not physical certification.

## Upgrade recovery

v0.5.5 introduced a protected application/firewall snapshot and recovery from detected upgrade errors. The v0.5.6 and RC installers check for an abandoned snapshot **before stopping the service**, offers guarded recovery in interactive Setup, includes a manual restore script and verifies runtime protocol/version/identity before committing the snapshot. It also tightens IP parsing and provides a helper for updating the Private-profile firewall allow-list when a hub IP changes. Do not delete persistent UUID, key or rollback snapshot to bypass a recovery error.

Native CI exercises wizard navigation, upgrade/migration, clipboard, failed-install restore and uninstall safety, but it is not an independent real Windows 11 RC verification. For recovery instructions and third-party licensing see [installation](../../INSTALLATION.md) and [third-party notices](../../docs/beta/THIRD-PARTY-NOTICES.md).
