> **Historical Linux-only v0.3.1 source document.** It describes the
> pre-refactor release and must not be used as evidence of hardware
> validation for v0.4.0-dev.1. For the current architecture read
> `README.md`, `PROTOCOL.md`, `INSTALLATION.md` and
> `docs/development/LINUX-PARITY-ACCEPTANCE.md`.

# v0.3.0 update

The security/installation preview now contains a bounded HTTP listener,
challenge throttling, transactional manual installer, rollback, explicit
uninstall, and cross-Python/CI test scaffolding. These changes are **locally
tested only**; prior public-beta release gates remain open for cross-distro
service testing, security review, package builds, key rotation, and signed
release publication. See `INSTALLATION.md`, `SECURITY-HARDENING.md`,
`VALIDATION.md` for authoritative current instructions.

---

# Public beta readiness checklist — v0.2.10

## Locally implemented

- [x] Local mDNS identity, UUID validation, rediscovery and retry behavior.
- [x] HMAC-SHA256 authenticated power requests with single-use nonce and
      restricted helper socket (opt-in).
- [x] WOL and power control regression baseline preserved from v0.2.8.
- [x] Custom telemetry and compact uptime, numeric automation attributes.
- [x] Explicit state reducer with failure/error distinctions and persisted
      pending actions / boot ID.
- [x] Installer with Python path detection, optional persistent WOL setup;
      dry-run support and non-secret diagnostic helper.
- [x] English/German translations and short load labels ready for account
      registration; no destructive capability changes.

## Live testing still required

- [x] v0.2.9 on Gentoo: all three power actions and wake from suspend/S5 — PASSED (15 Nov 2026).
- [ ] Hub restart mid reboot/suspend/shutdown; changed boot ID detection.
- [ ] App rendering and translation after manual cloud presentation update.
- [ ] Host offline due to router outage, agent stopped and wrongly assigned IP.
- [ ] Real Linux installations with NetworkManager (Ubuntu/Fedora),
      systemd-networkd (Gentoo), and at least one additional distribution.
- [ ] Persistent WOL across NIC link bounce, reboot and full shutdown.
- [ ] IPv6-only/multi-NIC and multicast-unavailable manual discovery.
- [ ] Security audit of root helper, API signing, listener binding and
      rate limiting; independent threat-model review.
- [ ] Distributions with mandatory access controls; user/group permissions.
- [ ] Installation, upgrade, rollback, uninstall and secret rotation docs.
- [ ] Dedicated public-release namespace/ownership policy and user consent.
- [ ] Community pilot feedback, screenshots, failure-rate observations.

**Not a certification claim.** No user-facing API action is performed by
building these files; cloud presentation updates and device driver installs
remain explicit operator actions.

See `RELEASE-PLAN.md`, `SECURITY-REVIEW-RELEASE.md`, and `DISTRO-MATRIX.md` for release gating and compatibility evidence.
