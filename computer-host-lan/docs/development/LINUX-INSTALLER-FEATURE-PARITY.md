# Computer Host LAN — installer feature-parity contract

**Status:** Development acceptance checklist, based on inspected repository sources on
2026-11-23. **Not an implementation or certification claim.** Covers the released
Windows Setup, the current Linux shell/Python installer on `main`, and the
**read-only** Go wizard in PRs #67 and #72. This matrix is a gate for the future
**installing** Linux wizard. The Windows and Linux internals need not be
identical; user-visible outcome and the Linux installer's established semantics
must be preserved. Do not modify `hydra` merely to exercise these tests.

## Definition of done

A first-time user can download one verified Linux installer, launch it **without
running the whole TUI as root**, accept a discovered SmartThings hub, keep
monitoring-only or explicitly enable power, authorize one privileged transaction,
see a **verified running** computer agent, follow driver-channel/onboarding
instructions, and—**only if power was enabled**—reveal or copy the existing
64-hex control key by explicit action. No Python, systemd, Avahi, WOL, or
`/var/lib` paths need to be typed for the normal happy path.

A returning user can upgrade, repair, uninstall and reinstall without silently
changing UUID, key, service state, power opt-in, managed network settings or
SmartThings device identity. Failures expose safe, recoverable actions.

Legend: **Yes** = existing behavior, **Partial** = incomplete/manual,
**No** = absent; **Preview** = displays/plans but **cannot perform it**.
“Required” is the future Linux wizard's acceptance criterion.

## Parity comparison

