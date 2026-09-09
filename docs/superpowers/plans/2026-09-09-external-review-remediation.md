# External Review Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve external-review findings R1 through R7 without changing firmware, hardware behavior, the wire protocol, or the M6/M7 scope boundary.

**Architecture:** Keep `SingleDeviceExecutor` as the one device transaction owner, bind each single capture to a deep APPLIED snapshot and its durable resolution callback, and publish a non-blocking cached device view for read-only status. Extend the existing public payload and plain-JavaScript console additively, then replace the Linux container smoke with a bounded command.

**Tech Stack:** Python 3.12, FastAPI, SQLite/WAL, pytest, plain JavaScript with Node VM tests, PowerShell/sh verification scripts, Docker/Buildx.

## Global Constraints

- Work only in `D:\Desktop\TUSS4470_software\.worktrees\m6-external-review-fixes` on branch `codex/m6-external-review-fixes` until integration.
- Create and activate this worktree's own `.venv`; do not reuse the main checkout environment.
- Use test-first red-green cycles for every behavioral change.
- Do not open COM9, flash firmware, issue a Burst, or alter firmware/hardware timing.
- Do not change the USAC wire protocol or SQLite schema.
- Do not implement the report's optional large-file, domain-model, dependency-locking, security, or multi-device refactors.
- Preserve raw samples, COMMIT-before-ACK behavior, save policies, configuration readback, and current REST compatibility.
- Stop and report any command that remains active for more than 60 seconds unless its bounded continuation is explicitly approved.
- Every formal document starts with `Document overview` or `文档说明`; comments explain contracts and non-obvious decisions rather than narrating statements.

---

### Task 0: Establish the isolated development baseline

**Files:**
- Verify: `scripts/bootstrap-dev.ps1`
- Verify: `scripts/test-all.ps1`

**Interfaces:**
- Consumes: locked Python dependencies from `uv.lock`.
- Produces: repository-local `.venv` used by every later command.

- [x] **Step 1: Build the worktree environment**

Run:

```powershell
& .\scripts\bootstrap-dev.ps1
. .\.venv\Scripts\Activate.ps1
```

Expected: `Development environment is synchronized.` and `$env:VIRTUAL_ENV`
resolves below this worktree.

- [x] **Step 2: Verify the untouched baseline**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
node --check .\packages\usac_runtime\src\usac_runtime\web\m5-app.js
```

Expected: 235 pytest cases pass and Node syntax validation exits zero. If the
baseline differs, stop before product edits and record the actual result.

---

### Task 1: Bind single capture, deep snapshot, and durable resolution (R1)

**Files:**
- Modify: `packages/usac_runtime/src/usac_runtime/device_executor.py`
- Modify: `packages/usac_runtime/src/usac_runtime/application.py`
- Modify: `packages/usac_runtime/tests/test_device_executor.py`
- Modify: `packages/usac_runtime/tests/test_simulated_device_client.py`
- Modify: `packages/usac_runtime/tests/test_bridge_device_client.py`

**Interfaces:**
- Consumes: `ConfigurationSnapshot`, `ExecutedCapture`, and
  `AcquisitionApplication._persist_capture(...)`.
- Produces: `SingleDeviceExecutor.capture_once(..., on_capture)` returning the
  callback result only after the frame is durably resolved.

- [x] **Step 1: Write executor tests that require an in-lock callback and deep snapshot**

Add tests equivalent to:

```python
def test_single_capture_resolution_stays_inside_device_lock(executor) -> None:
    worker, client = executor
    applied = worker.apply_draft()
    callback_started = threading.Event()
    release_callback = threading.Event()

    def resolve(executed):
        callback_started.set()
        assert release_callback.wait(timeout=1)
        return executed

    result = []
    capture_thread = threading.Thread(
        target=lambda: result.append(
            worker.capture_once(
                expected_profile_sha256=str(applied.actual["profile_sha256"]),
                expected_device_config_crc32=int(applied.actual["device_config_crc32"]),
                trigger_source="SOFTWARE",
                sync_timeout_ms=0,
                on_capture=resolve,
            )
        )
    )
    capture_thread.start()
    assert callback_started.wait(timeout=1)
    status_thread = threading.Thread(target=worker.status)
    status_thread.start()
    assert client.status_started.wait(timeout=0.05) is False
    release_callback.set()
    capture_thread.join(timeout=1)
    status_thread.join(timeout=1)
    assert result[0].snapshot == applied


