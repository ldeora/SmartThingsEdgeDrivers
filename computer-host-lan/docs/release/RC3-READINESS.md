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
| #84 Linux authenticity / #171 release approval | Implemented policy, not exercised; approver not yet confirmed | Continue pre-candidate work now. Current gate remains mandatory unless a separately reviewed prerelease-only policy is approved. Exact-candidate main CI, reproducible build, attestation and independent positive/negative verification remain required; no unverified elevated binaries. |
| #101 Linux engine cutover | Implementation merged, acceptance pending | Verified release candidate; clean install, legacy rc.2 in-place upgrade, repair, recovery, removal/reinstall, old entry-point refusal and identity continuity on real Gentoo and Debian/Ubuntu hosts. |
| #155 retained credentials | Narrow schema-1 implementation merged (#159); preliminary hydra metadata evidence in issue | Real-host upgrade, service restart, authorized rollback on reversible hosts; check redacted UUID/key metadata outcomes. Interrupted-process continuity remains not_verified, not a claim of equality. |
| #118 Third-party notice automation | Open follow-up (non-blocking for v1.0) | Best-effort evidence collection and notice-bundle improvements for Windows and Linux. Collection/upload failures do not block candidate CI or attestation. Preserve existing notices; the publisher remains responsible for applicable redistribution terms. An incomplete inventory is not a compliance sign-off. |
| #117 Windows signing | Maintainer decision: retain unsigned packages for v1.0.0 | Document unsigned status, checksum limitations, SmartScreen/Smart App Control and machine-readable release metadata before publication. Defer formal signing integration; do not bypass platform protections. |
| #120 / #23 Windows hub-page rendering | Physical confirmation pending; synchronous search remains a reported risk | Ask reporting Windows 11 tester to exercise first search, retry, manual selection and navigation. If reproduced, isolate a bounded UI fix and test; no speculative full installer redesign. |
| #31 Linux connection saturation | Merged (#176), needs acceptance | Absolute header deadline implemented (#56). Preserve 12 global handlers and add four concurrent handlers per source IP. Loopback tests verify distinct-source health, repeated excess connections, shared-source operation, global exhaustion and cleanup. Document residual distributed saturation, backlog pressure and shared-source limits. No waiver or physical-hub PASS claimed. |
| #129 / #130 release docs | Quick Start implementation merged, wider docs still stale | Update version-matched primary docs, current state model, protocol freeze and security disclosures during prep. Document that a generic network/server error after a rejected power command can reflect refusal; check host power opt-in, matching key, allowPowerCommands and redacted logs. Do not imply every network error is refusal. Preserve historical files/immutable release notes and distinguish current published vs proposed release. |
| #119 hardware/soak | Open | Record exact-version evidence in one rc.3 acceptance record (below); two independent Windows 11 x64 hosts, Gentoo and Debian/Ubuntu, minimum seven-day real-hub Windows/Linux soak before stable. |
| Candidate identity and channel | Not prepared | Final versions, all five exact-main workflows, matching release assets, exact expected tag/SHA via independently trusted release record; separate explicit Edge upload/assignment and real installed version check. |

Order: complete the pre-candidate fixes below and settle remaining owner decisions,
prepare versions/docs/packages, verify exact-candidate release artifacts,
perform supervised physical checks, publish rc.3 only with explicit approval
and appropriate entry-gate evidence, soak and decide stable. No tag, dispatch,
publication or driver deployment is authorized by this record. The expected
source commit cannot be embedded in its own source commit as a self-reference;
publish the approved SHA in an independently trusted release record.

## Maintainer decisions and approved review-fix disposition (2026-11-25)

The maintainer has chosen to retain unsigned Windows packages for now,
continue development while looking for an independent GitHub environment
approver, and evaluate a narrowly scoped #31 mitigation before rc.3.
Issue #171 tracks the requested consideration of a prerelease-only approval
policy. The merged attestation gate is unchanged: no independent approver
means no eligible attestation dispatch under the current policy. Any rc.3
exception must be separately designed, reviewed and explicitly approved,
with no stable exception or unsigned Linux installer fallback. Ordinary CI,
code review and packaging preparation do not require that environment approval.

The following dispositions were approved by the maintainer by merging #170.
They explicitly preserve the roadmap rule that known in-scope production
fixes must land before the rc.3 freeze, not be postponed until soak.
Each fix requires its own scoped review and relevant behavioral tests.

