# Linux Host LAN integration — beta-engineering candidate 0.3.1-beta.1

**Start here:** [`docs/beta/START-HERE.md`](https://github.com/ldeora/SmartThingsEdgeDrivers/blob/97b078727180096631ca52b7892f168086d0490b/computer-host-lan/docs/beta/START-HERE.md). This release contains the **unchanged** tested Linux Agent **0.3.0** and Edge Driver **0.2.9**. New work is distro-test automation, release tooling, privacy-safe reporting and volunteer documentation. Do not publish as an unrestricted public beta until `docs/beta/PUBLICATION-GATES.md` has been satisfied, especially the copyright-holder license decision. Testing described in the compatibility matrix is evidence-specific; a source-only container smoke pass is not a systemd or hardware validation.

---

# Linux Host LAN v0.3.0 — security and installation preview

**Development preview, not public stable.** Agent **v0.3.0**;
SmartThings Edge Driver **v0.2.9** (unchanged); API protocol **v1**.
The complete live power-control and monitoring workflow was verified on Gentoo
with Agent v0.2.2. The hardened agent has only passed local automated tests;
its Gentoo rollout and cross-distro service/SELinux tests remain to be done.

## Start here

Read **[INSTALLATION.md](INSTALLATION.md)** for safe preflight, preview,
installation, upgrade, rollback and uninstallation. Read
**[SECURITY-HARDENING.md](https://github.com/ldeora/SmartThingsEdgeDrivers/blob/97b078727180096631ca52b7892f168086d0490b/computer-host-lan/SECURITY-HARDENING.md)** and
**[VALIDATION.md](VALIDATION.md)** for limits and remaining release gates.

No reinstall or repackaging of the already-working Edge Driver is required.
The agent retains UUID, authentication key, and WOL interface configuration.
The installer does **not** edit firewall rules, WOL persistence or OS Python
symlinks. Power-control enablement is opt-in and preserved on upgrades.

```sh
./scripts/preflight.sh
./scripts/install-agent.sh --dry-run
sudo ./scripts/install-agent.sh --enable-power --wol-interface enp3s0
```

`enp3s0` is an illustrative interface name. Review all scripts before running
as root; never share the key or raw signed requests. Do not expose TCP 8765 to
untrusted networks. See the full installation and security guides.

---

# Linux Host LAN for SmartThings — v0.2.11 (release engineering preview)

## November 2026 release engineering — integration v0.2.11

**Not a public release.** This source update **does not change** the live Linux
Agent (v0.2.2) or the proven SmartThings Edge Driver (v0.2.9). It adds a
read-only prerequisite checker, Python 3.10+ selection, genericized examples,
compatibility research, packaging strategy and security review. Do not reinstall
working components on your test system merely to update documentation.

From the extracted integration directory, check prerequisites without root:

```sh
./scripts/preflight.sh
./scripts/preflight.sh --interface enp3s0       # replace with your NIC
```

On RHEL 9-like hosts, the default `python3` is 3.9 and is **not compatible**.
The installer can select a compatible parallel interpreter (`python3.11` or
`python3.12`) or accept `--python /absolute/path/to/python3.11`. It never
changes distribution `python3` symlinks.

Read [RELEASE-BRIEF.md](RELEASE-BRIEF.md),
[DISTRO-MATRIX.md](https://github.com/ldeora/SmartThingsEdgeDrivers/blob/97b078727180096631ca52b7892f168086d0490b/computer-host-lan/DISTRO-MATRIX.md),
[PACKAGING-STRATEGY.md](https://github.com/ldeora/SmartThingsEdgeDrivers/blob/97b078727180096631ca52b7892f168086d0490b/computer-host-lan/PACKAGING-STRATEGY.md),
[SECURITY-REVIEW-RELEASE.md](https://github.com/ldeora/SmartThingsEdgeDrivers/blob/97b078727180096631ca52b7892f168086d0490b/computer-host-lan/SECURITY-REVIEW-RELEASE.md) and
[RELEASE-PLAN.md](RELEASE-PLAN.md) before deploying beyond a trusted LAN.

**Public end users will eventually install the Edge driver through our
published SmartThings channel.** They must not create or re-register the six
`oceancircle09600` capabilities themselves. Current registration commands are
intended for the publisher/developer only.


**Status: DEVELOPMENT PREVIEW / RELEASE ENGINEERING.** Full power cycling,
monitoring and v0.2.9 state transitions have been validated on **one Gentoo
Linux host** (agent interruption/recovery, reboot, suspend/WOL, shutdown/WOL).
The new v0.2.11 portability tooling has only been tested locally; **no claims
of Debian, Ubuntu, Fedora, RHEL, openSUSE or Arch real-hardware compatibility.**

**v0.2.10 scripts-only fix:** Read-only WOL checks now distinguish permission-denied or incomplete ethtool queries from unsupported hardware. If netlink WOL_GET cannot be read by an unprivileged user, the scripts retry `ethtool --disable-netlink` (ioctl); otherwise they report an access/unknown error with explicit `sudo ethtool IFACE` instructions. New mock regressions cover this. **No hub or agent update is necessary for this fix; only `scripts/configure-wol.sh` and `scripts/diagnose.sh` change.** Leave a working systemd `.link` WOL configuration untouched.

**v0.2.9:** Separates acknowledged power-action evidence from ambiguous connectivity errors, persists pending actions/boot ID across hub restarts, reduces duplicate status events, improves uptime formatting and includes English/German capability translations, optional WOL persistence installer, safe diagnostic tools and release checklist. **Do not remove or re-pair the existing SmartThings device.** The Linux agent remains v0.2.2, and no custom-capability schemas change. Updated capability *presentations and translations* require explicit developer-account CLI updates; Edge packaging alone will not publish those files.

**v0.2.8 hotfix:** Advanced custom attributes now emit real events (callable Edge attribute tables were rejected by the previous guard). Failed emission attempts are retried. Existing custom capability registrations and the advanced profile are unchanged; upgrade the Edge driver without removing your SmartThings device. Agent v0.2.2 remains installed.

**v0.2.7 telemetry release:** The included agent remains **v0.2.2**; the Edge Driver advances to **v0.2.7** with the advanced monitoring profile, six custom capabilities, all three load averages, readable uptime, and profile migration for existing LAN devices. Register the capabilities and presentations in the developer account before packaging the advanced profile.

**v0.2.6 agent fix:** The agent now re-detects its WOL Ethernet interface when `/v1/info` is requested, so a route that appears after daemon startup is no longer missed permanently. If using several network interfaces (for example Ethernet plus Tailscale), pin the intended physical NIC with `sudo ./scripts/install-agent.sh --enable-power --wol-interface enp3s0` (replace the interface name). This preserves the stored installation UUID, HMAC key, and existing SmartThings device. Updating only the agent does not require repackaging or reinstalling the Edge Driver.

**v0.2.5 WOL metadata hotfix:** Newly created or upgraded devices can temporarily lack stored WOL MAC metadata. The Edge driver now refreshes `/v1/info` when required, persists validated metadata, and retries metadata recovery at the Wake button. This requires the agent to be reachable at least once; if it is currently powered off and no MAC was saved, set the `WOL MAC override` preference. The Linux agent remains v0.2.1. This change does not yet establish the cause of a separate SmartThings mobile-app network error.

**v0.2.4 switch/power-state update:** Main `switch` now tracks computer reachability instead of freezing indefinitely in ON after an external shutdown. A failed HTTP health check with `Connection refused` keeps the switch ON, because the remote TCP stack responded. Repeated transport timeouts or host-unreachable errors turn the switch OFF by default (configurable). This is an **inference of logical availability, not an electrical power measurement**: network outages can look identical to shutdown. Reboot keeps the switch ON throughout its expected outage; WOL and shutdown do not publish optimistic state changes. The Linux agent remains **v0.2.1**, so no agent reinstall is required. Existing devices, profile names, control keys and installation IDs are preserved.

This project integrates one or more Linux computers with SmartThings through a local
LAN Edge driver and a small Linux agent. It builds on the discovery, persistent
identity and polling design of the earlier Davis AirLink Edge driver.

## Features

- Primary standard SmartThings **`switch`**: `on` sends Wake-on-LAN (WOL) from
  the hub; `off` sends an authenticated graceful shutdown request.
- Separate standard **`momentary`** actions for **Wake**, **Reboot** and **Suspend**.
- **`refresh`** and **`temperatureMeasurement`** (CPU temperature when present).
- Six custom SmartThings monitoring capabilities for host state, CPU %, memory
  %, installed RAM, root filesystem %, uptime, and 1/5/15-minute load averages.
- Human-readable uptime (for example `12d 4h`, or `45m`) plus numeric uptime and
  metric attributes that can be used as SmartThings Automation conditions.
- The base `linux-host` profile remains available as a standard-capability
  fallback; `linux-host-advanced` is selected by default and requires the six
  custom capabilities to be registered in the developer account first.
- Automatic mDNS discovery (`_linuxhost._tcp.local`), immutable installation
  UUID, configurable manual discovery, DHCP/IP rediscovery and persistent WOL
  metadata (MAC and broadcast).
- Host and SmartThings device states remain separate: losing the HTTP agent
  **does not mark the hub-side controller offline**.
- HMAC-SHA256 authenticated power control, short-lived one-use nonce, and an
  isolated **root-only power helper** exposed via a group-restricted Unix socket.
- No cloud service, MQTT broker, or third-party Python packages required.

## Downloads and layout

- `edge-driver/` — SmartThings Edge source and device profile.
- `agent/` — Python daemon, minimal power helper, systemd and Avahi files.
- `scripts/install-agent.sh` — optional systemd installation helper with opt-in WOL setup.
- `scripts/configure-wol.sh` — independent WOL capability/persistence checker (dry-run by default).
- `scripts/diagnose.sh` — read-only non-secret support diagnostics.
- `scripts/publish-presentations.sh` — opt-in update of existing capability presentations and en/de labels.
- `STATE-MODEL.md`, `PORTABILITY.md`, `RELEASE-READINESS.md` — release guidance.
- `tests/` — agent HTTP/security tests, Lua vector tests, syntax/profile checks.
- `TESTING.md`, `SECURITY.md`, `PROTOCOL.md` — field testing and API docs.

Every release ZIP contains one versioned **top-level directory**, following
our established SmartThings Edge driver packaging convention.

## Requirements

- Linux with Python 3.10+, `/proc` and `/sys`; **systemd required** for the supplied power
  helper and service units; Avahi (or manual host discovery) for mDNS.
- SmartThings Hub with LAN Edge support and working hub-to-agent LAN TCP
  connectivity (default TCP **8765**).
- SmartThings CLI is needed **by the publisher/developer** to package and
  register capabilities. Public beta testers will enroll in a shared Edge
  Driver Channel invitation; they will not need the CLI for installation.
- UDP 5353 multicast between agent and hub for mDNS, unless using manual hosts.
- Wake-on-LAN-capable motherboard/NIC and suitable firmware, BIOS/UEFI,
  Ethernet and network settings for WOL. USB/Wi-Fi/some low-power systems may
  not wake via WOL.

## Installation

**v0.2.1 systemd startup fix:** the agent only orders itself after `network.target`
and no longer pulls in `network-online.target`. If you previously installed v0.2.0
and `systemctl enable --now linux-host-agent.service` waited for
`systemd-networkd-wait-online`, interrupt the installer and re-run the updated
installer. The systemd unit will be replaced and reloaded. Do not globally
disable `systemd-networkd-wait-online` just to work around this service.


### A. Linux host

From the extracted **complete integration** directory:

```sh
sudo ./scripts/install-agent.sh  # monitoring + WOL; power control remains disabled if never enabled
# Opt-in separately for authenticated shutdown/reboot/suspend:
# sudo ./scripts/install-agent.sh --enable-power
# Optional, recommended for multi-interface computers such as examplehost:
# sudo ./scripts/install-agent.sh --enable-power --wol-interface enp3s0
# Optional persistent WOL setup (explicitly opt in only if required):
# sudo ./scripts/install-agent.sh --enable-power --wol-interface enp3s0 --configure-wol
sudo systemctl enable --now avahi-daemon.service  # if Avahi is installed
sudo systemctl status linux-host-agent.service
sudo systemctl status linux-host-agent-power.socket
```

The helper creates the dedicated **`linuxhost` system user** if necessary, copies
Python and unit files, enables the agent and (only when power control was opted in) the restricted power socket, and
installs Avahi advertisement when its directory exists. Remote shutdown,
reboot and suspend remain disabled until `--enable-power` is explicitly used. It **does not** install
Avahi, alter your firewall, or enable WOL in your NIC. On Gentoo, install Avahi
using `emerge --ask net-dns/avahi` and verify your Python path.

To install without the script, use the contents of `scripts/install-agent.sh`
as a checklist. `--wol-interface IFNAME` persists a systemd environment override in `90-wol-interface.conf` (without overwriting the power-control drop-in); it is optional, and rerunning the installer without this option retains an existing pin. The agent also supports `--wol-interface` directly and the `LINUX_HOST_WOL_INTERFACE` environment variable. To enable remote power later, run `sudo ./scripts/install-agent.sh
--enable-power` from the extracted project. This installs a systemd drop-in
that adds `--enable-power-control` and restarts the agent. To disable remote
power again, remove the drop-in and restart the agent. WOL from the hub is
unaffected.

Inspect agent:

```sh
curl -fsS http://127.0.0.1:8765/v1/info
curl -fsS http://127.0.0.1:8765/v1/health
curl -fsS http://127.0.0.1:8765/v1/metrics
avahi-browse -rt _linuxhost._tcp
```

Copy the control key into the SmartThings device preference **Power control
key** only after discovery:

```sh
sudo cat /var/lib/linux-host-agent/control-token
```

The **installation ID and control key are persistent**. Retain these files
through agent upgrades so the same SmartThings device keeps working. Treat
`control-token` as a password; do not put it in tickets, forum posts or logs.

### B. SmartThings Edge driver

For a fresh install, first register and verify the six custom capabilities and their
presentations as described in `edge-driver/custom-capabilities/REGISTER.md`.
The advanced profile references those account-level capabilities and cannot be
installed before they exist. **Already registered v0.2.8 capabilities must NOT be created again.**
For new en/de localization and short presentation labels, first review
`./scripts/publish-presentations.sh` (dry-run), then explicitly run
`./scripts/publish-presentations.sh --apply`. These calls modify shared cloud
resources under your developer namespace; they are separate from the driver update.

Then, from the extracted **complete integration** directory:

```sh
smartthings edge:drivers:package edge-driver/ --install
smartthings edge:drivers:logcat
```

If using the separate Edge driver ZIP, run the following from its extracted parent directory:

```sh
smartthings edge:drivers:package ./linux-host-edge-driver-v0.2.9 --install
```

Start a **Scan nearby** in the SmartThings app while the Linux agent is online.
It should create `Linux <hostname>` with one main Switch and three momentary
components. Open device settings and set:

- `allowPowerCommands = true` **only** after verifying the helper and key.
- `controlKey` to the generated 64-character hex value (never logged).
- Optional WOL MAC, broadcast and UDP port if the agent's values are missing or
  your network requires overrides.

For a manual first discovery if multicast is blocked, edit
`edge-driver/src/linuxhost/manual_hosts.lua` before packaging:

```lua
return { "192.168.50.25:8765" }
```

After initial discovery, a per-device static host override is available in
SmartThings settings. The IP address is *not* used as the permanent device ID.

### C. Wake-on-LAN on the target

Check your Ethernet interface, for example:

```sh
ethtool enp3s0 | grep -E 'Supports Wake-on|Wake-on'
sudo ethtool -s enp3s0 wol g
```

`Wake-on: g` indicates magic-packet wake is enabled. Persist the setting with
your Linux network manager or distribution-specific configuration. Configure
firmware/UEFI wake support and check whether the NIC remains powered during
suspend and soft shutdown. The SmartThings hub must be able to deliver UDP
broadcast to the **same L2 subnet** (or through a configured WOL relay).

## Switch and availability semantics (v0.2.4+)

| Observation or action | Main Switch | Advanced host status |
|---|---|---|
| `/v1/health` responds successfully | **ON** | `running` |
| Switch ON while host is unresponsive | Send WOL; **remain OFF** until health succeeds | `starting` |
| Switch OFF while agent responds | Send **authenticated graceful shutdown**; wait before reporting OFF | `stopping` |
| Authenticated shutdown accepted, then health fails repeatedly | **OFF** (inferred) | `stopped` |
| Suspend action accepted, then health fails repeatedly | **OFF** (inferred) | `suspended` |
| External/manual shutdown; repeated timeouts / host unreachable | **OFF** (default; inferred) | `unreachable` |
| Agent stopped or crashed; TCP connection **refused** | **ON** (likely host still running) | `unreachable` |
| Reboot accepted, temporarily unreachable | **ON** until reboot finishes or command tracking expires | `rebooting` |
| Health comes back, manually or following WOL | **ON** (confirmed) | `running` |
| HTTP protocol failure or unexpected device UUID | Retain previous state | `unreachable` |

**Limits of a two-state switch:** a machine that is off and one whose network has
failed can both look like a timed-out TCP connection. The default `Switch off
when host unreachable` preference reports OFF after the configured number of
consecutive host-unreachable polls; disable this preference to retain the last
known switch state on unexpected outages. `Connection refused` (as seen when
stopping the agent on Gentoo) is treated as evidence that a host TCP stack is
responding. Network firewalls, proxies and gateways can invalidate these
heuristics, so neither a timeout nor a refusal is absolute electrical proof.
The advanced host-status capability communicates the uncertainty.

The `Unreachable after failed polls` preference (default **3**) and `Availability
polling (seconds)` (default **30**) determine the delay before inference.
After a confirmed running state, a manual shutdown generally takes about
three failed polls to report OFF, depending on when the shutdown completes.

A rejected OFF command must not change the reported status; check the control
key and `Enable shutdown/reboot/suspend` preference. A WOL packet being sent
does not prove a boot, and the driver only emits ON when the agent answers.
There is a dedicated Wake button as a fallback. The SmartThings LAN device
itself remains **online** even if the Linux target is powered off so WOL works.
The driver logs recovery after failed polls and republishes the last observed
switch state after a driver restart.

The telemetry release needs no new agent endpoint or token: **agent v0.2.1
and later already expose the required `/v1/metrics` fields**. Agent v0.2.2 is
recommended because it also fixes dynamic WOL-interface detection. The existing
Switch, authentication, and power-control behavior remain unchanged.

## Enhanced telemetry profile (v0.2.7)

The Linux agent already supplies CPU utilization, memory utilization, total
physical memory, root filesystem utilization, all three load averages, uptime,
CPU temperature, and boot ID through `/v1/metrics`. The Edge Driver now exposes
those values through six custom SmartThings capabilities, while retaining the
standard `temperatureMeasurement` capability for CPU temperature. Numeric
metrics and host status are exposed as Automation conditions as well as current
state in the device detail view.

The enhanced profile uses the developer namespace `oceancircle09600` by
default. Confirm that namespace and register the six capability definitions and
presentations before packaging the driver. Follow
`edge-driver/custom-capabilities/REGISTER.md` exactly. Custom capabilities are
account-level SmartThings resources; the hub does not import them from local
JSON files in the driver ZIP.

The package contains two profiles:

- `linux-host` — standard Switch, Refresh, CPU temperature and power buttons;
  no custom capability dependency.
- `linux-host-advanced` — the same controls plus host status, CPU, memory,
  installed RAM, root filesystem usage, uptime, and 1/5/15-minute load averages.

`src/linuxhost/constants.lua` selects `linux-host-advanced` by default. After
capability registration, package and install with:

```sh
smartthings edge:drivers:package edge-driver/ --install
```

Existing LAN devices request migration to the advanced profile with
`device:try_update_metadata`. The driver does not delete or recreate them, so
the installation UUID, control key, device ID, WOL metadata, and existing
preferences remain intact. If custom capabilities are not wanted, change
`C.PROFILE_NAME` back to `linux-host` before packaging; the standard profile
continues to provide Switch, CPU temperature, Refresh and power controls.

The agent does not need an upgrade for this telemetry release: **Linux Host
Agent v0.2.2 already supplies every metric used here**. The Edge Driver polls
metrics at the configured telemetry interval (default 60 seconds). CPU usage
may be null in the first sample because it is calculated from two `/proc/stat`
snapshots; the next sample supplies the first value. Rapidly changing custom
metric events are marked non-displayed in history to avoid flooding event
history, but their latest values remain available in device state.

See `PROTOCOL.md` for the API fields and `TESTING.md` for the staged hub test
plan. Custom capability definitions and presentations must be validated on the
user's SmartThings developer account and mobile app before public release.

## Upgrades, boundaries, and public release

The agent's `api_version` stays at 1, and `v0.1.0` agent identities are
preserved. When upgrading from the read-only version, restart the daemon and
then refresh/reinstall the Edge driver as appropriate. Existing devices
retain their device network IDs **only if the original installation-ID file is
retained and readable by the new service user**. Version 0.1.0 used a systemd
`DynamicUser`; migration to the static `linuxhost` account requires checking
state-directory ownership and possibly copying the UUID file from
`/var/lib/private/linux-host-agent/` to the static user’s state directory.
Do not delete or regenerate the original ID. Matching devices should pick up
MAC/metadata on the first successful poll. Device profile migration from `presenceSensor` to `switch`
**may require explicit migration or re-adding the device**; this must be
verified on a hub. Do not casually delete the installation UUID as a workaround.

This is **not** a finished, security-audited public release. See `SECURITY.md`.
The code has been tested locally, but **hub runtime, app presentation, real WOL,
real power helper, multi-host discovery and upgrade migration have not yet been
validated with physical hardware**. Do not run untested shutdown automations
against machines holding important unsaved work.

## Credits

The LAN driver uses proven design patterns from our Davis AirLink LAN Edge
driver v1.0.3, including its mDNS scanning, stable IDs, persistent fields,
background polling and rediscovery; computer-specific power and telemetry
features are new.

## Project publication notes

Before a public release, select and add an explicit open-source license,
verify the capability namespace owner agrees to maintain the capability IDs,
settle user-facing component names/translations, and publish installation and
migration steps tested on real hub firmware. No license is granted or implied
merely by distributing this development archive.


### v0.2.8 telemetry hotfix

If custom telemetry capabilities are visible but empty after updating to v0.2.7,
install the v0.2.8 Edge Driver package. v0.2.7 erroneously required the
SmartThings custom attribute constructor to be a Lua function, although the Edge
library exposes callable attribute tables. v0.2.8 fixes the guard and retries
failed metric emissions. The existing capability registrations, advanced device
profile and Linux Agent v0.2.2 are unchanged. Do not remove the device.

## Development / troubleshooting

For non-secret diagnostics on the Linux host:

```sh
./scripts/diagnose.sh --interface enp3s0
```

For WOL dry-run evaluation without changing system configuration:

```sh
./scripts/configure-wol.sh --interface enp3s0
# If an old ethtool lacks the legacy ioctl option, inspect privileges:
sudo ethtool enp3s0 | grep -i 'Wake-on'
```

The Linux kernel's WOL_GET netlink API may require CAP_NET_ADMIN even for queries.
A failed query does not establish a lack of WOL hardware support. v0.2.10
tries the ioctl fallback and reports errors without modifying your NIC.

Run all source tests using `python3 -m unittest discover -s tests -q`.
Read `STATE-MODEL.md` for *inferred vs observed* state semantics, `PORTABILITY.md`
for supported hosts and `RELEASE-READINESS.md` for the public-beta checklist.
