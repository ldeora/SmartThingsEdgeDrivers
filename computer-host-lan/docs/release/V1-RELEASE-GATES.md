# Computer Host LAN — first stable release gates (v1.0.0)

**Planning document for stable v1.0.0, not proof of completed acceptance.** The current [published prerelease v1.0.0-rc.2](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.2) was built from immutable source commit `72e4a99c4b2e8f958ce771152826319318d0d537`. v0.5.5-beta.1 is the last independently Windows 11 hardware-tested fallback. Refer to [release readiness](../../RELEASE-READINESS.md) for current evidence and [RC acceptance](RC-ACCEPTANCE.md) for per-platform checks. Several originally planned rc.2 publication gates remain open; publication does **not** retroactively mark them PASS.

## Intended 1.0 contract

Computer Host LAN monitors supported Linux and Windows computers over a trusted private LAN using protocol v2 and optional, explicitly enabled, authenticated shutdown/reboot/suspend. WOL is best effort and hardware-dependent. Preserve the installation UUID, SmartThings device network identity, existing driver/channel IDs, custom capability IDs and established attribute semantics; preserve the existing 256-bit control key during upgrades. No device re-pairing should be necessary.

**Not in scope for 1.0:** automatic pairing; routine/automatic key rotation; new authentication or HTTP transport; Windows tray application; WinGet or new APT/DNF repository; native DEB/RPM; macOS; TLS/mTLS; extra metrics or power actions. These are not prerequisites for stability. If a credential is lost or compromised, document a **manual recovery** procedure which does not silently reset the identity or enable power; do not implement rotation in this release.

### P0: original rc.2 entry-gate evidence (outstanding items carry into stable review)

These requirements were drafted before rc.2 publication; unchecked items remain open for the stable decision, without implying that they were satisfied at prerelease publication.

