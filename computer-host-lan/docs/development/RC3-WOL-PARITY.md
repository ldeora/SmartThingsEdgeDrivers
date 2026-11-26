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