| Feature / behavior | Windows Setup (Inno + PowerShell) | Linux scripts on `main` | Linux Go wizard PR #67/#72 (today) | Installing Linux wizard: required outcome |
| --- | --- | --- | --- | --- |
| Download and guided start | Native Setup.exe, unsigned RC | Source ZIP, verify checksum, shell commands | Test-only Go binary; explicit external API launcher | Single release-verifiable Linux binary/package, no Go checkout required |
| Preflight/prerequisites | Windows/UAC-specific checks | `preflight.sh`, Python selector 3.10+, systemd, tools | Live `inspect` and friendly summary; `-live -preview` diagnostics | Check before writes, show actionable fixes, optional Avahi |
| Privileges | Setup elevation, PowerShell only for privileged work | Installer must run as root | **No privilege boundary crossed** | Suspend UI safely for admin authorization; trusted root-owned payload/execution |
| Fresh application files | Yes, Windows agent to Program Files | **Yes:** two Python files in `/opt/linux-host-agent` | Preview only | Reuse `install_core` allowlist and exact versioned payload |
| Service registration | `ComputerHostAgent` LocalService | `linuxhost` system account + three hardened systemd unit files | No | Same current Linux account/unit naming, service hardening and permissions |
| Service enable/start | Auto start + health checks | First install enables/starts unit; upgrades preserve stopped/disabled state | Inspect/plan only | Same service-state semantics, followed by bounded verification |
| Discover SmartThings **hub** | Automatic `_smartthings._tcp` search, first result preselected | Not part of installer | Avahi browse; found candidate preselected | Auto-discover, rescan, zero/one/many handling, manual IPv4 |
| Missing discovery/manual hub IP | Manual IPv4 or explicit Private LocalSubnet fallback | No hub-IP input; agent advertises itself separately | Manual IPv4 or choose later, **advisory only** | Usable fallback; no false pairing claim or silent firewall broadening |
| Network firewall | Auto Private-profile inbound allow from hub IP or chosen LocalSubnet | **No modifications**; prints TCP/8765 guidance | No modification | Explicit status/guidance; optional future reviewed policy adapter, no unapproved changes |
| HTTP listening port | Respects retained custom port, validates firewall/health port | Hard-coded **8765** in service, power drop-in, Avahi | No port change | At least preserve 8765 correctly; define and test custom port preservation before claiming full parity |
| Agent advertisement to hub | Windows agent discovery | Avahi service XML for `_computerhost._tcp` if services dir present | Only inspect/plan; separate **hub** discovery in UI | Verify agent advertised and reachable; clearly distinguish two discovery directions |
| Monitoring-only default | Yes | Yes (`--enable-power` explicit) | Yes in planned options | Yes, usable without authentication key entry |
| Remote shutdown/restart/suspend | User opt-in; service honors setting | `--enable-power`: systemd drop-in + restricted root socket/helper | Planned setting only | Same guarded opt-in, systemd helper/socket, no unapproved enable |
| Preserve power setting on upgrade | Setup reads existing config | `generate_plan` retains existing drop-in unless explicitly changed | Review describes current/default | Preserve effective previous setting, never switch on accidentally |
| **Control key generation** | When power enabled, protected random 32-byte token (64 hex) | **Agent itself generates 64-hex key on first startup even in monitoring mode** | No key creation (cannot start agent) | **Reuse agent-generated key**; do NOT generate a second key in Go |
| **Key persistence** | `%ProgramData%\ComputerHostAgent\control-token` kept | `/var/lib/linux-host-agent/control-token` kept, chmod 0600, StateDirectory 0700 | Reports credentials not inspected | Preserve byte-for-byte across upgrades, rollback, reinstall, uninstall; no automatic rotation |
| **Key display/copy** | After install, conditional masked Show/Hide + Copy page | **No** integrated display; only prints private file path | **No** | Optional **post-health**, consent-driven masked reveal/copy, only when power enabled; no stdout/argv/logs, clipboard optional |
| SmartThings power preference | Key pasted into device `controlKey`; `allowPower` enabled manually | Same separate SmartThings device step | No pairing or settings change | Plain instructions for both values; never claim app settings set automatically |
| Wake-on-LAN (hub → computer) | Agent/driver support, but Windows Setup does **not** configure firmware/NIC | Driver/agent support; optional `--wol-interface` metadata pin | Optional advanced **pin preview**, suggested NIC | Preserve pinned interface; avoid treating pin as WOL enablement |
| Persistent NIC WOL | Not configured by Windows Setup | Separate explicit `--configure-wol`: `ethtool`, NetworkManager or systemd-udev `.link` | **No** WOL operations | Distinct opt-in, hardware/persistence check, no network restart or overwrite; failure nonfatal to core install |
| Rollback on detectable failure | Pre-install snapshot, guarded restore | `install_core.py` snapshots managed files and auto-restores on caught failures | None | Equivalent backup/apply/restore, plus protected crash journal for interrupted operations |
| Interrupted upgrade recovery | Prepared/abandoned snapshot reconciliation | **No durable phase journal yet** | None | Mandatory fail-safe recovery before replacing files; no delete-state workaround |
| Runtime health/version/identity | Post-install loopback health and upgrade identity/version checks | **No post-activation HTTP gate**; systemctl commands mainly | No runtime verification | systemd + loopback `/v2/info`/`health`, version/protocol/UUID/port, verify before commit |
| Preserve running/stopped state | Setup manages existing service in upgrade | Linux preserves intentionally stopped/disabled unit states | Inspects states, does not change | Must not start an intentionally stopped existing service just to pass health |
| Reinstall after uninstall | Preserves identity and key | Uninstall removes managed files; retains user, state, WOL, backups | None | Reinstall accepts retained **v2** state, no spurious v1 migration blockers |
| Uninstall | Setup entry + script, retained ProgramData | `uninstall-agent.sh --confirm` and snapshot, state retained | None | Confirm destructive changes, preserve credentials by default, recovery possible |
| Onboarding | Post-install Open/Copy driver-channel link + Scan nearby instructions | Documentation/terminal only; no guided page | No (preview ends) | Post-install Open/Copy channel + SmartThings Add device → Scan nearby; upgrades preserve existing device |
| Diagnostics, privacy | Setup log/sanitized recovery messaging | `diagnose.sh`, `beta-report.sh` redact keys/UUID/MAC/IP | Redacted `inspect`, hidden secret values | Clear failures, opt-in redacted report, no private key, UUID, auth headers or unfiltered stderr |
| Distribution/accessibility | Windows x64 Setup and keyboard UX | POSIX sh, Python 3.10+, systemd; `sudo` not intrinsically required | Go TUI with plain-text accessible mode; Gentoo field tests | First Gentoo/systemd acceptance; distro/ARM evidence gates tracked separately |

## Exact existing Linux installation flow to preserve

1. `install-agent.sh` parses power/WOL/Python/--dry-run options,
   validates interface names, root/systemd/tool prerequisites, selects a
   compatible Python, parses agent/helper/core Python before touching
   services, and creates the `linuxhost` system account (non-login shell)
   when needed.
2. `install_core.py` creates an exclusive install lock and a protected
   snapshot of allowlisted managed files, stages atomic replacements of
   Python modules and systemd service/socket files, keeps customized
   power drop-in when not explicitly changed, writes optional interface
   environment drop-in and the Avahi XML only if its services directory
   is present.
3. On first install, systemd enables and starts the unprivileged agent and
   the power-helper socket only when power is enabled; on upgrade it
   preserves intentionally stopped/disabled service state. On caught
   activation errors it restores managed files and service state.
4. `linux_host_agent.py` first startup securely publishes
   `installation-id` and `control-token` **atomically** (mode 0600);
   the systemd unit uses `StateDirectory=linux-host-agent` and
   `StateDirectoryMode=0700`. Key generation is done by the agent,
   **unconditionally**, not by `install_core.py`. A pre-existing key is
   validated and reused; it is never silently rotated.
