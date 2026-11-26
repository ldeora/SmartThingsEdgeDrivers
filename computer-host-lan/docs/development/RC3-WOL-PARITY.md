# rc.3 persistent Wake-on-LAN parity (#88, #43, #49)

This is the first, deliberately inactive backend increment of the rc.3
parity work. No release or install behavior changes yet. Port the rc.2
configure-wol.sh paths, not the experimental wol_* modules.

## Contract before activation

* The ordinary-user wizard selects wired hardware only. Capability unknown
  (including denied ethtool GET) is distinct from unsupported. Default on
  only with verified magic-packet support. Existing upgrades preserve
  settings; no silent mutation. Show exact backend, profile or .link target
  and immediate runtime change before INSTALL. CLI --wol keep|configure|leave
  with explicit interface; keep and leave both preserve existing settings
  and ownership, configure requests the changes. Neither means relinquish
  rollback ownership.
* Privileged controller re-derives and validates the reviewed plan. No
  mutation until the schema-1 SNAPSHOTTED/APPLYING records are durable.
  Extend protected snapshot/provenance with a validated bounded WOL record
  of before and intended after state, including protected ownership before
  and after. No broadening of MANAGED_PATHS. Recover before state on every
  APPLYING+ failure; verify both network and managed-file rollback.
* Ownership must survive process restart, reboot, upgrade and uninstall.
  Distinguish transaction-created file from an identical preexisting or
  concurrently created file; byte equality alone is not ownership. Do not
  remove a file or modify a profile without verified ownership evidence.
  On a collision, crash or external change, refuse destructive compensation
  until provenance is resolved. Persist the original NM numeric setting,
  profile UUID and adapter identity, and account for reboot/ifindex change
  separately from immediate rollback. Keep existing rc.2 configuration.
* Integrate root request, preview API, Go wizard/CLI, trusted helper manifest,
  embedded bundle and sync tests together. Old journals without WOL records
  must remain recoverable. Add crash/failure injection and uninstall tests
  before enabling the backend. The current apply/restore primitives are not
  sufficient alone to establish ownership, and are not wired to any caller.
* Verify real nmcli output/round-trip numeric flags, udev rule selection,
  no-clobber and existing-rule behavior on supported distributions. The
  backend conservatively refuses complex link rules and SecureOn policies;
  do not silently override admin settings. No network restart.
* Physical tests: hydra (systemd-networkd) and a NetworkManager physical
  Ubuntu/Fedora desktop. Fresh installation, shutdown/wake, reboot,
  shutdown/wake, normal uninstall retains WOL; explicit removal restores
  the installer-owned configuration.
  VM can validate NM property changes but cannot prove physical wake.
* Completion and quick start: BIOS/UEFI support required; this setup does
  not support Wi-Fi WOL or routed-subnet WOL. Do not advertise a PASS before
  physical acceptance.

## Other rc.3 gates

Retained rc.2 identity reuse after explicit consent and strict validation;
historical snapshot restoration as a new transaction; installable release
asset. Do not close #88/#43/#49 merely because the backend exists.

## Installation lifecycle and multi-computer acceptance (maintainer decision)

rc.3 must be a complete replacement for rc.2, not a reduced-functionality
technical preview. Existing beta testers may upgrade, uninstall and reinstall
repeatedly, or install on additional computers while other agents retain
older versions. These are normal supported workflows. No new permanent
purge/factory-reset operation is required by this decision.

### WOL ownership and repeatability requirements for this PR

- A fresh install offers persistent WOL on supported wired hardware and
  applies magic-packet WOL immediately. Unknown capability is not unsupported.
- Upgrade from rc.2 preserves existing persistent WOL, including manual
  .link rules and NetworkManager profiles; never claim ownership merely
  because a setting or file matches the desired configuration.
- Upgrade, same-version reinstall and repair of rc.3 must be idempotent:
  preserve the original before-state of installer-owned WOL, not replace it
  with the already-configured state. Do not accumulate files, records or
  unnecessary network changes.
- Normal uninstall removes agent/services but retains WOL configuration and
  its protected ownership record, like rc.2. Preserve unrelated administrator
  settings, UUID, control key and recovery backups. Offer an explicit,
  unchecked "Also remove the Wake-on-LAN setting this installer made" option
  during uninstall and in Configure. Only verified installer-owned changes
  can be reversed. Conflicts or uncertain ownership must be reported, not
  resolved by deleting/replacing unknown configuration.
- Reinstall after normal uninstall must reuse legitimate retained identity
  and key, after the appropriate confirmation, and retain the original WOL
  ownership baseline. If explicitly removed and configured again, capture
  a fresh before-state. Never reuse stale ownership as authorization to
  mutate a new interface or profile.
- Preserve ownership and rollback across reboot and repeated upgrades;
  check stable adapter/profile identity rather than relying on an old
  ifindex. Recovery of an interrupted uninstall or reinstall must be
  covered, not only first-install failure.
