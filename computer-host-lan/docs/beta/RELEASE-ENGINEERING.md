# Computer Host LAN — public beta release engineering

**Version:** v0.5.1-beta.1 · **Tag:** `computer-host-lan-v0.5.1-beta.1`.

The [verified SmartThings channel invitation](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20) already distributes the Computer Host LAN driver. Another SmartThings account has installed it. The shared channel also contains other custom drivers; testers install only **Computer Host LAN**.

The GitHub draft prerelease was initially prepared from `eb277dde1fce72784c2da44eadbdd60f5356e20f`. **After merging any release-documentation changes, rebuild and replace its assets from the new exact `main` commit before publication.** Do not mix archives built from different commits.

The [.github/workflows/computer-host-release.yml](../../../.github/workflows/computer-host-release.yml) workflow builds source/docs ZIPs, tests and packages the unsigned Windows x64 agent, verifies the Windows package under Windows PowerShell 5.1 after extraction, and assembles a unified `SHA256SUMS.txt`. It never publishes releases, signs files, modifies SmartThings or executes authenticated power commands.

## Safe release publication
1. Confirm all Windows, Linux and release-packaging checks passed for the final `main` commit.
2. Download that commit's **complete** release-candidate artifact; verify all ZIPs with `sha256sum -c SHA256SUMS.txt`.
3. Confirm the Windows kit's `BUILD-INFO.json` and the source bundle's `release.json` match the final commit and version.
4. Replace all four draft release assets and its body with the vetted notes from that same commit. Keep it a draft while checking.
5. Confirm no mismatched existing tag; publish as **prerelease**, targeting the final commit. Verify resulting Git tag and public downloads.
6. Publish the [prepared SmartThings Community post](COMMUNITY-ANNOUNCEMENT.md).

**Disclosures:** Windows 11 real hardware discovery and power/WOL have not been validated. HTTP telemetry is not encrypted; use only on trusted LANs. The Windows executable is unsigned. Windows ARM64 is cross-built only; Linux distro container tests are not physical power tests.
