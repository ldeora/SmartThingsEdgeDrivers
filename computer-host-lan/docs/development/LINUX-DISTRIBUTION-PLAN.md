# Linux distribution support plan

**Status:** proposed plan, 2026-11-22, revised after review. Nothing in this document is implemented yet.
**Companion:** [Linux distribution compatibility matrix](LINUX-DISTRIBUTION-MATRIX.md) (current evidence and defaults) and [Linux installer design](LINUX-INSTALLER-DESIGN.md) (wizard architecture and privileged phases).

## Why

Only Gentoo `hydra` is verified on real hardware. Debian, Ubuntu and Fedora pass container source tests that run without systemd as PID 1. The compatibility matrix shows the gaps:

- no `sudo` on Debian (when a root password was set at install), Arch and Gentoo;
- an old system `python3` on RHEL 9 (3.9) and openSUSE Leap 15.6 (3.6);
- firewalld blocking 8765/tcp, and SELinux enforcing;
- several possible network stacks per host, which matters for WOL;
- missing Avahi, `ethtool` and `unzip`.

Distribution support is mainly **not** about recognizing distribution names or installing packages. It is about making **identical, safe installation decisions** across different combinations of init system, filesystem layout, privilege mechanism, security policy and network manager. This plan is built around that.

## Scope

- **Installers:** both protocol-v2 front ends.
  - The upcoming **Go wizard** (`linux-installer/`, which calls `scripts/installer-api.sh` / `installer_api.py`) becomes the **main installation method**.
  - The **manual installer** (`scripts/install-agent.sh`, which runs `scripts/install_core.py`) stays the expert and fallback path, with identical flags.
- **Legacy v1** `linux-host-lan` is treated only as a migration source.
- **Native packages** (DEB, RPM, PKGBUILD, ebuild) are out of scope for this plan.
- **Target distributions:**
  - first wave: Debian, Ubuntu, Fedora, RHEL / AlmaLinux / Rocky;
  - second wave: Arch, openSUSE, Mint / Pop!_OS, Raspberry Pi OS;
  - Gentoo (systemd profile) stays the hardware reference;
  - non-systemd and immutable/image-based systems are refused with a specific message.

**Principle: one engine, two front ends.** All distribution handling lives in shared Python code that both installers use. The Go wizard only renders allowlisted IDs, and the shell installer prints the same facts. No distribution logic or safety decision is duplicated in Go or shell.

## Order of work

1. **Correct and merge this documentation** (matrix and plan). No code.
2. **v1/v2 coexistence guard** (Step 1 below).
3. **Execution-environment hardening and shared platform detection** (Steps 2 and 3).
4. **Automated distribution tests:** source tests first, then disposable VMs for the systemd lifecycle and SELinux (Step 4).
5. **Privileged wizard execution and release builds**, only after the design's crash-safe transaction, recovery and health-gate work (Step 5).

Each numbered item is one or more small PRs that are reviewed separately.

## Step 1: v1/v2 coexistence guard (blocking safety fix)

**The problem.** `linux-host-lan/scripts/install_core.py` and `computer-host-lan/scripts/install_core.py` have identical `SYSTEMD_PATHS`, `APP_FILES`, `AVAHI_PATH` and `BACKUP_BASE`. Both use the `linuxhost` account and `/var/lib/linux-host-agent` for state. The v1 agent declares `PROTOCOL = "linux-host-agent"` and advertises `_linuxhost._tcp`; v2 uses `computer-host-agent` and `_computerhost._tcp`. No v2 script detects v1, so an ordinary v2 install replaces the v1 application files as if it were an upgrade. The v1 Edge driver then loses the device.

**Where the guard must run.** Before **any** step that can change the host. In today's manual installer that is before `install-agent.sh` creates the `linuxhost` account, which happens *before* `install_core.py` starts. The guard therefore has to run:

- in `install-agent.sh`, before `useradd`, by calling a read-only classification entry point in Python;
- again in `install_core.py --install`, before the backup directory is created or changed, the snapshot is taken or any unit is replaced, so that no entry point can bypass it;
- in `installer_api.py inspect` and `plan`, so the wizard shows the same result;
- in `rollback-agent.sh` and `uninstall-agent.sh`, which must not act on a v1 installation as if it were v2.

**How to classify.** A new read-only function `classify_existing_installation(root)` returns exactly one of:

