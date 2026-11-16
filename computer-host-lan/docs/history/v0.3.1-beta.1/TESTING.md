# Linux Host LAN v0.2.10 — Test checklist

## Static tests (run before hub testing)

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q agent tests
```

Automated coverage: identity/token persistence, file mode enforcement,
Linux metrics parsers, HTTP v1 endpoints, HMAC protocol and replay rejection,
wrong/disabled power actions, disconnected power helper, root helper action
allowlist, actual Lua SHA-256/HMAC test vectors, WOL payload generation,
Lua parser checks, profile JSON/YAML syntax, standard capabilities and unit
configuration. Tests do **not** prove the SmartThings hub/API runtime or
systemd power transitions work on real hardware.

## Staged field testing (do in this order)

1. **Agent read-only smoke test:** `curl` info/health/metrics, verify stable
   UUID across reboot/reinstall; inspect CPU temperature accuracy, memory,
   root FS usage and WOL MAC/broadcast. Check agent logs.
2. **mDNS:** `avahi-browse -rt _linuxhost._tcp`, then start SmartThings scan,
   check unique device creation, no duplicates on repeated scans.
3. **Switch/Refresh:** verify running host reports `switch.on`, Refresh and
   temp updates; make sure no `presenceSensor` is exposed.
4. **Network resilience:** stop agent (not system), wait for threshold;
   observe `Connection refused` and ensure the switch stays ON; the LAN
   controller and Wake button remain available. Restart agent and verify
   connection-restored log and telemetry. Test a firewall DROP/timeout
   separately: after three consecutive host-unreachable polls switch
   reports OFF by default; restore network and verify it goes ON.
5. **DHCP change:** renew address / change IP; check automatic rediscovery and
   existing DNI rather than a duplicate device. Test manual host override.
6. **WOL:** enable NIC WOL, turn computer off *locally*, verify the switch
   transitions OFF after the host stops responding, then toggle main switch ON.
   Confirm the machine wakes and the switch reports ON only after the agent
   responds. Test suspend and separate Wake button too.
7. **Power commands:** first test intentionally with invalid key, disabled
   toggle and helper stopped: switch OFF must not claim success. Then test
   with a valid key and no unsaved work. Switch OFF must trigger shutdown and
   switch state should become OFF only after failed health checks. Reboot
   should retain ON during a temporary outage; suspend should become OFF
   and the main switch ON must WOL the machine again.
8. **Fault injection:** firewall drop, wrong IP, reused IP/other host UUID,
   mDNS off, wrong MAC, wrong broadcast, WOL UDP blocked, agent timeout.
9. **Multi-host:** two Linux machines on same subnet, different stable UUIDs,
   distinct MACs and independent SmartThings events.
10. **Hub restart/driver reinstall:** confirm persisted address and WOL
    metadata survive, poll resumes, profile migration from v0.1.0 is handled.
11. **Enhanced telemetry (v0.2.7):** register all six custom capabilities and
    presentations, install the advanced profile, and verify CPU %, memory %,
    installed RAM, root filesystem %, uptime text/minutes, all three load
    averages, and host status. Check current state and event-history visibility
    on Android/iOS; verify existing device migration without re-pairing.
12. **Release gate:** test different hub generations/firmware, distributions,
    IPv4 topology variants, permissions/systemd variants, resource usage and
    command security against malicious LAN input.

## Useful commands

```sh
journalctl -u linux-host-agent.service -n 100 --no-pager
journalctl -u linux-host-agent-power.service -n 100 --no-pager
systemctl status linux-host-agent-power.socket
smartthings edge:drivers:logcat
ethtool <interface> | grep Wake-on
```

Do not automate shutdown of workstations until all staged tests have passed.

## Regression checks added in v0.2.3

- On an existing installation, refresh or let health poll once; there should be no `tonumber` exception at `init.lua:109`, and the success counter should initialize correctly.
- Simulated Edge `get_field` returns zero values for an unset field; the driver must not interpret this as a failed health check. Internal Lua polling exceptions should be logged separately from HTTP failures.
- With Avahi advertising both IPv4 and IPv6 addresses, discovery should contact the IPv4 endpoint and should not try an unresolved `examplehost-2.local` hostname from the IPv6-only record.
- Verify that device UUID, profile and preferences remain unchanged after installing v0.2.3. The agent need not be reinstalled.

## Switch state regression checks added in v0.2.4

- Stop only `linux-host-agent.service`: HTTP `Connection refused` should keep
  Switch ON after the failure threshold and recovery should be logged.
- From an external shutdown or deep suspend, check that repeated TCP timeouts
  result in Switch OFF (default preference) even without a SmartThings command.
- Toggle Switch ON: a magic packet is sent; ON state should appear **only**
  once `/v1/health` works following boot/resume.
- Toggle Switch OFF with authenticated control: shutdown is requested, OFF
  reported after repeated failed polls; rejected commands must not claim OFF.
- Reboot using the momentary control: the main switch stays ON during the
  transient loss of health, then confirms recovery by the changed boot ID.
- Disable `Switch off when host unreachable`: unexpected TCP timeouts should
  retain the last confirmed state, but explicitly requested shutdown/suspend
  must still report OFF.
- Restart the Edge Driver while the target is OFF and again while it is ON;
  the first inferred/confirmed state must be emitted even if cached locally.
- Test Wi-Fi, proxy, firewalled hosts separately: `Connection refused` and
  timeout are only networking evidence, not guaranteed electrical states.

## WOL metadata recovery (v0.2.5+)

- When the agent is online, confirm `/v1/info` includes a valid `wol_mac` and `wol_broadcast`. Refresh the SmartThings device, then press **Wake**: the hub should log `Linux Host magic packet sent` rather than `missing or invalid unicast Ethernet MAC`.
- A newly created or upgraded device with no saved WOL metadata automatically fetches and stores it from `/v1/info`; verify `WOL MAC saved for ...` appears when metadata is first acquired.
- After that first successful acquisition, stop the agent and press **Wake**: WOL must work using the persisted MAC without an HTTP response. Stop the agent *only*; this test does not require suspending or shutting down Linux.
- If the agent is powered off before the metadata was saved, enter **WOL MAC override** (and subnet broadcast if needed) in the current device's Settings. The Edge driver cannot learn an unknown MAC from a powered-off computer.
- Verify that an address returning a different installation UUID is rejected; the driver must not store a MAC from another host.
- A SmartThings CLI `Command executed successfully` message confirms command acceptance, not that the Edge driver executed its action. Check logcat for `received command` and the subsequent action result.
- If the mobile app reports a network error but CLI commands reach the driver, investigate the current SmartThings device ID and app/presentation independently. Do not delete/recreate the device just to reset the app.

## Agent v0.2.2 network-interface recovery (regression)

1. Install/upgrade on an already networked host: `sudo ./scripts/install-agent.sh --enable-power --wol-interface enp3s0` (substitute a WOL-capable physical NIC).
2. Run `curl -fsS http://127.0.0.1:8765/v1/info | python3 -m json.tool`. Verify `wol_mac`, `wol_broadcast`, and `wol_interface` are populated and match the intended NIC.
3. On a test installation **without** an explicit interface pin, confirm that the agent can start before an IPv4 route is ready and that `/v1/info` recovers on a subsequent request after the route is available. Do not disrupt networking on a production system merely to simulate this test.
4. Verify the SmartThings hub logs a one-time `Linux Host WOL MAC saved` entry if metadata was missing, then sends a valid WOL packet after the computer is shut down.
5. Verify the configured control key and power-actions capability survive the agent update unchanged.

