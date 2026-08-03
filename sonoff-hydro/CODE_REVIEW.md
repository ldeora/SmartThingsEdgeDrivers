# Alpha29 code review

## Review objective

Correct the ten-minute device-side cutoff without changing the alpha28 standard-control architecture or removing any user-facing feature.

## Scope of code changes

Runtime changes are confined to the optional `0x501D` synchronization path in `src/init.lua`:

- persistent recognition of an explicitly configured duration;
- bounded synchronization timeout;
- independent retry on unverified initialization, manual Refresh, and later valve activity;
- correction of both duration fields in the 12-byte aggregate;
- matching fail-safe correction on Hydro ONE and Hydro DUO;
- stricter readback verification.

The three physical-control functions `send_on`, `send_off`, and `send_timed_open` are byte-for-byte identical to alpha28.

## Findings

### Basic command isolation

- Valve Open and Switch On still queue the standard Zigbee On command before local bookkeeping.
- Valve Close and Switch Off still queue the standard Zigbee Off command before local bookkeeping.
- Custom timed watering still schedules its safety callback and uses the same standard On/Off path.
- None of those functions references `0x501D`, a private read helper, or the synchronization state.
- A real `device:send()` failure remains visible to SmartThings; failures in post-send UI or timer bookkeeping are caught and cannot undo a command already queued.

### Corrected `0x501D` payload

The decoded 12-byte layout used by alpha29 is:

1. mode;
2. total-duration high byte;
3. total-duration low byte;
4. irrigation-duration high byte;
5. irrigation-duration low byte;
6–7. interval/pause;
8. amount unit;
9–10. amount;
11–12. fail-safe timeout.

Alpha29 performs a fresh read-modify-write. It updates bytes 2–5 to the selected duration. Hydro ONE and Hydro DUO also update bytes 11–12 to the same value. All other bytes are preserved. Hydro ONE Lite preserves bytes 6–12 after updating its two duration fields.

Verification succeeds only when:

- the valve is in duration mode;
- both duration fields match the selected value;
- and, on Hydro ONE or Hydro DUO, the fail-safe field also matches.

An unsolicited attribute report cannot authorize the write; synchronization advances only from an actual read response.

### Retry behavior

- The default 10-minute preference is not written merely because alpha29 was installed.
- A previously selected non-default value is recognized during initialization.
- A preference change starts one independent read-modify-write transaction.
- A tokenized timeout prevents a stale callback from terminating a newer transaction.
- A timeout clears the active phase so Refresh or later valve activity can retry.
- Retry traffic remains bounded to one active synchronization transaction per device.

### Compatibility review

The following files are byte-for-byte unchanged from alpha28:

- `src/sonoff_utils.lua`
- `fingerprints.yml`
- `config.yml`
- all custom capability definitions;
- all custom capability presentations.

Profile component structures, capability lists, preference names, defaults, and ranges are unchanged. Only the explanatory text for **Device-side watering limit** was updated.

## Automated validation

- Lua syntax parsing: passed
- Static architecture validation: passed
- 38 mocked runtime scenarios: passed
- Standard Open/Close isolation tests: passed
- Timed-watering and restart-recovery regression tests: passed
- Full-model dual-duration and fail-safe payload test: passed
- Lite duration update with unrelated-byte preservation: passed
- Stale readback, timeout, retry, and preference-change tests: passed
- DUO endpoint and abnormal-state regression tests: passed
- All YAML and custom-capability JSON parsing: passed
- ZIP integrity validation: passed after final packaging

## Residual risks

- Automated tests cannot prove that a particular SONOFF firmware accepts the private write or applies it to an already active watering run.
- The first long watering test must begin only after a verified readback.
- Hydro ONE Lite does not expose a separately configurable fail-safe in the current public integration surface; alpha29 therefore preserves that field rather than inventing new semantics.
- There is no new user-visible synchronization-status capability in this conservative release. Success or failure is shown in debug logs to avoid changing existing capability dependencies.
- Hydro DUO still needs complete two-channel hardware validation.

## Release recommendation

Use as a supervised alpha. Basic control should be regression-tested first. The device-side limit should then be tested with a 15- or 20-minute ordinary Open run after confirmed `0x501D` readback.
