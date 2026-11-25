# Computer Host LAN — Linux installer (development only)

The standalone Go executable provides an interactive wizard, noninteractive
CLI and read-only inspection. Both modifying interfaces share a protected
Python transaction engine. This is **not a published or release-certified
installer**. Published v1.0.0-rc.2 continues to use the legacy shell installer.

Read the [current architecture](../docs/development/LINUX-INSTALLER-ARCHITECTURE.md)
for components, lifecycle, locks and trust boundaries; see the
[convergence contract](../docs/development/LINUX-INSTALLER-CONSOLIDATION.md)
and [release-authentication design](../docs/development/LINUX-INSTALLER-RELEASE-AUTHENTICATION.md)
for outstanding gates. A checksum beside an unsigned CI binary is not
publisher authentication. Do not elevate a downloaded unverified executable.

## Interactive wizard

Run as an ordinary user. Real installation uses an embedded inspector
by default and requests administrator authorization only after explicit
confirmation. Power management defaults to off on a new host and is
preserved on upgrade. Interface pinning is separate from persistent NIC WOL.

```sh
# Inert demo
./computer-host-linux-installer-test -preview
# Read-only inspection or interactive preview
./computer-host-linux-installer-test -live -preview -api ../scripts/installer-api.sh
./computer-host-linux-installer-test -live -api ../scripts/installer-api.sh
# Supervised installation/upgrade: type INSTALL
./computer-host-linux-installer-test -live -install
# Plain-text wizard with terminal su
./computer-host-linux-installer-test -live -install -accessible -elevation su
# Explicit recovery: type RECOVER
./computer-host-linux-installer-test -recover
# Journaled uninstall: type UNINSTALL
./computer-host-linux-installer-test -uninstall
```

Modifying examples are for supervised development on a reversible test host,
not production deployment. Authorization supports auto, sudo, doas, run0
and interactive su; no provider fallback after refusal. Demo and plain live
preview never elevate. Interactive live mode may browse mDNS via Avahi,
without contacting or pairing a hub. Uninstall verifies quiescence and
disablement before removing managed files; private identity/key, ownership
marker, account, snapshots and recovery helper are retained. Recovery reverses
an interrupted transaction or cleans terminal records, never resumes forward
work. When identity is verified, refresh an existing SmartThings device first.
Identity verification does not prove key equality; the key is not displayed.

The completion screen links to the existing driver channel, reminds users to
allow TCP 8765 (or their configured port) from the hub on a trusted private LAN,
and provides optional power setup instructions. If power is enabled and the
key is needed, an administrator can read the existing control token locally
with `sudo cat /var/lib/linux-host-agent/control-token`, or use
`run0 cat /var/lib/linux-host-agent/control-token` or
`su -c 'cat /var/lib/linux-host-agent/control-token'` (requires the root
password). Use a private terminal without logging or screen sharing.
In the SmartThings device settings, enter the 64-character value in
**Power control key (64 hex chars)** (`controlKey`) and turn on
**Enable shutdown/reboot/suspend** (`allowPowerCommands`).
Do not read or replace a key merely to upgrade an existing installation with
working power control. Monitoring-only installations do not need the key.
The wizard never reads, displays or copies the secret.

## Noninteractive CLI (development only)

