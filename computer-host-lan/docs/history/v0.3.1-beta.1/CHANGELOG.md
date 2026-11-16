# Changes in Linux Host LAN v0.3.0 — security and installer preview

- Agent upgraded from v0.2.2 to **v0.3.0**, preserving API v1 and HMAC wire format.
- Added bounded HTTP concurrency (12), per-connection timeouts (4s), 429
  challenge throttling (20/min/IP, 120/min global), and full nonce cache
  rejection without wiping valid challenges. Wrong HMAC no longer consumes a nonce.
- Added 3-second helper socket read timeout and sanitized service errors.
- Applied additional systemd resource limits and sandbox hardening.
- Introduced transactional installer (atomic managed-file updates, root-only
  recovery snapshots, error rollback), rootless dry-run, rollback and explicit
  uninstall scripts. Existing UUID/key and WOL rules are preserved.
- Added 30 new unit/integration tests, loopback-only HTTP adversarial tests,
  CI templates and guides for installation, security and validation.
- **SmartThings Edge Driver v0.2.9 unchanged.** No new capabilities/profile
  registrations or device recreation. Non-Gentoo integration certification OPEN.

---

# Changelog

## 0.2.11 — release engineering (source + installer only)

- Added read-only distribution preflight and Python >=3.10 interpreter
  selection, including alternative installed interpreter detection and an
  explicit `--python` override. Default system Python is never modified.
- Sanitized real host-specific names, addresses and MACs from examples and
  test fixtures; publisher namespace `oceancircle09600` intentionally retained.
- Added distribution matrix, DEB/RPM packaging decision proposal, candid
  security findings, beta test checklist and provenance notes.
- No agent API, helper, WOL implementation, SmartThings profile or state
  machine changes. Agent remains v0.2.2; Edge driver remains v0.2.9.
- Not validated on any distribution except the original Gentoo host; the
  revised installer tooling has only local automated checks.


## v0.2.10 — ethtool WOL diagnostic permission handling

- Corrected the WOL setup and diagnostic scripts for unprivileged Linux users: a WOL_GET netlink query can require CAP_NET_ADMIN and can fail even when the adapter fully supports Wake-on-LAN.
- Require actual `Supports Wake-on:` and `Wake-on:` data before interpreting an ethtool result, even if the process reports exit status zero; retry with `ethtool --disable-netlink` (legacy ioctl) when necessary.
- If both methods fail, print a permissions/capability diagnostic and suggested root verification rather than falsely concluding that WOL is unsupported.
- `--apply` now explicitly checks root access before attempting any modification. Dry-run and diagnostics remain read-only.
- Added five mocked regression tests; 37 local tests passed. No Edge Driver, agent, API, capability or service changes. Existing WOL configuration must not be replaced.


## 0.2.9 — state, installer and presentation beta preparation

- Dedicated pure Lua state reducer, with stronger evidence requirements for
  inferred `stopped` / `suspended`; unknown identity errors yield `unknown`.
- Pending action and Linux boot ID are now persisted across Edge driver restarts;
  pending actions expire after 180s with an explicit log warning.
- Deduplicated host-status events, reasserted after init; `running` confirmed
  only by matching agent health, and reboot confirmed by changed boot ID.
- Human-readable uptime: e.g. `45m`, `2h 15m`, `2d 4h`.
- Short load-average column labels and capability localization (`en`/`de`),
  with manual/opt-in account-wide presentation publication.
- Opt-in systemd-networkd/udev `.link` or NetworkManager WOL configuration,
  Python-path-discovering installer, disabled-by-default privileged socket,
  read-only redacted diagnostic script and release checklist.
- No changes to Linux agent v0.2.2 or the six existing capability schemas.
- Confirmed locally via Python/Lua regressions and shell syntax only;
  real-hardware validation of this version remains pending.



## v0.2.8 — Custom telemetry event emission hotfix

- Fixed the custom-capability event constructor guard: Edge capability attributes are
  callable Lua tables, not just functions; v0.2.7 rejected valid attributes,
  leaving advanced profile telemetry values empty despite successful registration.
- Keep failed custom metric events eligible for retry on subsequent polls;
  especially important for constant values such as total installed RAM.
- Added Lua regression coverage using callable attribute tables and temporary
  attribute unavailability.
