# Computer Host LAN v0.5.4-beta.1 — guided Windows setup joins the public beta

This update makes the **Windows 11 x64 graphical Setup.exe** the recommended installation and upgrade method. The original self-contained Windows ZIP and PowerShell scripts remain available as a fully supported alternative and recovery method. **Linux and the existing SmartThings Edge driver do not change.** Protocol v2, the current device identity, monitoring, telemetry, and the separate Linux Host LAN project are unaffected.

## Components

- Integration: **v0.5.4-beta.1**
- Windows agent: **v0.2.3-beta.1** (same runtime behavior and protocol as v0.2.2-beta.1; new Windows setup distribution)
- Linux agent: **v0.4.2-beta.1** (unchanged)
- SmartThings Edge driver: **v0.4.2-beta.1** (unchanged)
- Protocol: **v2** (unchanged)

## Choose a download

[GitHub prerelease v0.5.4-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.4-beta.1), **once published**:

| Asset | Purpose |
| --- | --- |
| `computer-host-lan-v0.5.4-beta.1-windows-x64-unsigned-setup.exe` | **Recommended** Windows 11 x64 installer and upgrade tool |
| `computer-host-lan-v0.5.4-beta.1-windows-x64-unsigned.zip` | Windows PowerShell installation, diagnostics and fallback |
| `computer-host-lan-v0.5.4-beta.1-source.zip` | Linux systemd/Avahi agent source and installer |
| `computer-host-lan-v0.5.4-beta.1-documentation.zip` | Reference, onboarding and test documentation |
| `SHA256SUMS.txt` | SHA-256 checksums for all four files |

Use the **attached release assets**, not automatically generated GitHub Source code ZIPs or temporary Actions artifacts. Both Windows distributions are **unsigned**; SmartScreen may warn. Use only downloads from the official release and verify their hashes. No .NET SDK is needed for Setup.exe or the prebuilt Windows ZIP.

## Recommended Windows installation

1. Verify the Setup.exe hash and run it as Administrator on Windows 11 x64.
2. Select a SmartThings hub found via DNS-SD/mDNS, retry discovery or manually enter the hub IPv4. If mDNS fails, use the explicit **Allow connections from devices on my local network** fallback; it scopes the Windows firewall to Private networks / LocalSubnet and does not solve multicast routing.
3. On the optional power page, begin with **monitoring only**. Fresh installs disable remote shutdown, reboot and suspend. Existing installations preserve their former power selection unless you change it.
4. The **Connect to SmartThings** page links to the [verified SmartThings Edge driver channel](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20) and explains installing **Computer Host LAN** and **Scan nearby**. If power was enabled, a separate page allows deliberate display/copying of the private 64-hex key for the SmartThings device preferences.
5. Verify the Windows Service and SmartThings device metrics. For physical power testing, save work and ensure the PC is recoverable.

**In-place upgrades from the original PowerShell/ZIP method and from earlier Setup builds are supported.** Do not first uninstall, purge `%ProgramData%\ComputerHostAgent`, delete the SmartThings computer or re-pair. The wizard preserves installation identity, control token, existing `appsettings.json`, and power preference. Normal removal through Windows **Installed apps** stops/removes the agent service, firewall rule and application files while retaining state for a later installation.

**PowerShell fallback:** Run the version-matched Windows ZIP's `scripts/Verify-Package.ps1` and `scripts/Install-WindowsAgent.ps1` as Administrator. Supply `-HubIPv4` for your hub; `-EnablePower` **must be specified again with each PowerShell reinstall/upgrade** if it was previously enabled. This differs intentionally from the graphical installer's preservation of the existing power preference. See [full installation instructions](../../INSTALLATION.md).

## Validation

[PR #17](https://github.com/ldeora/SmartThingsEdgeDrivers/pull/17) was merged after successful native **Windows Server 2025** CI tests. These tested the Welcome screen, hub-address input, complete wizard navigation, optional power/key display and clipboard copying, monitoring-only installation, LocalSubnet fallback, ZIP-to-Setup migration, Setup upgrades, retained UUID/key/custom configuration, removal, and refusal to uninstall an unrelated same-name Windows Service. The exact published build also requires passing release-asset packaging and checksums from one commit.

**Not yet established on physical Windows 11:** discovery of zero/one/multiple real hubs; Wi-Fi/VLAN/multicast variations, display-scale diversity, SmartScreen reputation, power/WOL behavior across firmware and adapters, and all long-running recovery paths. These are intentional beta test objectives, not assertions of completed certification. One earlier Windows 11 volunteer reported that the *previous* ZIP-based agent installed and ran, including shutdown/reboot/suspend. This does not validate the new Setup.exe on that hardware.

## Security and reporting

The agent listens on TCP **8765** on a trusted LAN; mDNS uses UDP **5353**. Do not expose the service to the internet. The optional authenticated power feature is disabled by default, secrets must never enter bug reports or screenshots, and HTTP has no transport encryption. The installer is unsigned and provides no automatic updates.

Please share Windows 11 setup and upgrade results in the [Computer Host LAN Community beta thread](https://community.smartthings.com/t/st-edge-computer-host-lan-bring-windows-and-linux-computers-into-smartthings-public-beta/312605), using the [test checklist](TESTER-CHECKLIST.md) and sanitizing device/host/network identifiers and logs. The previous [v0.5.3-beta.1 release](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.3-beta.1) remains available for rollback.
