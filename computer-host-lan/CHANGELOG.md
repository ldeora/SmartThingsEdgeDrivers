# Computer Host LAN — change log

## v1.0.0-rc.3

- Linux: unified full-screen maintenance/setup, review and literal consent, structured results, genuine terminal authorization, and deterministic terminal input ownership (#194, #200–#203). Plain accessible and CLI paths remain available. Historical restore and WOL check/removal retain separate authorization where needed.
- Linux release: full Go module/runtime notices asset, included in the unified checksums and documentation archive (#190/#206).
- Edge: Host Status on Linux/Windows device tiles with the existing switch action (#192/#205). Existing Linux device, routines and physical switch actions tested on the private channel. Unreachable inactive colour is a separate account-level presentation rollout.
- Windows Setup: plainer power wording, manual WOL hint, conditional upgrade note, fixed hub address tip, and current selection status that follows typed/cleared addresses and the local-network choice (#191/#207). Illustrated Windows quick start; screenshots included in the Windows ZIP.
- CI: transient HTTP request timeouts in the Windows recovery test are retried without weakening the overall test deadline (#204).
- Known limitation (#193): host power enablement may take time to appear in SmartThings; about one minute was observed on hydra, not a guaranteed maximum. Accepted for v1.0; metadata refresh improvement remains a follow-up.

- Linux: standalone release installer, protected install/upgrade/repair/uninstall/recovery; persistent wired WOL with explicit owned removal (#183–#185), retained rc.2 identity reuse (#186), historical restore (#187), maintenance menu (#188). Normal uninstall keeps credentials, snapshots and NIC WOL. Release builds require byte-identical Linux replicas and unified SHA-256/build metadata.
- Windows: preserve validated firewall scope and power preference during Setup/ZIP upgrades; runtime retained-state checks, DNS-SD retry and per-source connection limits (#173/#174/#179/#180).
- Edge: bounded cooperative HTTP request budget, command acknowledgements and safer endpoint selection (#175/#177/#178); protocol v2 unchanged.
- Documentation: version-specific upgrade, reinstall and recovery journeys (#181). Exact-candidate hardware acceptance remains pending.

- Windows: `ComputerHostAgent` now displays a service description in Windows Services (`services.msc`), set on fresh installations and upgrades through both Setup and PowerShell.
- Switch ON: after successfully transmitting the Wake-on-LAN magic packets, acknowledge the switch command immediately with ON while Host Status remains `starting`. A matching health response confirms `running`; if boot never succeeds, existing 180-second pending expiry and reachability inference restore OFF where appropriate (including a previously settled `stopped` state). A successful UDP send does not prove the computer has booted. Rejected Wake packets do not emit ON. This adjustment only affects the main switch; the separate momentary Wake control is unchanged. Gentoo hardware validation required.
- Switch OFF: acknowledge an accepted shutdown immediately. Previously the driver only set Host Status to `stopping`, so the SmartThings app waited for its command timeout, showed "A network or server error occurred", and the switch went Off only after repeated host timeouts. The switch now turns Off when the agent answers HTTP 202 and stays Off while the agent may still answer during the 60-second shutdown grace period (new `State.SHUTDOWN_GRACE_SECONDS`). A cancelled or blocked shutdown returns the switch to On after the grace period, as before for Host Status.
- Duplicate OFF commands during `stopping` are ignored instead of re-sent, so a Windows HTTP 409 can no longer flip the switch back On. A new OFF after the host is `running` again is sent normally. ON and momentary Wake/reboot/suspend controls during shutdown grace cannot overwrite the pending shutdown action. A new boot ID restores ON/running immediately even within the grace period. Rejections, including Windows HTTP 409 (another power operation pending, or a shutdown or reboot already in progress), keep their existing handling.
- Fix (pre-existing): Host Status `stopped`/`suspended` lasted only one health check. Confirming the shutdown cleared the pending action, so the next silent check fell back to the generic `unreachable`. The inferred state is now kept while the host stays silent and is cleared by a sign of life (health reply or refused connection). Other errors show `unknown` without discarding the inference. Found in the Gentoo hub test on 2026-11-22.
- **Important for automations:** The main switch now acknowledges accepted shutdown and successfully transmitted Wake requests, before actual power transitions complete. Host Status separately tracks progress. Use Host Status = Stopped or Running for automations that require confirmed/inferred completion rather than relying on Switch = Off/On.
- Known limitation (unchanged, deferred): rejected commands (failed Wake, rejected Off) and On during `stopping` can still end in the app's generic timeout message.

## v1.0.0-rc.2 (published prerelease 2026-11-21 UTC) — post-rc.1 stabilization

- Published [GitHub prerelease](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.2) from commit `72e4a99c4b2e8f958ce771152826319318d0d537`: integration **1.0.0-rc.2**, Linux/Edge **0.4.6-rc.2**, Windows agent **0.2.7-rc.2**, protocol v2 unchanged. Four unsigned deliverables plus `SHA256SUMS.txt`; SmartThings channel assignment is separately verified.
- PR #56: enforce the driver's four-second LuaSocket HTTP timeout and Linux's cumulative header deadline, including slow-client regression tests (#30, partial #31).
- PR #57: Windows native shutdown/reboot acceptance and 409/503 error mapping; Linux power-helper path validation and acknowledgment ordering, with safe delayed shutdown/reboot attempts (#33, #44).
- PR #58: refuse Windows ProgramData state with untrusted owner/permissions/reparse points; atomic protected-directory creation and path-specific ACLs, retaining credentials and UUID across legitimate upgrades (#32).
- PR #59: retry unconfirmed device creation after 120 seconds, preserve known switch state on failed Wake, warn about Windows Public profile while retaining Private-only firewall, and permit redacted beta/RC reporting on a custom local port (#34, #37, #46, #47).
- PR #60: align published rc.1 metadata and security/docs with the actual tag, distinguish rc.1 from post-tag hardening, verify bundled notes exactly (#52–#54).
- Publisher reports an rc.2 Gentoo Linux upgrade running as expected (2026-11-21). Individual rc.2 power tests, Windows 11 acceptance, additional Linux hardware and seven-day soak are still needed before stable. See [rc.2 notes](docs/release/RELEASE-NOTES-v1.0.0-rc.2.md).

## v1.0.0-rc.1 (published prerelease 2026-11-20 UTC) — installation and update readiness

- Coordinated candidate versions: Windows agent 0.2.6-rc.1; Linux agent and SmartThings Edge driver 0.4.5-rc.1; protocol v2 unchanged.
- Improve initial Windows hub-search painting and preserve the selected hub IP if a discovery retry fails (merged PRs #23 and #27).
- Make the Windows upgrade health check follow the packaged agent version; clarify detectable failure/recovery messaging (PR #28).
- Retain v0.5.6 hardening for agent identity, installer rollback, mDNS, optional power, NIC selection, Linux WOL configuration and SmartThings transient state accuracy.
- Prepare concise RC installation instructions and version-coherent checksummed assets. No new pairing, secret rotation, device capabilities or automatic publication.
- Physical Windows 11 rendering/upgrades, Linux hub testing, channel assignment and soak validation remain pending.

## v0.5.6-beta.1 (published 2026-11-20) — consolidated installer and runtime hardening

- One consolidated release candidate instead of separate installer/runtime betas.
- Installer: restore abandoned upgrades, gate commit on actual agent health and identity, canonical hub IP validation and reconfiguration helper.
- Windows: mDNS retry, physical NIC WOL selection, privilege preflight, atomic identity, per-service SID ACLs.
- Linux: atomic ID/token state, conservative WOL link conflicts, fixed diagnostics.
- Edge: bounded state-context improvements for delayed shutdown and transient suspend failures.
- v0.5.5-beta.1 hardware validation: volunteer confirmed full upgrade/service/status/metrics/controls/WOL on Windows 11 Pro.


## v0.5.5-beta.1 (published) — stabilization from merged PR #19

- Correct Windows `/v2/info` runtime agent version and assert component versions against the release manifest.
- Protect the existing authentication token ACL on upgrades; preserve customized Windows ZIP/PowerShell configuration and align firewall/installer diagnostics with the configured HTTP port.
- Snapshot existing Windows application and firewall settings before graphical upgrades; restore service/configuration on detected failure, with regression coverage.
- Clear stale suspend/cancelled-shutdown states when a host remains or becomes reachable, without claiming actual power completion.
- Add source/CI checks, updated compatibility evidence and dependency/provenance notices. No protocol-v2 schema change and no alteration to published beta assets.


## v0.5.4-beta.1 (2026-11-19) — native Windows guided installer (candidate)

- PR #17 merged into `main`; Windows x64 Inno Setup 7 wizard is now the recommended beta installer, with the original ZIP/PowerShell route retained.
- Wizard includes mDNS hub discovery and editable IPv4 selection, retry and explicit Private LocalSubnet firewall fallback, a separate opt-in power page, SmartThings channel onboarding, masked/copyable private key and safe Installed apps uninstall.
- Existing ZIP/PowerShell installations can migrate directly to Setup, preserving UUID, token, customized appsettings and power preference. Normal uninstall retains ProgramData. The PowerShell fallback still requires `-EnablePower` on each upgrade.
- Windows Server 2025 GUI, clipboard, migration, upgrade, service-ownership safety and uninstall passed CI ([run 44515639490](https://github.com/ldeora/SmartThingsEdgeDrivers/actions/runs/44515639490)). Real Windows 11 discovery/interaction and WOL require public-beta hardware tests.
- Linux agent and Edge driver stay at v0.4.2-beta.1. Windows agent v0.2.3-beta.1; protocol v2 unchanged. Release workflow now prepares both the standalone Setup.exe and existing Windows ZIP with checksums.


## v0.5.3-beta.1 (2026-11-18) — four-value resource telemetry (candidate)

- PR #15 adds exact RAM used/available and root/system filesystem allocated/available byte metrics on Linux and Windows; existing percent/total readings remain unchanged.
- SmartThings `computerMemoryUsage` and `computerDiskUsage` now display Usage %, Total GiB, Used GiB, Available GiB with English/German translations and responsive app layout.
- Linux Gentoo hydra + real hub validation passed 2026-11-18; all eight readings populated, existing events/automations retained. A transient memory-translation HTTP 422 succeeded after retry.
- Windows agent measurements tested in CI; Windows 11 hardware validation of new values remains a beta objective. No protocol, discovery, identity or power-control changes.
- Linux and Edge Driver v0.4.2-beta.1, Windows agent v0.2.2-beta.1; preserved v0.5.2-beta.1 as published baseline.


## v0.5.2-beta.1 (2026-11-18) — filesystem-capacity beta update (published)

- PR #13 adds `disk_root_total_bytes` for Linux root and Windows system volume, mapped to a new SmartThings `diskTotalGiB` readout alongside disk usage %.
- Additional field is optional and protocol v2 is unchanged. Existing UUIDs, keys, discovery, power behavior and device profiles remain compatible.
- Verified on real SmartThings hub with Gentoo Linux after a hub reboot refreshed the updated custom capability; Windows implementation passed CI, but Windows 11 hardware capacity remains an important beta test.
- Versioned next-beta candidate: Linux agent and Edge Driver v0.4.1-beta.1, Windows agent v0.2.1-beta.1.
- Published GitHub prerelease and assigned matching driver to the existing channel on 2026-11-18; v0.5.1-beta.1 assets are preserved.


## v0.5.1-beta.1 (2026-11-16) — public-beta release candidate

- Cross-platform Computer Host LAN integration packaged for volunteer testing with an independently versioned protocol-v2 Linux agent, shared Edge Driver and native Windows Host Agent.
- GitHub CI now assembles and verifies a complete unsigned Windows x64 kit (installer, verifier, sanitized diagnostics, test checklist and license) alongside Linux source and documentation archives, using SHA-256 manifests.
- No changes to the hardware-validated Linux agent and Edge Driver runtime; Windows 11 mDNS discovery and physical power/WOL compatibility remain **untested**.
- Publication is **pending** final versioned CI, copyright/provenance review, permanent GitHub Release assets and a working SmartThings beta channel invitation.

## v0.5.1-dev.1 (2026-11-16) — cross-platform CI candidate

- Retains the Linux v0.4.0-dev.1 reference agent and its hardware-validated SmartThings Edge Driver behavior.
- Native Windows Host Agent v0.2.0-alpha.1 provides CPU/RAM/drive/uptime telemetry, Windows Service and DNS-SD registration, opt-in HMAC-authenticated reboot/shutdown/suspend and candidate WOL metadata.
- Windows Server 2025 x64 CI verified compilation, self-contained publishing, protocol/HMAC tests, HTTP smoke, LocalService installation, protected state, and PowerShell 5.1 opt-in/out. Real Windows 11 SmartThings and hardware power behavior remain **unverified**.
- Windows ARM64 cross-publish verified; runtime untested.
- Separate `computer-host-lan/` project directory; independent `linux-host-lan/` retained.
- Follow-up repository cleanup updates active CI workflows, versioned source-manifest generation, current beta guidance and issue reporting. No Windows or Linux runtime changes in that cleanup.
- Not yet a released public-beta version. No SmartThings channel invitation or permanent GitHub release assets yet.

## v0.5.0-dev.1 (2026-11-16) — Windows monitoring source

Initial Windows monitoring agent implementation and test scaffolding.

## v0.4.0-dev.1 (2026-11-16) — generic protocol v2

New `_computerhost._tcp` discovery, `computer-host-agent` API v2, shared driver, platform-specific profiles and custom monitoring capabilities. Linux successfully validated on Gentoo `hydra`.

Older Linux-only release history: [archived change log](docs/history/v0.3.1-beta.1/CHANGELOG.md).
