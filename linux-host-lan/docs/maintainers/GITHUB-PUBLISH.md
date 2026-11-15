# Publishing Linux Host LAN in ldeora/SmartThingsEdgeDrivers

**Source import completed:** Linux Host LAN was merged into `main` through [PR #1](https://github.com/ldeora/SmartThingsEdgeDrivers/pull/1) on 2026-11-15. The source lives in [`linux-host-lan/`](https://github.com/ldeora/SmartThingsEdgeDrivers/tree/main/linux-host-lan). Do not import the GitHub-ready ZIP into the repository a second time.

**Current task:** prepare the **draft prerelease** `linux-host-lan-v0.3.1-beta.1`. A draft can be reviewed without advertising an unfinished public download. This guide deliberately leaves broader public-beta gates open.

## Prerelease safeguards

1. Apache-2.0 licensing is present in `linux-host-lan/LICENSE` and the agent archives. Check code provenance and any third-party attribution before public distribution.
2. The project targets trusted LANs, not public networks. Review `SECURITY.md` and `docs/beta/PUBLICATION-GATES.md` before releasing assets to volunteers.
3. The Gentoo Agent 0.3.0 + Edge Driver 0.2.9 combination is hardware validated. Other distributions have **not** passed full systemd/hardware testing; the six-distro CI template remains inactive.
4. The publisher must verify the driver channel, custom capabilities and a separate tester account before inviting volunteers.

## Build and verify the release artifacts

Start from an up-to-date local checkout **after the documentation PR is merged**:

```sh
cd ~/devel/ghar/SmartThingsEdgeDrivers
git switch main
git pull --ff-only
cd linux-host-lan
python3 -m unittest discover -s tests -q
sha256sum -c FILES.sha256
python3 scripts/ci/build_release.py --output-dir dist
(cd dist && sha256sum -c SHA256SUMS.txt)
```

The release builder produces **four** upload assets in `linux-host-lan/dist/`:

- `linux-host-lan-github-ready-v0.3.1-beta.1.zip` — project-only source snapshot (optional GitHub Release asset; GitHub also auto-generates repository-wide source archives)
- `linux-host-agent-bundle-v0.3.1-beta.1.tar.gz` — recommended volunteer Linux download
- `linux-host-agent-bundle-v0.3.1-beta.1.zip` — alternative volunteer download
- `SHA256SUMS.txt` — checksums for the three generated archives

The standalone agent bundles include the Apache-2.0 license and exclude development-only driver files, tests, machine identities and secrets. Do not publish control keys, UUIDs, local configuration, or service state files.

## Tag the reviewed source

Run these commands from the **repository root**, after confirming the correct `main` commit and a clean work tree:

```sh
cd ~/devel/ghar/SmartThingsEdgeDrivers
git status --short
git rev-parse --short HEAD
git tag -a linux-host-lan-v0.3.1-beta.1 -m 'Linux Host LAN v0.3.1-beta.1'
git push origin linux-host-lan-v0.3.1-beta.1
```

Do not reuse or forcibly move a published version tag. If the reviewed code changes after tagging, prepare a new prerelease version instead.

## Create a DRAFT prerelease with GitHub CLI

From the repository root, with `gh auth status` showing the expected account:

```sh
gh release create linux-host-lan-v0.3.1-beta.1 \
  linux-host-lan/dist/linux-host-agent-bundle-v0.3.1-beta.1.tar.gz \
  linux-host-lan/dist/linux-host-agent-bundle-v0.3.1-beta.1.zip \
  linux-host-lan/dist/linux-host-lan-github-ready-v0.3.1-beta.1.zip \
  linux-host-lan/dist/SHA256SUMS.txt \
  --draft --prerelease \
  --title 'Linux Host LAN v0.3.1-beta.1 (closed beta)' \
  --notes-file linux-host-lan/docs/maintainers/RELEASE-NOTES-DRAFT.md \
  --verify-tag
```

Review the draft in GitHub's Releases UI. It is intentionally **not yet published**; publishing requires an explicit decision after the remaining release gates are reviewed. GitHub's automatically generated ZIP/TAR source archives refer to the **entire monorepo**, so volunteers should use the named Linux Host Agent bundle instead.

## SmartThings channel and support

Create the beta channel/invitation separately; do not substitute a GitHub download for the hub-installed Edge Driver. Validate the existing `oceancircle09600` capabilities, device presentations, and hub onboarding from an account other than the publisher's. Provide the real driver-channel URL and release URL in the SmartThings Community post only after both are verified.

Bug reports belong in [GitHub Issues](https://github.com/ldeora/SmartThingsEdgeDrivers/issues), with the forum used for general discussion. Never request unredacted diagnostic logs or the HMAC control token. Instructions for CI activation are in `docs/maintainers/CI-ACTIVATION.md`; leave it inactive until review.
