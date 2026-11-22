# Linux distribution support plan

**Status:** proposed plan, 2026-11-22. Nothing in this document is implemented yet.
**Companion:** [Linux distribution compatibility matrix](LINUX-DISTRIBUTION-MATRIX.md) (current evidence and defaults) and [Linux installer design](LINUX-INSTALLER-DESIGN.md) (wizard architecture and privileged phases).

## Why

Only Gentoo `hydra` is verified on real hardware. Debian, Ubuntu and Fedora pass container smoke tests that run without systemd as PID 1. The compatibility matrix shows the gaps to close:

- no `sudo` on Debian (when a root password was set at install), Arch and Gentoo;
- an old system `python3` on RHEL 9 (3.9) and openSUSE Leap 15.6 (3.6);
- firewalld blocking 8765/tcp, and SELinux enforcing;
- different network stacks for WOL (NetworkManager, systemd-networkd, wicked);
- missing Avahi, `ethtool` and `unzip`.

## Scope

- **Installers:** both protocol-v2 front ends.
  - The upcoming **Go wizard** (`linux-installer/`, which calls `scripts/installer-api.sh` / `installer_api.py`) becomes the **main installation method**.
  - The **manual installer** (`scripts/install-agent.sh`, which runs `scripts/install_core.py`) stays the expert and fallback path, with identical flags.
- **Legacy v1** `linux-host-lan` is treated only as a migration source.
- **Native packages** (DEB, RPM, PKGBUILD, ebuild) are out of scope for this plan.
- **Target tiers:**
  - **Tier 1:** Debian, Ubuntu, Fedora, RHEL / AlmaLinux / Rocky.
  - **Tier 2:** Arch, openSUSE, Mint / Pop!_OS, Raspberry Pi OS.
  - **Reference:** Gentoo (systemd profile).
  - **Refused with a clear message:** non-systemd systems and immutable/image-based systems.

**Principle: one engine, two front ends.** All distribution differences live in **one read-only Python module** that both installers use. The Go wizard only renders allowlisted IDs, and the shell installer prints the same facts. No distribution logic is duplicated in Go or shell.

## Step 0 (blocking safety fix): v1/v2 coexistence guard

`linux-host-lan/scripts/install_core.py` and `computer-host-lan/scripts/install_core.py` have identical `SYSTEMD_PATHS`, `APP_FILES`, `AVAHI_PATH` and `BACKUP_BASE`. Both use the `linuxhost` user and `/var/lib/linux-host-agent` for state. The v1 agent declares `PROTOCOL = "linux-host-agent"` and advertises `_linuxhost._tcp`. No v2 script detects v1. So the v2 installer would silently replace a v1 agent as an "upgrade", and the v1 Edge driver would then lose the device.

- **`install_core.py`:** add `detect_legacy_v1(root)`.
  - It reads only `/opt/linux-host-agent/linux_host_agent.py` (looking for `PROTOCOL = "linux-host-agent"`) and `/etc/avahi/services/linux-host-agent.service` (looking for `_linuxhost._tcp`).
  - It uses the existing `refuse_links` checks and never reads the state directory.
- **`run_cli`:** refuse `--install` when v1 is detected, unless an explicit future `--migrate-from-v1` flag is given. Migration itself is not part of this step; the design spec requires it to be a separate, explicit operation. `--plan` reports the detection.
- **`installer_api.py`:**
  - `inspect` adds the check `legacy_v1_installation` (status `blocked`) and `installation.protocol: "v1" | "v2" | "unknown"`;
  - `plan` returns the error code `legacy_install_present`.
- **`linux-installer/live.go`:** add the new check ID and error code to `knownCheck` / `permittedError`, and show the blocked state on the Compatibility page.
- **Tests:** fixture roots with v1 files for both installers (`tests/test_installer_api.py`, `tests/test_installer_v030.py`, Go `live_test.go`).

## Step 1: shared platform profile (read-only)

New `scripts/platform_profile.py`: pure functions that take a `root: Path`, so fixture roots can be used, as `installer_api.inspection` already does. It detects:

