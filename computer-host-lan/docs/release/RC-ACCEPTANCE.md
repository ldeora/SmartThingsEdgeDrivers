# Computer Host LAN v1.0.0-rc.1 — one-round acceptance

Use **one published RC package** when available, not temporary PR artifacts. Preserve existing SmartThings devices and host identity. Record OS/build, agent version, hub/Edge driver version, and **PASS / FAIL / NOT TESTED** for the cases below. Do not share credentials, IPs, MACs or installation IDs.

| Check | Expected result |
| --- | --- |
| **Windows first launch** | Welcome page and **initial hub-search page** paint correctly at the tester's normal screen scaling (original rendering complaint). |
| **Windows Public profile** | Setup clearly explains its Private-only firewall restriction. A Public network may block hub access despite a successful localhost agent health check; no automatic Public rule or profile change is made. |
| **Hub discovery** | Detected hub is selectable; **Search again** works; if retry finds nothing, previous IP remains; manual IPv4 and Advanced options remain usable. |
| **Existing installation upgrade** | Run RC Setup directly over installed beta; retain UUID, control key, custom port/config, previous power setting and **the same SmartThings computer device**. Do not uninstall or reset first. |
| **Fresh installation** | Monitoring-only by default; Connect to SmartThings guide and Start Menu shortcut work; SmartThings scans and creates **one** correct computer device. |
| **Monitoring** | CPU, RAM (%, total, used, available), disk (%, total, used, available), uptime and status update plausibly without duplicated devices. |
| **Recovery** | Stop/restart agent service, then restart computer; existing device becomes reachable again. No manual re-pairing. |
| **Optional power** | Only when previously enabled and physically safe: Reboot, Suspend and Wake-on-LAN. Report unsupported power states as N/A, not as general failure. |
| **Soak** | Leave the installation running during normal use; report unexpected offline states, duplicate devices, missing updates, or service crashes with approximate time. |

**Linux redacted reporting:** `./scripts/beta-report.sh --port PORT` prints the local agent's stable/beta/RC version without exposing hostnames, UUIDs, addresses or keys; omit `--port` for TCP 8765. Verify repeated SmartThings scans do not duplicate pending devices and that a failed Wake retains the last known ON/OFF state.

**Linux (publisher):** upgrade Gentoo reference host with matching RC source; verify the same identity, service recovery, metrics, suspend/WOL and no unexpected changes to WOL settings. Other distributions require separate hardware evidence before they are claimed as certified.

**If something fails:** Stop at the failing step, keep the previous installer and any protected rollback snapshot, and share a brief **redacted** description. Do not delete ProgramData or the SmartThings device to make a retry work.
