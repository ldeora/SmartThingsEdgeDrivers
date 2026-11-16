# Computer Host LAN — beta status (2026-11-16)

**Release candidate:** integration v0.5.1-beta.1; Linux agent/Edge Driver v0.4.0-dev.1; Windows agent v0.2.0-alpha.1. **No Computer Host LAN GitHub prerelease has been published yet.**

**Confirmed:**
- Gentoo `hydra` + SmartThings hub: protocol v2 discovery/telemetry, interruption recovery, reboot, suspend/WOL and shutdown/WOL (real hardware).
- Windows x64 on Windows Server 2025 CI: .NET 10 compilation, self-contained publish, protocol/HMAC tests, HTTP smoke, actual Windows Service installation as LocalService, protected persistent state, PowerShell 5.1 monitoring/power opt-in/power opt-out tests. No actual power command was issued.
- Windows ARM64: cross-publish only.
- Linux CI: Python 3.10–3.14 and Debian/Ubuntu/Fedora container/source tests.

**Unverified:** Windows 11-to-SmartThings LAN discovery; Windows native DNS-SD on volunteer networks; Windows suspend, reboot, shutdown/WOL on physical hardware; non-Gentoo Linux service/power lifecycle; SmartThings cross-account enrollment and Windows profile presentation.

**Before announcement:** check ownership/provenance of the Apache-2.0 license, publish the new driver to an accessible SmartThings beta channel, create a permanent reproducible versioned GitHub prerelease with checksums, publish installation/feedback/upgrade paths, and review safety notices. The developer branch and temporary CI artifacts are not adequate distribution URLs.

See [publication gates](docs/beta/PUBLICATION-GATES.md) and [compatibility](docs/beta/COMPATIBILITY-STATUS.md). Earlier Linux-only beta documents are kept under `docs/history/v0.3.1-beta.1/`.
