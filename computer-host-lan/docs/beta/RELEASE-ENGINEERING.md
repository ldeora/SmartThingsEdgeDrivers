# Computer Host LAN — v0.5.5-beta.1 candidate release engineering (2026-11-19)

**Published baseline:** v0.5.4-beta.1 remains available. **Unpublished candidate:** v0.5.5-beta.1, based on merged PR #19, with Linux/Edge v0.4.3-beta.1 and Windows v0.2.4-beta.1. Protocol v2 is unchanged.

1. Merge the release-version PR only after the four CI workflows pass on one commit. The **final merged `main` commit** must pass them again.
2. Download `computer-host-lan-complete-unsigned-beta-candidate` from that final release workflow. Verify **3 ZIP archives, one Setup.exe and `SHA256SUMS.txt`**, plus internal Windows ZIP `BUILD-INFO.json`, source `release.json`, runtime version constants and exact commit.
3. Approve the distribution caveats and copyright/license notices. Code signing and a broader provenance review remain open for stable v1.0; keep beta binaries explicitly unsigned.
4. Publish a **new prerelease** `computer-host-lan-v0.5.5-beta.1` from that final commit; do **not** overwrite existing beta assets or tags. Verify release attachments and hashes post-publication.
5. Repackage and assign the **changed** SmartThings Edge driver v0.4.3-beta.1 to the **same existing driver/channel**, preserving UUIDs, profiles and registered custom-capability schema. This is **not automated** by GitHub Actions.
6. Ask Windows 11 Pro tester to upgrade from the released v0.5.4 Setup and check identity, settings, service recovery, metrics; recheck Gentoo. Announce in the existing Community thread only when both binary release and Edge channel are ready.

Future RC/stable release gates: [release readiness](../../RELEASE-READINESS.md). Previous release-engineering history follows.

---

## Next beta candidate v0.5.3-beta.1 (2026-11-18)

**Tag:** `computer-host-lan-v0.5.3-beta.1`. **Source:** merged PR #15 followed by the release-version PR. The publisher validated all four RAM and filesystem readings on real Linux/hub hardware. The existing `oceancircle09600.computerMemoryUsage` / `computerDiskUsage` capability schemas, localizations and presentations were updated and confirmed, so testers must not create them.

Do not replace or delete [v0.5.2-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.2-beta.1) assets. Verify GitHub Actions Linux, Windows and unsigned candidate packaging at the **final `main` commit**, then download artifact `computer-host-lan-complete-unsigned-beta-candidate`, verify all three ZIPs and the manifest, confirm source `release.json` and Windows `BUILD-INFO.json` embed the same final SHA and correct versions. Publish new **prerelease** with ZIPs + `SHA256SUMS.txt`, then package/assign the new Edge driver to the **existing shared channel** preserving driver ID. Announce only after both are ready with `docs/beta/UPDATE-v0.5.3-beta.1-COMMENT.md`.

CI does **not** publish GitHub releases or change SmartThings channels. Windows executable remains unsigned and Windows 11 hardware measurement validation is a beta test objective.

---

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
