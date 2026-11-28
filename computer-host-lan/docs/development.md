# Development and release engineering

For contributors and maintainers. End users should start with the
[installation guides](../README.md#get-started). See [architecture](reference/architecture.md),
[protocol v2](reference/protocol.md), and the [Linux installer engineering
reference](reference/linux-installer.md). Keep user instructions current;
put open design work in issues, not historical narratives in user guides.

## Build and test

Work from the computer-host-lan directory in the monorepo. Use separate
disposable build/test environments. Do not elevate a development checkout
or run real power commands during automated tests.

Linux agent and Edge fixtures:

```sh
python3 -m pip install -r requirements-test.txt
python3 -m unittest discover -s tests -q
python3 scripts/ci/smoke_agent.py
```

Install liblua5.4 for mandatory Lua regression tests; CI sets
COMPUTER_HOST_REQUIRE_LUA=1. The Linux workflow also runs native cosock
transport integration and an isolated NetworkManager property smoke.
Containers cover Debian/Ubuntu/Fedora source compatibility, not real
systemd boot or physical WOL.

Linux standalone installer (Go version from release.json; currently
1.25.14):

```sh
cd linux-installer
python3 sync_bundle.py --check
go mod verify
go test ./...
go test -race ./...
go vet ./...
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -o computer-host-linux-installer-test .
```

Only demo/preview or unprivileged test workflows are appropriate for a
development build. When an authoritative agent/script/unit changes,
run sync_bundle.py and review the embedded diff in the same commit.
CI rejects stale payload bytes. Do not edit bundle copies independently.
Release builds must use the exact CI build flags and clean VCS identity
rather than treating a local development binary as a distributable.
Reconcile Linux third-party notices against the actual linked module
graph and build-info; preserve full upstream license texts.

Windows uses .NET 10, Windows PowerShell 5.1 and Inno Setup 7; build/test
the solution on a native Windows CI worker. The release workflow publishes
self-contained win-x64, builds the hub discovery helper, compiles Setup,
and exercises the extracted PowerShell kit. ARM64 cross-build is not
native qualification. Inspect the workflow for exact commands, compiler
version and build flags. Never invoke shutdown/suspend on CI.

## CI and documentation contracts

| Workflow under repository .github/workflows | Responsibility |
| --- | --- |
| computer-host-linux.yml | Python 3.10–3.14, Lua, distro smoke, native cosock, NetworkManager, source archive |
| computer-host-linux-installer.yml | Go, embedded parity, PTY/terminal stress, integration and license evidence |
| computer-host-windows.yml | .NET contract/service/power tests and ARM64 build |
| computer-host-inno.yml | Native Setup GUI and lifecycle/upgrade/uninstall |
| computer-host-release.yml | Exact-source unsigned candidate, reproducible Linux binary, Windows installer and archive checks |
| computer-host-docs.yml | Strict tracked links/anchors, generated user/Windows ZIP links |
| computer-host-linux-attested-release.yml | Separate optional protected attestation workflow, not ordinary release publication |

Run applicable CI on PR head and final merged commit. Explicitly dispatch
any path-filtered workflow missing on the final candidate. Do not merge
a runtime regression because documentation changed. Preserve tests of
state inference, identity, ACLs, protocol, journal recovery, terminal
handoff, WOL policy and secret redaction.

User guide packaging is selected by scripts/ci/user_docs.py, consumed by
build_release.py and build_windows_kit.py. Keep relative paths valid in
both actual ZIPs. Test notices, images and internal checksums; Setup's
notice path must match. Current download links and installer filenames
are checked against release.json; documented defaults/ranges and status
values are checked against actual profiles/capability. Keep development
history out of user downloads. Use the source ZIP for source work.

## Capabilities and presentations

End users install the existing channel driver; they do not register
custom capabilities. Maintainers use the account-owned namespace
oceancircle09600; a fork needs its own namespace and consistently updated
references. Six custom capability IDs (version 1) are computerHostStatus,
computerCpuUsage, computerMemoryUsage, computerDiskUsage, computerUptime,
linuxLoad. Preserve existing IDs, attributes, command/routine semantics
and translations. Only additive compatible metrics may be added to v2.

For first registration only, confirm the namespace and absence of the
capability; from edge-driver/ use:

```sh
smartthings capabilities:namespaces
smartthings capabilities
smartthings capabilities:create --namespace oceancircle09600 -i custom-capabilities/computerHostStatus.json
smartthings capabilities:presentation:create oceancircle09600.computerHostStatus -i custom-capabilities/computerHostStatus.presentation.json
```

Repeat for the other five only if absent, verify returned IDs. Existing
resources use deliberate update, never delete/recreate. Account-level
definitions, translations and presentations are separate from driver
packaging and affect every consumer, even older installed drivers.

Before any account mutation, confirm ownership, other consumers, live
schema, translations and presentation; save comparison evidence and a
known canonical Git rollback source. **The CLI presentation read can
return translated text rather than stored i18n placeholders. It is not
a safe rollback upload.** Compare per key/type, ignoring only expected
localized text differences; stop on unexpected drift. Use the known
canonical repository file with placeholders for upload/rollback. Do not
overwrite unrelated live changes. Get separate maintainer approval for
account-level changes.

For an isolated Host Status presentation update, from edge-driver/:

```sh
smartthings capabilities:presentation oceancircle09600.computerHostStatus 1 -j
# After comparison and explicit approval:
smartthings capabilities:presentation:update oceancircle09600.computerHostStatus 1 -i custom-capabilities/computerHostStatus.presentation.json
```

Check returned stored placeholders and expected values. Do not use the
bulk scripts/publish-presentations.sh --apply for an isolated edit; its
default dry run previews all six presentations and twelve translations.
Stop on API failure; never delete/recreate a capability as a workaround.
Rollback with reviewed pre-change canonical Git bytes, not localized
CLI output. The previously applied Unreachable inactive color is distinct
from the driver tile layout. Embedded deviceConfig must list every
component and capability in detail/automation views; test device
presentation and routine compatibility.

For additive schema changes, verify existing schema before updating,
apply reviewed definitions/translations/presentation in controlled order,
verify live registry and actual hub, then test agents and driver.
Missing optional values must not emit zero or poison emission caches;
preserve existing disk percentage semantics. Standard SmartThings
temperatureMeasurement/momentary are not ours to overwrite. Verify
actual app English/German labels and routines; registry synchronization
may need propagation or supervised hub restart, not device deletion.

Package from the exact reviewed candidate checkout:

```sh
smartthings edge:drivers:package ./edge-driver
```

Record driver ID, generated platform package version and source SHA.
Assign that exact version to a private development channel, verify actual
installed version on the test hub, and compare existing presentation,
metrics, routines and physical actions. Do not re-pair valid devices.
Retain previous package version for rollback; account-level rollback is
separate. No public assignment or account mutation without explicit approval.

## Release procedure

1. Decide version and scope; update integration/component versions,
   release.json, current notes, installer/version tests and current
   download references together. Protocol v2 remains backward-compatible
   for existing fields. Do not mark a candidate published because CI passed.
2. Review/merge the release-prep PR; freeze exact merged SHA. All applicable
   workflows must pass on that SHA. Download the complete unsigned candidate
   artifact from computer-host-release.yml; do not mix commits or builds.
3. Verify unified SHA256SUMS.txt, Windows internal BUILD-INFO.json and
   FILES.sha256, source release.json, Linux standalone binary checksum,
   build-info JSON and third-party notices. Verify reproducible Linux build,
   clean VCS revision, component versions and actual release asset set.
   Ordinary CI is not publication or publisher authentication.
4. Install verified final candidate on private test hardware/channel; record
   exact build and driver package version, upgrades and continuity, telemetry,
   recovery, power and known limitations. Test with older supported v2
   agents and multiple computers. Record scoped results, not aggregate
   claims. Keep current qualification and exceptions in
   [issue #119](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/119).
5. Obtain explicit publication approval and required licensing review.
   Current policy permits unsigned packages and defers formal signing/
   independent attestation integration; this is not a waiver of redistribution
   obligations. No automatic public release from CI. Create a new tag at
   the frozen SHA, create draft release with exact vetted notes/assets,
   download and verify all uploaded hashes against the original manifest,
   publish (prerelease for RC/beta), then independently verify public tag,
   asset count, checksums and release metadata. Never move a published tag
   or replace published assets under the same version.
6. Only after publication and channel approval, assign the previously
   qualified exact Edge package to public channel; verify separately.
   Do not repackage the tested driver. Announce both distributions only
   when confirmed. Update main's publication record without changing
   the frozen tag or implying later source builds are published assets.

Ordinary candidate assets include documentation/source ZIP, Windows x64
ZIP and Setup.exe, Linux x64 installer, its checksum/build-info/notices
and unified SHA256SUMS.txt. Verify the precise workflow contract, not this
summary alone. For redistribution see [notices](THIRD-PARTY-NOTICES.md).

## Stable qualification

The living stable decision is tracked in issue #119; preserve exact version,
commit, checksums, hub model/firmware, OS/NIC, PASS/FAIL/NOT TESTED/N/A and
approved scope dispositions. Prior prerelease publication never marks an
outstanding test passed. Preserve two physical Windows 11 hosts with
different NICs, Gentoo plus another supported Linux host (Debian/Ubuntu),
WOL persistence and retained identity, Windows GUI and network behavior,
Linux accessibility/authorization and recovery, mixed-agent/device
continuity, transport/hub checks and the seven-day real-hardware soak.
No physical wake guarantee from build/container evidence. Use safe
volunteer tests in [testing](testing.md); destructive/unsafe-state tests
belong only in disposable fixtures. Unverified or unsupported hardware
must be distinguished from defects. Separate account-level rollout evidence
from driver package evidence. Never publish raw IDs, addresses, tokens,
nonce/signature or unreviewed logs.

Stable 1.0 does not require adding TLS, automatic pairing/key rotation,
new metrics or OS support, new installers/package managers, or deferred
signing infrastructure beyond the approved scope. Fix blocking regression
or document an explicitly approved scope change, never silently waive
qualification. Keep a version-matched known-good rollback path.