- No changes to capabilities, device profile names, device identifiers,
  power controls, authentication, WOL or Linux agent (still v0.2.2).
- Existing custom capabilities remain registered; do not recreate or re-pair
  the device. Package/install the new Edge driver only.

## v0.2.7 — Enhanced telemetry profile

- Added the advanced device profile with six custom monitoring capabilities.
- Exposed CPU utilization, memory utilization, installed RAM, root filesystem
  usage, uptime, and all 1/5/15-minute load averages; numeric metrics and host
  status are available as Automation conditions.
- Added human-readable uptime (`Xd HHh MMm`) while retaining numeric uptime
  minutes for automation use.
- Added capability-aware event emission through `supports_capability_by_id`.
- Marked high-frequency metric updates as not displayed in event history to
  reduce history noise while retaining the latest device states.
- Added in-place advanced-profile migration for existing LAN devices using
  `device:try_update_metadata`; no device deletion or re-pairing is required.
- Kept the known-working Linux Host Agent v0.2.2 and all switch/WOL/power
  behavior unchanged.
- Custom capabilities must be registered in the developer account before the
  advanced profile is packaged and installed.
- Added regression tests for multi-attribute telemetry, uptime formatting,
  capability visibility, and existing-device profile migration (28 tests total).

## 0.2.6 — Dynamic Linux agent WOL interface selection (agent v0.2.2; Edge v0.2.5)

- **Root cause:** agent v0.2.1 selected the default-route interface exactly once at daemon startup. With `After=network.target`, the route could be missing at that instant, so `/v1/info` permanently returned `null` for `wol_mac`, `wol_broadcast`, and `wol_interface` even once network connectivity became normal.
- Agent v0.2.2 chooses its automatic WOL interface on **each** `/v1/info` request. It prefers the lowest-metric default IPv4 route on a physical NIC; when there is no default route, it can use an IPv4-addressed physical NIC. Tunnel/VPN interfaces are excluded from automatic WOL selection.
- Support the optional `LINUX_HOST_WOL_INTERFACE` service environment variable and `install-agent.sh --wol-interface IFNAME`. Pinning a NIC is recommended for multi-interface systems, unusual route arrangements, or multiple Ethernet adapters; it does not replace or change the existing power-control authentication.
- Keep `After=network.target` (no `network-online.target` wait); no new agent dependencies or API changes.
- No changes to the Edge Driver v0.2.5, profiles, identifiers, WOL logic, or keys. **Reinstall only the agent**, keeping power control enabled with `--enable-power` as previously configured.
- Added tests simulating a route appearing after daemon startup, explicit interface override, physical NIC preference over Tailscale, and a LAN without a default route. Total: 27 local tests passed; hub verification still required.

## 0.2.5 — WOL metadata recovery hotfix (Edge only)

- Recover WOL MAC and broadcast automatically from a reachable Linux Host Agent when the SmartThings device has lost or not yet received its persistent metadata (including after device recreation).
- Validate the returned installation UUID against the current device network ID **before** accepting any recovered MAC, preventing accidental wake-up of the wrong host after a DHCP address reassignment.
- Persist only valid unicast Ethernet MACs and IPv4 broadcast addresses; announce MAC acquisition and metadata failures in driver logs.
- Refresh WOL metadata during normal health polling when missing; retry it on-demand when Wake is pressed while the agent is reachable. Once saved, WOL continues to work even when the host is off.
- Keep the existing per-device WOL MAC override as an offline recovery option. Invalid overrides are rejected explicitly.
- No changes to profile IDs, SmartThings preference keys, authentication, device UUIDs, Linux agent, or power-state behavior. Existing agent v0.2.1 stays installed.
- Added regression coverage for missing fields, agent UUID mismatch, offline WOL after metadata persistence, and manual MAC override.
- The separate SmartThings mobile-app control/network error reported after device recreation has **not** been proven to be caused by the MAC bug. Test mobile-app routing separately if it persists.


## 0.2.4 — SmartThings Switch state and power transitions