- **Distribution:** `ID`, `ID_LIKE`, `VERSION_ID` and `VARIANT_ID` from `/etc/os-release`, mapped to a `family` (debian, fedora, rhel, arch, suse, gentoo, other) and a `support_tier` from one data table that mirrors the matrix.
- **Blocked layouts:** `/run/ostree-booted`, `ID=nixos`, a read-only `/usr` with transactional updates, and `/opt` as a symlink. Each gets a **specific** `blocked_layout` ID instead of today's generic `unsafe_managed_path`.
- **systemd version** from `systemctl --version`. Below 242, warn that `ProtectHostname=` and `RestrictSUIDSGID=` are ignored.
- **Network stack:** active state of `NetworkManager`, `systemd-networkd` and `wicked`, reusing `installer_api.service_state` (read-only `is-active` only).
- **Firewall:** whether firewalld or ufw is active, and whether nftables is present (read-only).
- **MAC policy:** SELinux (`/sys/fs/selinux/enforce`) and AppArmor (`/sys/module/apparmor/parameters/enabled`).
- **Privilege tools on PATH:** `sudo`, `doas`, `run0` (only with systemd 256 or newer), `pkexec`, `su`, and whether the process already runs as UID 0.

Wiring:

- `installer_api.py inspect` returns a `platform` object containing only enums and booleans: no paths and no raw os-release text.
- **Bump the API `SCHEMA_VERSION` to 2.** `live.go` decodes with `DisallowUnknownFields` and requires `schema_version == 1`, so it must change in the same PR. Add allowlists for family, tier, layout, network stack, firewall and MAC policy.
- `scripts/preflight.sh` calls `platform_profile.py` through the existing `python-selector.sh` and prints the same facts, so both installers report the same result.

## Step 2: engine and manual-installer portability

- **Fixed root PATH:** after the UID check in `install-agent.sh`, `rollback-agent.sh` and `uninstall-agent.sh`, set `PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin`. This fixes the Debian plain-`su` failure (`Required command missing: useradd`) and stops root from trusting a user's PATH.
- **Not-root message:** replace the bare "Run as root." with the detected methods (`sudo`, `su -`, `doas`, `run0`) and an absolute-path example. Use the Step 1 module, or a small shell `command -v` loop if Python has not been selected yet.
- **Avahi:** keep the Avahi file optional. Add a preflight hint when the services directory exists but `avahi-daemon` is inactive.
- **WOL:** when `wicked` is active, `configure-wol.sh` refuses persistent WOL with guidance, instead of falling through to a `.link` file that wicked may override. The netplan/networkd and NetworkManager paths are unchanged.
- **Firewall:** stays **read-only**. Preflight, `inspect` and the wizard show exact, copyable guidance per backend (firewalld zone, port and mDNS; ufw), limited to the hub IP when one is known. Nothing is applied automatically, as the design spec requires.
- **SELinux:** add a `restorecon` step on managed paths only if the Step 4 enforcing tests show AVC denials. Do not change policy speculatively.

## Step 3: prerequisite guidance (both front ends)

- `inspect` adds a `missing` list of allowlisted IDs (`python310`, `avahi`, `ethtool`, `nmcli`, `udevadm`, `unzip`) and a `package_manager` enum (apt, dnf, pacman, zypper, emerge).
- The Go wizard and `preflight.sh` map each ID and package manager to a fixed command string from one table. Example for RHEL 9: `dnf install python3.12 avahi ethtool`.
- **Never install packages automatically in this phase.** Showing a command is safe; running one as root is a later, explicit decision.

## Step 4: test infrastructure

1. **Wider unprivileged container matrix** (`.github/workflows/computer-host-linux.yml`, `scripts/ci/run-container-tests.sh`):
   - add `ubuntu:22.04`, `almalinux:9` (with `python3.12` while `python3` stays 3.9), `almalinux:10`, `archlinux:latest`, `opensuse/tumbleweed` and `opensuse/leap:16.0`;
   - add a Debian image **without `sudo`** that runs the install path as root.
2. **Installer parity test:** for each image, compare the actions from `install-agent.sh --dry-run` with `installer-api.sh plan` for the same flags. The two front ends must never disagree.
3. **systemd-as-PID-1 container job** (new; the main evidence step): boot each Tier 1 image, then each Tier 2 image, with `/sbin/init` in privileged Docker on GitHub runners, with cgroup mounts. In each container:
   - install for real, then check `systemctl is-active`, `/v2/info` and `/v2/health`;
   - reinstall/upgrade, checking that the UUID and key are preserved (reported as booleans only);
   - plan with power disabled, then uninstall, checking that the state is kept;
   - install the v1 fixture and confirm the v2 install is refused (Step 0).

   The wizard's non-interactive install path joins this job once it exists (design Phase D).
