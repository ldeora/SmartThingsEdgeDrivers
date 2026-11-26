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
  shutdown/wake, uninstall restores installer-owned configuration.
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
- Normal uninstall removes agent/services and reverses only verified
  installer-owned WOL changes. Preserve unrelated administrator settings,
  UUID, control key and recovery backups. A conflict or uncertain ownership
  must be reported, not resolved by deleting/replacing unknown configuration.
- Reinstall after normal uninstall must reuse legitimate retained identity
  and key, after the appropriate confirmation, and allow WOL configuration
  again with a fresh ownership baseline. Never reuse stale ownership as
  authorization to mutate a new interface or profile.
- Preserve ownership and rollback across reboot and repeated upgrades;
  check stable adapter/profile identity rather than relying on an old
  ifindex. Recovery of an interrupted uninstall or reinstall must be
  covered, not only first-install failure.
- No automatic credential rotation, device deletion, network restart,
  or changes to another computer. Existing rc.2 WOL configuration stays
  administrator-owned unless independently established otherwise.
- Add fake-command/fixture regression tests for fresh configure, rc.2
  preconfigured upgrade, repeated upgrade/repair, uninstall and reinstall
  on both persistence backends; verify original baseline restoration,
  external edits, crash recovery and absence of duplicate ownership.
  Include cases where a different adapter/profile is selected; never
  abandon earlier managed changes silently. Keep/leave must not erase
  ownership or silently undo configuration.

### Physical lifecycle matrix (all NOT TESTED)

| Scenario | Evidence required |
| --- | --- |
| hydra existing installation | Record baseline agent/driver, locally compare identity/key without exporting them, existing device/routines, WOL policy and runtime; private candidate driver against old agent first |
| hydra in-place upgrade | Same device, settings, key and routines; existing WOL preserved; monitoring, reboot, suspend, shutdown and wake where supported |
| hydra normal uninstall | Agent/services removed; owned WOL restored where applicable, preexisting policy untouched; identity/key/backups retained |
| hydra reinstall | Reuse retained identity; original device resumes without re-pairing; configure WOL if selected; repeat monitoring and power tests |
| hydra repeated install/repair | No duplicate devices or accumulated configuration; verify WOL after reboot |
| Genuine first install (.link) | On suitable clean or disposable physical environment: configure WOL, shutdown/wake, reboot, shutdown/wake, uninstall and verify reversal |
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