- [ ] **Close v0.5.6 verification:** record published tag and source SHA, four unsigned assets and `SHA256SUMS.txt`, `BUILD-INFO.json`/manifest component versions, and all four CI workflows on the exact release commit. Check that Edge driver 0.4.4-beta.1 is assigned and installed on a real hub on the **existing** channel/driver ID. Never infer assignment from the release link.
- [ ] **Resolve reproducible installer defects:** first hub-search painting glitch reported on Windows 11; verify any isolated fix on the reporting hardware (fresh wizard start, initial search, second search, manual IP, Advanced options, Next/Back) and run native Inno GUI compilation/tests. A CI window-control smoke test cannot prove pixels are painted correctly.
- [ ] **Windows installation and upgrade:** on two independent physical Windows 11 x64 systems with different NICs, validate monitoring-only defaults, hub discovery/manual IP, working SmartThings display, version reporting, service stop/recovery, in-place upgrade, untouched UUID/key/configuration/custom port and uninstall preserving state. If privileged commands are enabled, verify reboot/suspend/shutdown only on consented machines with physical recovery. Record failure modes separately from unsupported S0/S3/S4/S5/WOL.
- [ ] **Linux reference and additional installation:** repeat real Gentoo `hydra` protocol-v2 monitoring/service/reboot/WOL checks after the candidate upgrade; validate at least one physical Debian or Ubuntu system with systemd and Avahi, installation, service recovery, upgrade and identity preservation. Fedora (SELinux enforcing/firewalld) is only advertised as hardware-verified after a real host test; container CI is not equivalent.
- [ ] **Compatibility and upgrade safety:** verify the new Edge driver does not create duplicate computer devices when agents are upgraded; older protocol-v2 agents must continue to work for already-supported fields or any breaking minimum version must be declared before RC. Never modify old capabilities/profiles or force re-pairing to cure an update.
- [ ] **Security/documentation:** current, non-historical `SECURITY.md` and short user-facing disclosure of unencrypted read-only HTTP telemetry, trusted-LAN firewall restrictions, retained secret in SmartThings preference, HMAC/nonces, monitoring-only defaults and WOL limitations. Review no key/token leakage through installer, diagnostics, logs or release assets. Record a clear code-signing decision; do not imply signing removes SmartScreen warnings.
- **Third-party notice automation (#118):** best-effort, non-blocking follow-up for v1.0, not a P0 release gate. The publisher remains responsible for applicable redistribution terms and existing notices; incomplete automated evidence does not establish compliance. Formal notice automation and signing/independent attestation integration are deferred to v1.2. Applicable redistribution obligations remain.
- [ ] **User documentation:** one up-to-date Windows quick start and one Linux quick start, upgrade/uninstall guide and troubleshooting reference; published version links sourced from `release.json` and checked by tests. Keep historic release-engineering content separate.
- [ ] **Freeze and traceability:** document agent/driver compatibility, version policy (public integration release vs internally versioned agents), explicit platform support and known hardware limitations. Freeze protocol v2's existing semantics for the 1.x line, allowing backward-compatible optional additions only.

### P0: gate from published v1.0.0-rc.2 to stable v1.0.0

- [ ] **Linux installer convergence (#101):** one protected schema-1 engine
  for install, upgrade, repair, uninstall, recovery, persistent wired WOL,
  explicit retained rc.2 state reuse and historical restore. Implemented in
  #164–#188; legacy mutations remain refused. No elevated Python override.
  Cutover requires the version-matched release binary, real-host acceptance
  and current user documentation. See [maintenance journeys](UPGRADE.md).
- [ ] **Linux installer distribution (#84):** maintainer decision 2026-11-26:
  formal signing and independent attestation/approval deferred to v1.2.
  rc.3 and v1.0 use unsigned release packages from the exact approved source,
  reproducible Linux binary builds, build metadata and SHA-256 verification.
  Normal release workflow must include the standalone Linux installer.
  Independently authenticated provenance is optional, not mandatory.
  Do not substitute ordinary CI artifacts; checksums verify bytes, not
  publisher identity. The optional attestation workflow retains its own
  requirements if used. Verify helper promotion/recovery and legacy refusals.

- [ ] Run a **minimum seven-day unattended soak** on at least one physical Windows 11 system and one Linux host with a real SmartThings hub; log dates, exact binaries/driver version, reconnects, resource use and any duplicate/stuck state.
- [ ] Exercise hub restart, agent stop/start, computer reboot, a router/network interruption and host DHCP address change (where feasible); separate a **hub IP change** from a **host IP change**, because the Windows firewall may intentionally scope access to the hub's previous IP.
- [ ] Validate all five required repository workflows on the **final merged main SHA**. Build the proposed stable release assets from the final stable commit, checking source/embedded versions, reproducible Linux build, SHA-256 and build metadata; do not mix commits or replace existing rc.2 release assets.
- [ ] Verify Windows x64 first install and upgrade from v0.5.5/v0.5.6 on an existing device; verify Linux upgrade. Failure recovery must retain known-good snapshot/state. Recheck SmartThings channel assignment separately from GitHub publication.
- [ ] Perform final security, download integrity and supported-platform sign-off; record the status of advisory #118 separately. Publish a new stable tag only after explicit approval; never retag or overwrite existing published betas. Test permanent links and disclose unsigned status if applicable.

### P1: useful before or shortly after stable, not automatic blockers

- Separate, low-noise SmartThings diagnostic status and compatible agent-version display without overloading the existing `computerHostStatus.status` enum. Changing custom-capability schemas/presentations requires cloud-side rollout and migration testing, not just an Edge ZIP.
- GitHub Issue forms and manual-redaction diagnostics guidance.
- SBOM and GitHub artifact provenance attestation, if implementable and validated without destabilizing packaging.
- German translation of the user quick starts, after the English instructions are accurate.

## Evidence policy

Use **PASS / FAIL / N/A / NOT TESTED** and record OS build, NIC, hub model/firmware, agent/driver version and safe redacted CI/test references. A successful command HTTP 202 is not physical power-state confirmation. A feature supported on one Windows machine does not imply universal Modern Standby, S5 or Wake-on-LAN support. A single unconfirmed report must not be labeled a reproduced regression.

The November 20 Windows 11 Pro reports include a successful reboot on one tester's installation, a separate unconfirmed reboot complaint, and a first-search wizard painting defect with correct hub discovery. Do **not** modify power implementation based on the unconfirmed complaint; collect the agent's `/v2/info.power_actions` and the tester's settings if repeated. The rendering report is a user-visible release-quality issue until the fix is verified on real Windows.

## Go / no-go

The project is **GO** for a candidate only after all P0 RC-entry gates have evidence (or supported-platform scope is narrowed explicitly). It is **GO** for stable only after the RC-to-stable gates pass without unresolved critical security, data loss, installation regression, duplicate device or persistent stuck-state defects. Record any waived noncritical item and its user-facing limitation; do not convert unverified functionality into a supported claim.

**No key rotation, silent credential replacement, hardware power tests or production-device changes are authorized by this checklist.**
