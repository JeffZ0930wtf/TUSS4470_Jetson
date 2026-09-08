# M5 first-version feature verification

## Document overview

This document records M5 implementation and verification evidence for the
ultrasonic acquisition submodule. It applies to full semantic parameter
coverage, configurable acquisition, synchronization, digital events, and the
firmware lease defined by the controlled design and roadmap. It is updated at
each M5 gate; it does not replace the roadmap and must not be read as milestone
closure until the hardware, Windows pipeline, ARM64, commit, push, and cleanup
gates are all complete.

## Status

**Closed — 2026-09-08.** The reviewed M5 candidate
using the Timer_B0 CCR2 DMA trigger has passed the default D10x4 two-frame,
parameter endpoint, finite run-plan, periodic/STOP, renewal, lease-expiry,
OUT3/OUT4 event, and Master/Slave synchronization gates through COM9, bridge,
core, and SQLite. S3 reset and safely power-sequenced USB reconnect recovery
also pass without restarting either host service. The 100, 1000, and all three
seeded-random long-sequence normal-path gates now pass their count, raw-data,
SQLite, spool, and bounded-resource criteria. The first-version host-interface/
persistence checklist and final offline regression are now complete. M5 was
fast-forwarded to `main` after the Windows and native Jetson ARM64 gates.
The merged `main` then repeated the complete 215-test and firmware-build
regression successfully. This summary update is the prescribed
`milestone(M5): complete first-version parameter coverage` closure commit at
`170207c8f0ce55c05eec4c28d3cd3200c6be44f1`.
The 10000 ms lease and non-lossless 5 Hz scheduling limitations remain explicit
M7 work and are not presented as product readiness.

## Firmware candidate implemented

- `sample_interval_ticks=120..960`, fixed 2048 raw samples, and configurable
  pretrigger without interpolation;
- `burst_period_ticks=24..800` and finite `BURST_PULSE=1..63`;
- IO_MODE 0 SPI enable, IO_MODE 1 IO1 enable, IO_MODE 2 finite two-output
  sequence, and IO_MODE 3 IO2 clock generation;
- BOOSTXL pin-11/P8.1 external slave sync and pin-13/P2.6 master sync, including
  a bounded 1..60000 ms slave timeout that starts no Burst on expiry;
- OUT3 first-rising and OUT4 up-to-16-edge hardware capture on an independent
  TA0/SMCLK timebase, with overflow and ambiguous-time quality flags;
- finite and infinite periodic schedules protected by a 1000..10000 ms lease;
  lease expiry, DTR/session loss, and runtime oscillator faults force safe;
- M5 ACLK sourced from the LaunchPad 32.768 kHz XT1, while the already accepted
  M2/M3 images retain their prior REFO behavior; and
- direct streaming from the single 2048-sample buffer with variable event
  metadata, preserving raw ADC values exactly.

## Offline evidence completed

- the final Windows offline regression passed all 215 Python tests, followed by
  the M0, M2, M3, and M5 firmware builds, static safety checks, and all M5
  firmware simulator suites;
- REST, CLI, and Web share one saved DRAFT, validation, and atomic apply service;
  a full GET_CONFIG match is decoded into per-field semantic readback, while
  RunPlan-only fields are explicitly marked as host controlled;
- finite Sweep compilation retains at most 256 validated targets and lazily
  derives Loop steps; callback execution does not retain a second capture
  history, while session responses remain bounded to 100 recent IDs;

- `scripts/test-firmware-m5-burst-plan.ps1`: PASS;
- `scripts/test-firmware-m5-schedule.ps1`: PASS at the scheduler checkpoint and
  again as part of the final 215-test/firmware-build regression;
- `scripts/test-firmware-m5-app.ps1`: PASS, including sync timeout, event
  serialization, lease expiry, and runtime clock-fault shutdown;
- selected protocol schema/message/config pytest: 21 passed;
- `scripts/test-firmware-unit.ps1`: PASS for the existing M2/M3 simulator suite;
- `scripts/build-firmware-m2.ps1`: PASS, no flash;
- `scripts/build-firmware-m3.ps1`: PASS, no flash; and
- `scripts/build-firmware-m5.ps1`: PASS, no flash, with 26,862 B text, 98 B
  data, and 6,116 B BSS. The hardware-tested CCR2 candidate has SHA-256
  `A5FDC5AEACC62C2DCB7B7952A52614D71CE6605B0732047850BBA0FCF2AC7C48`.
  After the boundary-only `pretrigger_count<sample_count` validation change,
  the rebuilt candidate has SHA-256
  `ADB26DDFEA0C819A3AC5C260DD9C1CBD3EDE383851BCB16E9B80F43453DF8623`;
  it passed the focused Python, MCU simulator, M5 application, and build gates.
  On 2026-09-07 it was flashed with external 7 V off and DSLite reported
  successful program verification; no serial command or Burst was issued.
