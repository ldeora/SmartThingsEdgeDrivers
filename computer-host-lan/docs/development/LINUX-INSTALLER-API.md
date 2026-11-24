# Linux installer — experimental read-only JSON API

> **Historical design note:** Describes the implementation at its original milestone. For current behavior, see [Linux installer architecture](LINUX-INSTALLER-ARCHITECTURE.md).
>
> **Current v1.0 cutover:** The legacy `install-agent.sh` source entry point is now read-only/dry-run only and refuses installation. Published rc.2 instructions remain version-bound; the authenticated Go wizard/CLI is the intended v1.0 entry point but is not yet release-qualified.

**Status:** preliminary implementation; no privileged installer operations.  
**Design contract:** [LINUX-INSTALLER-DESIGN.md](LINUX-INSTALLER-DESIGN.md)

These commands report limited compatibility facts, prospective changes and
optional **live loopback verification** for the existing v2 Linux agent.
They **do not** install,
repair, upgrade, remove, elevate, access credentials, inspect root-private
journals/backups or change any service, WOL setting, firewall or network state.

## Usage from a checked-out source tree

Use the POSIX launcher on all systems, **including those whose default
`python3` is Python 3.9 but which have Python 3.10+ available**:

```sh
sh scripts/installer-api.sh inspect
sh scripts/installer-api.sh plan
sh scripts/installer-api.sh inspect --python /usr/bin/python3.11
sh scripts/installer-api.sh plan --python /usr/bin/python3.11
./scripts/installer-api.sh plan --python=/usr/bin/python3.11
sh scripts/installer-api.sh plan --enable-power
sh scripts/installer-api.sh plan --disable-power --wol-interface enp1s0f0
sh scripts/installer-api.sh verify
sh scripts/installer-api.sh verify --port 8765 --expected-version 0.4.6-rc.2
```

