# Persistent Wake-on-LAN: read-only inspection and integration plan

Issue #88. This first increment deliberately does **not** configure Wake-on-LAN,
add a privileged request, modify the installation journal, or change the
existing manual `configure-wol.sh` behavior. The reviewed installer lifecycle
remains unchanged.

## Development probe

From the Computer Host LAN source directory, as a normal user:

```sh
python3 scripts/wol_inspect.py --interface enp1s0f0
```

Only if the hardware fields report `not_verified` because of ethtool
permissions, repeat from a reviewed trusted checkout with administrator
authorization. This is a diagnostic, not an installer or a request for
network changes. Do not run an untrusted checkout as root.

The bounded, redacted JSON uses fixed enums and never includes the interface
name, MAC address, NetworkManager connection UUID, profile contents, link
path, SecureOn password, or raw command output.

| Field | Meaning |
| --- | --- |
| interface_state | Physical Ethernet evidence, unsupported/invalid interface, unknown or changed during inspection |
| magic_packet_support | Supported, unsupported, or not_verified from both ethtool WOL lines |
| runtime_magic_packet | Current magic-packet flag, independent of persistence |
| hardware_query | Default ethtool or legacy ioctl fallback, otherwise not_verified |
| default_query_status / ioctl_query_status | verified, query_failed, incomplete_or_invalid, or not_attempted; a failed command is not proof of missing capability |
| permanent_mac_match | Whether ethtool's reported permanent address equals the current address |
| backend | Observed active NetworkManager profile, observed systemd-udev link selection, or not_verified |
| networkmanager_state | active, inactive, unexpected_state, or not_verified; active alone does not establish interface ownership |
| nm_profile_policy | Explicit profile flags: magic, magic_with_other_flags, other_flags, none, default, ignore, not_verified |
| observed_link | Origin of the last udev-selected base link (local, runtime, local_vendor, vendor, not_verified) |
| observed_link_dropins | present if udev reports nonempty ID_NET_LINK_FILE_DROPINS; not_reported if absent/empty, not_verified if the observation is invalid or unavailable |
| base_link_policy | Declaration in the selected base file only: magic_declared, other_declared, unspecified (including an empty WakeOnLan=), not_verified; suppressed if drop-ins are reported |

The probe always reports `changes_applied: false`,
`persistence_verified: false` and `secrets_included: false`.
A magic declaration is **not** proof of merged or future effective policy.
A nonempty observed drop-in property suppresses base-file WOL evidence;
not_reported does not establish that drop-ins are absent on disk or that
an older udev exposes them. No drop-in contents or paths are emitted.
NetworkManager flags may be numeric, named, or comma-separated names;
numeric annotations must agree with the flags, and contradictory special
flags, duplicates and unknown names remain not_verified.
It does not resolve drop-ins, masks, ordering, matching, global NM settings,
SecureOn, driver/firmware behavior, or changes made since the last device
initialization. An active NM daemon with no verifiable active connection
for the selected NIC is ambiguous; it must not silently select the udev
backend. All unavailable probes remain unknown rather than assuming disabled
or unsupported. The per-command WOL diagnostics distinguish an unsuccessful
query from successful but incomplete/invalid output; they intentionally do
not infer whether an error was caused by permissions, driver support, tool
availability, an old ethtool version or timeout. The probe does not execute `udevadm test-builtin`, change
the current WOL flag, or restart networking.

## Development policy planner

The next increment adds a separate development-only read-only command:

```sh
python3 scripts/wol_plan.py --interface enp1s0f0
```

It combines the same redacted inspection with additional systemd policy
evidence. Run it first as a normal user. Where hardware capability cannot
be retrieved, use the already reviewed trusted checkout with administrator
authorization for a read-only comparison. No configuration is applied.

The planner inventories the supported systemd network directories in
same-basename priority order. A standard merged-/usr alias is recognized;
ambiguous distinct legacy vendor directories, unsafe paths, unreadable
files and excessive inventory sizes are not verified. Empty files and
`/dev/null` masks are recognized. The observed udev base file must be
the current same-name winner. Earlier effective rules are considered
potentially matching unless they contain a single literal permanent MAC
match for a different NIC. A current-MAC mismatch alone is not enough
to exclude an earlier rule at the next boot. Any potentially relevant
drop-in directory or reported drop-ins defers policy evaluation, even
if the directory is empty or the file is masked. The planner deliberately
does not implement general systemd matching, drop-in merging, or
re-evaluation of device initialization; a consistent observed base
rule is only limited evidence, not proof of future effective policy.
It does not execute udev test builtins. Re-read the udev selection
and interface identity after inspection; concurrent policy changes
still require a fresh protected check before a future write.

The plan exposes fixed enums only. In particular, it emits no writable
target, command, raw profile, MAC, filename, password or old/new value.
`automatic_changes_allowed`, `changes_applied`,
`persistence_verified` and `secrets_included` are always false.
The nested `inspection` is evidence, not authorization.

