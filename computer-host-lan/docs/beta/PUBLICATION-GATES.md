# Computer Host LAN — public beta publication gates

The intention is to **recruit real hardware testers**, so Windows 11 and multi-distribution power-state certification are not prerequisites. The following distribution hygiene requirements *are* prerequisites for a public forum announcement:

- [x] Separate driver source and package key from legacy `linux-host-lan`.
- [x] Linux Gentoo hardware reference (discovery, telemetry, WOL/power).
- [x] Windows x64 build, HTTP contract, LocalService install, opt-in/out CI; ARM64 cross-publish clearly labeled.
- [x] Source license file present (Apache-2.0); **owner still to confirm rights and attributions before redistribution**.
- [ ] Resolve repo-level stale docs and release metadata; ensure documented CI results match real runs.
- [ ] Review and merge project PR into `main` (or publish a deliberate stable branch with permanent links).
- [ ] Produce versioned, checksum-verified assets from an immutable tested commit; no temporary Actions artifact link in forum post.
- [ ] Include Windows x64 installer, source/Linux installer, guides, sanitized diagnostics, upgrade/removal instructions and known limitations; inspect ZIP contents from a fresh checkout.
- [ ] Verify GitHub Issue template, privacy/security reporting and release update procedure.
- [ ] Publish publisher-owned Computer Host LAN Edge Driver to appropriate beta channel; generate invitation link.
- [ ] Validate channel enrollment with a separate SmartThings account/hub and both profiles' presentations if possible.
- [ ] Publish explicit caution: power commands disabled by default; no TLS on LAN telemetry; Windows NIC/S0/S3/S4/S5 wake not guaranteed; unsigned beta.
- [ ] Confirm copyright attribution/code provenance and any redistributed dependency terms.

**After announcement:** Windows 11 real-hardware discovery/power, additional Linux distributions, persistent WOL across configurations, and installer edge-case testing are volunteer acceptance scenarios. DEB/RPM, MSI, code signing, automatic updates, complete ARM64 hardware support and broader OS guarantees can be postponed, explicitly marked unavailable.

Evidence: [Windows CI](https://github.com/ldeora/SmartThingsEdgeDrivers/actions/runs/43827358333) · [Linux CI](https://github.com/ldeora/SmartThingsEdgeDrivers/actions/runs/43827358342). Both reference commit `366eff3`; rerun after publication changes.