- After the Slave timeout correction, the current candidate has SHA-256
  `83730CBB7891C440DDB8B9659EF17414B255464DE0F78C1E2D463043CF79BFF8`,
  26,886 B text, 98 B data, and 6,118 B BSS. The scheduler, application,
  Burst-plan, M3 static, and M5 build checks passed before DSLite flashed and
  verified it with external 7 V off.
- After the host reconnect correction and the conditionally compiled M3
  diagnostic helper guard, `scripts/test-all.ps1` passed all 207 Python tests,
  M0/M2/M3/M3-diagnostic builds and static audits, and all three M5 firmware
  tests. The M5 ELF size and SHA-256 remained exactly unchanged, confirming
  that the build-only guard did not alter the hardware-tested M5 image.

## Jetson ARM64 build evidence

On the Jetson host, commit `2bb77e8` was checked out in the organized temporary
worktree `/home/yizhouzhao/workspace/TUSS4470_verification/worktrees/m5-arm64`.
`deploy/Dockerfile.core` built natively with `docker buildx --platform
linux/arm64 --load`; the resulting `tuss4470-acquisition-core:m5-verify` image
reported `arm64 linux`. `docker compose -f deploy/compose.jetson.yaml config
--quiet` also passed. No container was started, no `/dev/ttyACM*` device was
mapped, and this build check produced no hardware access or Burst.

## Two-frame repeatability evidence

On 2026-09-07, DSLite flashed and verified the reviewed candidate while
external 7 V was off. After external 7 V was restored and S3 reset was pressed,
the core applied the unchanged D10x4 baseline: 200 kS/s, 2048 samples,
64-sample pretrigger, 480 kHz, IO_MODE 3, and `BURST_PULSE=1`. Register readback
matched the encoded values before either Burst.

Two captures then completed without reset, reconnect, reconfiguration, or
automatic retry in the same device boot and bridge/core session:

| Capture ID | Boot ID | Sequence | Samples | Sample BLOB | Wire frame |
|---|---|---:|---:|---:|---:|
| `669bac091ad3f8c8022ef4127e4d4d73` | `7c5a38708011a6bbc94b8cd72ee26d7c` | 1 | 2048 | 4096 B | 4324 B |
| `b11b6728127cc14b9827152bb247485a` | `7c5a38708011a6bbc94b8cd72ee26d7c` | 2 | 2048 | 4096 B | 4324 B |

Both records have `adc_clipping=0`, `TUSS_DEV_STAT=0x08`, quality flag
`TIMING_UNCALIBRATED`, and the same inner-frame CRC32 expected from the
unchanged configuration and observed waveform. SQLite contains both rows,
the bridge contains both matching committed tombstones, and the final pending
count is zero. Final device status reported capture sequence 2, no clock fault,
no last error, and no active schedule. The bridge and core were then stopped.

## Parameter endpoint evidence

On the same reviewed firmware, a fresh bridge/core session changed one tested
parameter at a time while retaining IO_MODE 3, `BURST_PULSE=1`, and the rest of
the D10x4 baseline. Every apply completed its register/timer readback before the
single authorized capture:

| Capture ID | Sequence | Changed endpoint | Readback | Samples |
|---|---:|---|---|---:|
| `66e6f6e13fc7ba9e7dd000118e42b696` | 3 | 100 kS/s | 240 sample ticks | 2048 |
| `869fe7e03defd4475241f0a9fead143d` | 4 | 50 kS/s | 480 sample ticks | 2048 |
| `d5db81e1460280b83472cad19a38090d` | 5 | 25 kS/s | 960 sample ticks | 2048 |
| `b05917082d74cd26320e1b743405d92c` | 6 | pretrigger 0 | 0 samples | 2048 |
| `e8b27e8947f857c5d4b03195d25c6e72` | 7 | pretrigger upper operational bound | 2047 samples | 2048 |
| `32f142d4af86ce4875f00530244f10d9` | 8 | 1 MHz Burst | 24 Burst ticks | 2048 |
| `08f38ba8d9986158ec11913ae73e3206` | 9 | 30 kHz Burst | 800 Burst ticks | 2048 |

