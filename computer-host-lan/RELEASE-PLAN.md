# Computer Host LAN — release plan

## Phase A: repository preparation
- [x] Isolate `computer-host-lan/` from legacy `linux-host-lan/`.
- [x] Run Windows x64 build/service smoke and Linux CI; ARM64 cross-publish.
- [x] Replace stale prerelease onboarding docs and remove duplicate inactive workflows.
- [ ] Review and merge the new project via PR; verify release-source checksum generation.

## Phase B: publishable prerelease
- [ ] Decide the final name/version and tag from a **fixed passing commit**.
- [ ] Build versioned source and Windows x64 install kit from that commit in CI; sign where feasible or prominently label unsigned; attach SHA-256, source/license, known limitations and upgrade notes.
- [ ] Verify asset download and checksum as a new tester would. Do not rely on 7-day Actions artifacts.

## Phase C: SmartThings distribution
- [ ] Verify new Computer Host LAN driver package key, its six capabilities, bilingual presentations and both Linux/Windows profiles.
- [ ] Assign the driver to an appropriate beta channel and generate a verified invitation.
- [ ] Perform test enrollment with another account/hub before posting.
- [ ] Record steps for controlled driver updates and host agent rollbacks.

## Phase D: SmartThings Community
Publish one announcement with **permanent** GitHub release assets, SmartThings channel enrollment link, quick-start guides, supported/unverified matrix, opt-in power warnings and a GitHub issue-template link. Recruit technically capable Windows 11 and Linux volunteers. Hardware behavior is the aim of the beta; do not claim Windows 11 power-state compatibility already proven.

See `docs/beta/PUBLICATION-GATES.md` and `docs/beta/FEEDBACK-AND-SUPPORT.md`.
