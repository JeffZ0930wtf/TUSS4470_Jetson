# External Review Follow-up Implementation Plan

## Document overview

This plan implements the two follow-up findings accepted after commit
`e62ee8f`: duplicate periodic starts must not disturb an active session, and
the device page must recover from the first disconnect observation or request
failure. It applies only to the post-M6 host/API/Web maintenance branch and is
subordinate to the external-review remediation design and staged roadmap.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans
> to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** Close the two follow-up regressions with deterministic tests and the
smallest host-side changes.

**Architecture:** Keep the backend as the authority by rejecting conflicting
starts before any callback or delivery-policy mutation. Add a provisional Web
start state for immediate operator feedback, and preserve one device-refresh
timer chain across both success and failure. Convert expected first-disconnect
exceptions into the reconnecting client's published immutable snapshot.

**Tech Stack:** Python 3.12, FastAPI, SQLite/WAL, pytest, plain JavaScript,
Node VM tests.

## Global Constraints

- Work only in `.worktrees/m6-external-review-followup` on branch
  `codex/m6-external-review-followup` until integration.
- Use test-first red-green cycles; observe each new test fail for the expected
  defect before editing production code.
- Do not access COM9, flash firmware, issue Burst, or require external 7 V.
- Do not change firmware, wire messages, SQLite schema, capture parameters, or
  M6/M7 scope.
- Keep every command bounded to 60 seconds and stop rather than repeatedly
  reconnecting or rerunning a stalled command.
- Preserve existing REST request/response compatibility and the single-device
  execution model.

---

### Task 1: Preserve the active periodic owner on duplicate start

**Files:**
- Modify: `packages/usac_runtime/tests/test_bridge_device_client.py`
- Modify: `packages/usac_runtime/src/usac_runtime/application.py`
- Modify: `packages/usac_runtime/src/usac_runtime/core_store.py`

**Interfaces:**
- Consumes: `AcquisitionApplication.start_periodic(...)`,
  `BridgeDeviceClient.set_async_capture_handler(...)`, and the existing
  `_serve_capture_before_renew_response(..., renewal_fails_after_capture=True)`
  socket scenario.
- Produces: conflict rejection with no mutation of the active handler or
  delivery policy; conditional cleanup through
  `CaptureStore.unregister_delivery_policy(device_id, boot_id, session_id)`.

- [x] **Step 1: Add the deterministic failing regression**

Gate the original worker immediately before its first renewal, call
`start_periodic` a second time, and then release the renewal. The assertion set
must include:

```python
with pytest.raises(SessionConflict):
    application.start_periodic(**same_request)

assert device._async_capture_handler is original_handler
assert status["state"] == "COMPLETED"
assert status["capture_count"] == 1
assert status["last_capture_id"] is not None
assert spool.pending_records() == []
```

Read the `delivery_policy_contexts` row for the active device boot and assert
its `session_id` remains the original session ID. The injected socket peer must
send the final frame while renewal waits for its response and must then reject
that renewal.

- [x] **Step 2: Run the focused test and observe RED**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest packages/usac_runtime/tests/test_bridge_device_client.py::test_duplicate_start_preserves_final_capture_during_failed_renewal -q
```

Expected: the original session is `FAILED`, its handler identity changes, or
`last_capture_id` is absent. A setup/import error is not an acceptable RED.

- [x] **Step 3: Implement the minimal atomic transition**

Move periodic conflict detection ahead of snapshot, handler installation, and
delivery-policy registration, and retain `_session_lock` through ownership
publication. On startup failure, clear only this attempt's handler and remove
only its policy:

```python
with self._session_lock:
    if any(item.state in {"RUNNING", "STOPPING"}
           for item in self._sessions.values()):
        raise SessionConflict("the device already has an active run session")
    self._prune_finished_sessions_locked()
    # construct snapshot/session and register its replay policy
    try:
        install_handler(persist_interleaved)
        controller.start(schedule, now_ms=now_ms)
    except Exception:
        self._clear_async_capture_handler(persist_interleaved)
        store.unregister_delivery_policy(
            device_id=device_id,
            boot_id=boot_id,
            session_id=session.session_id.hex(),
        )
        raise
```

`unregister_delivery_policy` shall use a conditional SQL delete on all three
identity fields so a failed old attempt cannot remove newer ownership. Do not
introduce a queue or new session state.

- [x] **Step 4: Run focused and neighboring periodic tests GREEN**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest packages/usac_runtime/tests/test_bridge_device_client.py packages/usac_runtime/tests/test_periodic_lease.py -q
```

Expected: all selected tests pass, including the new deterministic
interleaving.

- [x] **Step 5: Commit the backend fix**

```powershell
git add -- packages/usac_runtime/src/usac_runtime/application.py packages/usac_runtime/src/usac_runtime/core_store.py packages/usac_runtime/tests/test_bridge_device_client.py
git diff --cached --check
git commit -m "fix: preserve active periodic session on duplicate start"
```

---

### Task 2: Return the disconnected snapshot on the first failed query

**Files:**
- Modify: `packages/usac_runtime/tests/test_m5_api.py`
- Modify: `packages/usac_runtime/src/usac_runtime/device_executor.py`

**Interfaces:**
- Consumes: `ReconnectableBridgeDeviceClient.published_session` and
  `SingleDeviceExecutor.try_device_view(refresh=True)`.
- Produces: the first `/api/v1/device` request that discovers a transport loss
  returns HTTP 200 with a disconnected, diagnostic-free snapshot.

- [x] **Step 1: Add the failing API regression**

Use a closable `SimulatedDeviceClient` whose first `status()` raises
`ConnectionError`, wrap it in `ReconnectableBridgeDeviceClient`, and call the
real API once:

