# M6 Bilingual Host UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the M6 Windows host increment with replay-safe terminal sessions and a complete Chinese/English operator interface.

**Architecture:** Keep firmware, wire messages, REST payloads, and SQLite values unchanged. Resolve bridge replay from persisted host context, and render one HTML interface through a small JavaScript text catalogue selected by a browser-local language preference.

**Tech Stack:** Python 3.12, SQLite/WAL, FastAPI, plain HTML/CSS/JavaScript, pytest, Node syntax check, in-app browser smoke test.

## Global Constraints

- No COM port access, firmware flashing, Burst, or Jetson migration in this increment.
- Chinese is the default; the top-right control toggles Chinese and English.
- Translate operator-facing text only; never translate protocol identifiers or stored data.
- Add no third-party internationalization dependency.

---

### Task 1: Close terminal-session replay

**Files:**
- Modify: `packages/usac_runtime/src/usac_runtime/core_store.py`
- Test: `packages/usac_runtime/tests/test_core_store.py`

**Interfaces:**
- Consumes: `CaptureStore.commit_replayed_delivery(delivery)` and persisted `acquisition_sessions` rows.
- Produces: a replay decision that updates a terminal session and leaves no orphan `session_latest_captures` row.

- [x] Add a failing test that finalizes an interrupted `SAVE_LAST` session, replays a later frame, and expects the later frame to be the sole archived last capture with updated terminal counts.
- [x] Run that test and confirm it fails because a rolling row remains.
- [x] Make replay and terminal summary reconciliation one transaction for terminal sessions.
- [x] Run the focused core-store tests and confirm they pass.

### Task 2: Add the complete language switch

**Files:**
- Modify: `packages/usac_runtime/src/usac_runtime/web/index.html`
- Modify: `packages/usac_runtime/src/usac_runtime/web/m5-app.js`
- Modify: `packages/usac_runtime/src/usac_runtime/web/m5-styles.css`
- Test: `packages/usac_runtime/tests/test_m5_api.py`
- Test: `packages/usac_runtime/tests/test_m5_server.py`

**Interfaces:**
- Consumes: existing DOM element IDs and unchanged REST JSON fields.
- Produces: `I18N`, `t(key, values)`, and `setLanguage(language)` with `usac-language` local-storage persistence.

- [x] Add failing page-contract tests for the top-right language control, both catalogues, local-storage persistence, and translated dynamic device/acquisition terms.
- [x] Run the focused tests and confirm failure because the language interface does not exist.
- [x] Add translation markers to static HTML and route all dynamic operator text through `t`; retain Chinese fallbacks in markup.
- [x] Style the language control inside the existing instrument header without changing the page layout model.
- [x] Run focused tests, Node syntax check, full pytest, and bounded firmware/static gates.
- [x] Smoke-test Chinese/English switching, configuration readback, one simulated capture, counters, waveform, and saved history in the browser.