The wrapper is committed as **executable (Git mode 100755)** and can be\ninvoked directly by the Go wizard or via \`sh\`. Both \`--python /path\` and\n\`--python=/path\` are accepted. Its errors use the Python API's exact\ncompact, sorted-key JSON layout.\n\nThe wrapper sources the **same** `scripts/python-selector.sh` used by
`install-agent.sh` and `preflight.sh`, and launches the selected interpreter
without modifying the system `python3` symlink. The Python API also selects
that interpreter for inspection and planning, rather than interpreting its own
`sys.version_info` as proof that a valid agent interpreter was found. An
explicit `--python` must be an existing executable absolute path to Python
3.10+ using the shell selector's restricted path syntax (no spaces).
The directly invoked Python script requires Python 3.10+ to run; use the
launcher for cross-distribution compatibility.

### JSON-only contract

Each successful operation prints **one JSON object on stdout**, exits 0,
and prints no other output. Errors print **one JSON object on stderr**, with
no paths, user input or exception details, and exit 2 for expected problems
(or 1 for unexpected internal errors). Even missing subcommands, unknown
subcommands and unsupported options use JSON, not argparse usage text.
`--help` is an intentional human-readable help request, not an error response.

All results include `schema_version: 1`, `mode: "read_only"`, an
`operation` value (`inspect`, `plan`, `verify`, or `unknown` for malformed
invocations), and either a response body or an `error.code`.

| Error code | Meaning / wizard treatment |
| --- | --- |
| `invalid_argument` | Invalid CLI arguments, conflicting power options, invalid/missing WOL interface, invalid `--python`. Offer correction. |
| `unsafe_managed_path` | Existing managed file/path is linked or not safely inspectable. **Stop** and request human review. |
| `source_unavailable` | The checked-out installer source/required templates are unavailable or cannot produce the plan. Check the bundle. |
| `prerequisite_missing` | No compatible Python selected or the selector could not run. Show dependency remediation. |
| `internal_error` | Unexpected API failure. Stop; do not attempt installation. |

Never turn an error into a successful plan, attempt a privileged operation,
or parse human wording in place of the code.

### Inspect response

The `checks` array contains `passed`, `blocked`, `warning` or
`not_verified` statuses for Linux, the **installer-selected** Python >=3.10,
systemd active init, required tools, Avahi readiness and managed-path
inspection. It may additionally report managed-file visibility as unverified.

- `python.selected_interpreter`: the interpreter chosen by the *actual*
  shell selector, or null. `python.version_supported` reflects that result.
- `avahi.services_directory`: whether `/etc/avahi/services` exists.
  `avahi.daemon_state`: read-only `systemctl is-active avahi-daemon.service`
  result where available. The **`avahi_discovery` check** passes only if
  the directory exists **and** the daemon is active; it warns if the directory
  is absent or the daemon is inactive/failed, otherwise reports `not_verified`.
  No installed agent Avahi file is required on a **fresh installation**.
- `installation.detected`: the managed systemd service file appears present;
  **not** proof of a healthy installed agent.
- `installation.service_file`, `power_dropin`,
  `avahi_service_file`: managed-file presence/absence/safety status.
  These are app-owned-file checks, **not** Avahi readiness.
- `installation.agent_service_state`: read-only `systemctl is-active` where
  supported; `installation.agent_service_enabled`: separate read-only
  `systemctl is-enabled`. An absent unit is reported as `detected: false`
  with service states `unknown`, rather than presenting `inactive` as
  proof that an agent was installed. Service states remain `unknown` if the
  unit is inaccessible or no live systemd can be queried.
- `privileged_transaction_state: "unknown"`: the unprivileged API
  does not inspect protected transaction journals or backups.
- `identity_preserved: "not_verified"`, `secrets_included: false`:
  no credential access or identity validation is attempted.

### Plan response

`changes` is an array of `{path, action}` generated by the existing
`install_core.generate_plan` and constrained to `MANAGED_PATHS`. Actions
are `create`, `replace`, `remove`, `unchanged`. The plan does not compare
file contents to prove the absence of an update.

`selected_python` is the same selector result that the real installer would
use for its systemd unit, not `sys.executable`.
`power_option` defaults to `preserve`; WOL is opt-in, and
`wol_interface_requested` means only that an existing interface under
`/sys/class/net` passed the **same name-and-existence checks** as
`install-agent.sh`. This is **not proof of a physically wired interface
or WOL hardware support**. The plan doesn't make persistent WOL changes.
`runtime_verified` and `changes_applied` always remain false.

### Verify response (read-only runtime health; NEW)

`verify` is an explicit, bounded check of a **running local v2 Linux agent**.
It only connects to **127.0.0.1** using a fixed pair of HTTP paths
(`/v2/info` and `/v2/health`), requires JSON HTTP 200 responses, and
rejects redirects, non-JSON data and responses exceeding **16 KiB**
(with at most **8 KiB of HTTP headers**). A fixed **3-second absolute
deadline per request**, including connection and response headers/body,
prevents a slow-drip listener extending per-read timeouts. It probes the managed
agent systemd unit with `is-active` when systemd is available. No root
privileges are needed or requested. **This deadline is per HTTP request,
not for the entire `verify` operation:** two requests may use up to 6 seconds,
and the systemd probe up to another 3 seconds, plus launcher overhead. Future
Go wizard integration must budget for the full operation (the existing
read-only Go subprocess budget is 45 seconds) or introduce a shared deadline.

- `--port` defaults to **8765**, permits 1024–65535, and is the *only*
  connection target control. There is **no arbitrary URL, hostname or
  remote-IP option**. This is a read-only probe; it does not change service
  listening port or persisted settings. It works with the shipped agent
  listening on `0.0.0.0` (including loopback); a future LAN-only bind address
  would require a separate, explicitly designed local verification path.
- `--expected-version` is optional and compares an allowlisted version
  against the running agent. The future privileged installer will supply
  its version from the **trusted bundled payload**, not a user's guess.
- `status` is `passed`, `failed` or `not_verified`; corresponding
  `runtime_verified` is true only on `passed`. A successful JSON API
  invocation may return `status: "failed"` with exit code 0: **callers
  must inspect the result**, not just process exit code.
- The result includes service readiness, matching v2 protocol/API/platform,
  matching **private UUID between the two HTTP responses**,
  sanitized `agent_version` (a bounded version string or JSON `null`),
  and reported power-control state. Regression tests ensure malformed
  agent-supplied version objects, oversized strings or UUID values are
  **never echoed**, even when verification fails. The advertised power
  actions are checked against the shipped v2 agent's allowed actions by CI.
  The UUID itself, hostname, MAC, address, boot ID, token, nonces, raw
  response and network errors are **never included**.
- When the API was not supplied an already-trusted expected UUID,
  `identity_preserved` is deliberately **`not_verified`**. The
  unprivileged `verify` command has no expected-UUID option and never
  reads `/var/lib/linux-host-agent`. A malicious local listener can
  emulate these endpoints; this probe is **not authentication** or proof
  the real SmartThings hub can connect.
- The separately testable `runtime_verify.verify_runtime()` Python
  function supports **in-memory** expected UUID, version and power-option
  comparisons for future trusted post-activation checks. Those inputs
  must originate in the privileged transaction and must not be printed,
  passed via process arguments, or exported in ordinary inspection JSON.
- An intentionally stopped/disabled service is **not an installation
  failure**: the future transaction engine must verify expected
  stopped state and installed-file integrity separately, rather than
  waking the service merely to pass a live HTTP probe.

`verify` cannot install, pair, fix firewall rules, establish hub
reachability, or inspect protected credentials. The legacy
`scripts/install-agent.sh` is no longer a supported mutation path in
current development source; it refuses installation. The runtime verifier
has **not yet been integrated as a commit gate** in `install_core.py`;
that requires protected transaction/recovery handling. Existing `inspect`
and `plan` schema fields remain unchanged.

## Platform and security limitations

- A non-root report is advisory. Root-owned transaction status requires a
  **separate privileged read-only helper** and will not be inferred by probing
  root-private state. The status must remain `unknown` until that exists.
- The API uses the existing `InstallTransaction.refuse_links` policy.
  **Symlinked ancestor directories are rejected** even when they are a
  legitimate OS layout, for example immutable/image-based systems that link
  `/opt` to `/var/opt` (Fedora Silverblue). This limitation exists in the
  current installer too and must be addressed together with the protected
  root-side path-resolution policy, **not** worked around in the read-only API.
- The API does not accept `--root` or `--source` command-line parameters.
  Internal `root` and `source` injection are strictly for fixture testing.
  Read-only checks are not authority to run code as root from a writable tree.
- The interpreter selector executes candidate Python interpreters in a
  read-only version probe, just as the existing installer does; it does not
  install Python packages or modify the system default.
- No accidental output of raw paths, CLI arguments, control keys, UUIDs,
  backup contents or exception stack traces in error JSON.

## Testing

The tests in `tests/test_installer_api.py` and
`tests/test_runtime_verifier.py` use temporary fake roots, mocked HTTP
responses, a disposable IPv4 loopback listener for the hard-deadline
regression and stubbed interpreters; real host systemd access is mocked. The test suite is automatically run by
`.github/workflows/computer-host-linux.yml` on Python 3.10–3.14 and in
container smoke jobs. The new `scripts/installer-api.sh` is shell-syntax
checked by existing CI.

## Deferred before a privileged installer can ship

Protected transaction-state helper; authenticated and root-owned bundled
payload staging; crash-safe transaction journal/recovery; preservation of
custom ports and systemd enabled/stopped intent; **integration of this
read-only verifier into a privileged post-activation commit gate with
trusted identity checks**; real SmartThings hub acceptance and
hardware/distribution validation. This API does **none** of those privileged
operations.
