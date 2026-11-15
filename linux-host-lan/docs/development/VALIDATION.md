# v0.3.0 validation plan — from unit test to public beta

## Automated locally, without root

```sh
python3 -m unittest discover -s tests -v
./scripts/install-agent.sh --dry-run
for script in scripts/*.sh; do sh -n "$script"; done
systemd-analyze verify agent/systemd/linux-host-agent.service agent/systemd/linux-host-agent-power.service agent/systemd/linux-host-agent-power.socket
```

The regression suite currently passes **84 local tests**, including a check that the Apache-2.0 license is included in both source and standalone agent release artifacts. A separate real-process
smoke test on the Debian 13 execution environment confirmed that the
unprivileged agent v0.3.0 starts on loopback, exposes info/health/metrics,
and rejects challenge requests when power control is disabled.

The regression suite includes the tested v0.2.x Edge state reducer and HMAC
interoperability, plus bounded HTTP concurrency, challenge exhaustion,
per-IP/global rate limits, nonce replay, malformed POST handling, slow client
read timeouts and transactional file-rollback scenarios. All network tests
bind loopback only; power-helper calls are mocked.

## Distribution testing still REQUIRED

| Environment | Automated tests | Systemd installation | Hub discovery / power cycling |
|---|---|---|---|
| Gentoo (reference) | 83 tests passed | **v0.3.0 upgrade verified** | Agent 0.3.0 + Edge 0.2.9 monitored and power cycled successfully |
| Debian 13 | Local unit tests run in Debian 13 tool runtime | Not performed | Not performed |
| Ubuntu 22.04/24.04/26.04 | CI matrix configured, not executed | Not performed | Not performed |
| Fedora 43/44 | CI matrix configured, not executed | Not performed | Not performed |
| RHEL/Rocky/Alma 9/10 | Interpreter compatibility researched | Not performed | Not performed |
| Arch/openSUSE/Raspberry Pi OS | Hypotheses only | Not performed | Not performed |

`ci/github-actions-template.yml` is an **inactive** workflow template for future repository CI. It has not been activated or run on GitHub. Containers cannot
fully prove systemd boot, SELinux permissions, multicast discovery or WOL.

## Safe Gentoo upgrade validation

1. Preflight and read-only `--dry-run` first.
2. Save the current status and verify you have alternative local/physical
   access to recover if the agent fails.
3. Install agent v0.3.0 while retaining the already-proven SmartThings Edge
   Driver v0.2.9 and existing control key.
4. Confirm `curl -fsS http://127.0.0.1:8765/v1/info` reports agent `0.3.0`
   and the **same persistent installation ID** as before.
5. Confirm WOL MAC, broadcast and selected interface are unchanged; check
   `ethtool` as root where required.
6. Confirm two successive unsigned health/metrics polling requests work.
7. Confirm authenticated power control and Switch after stable operation.
8. Repeat deliberate agent stop/restart, reboot, suspend/WOL and shutdown/WOL
   only after verifying step 4–6.
9. If any issue occurs, use the printed recovery snapshot with
   `sudo ./scripts/rollback-agent.sh --backup /var/backups/linux-host-agent/snapshot-...`.

## External tester checklist

Capture distro/version/architecture, Python path, systemd version, network
manager, SELinux/AppArmor state, firewall status, Avahi availability, mDNS
results, WOL flags, installer/rollback output, agent health/metrics and
SmartThings UI state. **Redact hostname, installation UUID, MAC/IP and key**.

## Security gates before broad release

- Independent network/installer security review or migration away from
  `http.server` to a supported hardened transport.
- Document and validate key rotation, preference exposure, and credential
  provisioning across SmartThings accounts.
- Multidistro systemd/SELinux/AppArmor install, upgrade and uninstall tests.
- Trusted-LAN firewall guidance verified on representative setups.
- Signed/checksummed releases, attribution review, support process and a tested
  beta Edge Driver channel invitation process.
