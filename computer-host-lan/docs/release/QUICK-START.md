# Computer Host LAN — quick start (v1.0.0-rc.1)

**Release-candidate preparation.** Download only from the **published GitHub prerelease** after it becomes available; a temporary GitHub Actions artifact is not a public installer. The [last published beta](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.6-beta.1) remains available, with [v0.5.5-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.5-beta.1) as the previously hardware-tested fallback. The RC's physical Windows 11 validation is still pending.

**Requirements:** A SmartThings hub with LAN Edge support; computer and hub on a trusted private LAN; mDNS/UDP 5353 for automatic discovery and TCP 8765 from hub to computer (or your configured port). Never forward the agent's HTTP port to the Internet.

## Windows 11 x64

1. Download `computer-host-lan-v1.0.0-rc.1-windows-x64-unsigned-setup.exe` and `SHA256SUMS.txt` from the same published RC release. Verify the SHA-256, then start Setup as administrator. The installer is **unsigned**; Windows may show a publisher/SmartScreen warning.
2. On **SmartThings hub**, confirm the detected hub. If discovery fails, use **Search again**, enter the hub IPv4, or deliberately choose **Advanced options → Allow connections from devices on my local network** (Private profile only).
3. Leave **Power management** off for initial monitoring. Follow the **Connect to SmartThings** screen. You can reopen these instructions from the Start Menu.
4. In SmartThings, use the [existing channel invitation](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20), enroll your hub if necessary, install **Computer Host LAN** and choose **Add device → Scan nearby**. Do **not** delete or re-pair an already installed computer device.
5. Check CPU, memory, system disk, uptime and online state in SmartThings. Optional power commands require opt-in on the computer **and** the matching control key in SmartThings settings. Save work and keep physical access before testing.

**Existing Windows installation:** Run the newer Setup.exe **over** the current installation, including ZIP/PowerShell installations. Do not uninstall first or remove `%ProgramData%\ComputerHostAgent`. Setup is designed to retain the UUID, secret, configuration, custom port and previous power preference. If Setup fails, preserve the rollback snapshot; use the matching ZIP's `Restore-WindowsAgentUpgrade.ps1` rather than deleting state. The Windows ZIP is a fallback, not the preferred installation route.

## Linux (systemd)

Download the **matching RC source ZIP** when published. Linux needs Python 3.10+, systemd and Avahi. From the extracted source directory:

```sh
./scripts/preflight.sh
./scripts/install-agent.sh --dry-run
sudo ./scripts/install-agent.sh
systemctl status linux-host-agent.service
curl -fsS http://127.0.0.1:8765/v2/info
```

The installer retains the existing installation identity, key and opt-in configuration. Linux power and Wake-on-LAN configuration are optional and hardware-dependent.

## Feedback and limitations

Please report the actual **OS, agent version, Edge driver version and result** (PASS/FAIL/NOT TESTED), particularly initial Windows installer rendering, hub discovery/retry, in-place upgrade, service restart and SmartThings device continuity. A Windows 11/SmartThings hardware result is not equivalent to CI. **Do not share IP/MAC addresses, installation IDs or control keys.** Full instructions: [installation and recovery](../../INSTALLATION.md).
