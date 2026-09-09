# External Review Remediation Design

## Document overview

This document defines the bounded maintenance release that resolves findings
R1 through R7 in the 2026-09-09 external review of the TUSS4470 ultrasonic
acquisition submodule. It applies to the already closed M6 host, API, Web, and
Linux verification paths. It refines implementation behavior without changing
the M6 hardware protocol, firmware timing, electrical safety gates, or the M7
production-hardening boundary. The staged roadmap remains authoritative for
milestone scope; the external report remains the source of the reproduced
defects.

## 1. Objective and scope

The maintenance release shall correct normal operator workflows that can
misidentify capture configuration, lose the Web stop control, hide current
waveforms, or expose incomplete capture metadata. It shall also make the Linux
aggregate verification command terminate normally.

The release includes:

- R1: bind a single capture, its APPLIED configuration snapshot, durable
  storage decision, bridge acknowledgement, and pending-frame release;
- R2: preserve active Web task ownership across unrelated request failures;
- R3: prevent periodic mode from displaying unsupported trigger options;
- R4: expose the complete existing wire-frame metadata through the public API;
- R5: return a current host activity and the latest published device status
  without waiting for a complete Sweep;
- R6: refresh one latest waveform while a periodic or Sweep session runs; and
- R7: replace the non-terminating container smoke command with a bounded check.

The release excludes the report's optional architecture refactors, dependency
locking changes, multi-device scheduling, new security infrastructure,
WebSocket streaming, new database indexes, wire-protocol changes, firmware
changes, and new hardware tests. Those items remain possible future work and
must not be introduced incidentally while resolving R1 through R7.

## 2. Selected approach

The implementation shall be a small M6 maintenance patch on an isolated Git
worktree. It shall extend the existing `SingleDeviceExecutor`,
`AcquisitionApplication`, schema-driven Web page, and test scripts rather than
introduce new services or a front-end framework.

Two alternatives were rejected:

1. fixing only R1 and R2 would leave known first-version API and operator
   workflow gaps; and
2. combining the fixes with the report's larger model/file/dependency cleanup
   would expand risk and obscure the evidence for each reproduced defect.

## 3. R1: atomic single-capture resolution

### 3.1 Transaction boundary

`SingleDeviceExecutor` remains the sole owner of device-client serialization.
Its single-capture operation shall:

1. acquire the per-device lock;
2. refresh the bridge session and validate the expected APPLIED identity;
3. validate the trigger parameters;
4. create an independent deep copy of the current APPLIED
   `ConfigurationSnapshot`, including every nested mapping, list, and tuple;
5. request exactly one capture;
6. invoke the application-supplied resolution callback with an
   `ExecutedCapture` containing the raw decoded capture and copied snapshot;
7. let that callback persist the configuration context, commit the storage
   decision, issue `CAPTURE_COMMITTED`, and release the pending capture; and
8. release the executor lock only after the callback returns or raises.

The callback result becomes the operation result. No second read of shared
DRAFT/APPLIED state is allowed when preparing capture metadata. A frozen
dataclass alone is not considered immutable because its dictionary values can
still be edited in place. `ParameterService` and the executor must never
mutate a published snapshot in place, and the capture copy must share no
mutable nested object with the current DRAFT/APPLIED state. A regression test
shall mutate nested data after capture and prove that the stored capture
context does not change.

### 3.2 Failure behavior

If device capture or persistence fails, the existing single-session summary is
finalized as failed. The executor lock is always released. Existing spool
replay/idempotency rules remain unchanged; the patch must not acknowledge an
uncommitted frame.

A draft request arriving during this transaction may wait and run afterward.
Whether it is accepted after the capture is not part of the capture identity:
the stored frame must always retain the snapshot copied before acquisition.
An apply or other device command cannot enter the device transaction until the
pending capture is resolved.

## 4. R5: non-blocking published device status

The host shall publish one small immutable `DeviceViewSnapshot` containing all
information needed by `/api/v1/device`:

- connection state and backend kind;
- device ID, boot ID, firmware identity, and session generation;
- the most recently completed device status and capability response;
- the host activity; and
- the host UTC nanosecond timestamp at which device diagnostics were observed.

