# Computer Host LAN — release engineering brief

**Status:** v0.5.1-beta.1 release candidate, awaiting final CI, channel verification and permanent GitHub prerelease; not published yet.

## Functional scope

Shared SmartThings LAN Edge Driver for protocol v2 Linux and Windows agents. On Gentoo `hydra` the complete monitoring/reboot/suspend/WOL/shutdown/WOL path passed real hub tests. Windows v0.2.0-alpha.1 compiles, runs service/HTTP tests, and installs as LocalService with default-disabled opt-in power on a Windows Server 2025 CI runner. **Windows 11 SmartThings discovery and physical power transitions are outstanding.**

## Go/no-go for the public Community recruitment post

**Go** when a fixed CI-tested commit is available through a permanent checksummed GitHub prerelease; official host-agent installers, privacy-safe diagnostics and tester instructions are bundled; the Computer Host LAN beta driver channel invitation is verified; an issue intake template exists; and owners approve license/provenance and safety/unsupported-platform language.

**Do not claim** Windows 11 mDNS/WOL/full-shutdown validation, Linux distro hardware certification, signed installers, or guaranteed sleep-state compatibility.

Windows x64 first; Linux source/systemd installer in a separate asset; ARM64 cross-build can be offered as explicitly experimental. Native DEB/RPM, MSI, code signing and auto-updates remain later milestones.

## Evidence

[Windows CI](https://github.com/ldeora/SmartThingsEdgeDrivers/actions/runs/43827358333) · [Linux CI](https://github.com/ldeora/SmartThingsEdgeDrivers/actions/runs/43827358342) — passing at commit `366eff3`; validate the final release commit again.

Read [publication gates](docs/beta/PUBLICATION-GATES.md), [installation](INSTALLATION.md) and [privacy](docs/beta/SECURITY-AND-PRIVACY.md).
