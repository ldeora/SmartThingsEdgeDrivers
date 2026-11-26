# Computer Host LAN — quick start (published v1.0.0-rc.2)

**Development candidate v1.0.0-rc.3 — not published.** Linux/Edge 0.4.7-rc.3, Windows 0.2.8-rc.3, protocol v2. Release preparation and physical acceptance are pending; rc.2 remains the latest published release. See the [rc.3 release notes](RELEASE-NOTES-v1.0.0-rc.3.md).

**Available now: [v1.0.0-rc.2 GitHub prerelease](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.2)** (published November 21, 2026 UTC from commit `72e4a99c4b2e8f958ce771152826319318d0d537`). Integration **1.0.0-rc.2**, Linux/Edge **0.4.6-rc.2**, Windows **0.2.7-rc.2**, protocol v2 unchanged. Download matching checksummed unsigned Windows packages or Linux source; do not use transient CI artifacts. [v0.5.5-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.5-beta.1) remains the Windows hardware-tested rollback baseline. SmartThings channel deployment is separate.

**rc.1 is not equivalent to rc.2:** Published rc.1 predates PRs #56–#59 and **does not have the hardened Windows ProgramData/control-token checks** ([#32](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/32)). Avoid rc.1 authenticated power commands on a shared PC with untrusted local users: inspecting `%ProgramData%\ComputerHostAgent` cannot prevent its fresh-install race. Published rc.2 includes the fix, but **real Windows 11 acceptance remains pending**. Review [known rc.1 issues](../../SECURITY.md#known-issues-in-the-published-rc1) and [rc.2 notes](RELEASE-NOTES-v1.0.0-rc.2.md).

**Requirements:** A SmartThings hub with LAN Edge support; computer and hub on a trusted private LAN; mDNS/UDP 5353 for automatic discovery and TCP 8765 from hub to computer (or your configured port). Never forward the agent's HTTP port to the Internet.

## Windows 11 x64

1. Download `computer-host-lan-v1.0.0-rc.2-windows-x64-unsigned-setup.exe` and `SHA256SUMS.txt` from the [same versioned release](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.2). Verify SHA-256, then start Setup as administrator. The installer remains **unsigned**; Windows may show a publisher/SmartScreen warning. Do not use the older rc.1 Setup to test the new security protections.
2. On **SmartThings hub**, confirm the detected hub. If discovery fails, use **Search again**, enter the hub IPv4, or deliberately choose **Advanced options → Allow connections from devices on my local network** (Private profile only).
3. Leave **Power management** off for initial monitoring. Follow the **Connect to SmartThings** screen. You can reopen these instructions from the Start Menu.
4. In SmartThings, use the [existing channel invitation](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20), enroll your hub if necessary, install **Computer Host LAN** and choose **Add device → Scan nearby**. Do **not** delete or re-pair an already installed computer device.
5. Check CPU, memory, system disk, uptime and online state in SmartThings. Optional power commands require opt-in on the computer **and** the matching control key in SmartThings settings. Save work and keep physical access before testing.

**Public-network troubleshooting:** Windows inbound access is restricted to **Private** networks, including the LocalSubnet fallback. If the computer is on a Public network, the agent's local health test can pass while hub connections fail. Check `Get-NetConnectionProfile` and, only on a trusted home LAN, change the hub-facing network to **Private** in Windows Settings. Setup never opens Public access or changes the Windows network profile.

**Existing Windows installation:** Run the newer Setup.exe **over** the current installation, including ZIP/PowerShell installations. Do not uninstall first or remove `%ProgramData%\ComputerHostAgent`. Setup is designed to retain the UUID, secret, configuration, custom port and previous power preference. If Setup fails, preserve the rollback snapshot; use the matching ZIP's `Restore-WindowsAgentUpgrade.ps1` rather than deleting state. The Windows ZIP is a fallback, not the preferred installation route.

## Linux (systemd)

Download the **matching v1.0.0-rc.2 source ZIP from the published release**.
These Linux commands apply only to that immutable release. They must not
be used to elevate main or a development source archive, which now
refuses legacy mutations. The standalone Linux installer is not yet available as a release.
The [planned rc.3 Linux installer Quick Start](LINUX-INSTALLER-QUICK-START.md)
describes the future flow, not a currently available download. For planned
rc.3 Windows changes see [Windows Quick Start](WINDOWS-QUICK-START.md).
The [maintenance guide](UPGRADE.md) and [troubleshooting](TROUBLESHOOTING.md)
also describe planned rc.3, not changes to published rc.2.
Linux needs Python 3.10+, systemd and Avahi.
From the extracted **published rc.2** source directory:

```sh
./scripts/preflight.sh
./scripts/install-agent.sh --dry-run
sudo ./scripts/install-agent.sh
systemctl status linux-host-agent.service
curl -fsS http://127.0.0.1:8765/v2/info
```

The installer retains the existing installation identity, key and opt-in configuration. Linux power and Wake-on-LAN configuration are optional and hardware-dependent.

## Feedback and limitations

For one-round verification, use the [short RC checklist](RC-ACCEPTANCE.md). Report the actual **OS, agent version, Edge driver version and result** (PASS/FAIL/NOT TESTED), particularly initial Windows installer rendering, hub discovery/retry, in-place upgrade, service restart and SmartThings device continuity. A Windows 11/SmartThings hardware result is not equivalent to CI. **Do not share IP/MAC addresses, installation IDs or control keys.** Full instructions: [installation and recovery](../../INSTALLATION.md).
