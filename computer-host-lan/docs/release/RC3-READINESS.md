# Computer Host LAN — rc.3 readiness and issue triage

Decision record, 2026-11-25; reviewed source baseline `352b7b7c2fb30df4e423fbb0c11cefaa743b06ba` (after #169).
This is a qualification plan, **not an approved candidate or release**.
Published rc.2 and its immutable assets remain unchanged. The existing
[stable gates](V1-RELEASE-GATES.md) remain authoritative. No gate is waived,
and no hardware result is inferred from a merged PR.

## Implementation freeze

The intended v1.0 Linux installer entry points use the same protected
schema-1 engine. Protected handoff (#164), attestation workflow (#165),
legacy mutation retirement (#166), onboarding/key guidance (#167),
network guidance (#168), ordinary-user default launch and prospective
[Linux Quick Start](LINUX-INSTALLER-QUICK-START.md) (#169) are merged.
Freeze installer features; fix only concrete release defects. Release
authentication, in-place migration and physical acceptance remain open.

## Remaining critical path

| Gate / issue | Status at baseline | Next evidence or action |
| --- | --- | --- |
| #84 Linux authenticity | Implemented policy, not exercised | Maintainer configures reviewed-main/tag protections and independently approved environment; exact-candidate main CI, reproducible build, attestation, independent positive/negative verification. Do not elevate unverified CI binaries. |
| #101 Linux engine cutover | Implementation merged, acceptance pending | Verified release candidate; clean install, legacy rc.2 in-place upgrade, repair, recovery, removal/reinstall, old entry-point refusal and identity continuity on real Gentoo and Debian/Ubuntu hosts. |
| #155 retained credentials | Narrow schema-1 implementation merged (#159); preliminary hydra metadata evidence in issue | Real-host upgrade, service restart, authorized rollback on reversible hosts; check redacted UUID/key metadata outcomes. Interrupted-process continuity remains not_verified, not a claim of equality. |
| #118 Windows redistribution | Open P0 | Collect exact resolved self-contained runtime and NuGet licenses/notices from release build, assess Inno Setup distribution terms, include required texts in ZIP and Setup, test presence, publisher sign-off. Do not invent licenses or infer compliance from inventory. Also inventory bundled Go installer dependencies for the new Linux deliverable. |
| #117 Windows signing | Owner decision pending | Record whether v1 remains unsigned with explicit warnings/limits, or use a separately approved signing route. Checksums are not publisher authentication. Do not bypass SmartScreen or Smart App Control. |
| #120 / #23 Windows hub-page rendering | Physical confirmation pending; synchronous search remains a reported risk | Ask reporting Windows 11 tester to exercise first search, retry, manual selection and navigation. If reproduced, isolate a bounded UI fix and test; no speculative full installer redesign. |
| #31 Linux connection saturation | Partial fix in rc.2; residual per-source/reconnect risk open | Absolute header deadline implemented (#56); global cap remains. Decide whether to mitigate before rc.3 or explicitly accept bounded trusted-LAN availability risk for 1.0 with disclosure. No waiver yet. A per-address cap must preserve ordinary hub and shared-source behavior. |
| #129 / #130 release docs | Quick Start implementation merged, wider docs still stale | Update version-matched primary docs, current state model, protocol freeze and security disclosures during prep. Preserve historical files/immutable release notes and distinguish current published vs proposed release. |
| #119 hardware/soak | Open | Record exact-version evidence in one rc.3 acceptance record (below); two independent Windows 11 x64 hosts, Gentoo and Debian/Ubuntu, minimum seven-day real-hub Windows/Linux soak before stable. |
| Candidate identity and channel | Not prepared | Final versions, all five exact-main workflows, matching release assets, exact expected tag/SHA via independently trusted release record; separate explicit Edge upload/assignment and real installed version check. |

Order: settle owner decisions and remaining pre-candidate implementation,
prepare versions/docs/packages, verify exact-candidate release artifacts,
perform supervised physical checks, publish rc.3 only with explicit approval
and appropriate entry-gate evidence, soak and decide stable. No tag, dispatch,
publication or driver deployment is authorized by this record. The expected
source commit cannot be embedded in its own source commit as a self-reference;
publish the approved SHA in an independently trusted release record.

## Previously addressed rc.1 findings (#136)

Implementation statuses below are grounded in the published
[rc.2 release notes](RELEASE-NOTES-v1.0.0-rc.2.md); they are not new hardware
certifications. Do not close issues automatically.

| Issue | Implemented | Remaining |
| --- | --- | --- |
| #32 | #58 protected ProgramData creation and retained-state checks | Real Windows refusal/valid upgrade; agent runtime ACL question tracked separately in #121 |
| #34 | #59 pending creation TTL | Real-hub duplicate/retry acceptance where safely reproducible |
| #37 | #59 failed Wake restores last known switch state; later #63/#64 state improvements | Real-hub state transition acceptance |
| #44 | #57 fixed-path systemctl validation and delayed attempt semantics | Physical response delivery and actual host transition separately |
| #46 | #59 Private-only hint / Public warning | Real Windows profile and connectivity check |
| #47 | #59 redacted RC version/custom-port reporting | Verify against exact candidate |
| #31 | #56 cumulative header deadline | Residual global-cap availability issue as above |

## Scope control

- #148/#151/#152/#153 and remaining incompatible-schema #150 work:
  defer schema-2 production restore/adopt, durable credential evidence and
  cross-schema recovery provisioning to the separately reviewed 1.1 design.
  #160 implemented the narrow missing-helper evidence guard; do not claim
  that cross-schema compatibility has been delivered. Same-schema failures
  found in physical acceptance still block as appropriate.
- #128 automatic Linux inbound policy, #88 persistent WOL, #49 WOL reset:
  no new network or NIC mutation for v1.0. Existing #168 manual guidance
  stays; revisit only a concrete supported-path failure.
- #79 residual local lock availability, #161 clean-host status/recover message,
  #163 unsafe obsolete artifact cleanup, #81 progress hints: retain tracked
  limitations; no automatic deletion of suspicious evidence. Promote to
  release blockers if reproduced on supported normal paths or if recovery
  is unsafe. #105 test refactoring and broader feature work remain deferred.
- Other open findings are not silently resolved: #121/#124/#41 security
  threat-model questions; #123/#132 transport/discovery; #127/#126 Windows
  upgrade behavior; #134 switch command rejection; #131 Lua test availability;
  #125/#135/#133 and older low-priority issues. Review actual supported
  behavior against the stable contract during targeted qualification; do not
  widen scope solely because a ticket is open. Escalate reproduced security,
  data-loss, upgrade, duplicate-device or persistent state defects. No blanket
  risk acceptance or issue closure.

## rc.3 acceptance evidence (#119)

Populate after candidate preparation; all entries below are **NOT TESTED**
against rc.3. Keep the older [rc.2 checklist](RC-ACCEPTANCE.md) as historical
evidence, not a substitute. Use exact artifact SHA-256, integration/agent/Edge
version, OS build, NIC, hub model/firmware, date, PASS/FAIL/NOT TESTED/N/A
and redacted reference per result. Never include key, UUID, IP or MAC in
shared evidence. No testing on a working host that requires intentional
credential corruption or unsafe power transitions.

| Group | Required observations | Status |
| --- | --- | --- |
| Build and trust | final main SHA, five workflows, independent provenance and downloaded bytes, complete matched asset set | NOT TESTED |
| Linux Gentoo | verified installer; rc.2 migration, monitoring, same device, private state, service recovery, optional power/WOL; protected handoff | NOT TESTED |
| Linux Debian/Ubuntu | clean install, upgrade/repair, removal/retained-state reinstall, authorized recovery, metadata stability, supported elevation | NOT TESTED |
| Linux diagnostics | terminal and accessible behavior, missing Avahi and firewalld guidance, custom port, no network mutations, legacy refusals | NOT TESTED |
| Windows 11 host A | fresh install/upgrade, initial and repeated search, manual IP, monitoring, service restart, optional power, retained state | NOT TESTED |
| Windows 11 host B (different NIC) | same checks; unsafe ProgramData fixture only on disposable test system; Private/Public restrictions | NOT TESTED |
| Real hub | same channel/driver identity; exact installed driver; no duplicate on upgrade; state after shutdown/reboot/suspend/Wake and failed Wake | NOT TESTED |
| Network | hub restart, agent restart, router interruption, host DHCP change and separate hub IP change | NOT TESTED |
| Windows + Linux soak | >=7 days each on exact candidate with real hub, dates and anomalies; record unsupported hardware separately | NOT TESTED |
| Release sign-off | licenses/notices, signing decision, security caveats, final documentation, approval | NOT TESTED |

Use this record to consolidate evidence as it arrives; do not mark an
unperformed check PASS. Any narrowing of supported platforms or deferral
requires an explicit maintainer decision and user-facing limitation.