- Report Switch OFF after repeated TCP host timeouts or unreachable-host errors (default), including power-off initiated outside SmartThings. Report ON upon renewed health success. The off inference is configurable with `assumeOffWhenUnreachable`.
- Keep Switch ON when only the agent port refuses connections, reflecting evidence that the host TCP stack is still running; still expose advanced status `unreachable`.
- Preserve Switch ON during an acknowledged reboot, waiting for a changed Linux boot ID instead of clearing the pending reboot action on an early successful health request.
- Switch ON sends WOL when the agent is not reachable, and does not emit optimistic ON before successful health. Switch OFF requests authenticated shutdown and waits for failed health checks to report OFF; on rejection, reassert the current switch state.
- Count consecutive host-level failures independently of other API failures. Re-publish the first observed switch state following driver initialization and log connection restoration.
- Added full Lua mocked command/state regression coverage and classifier tests; updated both profiles and docs.
- **Edge-only update:** Linux agent stays v0.2.1. Persistent installation UUID, DNI, profile names and authentication preferences unchanged.


## 0.2.3 — Edge health polling and mDNS fallback fix

- Prevented a Lua exception on the first successful health poll when the success counter has not been initialized. Explicitly bind `get_field()` results before `tonumber()` for success, failure and pending-action counters.
- Avoided attempting ordinary HTTP access to unresolved `.local` names from IPv6-only mDNS records. IPv4 discovery remains automatic; manual host configuration still permits user-supplied hostnames.
- Distinguished unexpected Lua polling exceptions from actual HTTP failures, avoiding false host-offline classifications.
- Added regression tests for missing Edge fields and mixed IPv4/IPv6 mDNS responses.
- Updated Edge driver version to 0.2.3. Profiles, device IDs and configuration preferences are unchanged, so existing installations are retained.
- Linux Host Agent remains v0.2.1; **no agent reinstall is required**.


## 0.2.2 — SmartThings profile packaging fix

- Shortened the embedded `controlKey` preference title from 37 to 32 characters to satisfy the SmartThings 3–36-character validation rule.
- Applied the same fix to the optional advanced profile.
- Added a static regression test covering title limits in both profiles.
- No changes to the Linux agent, API, Edge driver Lua behavior, device IDs or preferences identifiers. The bundled agent remains v0.2.1.


## 0.2.1 — systemd startup hotfix

- Removed the unnecessary dependency on `network-online.target` from `linux-host-agent.service`.
- The agent now starts after `network.target` without waiting for `systemd-networkd-wait-online`, even on hosts not using `systemd-networkd`.
- No API, authentication, SmartThings profile, or telemetry behavior changes.


## 0.2.0 — development preview

- Replaced the earlier `presenceSensor`-only profile with a standard **Switch**
  and Refresh/Temperature capabilities.
- Added separate Wake, Reboot and Suspend momentary components.
- Implemented UDP Wake-on-LAN on the SmartThings hub, with configurable MAC,
  broadcast address and port.
- Added opt-in authenticated remote shutdown, reboot and suspend using an
  HMAC-SHA256 nonce challenge and isolated systemd/Unix-socket power helper.
- Implemented CPU utilization, CPU temperature, memory, load, root disk usage,
  uptime and boot-ID collection in a Python standard-library daemon.
- Added optional templates for six custom telemetry capabilities and an
  advanced profile without making the base package dependent on them.
- Preserved stable installation UUIDs, mDNS/manual discovery, persisted IP
  metadata, dynamic IP rediscovery and controller-online/host-unavailable
  separation from 0.1.0.
- Added systemd service/socket units, Avahi advertisement, installer, security
  documentation and automated tests.
- Retained established versioned top-level directory ZIP convention.

## 0.1.0 — initial proof of concept

- LAN discovery and read-only agent health checks with a presence sensor.

## Integration 0.3.1-beta.1 — closed-beta engineering candidate

- Agent **remains v0.3.0**; Edge Driver **remains v0.2.9** (no runtime change).
- Added six-target GitHub Actions distro **source** smoke matrix (Debian 12/13, Ubuntu 24.04/26.04, Fedora 43/44). No CI runs are implied by including the workflow.
- Added a disposable agent loopback smoke test using temporary state and power disabled.
- Added a privacy-conscious diagnostic/feedback report, volunteer checklist, security notes, supported-evidence matrix, installation guide and licensing/publication gates.
- Verified existing v0.3.0 agent against actual Gentoo hub hardware using user-provided results; Debian 13 source-smoke validated locally.
- Does **not** yet include distributable DEB/RPM packages. Requires owner license choice and external distro validation before unrestricted public beta.
