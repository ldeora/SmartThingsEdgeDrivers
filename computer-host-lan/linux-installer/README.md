# Computer Host LAN — Linux installer (development only)

The standalone Go executable provides an interactive wizard, noninteractive
CLI and read-only inspection. Both modifying interfaces share a protected
Python transaction engine. This is **not a published or release-certified
installer**. Published v1.0.0-rc.2 continues to use the legacy shell installer.

Read the [current architecture](../docs/development/LINUX-INSTALLER-ARCHITECTURE.md)
for components, lifecycle, locks and trust boundaries; see the
[convergence contract](../docs/development/LINUX-INSTALLER-CONSOLIDATION.md)
and [release-authentication design](../docs/development/LINUX-INSTALLER-RELEASE-AUTHENTICATION.md)
for historical design. The current [release gates](../docs/release/V1-RELEASE-GATES.md)
record the unsigned, exact-source/checksum release decision and v1.2 deferral.
A checksum beside an unsigned CI binary is not publisher authentication.
Do not elevate an ordinary downloaded CI artifact.

## Interactive wizard

Run as an ordinary user. Launch without arguments to open the real
installation wizard on a clean host or the maintenance menu on an existing/retained host; `-accessible` opens its plain-text variant.
On ordinary interactive terminals, the maintenance chooser uses a full-screen
layout (minimum 64 columns by 22 rows). It displays the installed **file**
version, the bundled agent version and the observed service state. A newer
bundled version is recommended only when the installed file version can be
reliably compared. Arrow keys or fixed numeric keys highlight tasks; Enter
selects, Esc or Q exits. Unavailable tasks remain visible with an explanation.
Protected backup availability and recovery state are not guessed by the menu.
The full-screen chooser exits before invoking the existing operation wizard;
selecting a task is never authorization. `NO_COLOR` with a non-empty value
disables colors. Accessible mode and non-terminal/unsupported maintenance
streams retain the original plain prompts.

The interactive setup and preview use the same full-screen application frame
and color palette. The step sidebar appears at 100 columns or wider; narrower
terminals use a framed single-column form. The wizard needs at least 64 columns
by 22 rows and may require more rows for a detailed review. Resize if prompted,
or use `-accessible`. Input is paused while the complete current page cannot fit,
except for Ctrl+C cancellation. Text and backgrounds are paired explicitly.
Huh still controls the actual fields, validation and conditional pages.
The framed wizard presents concise keyboard hints from the active native
bindings; optional hints may be shortened to fit, but review text and
validation errors are not clipped. Enter selects or advances; Shift+Tab goes
Back when available. Review defaults to Continue, which is not authorization.
Q is not a quit shortcut in the wizard. The alternate screen closes before
the original typed confirmation and administrator authorization.
Inspect opens a scrollable, read-only snapshot of installation, service,
network and requirement observations, with a concise overview first. Verification limits are shown explicitly:
no runtime power/WOL test, private credentials or protected recovery inspection
is implied. Use Up/Down, PgUp/PgDn or Home/End to navigate; Enter, Esc or Q closes
the view and returns to the interactive maintenance menu. Plain inspection
retains its previous output and exit behavior.

Restore still requests administrator authorization to list private local
backups before opening the full-screen chooser. The list is newest first,
with the complete selected version, snapshot name, capture time, saved
service/power settings and coverage shown below. Up/Down, PgUp/PgDn and Home/End
navigate; Enter selects a backup for review, not restoration. The alternate
screen closes before the existing review and exact typed RESTORE confirmation.
Esc/Q cancels without restoring anything. Accessible maintenance and
unsupported terminal streams keep the original plain prompts. CLI behavior
and protected restore eligibility are unchanged.

