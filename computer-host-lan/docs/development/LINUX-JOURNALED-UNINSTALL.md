# Journaled Linux uninstall — backend foundation

Status: **draft / backend-only**. This work extends the merged Linux
transaction engine. It does **not** expose an `uninstall` action through
`installer_root.py`, the privileged Go request decoder, or the wizard.
No new way for an unprivileged process to authorize deletion is introduced.

## Scope and promises

Uninstall removes **only** the fixed, audited `install_core.MANAGED_PATHS`:
the installed agent executable and helper, systemd units and opt-in
drop-ins, and the Computer Host LAN Avahi service. Systemd service/socket
units are stopped and disabled before managed files are removed.

It deliberately **retains**:
- The persistent installation ID and control token in
  `/var/lib/linux-host-agent` (never copied to a public reply).
- The nonsecret v2 ownership record and `linuxhost` system account.
- Root-owned historical snapshots, the protected journal's parent, and
  the installed trusted root-helper bundle for later `-recover`.
- Operator-managed WOL configuration (`/etc/systemd/network/*.link`,
  NetworkManager profiles, NIC settings), firewall rules, and all
  unrelated services, directories and files.

The engine does not automatically unpair SmartThings; the device will
appear offline until manually removed or reinstalled.

## Transaction and recovery

1. Under the same validated manual-install mutex, confirm a real v2
   installation and reject legacy/v1, ambiguous and already-uninstalled
   states. No managed mutation takes place before a protected journal.
2. Begin an `uninstall` journal; advance through `INSPECTED` and `STAGED`
   with **no payload staging** (the fixed removal allowlist needs no source).
3. Snapshot every managed target and previous systemd state, fsync the
   snapshot, and durably publish `SNAPSHOTTED` and then `APPLYING`.
4. Preserve the nonsecret v2 owner marker. Stop/disable the power socket
   and agent service. Verify neither is active **before** unlinking files.
5. Remove only managed paths, sync their parent directories, reload
   systemd and verify files absent, both units stopped and disabled,
   owner marker retained, and private UUID unchanged.
6. Commit `VERIFYING → COMMITTED`, then clean the terminal journal.
   Postcommit cleanup failure is reported as
   `uninstalled_cleanup_required` (never rolled back).
7. If an operation fails before `APPLYING`, abort without managed
   changes. If it fails after `APPLYING`, restore the v2-validated
   snapshot and previous service state; mark rolled back **only after
   independent file and service verification**. If verification fails,
   preserve the journal for explicit recovery.

Existing `-recover` accepts `uninstall` journal records and restores
the same v2-validated snapshots. It cannot silently resume deletion.

## Remaining integration steps (subsequent PR)

- Add an explicit versioned root action with a dedicated minimal,
  fixed-schema uninstall request. Do not reuse free-form install options
  or allow unprivileged paths, commands, private identifiers or tokens.
- Add a separate uninstall wizard entry point requiring the literal
  `UNINSTALL` confirmation before administrator authorization, with
  an explanation of retained identity, backups and remaining root helper.
- Add Go/Python protocol and UI tests, including refusal without
  confirmation, v1/unknown installation, interrupted uninstall recovery
  and deliberately stopped units.
- Run a supervised reversible hardware acceptance test only after the
  backend and authorization boundary receive independent review.

## Independent release work

Persistent Wake-on-LAN is a **different** opt-in feature. The existing
`scripts/configure-wol.sh` already has separate NetworkManager and
systemd-udev paths, plus guards against shadowing a user's `.link`
policy. It must not be invoked from uninstall or install without its
own review, transactional handling of owned configuration, and
explicit consent. Additional public-release gates include a secure
power-key display, distribution smoke tests, documentation, and
independently authenticated release binaries.
