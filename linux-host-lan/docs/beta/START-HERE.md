# Linux Host LAN — closed beta tester guide

**Beta-engineering candidate 0.3.1-beta.1**. This source bundle contains the **unchanged** Linux Agent 0.3.0 and SmartThings Edge Driver 0.2.9. The candidate's new content is release tooling, CI, testing guidance and documentation. All power transitions have been tested on Gentoo hardware only; other distribution coverage is currently smoke-test planning, not certification.

## Before you begin

- A SmartThings hub supporting LAN Edge drivers on the same trusted LAN as the Linux computer. Your hub must be enrolled in the publisher's **beta Edge Driver channel** (the invitation URL is not part of this archive).
- Linux running **systemd as PID 1**, Python **3.10+**, and root access for installation. No pip packages required at runtime. For ordinary first-time pairing **Avahi/mDNS is required in the current beta**. An advanced manual discovery fallback exists, but requires editing the driver's `manual_hosts.lua` and repackaging it; the device preference `hostOverride` only works **after** a device has been discovered.
- For **power control**, a machine with supported Linux shutdown/suspend, a WOL-capable Ethernet NIC, and firmware settings that permit wake. Many Wi-Fi adapters do not support wake from power-off. Use monitoring-only first; shut down only when you have local physical access.
- Ensure that TCP **8765** is accessible only to the SmartThings hub/trusted LAN. For discovery, multicast UDP **5353** must work between hub and host. This installer does **not** modify the firewall or the network manager.
- Have an independent way of accessing the PC before testing suspend, WOL and shutdown. Save your work, and do not run shutdown tests on production systems or unattended servers.

## 1. Inspect the archive, check requirements (ordinary user)

Download the `linux-host-agent-bundle-v0.3.1-beta.1.tar.gz` (or ZIP) from the project's GitHub Release, verify its SHA-256 checksum against the release checksums, extract it, and run:

```sh
cd linux-host-agent-bundle-v0.3.1-beta.1
./scripts/preflight.sh
./scripts/install-agent.sh --dry-run
```

Check the `preflight.sh` output. **Do not install** when a required dependency is marked `[FAIL]`, and do not ignore warnings about Python versions. Check the source/release checksums independently before executing code with root privileges. Never pipe an internet download into `sh`.

Useful distribution prerequisites (package names/versions can vary):

| Family | Example prerequisites | Notes |
| --- | --- | --- |
| Debian/Ubuntu | `sudo apt install python3 systemd avahi-daemon ethtool passwd` | Avahi and ethtool optional; on minimal/container installs systemd might not be PID 1 |
| Fedora | `sudo dnf install python3 systemd avahi ethtool shadow-utils` | SELinux/firewalld require independent validation |
| RHEL/Rocky/Alma 9 | Python 3.11/3.12 parallel installation | The distro default Python 3.9 does **not** meet the current 3.10+ requirement; select explicitly with `--python` |
| Arch | `sudo pacman -S python systemd avahi ethtool shadow` | Service enablement is the operator's responsibility |
| openSUSE | use `zypper` to install Python 3.10+, Avahi and ethtool | Exact package name varies by release; verify active network manager |
| Gentoo | Python 3.10+, systemd profile, Avahi, ethtool | Fully functional reference installation tested on real hardware |

## 2. Install monitoring-only first (root)

```sh
sudo ./scripts/install-agent.sh
```

Record the **recovery snapshot path** shown by the installer. The systemd service will run under the restricted `linuxhost` account. Power control is disabled on a clean installation. Existing upgraded installations preserve their prior power configuration.

```sh
systemctl status linux-host-agent.service
curl -fsS http://127.0.0.1:8765/v1/info | python3 -m json.tool
./scripts/beta-report.sh
```

The `/v1/info` payload includes identifiers: do **not** paste it unredacted into public issues. Use `beta-report.sh` instead.

## 3. Pair with SmartThings

Install the publisher's **Linux Host LAN** Edge Driver on your hub via its official beta channel. Use SmartThings **Scan for nearby devices** to discover the agent via `_linuxhost._tcp`. If that fails, check that Avahi is running and UDP 5353 multicast is available between hub and host. The fallback in `edge-driver/src/linuxhost/manual_hosts.lua` is currently developer-oriented: it requires inserting the host address in source, repackaging the Edge Driver and rerunning discovery. The `hostOverride` setting applies only to an **already discovered** device, so it cannot solve initial discovery. Power and telemetry are handled locally between hub and Linux, but SmartThings device-state events are reported through the platform. Do not create your own custom capability namespace—the published driver uses publisher-owned capability IDs.

Check that the device has a main Switch, CPU temperature, Host Status, CPU/memory/disk usage, uptime and three load averages. Successful app and cloud presence is not proof that the optional power actions are enabled.

## 4. Opt into power actions (optional; restricted trusted LAN only)

Read the safety notes in `SECURITY-AND-PRIVACY.md` first. Choose the actual wired interface, for example `enp3s0`, and examine the effect before applying changes:

```sh
sudo ./scripts/configure-wol.sh --interface enp3s0
sudo ./scripts/install-agent.sh --enable-power --wol-interface enp3s0
```

Enable persistent WOL only after examining the configuration with `--apply`, or by using the installation script's **explicit** `--configure-wol` option. Do not override existing network-manager configuration. The root-only file `/var/lib/linux-host-agent/control-token` contains the HMAC key; enter it privately in the SmartThings device settings. Never upload it, display it in a public terminal recording, or include it in a bug report.

Afterwards verify that `ethtool` reports `Wake-on: g` (root may be necessary) **after reboot**, and test from a machine that can recover locally if WOL fails.

## 5. Validate and report

Run `TESTER-CHECKLIST.md` from least disruptive to most disruptive. Record whether the host is merely unreachable or truly powered off; no network-only integration can always distinguish these with certainty. Generate a redacted report:

```sh
./scripts/beta-report.sh > beta-report.txt
```

Review the report before sending it. See `FEEDBACK-AND-SUPPORT.md` for a feedback template and data-removal guidance.

## 6. Upgrade, rollback and removal

Use the included installer for upgrades only; do not simultaneously install a native DEB/RPM package on an installation managed by the script. The installer preserves persistent ID, HMAC key, WOL and SmartThings device settings.

```sh
sudo ./scripts/rollback-agent.sh --backup /var/backups/linux-host-agent/snapshot-EXAMPLE
sudo ./scripts/uninstall-agent.sh --confirm
```

The rollback path must be your **own** snapshot. Uninstall keeps persistent identity/key and WOL settings by design. Removing those requires a separate, deliberate procedure. See `INSTALLATION.md` in the integration root for details.

## Scope of the beta

Working on Gentoo hardware: monitoring, mDNS, authenticated reboot/shutdown/suspend, WOL after suspend/shutdown and correct state recovery. On other distributions, start with read-only monitoring; independently validate systemd integration, firewall, MAC policies, Avahi and WOL. No claims are made for OpenRC/SysVinit, containers without systemd PID 1, or remote access across untrusted networks.