4. **SELinux enforcing:** containers can't enforce SELinux, so use a Fedora 44 and an AlmaLinux 9 VM (self-hosted, a nested-virtualization runner, or a documented manual checklist). Record `ausearch -m avc` output.
5. **Hardware acceptance:** volunteers per tier, reported with the fields in `docs/release/RC-ACCEPTANCE.md`, plus the privilege method used.

## Step 5: the wizard as main installer

This depends on the design spec's privileged phases (C and D): a root-owned staging folder, a crash-safe install log and a health gate. Those stay in separate PRs.

- **Elevation adapters,** tried in this order:
  1. already root;
  2. `sudo` (probe with `sudo -n true` first);
  3. `run0`;
  4. `doas`;
  5. `pkexec`;
  6. `su -`.

  The user can override the choice with `--elevate=`. Every adapter follows the design's terminal-handoff rule (pause Bubble Tea, or use `tea.ExecProcess`), passes only validated arguments, and never captures a password.
- **Wizard screens:**
  - Compatibility shows the tier, or a specific blocked-layout message;
  - prerequisites, with copyable commands;
  - firewall guidance;
  - the v1 migration notice.
- **Release (Phase E):** static `linux/amd64` and `linux/arm64` builds (the latter for Raspberry Pi). `QUICK-START.md` and `INSTALLATION.md` switch to the wizard only at that release; the manual installer stays documented as the fallback.

## PR sequence

Each step is a small PR that can be reviewed on its own:

1. v1/v2 coexistence guard (Step 0) for both installers, plus the Go allowlists.
2. `platform_profile.py`, `inspect` schema v2, `live.go` update, `preflight.sh` parity.
3. Fixed root PATH and the not-root guidance message.
4. Wider container matrix and the dry-run/plan parity test.
5. systemd-as-PID-1 container lifecycle job: Tier 1, then Tier 2.
6. Firewall/WOL guidance, the `configure-wol.sh` wicked refusal, and prerequisite IDs.
7. SELinux enforcing VM validation, plus a `restorecon` fix only if it is needed.
8. Wizard elevation adapters and screens (after the design's Phase C/D privileged PRs).
9. Hardware acceptance rounds, updated matrix status, and the Phase E release builds.

## Support-tier definitions

These definitions decide what the matrix may claim:

- **Tier 1:** the CI systemd-as-PID-1 lifecycle passes, there is at least one physical install report, and a MAC-policy check (SELinux or AppArmor) was done.
- **Tier 2:** the CI systemd-as-PID-1 lifecycle passes, and there is a community report.
- **Reference:** Gentoo `hydra`, with full hardware, power and WOL tests.
- **Refused:** non-systemd systems, NixOS, ostree/image-based systems, WSL and containers, each with a specific message.

## Files involved

- `scripts/install_core.py`, `install-agent.sh`, `rollback-agent.sh`, `uninstall-agent.sh`, `preflight.sh`, `configure-wol.sh`
- `scripts/installer_api.py`, `installer-api.sh`, and the new `scripts/platform_profile.py`
- `linux-installer/live.go` and its tests
- `.github/workflows/computer-host-linux.yml`, `scripts/ci/run-container-tests.sh`
- `docs/development/LINUX-DISTRIBUTION-MATRIX.md`, `LINUX-INSTALLER-DESIGN.md`, `LINUX-INSTALLER-API.md`

**Reuse rather than rewrite:** `python-selector.sh` (`linuxhost_select_python`), `InstallTransaction.refuse_links`, `installer_api.service_state` and `managed_file_status`, the existing error-code mechanism in `installer_api.py`, and the strict decoding in `live.go`.

## Verification

- **Unit tests:** fixture roots for every family's os-release, ostree and NixOS markers, v1 files, a missing `sudo` and an old Python. Run `python3 -m unittest discover -s tests`, and `go test -race ./...` in `linux-installer/`.
- **CI:** the wider container matrix, the parity test and the systemd-as-PID-1 lifecycle job must all pass for an image before its matrix row changes from "Expected" to "CI-tested (PID 1)".
- **Manual:**
  - a Gentoo `hydra` regression after each engine PR (install and upgrade with identity preserved, power, WOL);
  - one physical Tier 1 host per family before any "Tier 1" claim;
  - the SELinux enforcing VM checklist.
- **Documentation:** each PR updates `LINUX-DISTRIBUTION-MATRIX.md` only with evidence that PR actually produced.
