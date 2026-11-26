# Edge HTTP deadline — pre-merge hub qualification (#177)

**Scoped physical-hub transport and OFF acknowledgement checks passed.**
Independent review on 2026-11-26 recommends merge after recording hub
model/firmware and approving the revised gate below. Explicit maintainer
approval of this disposition is required before merge. Green upstream cosock
CI alone is not proof of hub runtime compatibility. Repeat affected checks
if production code changes. Do not publish to the public driver channel.

## Qualification evidence and revised gate (2026-11-26)

Reviewed source: `1ec661cacdce1a3c25c8cd29eb8985027aa065a1`.
Production API blob: `84d6129c341097073ff07af3b8f94c7620a7b142`.
All three PR workflows passed on this head, including mandatory native
upstream cosock/LuaSocket tests (8.000 s header, 8.000 s body, 4.002 s
inactivity; native descriptor and peer closure).
Isolated monitoring driver version: `2026-11-25T19:53:07.490582168`.
Hub model and firmware: **NOT RECORDED — required before merge**.

| Physical-hub observation | Result |
| --- | --- |
| Slow header | PASS: 8 peer closures, 7.978–7.992 s |
| Slow body | PASS: 2 peer closures, 7.987–8.007 s |
| Stalled body | PASS: 4 peer closures, 4.013–4.019 s |
| Connection cleanup | PASS: all 14 client closures, no fixture 12 s cutoff |
| Failure classification and recovery | PASS: host_unreachable, third failure unreachable/OFF; recovered after 9, 5 and 3 failures |
| Rediscovery | PASS for isolated pinned endpoint only; NOT TESTED for mDNS, DHCP migration or competing UUID (#124) |
| Queued OFF | PASS at driver level: refusal and known-state reassertion; app toast observed |
| Compatibility fallback | None observed in supplied excerpts; other firmware not qualified |

Authenticated synthetic A/B: same isolated driver identity, device, channel,
hub and endpoint, with no real power actions or WOL. Baseline post-#64
`849bd70d524fa14e1de8c2da82f0b4efe6b7f59b`, API blob
`2c5fa2f07eedf68961dd7f3ea88925e0e6eaa1a2`, installed version
`2026-11-25T23:44:07.286305377`; candidate installed version
`2026-11-26T00:17:31.752942027`, candidate ZIP API blob verified as above.
Both completed valid signed challenge/POST exchanges: deliberate 403
restored ON and produced the same generic app toast; accepted 202 caused
OFF/stopping without toast, then running/ON because the fixture stayed
reachable. Candidate redacted 403 diagnostic verified. Candidate 202
and app outcome were reported by the maintainer; command/recovery events
were absent from the excerpt, so exact candidate timings remain NOT TESTED.
This compares relevant intervening changes, not a one-variable source diff
or unmodified production package. Rejection toast was disclosed in #63;
do not emit false OFF. Exact app acknowledgement mechanism unverified.

Evidence: [native CI](https://github.com/ldeora/SmartThingsEdgeDrivers/actions/runs/45668057105),
[hub results](https://github.com/ldeora/SmartThingsEdgeDrivers/pull/177#issuecomment-7176280442),
[A/B results](https://github.com/ldeora/SmartThingsEdgeDrivers/pull/177#issuecomment-7178862021).
Maintainer reports days of normal production use without a toast; that
installation was not modified and is not exact-candidate soak evidence.

### Revised gate (independent recommendation; maintainer approval required)

Before merge: scoped actual-hub deadline, cleanup, recovery and OFF A/B as
above, no observed compatibility fallback, hub model/firmware recorded,
explicit maintainer approval of deferral, and green final-head CI.
Extended mixed-mode sessions and direct closure evidence support deferral
but do not prove uninterrupted normal operation or absence of all leaks.

Transfer the following **NOT TESTED** items to exact-candidate rc.3 acceptance:
one uninterrupted hour of normal health, metrics, refresh and availability
(may be recorded as an interval within the seven-day soak); full accepted
command timing; ordinary ON while running; authorized physical shutdown,
reboot, suspend and Wake; slow accepted challenge/POST on a disposable
fixture; unmodified package and upgrade acceptance. Retain the seven-day
Windows/Linux soak and all stable gates.

One slow poll plus challenge plus POST can consume about 24 s of cooperative
request budgets; additional queued or synchronous work may add latency.
Even an accepted command may exceed the observed roughly 18–20 s app toast
window. No guaranteed app timeout or automatic retry of an uncertain POST.
Document rejected-power diagnostics under #130; do not change Host Status
or invent false acknowledgement events. No deployment authorized.

## Setup and evidence

- Use an isolated development channel and a designated test hub, preferably
  the existing Gentoo test setup. Preserve the current working driver and
  record its installed version. Do not enroll other users or move the public
  channel to the test build. If isolation cannot be guaranteed, stop.
- Record PR commit, packaged driver ID/version, hub firmware, test host/agent
  version, start/end timestamps. Run the CLI driver log stream with secrets
  excluded from captured evidence. Never include control keys, nonce/signature
  headers or private installation IDs in shared logs.
- During exact-candidate rc.3 acceptance, observe at least one uninterrupted
  hour of normal health polling, metrics, refresh and availability. Test
  ordinary ON while running and authorized, safe power transitions; record
  requested switch state, Host Status, physical outcome and acknowledgement
  delay. No unexpected compatibility-fallback or transport-exception log.
- Use a separate disposable monitoring-only device and listener for the
  slow-response checks. Never redirect a real configured power-enabled
  device or copy its key. Scope the listener to a private test LAN and the
  hub address; do not open a public interface/firewall rule. See the
  companion `scripts/ci/hub_http_probe.py` for a test listener. No real
  power command is implemented by the listener.

## Starting the disposable listener

From the PR checkout, under an ordinary unprivileged account, substitute the
actual private IPv4 address of the test computer and test hub. Use an unused
port (the example uses 18765, not the real agent's 8765). Run:

```sh
mode_file=$(mktemp)
printf 'Mode file: %s\n' "$mode_file"
printf '%s\n' normal > "$mode_file"
python3 computer-host-lan/scripts/ci/hub_http_probe.py \
  --bind <TEST_COMPUTER_IPV4> --allow-peer <TEST_HUB_IPV4> \
  --port 18765 --mode-file "$mode_file"
```

Keep that terminal open. The fixture generates a separate UUID and boot ID;
it never reads host state or credentials. In another terminal advertise
the test-only service using Avahi, if available:

```sh
avahi-publish-service "Computer Host HTTP Deadline Probe" _computerhost._tcp 18765
```

Discover the fixture on the isolated test hub while the mode is normal.
Do not set a control key, enable power commands or set a WOL MAC override.
The listener accepts only the specified hub IPv4; no firewall rules are
changed by the script. If discovery cannot reach the bound address, check
the test network rather than broadening access. Use the full path printed
by `echo "$mode_file"` (from the original shell before starting Python)
to change modes from a second shell:

```sh
printf '%s\n' drip-header > /path/to/mode-file
printf '%s\n' drip-body > /path/to/mode-file
printf '%s\n' stall-body > /path/to/mode-file
printf '%s\n' normal > /path/to/mode-file
```

Select one mode at a time; new health requests read it. Info/metrics remain
normal. The probe prints peer closure/reset time; its own 12-second cutoff
is not evidence of a client deadline. Stop both processes, remove the
disposable device and delete the mode file after testing.

## Slow-response checks

1. Establish normal health and metrics with a distinct test installation.
2. Select the slow-header mode. Trigger refresh and observe the request's
   deadline, not the whole refresh duration. The listener sends bytes well
   inside the four-second inactivity limit. Expect a deadline timeout at
   about eight seconds (allow normal scheduler/log delivery jitter), a closed
   connection and exactly one ordinary health failure per failed health poll.
3. Repeat with a drip-fed response body and a stalled response body. The
   stalled body should hit the original four-second inactivity limit.
4. While a health request is pending, queue an OFF command on the
   monitoring-only device. No power action can be sent to a real host.
   After the poll returns, record whether the switch reasserts its last
   known state, how long the app waits, and whether a command-error toast
   appears. Check the configured failure threshold, then return the listener
   to normal mode. Expect running status and metrics recovery without
   recreating the device.
5. During rc.3 acceptance, record elapsed timings for a normal authenticated
   command on the safe real host separately; test slow accepted challenge or
   POST on a disposable fixture. In the pathological case challenge and POST each
   have an independent eight-second budget (about 16 seconds combined);
   work already queued ahead of the command can add latency. Do not assume
   a guaranteed SmartThings app acknowledgement window. Never retry a
   possibly accepted POST merely because of a timeout.

## Decision

Apply the revised pre-merge gate above only with explicit maintainer approval.
A fallback is an explicit compatibility warning, not a PASS. Investigate new
failures or unexpected app errors before merging; the reproduced rejection
toast is an existing limitation, not a transport regression. Record unavailable
tests as NOT TESTED, not PASS; rc.3 acceptance must include the deferred checks.

After testing, remove the disposable device/listener and restore normal
development-channel configuration. Do not modify published rc.2 artifacts.