def test_single_capture_snapshot_has_no_shared_nested_mutable_values(executor) -> None:
    worker, _client = executor
    applied = worker.apply_draft()
    applied.actual["nested_probe"] = {"values": [1]}
    executed = worker.capture_once(
        expected_profile_sha256=str(applied.actual["profile_sha256"]),
        expected_device_config_crc32=int(applied.actual["device_config_crc32"]),
        trigger_source="SOFTWARE",
        sync_timeout_ms=0,
        on_capture=lambda item: item,
    )
    applied.actual["nested_probe"]["values"].append(2)
    assert executed.snapshot.actual["nested_probe"] == {"values": [1]}
```

- [x] **Step 2: Run the executor tests and verify RED**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest packages/usac_runtime/tests/test_device_executor.py -k "single_capture" -vv
```

Expected: failure because `capture_once` does not accept `on_capture` and does
not deep-copy nested snapshot data.

- [x] **Step 3: Implement the minimal executor transaction**

Add `copy.deepcopy` and change the executor operation to this contract:

```python
from copy import deepcopy
from typing import TypeVar

T = TypeVar("T")


def _deep_snapshot(snapshot: ConfigurationSnapshot) -> ConfigurationSnapshot:
    return ConfigurationSnapshot(
        state=snapshot.state,
        requested=deepcopy(snapshot.requested),
        actual=deepcopy(snapshot.actual),
        readback=deepcopy(snapshot.readback),
    )


def capture_once(
    self,
    *,
    expected_profile_sha256: str,
    expected_device_config_crc32: int,
    trigger_source: str,
    sync_timeout_ms: int,
    on_capture: Callable[[ExecutedCapture], T] | None = None,
) -> T | ExecutedCapture:
    with self._lock:
        self._refresh_session_unlocked()
        self._require_applied_identity_unlocked(
            expected_profile_sha256, expected_device_config_crc32
        )
        self._validate_trigger(trigger_source, sync_timeout_ms)
        executed = ExecutedCapture(
            capture=self._client.capture_once(
                config=self._applied_config,
                trigger_source=trigger_source,
                sync_timeout_ms=sync_timeout_ms,
            ),
            sweep_index=None,
            loop_index=0,
            snapshot=_deep_snapshot(self._snapshot),
        )
        return executed if on_capture is None else on_capture(executed)
```

Update existing tests that inspect the old raw return value to read
`result.capture`.

- [x] **Step 4: Write the BridgeDeviceClient interleaving regression**

In `test_bridge_device_client.py`, use `socket.socketpair`, the existing bridge
test server helper, `BridgeDeviceClient`, and a persistence
barrier. Start the draft request while persistence is paused, release the
barrier, and assert:

```python
assert archived.sample_interval_ticks == 120
assert archived.requested_config["sample_interval_ticks"] == 120
assert archived.readback_config["sample_interval_ticks"] == 120
assert archived.actual_config["sample_rate_hz"] == 200_000.0
assert draft_result["requested"]["sample_interval_ticks"] == 240
```

The fixture must use temporary SQLite/spool paths and must close both sockets in
`finally`; it must not use a serial port. The concurrent `/device` response is
tested in Task 2 because its non-blocking behavior depends on the R5 published
view rather than the R1 capture identity transaction.

- [x] **Step 5: Run the interleaving test and verify RED**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest packages/usac_runtime/tests/test_bridge_device_client.py::test_single_capture_keeps_applied_context_until_delivery_is_resolved -vv
```

Expected before the application change: the capture result is not resolved
inside the callback contract or stored metadata follows the later draft.

- [x] **Step 6: Route application persistence through the callback**

Replace the post-executor persistence sequence with:

```python
def resolve(executed: ExecutedCapture) -> _PersistedCapture:
    if not isinstance(executed.capture, CaptureData):
        raise TypeError("device client returned an unsupported capture object")
    return self._persist_capture(
        executed.capture,
        run_plan=run_plan,
        snapshot=executed.snapshot,
        save_policy=storage_policy,
        session_id=session_id,
        on_resolved=record_resolved,
    )

