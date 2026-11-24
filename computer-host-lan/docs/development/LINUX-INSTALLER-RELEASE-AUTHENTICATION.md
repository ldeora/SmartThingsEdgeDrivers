# Linux installer release authentication — design for #84

**No attested release exists yet.** PR #164 merged the protected handoff.
The dedicated manually dispatched tag workflow implements the build,
attestation, verification and optional draft-only staging policy below.
It is not enabled by the current rc.2 manifest. Nothing in this document
authorizes a release tag, publication, or changes to existing RC assets.

Use GitHub public-repository artifact attestations (Sigstore-backed build
provenance) for the standalone Linux installer. Unlike a checksum shipped
alongside the executable, a signed provenance statement binds the digest to
an authenticated workflow and source revision. This is provenance, not proof
of code safety.
References: [GitHub artifact attestations](https://docs.github.com/en/actions/concepts/security/artifact-attestations),
[verification CLI](https://cli.github.com/manual/gh_attestation_verify).

## Build and publication policy

Dedicated workflow: .github/workflows/computer-host-linux-attested-release.yml.
No automatic push, PR or fork signing. The release gate checks the repository
name and ID, dispatch event, first run attempt, exact independently supplied
tag and full commit, lightweight tag and current main head, and the manifest.
Only v1.0.0 or v1.0.0-rc.3 and later v1.0.0 RCs are eligible. Release prep
must explicitly set `release_stage` to `attestation-ready-v<VERSION>`
and `release_candidate_tag` to the exact tag, including for stable v1.0.0.
The published rc.2 metadata is deliberately unchanged.

Require the latest exact-commit main push/dispatch runs of all five named
Linux, Windows, Inno, release-packaging and Go installer workflows to be
successful with all expected jobs successful. PR checks alone are not
sufficient. The Go installer CI now supports manual dispatch, so dispatch
any missing workflows on main after final release preparation and review.
No existing release (including draft) for the tag is allowed.

Two clean GitHub-hosted ubuntu-24.04 jobs build linux/amd64 with Go 1.25.14
(the exact patch observed in the successful #164 CI, newer than the minimum
1.25.8 in go.mod), GOTOOLCHAIN=local, CGO_ENABLED=0, GOAMD64=v1, no action
cache, verified modules and embedded bundle, tests and vet. Reevaluate the
pinned Go patch and action commits before release. Build with -mod=readonly
-trimpath -buildvcs=true and require clean VCS status and exact revision.
The attesting job compares both binaries and build information byte-for-byte.
No reproducibility claim until a real run passes.

Only the attesting job has id-token and attestations write permissions.
The verification job downloads the candidate on a separate runner and
uses gh to enforce repository, workflow, source ref, source and signer
digest, GitHub-hosted runners and SLSA provenance predicate. It rejects
modified bytes, wrong repo/workflow/ref/source digest and repeats the
positive check. The altered bytes also exercise the no-attestation case.

### Maintainer configuration and explicit dispatch (not performed yet)

Before the first real dispatch, protect reviewed main and release tags
against unapproved creation, updates and deletion using repository rules.
The gate checks live refs, not the completeness of repository rulesets;
administrators must configure and independently verify those controls.
No retagging. Keep main at the approved commit for this release operation.

Create the GitHub environments `computer-host-linux-attest` and (only
if draft staging is desired) `computer-host-linux-draft`. For each:
configure required reviewers, prevent self-review, disable administrator
bypass, and allow only the exact approved release tag using selected
deployment tags (no branch or wildcard). An independent authorized
reviewer is required; if the repository cannot provide one, stop rather
than weakening the policy. The gate checks reviewer rules, tag policy
and the recorded independent approval after the environment gate. The
repository owner must confirm admin bypass and tag protection separately.
API errors, missing settings, incomplete CI and absent approvals fail
closed. No settings are automatically created or altered by this PR.

After approval of a future release-prep commit, complete all exact-commit
CI and create the approved lightweight tag under the configured rules.
Example commands (placeholders, not authorization):

```sh
gh workflow run computer-host-linux-attested-release.yml \\
  --ref EXPECTED_APPROVED_TAG \\
  -f expected_tag=EXPECTED_APPROVED_TAG \\
  -f expected_sha=EXPECTED_APPROVED_SOURCE_COMMIT \\
  -f create_draft=false
```

Approve the attestation environment only after reviewing the expected
source/ref and CI. Download and independently verify the candidate.
A fresh dispatch with `create_draft=true` is optional and requires
separate environment approval after successful verification. Reruns
are refused; use a fresh explicit dispatch and approvals. The draft job
rechecks eligibility and provenance, creates only a new draft, uploads
only the Linux executable and its checksum/build-info files, downloads
the executable back by asset ID and verifies exact bytes and provenance.
If staging fails, leave any partial draft untouched for maintainer review.
No overwrite, deletion, automatic publication, Edge-channel changes,
or unsigned elevated release fallback. The draft is intentionally
incomplete: the full Windows/source/docs asset set and release acceptance
must be independently assembled and reviewed before manual publication.
The existing unsigned candidate packaging workflow remains unchanged.

## Independent operator verification

Operator independently knows the expected repository, approved tag and
commit (trusted release announcement/verified source record), and obtains
GitHub CLI from a trusted distribution. For an eligible release, use
the following verification policy (placeholders are not a real release):

```sh
gh attestation verify ./computer-host-linux-installer \
  --repo ldeora/SmartThingsEdgeDrivers \
  --signer-workflow ldeora/SmartThingsEdgeDrivers/.github/workflows/computer-host-linux-attested-release.yml \
  --source-ref refs/tags/EXPECTED_APPROVED_TAG \
  --source-digest EXPECTED_APPROVED_SOURCE_COMMIT \
  --signer-digest EXPECTED_APPROVED_SOURCE_COMMIT \
  --deny-self-hosted-runners \
  --predicate-type https://slsa.dev/provenance/v1
```

Normal online verification retrieves the attestation and trust material.
The trust model includes GitHub's repository/workflow identity and the
Sigstore trust infrastructure (the public Sigstore instance for public
repository attestations, with GitHub also a trust dependency). For a
disconnected host, obtain the matching attestation with
`gh attestation download` and the trust material with
`gh attestation trusted-root` on a trusted connected host. Transfer them
with the expected source record and verify with the same constraints
above plus `--bundle PATH_TO_ATTESTATION.jsonl --custom-trusted-root
PATH_TO_TRUSTED_ROOT.jsonl`. Do not accept an arbitrary trust root
supplied by an untrusted binary distributor. Offline name verification
alone does not establish that the repository still belongs to the same
owner; independently pin/check the source repository identifier and
expected source revision. Establish a trusted-root refresh and
attestation revocation/check policy before using offline verification
for deployment. See [GitHub offline verification instructions](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/verify-attestations-offline)
and [trusted-root CLI](https://cli.github.com/manual/gh_attestation_trusted-root).
No offline verification procedure has yet been accepted for this project.

Any nonzero result or unexpected signer/ref/commit means do not execute.
Use actual final filename and documented minimum verifier version at release.
A valid attestation is not an independent code review.

### Protected executable handoff — PR #164 (merged)

The new handoff snapshots `/proc/self/exe`, not the mutable pathname returned
by `os.Executable()`, into a private user-owned 0700 directory. The root
authorization provider invokes only a root-owned, non-writable system Python
3.10+ interpreter in isolated mode. Its fixed launcher opens the snapshot
directory/file with no-follow descriptor-relative operations, checks owner,
mode, link count, size and identity, copies the bytes into a fresh 0700
directory below root-owned `/run/computer-host-lan`, fsyncs the copy and
directories, and verifies SHA-256 against the digest computed from the
running image. It executes that root-only copy; the Go root bootstrap refuses
to run unless `/proc/self/exe` resolves to the expected root-owned handoff
path. The wrapper removes the temporary root copy after the bootstrap exits.
sudo, doas, run0 and su retain their existing input/password semantics.

### Platform-specific validation and deferred compatibility

- **`/run` mounted `noexec`: not supported by this implementation.** The
  protected copy is executed by pathname below `/run/computer-host-lan`.
  A hardened `noexec` mount therefore prevents the handoff from starting;
  the launcher fails closed, but currently reports its generic handoff
  failure rather than a dedicated mount diagnostic. Explicit detection and a
  fixed diagnostic, or a separately reviewed sealed-`memfd`/`fexecve`
  design, are deferred. Do not claim support for `noexec` hosts.
- **Gentoo Python wrapper:** `/usr/bin/python3` may resolve to Gentoo's
  `python-exec2c` wrapper. The Go code checks the resolved executable's
  root-owned path and invokes it with isolated, no-bytecode options
  (`-I -S -B`). Hydra acceptance on 2026-11-24 confirmed that direct
  wrapper invocation fails but the existing version-specific Python
  3.14.10 fallback succeeds. Actual `su` handoff returned
  `nothing_to_recover`, left only bootstrap.lock, and preserved the
  agent PID and activation timestamp. Basic `run0` authorization failed
  independently of the installer; physical `run0` acceptance remains
  required on a suitably configured supported host before release.

This pins the elevated process to the image already running in the ordinary
user process and prevents a pathname replacement between that launch and
elevation from changing the bytes executed as root. The handoff does not
verify the Sigstore attestation itself; the operator must independently
verify the release before launching it. It also does not make an untrusted
binary safe to launch or protect a file replaced before its first user-mode
execution. If the threat model is expanded to include that initial
verify-to-exec window, a separate trusted fd-aware verify-and-exec launcher
must be designed rather than claiming this handoff closes it.

Keep ordinary-user wizard/CLI behavior; never run the UI as root.

## Acceptance before closing #84

- Review pinned workflow, eligible ref policy and permissions.
- Produce an actual eligible attestation, retrieve independently and verify
  exact bytes. Negative tests: modified byte, wrong repo/workflow/ref/commit,
  missing attestation, unapproved source and failed publication gate.
- Test protected executable handoff; document exact verification commands
  and independently expected source. Verify downloaded release bytes.
- Explicit approval before first public release; do not alter existing RC
  assets or Edge channel. Final hardware and distribution acceptance separate.

Detached GPG/minisign is a fallback design only if separately reviewed;
fingerprint needs an independent trusted channel. No credentials change,
signing-key creation or publication is authorized by this design.