The earlier two-frame gate already covers the 200 kS/s/120-tick preset. All
seven endpoint records contain 4096-byte sample BLOBs and 4324-byte wire
frames, with no interpolation, ADC clipping, or TUSS fault. SQLite contains
seven unique rows, the bridge contains seven corresponding committed
tombstones, and the final pending count is zero. The original 480 kHz,
200 kS/s, pretrigger-64 baseline was applied and read back after the group;
final status reported sequence 9, no last error, no clock fault, and no active
schedule. The services were then stopped and their ports released.

The endpoint run exposed that the parameter registry advertised
`pretrigger_count` through 2048 while the firmware capture path required a
value below 2048. Design version 2.1 resolves the mismatch by requiring at
least one post-trigger sample: the public parameter schema, Python and C
configuration validators, CAPTURE_DATA validator, and protocol schema now all
use `0..2047`. The 2047 hardware endpoint remains the recorded upper-bound
capture; 2048 is rejected before ARM or Burst and is covered by offline tests.

After the corrected ELF was flashed and verified, a fresh device boot provided
the combined host/device recheck. Applying `pretrigger_count=2048` returned
HTTP 422 (`outside its legal range`); device capture sequence remained zero,
with no last error, clock fault, active schedule, or Burst. The D10x4 baseline
was then applied and read back, and one authorized `BURST_PULSE=1` capture
completed as `capture_id=26ebc6cbcbd6ae7f3ffc047123d7cb92`, boot
`12332b685a74aef70824731832237ffa`, sequence 1. SQLite stores 2048 samples in a
4096-byte BLOB and the 4324-byte wire frame; the matching committed tombstone
exists and final pending count is zero. Services were stopped after the check.

## Finite run-plan evidence

On 2026-09-07, a finite run plan exercised a two-point semantic LNA sweep with
two loops per point, 100 ms Start Delay, and 150 ms Loop Delay. The plan kept
the D10x4 baseline, `BURST_PULSE=1`, software trigger, and no periodic task or
automatic retry. The first hardware run completed all four captures but showed
that the stored `readback_config_json` was empty: the executor was persisting
the plan's pre-I/O VALIDATED snapshot instead of the APPLIED snapshot returned
after exact device readback.

The host-only correction now attaches that APPLIED snapshot to each
`ExecutedCapture`; it does not change firmware, protocol framing, Burst, or ADC
sampling. Two focused regression tests reproduced the defect before the fix,
then 29 device-executor, run-plan, and M5 API tests passed after it.

Hardware re-verification used session
`fcf5e24c689947379bee017c133fb986` and completed four captures:

| Capture ID | Sequence | LNA | Encoded/read-back 0x13 | Sweep/loop |
|---|---:|---|---:|---|
| `868b6e49c2fc1a853e02db665ad6c024` | 6 | 10 V/V | 1 / 1 | 0 / 0 |
| `086b62fd672fe7c554b7607da9986b56` | 7 | 10 V/V | 1 / 1 | 0 / 1 |
| `d1c42f05b261fa98678df58a9fe4de09` | 8 | 15 V/V | 0 / 0 | 1 / 0 |
| `ef26ccf8fc0a92f46bd2d39b6fb5061e` | 9 | 15 V/V | 0 / 0 | 1 / 1 |

Every record contains 2048 samples, a 4096-byte sample BLOB, a 4324-byte wire
frame, `TUSS_DEV_STAT=0x08`, and the full requested, encoded, read-back, actual,
and RunPlan context. The same-point storage intervals were approximately 257 ms
and 244 ms, both longer than the configured 150 ms Loop Delay; the first row
was stored about 189 ms after session start, covering the 100 ms Start Delay
plus ordinary configuration/capture work. SQLite contains four unique rows,
the bridge contains four matching committed tombstones, and final pending is
zero. The executor restored and read back the baseline LNA 15 V/V configuration;
status ended with no active schedule, clock fault, or device error. Runtime
services were stopped and both test ports released afterward.

## IO mode, finite pulse, and event evidence

