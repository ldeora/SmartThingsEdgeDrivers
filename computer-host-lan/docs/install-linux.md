# Install on Linux

Use the instructions matching the package you downloaded. Use only a trusted version-matched release installer, not a development source archive or ordinary CI artifact.

## 1. Prepare your computer

Use a Linux x86_64 (amd64) computer with systemd, Python 3.10+ and Avahi for
automatic discovery. Keep your SmartThings hub and computer on a trusted
private network. TCP 8765 (or your configured agent port) must be reachable
from the hub, and local multicast DNS (UDP 5353) must be available. Do not
forward the agent port to the Internet. See
[Avahi and firewall troubleshooting](troubleshooting.md#firewall-and-avahi)
for distribution-specific instructions. See the [support table](../README.md#platforms-and-requirements).

## 2. Download and verify the installer

Download `computer-host-lan-v1.0.0-rc.3-linux-x64-unsigned-installer`
and `SHA256SUMS.txt` from the [v1.0.0-rc.3 release](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.3)
into a private download directory. From that directory run:

```sh
sha256sum --check --ignore-missing SHA256SUMS.txt
```

Continue only if the exact installer filename reports **OK** and the command
succeeds. Checksums detect changed or corrupted downloads but do not prove
who published the file. The installer is unsigned; use a release you trust.
Rename the verified installer locally to `computer-host-linux-installer`
for the commands below.

## 3. Run Setup

As your ordinary user (do not prefix the executable with sudo):

```sh
chmod u+x ./computer-host-linux-installer
./computer-host-linux-installer
```

The full-screen terminal interface keeps setup, review and literal consent together; the actual administrator prompt appears on the ordinary terminal. On completion, review the structured result before exiting. A clean host opens setup directly. On an existing installation choose
**1 — Upgrade**; for retained data choose **1 — Install / reinstall**. Confirm or enter
your hub's IPv4, or choose it later. Leave remote power at its default for
initial monitoring; an existing power preference is retained unless changed.
Review the plan and type **INSTALL** (or **REUSE** for eligible retained rc.2 state) only if you agree to the changes. The
wizard then requests administrator authorization. You can cancel before
consent. The installer does not change firewall rules, start Avahi or pair
a SmartThings device. On a new installation with a suggested wired adapter,
Configure Wake-on-LAN is selected by default. Existing installations default
to Keep. Hardware support is checked after authorization; if the adapter
does not support magic packets or the check is unavailable (for example
ethtool is missing), the agent installs without configuring WOL and shows a
warning. If the optional network policy cannot be reviewed on a fresh setup,
the review offers installation with WOL left unchanged. Install ethtool
if missing and run setup again to enable WOL.

For plain-text prompts, run `./computer-host-linux-installer -accessible`.
For a real read-only plan, use `./computer-host-linux-installer -live -preview`.
For a simulated wizard, use `-demo`. The read-only plan and simulated
wizard never elevate; the accessible installation wizard still requires
explicit consent and administrator authorization.

## 4. Connect to SmartThings

Follow [SmartThings setup](smartthings.md#add-a-computer), then check CPU, memory, disk, uptime and Host Status. Use the installer's completion instructions to retrieve the private key if power is enabled. Never publish the key. If discovery fails, follow [troubleshooting](troubleshooting.md).

## Maintenance menu

Run `./computer-host-linux-installer` again as your normal user. The menu
uses fixed keys. In the full-screen menu, use Up/Down or a number to highlight a task, then Enter to select it. Esc or Q exits the menu without changes. Unavailable tasks may be shown disabled; read the reason before proceeding.
In accessible mode, type the number and press Enter; 0 or Enter alone exits.

| Key | Action |
| --- | --- |
| 1 | Upgrade / install bundled version, or install / reinstall if absent |
| 2 | Configure power or WOL through setup, or separately check/remove installer-owned WOL |
| 3 | Repair using the bundled version (existing agent) |
| 4 | Restore an earlier eligible backup |
| 5 | Recover an interrupted operation |
| 6 | Inspect installation status, read-only |
| 7 | Uninstall agent (existing agent); keep private state and backups |
| 0 | Highlight Exit; press Enter to leave without changes |

Selecting a task is not authorization. Follow its separate confirmation.
Inspect does not verify the protected journal; use `cli status` for that.
All existing flags remain available. See [all maintenance journeys](upgrade.md).

## What's installed and what stays on uninstall

The downloaded installer itself is not a resident service; the installer also provisions protected recovery components.
The agent uses the selected system Python (no additional PyPI runtime
packages). The following are the managed locations; optional files may
not be present on every computer.

| Location or component | Purpose | Normal uninstall |
| --- | --- | --- |
| `/opt/linux-host-agent/linux_host_agent.py`, `power_helper.py` | Agent and restricted power helper | Managed files removed |
| `/etc/systemd/system/linux-host-agent.service`, `linux-host-agent-power.service`, `linux-host-agent-power.socket` | Agent and opt-in helper units | Managed units removed |
| `/etc/systemd/system/linux-host-agent.service.d/enable-power.conf`, `90-wol-interface.conf` | Optional power and interface settings | Managed drop-ins removed |
| `/etc/avahi/services/linux-host-agent.service` | Discovery advertisement, if supported | Managed file removed |
| `linuxhost` service account | Restricted agent identity | Retained |
| `/var/lib/linux-host-agent` | Private persistent host identity and key | Retained |
| `/var/lib/linux-host-agent-installer/protocol` | Installer ownership/protocol marker | Retained |
| `/var/backups/linux-host-agent` | Private snapshots and recovery material | Retained |
| `/usr/libexec/computer-host-lan`, `/var/lib/computer-host-installer` | Trusted recovery helper, transaction and staging material | Retained as required for safe recovery |
| NetworkManager profile or per-MAC systemd .link rule | Persistent wired WOL, if configured | Retained unless separately authorized for removal |

The installer does not install firewall software, change firewall rules or start
Avahi. It does not pair devices. Administrator network policy not owned by
the installer is not removed.

## Enable power or Wake-on-LAN later

Choose **2 — Configure → 1 — Change power or WOL settings**, review
Enable/Disable/Keep and the interface choice, and explicitly consent with
INSTALL. This uses the bundled agent version, not a configuration-only
edit. Remote power is separate from Wake-on-LAN. When enabled on the host,
also configure the matching key and opt-in in [SmartThings](smartthings.md#optional-power-control).
A fresh installation suggests persistent wired WOL; upgrades keep the
existing settings. To change WOL, choose Configure in the WOL step.
To check or remove an installer-owned WOL configuration, choose the
separate Configure maintenance operation; removal requires REMOVE.
See [Wake-on-LAN troubleshooting](troubleshooting.md#sleep-or-wake-on-lan-not-working).

## Remove or reinstall

Choose **7 — Uninstall** and review the plan; type UNINSTALL only if you
intend to remove the agent. Normal removal keeps the identity, key and
backups for reinstall. For upgrade, repair, historical restore, interrupted
recovery and intentional fresh identity, see [maintenance](upgrade.md).
There is no supported automatic Linux purge of all recovery components.
Do not manually delete protected journals, staging files, helpers or backups
to bypass refusal. Seek support if you require complete removal beyond the
supported uninstall and private-state retirement procedure.
