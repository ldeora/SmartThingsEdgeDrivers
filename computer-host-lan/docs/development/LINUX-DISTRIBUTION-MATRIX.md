# Linux distribution compatibility matrix

**Status:** planning and support reference, 2026-11-22.
**Scope:** the protocol-v2 Linux agent (`agent/`), the current manual installer
(`scripts/install-agent.sh`), optional WOL (`scripts/configure-wol.sh`) and the
planned Go wizard (`linux-installer/`).
**Evidence:** only Gentoo `hydra` is verified on real hardware. Every other
row is either tested in CI containers (no systemd PID 1, no Avahi or WOL) or
is an **expectation derived from the distribution's defaults**. Defaults vary
by edition, installer choices and image. Run `./scripts/preflight.sh` on the
actual machine; it is the authority, not this table.
**Roadmap:** how support is to be extended is described in the
[Linux distribution support plan](LINUX-DISTRIBUTION-PLAN.md).

## 1. What the agent and installer actually need

| Requirement | Needed for | Where it comes from | If missing |
| --- | --- | --- | --- |
| systemd as PID 1 | Install, service, power helper | `install-agent.sh` checks `/run/systemd/system` | **Blocked.** No OpenRC/runit/sysvinit support |
| Python **3.10+** | Agent, installer engine, read-only API | `python-selector.sh` tries `python3`, then `python3.14` … `python3.10` | Install a parallel Python package and pass `--python /absolute/path` if it is not found |
| `useradd`, `getent`, `install`, `systemctl` | Installer (checked) | shadow, glibc, coreutils, systemd | Installer stops before writing anything |
| `sed` | Preflight (checked) | sed | Preflight reports FAIL |
| `nologin` (or `/bin/false`) | Service account shell | util-linux / shadow | Falls back to `/bin/false` |
| Root privileges | Installing, upgrading, uninstalling, applying WOL | `sudo`, `su`, `doas`, `run0`, root shell | See §4. The installer checks the UID, **not** for `sudo` |
| systemd ≥ 242 | All hardening options in the units | `ProtectHostname=`, `RestrictSUIDSGID=` | Older systemd starts the service but ignores those two directives with a log warning |
| Avahi (`avahi-daemon`) + `/etc/avahi/services` | Automatic SmartThings discovery | Optional | Monitoring still works; add the device manually by IP in the Edge driver |
| `ethtool` | Any WOL check or change | Optional | `configure-wol.sh` exits; WOL cannot be configured |
| `nmcli` **or** `udevadm` | Persistent WOL | NetworkManager, or systemd-udev `.link` | NetworkManager active without `nmcli` → WOL step fails |
| `unzip` (or Python) | Extracting the release source ZIP | Optional | Use `python3 -m zipfile -e <zip> <dir>`, then run the scripts with `sh` (see §5) |
| `curl` | Only the post-install check in the docs | Optional | `python3 -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8765/v2/info').read().decode())"` |
| `avahi-browse` | Only the discovery check in the docs | `avahi-utils` / `avahi-tools` | Skip the check, or install the tools package |

The Go wizard does not change these needs. It is a static binary with no
library dependencies, but it calls the same Python engine.

## 2. Matrix: mainstream systemd distributions

Legend: ✅ present by default · ⚠️ depends on edition or install choices ·
❌ not present by default (installable) · ⛔ blocks installation.