5. Optional `configure-wol.sh --apply` runs **after** the core install.
   It checks `ethtool` magic-packet support, persists via the selected
   host network stack or `.link`, and attempts immediate `ethtool -s`
   without a network bounce. A WOL-stage failure can happen **after**
   the agent was successfully installed; the future UI must report this
   as a separate optional feature failure, not imply full rollback.
6. `uninstall-agent.sh --confirm` removes managed files and service
   registration but **keeps** the service user, persistent ID, control
   token, backup snapshots and existing hardware WOL configuration.
   `rollback-agent.sh --backup` restores a managed-file snapshot, not
   the contents of the protected state directory.

## Critical implementation rules for the Go wizard

1. **One backend, no feature reimplementations in Go.** The privileged
   version of the existing Python engine remains authoritative for
   state/service mutations. Go is responsible for usability, read-only
   planning, progress, consent and safe presentation.
2. **No independent key generation or implicit rotation.** A root-only
   read/reveal capability must validate the path and file owner, avoid
   symlinks, validate exactly 64 lowercase hexadecimal characters,
   and release the token only after an explicit reveal/copy request
   by the invoking administrator. Never return it as part of the
   ordinary `inspect/plan/verify` JSON, pass it via argv, log it, or
   show it on the default Review screen. Protect clipboard handling
   on X11/Wayland/headless/SSH; never auto-copy.
3. **Separate the hub's address from the agent advertisement.** Windows
   uses hub selection primarily to restrict its firewall. Linux does not
   currently configure its firewall; selecting a hub must not pretend
   connectivity or pairing has been validated, and should not be
   silently discarded when it becomes relevant to explicit guidance.
4. **No root TUI.** After review and explicit authorization, stage only
   version-matched, verified, root-owned trusted payloads and call a
   narrow privileged transaction interface; restore the terminal
   before an interactive authentication prompt.
5. **Transactional completion means runtime success**, including
   unchanged identity/key and expected protocol/version. A failed
   health gate rolls back managed resources without removing private
   persistent state; interrupted installs must have a recoverable
   protected journal. Uninstall/reinstall and rollback must work even
   when retained v2 state exists.
6. **Show one friendly completion.** On success: agent status, selected
   mode, channel invitation, Scan nearby instructions; optionally
   the masked key page. Do **not** claim SmartThings paired until the
   user actually adds the device, and never ask existing upgrade users
   to delete or re-add their device.

## Required acceptance scenarios before replacing the shell installer

| ID | Scenario | Pass condition |
| --- | --- | --- |
| P01 | Fresh monitoring-only installation | Agent starts, UUID/key created securely, helper socket disabled, pairing guidance shown, key UI skipped |
| P02 | Fresh power-enabled installation | Key reused/created by agent, socket enabled, protected Show/Copy, authenticated SmartThings action works |
| P03 | Upgrade existing enabled Linux v2 | Service intent, UUID, key, power-enabled drop-in and SmartThings identity preserved |
| P04 | Upgrade monitoring-only Linux v2 | Power stays disabled; no key shown; identity retained |
| P05 | Intentionally stopped/disabled service | Remains stopped/disabled, files updated, runtime marked not verified |
| P06 | Reinstall after v2 uninstall | Retained UUID/key reused; no new SmartThings device |
| P07 | Rollback and injected install errors | Managed files/service state restored, private state never deleted |
| P08 | Crash/SIGKILL during each transaction phase | Journal detects incomplete operation; recovery offered before new writes |
| P09 | Avahi absent or multiple hubs | Manual fallback/rescan, understandable warnings, no pairing claim |
| P10 | WOL configured or incompatible | Opt-in persists safely, or produces isolated warning without invalidating healthy monitoring |
| P11 | Key security | No token/UUID in logs, plans, diagnostics or default terminal output; clipboard only by action |
| P12 | Real systemd + SmartThings hub `hydra` | HTTP, discovery, status, metrics, reboot/shutdown/suspend and WOL hardware acceptance |
| P13 | Firewall blocks hub or custom listener port | Honest detection/guidance, no silent firewall alteration; port consistent across units/Avahi/health |
| P14 | Unsupported distro/init or missing dependency | Clear, non-mutating stop or warning, no false distribution certification |

**Release gate:** A successful Go read-only preview, shell dry-run, green
container CI or standalone Setup-like screens do **not** satisfy P01–P14.
The installer is not a drop-in replacement until the privileged backend,
runtime verification and post-install onboarding pass in a disposable
systemd environment and the relevant real-hub checks.
