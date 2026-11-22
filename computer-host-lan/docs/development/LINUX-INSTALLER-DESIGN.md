# Computer Host LAN — Linux installer design specification

**Status:** proposed / design only  
**Date:** 2026-11-22  
**Scope:** the `computer-host-lan/` protocol-v2 Linux agent and its systemd installation lifecycle.  
**Release boundary:** no agent, Edge driver, protocol, credentials, current installer or published v1.0.0-rc.2 artifacts are changed by this specification.

## 1. Product objective

Deliver a beginner-friendly **terminal installation and management wizard** with parity to the Windows Setup experience, without weakening Linux's existing privilege boundaries. A first-time user should be able to download one verified native installer, launch it as their ordinary account, select their hub/options, authorize only the changes that need root, and receive a verified running agent plus SmartThings onboarding instructions.

The wizard must also provide an expert/noninteractive interface, support in-place upgrades and recovery, and never require the user to install a developer toolchain or TUI framework. An attractive interface is not a substitute for correct installation semantics.

### Acceptance principles

1. Monitoring-only on new installations; remote power and persistent WOL are **separate explicit opt-ins**.
2. No unintended changes to firewall, network manager, system Python, unrelated services, existing WOL rules or SmartThings device identity.
3. Preserved UUID, control key, running/stopped/enabled service intent, and effective configuration across upgrades unless a specific change is explicitly requested.
4. A user sees **verified runtime health**, not merely `systemctl start` success.
5. Crash-safe, durable, understandable recovery from interrupted installs—not only exception-triggered rollback.
6. Accessible operation in a real TTY, narrow terminals, no-color/NO_COLOR, and noninteractive/automation use.
7. A standalone installer executable for each *tested* architecture; the Python agent and restricted power helper remain unchanged initially.

## 2. Confirmed baseline (2026-11-22)

| Area | Current behavior / file |
| --- | --- |
| Entry points | `scripts/preflight.sh`, `scripts/install-agent.sh`, `scripts/rollback-agent.sh`, `scripts/uninstall-agent.sh` |
| Engine | `scripts/install_core.py` snapshots approved managed paths in `/var/backups/linux-host-agent`, applies atomic file replacements, activates/restores systemd service state; `--plan` supports dry runs |
| Agent | `agent/linux_host_agent.py`, Python >=3.10, no third-party Python dependencies |
| Privilege separation | `linuxhost` user; optional systemd socket `linux-host-agent-power.socket` and restricted root helper |
| Files | `/opt/linux-host-agent`, `/etc/systemd/system`, `/etc/avahi/services`; persistent state under `/var/lib/linux-host-agent` |
| Discovery | agent advertises `_computerhost._tcp` via Avahi when available; Windows Setup separately discovers SmartThings hub `_smartthings._tcp.local.` |
| Power/WOL | power disabled on first install; existing opt-in kept unless changed; `configure-wol.sh` separately handles NetworkManager or systemd-udev with explicit opt-in |
| Networking | default TCP 8765; Linux installer does **not** change firewall; HTTP transport is LAN-only and unencrypted |
| Known gaps | no integrated onboarding or hub selection; no first-class configurable port in the Linux install templates; no post-activation HTTP identity/version health gate inside the transaction; interruption journal/reconciliation not yet implemented; WOL is applied separately after core installation |

**Important:** CI/container compatibility is not real distribution or hardware certification. Preserve the documented rc.2 acceptance status and do not treat this work as a new release.

## 3. Architectural decision

A small **Go application** using **Huh v2** for forms and **Bubble Tea v2** for application-level screen/state management will orchestrate the **existing Python installation engine**. The application, not the normal agent, is compiled to a native binary. Use the maintained `charm.land/huh/v2` and `charm.land/bubbletea/v2` packages; pin exact versions and commit `go.mod`/`go.sum` before build CI is enabled.

**Authoritative ownership:** Only the installation engine mutates managed files and services; the Go TUI is not a second installer. Never have shell and Go independently write the same configuration.

Suggested boundaries:

```
computer-host-lan/
  linux-installer/          # Go TUI/controller, tests, embedded release payload
  scripts/install_core.py   # privileged transactional installer + structured API
  scripts/install-agent.sh  # preserved compatible CLI entry point
  scripts/preflight.sh      # preserved until read-only probing is unified
  agent/                   # unchanged runtime and unit templates initially
```

