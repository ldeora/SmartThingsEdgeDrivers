# Computer Host LAN v0.5.5-beta.1 — stabilization and upgrade reliability

This beta contains the hardening changes merged in [PR #19](https://github.com/ldeora/SmartThingsEdgeDrivers/pull/19).
The previous [v0.5.4-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.4-beta.1) remains available for rollback. No stable-release certification is implied.

## Component versions

| Component | This candidate | Previous published beta |
| --- | --- | --- |
| Integration | **v0.5.5-beta.1** | v0.5.4-beta.1 |
| Windows agent | **v0.2.4-beta.1** | v0.2.3-beta.1 |
| Linux agent | **v0.4.3-beta.1** | v0.4.2-beta.1 |
| SmartThings Edge driver | **v0.4.3-beta.1** | v0.4.2-beta.1 |
| HTTP protocol | **v2, unchanged** | v2 |

## What's improved

- **Windows guided upgrades:** The installer snapshots the existing application and its managed firewall rule before replacing files. A detected failure attempts to restore the old files, configuration, rule and service. The snapshot is removed after a successful upgrade. Power-loss interruptions and unexpected process termination still require caution and additional physical testing.
- **Settings preserved:** Both Windows installation methods preserve existing custom `appsettings.json`; the installer and diagnostics respect nondefault listener ports, and the firewall rule is configured for that port. The ZIP/PowerShell fallback still requires `-EnablePower` on every upgrade if power commands should remain active. The graphical wizard preserves the previous power selection.
- **Authentication and privacy:** Existing Windows control-token files are restricted to protected system/service principals on upgrade. Routine WOL/discovery logs omit raw addresses and identifiers. Power remains opt-in, HMAC-authenticated and restricted to trusted private networks.
- **More accurate SmartThings status:** Quickly resumed machines and canceled shutdowns no longer leave prolonged stale transitional states. Human-readable component labels make Wake, Restart and Sleep easier to identify. Existing component IDs and device identities are retained.
- **Version and packaging consistency:** Native Windows smoke checks the real `/v2/info.agent_version`; source tests compare agent/driver/installer versions with `release.json`. Windows ZIP and Setup include third-party provenance notices.

## Download this beta

GitHub prerelease: [Computer Host LAN v0.5.5-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.5-beta.1). Verify that the release and its attached checksums are published before downloading.

Expected assets:

| File | Purpose |
| --- | --- |
| `computer-host-lan-v0.5.5-beta.1-windows-x64-unsigned-setup.exe` | Recommended Windows 11 x64 installation and upgrade wizard |
| `computer-host-lan-v0.5.5-beta.1-windows-x64-unsigned.zip` | Windows PowerShell fallback, verification and diagnostics |
| `computer-host-lan-v0.5.5-beta.1-source.zip` | Linux source, systemd installer and SmartThings Edge driver source |
| `computer-host-lan-v0.5.5-beta.1-documentation.zip` | Versioned install, compatibility, safety and tester documentation |
| `SHA256SUMS.txt` | Checksums covering the four deliverables |

The Windows executable is self-contained and unsigned; verify checksums and expect possible SmartScreen warnings. No .NET SDK is required by testers.

## Upgrade instructions

**Windows:** On a physically accessible test computer, download and checksum-verify the release Setup.exe; run it over the existing installation **without uninstalling or deleting the SmartThings device**. Preserve `%ProgramData%\ComputerHostAgent` and its identity/token. Check `Get-Service ComputerHostAgent`, `/v2/info` and telemetry; exercise restart and recovery. The new GUI preserves power-management opt-in; the PowerShell fallback requires `-EnablePower` again. Full instructions: [INSTALLATION.md](../../INSTALLATION.md).

**Linux:** Extract the matching release source ZIP, run `./scripts/preflight.sh` and `./scripts/install-agent.sh --dry-run`, then upgrade with `sudo ./scripts/install-agent.sh`. It preserves persistent identity and existing power-helper opt-in; validate `/v2/info` and `/v2/metrics`. Protocol v2 compatibility with older agents is maintained.

**SmartThings Edge driver:** This beta **does contain driver changes**. The [verified SmartThings Edge channel](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20) remains the installation route. The publisher must package and assign the v0.4.3-beta.1 driver to the **existing** SmartThings channel, preserving its driver ID and registered custom-capability schema. Testers should update the driver through the existing channel, not create a duplicate device. No automatic channel deployment occurs as part of GitHub CI.

## Verification and limitations

PR #19 and the post-merge `main` commit `0978dd75557ce8b3b38693cdf740aaa2585ab0fa` passed four Windows GUI, Windows agent, Linux and packaging CI workflows. The **versioned v0.5.5-beta.1 build requires passing tests on its own final source commit** before publication.

A Windows 11 Pro volunteer reported successful GUI installation, upgrade and accurate CPU/RAM/disk figures for **v0.5.4-beta.1**. This does *not* verify the new 0.5.5 rollback changes on physical hardware. Windows Wake-on-LAN remains dependent on firmware, NIC and sleep state. The read-only HTTP telemetry endpoint is not TLS-encrypted; use only a trusted private LAN and never forward the agent's listener port to the internet.

Please report upgrade/recovery results in the [SmartThings Community thread](https://community.smartthings.com/t/st-edge-computer-host-lan-bring-windows-and-linux-computers-into-smartthings-public-beta/312605), using the [tester checklist](TESTER-CHECKLIST.md) and redacting IDs, addresses and control keys. The previous release remains available for rollback, and the first stable release still requires real-hardware testing, licensing/provenance sign-off and an explicit signing policy.
