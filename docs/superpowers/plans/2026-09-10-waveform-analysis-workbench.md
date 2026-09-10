# Waveform Analysis Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a bilingual, centered waveform workbench that displays arbitrary contiguous raw windows, switches between raw and full-frame-normalized values, overlays at most 20 compatible captures, and shows the configured SQLite path without changing acquisition or storage semantics.

**Architecture:** Extend the existing FastAPI/SQLite metadata surface with additive read-only fields, then keep all waveform decoding, normalization, selection and drawing in the existing vanilla-JavaScript browser client. Reuse the current per-capture sample endpoint and Canvas 2D renderer; do not add a batch API, frontend framework, database migration, firmware change or wire-protocol change.

**Tech Stack:** Python 3.12, FastAPI, SQLite, vanilla JavaScript, HTML/CSS, Canvas 2D, Node test harness, pytest, Docker Compose.

## Document overview

This plan implements the approved design in `docs/superpowers/specs/2026-09-10-waveform-analysis-workbench-design.md`. It applies only to the post-M6 host Web/API and deployment-display maintenance increment. The controlled roadmap and `CONTRIBUTING.md` remain authoritative for repository workflow and hardware boundaries. Execution stops after Windows review readiness; Jetson synchronization and remote push require the user's later approval.

## Global Constraints

- Start execution in an isolated worktree created with `using-git-worktrees`; do not implement directly in `main`.
- Do not access COM9, flash firmware, power or trigger hardware, or produce a Burst.
- Do not modify MSP430 firmware, TUSS4470 control, USB/serial framing, capture transaction logic, save-policy semantics or SQLite schema.
- Preserve every raw sample exactly. Windowing selects consecutive original indices; it never interpolates, downsamples or synthesizes data.
- Normalize each curve from its complete frame to `0..1`; never persist or export normalized values.
- Count the primary curve, hidden selected curves and in-flight selected capture IDs together; the total is at most 20 distinct IDs.
- Use the existing individual `GET /api/v1/captures/{capture_id}/samples` endpoint; do not add a batch sample endpoint.
- All new user-visible text must exist in both Chinese and English in the existing `I18N` dictionary.
- Derive both Compose bind-mount source and displayed host database path from the same existing `USAC_CORE_DATA_DIR` value.
- Add no runtime dependency or frontend framework.
- Follow TDD: observe each targeted test fail before adding the minimal implementation, then run the targeted test again.

---

### Task 1: Complete read-only capture and storage metadata contracts

**Files:**
- Modify: `packages/usac_runtime/tests/test_m5_api.py`
- Modify: `packages/usac_runtime/tests/test_m5_server.py`
- Modify: `tests/integration/test_project_layout.py`
- Modify: `packages/usac_runtime/src/usac_runtime/core_store.py`
- Modify: `packages/usac_runtime/src/usac_runtime/application.py`
- Modify: `packages/usac_runtime/src/usac_runtime/m5_api.py`
- Modify: `packages/usac_runtime/src/usac_runtime/m5_server.py`
- Modify: `deploy/compose.yaml`
- Modify: `deploy/compose.jetson.yaml`

**Interfaces:**
- Extend `CaptureSummary` with `sample_interval_ticks: int` and `pretrigger_count: int`.
- Extend `AcquisitionApplication.__init__(..., store: CaptureStore | None = None, session_history_limit: int = 100, host_database_path: str | None = None)` with an optional display-only path.
- Make `AcquisitionApplication.capture(capture_id)` return `storage` for every successful branch: `TRANSIENT`, `ROLLING_LATEST`, or `ARCHIVE`.
- Add `AcquisitionApplication.storage() -> dict[str, str]` containing `backend`, `runtime_database_path`, `host_database_path`, and `path_mapping`.
- Add `GET /api/v1/storage` as a device-independent, read-only endpoint.
- Add `host_database_path: str | None = None` to `create_simulator_api` and `create_bridge_api`, plus CLI option `--host-database-path`; when absent, use the resolved runtime SQLite path.
- In Windows Compose, pass `${USAC_CORE_DATA_DIR:-D:/Desktop/TUSS4470_data/core}/acquisition.sqlite3` as display text; in Jetson Compose use `${USAC_CORE_DATA_DIR:-/var/lib/tuss4470/core}/acquisition.sqlite3`. Retain `/var/lib/usac/database/acquisition.sqlite3` as the runtime database in both containers.