The same powered boot then exercised the remaining finite output endpoints as
four single-variable captures: IO_MODE 0, 1, and 2 with one pulse, followed by
IO_MODE 3 with 63 pulses. Capture sequences 63 through 66 stored register
0x14/0x1A readback pairs of 0/1, 1/1, 2/1, and 3/63 respectively. Each record
contains 2048 samples, a 4096-byte sample BLOB, and a 4324-byte wire frame. All
four capture IDs have matching committed tombstones, bridge pending is zero,
and the baseline IO_MODE 3/Pulse 1 configuration was applied and read back at
the end with no device or clock fault. This verifies the finite functional
paths; physical IO_MODE 2 dead-time remains part of later instrument timing
calibration.

Event acceptance used three additional single captures and kept the original
ADC samples independent from the event table:

| Capture ID | Sequence | Enabled inputs | Result |
|---|---:|---|---|
| `24fefb1ce2e7970ae2ad644fc07d070b` | 67 | OUT3 + OUT4 | no event accepted; `EVENT_TIME_AMBIGUOUS` set |
| `dc67d20b8ca642631c96d1d268ae7cc3` | 68 | OUT3 | one rising event at sample 0, tick 0 |
| `7a197bf1a6497352163d0b173c34ffcf` | 69 | OUT4 | start level high; empty event array |

The OUT3 event is stored separately with channel 3, rising edge, hardware
capture method, one-tick uncertainty, and a 16-byte event record; its wire
frame is therefore 4340 bytes. OUT4 did not transition within this waveform,
so the correct representation is its high start level plus no event—not a
fabricated zero timestamp. With both high-rate comparators enabled together,
an initial interrupt/capture collision made the event ordering ambiguous. The
firmware took the designed quality-degradation path: it discarded the
untrustworthy events, set the ambiguity flag, and still preserved all 2048 raw
samples. The three frames are present in SQLite with 4096-byte sample BLOBs,
have matching committed tombstones, and leave bridge pending at zero. The
baseline disables both auxiliary channels after the test. Absolute event
timing remains uncalibrated until external timing instruments are available.

## External synchronization evidence

The Master path first completed one Pulse=1 capture with
`trigger_source=EXTERNAL_SYNC_MASTER`. Slave acceptance used BOOSTXL pin-11
(LaunchPad P8.1) through 2.2 kOhm: GND established the required low state and
3.3 V supplied the later rising edge. Pin-13 was not connected during the
Slave test.

Initial no-edge trials consistently returned `SYNC_TIMEOUT` without a Burst,
but elapsed much too early: a requested 1000 ms returned in about 94 ms. The
protocol carried the correct u32 value and disassembly showed correct 32-bit
arithmetic. Root-cause tracing isolated the defect to direct single reads of
running `TA1R`: TA1 runs from 32.768 kHz ACLK while the CPU runs from a separate
24 MHz clock. TI SLAU208Q states that a running Timer_A counter read is
unpredictable when its clock is asynchronous to the CPU. The lease path did
not share the symptom because it already advanced through compare interrupts.

The correction reuses the existing TA1CCR1 320-tick compare interrupt. Each
interrupt advances one Slave-wait quantum; the requested milliseconds are
rounded upward and receive one extra phase guard quantum, so timeout cannot
occur early. The implementation no longer reads `TA1R` in the Slave wait.
The REST capture endpoint also maps the device's explicit error to HTTP 422
instead of HTTP 500. Test-first evidence covers 0, 1, 1000, 5000, and 60000 ms
quantization, and all focused tests and the rebuilt firmware passed before
flash.

With pin-11 held low, a 1000 ms request returned structured HTTP 422
`device ERROR 26 / SYNC_TIMEOUT` in 1118 ms end-to-end. Capture sequence stayed
zero and SQLite stayed at 75 rows, proving no Burst and no fabricated frame.
With a single 60000 ms request armed, moving the resistor endpoint from GND to
3.3 V produced the required low-to-high edge and completed capture
`12e9c03e715a004340e2ec9b64d2d948`, boot
`17e7e952b70500d20d7a4929f62f227c`, sequence 1. SQLite stores exactly 2048
samples, a 4096-byte sample BLOB, a 4324-byte wire frame, and the full
`EXTERNAL_SYNC_SLAVE`/60000 ms RunPlan. The matching committed tombstone has
CRC32 3638921163 and bridge pending is zero. The frame retains
`TIMING_UNCALIBRATED`; absolute sync-to-ADC/Burst timing remains an M7
instrument-calibration item.

## Basic bridge/core reconnect evidence

The earlier host stack was deliberately reproduced before correction. The
bridge proxied one COM/TCP session and then exited; the core accepted one TCP
connection, closed its listener, and retained that dead socket. An S3 reset
therefore made Windows report an unusable serial handle and required both
processes to be restarted manually.

