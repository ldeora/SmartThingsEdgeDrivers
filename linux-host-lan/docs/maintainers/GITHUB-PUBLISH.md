# Publishing Linux Host LAN in ldeora/SmartThingsEdgeDrivers

The public repository already organizes Edge drivers in independent root directories. Add **one** new directory, `linux-host-lan/`; do not overwrite the repository's existing drivers or its root `README.md`. This release has been prepared but **has not been pushed**.

## Before making this public

1. **License selected:** Apache-2.0. Verify `LICENSE` is present in the repository subtree and in both agent bundles; confirm code provenance and attribution (including any third-party contributions) before publishing.
2. Review `SECURITY.md`, `docs/beta/PUBLICATION-GATES.md`, and the source. The current HTTP protocol is designed for trusted LANs, not public WAN exposure.
3. Prepare a dedicated SmartThings beta channel and verify a fresh install on a separate SmartThings account, including publisher-owned custom capabilities. Do **not** tell volunteers to create capabilities themselves.
4. CI matrix tests, cross-distro service installation and beta tester hardware tests remain pending. Avoid claims of certified compatibility.

## Push the project subtree (recommended branch/PR workflow)

```sh
git clone https://github.com/ldeora/SmartThingsEdgeDrivers.git
cd SmartThingsEdgeDrivers
git switch -c linux-host-lan-beta
# Extract the github-ready ZIP here; it adds linux-host-lan/

cd linux-host-lan
python3 -m unittest discover -s tests -q
cd ..
git status --short
git add linux-host-lan/
git commit -m 'Add Linux Host LAN closed-beta source and agent installer'
git push -u origin linux-host-lan-beta
```

Create a pull request into `main`, review changes and merge it. At the existing repository root, consider adding a one-line link to the new project without changing other drivers:

```markdown
- [Linux Host LAN — Linux system monitoring and power control](linux-host-lan/)
```

## Build GitHub Release assets (after source review)

From `SmartThingsEdgeDrivers/linux-host-lan/`:

```sh
python3 scripts/ci/build_release.py --output-dir dist
cd dist
sha256sum -c SHA256SUMS.txt
```

**Release tag:** `linux-host-lan-v0.3.1-beta.1` (prefix avoids conflicting with tags for other drivers in this monorepo). After the PR is merged, tag the reviewed commit:

```sh
git switch main
git pull --ff-only
git tag linux-host-lan-v0.3.1-beta.1
git push origin linux-host-lan-v0.3.1-beta.1
```

Create a **draft, prerelease** on GitHub for the tag and attach **all three** generated archives (GitHub-ready project source ZIP, agent `.tar.gz`, agent `.zip`) and `SHA256SUMS.txt`. Each archive includes the Apache-2.0 `LICENSE`. The checksum manifest must reference only assets that are actually available. The checksums do not authenticate the publisher; signed releases should be added later. Release documentation should link to the same source tag and clearly identify Agent 0.3.0, Edge Driver 0.2.9 and Gentoo-only hardware validation.

Do **not** enable the prepared CI workflow merely by copying it unmodified: it lives inside `linux-host-lan/ci/` and must be reviewed/activated at the repository root as `.github/workflows/`, with correct working directory and action pinning.

## Forum and tester onboarding

Publish the recruitment thread after the sources, agent assets and beta channel invitation are actually available. Put the repository path, GitHub Release link and SmartThings invitation link into the thread; do not invent these links in advance. Recommend monitoring-only installation first. Use GitHub Issues for reproducible bugs and the forum for discussion.