The hub-based WOL recovery path and actual wake-up after this update have not yet been re-tested. The 27 tests cover local code and mocks, not a live SmartThings hub.


## v0.2.8 custom telemetry emission regression

- Confirm that registered custom capability attributes are represented by
  callable Lua tables. The driver must invoke them without requiring
  `type(attribute) == "function"`.
- After installing v0.2.8, the device's six custom capabilities must receive
  non-empty states, not only appear as empty attributes.
- If a custom attribute is temporarily unavailable, retry sending unchanged
  readings when it becomes available (e.g. installed RAM).
- Confirm the main Switch and all power actions still work as before.
- The previously registered capability IDs and presentations must not be
  recreated or modified for this hotfix. Agent v0.2.2 remains installed.

## v0.2.9 proposed real-hardware matrix

1. Running host: CPU temperature, CPU %, RAM %, filesystem, load 1/5/15,
   numeric uptime and compact readable uptime continue to update.
2. Stop agent (leave Linux online): TCP connection refusal leads to
   `linuxHostStatus=unreachable`, but main Switch remains ON.
3. Block communication or disconnect network: repeated silent timeouts lead
   to `linuxHostStatus=unreachable`; main Switch OFF is *optional/inferred*.
4. Authenticated shutdown: a transient refusal should retain `stopping`;
   repeated silent timeouts result in `stopped` and main Switch OFF.
5. From OFF, WOL boots the computer; health confirms `running`, Switch ON.
6. Suspend: expected `suspending` → inferred `suspended` → WOL → `running`.
7. Reboot: keep Switch ON, `rebooting` until a different kernel boot ID is
   observed; verify hub-driver restart during the transition.
8. Wrong installation ID/protocol failure: `unknown`, no invented OFF state.
9. Disable remote power in device settings: shutdown is rejected; status and
   switch are restored and key is never logged.
10. Run `./scripts/diagnose.sh --interface IFNAME` and review for secrets.
11. Run WOL dry-run on systemd-networkd and NetworkManager hosts, then
    explicit opt-in and reboot verification. Do NOT assume that a live
    `ethtool -s` alone makes WOL persistent.
12. Publish presentation/translation files on a test account or after backup;
    confirm `en` and `de`, short load labels, and mobile app behavior.

**Live Gentoo field result (15 November 2026):** the v0.2.9 driver passed
agent stop/recovery, reboot, suspend/WOL and graceful shutdown/WOL. The app
reported the expected Running/Unreachable/Stopped/Suspended statuses and the
Switch followed power transitions. Multi-distribution testing remains OPEN.

## v0.2.10 WOL query regression

- Run `./scripts/diagnose.sh --interface IFNAME` as a nonroot user: it must
  show actual `Supports Wake-on:` / `Wake-on:` lines or an actionable
  "unavailable" message; it must never print an empty heading or a false
  "unsupported" assertion on permission errors.
- Run `./scripts/configure-wol.sh --interface IFNAME` (no `--apply`): with
  a netlink access error it should fall back to legacy ioctl; if neither
  backend can query, it must describe an access/unknown status.
- Compare against `sudo ethtool IFNAME | grep -i 'Wake-on'` for the same NIC.
- Run `python3 -m unittest discover -s tests -q` (37 tests); the 5 new mock
  cases simulate netlink EPERM, successful ioctl fallback, both backends
  inaccessible, and hardware that genuinely lacks WOL support.
- Do not reconfigure a functioning `.link` file during troubleshooting.
