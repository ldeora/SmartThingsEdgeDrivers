# Changelog

## GitHub-ready cleanup

- Shortened the repository directory name to `ledvance-plug-eu-em`.
- Rewrote `README.md` as clean GitHub-facing documentation.
- Moved historical implementation notes out of the README.
- Added a lightweight static validator.
- No runtime driver logic changes.

## Driver behavior notes

- Supports `LEDVANCE / PLUG EU EM T` and `LEDVANCE / PLUG EU EM T, black`.
- Uses standard Zigbee clusters for switch, metering, and electrical measurement.
- Does not include unconfirmed OSRAM fallback fingerprints.
- Does not force `powerOnBehavior=off` during onboarding, configure, or driver switch.
- Keeps startup behavior handling read-first and only writes on real preference changes.
- Does not suppress lower energy readings forever, so valid lower readings after resets are not ignored permanently.
