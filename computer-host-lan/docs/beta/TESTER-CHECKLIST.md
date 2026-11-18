# Computer Host LAN — hardware beta test checklist

**Record:** OS + version/build, architecture (x64/ARM64), host agent version, Computer Host LAN driver version, hub model/firmware, wired/wireless interface class and whether WOL is expected. Use **PASS / FAIL / N/A / NOT TESTED** for each. Never include the control token, personal hostname, internal IPv4/MAC, hub location or unredacted device IDs.

## Monitoring / discovery (all testers)

- [ ] M01: Downloaded the matching versioned package; verified SHA-256 / package integrity.
- [ ] M02: Installer dry run/preview; installed monitoring **without** power opt-in.
- [ ] M03: Service runs as restricted principal (`linuxhost` on Linux; `LocalService` on Windows).
- [ ] M04: `/v2/info` reports correct `platform`, protocol v2, power actions empty by default.
- [ ] M05: `/v2/health` and `/v2/metrics` provide non-fabricated values.
- [ ] M06: Computer is discovered through `_computerhost._tcp` by the hub on a trusted LAN.
- [ ] M07: SmartThings device is unique, correct Linux/Windows profile, usable app presentation.
- [ ] M08: CPU, RAM, disk, uptime, status and switch update; missing optional sensors do not break other metrics.
- [ ] M08a: New `/v2/metrics` includes a positive `disk_root_total_bytes`, and SmartThings shows a plausible `diskTotalGiB` for that exact root/system volume; record if a hub restart was needed.
- [ ] M08c: On RAM **and** root/system filesystem cards, confirm Usage %, Total GiB, Used GiB and Available GiB. Check raw `memory_used_bytes`, `memory_available_bytes`, `disk_root_used_bytes`, `disk_root_available_bytes` against OS readings. Used + Available need not equal Total on reserved-block/quota-restricted filesystems; do not treat that as an automatic failure. Record localized label/layout issues.
- [ ] M08b: In-place upgrade retains the same SmartThings device, agent installation ID and control key; Linux preserves power opt-in, Windows requires explicit `-EnablePower` to preserve it.
- [ ] M09: Stop only agent; app reports unavailable, without claiming confirmed physical power-off.
- [ ] M10: Restart agent; existing device recovers without losing identity.
- [ ] M11: Restart host; service starts automatically, boot ID rotates and uptime resets.
- [ ] M12: Reinstall/upgrade preserves UUID; no duplicate device or unexpectedly enabled power.
- [ ] M13: Uninstall removes service and application-owned firewall rule; state retained unless purge requested.
- [ ] M14: Diagnostics are readable and manually reviewed for identifiers before sharing.

## Optional power / wake (requires physical recovery)

- [ ] P01: Test machine only, saved work, correct NIC and appropriate wake firmware/Windows policy.
- [ ] P02: Enabling power creates private 64-hex key; not printed in report or logs.
- [ ] P03: SmartThings remains unable to run power without matching opt-in/key.
- [ ] P04: Reboot command results in fresh boot and agent/device recovery.
- [ ] P05: Suspend command enters actual hardware-supported sleep state.
- [ ] P06: Wake button resumes suspended machine; uptime/boot ID remain consistent with a resume.
- [ ] P07: Shutdown command eventually powers off computer (not merely agent process).
- [ ] P08: WOL starts the powered-off host, **if** firmware/NIC/OS state permits; otherwise mark N/A or FAIL with state details.
- [ ] P09: Rejected/invalid HMAC command never executes a power action.
- [ ] P10: Disabling opt-in removes `power_actions` and disables remote shutdown/reboot/suspend.
- [ ] P11: WOL/availability remains sensible under transient LAN/mDNS outage and hub reboot.

Include `powercfg /a` output **after redaction** on Windows, or Linux `ethtool` WOL support flags. Mark any untested condition explicitly. A CI cross-build is not an ARM64 hardware test; server CI is not a Windows 11 SmartThings hub test.
