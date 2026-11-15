# Beta validation status

**Candidate:** v0.3.1-beta.1 (agent v0.3.0; driver v0.2.9).

**Hardware verified:** Gentoo Linux (systemd), mDNS discovery, telemetry, graceful reboot, suspend/WOL and shutdown/WOL, device-state synchronization, upgrade preserving credentials.

**Source and smoke checks:** automated unit suite plus Debian 13 loopback HTTP smoke / installer preview; no proof of full Debian systemd service or hardware compatibility.

**Not yet verified:** Ubuntu/Fedora/RHEL/openSUSE/Arch service installation, SELinux/AppArmor, beta channel on another SmartThings account, independent security review, real VM lifecycle rollback, GitHub Actions matrix, code provenance/attribution verification and signed public release. The project owner selected Apache-2.0 and the full license is included in the source and agent bundles.

Power actions are opt-in and intended only for trusted LANs; run monitoring-only tests first.