- [x] **Step 1: Add failing history and capture-detail contract tests**

Extend the stable history-page test to require `sample_interval_ticks` and `pretrigger_count`. Extend capture metadata coverage so archived data returns `storage="ARCHIVE"`, and use the existing periodic `SAVE_LAST` scenario to assert the same capture ID reports `ROLLING_LATEST` before finalization and `ARCHIVE` after the terminal summary freezes it.

- [x] **Step 2: Run the focused API tests and confirm failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest packages/usac_runtime/tests/test_m5_api.py -q
```

Expected: FAIL because the history summary lacks two fields and archived detail lacks `storage`.

- [x] **Step 3: Implement the additive capture metadata fields**

Update both `list_captures` SELECT variants and row mapping. In the archived branch of `AcquisitionApplication.capture`, add `storage: "ARCHIVE"` to the returned payload without changing `_capture_payload`, database rows or resolution decisions.

- [x] **Step 4: Run the capture metadata tests and confirm success**

Run the command from Step 2.

Expected: all `test_m5_api.py` tests PASS.

- [x] **Step 5: Add failing storage endpoint and Compose source tests**

Test bare-host equality, explicit bind-mount mapping, device-disconnected access, and opaque Windows path handling. Update the project-layout test to require each Compose file to use `USAC_CORE_DATA_DIR` for both the mount source and displayed host database path.

- [x] **Step 6: Run the focused storage/layout tests and confirm failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest packages/usac_runtime/tests/test_m5_api.py tests/integration/test_project_layout.py -q
```

Expected: FAIL because `/api/v1/storage` and the display-path startup input do not exist.

- [x] **Step 7: Implement the storage endpoint and startup wiring**

Keep the host path as an opaque string: never call `Path.resolve()` on a Windows host path inside Linux. Derive `path_mapping` from whether the explicit display path differs from the runtime path. The endpoint must not acquire the device executor or inspect USB state.

- [x] **Step 8: Run the Task 1 tests**

Run the command from Step 6.

Expected: PASS with no database migration and no device access.

- [x] **Step 9: Commit Task 1**

```powershell
git add -- packages/usac_runtime/tests/test_m5_api.py packages/usac_runtime/tests/test_m5_server.py tests/integration/test_project_layout.py packages/usac_runtime/src/usac_runtime/core_store.py packages/usac_runtime/src/usac_runtime/application.py packages/usac_runtime/src/usac_runtime/m5_api.py packages/usac_runtime/src/usac_runtime/m5_server.py deploy/compose.yaml deploy/compose.jetson.yaml
git commit -m "feat: expose waveform metadata and storage paths"
```

---

### Task 2: Add the bounded waveform data model and renderer

**Files:**
- Modify: `packages/usac_runtime/tests/test_m5_app.cjs`
- Modify: `packages/usac_runtime/src/usac_runtime/web/m5-app.js`

**Interfaces:**
- Add pure helpers `decodeSamples(bytes, expectedCount)`, `normalizeFrame(samples)`, `validatedWindow(start, count, sampleCount)`, and `basisDifferences(left, right)`.
- Replace the single waveform summary state with a `Map` keyed by capture ID plus `primaryCaptureId`, `windowStart`, `windowCount`, `displayMode`, `followLatest`, `latestCaptureId`, and integer `viewRevision`.
- Each asynchronous load owns `{captureId, revision, loadToken}`. Success, failure and cleanup mutate state only while all three still identify the current reservation.
- Draw every original point in the selected contiguous window. A one-point window uses a centered marker and never divides by `count - 1`.
- Raw mode uses one shared auto-fit axis labelled in actual ADC counts; normalized mode uses a fixed `0..1` axis.

