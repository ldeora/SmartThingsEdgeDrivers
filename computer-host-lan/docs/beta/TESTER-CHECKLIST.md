> **Historical v0.3.1-beta.1 beta document.** This page describes the previous Linux-only
> integration and is **not** a valid installation or protocol guide for
> v0.4.0-dev.1. Use root `README.md`, `PROTOCOL.md` and `INSTALLATION.md`.

# Closed-beta acceptance checklist

Record each case as PASS / FAIL / NOT APPLICABLE, including the distribution/version, kernel version and agent/driver versions. Keep credentials and network identifiers private.

## Baseline (all testers)

- [ ] `preflight.sh` reports the required tools and compatible Python; no unsupported assumptions made
- [ ] Installer dry run shows only expected files; no firewall/network/WOL change
- [ ] Fresh monitoring-only install succeeds without downloading pip packages
- [ ] Agent is running under `linuxhost`, not root; privileged power socket is not enabled by default
- [ ] `GET /v1/info`, `/v1/health`, `/v1/metrics` respond locally
- [ ] SmartThings discovers the host via Avahi/mDNS (or developer repackaged manual-host fallback)
- [ ] CPU temperature is shown if sensor supported (absence should not break other metrics)
- [ ] CPU, memory, disk, uptime, load and status update in the app
- [ ] Agent stop gives `unreachable` and does not falsely report host shutdown after TCP refusal
- [ ] Agent start returns to `running` without re-pairing or losing identity
- [ ] Agent service and monitoring survive an ordinary reboot
- [ ] In-place reinstall/upgrade retains identity, credentials, preferences and WOL settings
- [ ] Redacted `beta-report.sh` produces no secrets or host identifiers

## Power tests (explicit opt-in, local recovery path required)

- [ ] Read-only WOL detection identifies support, including root requirement where applicable
- [ ] Persistent WOL configuration survives reboot; NIC advertises magic packet wake (`Wake-on: g`)
- [ ] Authenticated reboot returns to Running; Switch stays On
- [ ] Suspend state and delayed Off transition behave as documented
- [ ] WOL wakes the suspended host; telemetry resumes
- [ ] Authenticated shutdown turns host off and Switch eventually Off
- [ ] WOL turns powered-off host on; status and Switch return to Running/On
- [ ] Restarting **only** the agent does not falsely flip the Switch to Off

## Lifecycle tests (test machine / VM only)

- [ ] Documented rollback restores the previous service version and state
- [ ] Deliberately simulated installation failure rolls back managed files (never delete identity/token)
- [ ] Uninstall removes only application-owned files and stops services
- [ ] Reinstall after uninstall reuses persistent identity when intended
- [ ] No native DEB/RPM package overwrote script-managed `/etc/systemd/system` units

## Additional interoperability evidence

- [ ] systemd PID 1 verified, not merely installed
- [ ] NetworkManager/networkd/other manager identified and documented
- [ ] SELinux enforcing/AppArmor restrictions checked (if present)
- [ ] IPv4 and optional IPv6 LAN paths checked
- [ ] TCP 8765 allowed only from the hub/trusted LAN; mDNS multicast routing understood
- [ ] Multi-NIC/Tailscale/VPN tested with explicit `--wol-interface` when necessary

Keep PASS/FAIL evidence per scenario. A passing container job is not a physical power-control test. Collect sanitized service logs only when an error occurs. Include a reproducible failure description rather than uploading complete journals.
