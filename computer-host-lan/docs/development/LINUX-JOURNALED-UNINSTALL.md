# Journaled Linux uninstall — backend foundation

Status: **draft / backend-only**. This work extends the merged Linux
transaction engine. It does **not** expose an `uninstall` action through
`installer_root.py`, the privileged Go request decoder, or the wizard.
No new way for an unprivileged process to authorize deletion is introduced.

## Scope and promises

Uninstall removes **only** the fixed, audited `install_core.MANAGED_PATHS`:
the installed agent executable and helper, systemd units and opt-in
drop-ins, and the Computer Host LAN Avahi service. The agent and power
socket are stopped and disabled, and the socket-activated power-helper
service is explicitly stopped, before managed files are removed.

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
4. Preserve the nonsecret v2 owner marker. Disable and stop the power
   socket, explicitly stop the static power-helper service, and disable
   and stop the agent. Require successful commands and explicit systemd
   properties: all three units inactive, the socket and agent disabled,
   and the helper static or disabled **before** unlinking files.
5. Remove only managed paths, sync their parent directories, reload
   systemd and verify files absent, all three units not found and inactive,
   owner marker retained, and private UUID unchanged. Query errors,
   timeouts, incomplete state and unexpected unit states fail closed;
   a negative exit status alone is not evidence of inactivity.
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
The UI must explain that rollback has undone an interrupted uninstall
and that the user may explicitly retry. Historical snapshots remain
available after uninstall; a separate purge would need separate consent.

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