persisted = self._executor.capture_once(
    expected_profile_sha256=expected_profile_sha256,
    expected_device_config_crc32=expected_device_config_crc32,
    trigger_source=trigger_source,
    sync_timeout_ms=sync_timeout_ms,
    on_capture=resolve,
)
```

Derive `capture_id` from `persisted.payload` after the callback returns; do not
read a second configuration snapshot in `_persist_capture`.

- [x] **Step 7: Verify GREEN and commit R1**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest packages/usac_runtime/tests/test_device_executor.py packages/usac_runtime/tests/test_simulated_device_client.py packages/usac_runtime/tests/test_bridge_device_client.py::test_single_capture_keeps_applied_context_until_delivery_is_resolved packages/usac_runtime/tests/test_m5_api.py -q
git diff --check
git add -- packages/usac_runtime/src/usac_runtime/device_executor.py packages/usac_runtime/src/usac_runtime/application.py packages/usac_runtime/tests/test_device_executor.py packages/usac_runtime/tests/test_simulated_device_client.py packages/usac_runtime/tests/test_bridge_device_client.py
git commit -m "fix: bind single capture to durable configuration context"
```

Expected: focused tests pass and the commit contains only R1 behavior/tests.

---

### Task 2: Publish a complete non-blocking device view (R5)

**Files:**
- Modify: `packages/usac_runtime/src/usac_runtime/device_executor.py`
- Modify: `packages/usac_runtime/src/usac_runtime/bridge_device_client.py`
- Modify: `packages/usac_runtime/src/usac_runtime/application.py`
- Modify: `packages/usac_runtime/tests/test_bridge_device_client.py`
- Modify: `packages/usac_runtime/tests/test_m5_api.py`
- Modify: `packages/usac_runtime/tests/test_m5_server.py`

**Interfaces:**
- Consumes: completed bridge HELLO, executor activity, status, and capabilities.
- Produces: immutable `PublishedDeviceSession`, `DeviceViewSnapshot`, and
  `SingleDeviceExecutor.try_device_view()` with non-blocking refresh.

- [x] **Step 1: Write real-wrapper cache and lock-race tests**

Cover these behaviors using a real `ReconnectableBridgeDeviceClient` wrapping
the socketpair-backed `BridgeDeviceClient`:

```python
assert wrapper.published_session.connected is True
assert wrapper.published_session.device_id == bridge_client.device_id
wrapper.close()
assert wrapper.published_session.connected is False
assert wrapper.published_session.device_id is None
```

Start a Sweep whose `start_delay_ms` wait owns the executor lock, then assert:

```python
started = time.monotonic()
payload = application.device()
assert time.monotonic() - started < 0.25
assert payload["activity"] == "SWEEPING"
assert payload["device_id"] == expected_device_id.hex()
```

Also replace the bridge session while the old view exists and assert the new
boot/device/generation replace the old identity atomically.

- [x] **Step 2: Run the new tests and verify RED**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest packages/usac_runtime/tests/test_device_view.py packages/usac_runtime/tests/test_bridge_device_client.py packages/usac_runtime/tests/test_m5_server.py -k "published or device_view or sweep" -vv
```

Expected: current `/device` blocks or the wrapper has no non-blocking published
session view.

- [x] **Step 3: Add immutable published view types**

Define the executor-facing values without mutable dictionaries:

```python
@dataclass(frozen=True, slots=True)
class PublishedDeviceSession:
    connected: bool
    backend: str
    session_generation: int
    hello: object | None
    device_id: bytes | None
    boot_id: bytes | None


@dataclass(frozen=True, slots=True)
class DeviceViewSnapshot:
    session: PublishedDeviceSession
    status: object | None
    capabilities: object | None
    diagnostics_observed_utc_ns: int | None