| Issue | Approved disposition | Scope and rationale |
| --- | --- | --- |
| #126 | Merged (#174), needs acceptance | Preserve the existing ZIP/PowerShell power preference unless explicitly changed; fresh installs remain off, Setup explicitly communicates its choice. Reject conflicting flags. |
| #127 | Merged (#174), needs acceptance | Reuse only a validated existing Private firewall scope on upgrades, allow explicit changes, and refuse ambiguous or missing scope rather than silently broadening access. Cover GUI and silent paths. |
| #135 | Merged (#173), needs acceptance | A missing, malformed or unreadable key disables optional power without taking down otherwise safe monitoring. Never regenerate a key implicitly. |
| #121 | Merged (#173), needs acceptance | Check protected state and token ACL/ownership/reparse boundaries before runtime use; keep monitoring only when identity/state can be used safely. Do not create inherited unsafe state or weaken installer checks. Test under the actual service identity. |
| #134 | Merged (#175), needs acceptance | Emit appropriate switch acknowledgements for known command paths without inventing physical state or weakening shutdown grace. Preserve momentary capability/status contracts; document rejection guidance. |
| #123 | Merged (#177), needs exact rc.3 acceptance | Native cosock/LuaSocket CI and scoped physical V4 hub deadline/cleanup/recovery and authenticated OFF A/B passed (firmware `000.063.00006`). Maintainer approved the documented deferral; final PR CI green. Compatibility fallback is not a PASS. Uninterrupted one-hour normal operation, full accepted-command timing, physical power and unmodified package checks remain NOT TESTED against rc.3; seven-day soak and stable gates unchanged. See [qualification decision](../development/EDGE-HTTP-HUB-QUALIFICATION.md). |
| #125 | Accept current best-effort behavior for v1.0 with disclosure; improve in v1.0.1 | Hardware/OS-dependent suspend is already a declared limitation. S3 absence alone does not prove Modern Standby is unsupported. Do not add an unreliable capability filter. Document advertisement vs successful transition and qualify supported paths. |
| #124 | Merged (#178), needs acceptance | Prefer a fresh matching health response from the stored endpoint over a competing candidate; preserve explicit host override and cached WOL metadata until matching health on the newly selected endpoint. Recheck selection after yielding network probes. Test genuine address/port migration and competing UUID on disposable devices. This mitigates unnecessary redirection, not unauthenticated discovery itself. No new authentication protocol. |
| #132 | Merged (#179), needs acceptance | Address the known asynchronous registration failure with bounded retry and safe native callback lifetime; verify host-IP change/resume on real Windows. If automatic advertisement recovery fails within 180 seconds of restored network connectivity after DHCP change or resume, bounded/debounced network-change re-registration is a pre-rc.3 fix, not a deferred feature. |

Continue #118 in parallel as a non-blocking follow-up; prioritize the
approved production fixes and group #135/#121 and #126/#127 where shared
implementation boundaries justify it. No need to merge unrelated
changes in one PR. #31 follows its agreed evaluation gate above. If a
proposed fix proves substantially more invasive than expected, bring a
revised disposition to the maintainer rather than silently defer it.
After the candidate freeze, any production-code change invalidates the
affected candidate evidence and restarts the seven-day qualification soak
on the replacement candidate. No previously reported hardware PASS is
transferred automatically.

Windows #31 parity: this work package adds a four-connection per-source limit before HTTP parsing while retaining Kestrel's global twelve-connection limit. Verify distinct-source health, connection cleanup and shared-source operation on the exact candidate; distributed saturation and transport backlog pressure remain possible. No hardware PASS claimed.

## Previously addressed rc.1 findings (#136)

Implementation statuses below are grounded in the published
[rc.2 release notes](RELEASE-NOTES-v1.0.0-rc.2.md), with later main-only
changes explicitly identified; they are not new hardware certifications. Do not close issues automatically.

| Issue | Implemented | Remaining |
| --- | --- | --- |
| #32 | #58 protected ProgramData creation and retained-state checks | Real Windows refusal/valid upgrade; agent runtime ACL question tracked separately in #121 |
| #34 | #59 pending creation TTL | Real-hub duplicate/retry acceptance where safely reproducible |
| #37 | #59 failed Wake restores last known switch state in rc.2; #63/#64 state improvements are on post-rc.2 main only | Real-hub state transition acceptance |
| #44 | #57 fixed-path systemctl validation and delayed attempt semantics | Physical response delivery and actual host transition separately |
| #46 | #59 Private-only hint / Public warning | Real Windows profile and connectivity check |
| #47 | #59 redacted RC version/custom-port reporting | Verify against exact candidate |
| #31 | #56 cumulative header deadline; #176 per-source cap | Single-source monopolization mitigated; global and shared-source saturation remain possible; candidate acceptance pending |

## Scope control

- #148/#151/#152/#153 and remaining incompatible-schema #150 work:
  defer schema-2 production restore/adopt, durable credential evidence and
  cross-schema recovery provisioning to the separately reviewed 1.1 design.
  #160 implemented the narrow missing-helper evidence guard; do not claim
  that cross-schema compatibility has been delivered. Same-schema failures
  found in physical acceptance still block as appropriate.
- #128 automatic Linux inbound policy remains deferred. The maintainer's
  subsequent rc.2 parity decision supersedes the earlier WOL deferral:
  #183–#185 implement persistent wired WOL and explicit owned removal;
  physical acceptance remains pending. The narrow schema-1 retained-state
  reuse path below does not activate the experimental schema-2 engine.
