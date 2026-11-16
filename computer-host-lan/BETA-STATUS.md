> Phase 2 notice: The Linux v0.4.0-dev.1 reference passed five core
> hardware-validation milestones on `hydra` as reported by the owner on
> November 16, 2026. This does not certify other Linux distributions.
> New Windows v0.1.0-alpha.1 is **source-only and uncompiled** at this stage.
> Windows CI workflow is defined but not yet executed; no real Windows
> discovery/service/power validation has been performed. Details in
> `windows-agent/README.md` and `windows-agent/docs/HARDWARE-TEST-MATRIX.md`.

> **Historical Linux-only v0.3.1 source document.** It describes the
> pre-refactor release and must not be used as evidence of hardware
> validation for v0.4.0-dev.1. For the current architecture read
> `README.md`, `PROTOCOL.md`, `INSTALLATION.md` and
> `docs/development/LINUX-PARITY-ACCEPTANCE.md`.

# Linux Host LAN closed-beta preparation: v0.3.1-beta.1

## Current runtime baseline (unchanged)

- Linux Host Agent **v0.3.0** (protocol v1), hardened HTTP listener, dedicated `linuxhost` account and opt-in restricted privileged power helper.
- SmartThings LAN Edge Driver **v0.2.9**, publisher-owned monitoring custom capabilities, switch control and state reducer.
- Known-working real-hardware reference: Gentoo Linux/systemd 261/Python 3.14 with monitoring, agent interruption/recovery, reboot, suspend/resume and full shutdown/WOL boot successfully exercised on 2026-11-15.

## Engineering work added in this candidate

- Six-image GitHub Actions source-smoke **workflow** (Debian 12/13, Ubuntu 24.04/26.04, Fedora 43/44); **not yet executed on GitHub**.
- `scripts/ci/run-container-tests.sh` includes source/unit regressions, dry-run installer and disposable `/v1` HTTP smoke test, as nonroot if possible.
- `scripts/beta-report.sh` generates a diagnostic report that excludes host IP/MAC, hostname, secrets, UUID and SmartThings identifiers; the operator must review any additional logs manually.
- A volunteer installation guide, compatibility matrix, security/privacy boundaries, test checklist, packaging decision, issue-report format and SmartThings channel rollout instructions.
- **Debian 13 source smoke executed locally**: original 73 runtime tests plus new beta checks, installer preview and disposable loopback HTTP agent (nonroot process). Real systemd/Avahi/power-management integration on Debian remains untested.

## What this is **not**

Not a finished public beta, a distribution certification, an audited RPM/DEB, a successful six-distro GitHub Actions run, or a third-party security audit. The installer presently supports systemd PID1 only. Initial pairing for ordinary users requires Avahi/mDNS; manual-host first discovery still needs Edge Driver source modification.

## Release blockers

1. Explicit copyright-holder licensing choice and valid LICENSE.
2. Repository, issue tracker, release signing and update/support scope.
3. Real GitHub CI results and systemd-PID1 installation tests on additional distributions.
4. Fedora or other mandatory access-control validation, cross-account SmartThings pairing and physical tester feedback.
5. Security review of local HTTP trust model and user-entered HMAC key handling.
6. Native package lifecycle validation, if DEB/RPM are to be included in the public beta; otherwise retain the source/script installer.

See `docs/beta/PUBLICATION-GATES.md` for the actionable checklist.