The same standalone Go executable provides a strict, noninteractive command
interface. Use only a trusted test build on a reversible test host until
release authenticity (#84) and installer convergence (#101) are complete.

```sh
./computer-host-linux-installer-test cli --help
# Unprivileged, configurable plan (no authorization):
./computer-host-linux-installer-test cli plan --action upgrade --power preserve
# Examples for a supervised test with already-authorized sudo:
./computer-host-linux-installer-test cli install --confirm INSTALL --elevation sudo
./computer-host-linux-installer-test cli upgrade --confirm UPGRADE --power preserve --elevation sudo
./computer-host-linux-installer-test cli repair --confirm REPAIR --elevation sudo
./computer-host-linux-installer-test cli status --elevation sudo
./computer-host-linux-installer-test cli recover --confirm RECOVER --elevation sudo
./computer-host-linux-installer-test cli uninstall --confirm UNINSTALL --elevation sudo
```

Run as an ordinary user, not with sudo in front of the executable. The CLI
does not prompt for passwords: sudo/doas use noninteractive authorization
and run0 uses no-ask-password. Auto selects one available provider and
does not retry another after failure. It does not support su. Install,
upgrade and repair require the action to agree with the embedded read-only
inspection; the backend checks again under its lock. Default power is
preserve; enable/disable are explicit. Optional `--wol-interface IFNAME`
pins the agent interface only. No discovery, pairing, firewall or persistent
WOL change is performed. Recovery uses the already installed protected
helper, not a replacement payload. Status is privileged inspection and can
initialize the bootstrap coordination lock; it does not install an agent.

The `plan` action requires `--action install|upgrade|repair`, accepts the
same power/interface options as installation, and rejects confirmation and
elevation options. It uses the same embedded inspector and prospective
file plan, including action matching and prerequisite checks, and never
calls the privileged bootstrap. It may create and remove a private
temporary inspector directory, but does not modify managed files, services,
accounts, locks or network policy. A successful plan returns
`status: planned`, `planned_action`, and a nested validated read-only
`plan` object; privileged transaction state is unknown, runtime and
identity are not verified. A plan is not a reservation or authorization.

Once the read-only inspection has succeeded, plan and installation
preflight failures include the validated `checks` list (each entry has
a fixed `id` and `status`: passed, blocked, warning or not_verified).
For example, `systemd_pid1` with status blocked identifies a missing
systemd prerequisite. The list is also included in successful plans and
in validated installation replies. If inspection itself fails, checks
are omitted rather than invented. A plan failure retains the requested
`planned_action`. A list without blocked checks does not imply that all
preflight gates passed: action mismatch, interpreter consistency and
plan generation can independently fail. No raw error output is exposed.

Successful installation/upgrade/repair results and plans include
`preflight_network`: `avahi_prerequisites` is passed or not_verified;
`firewalld` is active or not_verified. Active firewalld may block TCP/8765;
not_verified does not mean inactive or safe. These observations are
pre-install prerequisites only, not verified discovery, firewall rules,
hub reachability or runtime state. Status, recovery and uninstall do not
probe these conditions. Successful installation results also include
`onboarding`: check_existing_device (identity verified, refresh first;
discover only if no device is registered) or check_or_discover (identity
not verified). Neither value verifies the retained control key or the
SmartThings registration.

Each option is a separate name/value pair, may occur only once, and is
valid only for the documented action. Missing or wrong confirmation is
an invocation error. There is no arbitrary source, Python override,
historical backup restore, retained-state adoption, persistent WOL
configuration or legacy shell fallback in this increment. Current published
shell instructions remain unchanged, including their read-only dry run.

Except for help, stdout is a single schema-version-1 JSON result containing
fixed operation/status/error, recovery/identity and optional validated plan,
preflight-network, checks and onboarding fields;
`secrets_included` is false. Empty strings mean no applicable or reported
value, not a verified negative. `privileged_transaction_state: "unknown"`
on a read-only plan means protected journal state was not inspected; it
is distinct from an empty field and from `none`. No raw privileged output
is copied.
Exit 0 means a completed operation (for status, transaction state none);
1 means failure or unknown outcome; 2 invalid invocation or root caller;
3 indicates an outstanding transaction (including an in-progress one)
or committed success with pending cleanup. A status result can be
successful with exit 3: its state is retained. Do not recover an active
transaction merely because status exited 3.

`preflight_failed` and `authorization_unavailable` are certain no-ops
with respect to privileged installation: preflight failed, no provider
could be selected, the executable could not be resolved, or the provider
process could not start. `outcome_unknown` means the caller lacks a
definitive result; authorization refusal after the provider started
(e.g. sudo -n) is one possible cause. No provider stderr is parsed.
Do not assume that nothing changed; inspect status and use explicit
recovery if indicated, rather than blindly repeating an installation.
For discovery, restrict TCP/8765 to the trusted LAN/hub and ensure Avahi
is installed/running; these are not modified by CLI commands.

## Regenerating the embedded bundle

The checked-in `bundle/` is generated from a fixed allowlist of authoritative
agent and script sources. After changing any of those sources, run from
`computer-host-lan/linux-installer`:

```sh
python3 sync_bundle.py
python3 sync_bundle.py --check
go test -run TestEmbedded ./...
```

Commit the generated changes together with the source changes. The generator
refuses unexpected bundle entries instead of deleting them, and `--check`
reports drift without writing. CI checks the generator and independently
runs the existing Go embedded parity tests. This is development tooling,
not a privileged installer step; never run it to repair an installed helper.

## Development and acceptance

From a current trusted checkout with Go 1.25.8 or compatible newer version:

```sh
cd computer-host-lan/linux-installer
python3 sync_bundle.py --check
go mod verify
go test ./...
go test -race ./...
go vet ./...
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -o computer-host-linux-installer-test .
# Unprivileged; no installation or hub discovery:
./computer-host-linux-installer-test cli plan --action upgrade
```

Choose install instead of upgrade on a host without a detected installation.
Plain read-only live mode requires an explicitly selected API launcher;
CLI plan uses the embedded inspector. External launchers must be trusted,
non-symlinked, executable and not group/world-writable. Output is bounded and
validated, with a 45-second outer timeout and 2-second pipe wait delay.

CI covers fixture/unit/race tests, formatting, static checks, embedded
parity, interactive PTY smoke, CLI argument smoke and disposable root-helper
status smoke. The Computer Host LAN Linux installer integration workflow
uploads the seven-day test-only artifact
`computer-host-linux-wizard-integration-test-only`. Check exact source
commit and successful workflow before development tests. Its adjacent
checksum checks transport integrity only.

For hardware acceptance record exact binary/source/agent versions, operator
consent, prior state, identity verification, service recovery and protected
transaction status. Gentoo/Btrfs lifecycle evidence does not certify final
release bytes or other distributions. No additional reboot, power loss,
network change or installation is implied by this document.
