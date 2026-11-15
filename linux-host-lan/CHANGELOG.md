# Changelog

## 0.3.1-beta.1 — GitHub-ready closed-beta preparation (2026-11-15)

- Preserves Linux Agent **0.3.0** and Edge Driver **0.2.9** without runtime changes.
- Adds standalone Linux agent release packaging, beta tester guidance, redacted support diagnostics and compatibility reporting.
- Cleans repository layout and documents GitHub publication, security and license gates.
- Confirms the owner's **Apache-2.0** license choice; includes full `LICENSE` in repository and standalone agent bundles, without runtime changes.
- Defines multi-distro CI workflows as **inactive templates**; they have not yet been executed.

## Linux Agent 0.3.0 — Hardening

- Bounds HTTP listener concurrency, header size and request timeouts; adds authentication challenge/rate controls and nonce replay handling.
- Transactional systemd installer with dry run, recovery snapshots, rollback and explicit uninstall.
- Agent 0.3.0 and Edge Driver 0.2.9 verified together on Gentoo hardware (monitoring and power-control cycle).

## Edge Driver 0.2.9 — State and presentation

- Adds reachability-aware running/unreachable/power-transition state logic, reboot boot-ID detection and event deduplication.
- Includes advanced telemetry capabilities, English/German capability presentations and short human-readable uptime.