```

`ReconnectableBridgeDeviceClient` stores one `PublishedDeviceSession` reference
and returns it without acquiring `_lock`. `replace`, `close`, and transport-loss
handling assign a complete new value after changing `_client`; they never edit
the published object in place.

- [x] **Step 4: Implement non-blocking executor refresh**

Add a cached `DeviceViewSnapshot` and use an immediate lock attempt:

```python
def try_device_view(self, *, refresh: bool) -> DeviceViewSnapshot:
    published = self._client.published_session
    cached = self._merge_published_session(self._device_view, published)
    self._device_view = cached
    if not refresh or not self._lock.acquire(blocking=False):
        return cached
    try:
        self._refresh_session_unlocked()
        published = self._client.published_session
        if not published.connected:
            return self._publish_disconnected_view(published)
        return self._publish_diagnostics(
            published,
            status=self._client.status(),
            capabilities=self._client.capabilities(),
            observed_utc_ns=time.time_ns(),
        )
    finally:
        self._lock.release()
```

For the simulator, publish the same session interface from in-memory values.
No `/device` response path may directly access live `connected`, `hello`,
`session_generation`, `status`, or `capabilities` properties.

- [x] **Step 5: Make `/device` publish activity before optional refresh**

Compute activity under `_session_lock`, then call:

```python
view = self._executor.try_device_view(refresh=activity == "IDLE")
return self._device_payload(view, activity=activity)
```

The unavailable payload gains `session_generation` and
`diagnostics_observed_utc_ns` with `None` values. Update exact API assertions in
`test_m5_server.py`.

- [x] **Step 6: Verify GREEN and commit R5**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest packages/usac_runtime/tests/test_bridge_device_client.py packages/usac_runtime/tests/test_m5_server.py packages/usac_runtime/tests/test_m5_api.py -q
git diff --check
git add -- packages/usac_runtime/src/usac_runtime/device_executor.py packages/usac_runtime/src/usac_runtime/bridge_device_client.py packages/usac_runtime/src/usac_runtime/application.py packages/usac_runtime/src/usac_runtime/simulated_device_client.py packages/usac_runtime/tests/test_bridge_device_client.py packages/usac_runtime/tests/test_m5_server.py packages/usac_runtime/tests/test_m5_api.py
git commit -m "fix: publish nonblocking device status snapshots"
```

Expected: wrapper/session invalidation and Sweep response tests pass.

---

### Task 3: Expose complete public capture metadata (R4)

**Files:**
- Modify: `packages/usac_runtime/src/usac_runtime/core_store.py`
- Modify: `packages/usac_runtime/src/usac_runtime/application.py`
- Modify: `packages/usac_runtime/tests/test_core_store.py`
- Modify: `packages/usac_runtime/tests/test_m5_api.py`

**Interfaces:**
- Consumes: the existing decoded `CaptureData` wire fields.
- Produces: the same additive metadata fields for archived and transient capture
  payloads.

- [x] **Step 1: Write SAVE_ALL/SAVE_NONE metadata parity tests**

For one deterministic simulated frame, assert both payloads expose:

```python
PUBLIC_FRAME_FIELDS = (
    "adc_bits", "sample_encoding", "vref_mv", "smclk_nominal_hz",
    "smclk_calibrated_hz", "frame_start_tick48", "t_trigger_offset_ticks",
    "adc0_hold_offset_ticks", "adc_aperture_ns", "trigger_to_tx_output_ns",
    "calibration_version", "out3_start_level", "out4_start_level",
)

for name in PUBLIC_FRAME_FIELDS:
    assert save_all[name] == save_none[name] == getattr(decoded_capture, name)
assert save_all["quality_flags"] == save_none["quality_flags"]
```

Also assert `smclk_calibrated_hz == 0` remains zero when the input frame says it
is unknown.