The endpoint must not read `connected`, `hello`, `session_generation`,
`status`, `capabilities`, or any other property from the live device wrapper
while serving a cached response. In particular, those properties on
`ReconnectableBridgeDeviceClient` use the same wrapper lock as device commands
and are therefore treated as potentially blocking device access.

`ReconnectableBridgeDeviceClient` shall publish an immutable session view when
a completed HELLO session is installed. It shall replace that view with a
disconnected view when the session is closed or lost, and a different
device/boot/session generation shall replace rather than amend the old view.
The executor/application device view is updated from this published session
view and from completed diagnostic commands; no stale identity is presented as
the current connected session after invalidation.

`/api/v1/device` shall first obtain the current published snapshot without
device I/O. When no host activity is known, it may ask the executor for a
refresh only through a non-blocking lock acquisition. If the executor lock is
not acquired immediately, including the race where an operation begins after
the activity snapshot was read, the endpoint returns the published cache. It
must not wait for a complete capture, Start Delay, Sweep, periodic callback, or
pending-frame resolution. A cache that has not yet been populated is
represented as an unavailable value, not as fabricated normal hardware state.

This design preserves Sweep's exclusive configuration semantics. It does not
split the executor lock between Sweep points and does not permit writes during
an active plan. Verification shall use the real
`ReconnectableBridgeDeviceClient` around the test bridge client, not only the
simulated-device implementation, and shall cover session replacement and
disconnect invalidation.

## 5. R4: public capture metadata

### 5.1 Output contract

One metadata serializer shall be used for archived captures and transient
`SAVE_NONE`/rolling-latest results. In addition to the fields already returned,
the public capture payload shall expose these existing `CaptureData` fields:

- `adc_bits`;
- `sample_encoding`;
- `vref_mv`;
- `smclk_nominal_hz`;
- `smclk_calibrated_hz`;
- `frame_start_tick48`;
- `t_trigger_offset_ticks`;
- `adc0_hold_offset_ticks`;
- `adc_aperture_ns`;
- `trigger_to_tx_output_ns`;
- `calibration_version`;
- `out3_start_level`; and
- `out4_start_level`.

Values shall be passed through exactly as decoded from the wire frame. A zero
calibrated clock or calibration version retains its protocol meaning; the host
must not relabel the nominal 24 MHz clock as calibrated. Existing
`quality_flags`, `interpolated=false`, configuration snapshots, events, and
storage resolution remain present.

### 5.2 Persistence model

No schema migration or new indexed columns are required. `CaptureStore` shall
decode the already archived `wire_frame` when constructing a `CaptureRecord`
and attach the public metadata values to that record. Transient responses use
the same serializer directly from the decoded `CaptureData`. This keeps the
wire frame authoritative and makes archived and transient payloads comparable.

## 6. R2, R3, and R6: Web task behavior

### 6.1 Task ownership

The generic error wrapper shall only display the error and restore controls
appropriate to the current state. It shall not clear `state.active`.

The capture-start path owns cleanup for a start request that fails before a
session is returned. A SINGLE capture request shall release its busy/task state
as soon as the capture request itself succeeds or fails; waveform rendering and
history refresh happen afterward and cannot prevent that cleanup. Once a
periodic or Sweep session ID has been accepted, only a backend terminal state
(`COMPLETED`, `STOPPED`, `FAILED`, or `INTERRUPTED`) clears `state.active`.
When a terminal response is received, the page shall first publish the terminal
state and clear task ownership, then attempt waveform and history refresh.
Failures from save draft, validate, history, waveform, refresh, or stop
requests must preserve any still-active session and its stop control.

Polling transport, session-query, or waveform-display failures are display
errors rather than evidence that the backend task ended. If `state.active`
still identifies a periodic or Sweep session after such an error, the page
shall schedule the next bounded poll. Only a confirmed backend terminal state
stops polling for that session.

### 6.2 Mode-specific controls

The trigger source and synchronization timeout controls apply only to SINGLE
and SWEEP. Selecting PERIODIC shall hide and disable both controls and display
a bilingual explanation that the firmware periodic scheduler uses its own
internal timing. The periodic request body shall remain unchanged and shall
not silently accept or discard visible external-sync choices.

