# Computer Host LAN — v0.5.6 release-integrity audit (2026-11-20)

**Scope:** Read-only inspection of the published v0.5.6-beta.1 GitHub release, the corresponding tag and CI logs, release assembly scripts, Windows packaging declarations, and third-party notices. This is evidence for the v1.0 readiness checklist, **not** an independent security assessment or legal sign-off. No host, SmartThings hub or published asset was modified.

## Verified release evidence

- **Published prerelease:** [computer-host-lan-v0.5.6-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.6-beta.1), published **2026-11-20 13:55:46 UTC**, draft=false, prerelease=true.
- **Tag and release target:** both point to full commit `ec0a88db25c30c988c2b26f01236fa8e56f968cd`. This is the source commit recorded in the release-packaging validation log.
- **All four push workflows succeeded on that SHA:** [Linux](https://github.com/ldeora/SmartThingsEdgeDrivers/actions/runs/44745252772), [Windows agent](https://github.com/ldeora/SmartThingsEdgeDrivers/actions/runs/44745252804), [native Inno GUI](https://github.com/ldeora/SmartThingsEdgeDrivers/actions/runs/44745252851), [full release asset validation](https://github.com/ldeora/SmartThingsEdgeDrivers/actions/runs/44745252775). These are CI tests, not physical Windows/Linux or SmartThings channel-deployment evidence.
- **Release contents:** exactly four named deliverables plus `SHA256SUMS.txt`, visible through the GitHub release API.
- The release workflow verified the expected ZIP/installer filenames, inner Windows `BUILD-INFO.json` (version/commit/runtime), source/documentation `release.json` copies and the unified checksum manifest.

### CI → GitHub release artifact comparison

The published GitHub asset API exposes SHA-256 digests. The source and documentation ZIP hashes were computed independently from the downloaded **source-workflow artifact** (ID `14632936462`); the Windows ZIP and Setup hashes were obtained from the **Windows-build job log** (job `136318781816`). The published digest of the checksum file was compared with the **reconstructed** checksum manifest using the exact shell glob order in the release assembly script (`*.zip` then `*setup.exe`).

| Published release asset | SHA-256 recorded by CI | Matches published GitHub digest? |
| --- | --- | --- |
| `computer-host-lan-v0.5.6-beta.1-documentation.zip` | `b33547ae179b5400274ad2206cc0821bb0b7c4fcf321e79d4e0626b59162ba01` | **Yes** |
| `computer-host-lan-v0.5.6-beta.1-source.zip` | `ee4de82c985c41bf9add45da38581271b4d19c0f287a37da7a2d0200938fa70d` | **Yes** |
| `computer-host-lan-v0.5.6-beta.1-windows-x64-unsigned.zip` | `88e9683f5c81787bfa9f3a40e2e431e67d4bc791d1e01dbec06a97a28ac27471` | **Yes** |
| `computer-host-lan-v0.5.6-beta.1-windows-x64-unsigned-setup.exe` | `48f9adb5f6b34b9036b09c160b0dab18477540a4ced2827b3a7c93bf715f5049` | **Yes** |
| `SHA256SUMS.txt` | `14bcaf6b8d8718335b0ef889c9b3c55d977dfb34aabfe43d9c65d10b06435e8e` (reconstructed manifest digest) | **Yes** |

**Conclusion:** Strong evidence supports that all five published attachments match the files generated or verified by the release workflow on the release commit. This is a digest/CI-log comparison; the release assets themselves were not independently downloaded and rehashed one by one. The GitHub API provides asset digests, not Authenticode signatures or an independently verified chain of custody for a compromised publishing account.

## Gaps requiring action before stable publication

### P0 — Redistribution and third-party notices

- `windows-agent/ComputerHost.WindowsAgent/ComputerHost.WindowsAgent.csproj` directly references `Microsoft.Extensions.Hosting.WindowsServices` 10.0.0; `windows-agent/HubDiscovery/ComputerHost.HubDiscovery.csproj` references `Zeroconf` 3.7.16. Both produce self-contained .NET 10 Windows builds.
- `docs/beta/THIRD-PARTY-NOTICES.md` is explicitly an **inventory**, not the full transitive dependency/redistribution license bundle; it already flags sign-off as open.
- `build_windows_kit.py` includes the project's Apache `LICENSE` and the third-party **inventory**, but does not gather the **full applicable upstream license texts** from the resolved restore output. `ComputerHostLAN.iss` includes the inventory in the graphical installation but does not explicitly install the project's Apache `LICENSE` or a complete collection of third-party notices.
- **Action:** record the complete restored dependency graph and exact runtime/installer components; review applicable license obligations with the actual build outputs; package required license texts and notices in both Windows delivery paths. Determine whether an Inno Setup commercial license purchase is appropriate for the publisher's usage. Do not declare license sign-off complete from this inventory alone.

### P0 — Code-signing decision

- Current Windows Setup and agent are explicitly **unsigned**. SHA-256 checksums and potential GitHub provenance attestations do not provide a Windows Authenticode publisher signature or instantly remove SmartScreen warnings.
- **SignPath Foundation** offers OSS signing subject to project, team/release policy, signable-file, approval and provenance requirements; it would sign under the **SignPath Foundation** publisher identity, not automatically under a personal developer name.
- **Microsoft Azure Artifact Signing** (formerly Trusted Signing) is another option, but eligibility differs for organizations and individuals and by country. Confirm the publisher's legal/entity status and availability before selecting this route.
- **Action:** document an explicit sign/unsigned-stable decision, including any required enrollment work, and do not claim SmartScreen prompts will disappear immediately.

### P1 — Provenance, SBOM and build-input determinism

- The release workflow currently creates SHA-256 manifests and checks version/commit metadata but does **not** invoke `actions/attest`, generate an SBOM, or publish a signing attestation. CI artifacts are retained for seven days.
- GitHub Actions dependencies use mutable major-version tags (`actions/checkout@v7`, etc.); .NET SDK selection uses `10.0.x`; Inno Setup 7 is installed via unversioned `winget` resolution. Direct NuGet PackageReferences have versions, but no committed `packages.lock.json` was observed under `windows-agent/`. Consequently, **bit-for-bit reproducible Windows binaries have not been demonstrated**.
- **Action:** in a separate, scoped PR, evaluate locking/pinning input tools and resolved dependencies, then add build provenance using `actions/attest` for the final four produced assets. Generate a reviewed SPDX/CycloneDX SBOM from resolved release dependencies if practical; test the verification instructions before claiming provenance.

### Still outside this audit

- SmartThings Edge driver **0.4.4-beta.1 channel assignment and actual hub installation**.
- Independent real Windows 11/Gentoo v0.5.6 tests and PR #23 initial-search repaint confirmation.
- Physical Debian/Ubuntu testing, upgrade preservation on the RC, seven-day soak, and network-recovery cases.
- Direct HTTP retrieval of the five public attachments, as opposed to comparing GitHub's published asset digests against CI evidence.

## Recommended order

1. **P0:** Close the resolved dependency/redistribution notices inventory and package the applicable license texts (no auth, runtime or installation-state changes).
2. **P0:** Make and document the Windows code-signing decision; any signing integration comes later on its own PR.
3. **P1:** Add provenance/attestation and controlled dependency/tool versions only after assessing any impact on the existing packaging workflow.
4. Continue the already agreed hardware/SmartThings validation in parallel. Preserve v0.5.5 for tested rollback and do not overwrite v0.5.6 published assets.

Reference policy: [v1.0 release gates](V1-RELEASE-GATES.md) and [current release readiness](../../RELEASE-READINESS.md).