- [x] **Step 2: Run the metadata tests and verify RED**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest packages/usac_runtime/tests/test_core_store.py packages/usac_runtime/tests/test_m5_api.py -k "metadata" -vv
```

Expected: at least the 13 additive public fields are missing.

- [x] **Step 3: Populate CaptureRecord from its authoritative wire frame**

Add the 13 fields to `CaptureRecord`. In `get_capture`, decode once and populate
them exactly:

```python
wire_frame = bytes(row[14])
capture = decode_capture_data(decode_frame(wire_frame).payload)
return CaptureRecord(
    # existing fields remain unchanged
    adc_bits=capture.adc_bits,
    sample_encoding=capture.sample_encoding,
    vref_mv=capture.vref_mv,
    smclk_nominal_hz=capture.smclk_nominal_hz,
    smclk_calibrated_hz=capture.smclk_calibrated_hz,
    frame_start_tick48=capture.frame_start_tick48,
    t_trigger_offset_ticks=capture.t_trigger_offset_ticks,
    adc0_hold_offset_ticks=capture.adc0_hold_offset_ticks,
    adc_aperture_ns=capture.adc_aperture_ns,
    trigger_to_tx_output_ns=capture.trigger_to_tx_output_ns,
    calibration_version=capture.calibration_version,
    out3_start_level=capture.out3_start_level,
    out4_start_level=capture.out4_start_level,
)
```

- [x] **Step 4: Use one serializer for archived and transient metadata**

Add a helper whose keys exactly match `PUBLIC_FRAME_FIELDS`, use it from
`_capture_payload`, and merge the same keys into transient payloads. Do not
derive, normalize, or substitute any calibration value.

- [x] **Step 5: Verify GREEN and commit R4**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest packages/usac_runtime/tests/test_core_store.py packages/usac_runtime/tests/test_m5_api.py -q
git diff --check
git add -- packages/usac_runtime/src/usac_runtime/core_store.py packages/usac_runtime/src/usac_runtime/application.py packages/usac_runtime/tests/test_core_store.py packages/usac_runtime/tests/test_m5_api.py
git commit -m "feat: expose complete capture frame metadata"
```

Expected: archived and transient contracts match without a schema migration.

---

### Task 4: Correct Web task lifecycle, periodic controls, and live waveform (R2, R3, R6)

**Files:**
- Modify: `packages/usac_runtime/src/usac_runtime/web/index.html`
- Modify: `packages/usac_runtime/src/usac_runtime/web/m5-app.js`
- Create: `packages/usac_runtime/tests/test_m5_app.cjs`
- Modify: `packages/usac_runtime/tests/test_m5_api.py`
- Modify: `scripts/test-all.ps1`
- Modify: `scripts/test-all.sh`

**Interfaces:**
- Consumes: existing `/sessions/{id}`, `/captures/{id}/samples`, configuration,
  periodic, and Sweep REST routes.
- Produces: mode-correct controls, resilient task ownership, and one-slot live
  waveform refresh.

- [ ] **Step 1: Convert the external UI probe into repository regression tests**

Create a Node VM test that removes only the terminal `init()` invocation and
executes the real functions. Its assertions shall include:

```javascript
assert.equal(activeAfterDraftError.mode, "PERIODIC");
assert.equal(stopDisabledAfterDraftError, false);
assert.equal(periodicTriggerContainer.hidden, true);
assert.equal(triggerSelect.disabled, true);
assert.equal(Object.hasOwn(periodicRequest, "trigger_source"), false);
assert.deepEqual(sampleRequests, [
  "/api/v1/captures/capture-1/samples",
  "/api/v1/captures/capture-2/samples",
]);
assert.equal(scheduledPollsAfterWaveformFailure > 0, true);
assert.equal(activeAfterTerminalRefreshFailure, null);
assert.equal(activeAfterSingleDisplayFailure, null);
```

The stub stores only request paths, timeout callbacks, and the latest canvas
values. It must assert that no frame/sample array is appended across polls.

- [ ] **Step 2: Run the UI test and verify RED**

Run:

```powershell
node .\packages\usac_runtime\tests\test_m5_app.cjs
```

Expected: current generic guard clears the active task, periodic controls remain
visible, and RUNNING sessions do not request samples.

