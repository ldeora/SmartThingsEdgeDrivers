# Computer Host LAN — compatibility evidence (2026-11-16)

| Platform | Evidence | Outstanding |
| --- | --- | --- |
| Gentoo Linux (`hydra`), systemd-networkd, Python 3.14 | **Real SmartThings hub hardware passed:** v2 discovery/metrics, service interruption/recovery, reboot, suspend/WOL, full shutdown/WOL | Other hardware, long unattended run, upgrade/rollback edge cases |
| Debian 12/13 | Python/unit and installer-source smoke **CI passed in containers** | Real systemd PID1, Avahi, hardware WOL |
| Ubuntu 24.04/26.04 | Python/unit and installer-source smoke **CI passed in containers** | Full systemd/network manager integration, hardware WOL |
| Fedora 43/44 | Python/unit and installer-source smoke **CI passed in containers** | SELinux enforcing, firewalld, actual hardware |
| Windows Server 2025 x64 | .NET 10 compile/run, metrics/API/HMAC tests, `LocalService` install/upgrade/opt-in/out on CI runner **passed** | Physical power actions, SmartThings LAN/mDNS, Windows desktop sleep policy |
| Windows 11 x64 | **No verified hardware result yet** | This is a primary beta volunteer target |
| Windows ARM64 | Cross-publish passed | Execution, installer, mDNS, power, hardware WOL |
| Other Linux, Windows variants | Not validated | Must not be advertised as verified |

Windows and Linux use the same v2 protocol but platform-specific app profiles. Windows has no fabricated CPU temperature or Linux load averages.

A pass in CI **does not** prove SmartThings device discovery, real S0/S3/S4/S5 transitions or WOL on a different network. WOL can fail after Windows Fast Startup or firmware-specific shutdown. Status `OFF` is inferred from network evidence, not physically measured.

[Windows CI](https://github.com/ldeora/SmartThingsEdgeDrivers/actions/runs/43827358333) · [Linux CI](https://github.com/ldeora/SmartThingsEdgeDrivers/actions/runs/43827358342).