```python
response = client.get("/api/v1/device")
assert response.status_code == 200
assert response.json()["connected"] is False
assert response.json()["health"] == "NOT_DETECTED"
assert response.json()["status"] is None
assert response.json()["session_generation"] == 1
```

Also assert device and boot identity plus capabilities are absent so cached
diagnostics cannot leak across a generation change.

- [x] **Step 2: Run the focused test and observe RED**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest packages/usac_runtime/tests/test_m5_api.py::test_first_device_query_returns_disconnected_snapshot -q
```

Expected: HTTP 500 caused by propagated `DeviceUnavailable`.

- [x] **Step 3: Catch only expected device unavailability**

In `try_device_view`, catch `DeviceUnavailable` around the refresh/status/
capabilities sequence, reread the published session, and replace the cached
view with empty diagnostics:

```python
except DeviceUnavailable:
    self._device_view = DeviceViewSnapshot(
        self._published_session(), None, None, None
    )
    return self._device_view
```

Leave the `finally` lock release in place and do not catch broad exceptions.

- [x] **Step 4: Run API/device-view tests GREEN and commit**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest packages/usac_runtime/tests/test_m5_api.py -q
```

Then commit:

```powershell
git add -- packages/usac_runtime/src/usac_runtime/device_executor.py packages/usac_runtime/tests/test_m5_api.py
git diff --cached --check
git commit -m "fix: publish first device disconnect without HTTP 500"
```

---

### Task 3: Guard pending starts and keep one device polling chain

**Files:**
- Modify: `packages/usac_runtime/tests/test_m5_app.cjs`
- Modify: `packages/usac_runtime/src/usac_runtime/web/m5-app.js`

**Interfaces:**
- Consumes: `startCapture()`, `setHardwareActions()`, and `refreshDevice()`.
- Produces: one start request while its response is pending and exactly one
  subsequent refresh timer after either device-query success or failure.

- [x] **Step 1: Add two failing Node regressions**

Extend the harness with a deferred response. While the first PERIODIC start is
unresolved, invoke the start action twice and assert:

```javascript
assert.equal(ui.run("state.active.pending"), true);
assert.equal(ui.node("#capture-start").disabled, true);
assert.equal(ui.node("#capture-stop").disabled, true);
assert.equal(startRequests.length, 1);
```

In a separate harness, make the first device request fail, execute the one
scheduled timer, then return a connected payload. Assert one timer is queued
after each attempt and the successful payload updates `state.connected`.

- [x] **Step 2: Run the Node test and observe RED**

Run:

```powershell
node packages/usac_runtime/tests/test_m5_app.cjs
```

Expected: no provisional active state and/or the initial failed refresh leaves
no next timer. A harness syntax error is not an acceptable RED.

- [x] **Step 3: Implement the minimal Web state changes**

Make `startCapture()` return immediately when a task already owns the page.
For PERIODIC/SWEEP, publish an identity-checked provisional object before the
request, replace it on success, and clear it on failure. Update stop gating:

```javascript
$("#capture-stop").disabled = !state.active ||
  state.active.mode === "SINGLE" || Boolean(state.active.pending);
```

Make `refreshDevice()` own one timer in `finally`:

```javascript
async function refreshDevice() {
  try {
    const { payload } = await fetchJson("/api/v1/device");
    updateDevice(payload);
  } catch (error) {
    toast(error.message);
  } finally {
    window.setTimeout(refreshDevice, 1000);
  }
}
```

Do not add exponential backoff, another scheduler, or a front-end framework.

- [x] **Step 4: Run Node syntax and behavior tests GREEN and commit**

Run:

```powershell
node --check packages/usac_runtime/src/usac_runtime/web/m5-app.js
node packages/usac_runtime/tests/test_m5_app.cjs
```

Then commit:

```powershell
git add -- packages/usac_runtime/src/usac_runtime/web/m5-app.js packages/usac_runtime/tests/test_m5_app.cjs
git diff --cached --check
git commit -m "fix: keep web start and device polling state recoverable"
```

---

### Task 4: Verify and close the follow-up maintenance patch

**Files:**
- Modify: `docs/verification/M6/external-review-remediation.md`
- Modify outside repository: controlled staged roadmap maintenance checkpoint

**Interfaces:**
- Consumes: the three focused green cycles.
- Produces: a traceable follow-up verification record and clean branch ready
  for review, push, Jetson synchronization, and worktree archival.

- [x] **Step 1: Run the bounded offline aggregate gate**

```powershell
& .\scripts\test-all.ps1
```

Expected: Python, Node, firmware/static, and simulator checks pass within 60
seconds without COM access, flashing, or Burst.

- [x] **Step 2: Run final source-scope checks**

```powershell
node --check packages/usac_runtime/src/usac_runtime/web/m5-app.js
git diff --check
git status --short
git diff --stat main...HEAD
```

Expected: clean syntax/whitespace and only the approved follow-up scope.

- [x] **Step 3: Record evidence and commit closure**

Add a dated follow-up subsection mapping each reproduced defect to its focused
test and result. State explicitly that no firmware/hardware behavior changed
and no hardware was accessed. Update the external controlled roadmap with the
same post-M6 maintenance checkpoint.

```powershell
git add -- docs/verification/M6/external-review-remediation.md docs/superpowers/specs/2026-09-09-external-review-remediation-design.md docs/superpowers/plans/2026-09-09-external-review-followup.md
git diff --cached --check
git commit -m "docs: close external review follow-up"
```

- [x] **Step 4: Integrate only after final verification**

Fast-forward `main`, rerun the bounded aggregate gate, push without rewriting
history, synchronize the Jetson checkout to the exact pushed SHA, and archive
the owned worktree. If Jetson cannot fetch GitHub, use the previously verified
Git bundle transfer; do not change product code to work around networking.
