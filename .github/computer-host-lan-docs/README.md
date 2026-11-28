# Computer Host LAN documentation consolidation

The four-phase migration replaced the historical notes with current user and
engineering references. The complete original inventory and migration plan are
retained at [the pre-cleanup commit](https://github.com/ldeora/SmartThingsEdgeDrivers/blob/ae6a53d870df67a1e3756a06ed9857731d8ba8a5/.github/computer-host-lan-docs/README.md).
The [same pinned project tree](https://github.com/ldeora/SmartThingsEdgeDrivers/tree/ae6a53d870df67a1e3756a06ed9857731d8ba8a5/computer-host-lan)
contains every retired file, including the complete development experiments,
historical release manifests, prior acceptance checklists and original notices.
Released tags/assets are unchanged.

## Current ownership

Start at [Computer Host LAN](../../computer-host-lan/README.md).
The six user guides own installation, SmartThings usage, upgrade/maintenance,
troubleshooting and volunteer testing. SECURITY owns trust and historic
security advisories. The three technical references and development guide
own implementation contracts, build, release and account-level changes.
Release-specific notes live in docs/release-notes; current manifest and
qualification issue #119 carry distinct publication and hardware evidence.

Keep a few short main-path compatibility pages for previously linked user
entry points; they are navigation only and not included in the docs ZIP.
Do not add obsolete content to them. The original source ZIP and release
tags remain the authority for older versions. External bookmarks cannot
be enumerated exhaustively; the known forum checklist path is retained.
Use [Git history](https://github.com/ldeora/SmartThingsEdgeDrivers/releases) for historic releases.

## Ongoing rules

- Update authoritative documentation with every behavior or default change.
- Never remove a security/runtime invariant or weaken a regression test to
  satisfy a documentation reorganization.
- Link check is strict; test repository links and all three extracted ZIP
  layouts. Version/default/state tests track canonical sources.
- Keep the required notices byte-for-byte; only reviewed dependency/license
  changes justify changes to notice content.
- Record exact release commit, manifest digest, and public release URL in
  release.json, qualification and separate driver deployment in
  [issue #119](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/119). No qualification waiver.
- New design discussions belong in issues/PRs; lasting contracts belong in
  [development](../../computer-host-lan/docs/development.md) or a technical
  reference. German translation/localization is a later release task.