Configure opens a framed task chooser. Recovery and Uninstall show a
concise review of what will change and what is retained, with Cancel selected
by default. Enter on Continue closes the full screen and opens the original
typed RECOVER or UNINSTALL prompt. No authorization occurs in the review.
Saved Wake-on-LAN retains the normal terminal's interface entry and authorized
check, then shows the validated policy status in a framed review. Cancel keeps
the policy; Continue still requires the exact REMOVE token before removal.
The optional post-uninstall WOL question remains separate. Plain accessible
maintenance paths and the machine-readable CLI retain their prior behavior.

Structured result screens and actual transaction progress remain separate
integration work.

The previous `-live -install` spelling remains supported.
Real installation uses an embedded inspector
by default and requests administrator authorization only after explicit
confirmation. Power management defaults to off on a new host and is
preserved on upgrade. Interface pinning is separate from persistent NIC WOL.

```sh
# Inert demo or simulated plan
./computer-host-linux-installer-test -demo
./computer-host-linux-installer-test -preview
# Read-only inspection or interactive preview (embedded inspector)
./computer-host-linux-installer-test -live -preview
./computer-host-linux-installer-test -live
# Supervised installation/upgrade: type INSTALL after review
# For retained rc.2 state, review and type REUSE instead
./computer-host-linux-installer-test
# Plain-text wizard with terminal su
./computer-host-linux-installer-test -accessible -elevation su
# Explicit recovery: type RECOVER
./computer-host-linux-installer-test -recover
# Journaled uninstall: type UNINSTALL
./computer-host-linux-installer-test -uninstall
```

For source-checkout diagnostics, explicit `-live` modes may still use
`-api ../scripts/installer-api.sh` as a trusted unprivileged inspector.
See the [rc.3 Quick Start](../docs/release/LINUX-INSTALLER-QUICK-START.md).
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
The unprivileged wizard never reads, displays or copies the secret. For
explicit retained-state reuse the protected controller validates its private
format and verifies continuity without displaying or copying it.

## Troubleshooting discovery and connectivity

The wizard's warnings reflect pre-install observations, not proof of
network reachability. A successful local agent health check does not prove
that the hub can reach it. The installer never changes firewall rules or
starts Avahi on your behalf. The commands below are manual administrator
actions; use your usual authorization method (sudo is shown as an example).

### Avahi / mDNS

Before installing the agent, check that the Avahi daemon is running:

```sh
systemctl is-active avahi-daemon.service
```

If Avahi is missing, install the daemon and browsing tools appropriate for
your distribution. Examples (choose only the applicable one):

- Debian/Ubuntu: `sudo apt install avahi-daemon avahi-utils`
- Fedora: `sudo dnf install avahi avahi-tools`
- Gentoo: `net-dns/avahi` (ensure the distribution's D-Bus and systemd
  integration is available).

On a trusted systemd host, if permitted by your local policy, enable and
start the installed daemon with
`sudo systemctl enable --now avahi-daemon.service`.
Install the prerequisites before running the agent installer: it only
installs the managed Avahi service file when `/etc/avahi/services` exists.
If you installed Avahi afterward, resolve any pending recovery first, then
rerun the verified installer. The interactive wizard automatically chooses
upgrade when it detects an existing installation. Alternatively, use the
documented `cli repair --confirm REPAIR` action with an already-authorized
noninteractive elevation provider (see below). Do not delete the retained
identity or SmartThings device.

After installation, verify the agent advertisement on the local network:

```sh
avahi-browse -rt _computerhost._tcp
```

Look for your computer and its expected address/port, not just any
Computer Host LAN agent. A local result does not establish that the hub
can see it. Keep multicast DNS (UDP 5353) available on the trusted
hub-facing network; guest isolation, VLANs or multicast filtering may
prevent discovery. Do not expose mDNS to untrusted networks.

### firewalld and other firewalls

If firewalld is active, inspect the runtime configuration as administrator:

```sh
sudo firewall-cmd --get-active-zones
sudo firewall-cmd --zone=ZONE --list-all
```

