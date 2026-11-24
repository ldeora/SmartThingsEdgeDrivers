# Linux installer release authentication — design for #84

**No attested release exists yet.** The protected executable handoff is
implemented in PR #164, pending independent review and merge. The dedicated
tag-only build/attestation/publication workflow below remains the next
implementation increment. Nothing in this document authorizes a release tag,
publication, or changes to existing RC assets.

Use GitHub public-repository artifact attestations (Sigstore-backed build
provenance) for the standalone Linux installer. Unlike a checksum shipped
alongside the executable, a signed provenance statement binds the digest to
an authenticated workflow and source revision. This is provenance, not proof
of code safety.
References: [GitHub artifact attestations](https://docs.github.com/en/actions/concepts/security/artifact-attestations),
[verification CLI](https://cli.github.com/manual/gh_attestation_verify).

## Build and publication policy

Proposed dedicated workflow: .github/workflows/computer-host-linux-attested-release.yml.
Separate from PR test artifacts and existing unsigned candidate workflow.
No attestations for arbitrary PR/fork builds or pull_request_target code.
Only explicitly approved release tags on reviewed main; verify exact
release.json version/tag/commit, green required checks and no replacement
of existing assets. Pin actions to reviewed full commit SHAs. Least
privileges: contents read for build; id-token write and attestations write
only for attesting job; separate explicitly approved publishing job with
contents write. No unreviewed source inputs or secrets in assets.

Build clean linux/amd64 with exact supported Go patch version (go.mod
currently 1.25.8; reevaluate security updates before release), GOTOOLCHAIN=local,
CGO_ENABLED=0, GOOS=linux, GOARCH=amd64, go mod verify, bundle generator
check, tests and go build -mod=readonly -trimpath -buildvcs=true. Record exact
toolchain/version/source SHA/digest. Compare a second clean build; claim
reproducibility only after measurement. Attest the exact executable bytes
with GitHub's supported provenance action. Upload those bytes unchanged.
Fail closed if attestation or verification unavailable; no unsigned
elevated release fallback. No retagging or alteration of RC assets.

## Proposed verification

Operator independently knows the expected repository, approved tag and
commit (trusted release announcement/verified source record), and obtains
GitHub CLI from a trusted distribution. Once the workflow exists, use
the following verification policy (placeholders are not a real release):

```sh
gh attestation verify ./computer-host-linux-installer \
  --repo ldeora/SmartThingsEdgeDrivers \
  --signer-workflow ldeora/SmartThingsEdgeDrivers/.github/workflows/computer-host-linux-attested-release.yml \
  --source-ref refs/tags/EXPECTED_APPROVED_TAG \
  --source-digest EXPECTED_APPROVED_SOURCE_COMMIT \
  --deny-self-hosted-runners
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

### Protected executable handoff — PR #163 (pending review)

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
