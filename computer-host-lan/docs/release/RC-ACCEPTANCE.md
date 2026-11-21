# Computer Host LAN v1.0.0-rc.2 — one-round acceptance

**Version boundary and availability:** This checklist is for the **unpublished v1.0.0-rc.2 source candidate** (Linux/Edge **0.4.6-rc.2**, Windows **0.2.7-rc.2**, protocol v2). The published rc.1 package does not contain PRs #56–#59, including Windows ProgramData security, corrected power acknowledgments, the Public-network warning, and `beta-report.sh --port`. **Do not mark an rc.2 check PASS by testing rc.1.** Use one version-matched rc.2 package **only after** its tag and release have been explicitly approved and published; CI artifacts are not user distribution.

**Safety first:** Monitoring only on a fresh install. Do not remove valid ProgramData, rotate keys, re-pair devices or invoke shutdown/suspend without a planned physical recovery path. Avoid experimenting with rc.1 authenticated power commands on shared Windows computers with untrusted users (see [rc.1 security limitations](../../SECURITY.md#known-issues-in-the-published-rc1)). Record host OS/build, exact agent and Edge driver versions, and **PASS / FAIL / NOT TESTED / N/A** for each relevant check. Keep private credentials, MACs, addresses and UUIDs out of shared feedback.

| Check | Expected result |
| --- | --- |
| **Windows first launch** | Welcome page and **initial hub-search page** paint correctly at the tester's normal screen scaling (original rendering complaint). |
| **Windows Public profile** | Setup clearly explains its Private-only firewall restriction. A Public network may block hub access despite a successful localhost agent health check; no automatic Public rule or profile change is made. |
| **Windows state security** | On fresh install, state directory/token owner and allow ACEs are restricted to the intended administrators/SYSTEM and exact service SID. A deliberately prepared unsafe **test fixture** on a disposable Windows test PC is refused before its key can be adopted; no legitimate UUID or key is overwritten. Do not perform attacker-fixture tests on a machine holding real credentials. |
| **Windows Domain profile** | A DomainAuthenticated interface is also not covered by a Private-only firewall rule. Static Setup hint may not explicitly diagnose it. Report the actual profile and whether the hub can connect. |
| **Windows power acknowledgments** | Where safely tested: shutdown/reboot 202 follows native request acceptance; immediate native rejection maps to 409 (in-progress) or 503. Do not blindly repeat a request if its effect may already be pending. |
| **Hub discovery** | Detected hub is selectable; **Search again** works; if retry finds nothing, previous IP remains; manual IPv4 and Advanced options remain usable. |
| **Existing installation upgrade** | Run RC Setup directly over installed beta; retain UUID, control key, custom port/config, previous power setting and **the same SmartThings computer device**. Do not uninstall or reset first. |
| **Fresh installation** | Monitoring-only by default; Connect to SmartThings guide and Start Menu shortcut work; SmartThings scans and creates **one** correct computer device. |
| **Monitoring** | CPU, RAM (%, total, used, available), disk (%, total, used, available), uptime and status update plausibly without duplicated devices. |
| **Recovery** | Stop/restart agent service, then restart computer; existing device becomes reachable again. No manual re-pairing. |
| **Linux helper 202 semantics** | Confirm shutdown/reboot responses reach SmartThings before systemd stops the agent, then verify actual host state separately. Linux 202 acknowledges a delayed attempt, not systemd job acceptance; suspend errors should be reported when immediately detectable. |
| **Discovery and Wake regression** | A dropped device-creation request becomes retryable after the 120-second pending TTL without duplicate devices; a failed Wake restores the last confirmed On/Off state when one exists. If not safely reproducible on a real hub, mark NOT TESTED. |
| **Transport and slow headers** | Verify dropped-packet HTTP polling no longer behaves like the old 60-second LuaSocket timeout and that slow/incomplete Linux headers hit the cumulative deadline; do not run destructive saturation tests on a production host. |
| **Optional power** | Only when previously enabled and physically safe: Reboot, Suspend and Wake-on-LAN. Report unsupported power states as N/A, not as general failure. |
| **Soak** | Leave the installation running during normal use; report unexpected offline states, duplicate devices, missing updates, or service crashes with approximate time. |

**Linux redacted reporting:** `./scripts/beta-report.sh --port PORT` prints the local agent's stable/beta/RC version without exposing hostnames, UUIDs, addresses or keys; omit `--port` for TCP 8765. Verify repeated SmartThings scans do not duplicate pending devices and that a failed Wake retains the last known ON/OFF state.

**Linux (publisher):** upgrade Gentoo reference host with matching RC source; verify the same identity, service recovery, metrics, suspend/WOL and no unexpected changes to WOL settings. Other distributions require separate hardware evidence before they are claimed as certified.

**rc.2 acceptance notes:** The fixed Public-network hint may appear below extra blank space with Advanced options collapsed; this is a cosmetic issue to judge at normal screen scaling, not proof of a broken firewall. The PowerShell installer's live Public-profile warning is not shown inside the hidden Inno child process, so the GUI provides a static explanation. The deferred Linux per-address connection cap (#31) remains an open follow-up; the current absolute header deadline bounds each slow request, not every possible LAN abuse pattern.

**If something fails:** Stop at the failing step, keep the previous installer and any protected rollback snapshot, and share a brief **redacted** description. Do not delete ProgramData or the SmartThings device to make a retry work.