The first-version correction adds only session recovery. The bridge creates a
fresh Serial object, TCP connection, and HELLO session after transport loss;
it never retains or retries the failed command. The core keeps its listener
open and publishes a replacement only after HELLO, capability discovery, and
pending-spool replay complete. Publication increments a session generation,
which preserves operator parameter choices as DRAFT but invalidates the old
APPLIED configuration and zeroes its ETag. A fresh SET_CONFIG/readback is
therefore mandatory before any later capture. Focused reconnect, bridge,
executor, server, and API regression tests passed 44 cases.

For HIL acceptance, no SET_CONFIG or CAPTURE request was active. With external
7 V maintained, S3 was pressed once. The existing bridge and core processes
recovered without manual restart: device ID remained
`c5fa4769c16da8710b8688c70ba34cf7`, while boot ID changed from
`17e7e952b70500d20d7a4929f62f227c` to
`50ee416620835a2739995576089c1dbe`. Device state was 6, `last_error=0`, and
`TUSS_DEV_STAT=8`; configuration state was DRAFT with an all-zero ETag.
SQLite remained at 76 captures and the spool remained `pending=0`,
`committed=76`, so reset/reconnect produced no Burst, fabricated frame, or
duplicate delivery.

The physical USB path was then checked using the conservative power sequence:
external 7 V was turned off before USB removal and remained off during
re-enumeration. COM9 and TCP recovered automatically and boot ID changed to
`30817d671564ffd59253726c0a1cca57`; with VPWR absent, firmware explicitly
reported state 7 and error 9 (`VDRV_NOT_READY`) instead of permitting a Burst.
After 7 V was restored and S3 pressed, the same host processes established boot
`ccd42de9ccee30412a50e80a9dfb6e72` and reported state 6, `VDRV_READY=1`,
`last_error=0`, `TUSS_DEV_STAT=8`, and no clock fault. Configuration remained
DRAFT with an all-zero ETag throughout. SQLite stayed at 76 rows and the spool
at `pending=0`, `committed=76`. USB removal while VPWR remains energized and
the wider reset-fault matrix are intentionally deferred to M7.

## Periodic, STOP, and lease evidence

On 2026-09-07, the periodic path was exercised with the reviewed M5 firmware,
the D10x4 baseline, `BURST_PULSE=1`, and no automatic command or capture retry.
The acceptance sequence covered:

- a finite two-capture schedule at 200 ms, which completed with two committed
  SQLite rows and an empty bridge pending queue;
- an infinite schedule explicitly stopped after two captures; its session
  reached `STOPPED`, the capture count and device sequence remained unchanged
  through a further 350 ms observation, and firmware reported no active
  schedule or lease;
- a finite eight-capture schedule at 200 ms with a 3000 ms lease, which
  completed all eight frames while observing a lease renewal; and
- a lease-expiry test that suspended only the core server process for 3600 ms
  while leaving the bridge, TCP connection, USB CDC connection, and device
  powered. Firmware stopped the infinite schedule when its 3000 ms lease
  expired. After the core resumed, renewal of the old schedule was rejected,
  the device reported no active schedule, and its capture sequence remained
  stable through an additional 1100 ms observation.

Early periodic trials exposed three host-side serialization defects rather
than a firmware sampling defect. First, the core released the per-device lock
before SQLite commit and `CAPTURE_COMMITTED`, allowing a concurrent status
request to consume the confirmation response. Second, a reconnecting bridge
began replaying pending data immediately after HELLO while the core did not
proactively read that replay until another command. Third, the periodic worker
held the session lock while waiting for the device lock, while the capture
callback held the device lock and waited for the session lock. The corrections
keep capture delivery, SQLite commit, and confirmation inside the single-device
executor; drain replay during the initial capabilities exchange; and prohibit
holding the session lock across device I/O. These are bounded host concurrency
corrections and do not change the firmware, protocol payloads, Burst timing, or
raw sample path. The focused bridge/client/executor/API/lease suite passed 45
tests after the changes.

The public minimum lease was then re-tested rather than hidden by the more
forgiving 3000 ms setting. Session `c439495501e64847b25fb4cca192cc8c`
used a 200 ms period, eight captures, and `lease_timeout_ms=1000`. It completed
8/8 captures with sequence numbers 55 through 62; the first-to-last SQLite
storage span was approximately 1396.7 ms, so successful completion necessarily
crossed the initial one-second lease boundary. Every row contains 2048 samples,
a 4096-byte raw sample BLOB, and a 4324-byte wire frame. The eight capture IDs
match eight committed bridge tombstones, pending is zero, and final device
status reports `missed_capture_count=0`, no active schedule, no remaining
lease, no clock fault, and no device error.