The controller will offer a stable, versioned command/response interface to Python, e.g. a `--json` mode with **explicit schema versions, stable error codes, no secret values and no parsing of human prose**. Do not expose arbitrary command execution, shell snippets, free-form destination paths or `systemctl` arguments through this interface. Validate all inputs in both Go and Python.

Operations: `inspect`, `plan`, `install`, `upgrade`, `repair`, `verify`, `rollback`, `uninstall`. Each operation should be explicit; `repair` must not silently rotate credentials or reset configuration. Use an operation identifier and durable phase markers to correlate progress, logs and recovery.

### Elevation

The UI, discovery and read-only preflight run as the invoking **unprivileged user**. The actual install/repair/uninstall invokes a narrowly defined root helper after explicit review and a `sudo`/polkit authorization appropriate to the host; passing validated argv and a protected request file/pipe is preferred over composing commands for `sh -c`. No `curl | sudo sh`, no permanent privilege escalation and no TUI drawing as root. If credentials are unavailable or authorization is declined, stop without partial mutation.

Root-side state inspection must itself be secure: fail closed on suspicious ownership, symlinks/reparse-like redirects, non-regular files, attacker-controlled parent directories and untrusted backup/transaction manifests. Preserve the existing managed-path allowlist. Do not copy secret tokens into logs, plan JSON, metrics, crash dumps or public diagnostics.

## 4. Wizard interaction contract

Only show relevant steps. `Back`, `Cancel`, `Help` and keyboard shortcuts work consistently. All text is comprehensible without color.

| Stage | New install | Existing install / upgrade |
| --- | --- | --- |
| 1. Welcome | Install, documentation | Upgrade (default when appropriate), configure, repair, diagnose, uninstall |
| 2. Compatibility | OS/arch, systemd PID1, Python >=3.10, standard tools, Avahi status, port conflict, network | Same checks + current installation, installed version, ownership and incomplete-transaction state |
| 3. SmartThings hub | Browse `_smartthings._tcp.local.`, retry, select hub, or enter IPv4; continue without discovery | Existing hub preference proposed; ability to change intentionally |
| 4. Features | Monitoring always on; optional remote power; optional WOL with chosen **physical Ethernet** NIC | Preserve existing selections by default; change only requested features |
| 5. Review | Exact proposed changes including paths, firewall policy and service effects; authorization | Highlight preserved identity, key, port, service state, existing WOL and pending recovery |
| 6. Execute | Show truthful phase-by-phase results, classify partial optional feature failures separately | Use transaction, restore previous state on failed gate; show recovery options |
| 7. Connect | Verify loopback agent; show driver channel link and SmartThings pairing steps; offer guarded key reveal only if enabled | Verify existing SmartThings device continuity; **do not suggest re-pairing** |

**Hub selection is not pairing.** Discovery of a hub is unauthenticated mDNS and should be confirmed by the user. Hub IPv4 is used for network/firewall guidance and optional allow rules, not proof of cloud authorization or actual SmartThings pairing. The agent's own Avahi advertisement is a different service (`_computerhost._tcp`) and needs its own verification.

**Monitoring-only is a valid complete install.** A missing Avahi service can be a warning with manual-network guidance where supported; systemd or Python absence blocks install; unavailable WOL is optional and cannot invalidate monitoring. Distinguish `blocked`, `warning`, `skipped`, `passed` and `not verified`—never show a green check for untested behavior.

**Key display:** don't print, auto-copy, or log the 64-character key. Explicit reveal/copy only with consent, masking by default and no persistent TUI/history file. Treat clipboard support as optional on Linux (Wayland/X11/headless differences); provide clear manual instructions if unavailable. Never send a key to a browser, public diagnostic bundle or logging facility.

## 5. Installation/recovery state machine

The current `install_core.py` catches exceptions and rolls back managed paths, but interruption/power failure can happen without an exception handler. Add a durable root-owned transaction journal with ordered, fsynced phase transitions:

`INSPECTED -> STAGED -> SNAPSHOTTED -> APPLYING -> ACTIVATING -> VERIFYING -> COMMITTED`

Any unexpected state on next launch must **block a fresh write** and offer explicit *Resume recovery* / *Restore snapshot* actions after validating journal ownership, contents and snapshot integrity. Never silently delete or overwrite an abandoned snapshot. Journal/backup path must be protected against symlinks/hardlinks and concurrent modifications; retain the installation lock. Write and fsync relevant files and containing directories at the appropriate durability boundaries.

### Health verification before commit