- No automatic credential rotation, device deletion, network restart,
  or changes to another computer. Existing rc.2 WOL configuration stays
  administrator-owned unless independently established otherwise.
- Add fake-command/fixture regression tests for fresh configure, rc.2
  preconfigured upgrade, repeated upgrade/repair, normal uninstall/reinstall,
  explicit WOL removal
  on both persistence backends; verify original baseline restoration,
  external edits, crash recovery and absence of duplicate ownership.
  Include cases where a different adapter/profile is selected; require explicit
  confirmation for a new record and retain existing ownership until explicit removal. Keep/leave must not erase
  ownership or silently undo configuration.

### Physical lifecycle matrix (all NOT TESTED)

| Scenario | Evidence required |
| --- | --- |
| hydra existing installation | Record baseline agent/driver, locally compare identity/key without exporting them, existing device/routines, WOL policy and runtime; private candidate driver against old agent first |
| hydra in-place upgrade | Same device, settings, key and routines; existing WOL preserved; monitoring, reboot, suspend, shutdown and wake where supported |
| hydra normal uninstall | Agent/services removed; WOL and ownership retained by default, preexisting policy untouched; identity/key/backups retained; explicit removal tested separately |
| hydra reinstall | Reuse retained identity; original device resumes without re-pairing; configure WOL if selected; repeat monitoring and power tests |
| hydra repeated install/repair | No duplicate devices or accumulated configuration; verify WOL after reboot |
| Genuine first install (.link) | On suitable clean or disposable physical environment: configure WOL, shutdown/wake, reboot, shutdown/wake, normal uninstall retains WOL; explicit removal verifies reversal |
| Genuine first install (NetworkManager) | Same physical sequence; VM property/rollback evidence is supplemental only |
| rc.2 uninstall then rc.3 install | Separate retained-state parity gate: same identity/key/device after explicit validated reuse |
| Historical restore then upgrade | Separate historical-restore parity gate: managed files/services restored, identity/key/WOL preserved |
| Additional computer on same hub | Unique identity/key/device, correct metrics and target-specific power; upgrade/uninstall/reinstall one host without disturbing others |
| Mixed versions | Private candidate driver with rc.2 and supported v0.5.x agents; independently upgrade one host, leave others unchanged; no duplicates or cross-host commands |
| Windows lifecycle | Fresh install, old-version upgrade, same-version repair/reinstall, standard uninstall/reinstall, separate devices and settings continuity; separate Windows acceptance evidence |

Hydra is the maintainer's intended upgrade -> test -> uninstall -> reinstall
-> test sequence, not a confirmed clean-host test. No tester dates or results
are asserted. Physical power tests require saved work and physical recovery.
Record exact versions, OS/NIC, hub firmware, PASS/FAIL/NOT TESTED/N/A and
redacted evidence. Never export keys, UUIDs, MACs or private addresses.

The retained rc.2 state adoption and historical restore implementation remain
separate focused parity work packages, but all three functionality gates and
the installable release asset must pass before rc.3 publication. User guides
must explicitly cover normal uninstall/reinstall, retained device identity
and installing additional computers. No public driver deployment before
private mixed-version acceptance. No issue closure or publication is
authorized by this document.

## Review follow-up: bounded rc.3 implementation

Normal uninstall retains WOL by default, superseding the initial automatic
restoration requirement. Explicit removal satisfies #49 without introducing
network configuration changes into every uninstall. Use a small protected
root-owned ownership record next to the existing installer owner marker,
containing the backend, validated adapter MAC, profile UUID or fixed .link
name, previous value and written-state evidence (file digest/identity where
applicable). Persist intended before/after state with the existing schema-1
snapshot before APPLYING; do not treat intent alone as proof that a write
succeeded. Confirm ownership only when the write and verification establish
it. If a crash/collision leaves ownership ambiguous, do not delete an
unproven file or overwrite a changed NM profile. No new schema-2 engine,
research modules or exhaustive combinatorial crash matrix. Cover meaningful
failure boundaries and retain old-journal recovery.

Upgrade/repair retain the original record. A new adapter/profile requires
explicit confirmation and a separate bounded record; never silently discard
the earlier baseline. Reinstall after normal uninstall reuses the record.
Explicit removal is opt-in and independently verifies the owned state.
Keep the controller, wizard/CLI, preview, bundle and sync changes focused.

Backend review follow-ups:
- Parse documented numeric and symbolic NetworkManager flags; preserve
  values containing magic (including other bits), and do not run ethtool
  when runtime already includes magic. Real nmcli read/write evidence is
  still required. The Ubuntu CI smoke uses only a disposable, inactive
  Ethernet connection profile, never activates a connection, and reports
  actual output and numeric round-trip.
- Preserve the selected vendor default's Link settings when creating the
  per-MAC rule; refuse complex/default drop-in conflicts rather than
  changing unrelated policy. Give actionable guidance for manual rules,
  including generated netplan policies. Ubuntu Server networkd/netplan
  acceptance remains pending.