### Fresh-boot TA1 ownership regression

The later long-sequence preflight deliberately began from a fresh S3 boot. A
100-frame run stopped before its first capture; the host's later renewal saw
`ERROR 5`, but an immediate GET_STATUS preserved the originating device error
as `last_error=18` (`LEASE_EXPIRED`) with capture sequence zero. A second
diagnostic used a 10 s first-capture period and a 3000 ms lease, so it could not
produce a Burst. The schedule was already inactive about 28 ms after the start
response, again with `LEASE_EXPIRED` and sequence zero.

Source tracing closed the cause: TI USB Developers Package `USB_init()` calls
`USB_determineXT2Freq()`, which owns TA1 and leaves `TA1CTL` in SMCLK continuous
mode. The application had initialized TA1 for 32.768 kHz ACLK before
`USB_setup()`, so a fresh boot overwrote the lease timebase and consumed a
nominal three-second lease in milliseconds. A CDC-loss path happened to
reinitialize TA1 later, explaining why earlier periodic tests could pass.

The minimal correction moves the existing TA1 initialization after
`USB_setup()` and adds `scripts/test-m5-timer-ownership.ps1` to reject the old
ordering. The focused ownership test, M5 scheduler/application tests, and full
offline regression pass; text and static RAM remain 26886 B and 6216 B. The
exact candidate SHA-256 is
`407AA44598F04A04D53E71E68A4DE62D5A9FC5818FD2D794CD485C914647C20E`.
It was flashed with external 7 V off and verified by DSLite. On a fresh boot, a
10 s first-capture schedule retained its 3000 ms lease for real wall-clock time,
renewed once during the observation window, and was explicitly stopped without
producing a Burst. A subsequent 100 ms two-frame schedule completed 2/2 with
capture sequences 1 and 2, exact 2048-point payloads, matching SQLite rows and
committed tombstones, pending zero, no missed periods, and no device fault.

### Finite-schedule completion race

The first 100-frame normal-path group after the TA1 fix physically completed
all 100 Pulse=1 captures in about 10.25 s. Session
`0f1883b1849547738af8b4fcc5a5289e` produced device sequences 3 through 102;
SQLite contains 100 session rows totaling 204800 samples, with every row using
a 4096-byte sample BLOB and 4324-byte wire frame. Bridge state ended at pending
zero and 179 committed tombstones; device status reported no active schedule,
no missed period, and no error. The host session nevertheless reported FAILED
with `device ERROR 5 for type 0x0C`.

This was a host end-boundary race rather than a hardware or data failure. The
final CAPTURE_DATA arrived while core was already waiting for a renewal. Core
durably committed that frame and acknowledged the bridge; firmware had reached
the finite count and correctly removed the schedule, so the in-flight renewal
then received INVALID_STATE. The old exception path ignored the committed
count and changed the session to FAILED.

A test now reproduces that exact ordering and first failed with one committed
capture plus a FAILED session. The minimal host correction treats the boundary
as COMPLETED only when the requested nonzero finite count is already durably
committed; it releases local lease ownership without STOP. All other renewal,
transport, storage, infinite-session, and early-failure paths retain the prior
STOP/FAILED behavior. The focused regression and full bridge/API set pass (26
tests). The correction is count-independent and therefore applies to 2, 100,
1000, and longer finite schedules.

After restarting core with the correction, HIL session
`cef1ac85e4d949fbb7cf4a6ffe0bd1be` completed 100/100 in approximately 10.09 s
without retry. Device sequences advanced from 102 to 202, missed periods stayed
zero, and the final device state had no active schedule or fault. SQLite has
exactly 100 unique rows for the session and 204800 total samples; every sample
BLOB is 4096 bytes and every wire frame is 4324 bytes. Spool pending is zero.
This closes the 100-frame gate and permits the planned 1000-frame group.

The next HIL session `17959d4bbdbd49908bff7c8225a23f05` completed the
1000-frame group at a 100 ms period with a 3000 ms lease and no retry. Capture
sequences 203 through 1202 are continuous, SQLite has exactly 1000 unique rows
and 2048000 samples for the session, every sample BLOB is 4096 bytes, every wire
frame is 4324 bytes, and spool pending is zero. Device status ended with no
missed period, fault, or active schedule. The session retained only its most
recent 100 IDs and the process returned to five threads. Observed core working
set moved from about 53.7 MiB to 77.6 MiB but was non-monotonic during the run;
the three longer groups will determine whether this is a bounded allocator/
SQLite high-water mark rather than declaring a leak from one interval.

