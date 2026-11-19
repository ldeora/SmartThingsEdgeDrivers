# Computer Host LAN — hardware beta test checklist

**Record:** OS + version/build, architecture (x64/ARM64), host agent version, Computer Host LAN driver version, hub model/firmware, wired/wireless interface class and whether WOL is expected. Use **PASS / FAIL / N/A / NOT TESTED** for each. Never include the control token, personal hostname, internal IPv4/MAC, hub location or unredacted device IDs.

## Monitoring / discovery (all testers)

- [ ] M01: Downloaded the matching versioned package; verified SHA-256 / package integrity.
- [ ] M02: On Windows, used recommended graphical Setup.exe (or noted the PowerShell fallback); installed monitoring **without** power opt-in.
- [ ] M03: Service runs as restricted principal (`linuxhost` on Linux; `LocalService` on Windows).
- [ ] M04: `/v2/info` reports correct `platform`, protocol v2, power actions empty by default.
- [ ] M05: `/v2/health` and `/v2/metrics` provide non-fabricated values.
- [ ] M06: Computer is discovered through `_computerhost._tcp` by the hub on a trusted LAN.
- [ ] M07: SmartThings device is unique, correct Linux/Windows profile, usable app presentation.
- [ ] M08: CPU, RAM, disk, uptime, status and switch update; missing optional sensors do not break other metrics.
- [ ] M08a: New `/v2/metrics` includes a positive `disk_root_total_bytes`, and SmartThings shows a plausible `diskTotalGiB` for that exact root/system volume; record if a hub restart was needed.
- [ ] M08c: On RAM **and** root/system filesystem cards, confirm Usage %, Total GiB, Used GiB and Available GiB. Check raw `memory_used_bytes`, `memory_available_bytes`, `disk_root_used_bytes`, `disk_root_available_bytes` against OS readings. Used + Available need not equal Total on reserved-block/quota-restricted filesystems; do not treat that as an automatic failure. Record localized label/layout issues.
- [ ] M08b: In-place upgrade retains the same SmartThings device, agent installation ID and control key; Linux preserves power opt-in, the graphical Windows Setup preserves power opt-in; ZIP/PowerShell upgrades require explicit `-EnablePower`.
- [ ] M09: Stop only agent; app reports unavailable, without claiming confirmed physical power-off.
- [ ] M10: Restart agent; existing device recovers without losing identity.
- [ ] M11: Restart host; service starts automatically, boot ID rotates and uptime resets.
- [ ] M12: Reinstall/upgrade preserves UUID; no duplicate device or unexpectedly enabled power.
- [ ] M13: Uninstall removes service and application-owned firewall rule; state retained unless purge requested.
- [ ] M14: Diagnostics are readable and manually reviewed for identifiers before sharing.

## Windows guided Setup.exe beta test cases (Windows 11 x64)

- [ ] W01: Welcome screen visibly renders; all Next/Back/Cancel buttons and hub address input are accessible at the current Windows display scaling.
- [ ] W02: Hub discovery finds the expected real SmartThings hub (none/one/multiple); select it, retry, and test manual IPv4 entry if needed. Do not publish exact addresses.
- [ ] W03: Advanced options and explicit local-network firewall fallback are visible and have expected Private LocalSubnet scope; record limitations when mDNS is blocked.
- [ ] W04: Fresh installation starts monitoring only; Connect to SmartThings guide and Start Menu shortcut work and the hub can pair the agent.
- [ ] W05: Enable power only after monitoring, and verify masked key Show/Hide and Copy functionality; never include key in the feedback.
- [ ] W06: Migrate a prior Windows ZIP/PowerShell installation via Setup without uninstalling; verify same UUID, token, custom settings and power preference.
- [ ] W07: Re-run Setup as an upgrade; check identity/key and power remain unchanged; no duplicate SmartThings devices.
- [ ] W08: Uninstall using Installed apps; verify service/firewall removal and retained ProgramData; reinstall and ensure same UUID. Do not purge state as part of this test.
- [ ] W09: If graphical Setup fails, use the ZIP and PowerShell fallback, and record which step failed. For PowerShell upgrades, pass `-EnablePower` explicitly to retain remote actions.

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
