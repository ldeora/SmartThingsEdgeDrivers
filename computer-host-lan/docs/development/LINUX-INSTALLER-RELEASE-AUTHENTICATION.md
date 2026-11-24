# Linux installer release authentication — design for #84

**Proposal only; no attested release exists yet.** Use GitHub public-repository
artifact attestations (Sigstore-backed build provenance) for the standalone
Linux installer. Unlike a checksum shipped alongside the executable, a signed
provenance statement binds the digest to an authenticated workflow and source
revision. This is provenance, not proof of code safety.
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
A valid attestation is not an independent code review. Establish and test a
protected executable handoff that prevents replacing bytes/parent between
verification and elevation; current user-owned executable is a residual
trust gap. Keep ordinary-user wizard/CLI behavior; do not run UI as root.

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