- #79 residual local lock availability, #161 clean-host status/recover message,
  #163 unsafe obsolete artifact cleanup, #81 progress hints: retain tracked
  limitations; no automatic deletion of suspicious evidence. Promote to
  release blockers if reproduced on supported normal paths or if recovery
  is unsafe. #105 test refactoring and broader feature work remain deferred.
- The known review fixes have explicit approved dispositions above; they
  are not deferred by the implementation freeze. Remaining #41 security
  threat-model question, #131 mandatory Lua runtime (implementation in PR #175; verify candidate CI; broader harness refactoring deferred), #133 clock correction
  heuristic and older low-priority issues remain tracked. Confirm Lua tests
  actually run in candidate CI. Escalate concrete security, data-loss,
  upgrade, duplicate-device or persistent state defects. No blanket risk
  acceptance or issue closure.

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
| Linux Gentoo | verified installer; rc.2 migration, monitoring, same device, private state, service recovery, optional power/WOL; protected handoff via su and run0 (su preliminary evidence exists; run0 requires working authorization on a suitably configured host, not necessarily hydra) | NOT TESTED |
| Linux Debian/Ubuntu | clean install, upgrade/repair, removal/retained-state reinstall, authorized recovery, metadata stability, supported elevation | NOT TESTED |
| Linux diagnostics | terminal and accessible behavior, missing Avahi and firewalld guidance, custom port, no network mutations, legacy refusals | NOT TESTED |
| Windows 11 host A | fresh install/upgrade, initial and repeated search, manual IP, monitoring, service restart, optional power, retained state | NOT TESTED |
| Windows 11 host B (different NIC) | same checks; unsafe ProgramData fixture only on disposable test system; Private/Public restrictions | NOT TESTED |
| Real hub | same channel/driver identity; exact installed driver; no duplicate on upgrade; state after shutdown/reboot/suspend/Wake and failed Wake | NOT TESTED |
| Power refusal diagnostics | disposable test installation only: temporarily set a valid-format nonmatching key in SmartThings (never change the host key); OFF is rejected, switch returns ON, Host Status remains running and redacted log names key/opt-in settings; restore matching preference and verify monitoring. No physical power action should occur; NOT TESTED if not safe. | NOT TESTED |
| Edge transport | Repeat relevant scoped checks on exact rc.3 in a private channel: uninterrupted hour of normal health/metrics, refresh and availability (may be part of seven-day soak); safe ordinary ON and authorized physical power actions; full accepted-command timing; slow accepted challenge/POST on disposable fixture; slow header/body, inactivity timeout, cleanup, recovery, queued OFF, thresholds, no fallback. Record installed version, hub model/firmware and app timing. One slow poll plus challenge + POST can consume about 24 s of cooperative budgets, plus additional queued/synchronous work; even accepted commands may toast. Do not retry uncertain power POST. See [qualification decision](../development/EDGE-HTTP-HUB-QUALIFICATION.md) for scoped #177 evidence. Pre-merge metadata, approval and CI conditions were met; #177 is merged. | NOT TESTED against rc.3 |
| Network | hub restart, agent restart, router interruption, host DHCP/port change and separate hub IP change; disposable competing same-UUID discovery with responsive known endpoint, migration after failure, manual override and WOL metadata retention/refresh after matching health (#124); jointly test Windows DNS-SD (#132): after DHCP change or resume with connectivity restored, hub must rediscover within 180 seconds without re-pairing or restarting the agent; otherwise block rc.3 pending bounded network-change recovery fix | NOT TESTED |
| Windows + Linux soak | >=7 days each on exact candidate with real hub, dates and anomalies; record unsupported hardware separately | NOT TESTED |
| Release sign-off | signing decision, security caveats, final documentation, approval | NOT TESTED |
| Advisory #118 evidence (not a release gate) | record available notices, evidence failures and outstanding follow-up; publisher remains responsible for applicable terms | NOT TESTED |

Use this record to consolidate evidence as it arrives; do not mark an
unperformed check PASS. Any narrowing of supported platforms or deferral
requires an explicit maintainer decision and user-facing limitation.

### Retained rc.2 state reuse (implementation draft)

A read-only orphan-only plan identifies a candidate, not eligibility. The
wizard asks for REUSE instead of INSTALL; CLI requires --confirm REUSE.
The protected controller checks the shared lock, empty journal, absent
managed files/owner record, stopped units, exact private state layout,
canonical credentials and a complete root-private legacy v2 snapshot.
The snapshot corroborates protocol only, not credential association; the
operator confirms ownership. Existing credential continuity checks ensure
both files are unchanged. No new journal fields or credential copies.
A normal rc.3 uninstall with a valid owner marker keeps its existing path.
Physical rc.2 uninstall/reinstall acceptance and independent review remain.