For a **newly running** agent, verify within a bounded deadline: systemd unit active, TCP loopback response, expected `/v2/info` protocol (`computer-host-agent`), API version 2, Linux platform, intended agent version, `/v2/health` running status and stable UUID. Validate configured port, not a hard-coded 8765. Check Avahi advertisement separately and report discovery warnings without falsely asserting pair success.

For an existing service intentionally **stopped or disabled**, preserve that intent and verify installed files/unit syntax without starting the service just for a health test. Report `installed; service intentionally stopped; runtime not verified`. Existing UUID and key preservation should be checked with privileged internal comparisons and results reported as booleans—not by exporting secrets to the Go frontend.

An unsuccessful post-activation gate restores managed application files and prior service state. If restore fails, preserve journal and backup and display safe manual instructions. Never remove `/var/lib/linux-host-agent` as a recovery shortcut.

### WOL as a separate change set

The current shell installer configures WOL after the core operation. Preserve this separation: run an explicit dry-run/impact preview; protect prior NetworkManager/.link settings and record any wizard-created changes for a distinct revert operation. A WOL failure is a **feature warning**, not an agent install failure. No network bounce or firmware change. Real sleep/S5 wake requires hardware validation.

### Firewall policy

Initially implement **read-only** detection/guidance for common host firewalls; leave rules unchanged by default. Future explicit adapters for tested firewalld/UFW configurations may allow TCP only from the selected SmartThings hub IP, with exact undo semantics and a user-visible diff. Do not claim an inbound rule is working merely because the local loopback probe succeeds. Never disable a firewall, open Internet-facing access, or assume that all nftables/iptables backends share a safe common mutation interface.

## 6. Configuration and existing installations

- Define a **single source of truth** for port, power enablement, WOL interface and network policy. Respect prior administrator configuration and distinguish installer-owned files from customized files.
- Add supported port configuration across systemd ExecStart, Avahi service and validation; keep the default 8765. Preserve custom port on upgrades. Reject malformed ports and occupied listeners before stopping a working service.
- An upgrade from the legacy `linux-host-lan` protocol-v1 service is a **separate explicit migration** with compatibility checks: do not silently install competing listeners or claim protocol-v1 identity can be used with v2.
- Preserve current user/systemd/Avahi naming in the first delivery to minimize migration risk: `linux-host-agent.service`, `linux-host-agent-power.socket`, `linuxhost`, existing state paths and discovery type.
- A native DEB/RPM installation must not be modified by the manual wizard without a documented package-owner migration path. Detect package-managed ownership and stop with guidance.
- Uninstall removes **only owned application resources**; retain UUID and credential by default. A distinct, prominent destructive purge must never be a default or a recovery step.

## 7. Artifact and supply-chain policy

Phase 1 is a **proof of interaction** (no root access, no real installation, no release build). After the interaction is accepted:

1. Pin audited Huh/Bubble Tea releases in `go.mod` **and `go.sum`**; review license/transitive dependency inventory and Go toolchain version.
2. Produce reproducible, version-matched installer assets for tested `linux/amd64`, later `linux/arm64`; try `CGO_ENABLED=0` and verify the result actually runs on the target systems.
3. Embed a minimal allowlisted agent/power-helper/systemd/Avahi/Python installer payload from the **same fixed source commit**; do not bundle Windows binaries, private state or unrelated repository files.
4. Provide independent artifact hashes and build provenance/signature verification instructions. A checksum downloaded from the same untrusted origin alone does not authenticate the publisher. The TUI cannot retroactively prove its own signature.
5. Offer inspected download-and-run instructions and an offline source ZIP fallback. Do not require `curl | bash`, a Git clone, a Go toolchain or live network access to complete installation from the artifact.
6. Do **not** auto-update the agent or fetch executable install scripts at runtime. Installer updates and native package manager updates must not compete for ownership.

The existing Python >=3.10 runtime remains a prerequisite. A rewrite of the agent in Go is explicitly **out of scope**.

## 8. CLI/API contract (planned)

An illustrative command surface (not implemented by this document):

```text
computer-host-lan                   # interactive wizard
computer-host-lan inspect --json    # unprivileged, redacted environment/status
computer-host-lan plan --json       # read-only proposed changes
computer-host-lan install --non-interactive --monitor-only
computer-host-lan upgrade           # preserve existing choices
computer-host-lan repair            # preserve identity and credentials
computer-host-lan uninstall         # preserve state by default
```

Noninteractive operations require explicit parameters for potentially destructive changes, stable exit codes and structured output; `--yes` must not implicitly enable power, change firewall policy, purge state or rotate a key. No root operation should accept an arbitrary pathname or command as an unvalidated field.