- [ ] **Step 3: Separate generic errors from capture ownership**

Replace the generic guard with:

```javascript
const guarded = (operation) => () => operation().catch((error) => {
  setHardwareActions();
  toast(error.message);
});
```

For SINGLE, clear busy state in `finally` around only the capture request; draw
and history refresh run after cleanup with independent error reporting. For a
terminal periodic/Sweep payload, copy the capture ID, clear `state.active`,
publish terminal controls, then attempt display/history refresh.

- [ ] **Step 4: Keep polling independent of display failures**

Use one scheduler and one latest-rendered ID:

```javascript
function scheduleSessionPoll() {
  if (state.active) window.setTimeout(() => pollSession(), 250);
}

async function refreshLatestWaveform(payload) {
  if (!payload.last_capture_id || payload.last_capture_id === state.lastRenderedCaptureId) return;
  await drawCapture(payload.last_capture_id);
  state.lastRenderedCaptureId = payload.last_capture_id;
}
```

`pollSession()` schedules the next poll in `finally` only when the same session
is still active. Waveform errors are toasted and do not escape through the
session scheduler.

- [ ] **Step 5: Hide and disable periodic trigger controls**

Wrap both controls in `id="trigger-fields"`. In `updateMode()`:

```javascript
const triggerApplies = mode !== "PERIODIC";
$("#trigger-fields").hidden = !triggerApplies;
$("#trigger-source").disabled = !triggerApplies;
$("#sync-timeout").disabled = !triggerApplies;
$("#periodic-trigger-hint").hidden = triggerApplies;
```

Add Chinese and English text stating that PERIODIC uses the firmware internal
timer. Keep PERIODIC request JSON unchanged.

- [ ] **Step 6: Add the Node regression to both aggregate gates**

After pytest and before firmware/Docker work, invoke:

```powershell
node (Join-Path $repositoryRoot 'packages\usac_runtime\tests\test_m5_app.cjs')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

and on Linux:

```sh
node packages/usac_runtime/tests/test_m5_app.cjs
```

- [ ] **Step 7: Verify GREEN and commit the Web fixes**

Run:

```powershell
node --check .\packages\usac_runtime\src\usac_runtime\web\m5-app.js
node .\packages\usac_runtime\tests\test_m5_app.cjs
& .\.venv\Scripts\python.exe -m pytest packages/usac_runtime/tests/test_m5_api.py -q
git diff --check
git add -- packages/usac_runtime/src/usac_runtime/web/index.html packages/usac_runtime/src/usac_runtime/web/m5-app.js packages/usac_runtime/tests/test_m5_app.cjs packages/usac_runtime/tests/test_m5_api.py scripts/test-all.ps1 scripts/test-all.sh
git commit -m "fix: preserve web capture task control"
```

Expected: UI logic, syntax, and API static-contract tests pass.

---

### Task 5: Make the Linux container smoke bounded (R7)

**Files:**
- Modify: `scripts/test-all.sh`
- Modify: `tests/integration/test_project_layout.py`

**Interfaces:**
- Consumes: built `tuss4470-acquisition-core:m1-arm64` image.
- Produces: terminating ARM64 import/protocol smoke followed by the existing
  AMD64 OCI export.

- [ ] **Step 1: Write a static ordering and entrypoint-override regression**

Extend `test_host_automation_matches_the_platform_split`:

```python
arm64_run = "docker run --rm --platform linux/arm64 --entrypoint python"
amd64_export = "docker buildx build --platform linux/amd64"
protocol_smoke = "usac_protocol.frame"
assert arm64_run in jetson_test
assert protocol_smoke in jetson_test
assert jetson_test.index(arm64_run) < jetson_test.index(amd64_export)
```

- [ ] **Step 2: Run the layout test and verify RED**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/integration/test_project_layout.py -k "platform_split" -vv
```

Expected: current Docker run has no entrypoint override.

- [ ] **Step 3: Replace the service launch with a terminating smoke**

Use this shape in `test-all.sh`:

