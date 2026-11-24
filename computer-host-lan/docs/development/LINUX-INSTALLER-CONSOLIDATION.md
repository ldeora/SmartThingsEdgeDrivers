# Linux installer consolidation — proposed stable-release contract

Related: #101, #84, #88, #98, #109. This records the intended architecture
and acceptance gates, not a completed migration or an available release.

## Decision

Use one protected transactional backend for supported Linux installation,
upgrade, repair, uninstall and recovery entry points. Retain a compatible
noninteractive interface for users who need it. The Go wizard is a
presentation/authorization/bootstrap layer, not a second installation
engine. The current published rc.2 shell installer remains supported for
that release with its documented limitations. Do not switch public
installation instructions to an unsigned test artifact.

## Current contract and migration obligations

| Existing path | Current semantics | Required transition |
| --- | --- | --- |
| install-agent.sh --dry-run | Unprivileged prospective plan; existing-state guard | Keep read-only; no account, lock, service, network or file mutation |
| install-agent.sh | Root shell preflight, v2 coexistence check, account creation, snapshot/apply/activate | Common protected controller; account creation only after durable APPLYING; explicit install/upgrade choice under shared lock |
| --enable-power / --disable-power | Explicit power choice; no flag preserves existing configuration | Preserve choice, monitoring-only default and existing service enablement |
| --python /absolute/path | Explicit Python selection | Preserve supported interpreter choice only within the reviewed trusted executable policy; explain refusal |
| --wol-interface IFNAME | Pins agent's interface, not persistent NIC WOL | Keep separate from persistent network changes; validate name and actual interface |
| --configure-wol | Explicit legacy post-install network effect outside transaction | Do not carry forward as an implicit callback; separate consent, supported protected WOL operation or clear refusal with no agent/network mutation from the unsupported request |
| --adopt-retained-state | Expert v2 adoption of ambiguous retained state | Separate explicit reviewed adoption path; never assume v2 identity or regenerate key; until implemented, documented refusal |
| uninstall-agent.sh --confirm | Explicit removal of managed files; retain state | Common journaled uninstall with verified quiescence, helper stop, disablement and retained private state |
| rollback-agent.sh --backup PATH | Explicit historical snapshot restoration | Distinct protected operation; cannot be substituted by -recover |
| Go -recover | Recover interrupted journal, never replay forward changes | Preserve fixed request, protected helper and terminal cleanup |

The legacy install shell currently creates the service user outside the
engine's lock/journal and can run configure-wol after installation. The
legacy core uses boolean systemctl exit-code observations and does not
have the wizard's journal, strict service verification or runtime gate.
These are meaningful differences, not equivalent implementations.

## Trust and entry points

The current root helper verifies its protected manifest and stages the
fixed payload under the common lock. A manifest calculated from the same
untrusted source tree is not independent publisher authentication. Review
how the shell entry point obtains a trusted release payload and how the
protected helper is installed, upgraded and invoked for both interactive
and noninteractive paths. Never run code from a writable source tree
merely because a previous root helper exists. Preserve #84, fixed request
validation, trusted Python selection, shared lock ordering and the
bootstrap recovery protocol. No new privileged protocol is authorized
by this document.

Historical snapshot restore must validate the old snapshot and the
current state separately, journal the current before-state, verify
service/file restoration and preserve recovery if interrupted. Restoring
an old snapshot is not the same as undoing the active transaction;
do not expose a new restore operation until old-helper compatibility,
snapshot provenance and recovery dispatch have been reviewed.

## Staged migration

1. Inventory supported shell options and document current behavior and
   refusal cases; pin tests before changing semantics.
2. Define a trusted command-line entry contract for ordinary installation,
   upgrade, repair and uninstall using the existing backend. Validate
   interpreter selection, retained identity, error codes, locks, journal
   and helper lifecycle on fixture roots. Keep dry-run unprivileged.
3. Implement explicit historical restoration and adoption only after
   separate review of their recovery semantics; unsupported requests
   fail before mutation. No silent legacy fallbacks.
4. Keep persistent WOL independent. Complete #98 and #88 before
   advertising automated persistent configuration; no unjournaled
   configure-wol callback in the unified engine.
5. Test actual CLI entry points, failed/missing systemd states, crash
   recovery, upgrades, uninstall/reinstall, identity/key preservation
   and noninteractive behavior. Qualify the authenticated release
   installer on Gentoo and additional supported distributions. Then
   update user-facing quick starts and packaging together.

The current release instructions remain unchanged until this work passes
review and physical acceptance. Neither this architecture decision nor
fixture tests authorize changing live network policy.
