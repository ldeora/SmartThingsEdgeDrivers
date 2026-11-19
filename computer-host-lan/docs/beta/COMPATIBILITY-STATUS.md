# Computer Host LAN — compatibility evidence (updated 2026-11-19)

| Platform | Evidence | Outstanding |
| --- | --- | --- |
| Gentoo Linux (`hydra`), systemd-networkd, Python 3.14 | **Real SmartThings hub hardware passed:** v2 discovery/metrics, service interruption/recovery, reboot, suspend/WOL, full shutdown/WOL | Other hardware, long unattended run, upgrade/rollback edge cases |
| Debian 12/13 | Python/unit and installer-source smoke **CI passed in containers** | Real systemd PID1, Avahi, hardware WOL |
| Ubuntu 24.04/26.04 | Python/unit and installer-source smoke **CI passed in containers** | Full systemd/network manager integration, hardware WOL |
| Fedora 43/44 | Python/unit and installer-source smoke **CI passed in containers** | SELinux enforcing, firewalld, actual hardware |
| Windows Server 2025 x64 | Agent and native Inno Setup 7 GUI tests passed (Welcome, hub field, optional key copy, ZIP migration, upgrade, uninstall safety); service/HMAC/metrics CI passed ([GUI CI](https://github.com/ldeora/SmartThingsEdgeDrivers/actions/runs/44515639490)) | Physical SmartThings LAN/mDNS, Windows 11 graphical testing, WOL and desktop sleep behavior |
| Windows 11 x64 (first public-beta volunteer) | **Previous ZIP/PowerShell tester-reported success, not new GUI validation:** installation and basic SmartThings use; 64-character key entered via Android keyboard clipboard; authenticated Suspend, Reboot, and Shutdown (Switch Off) successfully executed | Windows WOL, detailed telemetry checks, service outage/recovery, upgrade/rollback, different NICs/hardware |
| Windows ARM64 | Cross-publish passed | Execution, installer, mDNS, power, hardware WOL |
| Other Linux, Windows variants | Not validated | Must not be advertised as verified |

The Windows 11 evidence is the tester's own report in the [SmartThings Community public beta thread](https://community.smartthings.com/t/st-edge-computer-host-lan-bring-windows-and-linux-computers-into-smartthings-public-beta/312605); it is not a complete independently witnessed hardware test matrix. Do not infer tested WOL or every monitoring attribute solely from the general positive installation report.

Windows and Linux share protocol v2 and have platform-specific app profiles. Windows does not fabricate CPU temperature or Linux load averages.

CI pass does not prove real-world SmartThings device discovery, S0/S3/S4/S5 transitions or WOL on a different network. WOL may fail after Windows Fast Startup or firmware-specific shutdown. Switch OFF after timeouts is inferred from network evidence, not electrically measured.

[Windows CI](https://github.com/ldeora/SmartThingsEdgeDrivers/actions/runs/43881027609) · [Linux CI](https://github.com/ldeora/SmartThingsEdgeDrivers/actions/runs/43881027590) · [Release packaging CI](https://github.com/ldeora/SmartThingsEdgeDrivers/actions/runs/43881027665).
