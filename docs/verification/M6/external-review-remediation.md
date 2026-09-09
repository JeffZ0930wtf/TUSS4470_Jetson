# M6 post-closure external review remediation

## Document overview

This document records the bounded maintenance patch performed after M6 closed.
It explains which external-review findings were corrected, which automated
checks prove each contract, and which limitations remain. It applies to the M6
host runtime, Web console, persistence API, and Jetson test automation. The M6
closure summary remains the authority for first-version hardware acceptance;
the remediation design and execution plan remain under `docs/superpowers/`.

## Scope and result

The seven findings in the 2026-09-09 external review were resolved without
changing MSP430 firmware, TUSS4470 register behavior, the USAC wire protocol,
ADC/DMA acquisition, Burst generation, or hardware safety gates. The Windows
aggregate offline gate passed with 242 Python tests, the repository Node UI
behavior test, all firmware builds and static audits, and all MSP430 simulator
tests. No COM port was opened, no firmware was flashed, and no Burst was
produced during this maintenance patch.

| Finding | Corrected contract | Exact automated evidence | Result | Remaining limitation |
|---|---|---|---|---|
| R1 | A single capture keeps the executor lock through configuration snapshot, SQLite/spool resolution, confirmation, and release. Nested configuration values are deep-copied before publication. | `test_single_capture_resolution_callback_remains_inside_device_serialization`; `test_single_capture_snapshot_deep_copies_nested_configuration`; `test_single_capture_keeps_applied_context_until_delivery_is_resolved` | Pass | This patch does not add a distributed transaction across separate machines; it closes the existing single-core delivery boundary. |
| R2 | Generic UI errors no longer clear an unrelated active task. Single and terminal session ownership is released before waveform/history presentation. | `packages/usac_runtime/tests/test_m5_app.cjs` draft-error, terminal-refresh, and single-display scenarios | Pass | Presentation failures are reported to the operator; they do not recreate a failed download automatically after a task has ended. |
| R3 | Periodic mode hides and disables external trigger/sync controls and omits them from its request. | `packages/usac_runtime/tests/test_m5_app.cjs` periodic-mode request and control assertions; `test_web_console_is_served_without_hardcoded_parameter_table` | Pass | Periodic acquisition continues to use the existing firmware internal timer; no new periodic trigger mode was added. |
| R4 | Archived and transient captures expose the same 13 raw frame metadata fields. Values, including calibrated-clock zero, come from the decoded authoritative frame without substitution. | `test_capture_record_metadata_comes_from_authoritative_wire_frame`; `test_archived_and_transient_capture_metadata_have_the_same_contract` | Pass | The fields are additive API output; no SQLite column migration was required because archived values are reconstructed from the retained wire frame. |
| R5 | `/device` uses an immutable published session and cached diagnostics while acquisition owns the executor. Disconnect/replacement invalidates prior identity and diagnostics; lock acquisition is non-blocking. | `test_reconnectable_device_publishes_real_bridge_identity_without_locking`; `test_reconnectable_device_switches_sessions_without_retrying_failed_command`; `test_device_endpoint_does_not_wait_for_sweep_executor_lock` | Pass | Diagnostic status may intentionally be stale during a run and includes `diagnostics_observed_utc_ns`; identity and connection generation remain current. |
| R6 | A running session renders each newly published latest capture at most once, keeps only one rendered ID, and schedules the next poll even when a query or waveform load fails. Terminal state is closed before display refresh. | `packages/usac_runtime/tests/test_m5_app.cjs` running-waveform, failed-waveform, and terminal scenarios | Pass | The Web view may skip intermediate frames produced faster than its 250 ms poll interval; acquisition and storage are unaffected. |
| R7 | The Jetson ARM64 container smoke overrides the service entrypoint with a terminating Python protocol codec check before AMD64 export. | `ProjectLayoutTests.test_host_automation_matches_the_platform_split` | Pass | The Windows gate verifies script structure only; actual ARM64 container execution is repeated on Jetson during synchronization. |

## Verification commands

The final branch checks were:

```powershell
$env:VIRTUAL_ENV = (Resolve-Path .venv).Path
./scripts/test-all.ps1
node --check ./packages/usac_runtime/src/usac_runtime/web/m5-app.js
git diff --check
git diff --stat main...HEAD
```

`scripts/test-all.ps1` completed successfully in approximately 49 seconds.
The test worktree reused the repository's pinned MSP430 toolchain through local
ignored directory junctions; no toolchain file or generated firmware artifact
is part of the patch.

## Acceptance boundary

This record closes the reviewed host defects only. It does not reopen M6, does
not mark M7 complete, and does not replace the real-hardware evidence already
recorded in `summary.md` and `jetson-validation.md`. Instrument-calibrated
timing, long unattended reliability, security hardening, and the accepted
lease/scheduling limitations remain M7 work.

## Jetson synchronization check

The Jetson formal checkout was clean and was fast-forwarded from
`890240306619d1de788b189c919baf9c35a67ce8` to
`35b3410fb6b750955bafed0c5a1d8620dabff264`. Direct Jetson-to-GitHub HTTPS did
not respond within the bounded check, so the exact already-pushed `main`
history was transferred as a verified Git bundle and fetched locally. Commit
identity and history were preserved.

The native `linux/arm64` image rebuilt successfully and the corrected
entrypoint-override protocol smoke exited successfully. No container mapped a
USB device and no acquisition command was sent. Three environment limitations
were observed and were not concealed as passes:

- the formal checkout's host `.venv` lacks the development dependency
  `fastapi`, so pytest stopped during collection;
- Node is not installed on the Jetson host, so the Node VM regression could
  not run there;
- the active Docker builder advertises only `linux/arm64` and
  `/proc/sys/fs/binfmt_misc/qemu-x86_64` is absent, so the bounded AMD64 export
  stopped with `exec format error` at the first target-architecture `RUN`.

Windows remains the complete offline source/firmware gate for this patch. The
Jetson result proves the R7 ARM64 smoke no longer launches a persistent server;
it does not claim that missing host development tools or AMD64 emulation were
restored.

## Cleanup

The repair branch was deleted after its commits were fast-forwarded to `main`,
and its Git worktree registration was pruned. Because the local environment and
build outputs kept the physical directory non-empty, the unregistered remainder
was retained for traceability under
`.worktrees/archive/m6-external-review-fixes` instead of being force-deleted.
The temporary Windows and Jetson Git bundles were deleted. The Windows and
Jetson formal `main` checkouts were clean at the synchronized commit.