- [ ] **Step 1: Extend the Node harness for deterministic drawing assertions**

Record Canvas operations needed by the implementation (`moveTo`, `lineTo`, centered marker, labels and resize dimensions) without starting a browser or server.

- [ ] **Step 2: Add failing pure-behavior tests**

Cover little-endian decoding, odd-byte and count mismatch rejection, valid/invalid window bounds, previous/next window clamping, full-frame min-max normalization, constant-frame zeros, basis differences, all-point drawing and the single-point marker.

- [ ] **Step 3: Run the Node test and confirm failure**

Run:

```powershell
node packages/usac_runtime/tests/test_m5_app.cjs
```

Expected: FAIL because the helpers and multi-waveform renderer are absent.

- [ ] **Step 4: Implement the pure helpers and Canvas renderer**

Keep the functions in `m5-app.js` to match the existing no-build frontend. Cache complete `Uint16Array` frames and lazily computed normalized arrays. Resizing and display-mode/window changes redraw only from cache.

- [ ] **Step 5: Add failing selection-limit and request-ownership tests**

Assert that primary, hidden and in-flight IDs share one 20-ID limit; duplicate IDs count once; hiding does not free a slot; removal does. Reproduce A loading while the view changes to B and separately inject late success, late failure and late cleanup from A; none may alter B, show an A error or release B's reservation.

- [ ] **Step 6: Run the Node test and confirm the new failures**

Run the command from Step 3.

Expected: the new ownership/limit assertions FAIL before state management is added.

- [ ] **Step 7: Implement selection reservations and `viewRevision` isolation**

Reserve a distinct-ID slot before network loading. Increment the revision only when rebuilding the view group. Use a unique load token so an old request for the same capture ID cannot release a newer request's reservation.

- [ ] **Step 8: Run the Task 2 test**

Run the command from Step 3.

Expected: PASS, including late success/failure/finally isolation and one-point rendering.

- [ ] **Step 9: Commit Task 2**

```powershell
git add -- packages/usac_runtime/tests/test_m5_app.cjs packages/usac_runtime/src/usac_runtime/web/m5-app.js
git commit -m "feat: add bounded waveform overlay model"
```

---

### Task 3: Integrate the bilingual workbench, static history analysis and storage display

**Files:**
- Modify: `packages/usac_runtime/tests/test_m5_app.cjs`
- Modify: `packages/usac_runtime/tests/test_m5_api.py`
- Modify: `packages/usac_runtime/src/usac_runtime/web/index.html`
- Modify: `packages/usac_runtime/src/usac_runtime/web/m5-styles.css`
- Modify: `packages/usac_runtime/src/usac_runtime/web/m5-app.js`
- Modify: `README.md`
- Update after verification: `docs/superpowers/plans/2026-09-10-waveform-analysis-workbench.md`

**Interfaces:**
- History summaries decide whether a saved row may be selected before its samples are downloaded.
- Real-time/latest data loads metadata from `GET /api/v1/captures/{capture_id}` before loading samples; it never substitutes current page configuration.
- `followLatest=true` updates the current view. Viewing or selecting history sets it false while acquisition and polling continue. “Resume latest” rebuilds a one-waveform group from `latestCaptureId`.
- `SAVE_NONE` detail/sample 404 is skipped without ending polling. At `SAVE_LAST` terminal state, re-fetch detail for the same ID and update the label only when `storage="ARCHIVE"`; do not re-download cached samples.
- Storage UI calls `GET /api/v1/storage`, displays runtime and host paths, and offers copy only.

