# Windows graphical installer (Inno Setup 7) — development

The graphical installer is **not** the currently published Windows ZIP. It is a
separate beta experiment until real Windows 11 fresh-install, ZIP-to-Setup
migration, upgrade, uninstall and multi-hub discovery are tested.

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
purging the UUID, boot session or HMAC key. It stops the service before file
replacement, performs an account/path ownership check, and reuses service
registration. The separate power-management page preserves the prior opt-in by default;
new installations start with monitoring only. On successful installation,
the **Connect to SmartThings** page confirms the local agent health and
provides an **Open driver channel** button, a copyable invitation link,
and instructions to add the computer through SmartThings > Add device >
Scan nearby. If power is enabled, Setup reads (without logging) the existing
or newly generated 64-hex control key, displays it masked by default and
allows revealing or copying it on explicit request. On a monitoring-only
installation, the private key controls are not shown. Clipboard copying is
opt-in, never automatic. A Start Menu link opens the installed
Docs/CONNECT-TO-SMARTTHINGS.html guide for later reference; it contains no
private key.

The uninstall path uses the existing PowerShell uninstaller with
`-KeepProgramFiles`, allowing Inno to remove tracked files while preserving
persistent UUID/control key in ProgramData. The legacy script itself remains
supported. No global execution-policy changes, firmware changes or dynamic
port forwarding. No automatic release, signing or channel update.

## Building on Windows

```powershell
dotnet publish ..\HubDiscovery\ComputerHost.HubDiscovery.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:DebugType=none -o ..\publish\hub-discovery
# The agent already publishes to windows-agent/publish/win-x64.
iscc.exe .\ComputerHostLAN.iss
```

Run from `computer-host-lan/windows-agent/installer`. The CI job builds and
executes the discovery helper's self-test before invoking Inno Setup 7. A
GitHub Windows runner **cannot** confirm discovery of a real SmartThings hub.
Real Windows 11 beta testing is required before any public Setup.exe release.
