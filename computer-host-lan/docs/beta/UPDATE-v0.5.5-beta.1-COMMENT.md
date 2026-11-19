### Computer Host LAN v0.5.5-beta.1 — stabilization update

**Post only after** the new GitHub prerelease is published, its hashes are verified, and Edge Driver v0.4.3-beta.1 is assigned to the **existing** SmartThings channel.

**[Download Computer Host LAN v0.5.5-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.5-beta.1)**

Following the successful Windows 11 Pro tests of the graphical installer and the thorough final code review, this beta focuses on reliability rather than adding new features.

Windows Setup now includes improved recovery when an upgrade fails, and both Windows installation methods better preserve custom configuration. A custom HTTP port is also recognized by the firewall and diagnostics. Authentication-key permissions and release version checks have been tightened, and SmartThings now uses clearer labels for the Wake, Restart and Sleep controls. The driver also handles quick resume and canceled shutdowns more consistently.

**The Windows Setup.exe remains the recommended installer**, while the ZIP/PowerShell option is still available. The Linux agent and SmartThings Edge driver have also been updated; protocol v2 and existing device identities are unchanged. **Don't delete or re-pair your SmartThings computer device.**

This beta is especially useful for testing in-place upgrades from v0.5.4-beta.1, service interruption/recovery and the revised GUI upgrade safeguards. Windows 11 Pro installation, upgrade and metrics were previously reported working on v0.5.4, but the new recovery paths still need field testing. Windows wake-from-sleep/shutdown remains hardware-dependent.

As before, the Windows packages are unsigned and intended only for trusted local networks. Please verify the checksums and omit private keys or identifying network details from reports. Feedback here is very welcome!
