# Release / distribution gates

The following block an unrestricted public beta; a small privately shared source-testing pilot may validate these items, but must carry explicit safety and compatibility warnings.

- [x] **Select a license:** project owner chose Apache-2.0; full `LICENSE` included in source and agent bundles.
- [ ] **Confirm rights and attribution:** verify provenance and ownership of any reused or third-party code; add any required notices before public release.
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

**Still open:** copyright/provenance review, cross-distro CI execution, distribution-specific systemd/MAC policy tests, external hardware validation and release signing/publishing. Selecting Apache-2.0 does not close the other gates. The CI workflow template is only a proposal until activated and run.
