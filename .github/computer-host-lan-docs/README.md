# Computer Host LAN documentation migration

Maintainer working plan, outside the distributable Computer Host LAN tree. This
is not end-user documentation. Inventory baseline: `88752d571e71ec4ce111a07408fa7440ebbbb304` (98 Markdown
files). All rows are proposed destinations, not approval to delete files or a
claim that every design invariant has already been extracted.

## Boundaries

- No changes to agent, driver, privileged installer behavior, published tag,
  published assets, or channel assignments. No rebuild or redistribution under
  the already published rc.3 version.
- History stays in Git, release tags, issues and PRs. Keep important unversioned
  public entry points as short redirects only when needed.
- Review PR #211 independently; carry its Windows FAQ and Fast Startup changes
  forward into the user guides after it merges. Do not overwrite that work.
- Release qualification remains in [issue #119](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/119).
  Preserve exact candidate commit, asset digests, hardware scope, exceptions,
  pending tests and separate channel/presentation decisions. Published rc.3
  is at [its release](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.3).
  Do not conflate an earlier hardware result with final qualification.
- English first; German documentation/localization is a later release task.
- Keep conventional top-level filenames, use lowercase kebab-case under docs
  except the notices filename. Targets are roughly 18–20 Markdown files and
  20–25k words, not hard limits.

## Ownership and acceptance

| Destination | Owns |
| --- | --- |
| README.md | Product overview, support/qualification distinction, navigation and downloads |
| docs/install-windows.md | Windows setup, fallback, installed components and ordinary removal |
| docs/install-linux.md | Linux setup, installed/retained components, maintenance menu and ordinary removal |
| docs/smartthings.md | Channel, pairing, multiple hosts, all preferences, capabilities, Host Status versus switch and routines |
| docs/upgrade.md | In-place upgrade, repair, historical restore, interrupted recovery, retained identity and deliberate fresh start |
| docs/troubleshooting.md | Symptoms, network changes, Fast Startup, diagnostics, redacted reports |
| docs/testing.md | Short volunteer checklist, safe power tests and report format |
| SECURITY.md | Trust boundaries, authentication limits, privacy, vulnerability reporting and critical warnings for older releases |
| docs/reference/architecture.md | Current topology, state transitions and communication; one diagram |
| docs/reference/protocol.md | Current protocol v2 wire contract |
| docs/reference/linux-installer.md | Transaction, privilege, recovery, journal, retained-state and WOL invariants with test references |
| docs/development.md | Build, tests, CI, packaging, capabilities, presentation rollout and publication |
| docs/THIRD-PARTY-NOTICES.md | Required notices; no licensing omissions |
| docs/release-notes/ | Current release-specific change summary; old versions under tags |

Use one authoritative location per topic; repeat essential warnings and
short steps when necessary for safe standalone installation. Reference current
implementation and tests, not obsolete prose. Verify settings against both
platform profiles and state semantics against Lua. Distinguish observed state,
inference, command acknowledgement and physical outcome. Do not promise
hardware wake or support beyond the recorded evidence.

## Migration order

1. Foundation: inventory, non-regression link gate, root project description.
   No project files deleted/moved or packaging selection changed. The checker
   compares broken-link occurrences to the pinned pre-migration snapshot,
   reports inherited failures and fails new failures. The inventory is a
   routing map, not a completed semantic/incoming-link audit. Fix inherited
   defects while replacing their documents; remove the baseline in phase 4.
2. User guides and packaging: replace/install user docs only when successors
   are reviewed, migrate issue templates, screenshots and ZIP links together.
   Incorporate PR #211. Record the current release publication metadata on
   main together with its consumers and stage-aware tests; don't activate
   stale rc.2-specific assertions or imply newly built bytes are published.
3. References: verify source/test contracts, retain security and recovery
   invariants, move remaining open work to issues, consolidate developer docs.
4. Final pass: remove remaining superseded prose, update navigation/changelog,
   enforce strict links (including extracted ZIPs), check preferences and
   current version facts, run all applicable CI. No release without its own
   exact-commit acceptance.

## Known dependency inventory (verify each consumer before moving files)

- `scripts/ci/build_release.py`: directory-prefix selection of development,
  beta, release and history docs plus explicit root/component files. Replace
  with a deliberate archive layout; check relative links after extraction.
- `scripts/ci/build_windows_kit.py`: mapped beta files, RC overrides for
  START-HERE and TEST-CHECKLIST, versioned notes and screenshot copies.
  Keep required entry points, bytes, manifest entries and offline links.
- `windows-agent/installer/ComputerHostLAN.iss`: notices and installed
  connection material. Verify required license and notices coverage.
- `tests/test_beta_release_version.py`, `tests/test_public_beta_publication.py`:
  stage-dependent paths, release versions, screenshots, release URL, private
  channel separation and historical security assertions. Refactor contracts
  with replacement docs rather than dropping protections.
- `release.json`: component identity, stage, URLs, historical evidence and
  candidate guidance. Audit all consumers before schema changes. The current
  source manifest's stage predates publication; do not mutate the frozen tag.
- `.github/ISSUE_TEMPLATE/computer-host-lan-bug.md`: checklist and reporting.
- All Markdown and other tracked text (HTML, scripts, tests, workflow configs,
  issue templates, embedded payloads, and README links) must be searched for
  references to each moved path. Review external unversioned forum links
  separately; CI cannot prove all third-party bookmarks remain valid.
- No production code or embedded agent files change in this migration.
  Packaging/CI and docs tests can change; compare artifact layouts and
  notices, and rerun full applicable CI per PR.

Before each deletion, record the replacement and verify retained requirements
against code/test evidence. Do not remove warnings merely because they mention
an older release. Preserve required license texts and attribution, including
the Linux installer notices. Never weaken a runtime/security test to make
documentation migration pass.

## File-by-file routing inventory

Paths are relative to computer-host-lan/. Destination names without a directory
prefix in this table refer to the ownership table above. Git history means
remove only after the relevant content and inbound links are reviewed.

| Existing file | Proposed destination / disposition |
| --- | --- |
| `BETA-STATUS.md` | README.md; qualification issue |
| `CHANGELOG.md` | CHANGELOG.md |
| `DISTRO-MATRIX.md` | README.md; qualification issue |
| `HISTORY-PHASE2-RESULTS.md` | qualification issue; Git history |
| `INSTALLATION.md` | install-windows.md; install-linux.md; upgrade.md |
| `PACKAGING-STRATEGY.md` | development.md |
| `PORTABILITY.md` | README.md; development.md |
| `PROTOCOL.md` | reference/protocol.md |
| `README.md` | README.md |
| `RELEASE-BRIEF.md` | README.md; release notes |
| `RELEASE-PLAN.md` | development.md; qualification issue |
| `RELEASE-READINESS.md` | qualification issue; development.md |
| `SECURITY-HARDENING.md` | SECURITY.md; reference/linux-installer.md |
| `SECURITY-REVIEW-RELEASE.md` | SECURITY.md; qualification issue |
| `SECURITY.md` | SECURITY.md |
| `STATE-MODEL.md` | smartthings.md; reference/architecture.md |
| `TESTING.md` | testing.md; development.md |
| `VALIDATION.md` | qualification issue; testing.md |
| `WINDOWS-POWER-STATUS.md` | install-windows.md; smartthings.md |
| `docs/beta/COMMUNITY-ANNOUNCEMENT.md` | published forum or Git history |
| `docs/beta/COMPATIBILITY-STATUS.md` | README.md; qualification issue |
| `docs/beta/FEEDBACK-AND-SUPPORT.md` | troubleshooting.md |
| `docs/beta/ISSUE-REPORTING.md` | troubleshooting.md; issue template |
| `docs/beta/LICENSE-DECISION.md` | SECURITY.md (if relevant); development.md; notices |
| `docs/beta/PACKAGING-RELEASE-DECISION.md` | development.md |
| `docs/beta/PUBLICATION-GATES.md` | development.md; qualification issue |
| `docs/beta/RELEASE-ENGINEERING.md` | development.md |
| `docs/beta/RELEASE-NOTES-v0.5.1-beta.1.md` | versioned release/tag; CHANGELOG.md summary |
| `docs/beta/RELEASE-NOTES-v0.5.2-beta.1.md` | versioned release/tag; CHANGELOG.md summary |
| `docs/beta/RELEASE-NOTES-v0.5.3-beta.1.md` | versioned release/tag; CHANGELOG.md summary |
| `docs/beta/RELEASE-NOTES-v0.5.4-beta.1.md` | versioned release/tag; CHANGELOG.md summary |
| `docs/beta/RELEASE-NOTES-v0.5.5-beta.1.md` | versioned release/tag; CHANGELOG.md summary |
| `docs/beta/RELEASE-NOTES-v0.5.6-beta.1.md` | versioned release/tag; CHANGELOG.md summary |
| `docs/beta/SECURITY-AND-PRIVACY.md` | SECURITY.md |
| `docs/beta/SMARTTHINGS-CHANNEL.md` | smartthings.md; development.md |
| `docs/beta/START-HERE.md` | install-windows.md; install-linux.md |
| `docs/beta/TESTER-CHECKLIST.md` | testing.md |
| `docs/beta/THIRD-PARTY-NOTICES.md` | docs/THIRD-PARTY-NOTICES.md; preserve notices verbatim |
| `docs/beta/UPDATE-v0.5.2-beta.1-COMMENT.md` | published forum or Git history |
| `docs/beta/UPDATE-v0.5.3-beta.1-COMMENT.md` | published forum or Git history |
| `docs/beta/UPDATE-v0.5.4-beta.1-COMMENT.md` | published forum or Git history |
| `docs/beta/UPDATE-v0.5.5-beta.1-COMMENT.md` | published forum or Git history |
| `docs/development/CPU-TEMPERATURE-RANGE-EXPERIMENT.md` | development.md; smartthings.md if relevant |
| `docs/development/CROSS-PLATFORM-ARCHITECTURE.md` | reference/architecture.md |
| `docs/development/DEVICE-TILE-ROLLOUT.md` | development.md; smartthings.md if relevant |
| `docs/development/DISK-CAPACITY-ROLLOUT.md` | development.md; smartthings.md if relevant |
| `docs/development/EDGE-HTTP-HUB-QUALIFICATION.md` | reference/architecture.md; reference/protocol.md; qualification issue |
| `docs/development/FOUR-METRICS-ROLLOUT.md` | development.md; smartthings.md if relevant |
| `docs/development/LINUX-GO-INSTALLER-INTEGRATION.md` | reference/linux-installer.md; relevant user guide; qualification issue if open |
| `docs/development/LINUX-INSTALLER-API.md` | reference/linux-installer.md; relevant user guide; qualification issue if open |
| `docs/development/LINUX-INSTALLER-ARCHITECTURE.md` | reference/linux-installer.md; relevant user guide; qualification issue if open |
| `docs/development/LINUX-INSTALLER-CONSOLIDATION.md` | reference/linux-installer.md; relevant user guide; qualification issue if open |
| `docs/development/LINUX-INSTALLER-CREDENTIAL-CONTINUITY.md` | reference/linux-installer.md; relevant user guide; qualification issue if open |
| `docs/development/LINUX-INSTALLER-DESIGN.md` | reference/linux-installer.md; relevant user guide; qualification issue if open |
| `docs/development/LINUX-INSTALLER-PRIVILEGED-RECOVERY.md` | reference/linux-installer.md; relevant user guide; qualification issue if open |
| `docs/development/LINUX-INSTALLER-RELEASE-AUTHENTICATION.md` | reference/linux-installer.md; relevant user guide; qualification issue if open |
| `docs/development/LINUX-INSTALLER-RESTORE-ADOPTION.md` | reference/linux-installer.md; relevant user guide; qualification issue if open |
| `docs/development/LINUX-INSTALLER-TRANSACTION-BACKEND.md` | reference/linux-installer.md; relevant user guide; qualification issue if open |
| `docs/development/LINUX-JOURNALED-UNINSTALL.md` | reference/linux-installer.md; relevant user guide; qualification issue if open |
| `docs/development/LINUX-PARITY-ACCEPTANCE.md` | reference/linux-installer.md; relevant user guide; qualification issue if open |
| `docs/development/LINUX-PERSISTENT-WOL.md` | reference/linux-installer.md; relevant user guide; qualification issue if open |
| `docs/development/LINUX-PRIVILEGED-STAGING.md` | reference/linux-installer.md; relevant user guide; qualification issue if open |
| `docs/development/LINUX-TRANSACTION-JOURNAL.md` | reference/linux-installer.md; relevant user guide; qualification issue if open |
| `docs/development/LINUX-WOL-TRANSACTION-DESIGN.md` | reference/linux-installer.md; relevant user guide; qualification issue if open |
| `docs/development/RC3-WOL-PARITY.md` | reference/linux-installer.md; relevant user guide; qualification issue if open |
| `docs/development/WINDOWS-UPGRADE-POLICY.md` | upgrade.md; install-windows.md; development.md |
| `docs/history/RC2-AND-EARLIER.md` | Git history / tags; preserve applicable warnings in SECURITY.md |
| `docs/history/v0.3.1-beta.1/BETA-STATUS.md` | Git history / tags; preserve applicable warnings in SECURITY.md |
| `docs/history/v0.3.1-beta.1/CHANGELOG.md` | Git history / tags; preserve applicable warnings in SECURITY.md |
| `docs/history/v0.3.1-beta.1/INSTALLATION.md` | Git history / tags; preserve applicable warnings in SECURITY.md |
| `docs/history/v0.3.1-beta.1/PROTOCOL.md` | Git history / tags; preserve applicable warnings in SECURITY.md |
| `docs/history/v0.3.1-beta.1/README.md` | Git history / tags; preserve applicable warnings in SECURITY.md |
| `docs/history/v0.3.1-beta.1/RELEASE-BRIEF.md` | Git history / tags; preserve applicable warnings in SECURITY.md |
| `docs/history/v0.3.1-beta.1/RELEASE-PLAN.md` | Git history / tags; preserve applicable warnings in SECURITY.md |
| `docs/history/v0.3.1-beta.1/RELEASE-READINESS.md` | Git history / tags; preserve applicable warnings in SECURITY.md |
| `docs/history/v0.3.1-beta.1/SECURITY.md` | Git history / tags; preserve applicable warnings in SECURITY.md |
| `docs/history/v0.3.1-beta.1/STATE-MODEL.md` | Git history / tags; preserve applicable warnings in SECURITY.md |
| `docs/history/v0.3.1-beta.1/TESTING.md` | Git history / tags; preserve applicable warnings in SECURITY.md |
| `docs/history/v0.3.1-beta.1/VALIDATION.md` | Git history / tags; preserve applicable warnings in SECURITY.md |
| `docs/release/LINUX-INSTALLER-QUICK-START.md` | install-linux.md; upgrade.md |
| `docs/release/QUICK-START.md` | tag-pinned rc.2 docs; current install guides |
| `docs/release/RC-ACCEPTANCE.md` | qualification issue; testing.md |
| `docs/release/RC3-READINESS.md` | qualification issue; testing.md; development.md |
| `docs/release/RELEASE-NOTES-v1.0.0-rc.1.md` | versioned release/tag; CHANGELOG.md summary |
| `docs/release/RELEASE-NOTES-v1.0.0-rc.2.md` | versioned release/tag; CHANGELOG.md summary |
| `docs/release/RELEASE-NOTES-v1.0.0-rc.3.md` | release-notes/v1.0.0-rc.3.md |
| `docs/release/TROUBLESHOOTING.md` | troubleshooting.md |
| `docs/release/UPGRADE.md` | upgrade.md |
| `docs/release/V1-RELEASE-ENGINEERING-AUDIT.md` | qualification issue; development.md |
| `docs/release/V1-RELEASE-GATES.md` | qualification issue; development.md |
| `docs/release/WINDOWS-QUICK-START.md` | install-windows.md |
| `edge-driver/custom-capabilities/REGISTER.md` | retain short entry point; development.md |
| `linux-installer/README.md` | retain entry point; install-linux.md; upgrade.md; reference/linux-installer.md |
| `linux-installer/ui-demo/README.md` | retain demo-specific entry point |
| `windows-agent/README.md` | retain entry point; install-windows.md; development.md |
| `windows-agent/docs/ARCHITECTURE.md` | reference/architecture.md |
| `windows-agent/docs/HARDWARE-TEST-MATRIX.md` | testing.md; qualification issue |
| `windows-agent/installer/README.md` | install-windows.md; development.md |
