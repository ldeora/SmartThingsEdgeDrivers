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
| permanent_mac_match | Whether ethtool's reported permanent address equals the current address |
| backend | Observed active NetworkManager profile, observed systemd-udev link selection, or not_verified |
| nm_profile_policy | Explicit profile flags: magic, magic_with_other_flags, other_flags, none, default, ignore, not_verified |
| observed_link | Origin of the last udev-selected base link (local, runtime, local_vendor, vendor, not_verified) |
| base_link_policy | Declaration in that selected base file only: magic_declared, other_declared, unspecified, not_verified |

The probe always reports `changes_applied: false`,
`persistence_verified: false` and `secrets_included: false`.
A magic declaration is **not** proof of merged or future effective policy.
It does not resolve drop-ins, masks, ordering, matching, global NM settings,
SecureOn, driver/firmware behavior, or changes made since the last device
initialization. An active NM daemon with no verifiable active connection
for the selected NIC is ambiguous; it must not silently select the udev
backend. All unavailable probes remain unknown rather than assuming disabled
or unsupported. The probe does not execute `udevadm test-builtin`, change
the current WOL flag, or restart networking.

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
2. **Policy planning:** Determine the actual effective policy and conflicts.
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
