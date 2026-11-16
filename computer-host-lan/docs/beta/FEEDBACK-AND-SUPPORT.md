# Computer Host LAN — volunteer feedback

Use the [Computer Host LAN GitHub issue template](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/new/choose) for reproducible reports; the SmartThings Community thread can be used for initial coordination. Do not post security-sensitive diagnostics publicly. If a report requires a control key, HMAC header, packet capture or private account data, do **not** attach it to a public issue.

## Report format

- Integration release and host agent version (Linux or Windows):
- Computer Host LAN Edge Driver version:
- OS, version/build, architecture (Windows 11 x64/ARM64, Linux distribution/kernel):
- Hub model/firmware and whether first-time channel enrollment succeeded:
- Wired Ethernet / Wi-Fi / VPN / multiple NICs (no MAC/IP):
- Test ID from [checklist](TESTER-CHECKLIST.md), or reproduction steps:
- Expected result / observed result / reproducibility:
- Monitoring-only or power opt-in? Relevant power state (S0/S3/S4/S5/unknown):
- Sanitized diagnostics (optional); screenshot with device/location IDs obscured:
- Recovery steps or workaround:

## Safe diagnostics

Windows: run `scripts/Collect-WindowsDiagnostics.ps1` from the tester kit and **review the output** before attaching. `Get-WolDiagnostics.ps1` can display MAC addresses and must not be posted without manual redaction.

Linux: run `scripts/beta-report.sh` and review manually. Do not attach full `journalctl` output automatically.

**Never share:** `control-token`, authentication signatures/nonces, SmartThings credentials/account/location IDs, internal IP/MAC addresses, personal hostnames or installation UUIDs. Treat raw logs and screenshots as personal until inspected. GitHub issue comments and attachments are public in this repository.

## Expected support scope

This is an experimental community beta. Linux behavior is reference-tested on Gentoo; other distributions and Windows 11 physical power/mDNS behavior are the purpose of voluntary testing, not guaranteed. The operator must be capable of restoring power, network and normal service. No automatic updates, unattended-machine guarantees or manufacturer certification.
