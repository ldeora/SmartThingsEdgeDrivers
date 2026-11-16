# Computer Host LAN: Phase 2 Windows source alpha — 2026-11-16

## Deliverable

- Integration: v0.5.0-dev.1 (source-only)
- Linux agent / SmartThings Edge Driver: unchanged v0.4.0-dev.1
- New Windows agent: v0.1.0-alpha.1, C#/.NET 10, monitoring-only
- Protocol: v2 (`computer-host-agent`, `_computerhost._tcp.local`, TCP 8765)
- Windows profile: separate `computer-host-windows` main-only monitoring profile
  (no Linux load, unverified CPU temperature, or action controls)

## Results actually obtained here

- Python/Lua/Linux automated regression suite: **91 passed**, 0 failed.
  (87 existing tests + 4 static Windows-source contract tests.)
- Linux HTTP loopback smoke: PASS (read-only endpoints).
- Linux shell script syntax: PASS.
- Binary comparison to the original v0.4.0-dev.1 package: the **Linux agent,
  Linux installer scripts, Lua driver source and Linux device profile are byte-for-byte identical**.
- Release ZIP validated against SHA256 file manifest.

## Tests NOT performed

- `dotnet build` / C# execution (no .NET SDK or Windows host in this environment).
- Native DNS-SD registration callback / SmartThings hub discovery from Windows.
- Windows Service installation under LocalService; Windows Firewall behavior.
- Windows UI / telemetry rendering, real hardware CPU metrics, Fast Startup boot ID.
- Signed executable or installer; independent security audit; power commands and WOL.
- GitHub Actions workflow was prepared but **not uploaded or run**.

## How to make the next test real

1. Stage the full integration source under `linux-host-lan/` in a development branch.
2. Copy the packaged `.github/workflows/windows-agent.yml` to the **repository root**
   `.github/workflows/windows-agent.yml` (its paths include `linux-host-lan/`).
3. On GitHub Actions, run the `Computer Host Windows agent` workflow.
4. Fix any compiler or Win32 smoke issues reported by Windows Server 2025 runner.
5. Download the unsigned x64 development build *only for a trusted external tester*.
6. On Windows 11 hardware, first test the three read-only API endpoints and mDNS,
   then verify SmartThings discovery and state recovery, **without power control**.
7. Review Windows service installer/ACL/Firewall in a VM before deploying on a
   volunteer's primary computer. Keep Windows restricted to a trusted LAN.

Do not publish this package as a verified Windows release.