| Result | Meaning | Install allowed |
| --- | --- | --- |
| `none` | No managed path, no `linuxhost` account, no state directory | Yes |
| `v2` | Every present managed file matches v2 markers | Yes (upgrade) |
| `v1` | v1 markers found (`PROTOCOL = "linux-host-agent"` in `/opt/linux-host-agent/linux_host_agent.py`, or `_linuxhost._tcp` in the Avahi file) | **No.** Requires a future explicit `--migrate-from-v1` operation |
| `ambiguous` | Anything else: partial files, mixed v1 and v2 markers, an account or state directory without unit files, unreadable or linked paths | **No.** Stop and explain; never guess |

Rules:

- It reads only managed application and Avahi files, using the existing `InstallTransaction.refuse_links` checks. It never reads `installation-id` or `control-token`.
- Treating `ambiguous` as blocked is deliberate. Incomplete or unknown states must not become a silent overwrite.
- Migration itself is a separate, explicit operation, as the design spec requires, and is not part of this step.

**Wizard and API.** `inspect` adds a check `existing_installation` (status `blocked` for `v1` and `ambiguous`) and `installation.protocol: "none" | "v1" | "v2" | "ambiguous"`. `plan` returns the new error codes `legacy_install_present` or `ambiguous_installation`. `linux-installer/live.go` adds them to its allowlists (`knownCheck`, `permittedError`) in the same PR.

**Tests.** Fixture roots for every classification in both installers' tests (`tests/test_installer_api.py`, `tests/test_installer_v030.py`, Go `live_test.go`). Each blocked case must also prove that **nothing changed**: no account created, no backup directory touched, no unit file written.

## Step 2: execution-environment hardening (manual installer and wizard root helper)

Setting `PATH` after the UID check is too late: `install-agent.sh` already runs `id -u` and other commands before then, resolved through the caller's `PATH`.