The recorded seed is `20260907`. Python
`random.Random(seed).randint(2000, 10000)` selected the ordered counts 9604,
3823, and 9460. They are run independently in that order and later groups stop
if any earlier group fails.

The first 9604 attempt was explicitly stopped at 3099 committed captures after
core working set rose from roughly 103 to 122 MiB while handle count rose from
307 to 349 over only 685 additional frames. Device sequence reached 4302 with
zero missed periods, no fault, and no active schedule after STOP; all committed
data was retained. This partial run does not count as a passed random group.

The cause was deterministic: both core archive and bridge spool used
`with sqlite3.Connection`, whose context manager commits or rolls back but does
not close the connection. OS/database handle reclamation therefore depended on
garbage collection. Two focused tests first reproduced the missing close. Both
stores now preserve WAL, synchronous FULL, and the existing transaction scopes
while closing every connection in `finally`. All 17 storage tests and the
combined 43 core/spool/bridge/API tests pass. Fresh core and bridge processes
started with 201 and 169 handles respectively; the 9604 group must be rerun
from zero while observing both processes.

On that rerun, deterministic close held: beyond 7000 frames core and bridge
remained near 52/25 MiB with roughly 208/169 handles. A periodic GET_STATUS
check at 7065 frames observed one missed schedule tick, so the run was stopped
as required. STOP returned 7325 captures, while SQLite then contained a final
7326th row for the same session with continuous sequences 4303 through 11628.
No raw data was lost, but the last frame bypassed in-memory session accounting
after the worker cleared its async handler while STOP was still awaiting ACK.

A new socket-level test reproduces exactly that tail-frame ordering. The worker
now defers handler release while state is STOPPING; the STOP caller retains it
through the device ACK and clears it on either success or failure. The focused
interleaving tests and combined storage/bridge/API set pass (44 tests). Timestamp
analysis of the interrupted run found p50 98.0 ms, p99 118.1 ms, and maximum
176.3 ms storage gaps. Because intermediate `/device` checks issue GET_STATUS
on the same serialized USB path at the 100 ms first-version ceiling, the next
9604 run keeps 100 ms but monitors only core session/process state until natural
completion; one final device status then decides the missed/fault gate.

That non-intrusive session, `a650e71c0dab48d99614a366ed861482`, naturally
completed 9604/9604. SQLite contains exactly 9604 unique IDs, 19668992 samples,
continuous sequences 11629 through 21232, fixed 4096-byte sample BLOBs and
4324-byte wire frames. Pending is zero and committed tombstones remain bounded
at 4096. Core/bridge stayed near 49--53/21--26 MiB and roughly
201--212/169--176 handles throughout. Final `missed_capture_count=37` records
schedule opportunities explicitly skipped by one-frame backpressure at the
100 ms throughput ceiling; no requested capture or committed data is missing.
This passes the acquisition/storage count gate but does not claim lossless
long-term 10 Hz scheduling. The remaining 3823 and 9460 groups use a conservative
200 ms period with all other safety and persistence conditions unchanged.

At 200 ms, session `62b046778c784498987bf6bc11ecdcaa` naturally completed
3823/3823 with continuous sequences 21233--25055, exactly 3823 unique SQLite
rows and 7829504 samples, fixed frame sizes, pending zero, missed zero, and no
device fault. Core/bridge ended near 31.6/16.9 MiB and 208/169 handles.

The first 9460 attempt was invalidated after a concurrent full offline test run
added non-normal host load and the schedule ended at 3891 captures. The offline
suite itself passed 211 Python tests plus all firmware builds/static/unit gates.
A clean retry kept resource use bounded but ended at 8405 captures with renewal
`ERROR 5`. Its SQLite sequences 28947--37351 are continuous and pending is zero.
Stored timestamps show one 2117 ms gap and a late cluster of 766, 599, 531, and
501 ms gaps. This supports a 3000 ms lease-margin problem around FULL-sync
storage/confirmation latency, but cleanup STOP cleared firmware `last_error`,
so LEASE_EXPIRED was not directly preserved and is recorded as an inference.
No further automatic retry was made.