Repeated externally synchronized acquisitions remain a finite sequence of
single-capture operations or a Sweep, as defined by the existing design. The
firmware periodic protocol is not expanded by this patch.

### 6.3 Latest waveform refresh

During session polling, the page shall compare the returned
`last_capture_id` with the ID most recently rendered. When a new non-null ID is
observed, it shall fetch and draw that capture once. Session polling is
scheduled independently of waveform rendering, so a slow or failed waveform
request cannot suppress the next status query. The active session remains
stoppable.

Only the latest rendered ID and waveform are retained. The page shall not
append frame objects or samples to an in-memory history, and the refresh rate
shall remain bounded by the existing session poll interval. This provides live
visibility for `SAVE_NONE` without converting it into durable storage.

## 7. R7: bounded Linux aggregate verification

After building the ARM64 core image, `scripts/test-all.sh` shall run that image
with its service entrypoint explicitly replaced by a deterministic command
that imports the runtime and protocol packages, performs a small protocol
encode/decode check, and exits with status zero. Failure to import or round
trip exits non-zero.

The script then proceeds to the existing AMD64 buildx OCI export. The check
shall not start a long-lived HTTP service, access a serial device, flash
firmware, or issue a Burst. A shell/static regression test shall verify that
the smoke invocation overrides the service entrypoint and that the AMD64
export remains after it.

## 8. API and compatibility

- Existing REST routes and request bodies remain compatible.
- Capture responses gain additive metadata fields; existing clients may ignore
  them.
- The device response gains observation timestamps and may publish cached
  status while host activity is in progress.
- PERIODIC keeps its current backend contract and internal timing behavior.
- No protocol version, SQLite schema version, firmware binary, or hardware
  wiring change is required.

## 9. Verification strategy

Each finding shall follow red-green testing using the review reproduction as
the behavioral source:

1. R1: place a barrier after frame receipt and before persistence; concurrently
   request device state and draft modification; assert no HTTP 500 and exact
   frame/requested/actual/readback identity. Mutate nested source snapshot data
   after capture and assert the stored context remains unchanged.
2. R2: reject draft, validation, history, waveform, and stop-related requests
   while a periodic session remains `RUNNING`; assert task ownership and stop
   access remain. For SINGLE and terminal session responses, fail waveform and
   history loading and assert task cleanup still completes.
3. R3: switch all three modes; assert only applicable trigger fields are
   enabled and every visible value is present in the emitted request.
4. R4: compare every public metadata field for one identical input frame under
   `SAVE_ALL` and `SAVE_NONE`.
5. R5: query `/device` through a real `ReconnectableBridgeDeviceClient` during
   a long Sweep start delay and executor-lock race; assert bounded response,
   `SWEEPING`, preserved write exclusion, and correct cache invalidation after
   session replacement/disconnect.
6. R6: publish successive `last_capture_id` values and inject one session or
   waveform request failure; assert one waveform fetch per new ID, continued
   polling while active, and no growth of waveform history.
7. R7: validate the script structure and, on Linux/Docker, execute the
   aggregate path through the ARM64 smoke and AMD64 export.

Final repository verification consists of the Windows aggregate gate,
JavaScript syntax check, focused UI logic tests, `git diff --check`, and a
sensitive-literal scan. Hardware access, COM9, firmware flashing, and Burst are
outside this maintenance release. Jetson receives the merged commit only after
Windows checks pass; its bounded verification shall not repeat completed HIL
captures.

## 10. Documentation and closure

The repository shall gain a maintenance verification summary mapping R1–R7 to
tests and results. The controlled staged roadmap shall record this post-M6
review patch without reopening or weakening M6/G3J evidence. README and Jetson
instructions are updated only where necessary to correct current commands.

After user review of this design, a separate implementation plan shall define
the exact test-first tasks and commit sequence. When all checks pass, the
branch is merged to `main`, pushed to GitHub, synchronized to the Jetson main
checkout, and the owned worktrees are removed. The remote repair branch may be
retained as traceable review history.