- [ ] **Step 1: Add failing DOM and lifecycle tests**

Require the new window controls, mode toggle, overlay counter, legend, resume-latest control, history checkboxes, storage-path card and parameter-bank jump. Test that history view/selection pauses following, live polling continues without replacing the view, and resume latest clears the static group and loads the latest metadata then samples.

- [ ] **Step 2: Add failing transient and `SAVE_LAST` lifecycle tests**

Assert that real-time frames request detail before samples, use returned frame metadata during Sweep, skip a transient 404 while scheduling the next poll, and update a rolling label only after the same ID's detail returns `ARCHIVE` at terminal state.

- [ ] **Step 3: Run focused Web/API tests and confirm failure**

Run:

```powershell
node packages/usac_runtime/tests/test_m5_app.cjs
.\.venv\Scripts\python.exe -m pytest packages/usac_runtime/tests/test_m5_api.py -q
```

Expected: FAIL because the new controls, interaction flow and storage card are not integrated.

- [ ] **Step 4: Restructure the HTML and responsive CSS**

Place acquisition first, the full-width waveform workbench second, history/storage below it, and the complete parameter bank last. Keep every existing parameter and acquisition control. On narrow screens stack history and storage vertically. Synchronize Canvas backing dimensions to its displayed size and device pixel ratio.

- [ ] **Step 5: Integrate history overlay and follow-latest behavior**

Use “View” to create a one-waveform static group and checkboxes to add/remove compatible rows. Display exact basis mismatches, short IDs, colors and hide/remove actions. Make all manual history analysis static; no live curve is dynamically mixed into that group.

- [ ] **Step 6: Integrate storage display and bilingual text**

Load storage information independently from device status. Show host/runtime labels appropriate to `same_as_runtime` or `bind_mount`; copy plain text only. Add Chinese and English strings for every new control, status and error, including “following latest”, “analysis view paused; acquisition continues”, transient/rolling/archive labels and constant-waveform notice.

- [ ] **Step 7: Run focused tests**

Run the command from Step 3.

Expected: both commands PASS.

- [ ] **Step 8: Run the complete offline repository gate**

Activate the repository virtual environment, then run:

```powershell
. .\.venv\Scripts\Activate.ps1
.\scripts\test-all.ps1
```

Expected: all Python, Node, firmware build/static and simulator checks PASS; the command must not open COM9, flash hardware or produce a Burst.

- [ ] **Step 9: Perform the Windows browser review setup**

Start the existing simulator-backed Web service on an unused localhost port. Verify the page loads with no browser-console error, then provide the URL to the user. Stop before Jetson synchronization, remote push or any real capture.

- [ ] **Step 10: Update documentation and record evidence**

Update `README.md` with the workbench behavior, raw-data guarantee, 20-ID rule, `followLatest` semantics and read-only storage-path display. Mark this plan's completed checkboxes and record exact targeted/full-gate results without claiming hardware verification.

- [ ] **Step 11: Commit Task 3**

```powershell
git add -- packages/usac_runtime/tests/test_m5_app.cjs packages/usac_runtime/tests/test_m5_api.py packages/usac_runtime/src/usac_runtime/web/index.html packages/usac_runtime/src/usac_runtime/web/m5-styles.css packages/usac_runtime/src/usac_runtime/web/m5-app.js README.md docs/superpowers/plans/2026-09-10-waveform-analysis-workbench.md
git commit -m "feat: add waveform analysis workbench"
```

## Completion checkpoint

Before asking for UI review, verify:

- the implementation worktree is clean;
- `git diff --check` passes for the complete increment;
- the three task commits contain only planned files and no firmware binary/source changes;
- the full offline gate result is recorded;
- the Windows simulator page is available for user review;
- no remote push or Jetson synchronization has occurred.

After the user approves the Windows interface, create a separate bounded closure step for merge/push and Jetson synchronization. Do not fold those actions into this implementation plan without that approval.
