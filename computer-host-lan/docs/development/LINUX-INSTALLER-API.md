# Linux installer — experimental read-only JSON API

**Status:** preliminary implementation; no privileged installer operations.  
**Design contract:** [LINUX-INSTALLER-DESIGN.md](LINUX-INSTALLER-DESIGN.md)

These commands report limited compatibility facts and prospective changes to
the existing `install_core.py` managed-path allowlist. They **do not** install,
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
`operation` value (`inspect`, `plan`, or `unknown` for malformed
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

Neither operation claims SmartThings hub discovery/pairing, TCP reachability,
firewall correctness, custom-port support, or successful agent service health.
The existing `scripts/install-agent.sh` remains the supported manual installer.

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

The tests in `tests/test_installer_api.py` use temporary fake roots and
stubbed interpreter candidates for deterministic checks, and explicitly mock
host systemd access. The test suite is automatically run by
`.github/workflows/computer-host-linux.yml` on Python 3.10–3.14 and in
container smoke jobs. The new `scripts/installer-api.sh` is shell-syntax
checked by existing CI.

## Deferred before a privileged installer can ship

Protected transaction-state helper; authenticated and root-owned bundled
payload staging; crash-safe transaction journal/recovery; preservation of
custom ports and systemd enabled/stopped intent; post-install HTTP
protocol/version/identity verification; real SmartThings hub discovery and
hardware/distribution acceptance. This API does **none** of those tasks.