| Distribution | Releases | Python ≥ 3.10 by default | Privilege tool by default | Avahi by default | WOL backend | Firewall by default | MAC policy | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Gentoo** (systemd profile) | rolling | ✅ | ❌ `su` only; `sudo`/`doas` optional | ⚠️ USE/emerge choice | systemd-networkd `.link` (verified) | none | none | **Verified on hardware** (`hydra`) |
| **Debian** | 12, 13 | ✅ 3.11 / 3.13 | ⚠️ **No `sudo` if a root password was set during install**; use `su -` | ⚠️ desktop tasks yes; server/minimal no | NetworkManager (desktop) or udev `.link` (ifupdown server) | none | AppArmor | CI containers |
| **Ubuntu** | 24.04, 26.04 LTS | ✅ | ✅ `sudo` (first user) | ⚠️ Desktop yes; **Server no** | Desktop NetworkManager; Server netplan → udev `.link` | `ufw` installed, inactive | AppArmor | CI containers |
| **Ubuntu** | 22.04 LTS | ✅ 3.10 | ✅ `sudo` | ⚠️ as above | as above | as above | AppArmor | Expected (not in CI) |
| **Linux Mint / Pop!_OS** | Ubuntu 22.04/24.04 bases | ✅ | ✅ `sudo` | ✅ usually | NetworkManager | ⚠️ check `ufw status` | AppArmor | Expected (Ubuntu base) |
| **LMDE** | 6, 7 | ✅ (Debian 12/13 base) | ✅ `sudo` | ✅ usually | NetworkManager | ⚠️ check `ufw status` | AppArmor | Expected (Debian base) |
| **Raspberry Pi OS** | Debian 12/13 bases | ✅ | ✅ `sudo` | ✅ (`raspberrypi.local`) | NetworkManager | none | none | Expected; agent only. Pi Ethernet WOL is generally **not** available |
| **Fedora** Workstation | 43, 44 | ✅ | ✅ `sudo` (admin user) | ✅ active | NetworkManager | firewalld; Workstation zone allows ports 1025–65535 and mDNS | **SELinux enforcing** | CI containers |
| **Fedora** Server | 43, 44 | ✅ | ✅ `sudo` (admin user) | ⚠️ often not active | NetworkManager | **firewalld blocks 8765/tcp** | **SELinux enforcing** | CI containers (Fedora image) |
| **RHEL / AlmaLinux / Rocky** | 10 | ✅ 3.12 | ✅ `sudo` (if admin was set) | ❌ install `avahi` | NetworkManager | **firewalld blocks 8765/tcp** | **SELinux enforcing** | Expected |
| **RHEL / AlmaLinux / Rocky** | 9 | ⚠️ **`python3` is 3.9**; install `python3.11` or `python3.12` | ✅ `sudo` | ❌ install `avahi` | NetworkManager | **firewalld blocks 8765/tcp** | **SELinux enforcing** | Expected; selector finds the parallel Python |
| **RHEL / AlmaLinux / Rocky** | 8 | ⚠️ **3.6**; install `python3.11`/`python3.12` | ✅ `sudo` | ❌ | NetworkManager | firewalld | SELinux | Not recommended: systemd 239 skips two hardening options |
| **Arch Linux** | rolling | ✅ | ❌ **`base` has no `sudo`**; root login or `su` | ❌ install `avahi`, enable daemon | depends on chosen network stack | none | none | Expected |
| **Manjaro / EndeavourOS** | rolling | ✅ | ✅ `sudo` | ⚠️ often installed, check that the daemon is enabled | NetworkManager | ⚠️ Manjaro may enable `ufw` | none | Expected |
| **openSUSE Tumbleweed** | rolling | ✅ | ⚠️ `sudo` present but **may ask for the root password** (`targetpw`) | ✅ usually | NetworkManager (desktop) / wicked (server) | **firewalld active** | **SELinux on new installs** | Expected |
| **openSUSE Leap** | 16.0 | ✅ | ⚠️ as Tumbleweed | ✅ usually | NetworkManager | **firewalld active** | SELinux | Expected |
| **openSUSE Leap** | 15.6 | ⚠️ **`python3` is 3.6**; install `python311`/`python312` | ⚠️ as above | ✅ usually | wicked or NetworkManager | **firewalld active** | AppArmor | Expected via parallel Python. Leap 15.6 is at or near end of life: prefer 16.0 |
| **Debian** | 11 | ⛔ 3.9, no supported 3.10+ package | ⚠️ as Debian | — | — | — | — | Unsupported (end of life) |

**wicked (openSUSE server):** `configure-wol.sh` only knows NetworkManager or
systemd-udev `.link` files. On a wicked-managed host it falls through to the
`.link` path. That may work, but it is untested and wicked can override it.

## 3. Unsupported or blocked layouts

| Distribution family | Reason | What would be needed |
| --- | --- | --- |
| Alpine, Void, Devuan, Artix, Gentoo OpenRC profile, Slackware, antiX, MX (sysvinit default) | No systemd PID 1 | Separate OpenRC/runit service and privilege model (non-goal for first release) |
| NixOS | `/etc/systemd/system` and users are declarative; imperative writes are lost or refused | A NixOS module |
| Fedora Atomic (Silverblue, Kinoite, Bazzite), other ostree images | `/opt` is a symlink to `var/opt`; the installer's link check refuses it (by design) | A layout-aware install path, e.g. `/var` or `/usr/local` staging, designed and tested separately |
| openSUSE MicroOS / Aeon, Ubuntu Core, SteamOS, other image-based systems | Read-only `/usr`, transactional package installs, snaps or vendor images | Untested; do not claim support |
| WSL, containers, chroots | systemd is often not PID 1; WOL and power do not apply | Monitoring may run manually; not a supported install target |

## 4. Hosts without `sudo`

The manual installer only needs to run with **UID 0**. It does not call
`sudo` itself; the documentation just uses `sudo` as the example. Any of
the following work. Always give an absolute path, because a login shell
changes the working directory.

| Method | Typical on | Command (run from the extracted source folder) |
| --- | --- | --- |
| `su -` (login shell) | Debian with a root password, Gentoo, Arch, openSUSE | `su - -c "cd '$PWD' && ./scripts/install-agent.sh"` |
| `doas` | Some Arch/Gentoo setups | `doas ./scripts/install-agent.sh` |
| `run0` (systemd ≥ 256 with polkit) | Recent Fedora, Arch, Debian 13, Ubuntu 26.04 | `run0 ./scripts/install-agent.sh` |
| Root console / SSH as root | Servers | `cd /path/to/source && ./scripts/install-agent.sh` |