- **Trusted `PATH` first.** Immediately after `set -eu`, before any external command, every privileged entry point (`install-agent.sh`, `rollback-agent.sh`, `uninstall-agent.sh`, `configure-wol.sh`, and later the wizard's root helper) sets `PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin` and `export`s it. This also fixes the Debian plain-`su` failure (`Required command missing: useradd`).
- **Sanitize the rest of the environment.** Unset variables that change how Python or the shell load code: `PYTHONPATH`, `PYTHONHOME`, `PYTHONSTARTUP`, `PYTHONUSERBASE`, `PYTHONINSPECT`, `BASH_ENV`, `ENV`, `IFS` (reset), `LD_PRELOAD`, `LD_LIBRARY_PATH`. Start Python with `-I` (isolated mode) and `-B`, so the user's site-packages and the current directory are never on the import path.
- **Not-root message.** Replace the bare "Run as root." with the methods actually present (`sudo`, `su -`, `doas`, `run0`) and an absolute-path example.
- **Acceptance test with a hostile environment.** Run each entry point with a `PATH` whose first folder contains fake `id`, `useradd`, `systemctl`, `python3` and `sed` that record being called, plus a `PYTHONPATH` with a fake `install_core` module. The test passes only if none of the fakes ran and the result is the same as with a clean environment.

## Step 3: shared platform detection

Split into three layers, so detection never pretends to be a support decision:

1. **Facts** (`scripts/platform_facts.py`): read-only observations, each with an explicit `unknown` state. All file access goes through an injectable filesystem root, and every command (`systemctl`, `networkctl`, `nmcli`) goes through an injectable command runner. Unit tests therefore never touch the real host's `/sys`, `/run` or `systemctl`.
2. **Policy** (`scripts/platform_policy.py`): turns facts into decisions such as `install_allowed`, `blocked_layout`, `wol_backend` and the support wave. One data table, mirroring the matrix.
3. **Guidance:** fixed, allowlisted message IDs that the wizard and `preflight.sh` render. A message never claims that detection proves compatibility.

**Facts to collect:**

- `/etc/os-release`: `ID`, `ID_LIKE`, `VERSION_ID`, `VARIANT_ID`.
- Layout markers: `/run/ostree-booted`, `ID=nixos`, a read-only `/usr` with transactional updates, `/opt` as a symlink.
- systemd version (below 242, `ProtectHostname=` and `RestrictSUIDSGID=` are ignored; `run0` needs 256 or newer).
- **Per-interface network management.** Which stack manages *the selected interface*, not just which services are active. Several can coexist, and the interface may be managed by a different one than the "main" service:
  - NetworkManager: `nmcli -g GENERAL.STATE,GENERAL.CON-UUID device show IFACE` (managed or unmanaged);
  - systemd-networkd: `networkctl status IFACE` (`configured` vs `unmanaged`);
  - wicked: `wicked ifstatus IFACE`;
  - result: `nm`, `networkd`, `wicked`, `none` or `unknown`.
- Firewall: firewalld or ufw active, nftables present.
- MAC policy: SELinux mode (`/sys/fs/selinux/enforce`) and AppArmor (`/sys/module/apparmor/parameters/enabled`). This is detection only; the effect is measured in Step 4.
- Privilege tools on `PATH` (`sudo`, `doas`, `run0`, `pkexec`, `su`) and whether the process already runs as UID 0.

**WOL backend per interface.** The persistent WOL backend comes from the selected interface's manager:

- `nm` → the NetworkManager connection;
- `networkd` or `none` → a systemd-udev `.link` file;
- `wicked` → **refuse** persistent WOL with guidance;
- `unknown` → refuse.

`configure-wol.sh` must use the same decision instead of its current "NetworkManager is active" test. Installed tools, a possible persistent configuration and working hardware are reported as three separate things.

**Wiring:**

- `installer_api.py inspect` returns a `platform` object of enums and booleans only: no paths and no raw os-release text.
- **Bump the API `SCHEMA_VERSION` to 2** in the same PR as `live.go`, which decodes with `DisallowUnknownFields` and requires `schema_version == 1`. Add allowlists for every new enum.
- `preflight.sh` calls the same Python code through `python-selector.sh`, so both installers print the same facts.

**Prerequisite guidance.** `inspect` adds a `missing` list of allowlisted IDs (`python310`, `avahi`, `ethtool`, `nmcli`, `udevadm`, `unzip`) and a `package_manager` enum (apt, dnf, pacman, zypper, emerge). Both front ends map them to fixed command strings from one table, for example RHEL 9 → `dnf install python3.12 avahi ethtool`. **Packages are never installed automatically in this phase.**

**Firewall guidance** stays read-only: exact, copyable commands per backend (firewalld zone, port and mDNS; ufw), limited to the hub IP when known. Nothing is applied automatically, as the design spec requires.

## Step 4: automated distribution tests

1. **Unprivileged containers, for source compatibility only.** Keep and widen the existing matrix (`.github/workflows/computer-host-linux.yml`, `scripts/ci/run-container-tests.sh`) with `ubuntu:22.04`, `almalinux:9` (with `python3.12` while `python3` stays 3.9), `almalinux:10`, `rockylinux:9`, `archlinux:latest`, `opensuse/tumbleweed` and `opensuse/leap:16.0`, plus a Debian image **without `sudo`**. These cover Python versions, shell parsing, prerequisite detection, platform facts against the real image files, and read-only planning. They do not prove service behavior.
2. **Behavioral parity between the two front ends.** Normalize both into one structured plan format: `install-agent.sh --dry-run` gains a machine-readable output mode next to `installer-api.sh plan`. Then run a shared scenario list through both and compare the **decision**, not just the listed file operations:
   - a fresh host, an existing v2 host, a v1 host and an ambiguous host;
   - a missing prerequisite, an old Python plus a parallel one, and an explicit `--python`;
   - a symlinked or otherwise unexpected managed file;
   - power enable, disable and preserve, and an existing custom power drop-in;
   - an invalid or missing WOL interface.

   Both must agree on allowed vs refused, the error category and the planned actions. This becomes the guard that stops the wizard from making different safety decisions from the shell installer.
3. **Disposable VMs for the systemd lifecycle.** Privileged Docker with host cgroup mounts is **not** used; it needs its own security and reliability review and gives a weaker isolation boundary. Instead, each run boots a fresh cloud image of the target in a throwaway VM, for example with QEMU/KVM on a runner that offers nested virtualization, or a dedicated self-hosted runner that destroys the VM after each job. In each VM:
   - fresh install, `systemctl is-active`, `/v2/info` and `/v2/health` on loopback;
   - reinstall/upgrade, checking that the UUID and key are preserved (reported as booleans only);
   - a preserved, deliberately stopped service;
   - power disabled, then uninstall, checking that the state is kept;
   - failure injection during install, checking that recovery works;
   - a v1 install and an ambiguous install, both refused with no changes (Step 1);
   - the hostile-environment test (Step 2).
4. **SELinux enforcing and AppArmor,** in the same VMs: Fedora 44 and AlmaLinux 9 enforcing, and Ubuntu 24.04 with AppArmor. Record the actual process domains (`ps -eZ`), file labels (`ls -Z`) and denials (`ausearch -m avc`). Add a `restorecon` step or a policy change **only** if these measurements show it is needed.
5. **Hardware acceptance:** volunteers report with the fields in `docs/release/RC-ACCEPTANCE.md`, plus the privilege method used. Hardware covers what a VM cannot: SmartThings discovery on a real LAN, WOL, suspend and the power states.

## Step 5: the wizard as main installer

This waits for the design spec's privileged phases (C and D): a root-owned staging folder, the crash-safe install log, recovery and the post-install health gate. Those stay in separate PRs.

- **Elevation adapters,** tried in this order:
  1. already root;
  2. `sudo` (probe with `sudo -n true` first);
  3. `run0`;
  4. `doas`;
  5. `pkexec`;
  6. `su -`.

  The user can override the choice with `--elevate=`. Every adapter follows the design's terminal-handoff rule (pause Bubble Tea, or use `tea.ExecProcess`), passes only validated arguments, starts the root helper with the Step 2 trusted environment, and never captures a password.
- **Wizard screens:**
  - Compatibility shows the support wave, or a specific blocked-layout message;
  - prerequisites, with copyable commands;
  - firewall guidance;
  - the v1 or ambiguous-installation notice.
- **Release (Phase E):** static `linux/amd64` and `linux/arm64` builds (the latter for Raspberry Pi). `QUICK-START.md` and `INSTALLATION.md` switch to the wizard only at that release; the manual installer stays documented as the fallback.

## Related future work

- **Manual discovery without Avahi.** Today the Edge driver's fallback is a hard-coded list in `edge-driver/src/computerhost/manual_hosts.lua` that must be edited, repackaged and redeployed. A user-facing way to add a host by IP (for example a driver setting) would make Avahi-less hosts practical. That is an Edge-driver change, planned separately from this installer work.
- **v1 → v2 migration** as an explicit, reversible operation.

## Evidence levels

These decide what the matrix may claim for a distribution and release:

| Level | Evidence required | What it does not cover |
| --- | --- | --- |
| **Source-compatible** | The unprivileged container job passes (Step 4.1), and the parity scenarios pass on that image (Step 4.2) | Service lifecycle, MAC policy, firewall, hardware |
| **Lifecycle-verified** | The VM lifecycle job passes (Step 4.3), including MAC-policy measurement where the distribution enforces one (Step 4.4) | Real SmartThings LAN discovery, WOL, suspend and power-state hardware behavior |
| **Hardware-verified** | A physical install with a real SmartThings hub: discovery, monitoring and upgrade; WOL and power reported separately | Other NICs, firmware and networks |
| **Refused** | Detected and blocked with a specific message | — |

A fully lifecycle-verified distribution can be documented as compatible even when no volunteer runs it. WOL and SmartThings behavior still need hardware evidence and are labeled separately. Gentoo `hydra` remains the hardware reference.

## Files involved

- `scripts/install-agent.sh`, `rollback-agent.sh`, `uninstall-agent.sh`, `configure-wol.sh`, `preflight.sh`, `install_core.py`
- `scripts/installer_api.py`, `installer-api.sh`; new `scripts/platform_facts.py` and `scripts/platform_policy.py`
- `linux-installer/live.go` and its tests
- `.github/workflows/computer-host-linux.yml`, `scripts/ci/run-container-tests.sh`; a new VM lifecycle workflow
- `docs/development/LINUX-DISTRIBUTION-MATRIX.md`, `LINUX-INSTALLER-DESIGN.md`, `LINUX-INSTALLER-API.md`

**Reuse rather than rewrite:** `python-selector.sh` (`linuxhost_select_python`), `InstallTransaction.refuse_links`, `installer_api.service_state` and `managed_file_status`, the existing error-code mechanism in `installer_api.py`, and the strict decoding in `live.go`.

## Verification

- **Unit tests:** fixture roots and fake command runners for every family's os-release, layout markers, per-interface network managers, every installation classification, a missing `sudo` and an old Python. Run `python3 -m unittest discover -s tests`, and `go test -race ./...` in `linux-installer/`.
- **Safety tests:** each refused case proves that nothing changed, and the hostile-environment test proves that no caller-controlled command or module ran.
- **CI:** a matrix row moves up an evidence level only when the jobs required for that level pass for that distribution and release.
- **Manual:** a Gentoo `hydra` regression after each engine PR (install and upgrade with identity preserved, power, WOL).
- **Documentation:** each PR updates `LINUX-DISTRIBUTION-MATRIX.md` only with evidence that PR actually produced.
