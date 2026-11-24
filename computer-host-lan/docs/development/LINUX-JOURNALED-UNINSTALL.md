# Journaled Linux uninstall — backend foundation

Status: **draft / integrated wizard**. PR #87 merged the root-side
transaction engine. The follow-up implements issue #89 with a standalone
`-uninstall` mode, literal confirmation and independent administrator
authorization. This is not a production release and no physical uninstall
has been authorized yet.

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

## Privileged request and user confirmation

- The standalone Go wizard requires a terminal, non-root UI execution,
  and a submitted literal `UNINSTALL` line after a clear scope/retention
  review. Any other response or EOF cancels. Other wizard modes cannot
  be combined with uninstall, including `-accessible` (the form is
  always plain text, just like recovery). Confirmation reads only the
  submitted line so that subsequent terminal input is not consumed before
  administrator authentication.
- The sole new request is `{"schema_version":2,"action":"uninstall"}`.
  Both Go and Python reject duplicates, extra fields (even null/empty
  installation settings), unknown versions and schema-v1 uninstall.
  The trusted Python handoff is required; the legacy status-only entry
  cannot authorize removal. Existing schema-v1 requests still work.
- The existing fixed-path root bootstrap validates and promotes its
  embedded trusted helper under the same locks; it refuses to replace
  a helper while recovery is pending. For uninstall, a fixed managed-agent
  path is checked under the shared installer lock before helper staging or
  promotion. A missing agent returns `not_installed` without creating a
  persistent helper or replacing a retained one; a pending transaction
  reported by an existing trusted helper takes precedence. Only temporary
  runtime locks may be created. An existing manually installed agent can
  still be considered for uninstall without a previous wizard helper; the
  Python backend independently checks v2 provenance under its own lock.
  No arbitrary source, network setting, command, ID, or path is accepted
  in the uninstall request.
- Results retain the schema-v1 envelope for compatibility. Both Go reply
  boundaries validate action-bound `uninstalled` and
  `uninstalled_cleanup_required` outcomes and fixed diagnostic enum
  values. No private identifier is relayed.
- Explicit recovery reports the fixed operation kind when available.
  It cleans terminal payload-free journals even if read-only status is
  `none`, and may retire a previous trusted helper only after a clean
  protected status check under the manual installer lock. Recovery may
  retain the newer trusted helper alongside the restored older agent;
  the helper and agent versions need not match. An interrupted
  uninstall rollback restores the installation and requires another
  explicit uninstall confirmation if removal is still desired.
- The physical uninstall/reinstall acceptance gate remains independent
  security review, green CI, and a supervised reversible test with
  verified backups. Do not test on a working host without approval.

## Independent release work

Persistent Wake-on-LAN is a **different** opt-in feature. The existing
`scripts/configure-wol.sh` already has separate NetworkManager and
systemd-udev paths, plus guards against shadowing a user's `.link`
policy. It must not be invoked from uninstall or install without its
own review, transactional handling of owned configuration, and
explicit consent. Additional public-release gates include a secure
power-key display, distribution smoke tests, documentation, and
independently authenticated release binaries.
