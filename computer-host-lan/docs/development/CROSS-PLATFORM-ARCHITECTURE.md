# Cross-platform architecture decision — 0.4.0-dev.1

## Decisions

1. One publisher-owned SmartThings Edge Driver for Linux and Windows.
2. Separate native agents. Python/systemd/Avahi remains the Linux reference.
   Windows agent will be a native Windows Service; C#/.NET is preferred but
   not finalized until a service/DNS-SD proof-of-concept is tested.
3. Generic JSON v2 protocol: same canonical metric names, power action
   identifiers, authentication construction, UUID identity and error codes.
4. Platform-specific metric availability and power semantics are explicit.
   Linux load averages remain Linux-only; CPU temperature remains optional.
5. No compatibility work for v1: there is only one private Linux installation,
   so new capabilities, new identifiers, and new discovery protocol are acceptable.
6. Linux functional equivalence is a **release gate**, not merely a wish.

## This candidate implements

- Generic edge Lua module namespace and package key.
- Shared validation of `protocol`, `api_version`, `platform`, installation UUID.
- Common `/v2/` API and HMAC header names in Linux + Edge Driver.
- Generic mDNS service type with Linux Avahi advertisement.
- Linux and Windows SmartThings device profiles (Windows profile is a stub
  waiting for a real agent); platform-dependent creation labels/metadata.
- Shared custom capabilities (CPU, memory, disk, uptime, host status), with
  Linux-only load averages retained in the Linux profile.
- Existing Linux systemd installer, power helper, telemetry samplers,
  state transitions, error classification, timers, WOL and authentication.

## Not implemented in this candidate

- C# Windows host agent, Windows Service installer, Windows DNS-SD advertiser.
- Real Windows telemetry, boot-session identity, power-state classification,
  WOL diagnosis, Fast Startup/Modern Standby detection and safe OFF preference.
- Windows OS/hardware test matrix or signed Windows distribution.
- TLS or read-response authentication; LAN isolation continues to be required.
- Real-hub checks for the refactored driver, custom capability IDs, and all
  Linux power functions. No hardware-tested claim for v0.4.0.

## Decisions deferred until Windows prototype

The Windows Service is expected to run under restricted credentials, with a
separate privileged operation path if needed. Security review must cover
local configuration ACLs, firewall rules, network profile changes, Windows
Fast Startup, Modern Standby, sleep/hibernation, boot-session identity,
service recovery, and installer updates. Windows shutdown WOL cannot be
promised because OEM/firmware/driver combinations differ.

A future shared protocol may add reported power mode and explicit capabilities
for `switch_off_behavior=shutdown|sleep|disabled`, and additional OS-specific
fields. Those fields must be designed with real Windows behavior before
being added to the current strict v2 contract.

## Scope of tests

The existing Lua state model `computerhost/state.lua` was kept functionally
identical to the verified Linux version, apart from a comment. Existing
switch/power/telemetry tests were updated to the newly named capabilities,
without changing behavioral assertions. New tests exercise v2 Linux HTTP,
strict old-route rejection, and mocked Linux/Windows discovery profile
selection. These do not emulate actual hub firmware or physical power states.