```sh
docker run --rm --platform linux/arm64 --entrypoint python \
    tuss4470-acquisition-core:m1-arm64 -c \
    'from usac_protocol.frame import Frame, MessageType, decode_frame, encode_frame; raw = encode_frame(Frame(MessageType.GET_STATUS, 1, b"")); assert decode_frame(raw).message_type is MessageType.GET_STATUS'
```

Do not add background services or arbitrary sleeps.

- [ ] **Step 4: Verify GREEN and commit R7**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/integration/test_project_layout.py -q
git diff --check
git add -- scripts/test-all.sh tests/integration/test_project_layout.py
git commit -m "fix: bound linux container smoke test"
```

Expected: static regression passes; actual Docker execution is reserved for the
Jetson integration step.

---

### Task 6: Run full offline gates and close the review patch

**Files:**
- Create: `docs/verification/M6/external-review-remediation.md`
- Modify: `README.md`
- Modify when command text is stale: `deploy/README-jetson.md`
- Modify outside repository: `D:\Desktop\工作\2026\02-BMS\docs\superpowers\plans\2026-08-20-tuss4470-ultrasonic-acquisition-module-roadmap.md`

**Interfaces:**
- Consumes: all R1–R7 tests and prior M6 evidence.
- Produces: traceable review resolution, merged/pushed main, Jetson sync, and
  cleaned owned worktrees.

- [ ] **Step 1: Run the Windows aggregate gate**

Run from the activated worktree environment:

```powershell
& .\scripts\test-all.ps1
```

Expected: all Python, Node, firmware build, static, simulator, and scheduling
checks pass; no COM port, flashing, or Burst occurs. Stop and report if the
command remains active beyond the agreed bound.

- [ ] **Step 2: Run source and staged-scope checks**

Run:

```powershell
node --check .\packages\usac_runtime\src\usac_runtime\web\m5-app.js
git diff --check
git status --short
git diff --stat main...HEAD
```

Expected: syntax/whitespace pass and the branch contains only the approved
review remediation.

- [ ] **Step 3: Write the formal verification record**

The new document begins with `Document overview` and records a table with one
row per R1–R7 containing: defect, changed contract, exact automated test,
result, and remaining limitation. It explicitly states that firmware and
hardware were not changed or revalidated.

README gains a short pointer to this maintenance record. The controlled roadmap
records a dated post-M6 maintenance checkpoint without reopening M6 or marking
M7 complete.

- [ ] **Step 4: Commit documentation and final branch state**

Run:

```powershell
git add -- README.md deploy/README-jetson.md docs/verification/M6/external-review-remediation.md
git diff --cached --check
git commit -m "docs: record external review remediation"
git status --short
```

Expected: repository worktree is clean. The external controlled roadmap is
verified separately because it is outside this Git repository.

- [ ] **Step 5: Integrate and push after final review**

From the clean main checkout:

```powershell
git checkout main
git merge --ff-only codex/m6-external-review-fixes
. .\.venv\Scripts\Activate.ps1
& .\scripts\test-all.ps1
git push origin main
git rev-parse HEAD
git ls-remote origin refs/heads/main
```

Expected: merged tests pass and local/remote 40-character SHAs match. Do not
force-push.

- [ ] **Step 6: Sync and run bounded Jetson verification**

On the Jetson formal checkout:

```sh
cd /home/yizhouzhao/workspace/TUSS4470_software
git pull --ff-only origin main
. .venv/bin/activate
timeout 60s .venv/bin/python -m pytest -q
node packages/usac_runtime/tests/test_m5_app.cjs
timeout 60s ./scripts/test-all.sh
```

If missing development dependencies prevent pytest, record that environment
fact and run the Docker ARM64 smoke plus AMD64 export steps individually with
the same 60-second bound. These checks do not require USB, serial access, or
external 7 V.

- [ ] **Step 7: Clean the owned worktrees after successful integration**

Verify the Windows and Jetson main checkouts are clean and at the pushed SHA,
then remove only the `.worktrees/m6-external-review-fixes` worktree created for
this patch and prune stale registration. Delete the local repair branch only
after merge; retain the remote branch if it was pushed as traceable review
history.
