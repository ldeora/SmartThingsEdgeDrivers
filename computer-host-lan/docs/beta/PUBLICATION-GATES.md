> **Historical v0.3.1-beta.1 beta document.** This page describes the previous Linux-only
> integration and is **not** a valid installation or protocol guide for
> v0.4.0-dev.1. Use root `README.md`, `PROTOCOL.md` and `INSTALLATION.md`.

# Release / distribution gates

The following block an unrestricted public beta; a small privately shared source-testing pilot may validate these items, but must carry explicit safety and compatibility warnings.

- [ ] **Choose an open-source license** and add actual `LICENSE` file with correct author rights. No license is currently selected by this assistant on behalf of the project owner.
- [ ] Select source repository, public issue tracker, disclosure contact, update/support scope and code-of-conduct expectations.
- [ ] Pin third-party GitHub Actions to reviewed commit SHAs; review source dependencies and Python testing-only dependency policy.
- [ ] Run the six-distro GitHub Actions matrix; publish links to successful runs and attach artifacts. A workflow file alone is not evidence.
- [ ] At least two target environments outside Gentoo perform a **systemd PID 1 installation**; one should enforce SELinux/AppArmor.
- [ ] At least one additional physical host confirms monitoring; power/WOL testing only where hardware is capable.
- [ ] Verify unattended install failure, rollback, uninstall and reinstall with real service activation, not just mock tests.
- [ ] Confirm authenticated reboot/suspend/shutdown flow, nonce replays, failed requests and recovery on supported hardware.
- [ ] Review listener TLS/trusted-LAN threat model and authenticated power-key lifecycle; provide key rotation instructions.
- [ ] Publish SmartThings Edge driver in designated beta channel, verify advanced profile and custom presentations on a *new* developer/tester account.
- [ ] Prepare signed, checksum-verified release source files, privacy-safe diagnostics, install/upgrade/uninstall instructions and explicit support boundaries.
- [ ] Decide DEB/RPM packaging ownership and migration strategy; package artifacts remain deferred until their own lifecycle tests pass.

**Blocked today:** licensing decision, actual cross-distro CI execution, distribution-specific systemd/MAC policy tests, external hardware validation and production signing/publishing. The checked-in CI workflow is only a proposal until run.