## 9. Verification matrix and release gates

| Gate | Required test |
| --- | --- |
| UI01 | Welcome/new/install/upgrade/repair/uninstall navigation; cancel/back semantics |
| UI02 | Accessible mode, no-color, 80x24 and narrow terminals, resize/interrupt handling, non-TTY fallback |
| UI03 | Manual hub IP validation, zero/one/multiple discovery results, retry and cancellation |
| UI04 | Existing installation settings preselected; new-install power/WOL **off** |
| SAF01 | Unprivileged UI/preflight does not mutate privileged state; deliberate privilege escalation only at commit |
| SAF02 | Invalid arguments, paths, symlinks, ownership, untrusted backup/journal content rejected before mutation |
| SAF03 | No token/UUID/MAC leakage in logs, accessible output, crash reports, screenshots or diagnostic archives |
| TX01 | Fresh install, idempotent reinstall, in-place upgrade, explicit disable power, restore intentionally stopped units |
| TX02 | Inject failure after every journal phase; abort/SIGKILL/power-loss simulation and next-run recovery |
| TX03 | Fail runtime health/version/UUID checks and prove rollback restores managed files and previous service state |
| TX04 | Keep protected UUID/key and existing SmartThings device through upgrade/rollback/reinstall |
| NET01 | Custom port preserved and advertised correctly; port collision detected; no firewall modification by default |
| NET02 | mDNS missing, isolated network, manual hub input; do not claim pairing without hub evidence |
| WOL01 | No WOL changes without opt-in; existing per-MAC .link/NetworkManager configuration not overwritten |
| PKG01 | Versioned payload matches fixed release manifest; clean offline install; artifact verification and license notice |
| PKG02 | Detect and refuse unexpected native-package ownership |
| HW01 | Real SmartThings hub: discovery, metrics, upgrade identity, power disabled by default |
| HW02 | Explicit power helper and WOL tested on real Linux hardware with recovery access; no regressions in current rc.2 behavior |
| DIST | At least Debian/Ubuntu, Fedora, Arch, openSUSE and Gentoo **with systemd PID1**, including missing dependency/SELinux/AppArmor cases documented as supported/unverified |

Use the existing `docs/development/LINUX-PARITY-ACCEPTANCE.md` checklist as the functional regression baseline. Green container CI is not proof of physical systemd/network/SmartThings/WOL behavior.

## 10. Delivery sequence and boundaries

**PR A — design specification (this PR).** Documentation only; no runtime or release changes.

**PR B — isolated TUI UX spike.** A standalone `linux-installer/` Go module with simulated preflight/hub/results, no privilege escalation, no embedded production agent, no mutation of system state, no publishing. Validate user experience, accessibility, terminal behavior and dependency lockfile before adopting API decisions.

**PR C — engine hardening.** Structured plan/status API, durable transaction recovery, post-install health verification, config/custom-port preservation; dedicated Python tests and real systemd fixture tests. Existing CLI remains functional.

**PR D — live wizard integration.** Read-only detection and mDNS, privileged transaction API, selected hub/power/WOL/options, guarded key reveal, onboarding and clean error handling.

**PR E — distribution and acceptance.** Fixed-source embedded payload, pinned Go deps, checksums/provenance and release packaging CI, test matrix, hardware acceptance. Publish a **new** version only after separate release approval.

### Explicit non-goals for first release

Non-systemd init managers; rewriting the Linux agent; silent pairing or automatic key exchange; remotely modifying SmartThings channel configuration; TLS/mTLS redesign; automatic update daemon; automatic credential rotation; uncontrolled firewall rules; a desktop GUI; claiming universal distro support.

## 11. Engineering references

- Current code: `scripts/install_core.py`, `scripts/install-agent.sh`, `scripts/preflight.sh`, `scripts/configure-wol.sh`, `agent/systemd/`
- Current behavior: `INSTALLATION.md`, `SECURITY.md`, `docs/release/QUICK-START.md`, `docs/development/LINUX-PARITY-ACCEPTANCE.md`
- Charm v2: https://github.com/charmbracelet/huh and https://github.com/charmbracelet/bubbletea
- Go embedded files: https://pkg.go.dev/embed
- Build provenance: https://docs.github.com/en/actions/concepts/security/artifact-attestations

**Decision:** prioritize the installation transaction contract and failure recovery over visual polish. Preserve the Windows installer feature/security expectations, with Linux-appropriate controls and honest network/power verification.
