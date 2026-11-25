# Edge HTTP deadline — pre-merge hub qualification (#177)

**Not yet tested.** A green upstream cosock test is not proof of compatibility
with the hub's bundled LuaSocket/cosock. Do not merge #177 until the following
checks pass on the exact reviewed head; repeat affected checks if production
code changes. Do not publish to the public driver channel.

## Setup and evidence

- Use an isolated development channel and a designated test hub, preferably
  the existing Gentoo test setup. Preserve the current working driver and
  record its installed version. Do not enroll other users or move the public
  channel to the test build. If isolation cannot be guaranteed, stop.
- Record PR commit, packaged driver ID/version, hub firmware, test host/agent
  version, start/end timestamps. Run the CLI driver log stream with secrets
  excluded from captured evidence. Never include control keys, nonce/signature
  headers or private installation IDs in shared logs.
- For an hour, observe normal health polling, metrics, refresh and device
  availability. Test ordinary ON while running and a safe, planned power
  transition on an authorized test host with no unsaved work. Record the
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
5. Record elapsed timings for a normal authenticated command on the safe
   real host separately. In the pathological case challenge and POST each
   have an independent eight-second budget (about 16 seconds combined);
   work already queued ahead of the command can add latency. Do not assume
   a guaranteed SmartThings app acknowledgement window. Never retry a
   possibly accepted POST merely because of a timeout.

## Decision

PASS requires normal operation, actual deadline enforcement, socket cleanup,
recovery, correct state/acknowledgement behavior and no compatibility-fallback
diagnostic. A fallback is an explicit compatibility warning, not a PASS.
If a test fails or app errors occur, capture redacted observations, stop
qualification, restore the previous working driver and investigate before
merging. Record any unavailable test as NOT TESTED, not PASS.

After testing, remove the disposable device/listener and restore normal
development-channel configuration. Do not modify published rc.2 artifacts.
