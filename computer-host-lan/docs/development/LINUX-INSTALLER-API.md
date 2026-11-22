# Linux installer — experimental read-only JSON API

**Status:** implementation experiment; not yet a stable or privileged installer API.  
**Design contract:** [LINUX-INSTALLER-DESIGN.md](LINUX-INSTALLER-DESIGN.md)

This initial implementation provides safe, unprivileged discovery of basic
installation facts and an explainable preview of the exact **allowlisted
managed paths** that the existing `install_core.py` engine would change. It
does **not** implement an installation operation. It does not make service,
network, WOL or firewall changes, does not acquire sudo privileges and does
not read private installation UUID, HMAC control token or root-private backup
and transaction contents.

## Usage from the source checkout

From `computer-host-lan/` (Python >=3.10, no external dependencies):

```sh
python3 scripts/installer_api.py inspect
python3 scripts/installer_api.py plan
python3 scripts/installer_api.py plan --enable-power
python3 scripts/installer_api.py plan --disable-power --wol-interface enp1s0f0
```

Both commands emit **one JSON object to stdout**. Invalid/unsafe requests emit a
minimal JSON error with a stable code to stderr and exit 2. The output includes
`schema_version: 1`, `mode: "read_only"`, and the requested operation. The
client must check schema and error codes rather than parsing human-readable
strings. Neither operation accepts a path to arbitrary executable code or a
root helper.

### Inspect schema (fields and semantics)

- `checks`: systemd active-init detection, Python >=3.10, required commands,
  Avahi advertisement file presence and managed-path safety.
- `installation.detected`: **only** whether the app-owned service file is
  present; not proof of a working agent or an intact installation.
- `installation.agent_service_state`: best-effort, read-only
  `systemctl is-active` result; can be `unknown`.
- `installation.service_file`, `power_dropin`,
  `avahi_service_file`: presence/absence or unsafe/unreadable. Presence
  does not prove that the content is valid.
- `privileged_transaction_state: "unknown"`: deliberately **not**
  inferred by trying to read private journals or backups.
- `identity_preserved: "not_verified"` and `secrets_included: false`.
  No credential display or identity validation is attempted.

### Plan schema (fields and semantics)

- `changes`: array of `{path, action}`, where the path comes from the
  current `install_core.MANAGED_PATHS` allowlist and the action is one of
  `create`, `replace`, `remove`, `unchanged`. No paths outside the
  existing engine allowlist are proposed.
- `power_option`: `preserve` (default), `enable`, or `disable`.
- `wol_interface_requested`: only whether a drop-in was requested. It
  does **not** configure physical WOL hardware.
- `runtime_verified: false` and `changes_applied: false` in every plan.

The plan is prospective; it does not compare existing and candidate file
contents to assert an upgrade is a no-op, and it does not validate actual
hardware support, real hub pairing, port reachability, or post-upgrade health.
A production wizard must not treat this preview as authority to write system
files. The existing `scripts/install-agent.sh` remains the supported manual
install path.

## Security boundary

The CLI does not accept `--root` or `--source` options. Internal Python
functions accept an alternate `root` for **unit fixtures only** and call
`InstallTransaction.refuse_links` before examining managed paths. This is
a non-privileged convenience check, **not** a substitute for privileged
directory-fd/no-follow validation of a root-owned transaction, which remains a
separate future milestone. Executing a copied source checkout under sudo is
not a supported invocation of this API.

When `inspect` reports `unknown`, the wizard must display **unknown**, not
`none` or `no recovery needed`. An eventual privileged read-only status
helper will return only the spec's allowlisted transaction-state categories.

## Testing

Tests in `tests/test_installer_api.py` run under the existing Linux CI matrix
(Python 3.10–3.14) alongside `test_installer_v030.py` and the existing agent
regression tests. They use temporary fake filesystem roots and do not mutate
real `/opt`, systemd, Avahi, WOL or persistent credentials.

## Deferred before any production install

- Protected read-only transaction status with a trusted root-owned helper.
- Root-owned/staged, independently authenticated installer payload.
- Durable transaction journal and next-run recovery.
- Proper install configuration state machine, including preserved custom port.
- Post-install HTTP version/protocol/UUID and systemd health verification
  performed before transaction commit.
- Real SmartThings discovery/onboarding and hardware/distro acceptance.

This document intentionally **does not** claim that those operations work.