- No physical acceptance is inferred from fixture or profile-only smoke.

### Real NetworkManager evidence (2026-11-26)

Both push and PR Python 3.12 jobs on e07662d reached actual Ubuntu 24.04
NetworkManager 1.46.0 (package 1.46.0-1ubuntu2.9). The smoke completed
read/modify/restore for default, magic, combined 66 (phy, magic), and
ignore. The zero-flags query returned an empty string, which the parser
incorrectly refused. Normalize that successful property result to 0;
failed commands still raise. Added zero-flags restoration and failed-query
regressions. The full real round-trip including zero restoration is pending
CI on the corrected head; no physical wake or netplan acceptance implied.
Jobs: 139865220471 and 139865195723.


### Controller integration increment (draft)

The internal InstallRequest.wol_plan_digest field binds a reviewed plan to
root re-inspection. It is deliberately not accepted by the public request
router yet. The schema-1 snapshot records the intended change and boot ID.
The controller applies WOL only after managed-file/service and credential
verification, before COMMITTED. A root-private per-adapter record is
published before mutation and confirmed after persistent verification,
before runtime mutation. On rollback, a missing record means the WOL step
was not reached; an unconfirmed changed value or colliding link fails closed.
Confirmed links require the planned text and original inode; same-boot
rollback checks the interface MAC and ifindex. After reboot rollback restores
persistent policy without rewriting current runtime state. Normal uninstall
does not touch the record. Existing records are never overwritten by a
second configure; changed profiles, uncertain state, and reconfiguration
requiring explicit removal are refused. The public consent flow, explicit
removal, runtime-only record lifecycle, recovery ergonomics and additional
fixture/physical tests remain required before activation.

### Engine review follow-up

Optional WOL rollback errors (WolError or filesystem OSError) no longer
block verified managed-file/service rollback. The protected WOL ownership
record is left untouched by the controller on failure. A completed rollback
returns the fixed optional boolean wol_review_required in the privileged
JSON/CLI and a manual-check warning in the interactive installer. No raw
network error or private adapter/profile identity is serialized. Ordinary
agent recovery/credential checks still gate terminal rollback. If the process
loses its reply after terminal cleanup, the unresolved ownership record is
still the evidence; the later Configure/Remove UI must surface it. No new
journal fields or recovery subsystem.

The user-visible follow-up is limited to approval of visible policy fields
(or a privileged read-only preview), wizard and CLI keep/configure/leave,
explicit removal, and actionable existing-ownership guidance. Default Keep
on upgrade/repair; defer runtime-only lifecycle and existing-link reconfigure
beyond parity unless required for physical acceptance. No public activation
in this engine PR.

### User-visible WOL follow-up

Preview hashes only visible policy, including exact generated rule text.
Hardware capability may be unknown without privilege; root independently
checks capability and all visible policy fields before applying. Explicit
inspection/removal requires the existing shared lock and clean journal.
Removal is retryable using the retained record, without agent/service writes.
Normal uninstall retains WOL. No hardware acceptance is inferred from CI.

Wizard: choose Configure persistent Wake-on-LAN, select the wired interface,
review the policy and confirm INSTALL. Fresh installs default to Configure when a physical wired adapter is
suggested, even if ordinary-user hardware capability is unknown.
Upgrades/repair default to Keep. A positive root-side observation of no magic
support skips WOL and the interface pin, completes agent installation and
returns wol_status=unsupported. Unavailable root-side hardware capability likewise skips WOL with
wol_status=capability_unknown. Unsafe/changed policy and ownership conflicts
still refuse rather than authorizing a different change. A fresh wizard can
review a no-WOL fallback on the specific wol_preview_unavailable result;
CLI configuration and upgrade/repair previews remain strict. Other preview
errors are not suppressed. Keep and leave do not change persistent or runtime WOL.
CLI: run cli plan --action upgrade --wol configure --wol-interface IFNAME,
then cli upgrade --confirm UPGRADE --wol configure --wol-interface IFNAME
--wol-plan-digest DIGEST using the reviewed digest (install/repair analogous).
The existing bare --wol-interface remains pin-only.
Configure (-configure) uses protected inspection for a chosen interface;
explicit REMOVE confirmation is required for restoration. Normal uninstall
retains WOL; after verified agent uninstall, a separate optional removal
prompt defaults to No. CLI uses wol-check and wol-remove separately. Removal
never requires reinstalling the agent and does not change agent files or
services. The protected launcher may be provisioned/updated on authorized
check/remove; this is not an unprivileged preview operation.

Ordinary-user hydra evidence (2026-11-26): ethtool enp1s0f0 reports
netlink Operation not permitted, and ethtool --disable-netlink reports
Cannot get wake-on-lan settings: Operation not permitted. Neither exposes
Supports Wake-on or Wake-on. This confirms unknown is not unsupported.