| Recommendation | Interpretation |
| --- | --- |
| preserve | Observed explicit magic policy and enabled runtime flag; leave it alone, not proof that wake will work after reboot |
| verify_hardware | Missing hardware information; a trusted administrator check may help |
| unavailable | Unsuitable/unverified interface or explicitly unsupported magic packets |
| review_runtime | Existing magic declaration differs from runtime; investigate, don't rewrite policy |
| review_nm_add_magic | Explicit NM flags lack magic; candidate for further review, never authorization to replace flags |
| review_link_dropin | Local single literal permanent-MAC rule with unspecified WOL and no observed precedence conflict; consider scoped drop-in only after additional checks |
| manual_review | Ambiguous ownership, identity, SecureOn, explicit conflicting/default/ignore policy, shared/complex rule, drop-ins, or unsafe paths |

The link evidence fields distinguish `base_rule_observed`,
`selection_changed`, `earlier_rule_requires_review`,
`dropins_require_review`, and `not_verified`. Scope can be
`permanent_mac`, `current_mac`, `shared_or_complex` or
`not_verified`. A SecureOn declaration or runtime flag requires review;
no password is emitted. Existing runtime-only and /usr/local vendor
policies are not treated as stable persistent configurations. The
observed base declaration is compared with the later read, but this
is not an atomic snapshot of network configuration.

A NetworkManager candidate is deliberately advisory: before any future
transaction, resolve the exact numerical old flags and proposed flags,
prove the profile is persistent and bound to the intended NIC (not
shared across devices), check password/SecureOn status, verify actual
active manager and profile identity, obtain explicit separate consent,
and revalidate under lock. Existing combined magic flags must remain
unchanged. Explicit none or other flags may be intentional; no
automated addition may happen merely because this planner suggested
review. DEFAULT and IGNORE require manual review rather than an
automatic override of global policy.

Likewise, a systemd drop-in candidate is not an approved file operation.
A future transaction must confirm the same exact permanent-MAC match,
supported systemd semantics, file and directory ownership, lack of
conflicting policies or credentials, exact before-state, and a
no-clobber owned destination. Current-MAC-only rules are not write
candidates. A shared/default rule cannot be modified for one NIC by
adding a shared drop-in; creating a competing first-match rule could
lose unrelated settings. Generic/default configurations therefore
require manual review in this increment. Broader safe support for
these common configurations is a separate design/review gate, not
silently handled by a new .link rule.

Physical Gentoo inspection from #93 established that ethtool 7.0
may return success without WOL lines when unprivileged, and that
both default and ioctl queries report the expected flags with
administrator authorization. The planner must preserve the existing
local WOL policy in that configuration, provided the additional
inventory checks find no ambiguity. A read-only NetworkManager
hardware comparison remains necessary before a writable NM path.

## Why this is separate from the manual script

The existing script's per-MAC rule detection only checks a narrow textual
pattern. systemd selects the first matching .link in lexical order; even
an apparently WOL-only new file could shadow unrelated naming, MAC, MTU
or other link settings. Drop-ins and higher-priority directories must also
be considered. The current script's NetworkManager modification sets
magic rather than preserving a potentially combined flag set.

References:
- https://www.freedesktop.org/software/systemd/man/latest/systemd.link.html
- https://networkmanager.dev/docs/api/latest/nm-settings-nmcli.html

## Next integration stages

1. **Review and real-hardware evidence:** Run the probe without privileges
   and, where necessary, using a trusted root copy on the existing Gentoo
   setup and on a NetworkManager-managed Ethernet connection. Verify
   classification and redaction without applying changes.
2. **Policy planning (this increment):** Collect conservative precedence and conflict evidence; defer complex effective-policy evaluation.
   Never create a first-match .link that shadows an existing rule. Consider
   a narrowly scoped supported override only if unrelated semantics are
   preserved; otherwise refuse automatic configuration and give manual
   guidance. For NetworkManager, snapshot the exact persistent flags and
   profile identity; preserve existing flags and explicit default/ignore
   semantics unless a specific separately authorized transition is safe.
   Treat SecureOn and ambiguous ownership as outside the automatic path.
3. **Protected transaction:** Design a dedicated opt-in WOL transaction
   with a fixed allowlist, independently validated interface identity,
   revalidation under lock, durable before-state record, protected recovery
   and exact postcondition checks. Do not widen the existing managed-path
   allowlist to arbitrary network files. No fire-and-forget shell call.
   Distinguish persistent change from runtime change, and restore both if
   the operation applies either; never bounce the interface or modify routes.
4. **Wizard consent:** Offer WOL as an independent decision, not implied
   by power control or a pinned NIC. Display what changes, what is retained,
   and what needs reboot verification. Do not expose credentials or private
   identifiers in structured replies. Default to no network changes.
5. **Acceptance:** Fixture tests for both backends and conflict/rollback
   paths; supervised Gentoo and NetworkManager hardware tests, reboot and
   magic-packet wake only after explicit approval.

The existing agent uninstall retains external WOL policy. Any later cleanup
of an installer-owned WOL configuration must be explicit, ownership-aware,
and separately reviewed.