**Debian pitfall:** plain `su` (without `-`) keeps the user's `PATH`, which on
Debian does not include `/usr/sbin`. The installer then stops with
`Required command missing: useradd`, before changing anything. Use `su -`
as shown above.

**openSUSE pitfall:** `sudo` may ask for the **root** password instead of
yours (`Defaults targetpw`). That is expected, not an error.

Do **not** install `sudo` only for this project if the administrator has
chosen not to use it. The methods above are equivalent for the installer.

## 5. Missing helper packages

Only Python 3.10+ is required beyond the base system. The rest is optional.

| Family | Python (if too old or absent) | Discovery | WOL | Convenience |
| --- | --- | --- | --- | --- |
| Debian / Ubuntu / Mint / Raspberry Pi OS | `python3` | `avahi-daemon` (+ `avahi-utils`) | `ethtool` | `unzip curl` |
| Fedora / RHEL 10 | `python3` | `avahi` (+ `avahi-tools`) | `ethtool` | `unzip curl` |
| RHEL / Alma / Rocky 9 | `python3.12` (or `python3.11`) | `avahi` | `ethtool` | `unzip` |
| Arch / Manjaro | `python` | `avahi`, then `systemctl enable --now avahi-daemon` | `ethtool` | `unzip` |
| openSUSE Tumbleweed / Leap 16 | `python3` | `avahi` | `ethtool` | `unzip` |
| openSUSE Leap 15.6 | `python312` (or `python311`) | `avahi` | `ethtool` | `unzip` |
| Gentoo (systemd) | `dev-lang/python` | `net-dns/avahi` | `sys-apps/ethtool` | `app-arch/unzip` |

**No `unzip`:** Python can extract the release ZIP:

```sh
python3 -m zipfile -e /path/to/downloaded-linux-source.zip computer-host-lan
cd computer-host-lan
sh scripts/preflight.sh
```

Python's `zipfile` does **not** restore the executable bit, so call the
scripts with `sh scripts/<name>.sh` (or `chmod +x scripts/*.sh` first).

## 6. Firewall and MAC policy notes

The installer never changes firewalls or SELinux/AppArmor policy. Where a
firewall is active, the SmartThings hub must be able to reach TCP **8765**
on this host, and mDNS (UDP 5353) must be allowed for automatic discovery.

- **firewalld (Fedora Server, RHEL family, openSUSE):** the default zone
  normally blocks 8765/tcp. An administrator can allow it, preferably
  limited to the hub's address. Fedora Workstation's default zone already
  allows ports 1025–65535 and mDNS.
- **ufw (Ubuntu, Mint, Manjaro):** installed but usually inactive. If it is
  active, allow 8765/tcp from the hub and 5353/udp.
- **SELinux enforcing:** the agent runs from `/opt` as an unconfined service.
  This is expected to work, but has **not** been tested under enforcing mode.
  Record `getenforce` and any `ausearch -m avc` output when testing.
- **AppArmor:** no profile is shipped. Ubuntu/Debian do not confine
  unprofiled services.

## 7. Architectures

The Python agent runs on any architecture with Python 3.10+ (x86-64, arm64,
armhf, riscv64). The planned Go wizard's test binary is **linux/amd64 only**;
`linux/arm64` is on the Phase E list. Raspberry Pi and other ARM hosts should
use the manual installer.

## 8. Implications for the Go wizard

- **Elevation cannot assume `sudo`.** At least Debian (root password set),
  Arch and Gentoo ship without it. The privileged step should accept `sudo`,
  `doas`, `run0`/polkit, `su -` and an already-root session, and must keep the
  terminal-ownership rules from the design (§3, *Elevation*).
- **Python selection** must stay delegated to `python-selector.sh`, so RHEL 9
  and Leap 15.6 work with parallel interpreters.
- **Preflight wording:** missing Avahi is a warning with a manual-IP path,
  missing `ethtool` only disables WOL, and an active firewalld should produce
  explicit guidance rather than a silent pass.
- **Atomic and NixOS hosts** should be detected and refused with a clear
  message, not reported as a generic "unsafe managed path".

## 9. Test coverage needed before claiming support

| Priority | Target | Why |
| --- | --- | --- |
| 1 | Physical Debian 13 or Ubuntu 24.04 | Largest user base; also tests `su -` vs `sudo` and udev `.link` WOL |
| 2 | Physical Fedora 44 Workstation | SELinux enforcing, firewalld, NetworkManager WOL |
| 3 | RHEL/Alma/Rocky 9 with `python3.12` | Parallel interpreter selection, firewalld server zone |
| 4 | Arch without `sudo` | Root-only install path, Avahi not installed |
| 5 | openSUSE Tumbleweed | SELinux default, `targetpw`, firewalld |
| 6 | Raspberry Pi OS (arm64) | Non-x86 agent, no WOL hardware |

Report results as described in `docs/release/RC-ACCEPTANCE.md`:
distribution, version, architecture, privilege method used, and
PASS/FAIL/NOT TESTED for install, discovery, monitoring, upgrade and WOL.
