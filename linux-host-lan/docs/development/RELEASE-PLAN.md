# v0.3.0 progress snapshot (2026-11-15)

**Locally implemented, not distribution-certified.** Agent HTTP security
bounded and installer transaction/rollback covered by automated tests.
SmartThings Edge Driver v0.2.9 remains the known hardware-validated state
machine. Agent v0.3.0 **has** now been installed and power-tested on Gentoo.

Open gates: Debian/Ubuntu/Fedora/RHEL VM installs, SELinux/AppArmor, genuine
network outage tests, credential provisioning/rotation, code provenance review
(Apache-2.0 selected) and signed releases. See [VALIDATION.md](VALIDATION.md).

---

# Linux Host LAN — public beta release gates

**Historical v0.2.11 baseline (superseded):** SmartThings Edge driver v0.2.9,
Linux Agent v0.2.2, WOL tools v0.2.10. Current beta uses Linux Agent v0.3.0
with the same Edge Driver v0.2.9; both have been hardware-tested on Gentoo.

## Gates

- **A — Identity/portability:** no host-specific values in runtime; stable
  UUID/key on update; interpreter version validated; correct discovery and
  fallback across distro network managers. Local automated work: IN PROGRESS.
- **B — Reliability:** clean/upgrade/rollback/power cycles and true network
  outages on 2+ non-Gentoo real hosts. Status: Gentoo PASSED, other distros OPEN.
- **C — Security:** review HTTP daemon, nonce DoS, HMAC credential ownership,
  helper acknowledgement, root socket permissions, SELinux. Status: OPEN.
- **D — Packaging:** agree manifest; generate native DEB/RPM from same versioned
  source; install, upgrade and remove in disposable VMs; preserve credentials.
  Status: STRATEGY PROPOSED, NO PACKAGES SHIPPED.
- **E — SmartThings distribution:** developer-owned custom namespace, channel
  onboarding, polished bilingual presentations, device profile migration,
  user guide and support policy. Status: PARTIAL.

## Tester report template

Distribution / version / architecture:
Python version and path:
Init and network manager:
SELinux/AppArmor mode:
Avahi/mDNS and firewall configuration:
Hub firmware/driver versions:
Monitoring-only or power-control opt-in:
NIC and WOL flags (omit MAC):
Agent start, restart, discovery, metrics:
Reboot, suspend/wake, shutdown/WOL:
Observed errors (redact keys, MAC, UUID, IP):
Reproduction steps:

## Local commands

```
./scripts/preflight.sh
./scripts/preflight.sh --interface enp3s0
sudo ./scripts/install-agent.sh --enable-power --wol-interface enp3s0
sudo ./scripts/diagnose.sh --interface enp3s0
python3 -m unittest discover -s tests -q
```

All example identifiers above are **illustrative**; replace the interface.
