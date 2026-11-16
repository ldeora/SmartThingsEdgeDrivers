# Linux feature-parity gate — v0.3.1-beta.1 → v0.4.0-dev.1

**Status: NOT PASSED on real hardware.** The initial baseline was verified on
Gentoo `hydra` with systemd, an Ethernet NIC and SmartThings hub. The new v2
refactor has only been exercised with source-level tests, real Lua VM mocks,
Linux loopback HTTP, and installer preview. Nothing here is evidence of an
actual successful SmartThings pairing or shutdown/WOL cycle under v2.

## Acceptance rule

The updated Linux agent/driver must preserve every feature and operational
property of the verified baseline. UI labels and device IDs may change, but
**functional behavior must not regress**. No public beta or Windows-agent
integration work is considered complete before this gate is documented.

### Gate 0 — source checks (automatable)

| ID | Requirement | Status / test |
|---|---|---|
| A01 | Original `v0.3.1-beta.1` retained as rollback reference | Original archive outside candidate; verify manually |
| A02 | Python agent unit/security tests | `python3 -m unittest discover -s tests -q`: passing locally |
| A03 | Linux HTTP loopback v2 (`info`,`health`,`metrics`) | `python3 scripts/ci/smoke_agent.py`: passing locally |
| A04 | Signature vectors and nonce replay defense | `test_lua_crypto.py`, `test_agent.py`, `test_security_v030.py`: passing locally |
| A05 | Live Lua parser, driver/state/telemetry tests | `test_lua_*`: passing locally (Lua lib available) |
| A06 | Linux state transitions preserved, threshold/inference behavior | `test_lua_driver.py`, `test_lua_state.py`: passing locally |
| A07 | DNS-SD service and JSON v2 agree | `test_generic_contract.py`: passing locally |
| A08 | Linux and Windows device profile selection | `test_generic_contract.py`: passing with mocked discovery |
| A09 | installer dry-run and systemd unit structural validation | Passing locally; **not** real PID1 installation |
| A10 | No secret/identity leak in bundled test fixtures | existing source checks; review reports before sharing |

These results do not prove hub-side capability registration or real network
behaviors.

### Gate 1 — SmartThings presentation and discovery (requires hub + hydra)

| ID | Action | Acceptance evidence |
|---|---|---|
| H01 | Register five new generic capability IDs; reuse existing Linux load | Registration and presentation successful; no unrelated capability changes |
| H02 | Install generic `computer-host-lan` Edge Driver | Driver installed in desired channel/hub; loads cleanly |
| H03 | Install v2 Linux agent in **monitoring-only** mode | systemd service active; old v1 routes no longer used |
| H04 | Check `_computerhost._tcp` advertisement | `avahi-browse -rt _computerhost._tcp` shows host and port |
| H05 | SmartThings discovery creates one Linux computer | Correct label, profile, UUID, no duplicates |
| H06 | Refresh and health polling | Switch ON only when matching `/v2/health` response received |
| H07 | Custom status and all telemetry capabilities | New capability IDs emit: CPU %, RAM %, RAM GiB, disk %, uptime; Linux load 1/5/15; temp (if sensor present) |
| H08 | German/English presentations | Expected labels, values and units in app; no missing cards |
| H09 | Temperature and CPU metrics updates | Polling correct and no excess event-history noise |
| H10 | Stability and responsiveness | Poll/recovery intervals at least as good as baseline; no duplicate timers |

### Gate 2 — failure handling / identity (requires hub + hydra)

| ID | Action | Expected behavior |
|---|---|---|
| H11 | Stop only the unprivileged agent service | SmartThings remains online; computer eventually `unreachable` rather than incorrectly `stopped` |
| H12 | Restart agent service | Host returns to `running`, switch ON without device recreation |
| H13 | Temporarily block TCP 8765 | Timeout handling and `assumeOffWhenUnreachable` behave exactly as documented |
| H14 | Simulate/refuse TCP connections | Connection refused must not prove shutdown or sleep; switch handling remains conservative |
| H15 | Restart Avahi or change DHCP address | Rediscovery works with stable UUID; WOL metadata remains associated only with matching UUID |
| H16 | Point agent address at another valid installation UUID | Wrong host must never be accepted or supply WOL MAC |
| H17 | Hub/driver restart while Linux is running | First state events republished; no duplicated devices or lost metrics |
| H18 | Hub restart while Linux is off | Controller remains online; stored WOL MAC/broadcast permit wake |

### Gate 3 — power and wake (opt-in, real hardware)

*Do not run until monitoring-only behavior passes. Save work and retain local
physical recovery access. Configure persistent NIC WOL separately.*

| ID | Action | Expected behavior |
|---|---|---|
| H19 | Attempt power actions before opt-in | Rejected, with no privileged helper unexpectedly enabled |
| H20 | Enable helper and configure key privately | Authenticated reboot/suspend/shutdown requests can reach helper; unauthenticated cannot |
| H21 | Trigger Reboot | `rebooting` while pending, then `running` with changed boot ID, main Switch ON |
| H22 | Trigger Suspend | `suspending`, then `suspended` only after sufficient silent failures |
| H23 | Wake after suspend with Switch ON/Wake control | WOL packet sent and agent comes back, Switch ON; no premature running claim |
| H24 | Trigger Switch OFF | `stopping`, then inferred `stopped` after repeated timeouts; Switch OFF |
| H25 | Switch ON after full soft-off | Stored MAC and broadcast permit WOL; machine returns to `running` |
| H26 | Agent power helper unavailable / invalid key | Safe error, no optimistic OFF and no command execution |
| H27 | Shutdown accepted but connectivity returns quickly | State reconciled from actual health rather than command acknowledgement alone |
| H28 | Force network failure during pending action | Wrong/unknown failures must not count as proof of completed shutdown/suspend |

### Gate 4 — Linux maintenance and rollback

| ID | Action | Expected behavior |
|---|---|---|
| H29 | Reinstall identical v2 agent | Identity and control token preserved; only one unit active |
| H30 | Reinstall with power enabled and WOL selected | Power/WOL settings preserved unless explicitly disabled; no firewall or network edits |
| H31 | Test manual rollback to v0.3.1 | Installer files restored from original snapshot and **matching old Edge Driver** restored; no protocol mismatch |
| H32 | Uninstall dry-run / explicit uninstall | Only application-owned files removed; secrets/identity kept as documented |
| H33 | Extended unattended run | No excessive CPU/memory load, unbounded logs, misclassified availability, or missed scheduled recovery |

## Record results before merging or publishing

Record OS/systemd/Python/driver versions, SmartThings hub model/firmware,
installation ID only if appropriately redacted, date/time, expected/actual
result, and minimal sanitized hub/agent logs for failures. Do not include key,
nonces, HMAC headers, serials, local IPs, raw UUIDs, or MAC addresses in
public reports.

**Go/no-go:** `A01–A10` and `H01–H33` must be individually marked PASS, or
an explicitly documented non-applicable condition justified. Any regression
in the existing Linux power-state machine blocks this release.