The accepted M5 scope decision is to rerun only this unfinished 9460-capture
group at the existing protocol maximum `lease_timeout_ms=10000`, retaining the
200 ms period, Pulse=1, the same firmware and host code, no in-run GET_STATUS,
and no automatic retry. Core still attempts renewal about once per second; the
larger lease only tolerates a longer transient stall. It also increases the
worst-case firmware auto-stop delay after a real core loss from about 3 seconds
to about 10 seconds, so it is not a product default or a root-cause fix. The
failed 3000 ms evidence above remains part of the acceptance record regardless
of the rerun result.

The final product must decouple lease renewal from synchronous database/storage
confirmation stalls, or provide an equivalently independent high-priority
keepalive path; preserve an attributable lease-expiry diagnostic through
cleanup; and select the default lease from measured Windows/Jetson worst-case
latency plus the allowed post-controller-loss Burst budget. These are explicit
M7 requirements. Passing the 10000 ms M5 rerun can close only the first-version
normal-path durability gate, not long-term unattended/product readiness.

That single authorized rerun, session `3b4620300e5b475ab64b274ed7d9d7f2`,
naturally reached `COMPLETED 9460/9460` without an automatic retry. Device
sequences 37352--46811 are continuous. SQLite contains exactly 9460 unique
capture IDs, 19374080 total samples, one boot/schedule/profile/config CRC, fixed
4096-byte sample BLOBs, and fixed 4324-byte wire frames. A full decode of all
9460 stored frames validated every frame CRC and found zero sample-BLOB or
identity mismatches. Spool ended with zero pending rows and its committed
tombstones remained capped at 4096.

The core database grew by 117465088 bytes, approximately 12417 bytes per
capture. Core began near 18.1 MiB/216 handles/3 threads, stayed around
17--23.7 MiB/222--227 handles/4 threads while running, and ended near
17.6 MiB/220 handles/3 threads. Bridge began near 9.3 MiB/169 handles/2 threads,
stayed around 11.6--12.7 MiB/169--176 handles/2 threads, and ended near
11.6 MiB/169 handles/2 threads. This is bounded rather than proportional to
the stored history.

Final device status had no fault and no active schedule, but reported
`missed_capture_count=4`. These are four explicit 200 ms scheduler opportunities
skipped while the one-frame backpressure path was occupied; the finite task
continued until all 9460 requested captures were committed. Thus no requested
or acquired frame is missing, while the result does not establish lossless 5 Hz
scheduling. Stored-time gaps had p50 198.822 ms, p99 260.996 ms, and maximum
2290.325 ms; two gaps exceeded 1000 ms. The 10000 ms lease absorbed this tail.
This closes the M5 normal-path count/data/resource gate for the seeded random
groups while retaining the lease/scheduling limitation as explicit M7 work.

## Pending firmware HIL evidence

- confirm 7 V VPWR, USB/DTR session, reset-safe state, SPI readback,
  `VDRV_READY`, and no TUSS driver fault before every authorized Burst group;
- [x] flash the exact reviewed M5 ELF only after external 7 V is off;
- [x] pass the default-profile two-frame repeatability gate without reset,
      reconnect, reconfiguration, or automatic retry;
- [x] verify GET_CAPABILITIES/GET_STATUS and all four IO modes without automatic
  retry, starting from the existing D10x4 baseline and Pulse=1;
- [x] verify sample-tick endpoints, pretrigger boundaries, and finite pulse counts;
- [x] use the required sync wiring/source for pin-11 Slave and pin-13 Master
      tests, including no-edge timeout without Burst and low-to-high capture;
- [x] verify OUT3/OUT4 disabled and enabled cases, event limits, and unchanged raw
  ADC samples; and
- [x] verify finite periodic completion, explicit STOP, normal renewal at the
      public 1000 ms minimum, and core-loss lease expiry;
- [x] verify injected S3 reset rebuilds bridge/core/HELLO without a Burst and
      invalidates the old APPLIED configuration;
- [x] verify physical USB/DTR loss with external 7 V first removed rebuilds
      COM9, bridge/core and HELLO after re-enumeration, remains inhibited while
      VPWR is absent, and returns healthy after 7 V restoration plus S3 reset.

IO_MODE 2 non-overlap, sync-to-ADC offset, and OUT3/OUT4 absolute timing still
require the external timing-instrument acceptance defined by the design. Until
that evidence exists, captures remain `TIMING_UNCALIBRATED` and cannot support
calibrated TOF claims.