Replace `ZONE` with the zone that actually applies to the hub's traffic;
check the interface and any source-based zone assignments. Use the
agent's configured TCP port (default 8765) and the hub's actual IPv4.
For example, the following adds a **temporary, hub-scoped IPv4 rule**
for testing only. Replace both the example zone `home` and the reserved
documentation address `192.0.2.20` with your own values, and adjust the port
if necessary. Do not use this rule on an untrusted network.

```sh
sudo firewall-cmd --zone=home --add-rich-rule='rule family="ipv4" source address="192.0.2.20/32" port port="8765" protocol="tcp" accept' --timeout=5m
```

The rule expires after five minutes. If hub connectivity works, add
the same reviewed rule to the permanent configuration. Replace the zone,
hub IPv4 and port just as for the temporary rule:

```sh
sudo firewall-cmd --permanent --zone=home --add-rich-rule='rule family="ipv4" source address="192.0.2.20/32" port port="8765" protocol="tcp" accept'
sudo firewall-cmd --reload
```

Before reloading, review the permanent configuration and any unrelated
runtime-only rules: reloading replaces runtime policy with permanent policy,
which can remove other temporary rules and affect connectivity. Do not reload
until it is safe for your host. The temporary test rule is replaced by the
permanent rule, as intended. Verify hub connectivity again. Check runtime
and permanent policy separately; avoid copying unrelated runtime rules
into permanent policy. Reserve the hub's IP or update the rule if it changes.

Check mDNS separately on the trusted LAN (firewalld's `mdns` service may be
appropriate there). If using UFW, nftables or another firewall, apply
the equivalent hub-scoped rule using that firewall's own administration
tools. A missing firewalld warning does not mean the firewall is inactive
or that traffic is permitted. Do not disable the firewall, broadly open
the agent port or forward it to the Internet.

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
an invocation error. There is no arbitrary source, Python override
or legacy shell fallback in this increment.
Persistent WOL setup/removal, historical backup restoration and explicit retained rc.2 state reuse are
available for supervised development. Current published shell instructions
remain unchanged, including their read-only dry run.

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

### Reuse after an rc.2 uninstall

The read-only plan identifies retained state only as a candidate. If the
state is yours and belongs to a previous Computer Host LAN v2 installation,
type REUSE at the wizard confirmation, or use `cli install --confirm REUSE`
after reviewing `cli plan --action install`. The protected controller checks
quiescence, the private state layout and complete legacy v2 snapshot evidence.
The backup itself does not contain or prove association with the credentials.
Do not delete or regenerate private state, account or backups if reuse is
refused. Choose remote power again if needed; retain the existing key and
refresh the existing SmartThings device. Normal reinstall with the current
v2 owner marker continues to use the ordinary INSTALL path.

### Maintenance menu

Run the installer without flags as your normal user. On an existing installation
it opens Maintenance: Upgrade, Configure, Repair, Restore, Recover, Inspect,
Uninstall or Exit. Retained state without an installed agent offers reinstall
and the applicable maintenance tasks. A clean host still opens setup directly.
Configure → Change power or WOL settings reruns setup with the bundled agent
version; Configure → Check or remove installer-owned Wake-on-LAN does not
reinstall the agent. Repair also uses the bundled version. Inspect is read-only
and does not check the protected journal; use `cli status` for that. Restore
labels the newest eligible backup, not necessarily the last upgrade, and shows
the installed file version when safely readable. Each mutation still needs its
existing explicit confirmation. Existing flags and CLI commands work unchanged.

Menu keys are fixed (1 setup/upgrade, 2 Configure, 3 Repair, 4 Restore,
5 Recover, 6 Inspect, 7 Uninstall, 0 Exit). Options not displayed do not
apply. After an rc.2 uninstall, select 1 and REUSE before Restore; a
valid rc.3 owner marker permits restoration after normal uninstall.
Latest backup describes the before-state of an eligible operation, which
may have the same agent version. See [user journeys](../docs/release/UPGRADE.md).
