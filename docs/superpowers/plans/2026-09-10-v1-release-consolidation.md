# TUSS4470 Acquisition Module V1.0 Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the accepted post-M6 acquisition module into a coherent, reproducible `v1.0.0` release by removing milestone names from active code and tooling, preserving offline export and safety evidence, consolidating current documentation, and publishing one verified release baseline without changing acquisition behavior.

**Architecture:** Keep the accepted two-service runtime: `usac-core` owns Web/API, configuration, orchestration, and SQLite; `usac-bridge` owns USB CDC, TCP forwarding, reconnection, and durable pending spool. Rename active host, Web, firmware, test, and build units by responsibility rather than milestone, remove superseded host utilities only after their still-needed behavior is migrated, and preserve historical evidence under `docs/archive/pre-v1/`. Treat all firmware renaming as behavior-preserving maintenance and compare loadable bytes, addresses, memory use, and static safety invariants against the `3bf041aee736980a413207640a36dcc1e3c2daf5` baseline.

**Tech Stack:** Python 3.12, FastAPI, Uvicorn, SQLite, pyserial, Docker Compose, JavaScript/Canvas, MSP430-GCC 9.3.1.11, TI MSP430 USB stack, PowerShell, pytest, Node.js, Git.

## Document overview

This plan defines the implementation and verification sequence for freezing the current TUSS4470 ultrasonic acquisition submodule as software release `v1.0.0`. It resolves misleading M0-M6 names in active files and commands, preserves the accepted hardware and data-integrity behavior, separates current operating documentation from development history, and records a release that can be reproduced on Windows and Jetson. It implements the post-M6 consolidation decision; it does not add acquisition features, change the wire protocol, change the database schema, or claim M7 production hardening.

## Global constraints

- Start from clean local `main` at `3bf041aee736980a413207640a36dcc1e3c2daf5`, with `origin/main` at the same SHA.
- Create one isolated `codex/v1-release-consolidation` worktree before implementation; do not develop this change directly in the main checkout.
- Preserve the established platform split: Windows validates Python, Web, protocol, and MSP430 firmware without Docker; Jetson performs the single native ARM64 image build and the single AMD64 cross-build.
- Preserve the accepted runtime boundary: browser/CLI -> `usac-core` -> `usac-bridge` -> USB CDC -> MSP430 -> TUSS4470.
- Preserve J2=TX, J3=RX, R12 removed, J1=8 nF, J4=6.8 nF, Standard power, VPWR 7.0 V, internal VDRV 5 V, and all existing fail-closed gates.
- Do not access COM9, flash firmware, or produce a Burst during rename and offline verification tasks.
- Preserve the USAC wire protocol `v1`, `/api/v1`, parameter schema `tuss4470-parameters-v1.yaml`, `AcquisitionConfigV2`, SQLite schema, stored raw bytes, and firmware version `0.2.0.2`.
- Software release `v1.0.0`, firmware `0.2.0.2`, and protocol `v1` are independent identifiers and must be recorded together rather than forced to match.
- Preserve complete offline export of `.usac`, `.u16le`, and `.json` from SQLite without requiring the Core service to run.
- Generate `requirements-container.lock.txt` from `uv.lock` with uv `0.12.5`; Docker must install third-party dependencies with hashes and execute the copied first-party source through the existing `PYTHONPATH`, avoiding an unlocked Python build-isolation environment inside the runtime image.
- Historical documents keep their original milestone terminology after moving under `docs/archive/pre-v1/`; active source, tests, commands, assets, build outputs, deployment files, and current documentation must not use milestone names as component identities.
- Preserve source ordering, compile options, preprocessor behavior, linker scripts, generated TI USB configuration, USB DMA fallback, and MSP430 memory ownership while renaming firmware units.
- A firmware rename is accepted only if the normalized loadable image bytes and addresses match the baseline, memory sizes and interrupt vectors match, and all retained static/unit checks pass. Stop and investigate any unexplained difference.
- Do not treat a whole-ELF hash difference caused by symbols, paths, or debug metadata as proof of behavior change; compare loadable content explicitly.
- Preserve current accepted limitations: uncalibrated timing, the 10,000 ms lease compromise, non-lossless 5 Hz scheduling, and incomplete long-running/reconnect hardening.
- Store reviewable text in Git under `docs/`; store firmware binaries, maps, disassemblies, raw logs, and bulky local evidence under ignored `D:/Desktop/TUSS4470_data/release/v1.0.0/`.
- Use TDD for behavior migration. Rename-only tasks require targeted tests before and after plus diff/whitespace review.
- Each task ends in a focused commit. Do not create the `v1.0.0` tag until Windows and Jetson release gates pass and local/remote `main` match.
- Freeze all runtime/build inputs in `V1_CANDIDATE_SHA` before building candidate artifacts. Later acceptance commits may change only `docs/`; the final tag is valid only when an explicit path-limited Git diff proves all runtime/build inputs still match that candidate.

---

## Target active structure

### Public commands

| Final command | Responsibility | Replaces |
|---|---|---|
| `usac-core` | Formal Web/API/Core server; real operation requires `--backend bridge` | `usac-m5-server` |
| `usac-bridge` | Long-running USB CDC/TCP bridge service; service options are accepted directly with no subcommand | replaces `usac-bridge serve`; legacy `capture/replay` exit |
| `usac-cli` | REST client for device, configuration, capture, session, history, and sample download | `usac-m5` |
| `usac-export` | Direct, offline SQLite inspection and complete `.usac`/`.u16le`/`.json` export | `usac-m4` |

The old M4 `usac-core`, `usac-m2-smoke`, `usac-m3-capture`, and `usac-m3-loopback` are not V1 public commands. Their source remains recoverable from Git history and the recorded pre-V1 baseline; they are not copied into the installed V1 package.

### Host and Web file mapping

| Current active path | Final active path |
|---|---|
| `packages/usac_runtime/src/usac_runtime/m5_server.py` | `packages/usac_runtime/src/usac_runtime/core_server.py` |
| `packages/usac_runtime/src/usac_runtime/m5_api.py` | `packages/usac_runtime/src/usac_runtime/api.py` |
| `packages/usac_runtime/src/usac_runtime/m5_cli.py` | `packages/usac_runtime/src/usac_runtime/client_cli.py` |
| `packages/usac_runtime/src/usac_runtime/m4_cli.py` | `packages/usac_runtime/src/usac_runtime/export_cli.py` |
| `packages/usac_runtime/src/usac_runtime/web/m5-app.js` | `packages/usac_runtime/src/usac_runtime/web/app.js` |
| `packages/usac_runtime/src/usac_runtime/web/m5-styles.css` | `packages/usac_runtime/src/usac_runtime/web/styles.css` |
| `packages/usac_runtime/tests/test_m5_server.py` | `packages/usac_runtime/tests/test_core_server.py` |
| `packages/usac_runtime/tests/test_m5_api.py` | `packages/usac_runtime/tests/test_api.py` |
| `packages/usac_runtime/tests/test_m5_cli.py` | `packages/usac_runtime/tests/test_client_cli.py` |
| `packages/usac_runtime/tests/test_m4_cli.py` | `packages/usac_runtime/tests/test_export_cli.py` |
| `packages/usac_runtime/tests/test_m5_app.cjs` | `packages/usac_runtime/tests/test_web_app.cjs` |

### Firmware file mapping

| Current active path pair | Final active path pair |
|---|---|
| `firmware/src/m2_main.c` | `firmware/src/main.c` |
| `firmware/src/m2_usb_events.c` | `firmware/src/usb_events.c` |
| `firmware/{src,include}/usac_m2_app.*` | `firmware/{src,include}/usac_firmware_app.*` |
| `firmware/{src,include}/usac_m2_core.*` | `firmware/{src,include}/usac_firmware_core.*` |
| `firmware/{src,include}/usac_m3_capture.*` | `firmware/{src,include}/usac_capture.*` |
| `firmware/{src,include}/usac_m3_capture_stream.*` | `firmware/{src,include}/usac_capture_stream.*` |
| `firmware/{src,include}/usac_m3_capture_tx.*` | `firmware/{src,include}/usac_capture_tx.*` |
| `firmware/{src,include}/usac_m3_loopback.*` | `firmware/{src,include}/usac_loopback.*` |
| `firmware/{src,include}/usac_m5_burst_plan.*` | `firmware/{src,include}/usac_burst_plan.*` |
| `firmware/{src,include}/usac_m5_schedule.*` | `firmware/{src,include}/usac_capture_schedule.*` |
| `firmware/{src,include}/usac_platform_m3_msp430.*` | `firmware/{src,include}/usac_acquisition_platform_msp430.*` |

First-party include guards, types, functions, constants, compile macros, comments, unit-test names, and static-check references that use M2/M3/M5 as component identities must change consistently with these files. Protocol/config version identifiers and historical evidence are excluded from this rename.

### Build and test file mapping

| Current path | Final path or disposition |
|---|---|
| `scripts/build-firmware-m5.ps1` plus `build-firmware-m2.ps1` | one formal `scripts/build-firmware.ps1` |
| `scripts/flash-firmware-m5.ps1` | `scripts/flash-firmware.ps1` |
| `scripts/test-m2-safety.ps1` | `scripts/test-firmware-safety.ps1` |
| `scripts/test-m3-acquisition-static.ps1` | `scripts/test-firmware-acquisition-static.ps1` |
| `scripts/test-m3-loopback-safety.ps1` | `scripts/test-firmware-loopback-safety.ps1` |
| `scripts/test-m5-timer-ownership.ps1` | `scripts/test-firmware-timer-ownership.ps1` |
| `scripts/test-firmware-m5-app.ps1` | `scripts/test-firmware-app.ps1` |
| `scripts/test-firmware-m5-burst-plan.ps1` | `scripts/test-firmware-burst-plan.ps1` |
| `scripts/test-firmware-m5-schedule.ps1` | `scripts/test-firmware-capture-schedule.ps1` |
| `scripts/verify-m6-jetson-hil.py` | `scripts/verify-jetson-hil.py` |
| M0 build and M3 startup/small-RAM/ADC-diagnostic build wrappers | remove from active tree after invariant migration is documented |

The formal firmware output becomes `firmware/build/release/tuss4470-acquisition-fw-0.2.0.2.elf`. Associated `.map`, disassembly, and normalized loadable image use the same basename. Docker images use `tuss4470-acquisition-core:1.0.0`.

---

### Task 1: Create the isolated release worktree and capture the immutable pre-rename baseline

**Files:**
- Create: `docs/release/v1.0.0-baseline.md`
- Create locally: `D:/Desktop/TUSS4470_data/release/v1.0.0/baseline/`
- Reference: `docs/verification/M6/summary.md`
- Reference: `docs/verification/M6/jetson-validation.md`
- Reference: `CONTRIBUTING.md`

**Interfaces:**
- Consumes: code baseline `3bf041aee736980a413207640a36dcc1e3c2daf5` plus this currently untracked plan document.
- Produces: a worktree on `codex/v1-release-consolidation` whose first commit adds only this plan, while every source/build input still matches code baseline `3bf041a...`; also produces baseline firmware ELF/map/disassembly/loadable image, hashes, sizes, section addresses, interrupt-vector evidence, and a textual baseline record used by Task 6.

- [ ] **Step 1: Refresh and verify the exact remote starting state**

Run `git fetch origin main`, then `git status --short --branch`, `git rev-parse HEAD`, and `git rev-parse origin/main`.

Expected: the only main-checkout change is the untracked plan file; both SHA values equal the required 40-character baseline. Do not rely on a stale local `origin/main` reference.

- [ ] **Step 2: Create the isolated worktree**

Use the `using-git-worktrees` skill and create `.worktrees/v1-release-consolidation` on branch `codex/v1-release-consolidation` from the verified `3bf041a...` baseline. Copy this plan into the new worktree, verify the copied file hash matches the reviewed copy, commit only that document as `docs: plan v1 release consolidation`, and remove only the original untracked duplicate from the main checkout.

Expected: the new worktree is clean at a documentation-only child of `3bf041a...`; `git diff 3bf041a... HEAD -- . ':!docs/superpowers/plans/2026-09-10-v1-release-consolidation.md'` is empty; the main checkout is clean at `3bf041a...`.

- [ ] **Step 3: Build the accepted pre-rename production firmware without hardware access**

Activate the worktree `.venv`, run `scripts/build-firmware-m5.ps1`, and do not run any flash or serial command.

Expected: `firmware/build/m5/usac-m5-first-version.elf` builds successfully.

- [ ] **Step 4: Save baseline artifacts outside Git**

Use these exact MSP430 tools from `.tools/msp430-gcc/msp430-gcc-9.3.1.11_win64/bin/` for both baseline and candidate:

```powershell
$toolRoot = 'D:/Desktop/TUSS4470_software/.tools/msp430-gcc/msp430-gcc-9.3.1.11_win64/bin'
$evidenceRoot = 'D:/Desktop/TUSS4470_data/release/v1.0.0/baseline'
$elf = 'D:/Desktop/TUSS4470_software/.worktrees/v1-release-consolidation/firmware/build/m5/usac-m5-first-version.elf'
$map = 'D:/Desktop/TUSS4470_software/.worktrees/v1-release-consolidation/firmware/build/m5/usac-m5-first-version.map'
$hex = Join-Path $evidenceRoot 'firmware-loadable-gap-ff.hex'
New-Item -ItemType Directory -Force -Path $evidenceRoot | Out-Null
& (Join-Path $toolRoot 'msp430-elf-objcopy.exe') -O ihex --gap-fill 0xFF $elf $hex
& (Join-Path $toolRoot 'msp430-elf-size.exe') -A $elf | Set-Content -Encoding utf8 (Join-Path $evidenceRoot 'size.txt')
& (Join-Path $toolRoot 'msp430-elf-objdump.exe') -h $elf | Set-Content -Encoding utf8 (Join-Path $evidenceRoot 'sections.txt')
& (Join-Path $toolRoot 'msp430-elf-objdump.exe') -d $elf | Set-Content -Encoding utf8 (Join-Path $evidenceRoot 'disassembly.txt')
& (Join-Path $toolRoot 'msp430-elf-readelf.exe') -S -l $elf | Set-Content -Encoding utf8 (Join-Path $evidenceRoot 'elf-layout.txt')
Copy-Item -LiteralPath $elf -Destination (Join-Path $evidenceRoot 'firmware.elf')
Copy-Item -LiteralPath $map -Destination (Join-Path $evidenceRoot 'firmware.map')
Get-FileHash -Algorithm SHA256 $elf, $hex | Format-List | Set-Content -Encoding utf8 (Join-Path $evidenceRoot 'sha256.txt')
```

Redirect each textual output to a named UTF-8 report and copy the ELF, map, disassembly, Intel HEX, and reports into `D:/Desktop/TUSS4470_data/release/v1.0.0/baseline/`. The Intel HEX is the canonical comparison artifact: `objcopy` includes loadable sections at their load addresses and fills inter-section holes with `0xFF`; both runs use the same tool version and command.

Expected: every copied artifact has a recorded byte size and SHA-256; the record identifies the baseline commit, exact compiler/binutils version, command line, address/section report, and hole-fill rule. Task 6 changes only `$evidenceRoot`, `$elf`, and `$map` to the post-source-rename paths; Task 7 changes them to the final release-build paths. Each comparison uses `Get-FileHash` plus `Compare-Object (Get-Content baseline.hex) (Get-Content candidate.hex)` and requires both SHA equality and no line differences.

- [ ] **Step 5: Write the baseline document**

Record the source commit, local/remote equality, accepted M6 evidence links, existing firmware version `0.2.0.2`, protocol `v1`, toolchain versions, artifact hashes, loadable image extraction method, and accepted limitations in `docs/release/v1.0.0-baseline.md`.

- [ ] **Step 6: Commit the baseline record**

Commit message: `docs: record v1 release baseline`

---

### Task 2: Establish neutral public host commands and preserve complete offline export

**Files:**
- Modify: `pyproject.toml`
- Rename: `packages/usac_runtime/src/usac_runtime/m5_server.py` -> `packages/usac_runtime/src/usac_runtime/core_server.py`
- Rename: `packages/usac_runtime/src/usac_runtime/m5_api.py` -> `packages/usac_runtime/src/usac_runtime/api.py`
- Rename: `packages/usac_runtime/src/usac_runtime/m5_cli.py` -> `packages/usac_runtime/src/usac_runtime/client_cli.py`
- Rename: `packages/usac_runtime/src/usac_runtime/m4_cli.py` -> `packages/usac_runtime/src/usac_runtime/export_cli.py`
- Rename tests according to the Host and Web file mapping above, except Web assets handled in Task 4.

**Interfaces:**
- Produces: `usac-core`, `usac-cli`, and `usac-export` console scripts.
- Preserves: current Core options and API behavior; offline export reads `CaptureStore` directly and emits exact `.usac`, `.u16le`, and `.json` files.

- [ ] **Step 1: Add failing command-registration tests**

Assert that installed script metadata contains exactly the four V1 public commands and no milestone-named commands. Assert `usac-core` resolves to `core_server:main`, `usac-cli` to `client_cli:main`, and `usac-export` to `export_cli:main`.

- [ ] **Step 2: Run the targeted tests and confirm failure**

Run the project-layout and renamed CLI/server test files.

Expected: failure because the neutral modules and command registrations do not yet exist.

- [ ] **Step 3: Rename the modules and update imports**

Use `git mv`; update relative imports, monkeypatch targets, module docstrings, CLI descriptions, tests, and the M6 HIL helper import. Do not change request payloads, routes, database logic, or default Core behavior in this step.

- [ ] **Step 4: Make real-hardware invocation explicit in tests and documentation fixtures**

Assert that the Core parser still defaults to `simulator` for safe local development, while every formal physical deployment passes `--backend bridge` explicitly. Preserve `--database`, HTTP port 8000, and bridge port 8765 semantics.

- [ ] **Step 5: Verify complete offline export byte identity**

Create a temporary committed capture in SQLite, run `usac-export`, and assert the emitted `.usac` equals `wire_frame`, `.u16le` equals `sample_blob`, and `.json` contains the stored metadata. Stop if the exporter requires a running Core.

- [ ] **Step 6: Run targeted Python tests**

Expected: Core server, API, client CLI, exporter, project layout, and byte-identity tests pass.

- [ ] **Step 7: Commit the host entry-point migration**

Commit message: `refactor: establish v1 host entry points`

---

### Task 3: Reduce Bridge to the formal long-running service and retire superseded host utilities

**Files:**
- Modify: `packages/usac_runtime/src/usac_runtime/bridge_cli.py`
- Modify: `packages/usac_runtime/src/usac_runtime/bridge_session.py`
- Modify: `packages/usac_runtime/tests/test_bridge_cli.py`
- Modify: `packages/usac_runtime/tests/test_bridge_device_client.py`
- Delete after coverage migration: `packages/usac_runtime/src/usac_runtime/m2_cli.py`
- Delete after coverage migration: `packages/usac_runtime/src/usac_runtime/m2_smoke.py`
- Delete after coverage migration: `packages/usac_runtime/src/usac_runtime/m3_cli.py`
- Delete after coverage migration: `packages/usac_runtime/src/usac_runtime/m3_loopback_cli.py`
- Delete after coverage migration: `packages/usac_runtime/src/usac_runtime/m3_capture.py`
- Delete after coverage migration: `packages/usac_runtime/src/usac_runtime/core_service.py`
- Delete after coverage migration: `packages/usac_runtime/src/usac_runtime/delivery.py`
- Delete after coverage migration: `packages/usac_runtime/src/usac_runtime/bridge.py`
- Delete after coverage migration: `packages/usac_runtime/src/usac_runtime/serial.py`
- Delete or replace corresponding obsolete tests: `test_m2_smoke.py`, `test_m3_capture.py`, `test_m3_cli.py`, `test_core_service.py`, `test_bridge.py`, `test_delivery.py`, and `test_serial.py`.

**Interfaces:**
- Produces: `usac-bridge --config ... --core-host ... --core-port ... --confirm-external-vpwr-7v` as the single formal bridge invocation; no `serve` subcommand is required after consolidation.
- Preserves: serial DTR sequence, reconnect supervision, spool-before-delivery, SQLite-commit receipt, no automatic Burst retry, and random positive 63-bit SQLite-compatible connection IDs.

- [ ] **Step 1: Add failing tests for the final Bridge CLI**

Assert the parser accepts the formal service arguments at top level, rejects removed `capture` and `replay` modes, still refuses startup without external VPWR confirmation, and never opens a serial port during parser tests.

- [ ] **Step 2: Add or identify coverage for every retained delivery invariant**

Before deleting old tests, map and retain tests for: spool durability, replay on a new HELLO session, matching commit receipt, duplicate commit handling, connection/session IDs, serial/TCP closure, DTR fail-safe, deferred commands during replay, and no capture-command retry.

- [ ] **Step 3: Run the targeted tests and confirm the new CLI test fails**

Expected: failure because `serve` is still a required subcommand.

- [ ] **Step 4: Move the active ID helper and simplify `bridge_cli.py`**

Move `new_sqlite_integer_id()` into `bridge_session.py` or another neutral active module, remove top-level imports of legacy capture/delivery code, flatten the `serve` arguments, and keep the current session implementation unchanged.

- [ ] **Step 5: Delete superseded installed utilities only after migrated tests pass**

Remove the files listed above from the active package. Their historical source remains at the baseline commit; do not copy them into a second importable legacy package.

- [ ] **Step 6: Run Bridge, spool, delivery, reconnect, and project-layout tests**

Expected: all retained behavior passes; importing `bridge_cli` no longer imports milestone modules.

- [ ] **Step 7: Commit the Bridge consolidation**

Commit message: `refactor: consolidate v1 bridge service`

---

### Task 4: Rename formal Web assets and remove milestone terminology from active UI code

**Files:**
- Rename: `packages/usac_runtime/src/usac_runtime/web/m5-app.js` -> `packages/usac_runtime/src/usac_runtime/web/app.js`
- Rename: `packages/usac_runtime/src/usac_runtime/web/m5-styles.css` -> `packages/usac_runtime/src/usac_runtime/web/styles.css`
- Rename: `packages/usac_runtime/tests/test_m5_app.cjs` -> `packages/usac_runtime/tests/test_web_app.cjs`
- Modify: `packages/usac_runtime/src/usac_runtime/web/index.html`
- Modify: `packages/usac_runtime/src/usac_runtime/api.py`
- Modify: `scripts/test-all.ps1`
- Modify: `scripts/test-all.sh`

**Interfaces:**
- Preserves: all `/api/v1` routes, bilingual UI, configuration controls, acquisition modes, save policies, waveform windowing, raw/normalized display, 20-capture overlay limit, follow-latest behavior, and storage-path display.

- [ ] **Step 1: Change the Node test to require neutral asset names**

Assert HTML references `/assets/app.js` and `/assets/styles.css`, API static routes serve those paths, and old `/assets/m5-*` paths are absent.

- [ ] **Step 2: Run Node and API asset tests to confirm failure**

Expected: failure on the old filenames/routes.

- [ ] **Step 3: Rename assets and update references without changing UI logic**

Use `git mv`, update HTML/API/tests/aggregate scripts, and replace milestone-only comments or test labels. Do not reformat or restructure the application JavaScript.

- [ ] **Step 4: Run Node, API, and server tests**

Expected: all Web behavior tests pass with the neutral asset paths.

- [ ] **Step 5: Commit the Web rename**

Commit message: `refactor: rename v1 web assets`

---

### Task 5: Define the production firmware build and safety-test migration before source renaming

**Files:**
- Create: `docs/release/v1.0.0-firmware-check-migration.md`
- Modify later: `scripts/test-all.ps1`
- Reference: every firmware build/static/unit script listed in the Build and test file mapping.

**Interfaces:**
- Produces: an explicit old-check -> verified behavior -> V1 check/exit-reason table used by Tasks 6 and 7.

- [ ] **Step 1: Inventory each existing firmware check by behavior**

Cover clock initialization, DCORSEL, SPI division/readback, reset-safe IO2, Standby/VDRV Hi-Z, configuration-valid versus profile-active state, DTR/session closure, ADC/DMA 2048-sample ownership, pretrigger, raw ordering, loopback timing, TA1 ownership, finite 1-63 Pulse plans, periodic/STOP/lease, synchronization, events, USB DMA exclusion, and protocol framing.

- [ ] **Step 2: Mark obsolete artifacts by reason, not by milestone name**

M0 skeleton compilation, startup diagnostic image, small-RAM diagnostic image, and ADC/DMA diagnostic image may exit the daily gate where either (a) a behavior still required by the formal firmware is covered by a named production unit/static/build check, or (b) the assertion tested only a diagnostic mechanism that is itself being retired. For case (b), record the diagnostic and its exit reason; do not force software-trigger or single-word-DMA diagnostic-only assertions into the production acquisition path.

- [ ] **Step 3: Review the matrix for gaps**

Expected: every currently safety-relevant production invariant has exactly one or more named V1 checks; every removed production or diagnostic-only check has a concrete replacement or exit reason. TA1 ownership must remain explicit.

- [ ] **Step 4: Commit the migration matrix**

Commit message: `docs: define v1 firmware verification migration`

---

### Task 6: Rename active firmware files and internal milestone identifiers with loadable-image equivalence

**Files:**
- Rename all active firmware source/header pairs in the Firmware file mapping.
- Remove superseded `firmware/src/main.c` M0 skeleton before moving the formal entry to that path.
- Rename: `firmware/tests/test_m2_core.c` -> `firmware/tests/test_firmware_core.c`
- Rename: `firmware/tests/test_m5_app.c` -> `firmware/tests/test_firmware_app.c`
- Rename: `firmware/tests/test_m5_burst_plan.c` -> `firmware/tests/test_burst_plan.c`
- Rename: `firmware/tests/test_m5_schedule.c` -> `firmware/tests/test_capture_schedule.c`
- Modify all active firmware includes, include guards, symbols, constants, compile macros, tests, and static scripts that reference milestone component names.
- Delete after migration: `firmware/tests/m3_platform_startup_stub.c`
- Delete after migration: `firmware/tests/m3_platform_small_ram_stub.c`

**Interfaces:**
- Preserves: all exported firmware behavior, wire bytes, hardware register operations, ISR ownership, global buffer dimensions, and callback/state-machine contracts.
- Produces neutral concepts: firmware app/core, capture/report/stream/transport, loopback, burst plan, capture schedule, and MSP430 acquisition platform.

- [ ] **Step 1: Add a filename and identifier hygiene test**

Scan active `firmware/src`, `firmware/include`, and `firmware/tests` for M0-M6 component identity tokens. Exempt only literal protocol/config/firmware version values and explanatory historical references explicitly listed in the test.

- [ ] **Step 2: Run the hygiene test and confirm failure**

Expected: it reports the current M2/M3/M5 files and identifiers.

- [ ] **Step 3: Rename files with `git mv` and update one responsibility group at a time**

Apply groups in this order: entry/USB events; firmware core/app; capture/report; stream/transport; loopback; burst plan/schedule; acquisition platform; tests. Keep the source list in the same relative order.

- [ ] **Step 4: Rename first-party identifiers consistently**

Replace stage-based include guards, C symbols, types, constants, compile macros, comments, and test names with the neutral responsibility vocabulary. Do not rename `AcquisitionConfigV2`, schema/protocol `v1`, firmware `0.2.0.2`, register fields, or wire message names.

- [ ] **Step 5: Build the renamed formal firmware**

Update only the source/header paths and renamed compile macros in the existing `scripts/build-firmware-m2.ps1` plus its `build-firmware-m5.ps1` wrapper, preserving their structure, source order, arguments, output location, and TI generated-file edits. Build through the existing M5 wrapper. Do not flash.

Expected: warning-clean build succeeds with unchanged linker inputs and options.

- [ ] **Step 6: Compare post-rename loadable content against Task 1**

Repeat the exact Task 1 commands, including `objcopy -O ihex --gap-fill 0xFF`, with the same MSP430 binutils. Compare Intel HEX SHA-256 and bytes, section/load addresses, `.text/.data/.bss`, interrupt vectors, and hardware-critical disassembly.

Expected: loadable image and addresses match exactly; memory sizes and vectors match. Symbol/path differences in ELF/map are documented. Any other difference blocks the task.

- [ ] **Step 7: Run all retained firmware unit and static safety checks**

Expected: every check in the Task 5 migration matrix passes.

- [ ] **Step 8: Commit the firmware source rename**

Commit message: `refactor: rename v1 firmware units`

---

### Task 7: Consolidate production build, flash, verification scripts, and aggregate gates

**Files:**
- Replace the existing M0 `scripts/build-firmware.ps1` with the formal production builder derived from `build-firmware-m2.ps1` and `build-firmware-m5.ps1`.
- Rename and update scripts according to the Build and test file mapping.
- Modify: `scripts/test-all.ps1`
- Modify only its firmware portions: `tests/integration/test_project_layout.py`
- Remove superseded M0/M2/M3/M5 wrappers and diagnostic-only scripts after migration.

**Interfaces:**
- Produces: `scripts/build-firmware.ps1`, `scripts/flash-firmware.ps1`, `scripts/test-all.ps1`, and `scripts/test-all.sh` as the only current top-level build/flash/aggregate gates.
- Preserves: TI tool locations, generated descriptor edits, USB bus-powered descriptor, USB DMA channel `0xFF`, MSP430 target/linker scripts, flash external-VPWR-off confirmation, and no serial/Burst side effects during build/test.

- [ ] **Step 1: Update project-layout tests for the final script set**

Assert neutral firmware names, the release output path, absence of retired firmware wrappers, and presence of every Task 5 retained check. Deployment-module, dependency-lock, Compose, and Docker-tag assertions remain assigned to Task 8.

- [ ] **Step 2: Run the layout test and confirm failure**

Expected: current milestone wrappers and image tags violate the final layout.

- [ ] **Step 3: Build one formal firmware script**

Collapse the wrapper/variant arrangement into `scripts/build-firmware.ps1`, remove diagnostic switches from the release builder, keep source order and all production compile/link arguments unchanged, and output `firmware/build/release/tuss4470-acquisition-fw-0.2.0.2.elf`.

- [ ] **Step 4: Rename the controlled flash script**

Point `scripts/flash-firmware.ps1` only at the release ELF, preserve `-ExternalVpwrOffConfirmed`, and preserve the rule that the script sends no serial command and cannot request a Burst.

- [ ] **Step 5: Rename retained functional checks and prune obsolete daily builds**

Apply the Task 5 matrix. Do not remove a check solely because its old filename contains M2/M3/M5.

- [ ] **Step 6: Update the Windows aggregate gate's firmware section**

Update the firmware portions of `scripts/test-all.ps1` to invoke only the retained neutral checks and the formal production build. Do not run the complete aggregate gate yet. Defer `scripts/test-all.sh`, container build names, and full project-layout assertions to Task 8, where all deployment references exist together.

- [ ] **Step 7: Run the renamed firmware checks individually**

Run the formal firmware build and each retained firmware unit/static check directly.

Expected: all checks in the Task 5 migration matrix pass without invoking Docker, serial, flash, or Burst. The first complete repository gate remains exclusively in Task 11.

- [ ] **Step 8: Reconfirm firmware equivalence after final build-script consolidation**

Repeat the exact Task 1 `objcopy -O ihex --gap-fill 0xFF`, size, section, vector, and disassembly commands using only the final `scripts/build-firmware.ps1` output. Its Intel HEX must match both the Task 1 baseline and the Task 6 post-source-rename image.

- [ ] **Step 9: Commit build and gate consolidation**

Commit message: `build: consolidate v1 firmware and release gates`

---

### Task 8: Update deployment files and verify the two-service runtime locally

**Files:**
- Modify: `deploy/Dockerfile.core`
- Modify: `deploy/compose.yaml`
- Modify: `deploy/compose.jetson.yaml`
- Create: `requirements-container.lock.txt`
- Rename or update: `deploy/README-jetson.md` -> `docs/deployment/jetson.md`
- Create: `docs/deployment/windows.md`
- Modify: `config/windows.example.toml`
- Modify: `config/jetson.example.toml`
- Modify: `scripts/test-all.sh`
- Modify: `tests/integration/test_project_layout.py`
- Modify: relevant deployment and package tests.

**Interfaces:**
- Core container entry: `python -m usac_runtime.core_server`.
- Jetson bridge entry: `python -m usac_runtime.bridge_cli` with top-level service arguments.
- Storage paths remain controlled by `USAC_CORE_DATA_DIR`, `USAC_BRIDGE_SPOOL_DIR`, and `USAC_SERIAL_DEVICE`.
- Container third-party dependencies are exported with hashes from the repository `uv.lock`; first-party source is copied at the candidate commit and imported through the existing `PYTHONPATH` rather than built in an unlocked isolation environment.

- [ ] **Step 1: Add failing deployment assertions**

Assert both Compose files and the Dockerfile use neutral module/command names and image tag `1.0.0`; assert physical Core always passes `--backend bridge`; assert the flattened Bridge command has no `serve`; assert core and bridge retain separate writable paths; assert the Dockerfile installs `requirements-container.lock.txt` with `pip --require-hashes`, does not run `pip install .`, and imports copied first-party source through `PYTHONPATH`.

- [ ] **Step 2: Export one hash-locked container dependency set from `uv.lock`**

Using repository tool `.tools/uv/uv.exe` version `0.12.5`, run:

```powershell
& ./.tools/uv/uv.exe export --frozen --no-dev --no-emit-project --no-header --format requirements.txt --output-file requirements-container.lock.txt
```

Add a test that regenerates the file to a temporary path with the same `--no-header` command and requires byte equality. `--no-header` is mandatory because uv otherwise embeds the output command, including its destination path, and makes equivalent exports byte-different. The export contains exact third-party versions and hashes but omits the local project, whose version comes from `pyproject.toml`.

- [ ] **Step 3: Update Docker and Compose references**

Copy `requirements-container.lock.txt` before first-party source and install it with `python -m pip install --require-hashes -r requirements-container.lock.txt`. Do not run `pip install .`; copy the candidate's `packages/`, `protocol/`, and metadata, retain the existing `PYTHONPATH`, and add OCI version/revision labels supplied by build arguments. Set each Compose image reference to `${USAC_CORE_IMAGE:-tuss4470-acquisition-core:1.0.0}` so acceptance can select an immutable candidate tag without rebuilding. Do not change ports, bind mounts, device mapping, restart policy, or network direction. Windows remains loopback-published; Jetson Core/Bridge communicate through the Compose private network.

- [ ] **Step 4: Complete deployment and aggregate-gate references**

Update `scripts/test-all.sh`, all project-layout assertions, Docker entrypoint, both Compose files, help text, and test fixtures to the final neutral names. Replace stale `m1-arm64` outputs with candidate-SHA-qualified ARM64 and AMD64 artifact names. Keep both image builds on Jetson: one native ARM64 image used for runtime verification and one AMD64 OCI cross-build used for portability verification. Actual image builds occur only once in Task 12.

- [ ] **Step 5: Rewrite current Windows and Jetson operating instructions**

Clearly distinguish host/container paths, simulator/bridge backends, external VPWR requirements, stable Jetson USB identity, build/start/stop commands, and SQLite/spool ownership.

- [ ] **Step 6: Run deployment/configuration checks without building an image**

Run the dependency-export equality test, project-layout tests, Dockerfile/Compose static assertions, and native Core simulator targeted tests on Windows. Do not require Docker on Windows, do not run the complete aggregate gate, and do not build or overwrite a release image in this task. The actual `docker compose config` check runs on Jetson in Task 12.

Expected: no USB, COM, SPI, flash, or Burst access; exact 2048-sample behavior remains.

- [ ] **Step 7: Commit deployment migration**

Commit message: `deploy: publish v1 service names`

---

### Task 9: Consolidate current documentation and archive pre-V1 history without losing accepted evidence

**Files:**
- Rewrite: `README.md`
- Create: `docs/release/v1.0.0-acceptance.md`
- Create: `docs/release/v1.0.0-known-limitations.md`
- Create: `docs/archive/pre-v1/README.md`
- Move completed plans/specs and detailed milestone verification under `docs/archive/pre-v1/`.
- Rename still-current ADR filenames by decision rather than milestone; archive diagnostic-only ADRs.
- Preserve: `docs/protocol.md`
- Modify: `CONTRIBUTING.md`

**Interfaces:**
- README becomes the current V1 entry for build, simulator, physical service start, Web/CLI use, offline export, data locations, safety, and links to authoritative release/protocol/deployment documents.
- V1 acceptance summarizes but does not replace detailed M0-M6 evidence.

- [ ] **Step 1: Create the V1 acceptance and limitations documents**

Reference the exact archived M6 evidence and state what passed on Windows and Jetson. Carry forward timing, lease, 5 Hz, long-run, and reconnect limitations verbatim in substance.

- [ ] **Step 2: Move completed historical documents under `docs/archive/pre-v1/`**

Keep original milestone names and internal content where needed for traceability. Add an archive index mapping old paths to new paths and mark them non-normative but evidentiary.

- [ ] **Step 3: Keep active ADRs by technical decision**

Rename still-valid clock/SPI, safe-standby, configuration-state, and ADC/timer ADR filenames without changing decision substance. Move diagnostic-only ADRs to the pre-V1 archive.

- [ ] **Step 4: Rewrite README around V1 operation rather than chronology**

Remove step-by-step M2/M3/M4 reproduction commands from the active README. Include exactly the four public commands, `--backend bridge` for hardware, external VPWR and flash gates, current Windows/Jetson data paths, simulator use, and offline export.

- [ ] **Step 5: Update repository archive and release rules**

Clarify in `CONTRIBUTING.md`: tracked textual history belongs in `docs/archive/`; raw/bulky local evidence belongs in ignored `archive/local/` or the release evidence directory; Git history is the source archive for deleted superseded code.

- [ ] **Step 6: Validate internal Markdown links and active-name hygiene**

Check that current docs do not instruct users to run milestone-named commands or use moved paths. Historical archive content may retain original commands but must be clearly marked non-current.

- [ ] **Step 7: Commit documentation consolidation**

Commit message: `docs: consolidate v1 operation and evidence`

---

### Task 10: Set release metadata and freeze a clean candidate source commit

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Verify/regenerate: `requirements-container.lock.txt`
- Update: release/deployment documents with final identifiers.

**Interfaces:**
- Produces one clean candidate source commit containing every runtime/build input, software version `1.0.0`, firmware identifier `0.2.0.2`, protocol `v1`, and the final dependency locks. No code, configuration, dependency, build, or deployment input may change after this commit; subsequent commits contain acceptance/release documentation only.

- [ ] **Step 1: Change Python project metadata to `1.0.0`**

Update `pyproject.toml` from `0.0.0` to `1.0.0`, replace the skeleton description with the current acquisition-module description, and regenerate `uv.lock` so its local project entry is also `1.0.0`. Do not change dependency bounds or third-party resolved versions.

- [ ] **Step 2: Revalidate the derived container lock**

Run the exact Task 8 export command again. Expected: `requirements-container.lock.txt` remains byte-identical because it excludes the local project; every third-party version and hash still derives from the updated `uv.lock`.

- [ ] **Step 3: Run package metadata and candidate-input tests without producing release artifacts**

Assert `pyproject.toml` and the local project entry in `uv.lock` both report `1.0.0`, dependency resolutions did not change, and console-script metadata contains only the four public commands. Actual firmware/container artifacts are built only after the candidate commit in Tasks 11-12.

- [ ] **Step 4: Commit all build inputs before producing artifacts**

Commit message: `release: freeze v1.0.0 candidate inputs`

- [ ] **Step 5: Record the immutable candidate SHA without changing the tree**

Require a clean worktree, record `git rev-parse HEAD` as `V1_CANDIDATE_SHA`, and push that exact branch commit. All Tasks 11-12 build and validate this SHA. Do not create artifacts from an uncommitted or documentation-updated checkout.

---

### Task 11: Verify the exact candidate on Windows without Docker or hardware mutation

**Files:**
- Update: `docs/release/v1.0.0-acceptance.md`
- Create: `docs/release/v1.0.0-manifest.md`
- Create locally: `D:/Desktop/TUSS4470_data/release/v1.0.0/candidate/windows/`

**Interfaces:**
- Consumes: clean checkout at `V1_CANDIDATE_SHA`.
- Produces: the Windows release-candidate gate and firmware artifact already built by that gate. It does not require Docker, flash, open COM9, or produce a Burst.

- [ ] **Step 1: Verify the checkout is the exact candidate**

Require `git rev-parse HEAD` to equal `V1_CANDIDATE_SHA` and `git status --porcelain` to be empty before any build.

- [ ] **Step 2: Run the complete Windows aggregate gate**

Activate the release worktree `.venv` and run `scripts/test-all.ps1`.

Expected: all tests pass; command output confirms no serial, flash, or Burst activity.

- [ ] **Step 3: Preserve the firmware artifact produced by the complete gate**

Do not invoke the firmware builder again. Use the formal firmware ELF/map/disassembly generated by Step 2, generate the canonical Intel HEX and comparison reports once with the Task 1 method, and require equality with the accepted baseline.

- [ ] **Step 4: Save the Windows candidate evidence outside Git**

Copy firmware ELF/map/disassembly/Intel HEX and comparison reports, dependency-lock hashes, tool/runtime version reports, and SHA-256 listing to `D:/Desktop/TUSS4470_data/release/v1.0.0/candidate/windows/`. Do not copy SQLite databases, credentials, or transient captures into Git.

- [ ] **Step 5: Run simulator operator verification with the native Core**

Start `usac-core` directly from the Windows project `.venv` with `--backend simulator` and a SQLite path outside the repository. Do not install or invoke Docker.

Verify bilingual UI, readable device states, all parameter controls, configuration apply/readback, single/periodic/sweep plans, all save policies, SQLite history, waveform windowing, raw/normalized display, compatible overlays, follow-latest, and storage path display.

- [ ] **Step 6: Verify offline export independently of Core**

Stop Core and export one committed test record with `usac-export`. Compare `.usac` byte-for-byte with `CaptureRecord.wire_frame` and `.u16le` byte-for-byte with `CaptureRecord.sample_blob`. Parse `.json` and compare its required fields and values with the same `CaptureRecord` plus the documented export schema; do not claim SQLite contains an original JSON file.

- [ ] **Step 7: Run hygiene and sensitive-data checks**

Check active filenames and public commands for milestone identities, scan tracked content for the previously exposed password and other credentials, run `git diff --check`, and inspect the complete branch diff from the baseline.

- [ ] **Step 8: Create the release manifest and record Windows results**

Record `V1_CANDIDATE_SHA` as the artifact-build SHA; record intended final tag `v1.0.0`; record software `1.0.0`, firmware `0.2.0.2`, protocol `v1`, `uv.lock` and container-lock hashes, firmware hashes/equivalence, Windows platform result, public commands, data paths, accepted limitations, and evidence links. Container identifiers are added after their single Jetson builds.

- [ ] **Step 9: Commit documentation-only Windows evidence**

Commit message: `test: record v1 windows acceptance`

Expected: `git diff --exit-code $env:V1_CANDIDATE_SHA HEAD -- . ':(exclude)docs/**'` is empty; only acceptance/release documents changed after the candidate commit.

---

### Task 12: Verify the release candidate on Jetson and real hardware

**Files:**
- Update: `docs/release/v1.0.0-acceptance.md`
- Update: `docs/release/v1.0.0-manifest.md`
- Create locally: `D:/Desktop/TUSS4470_data/release/v1.0.0/candidate/jetson/`

**Interfaces:**
- Consumes the exact `V1_CANDIDATE_SHA`; the Windows evidence commit is documentation-only and is not used as a new build input.
- Produces Jetson ARM64 deployment evidence and one bounded physical end-to-end confirmation.

- [ ] **Step 1: Synchronize the exact candidate source to Jetson**

Checkout or create a clean Jetson verification worktree at `V1_CANDIDATE_SHA`, not the later Windows evidence commit. Expected: Windows build input and Jetson build input use the same 40-character candidate SHA.

- [ ] **Step 2: Run the Jetson offline aggregate gate**

Activate the Jetson project `.venv` and run `scripts/test-all.sh`. The script must build the ARM64 image exactly once as `tuss4470-acquisition-core:1.0.0-rc-<candidate12>-arm64` and cross-build the AMD64 OCI artifact exactly once as `tuss4470-acquisition-core-1.0.0-rc-<candidate12>-amd64.tar`. Pass the full candidate SHA into OCI labels, record the ARM64 image ID/digest and AMD64 OCI SHA-256, verify ARM64 installed dependency versions against `uv.lock`, and reuse the ARM64 image for simulator and physical checks. Do not build or overwrite final tag `:1.0.0`.

Expected: all tests and container checks pass without physical capture.

- [ ] **Step 3: Save the two candidate container evidence**

Copy the ARM64 image inspection/dependency reports and AMD64 OCI artifact/hash to `D:/Desktop/TUSS4470_data/release/v1.0.0/candidate/jetson/` or the corresponding persistent Jetson release-evidence directory, then record its exact location. Do not rebuild either image.

- [ ] **Step 4: Stop before any Bridge start and verify host device identity**

Ensure no old Bridge container/process is running. On the Jetson host, resolve `USAC_SERIAL_DEVICE` to the actual stable `/dev/serial/by-id/...` path, verify its TI USB product/serial attributes identify the intended MSP430 CDC interface, and verify the Compose device mapping will expose that host path as container alias `/dev/tuss4470`. The container alias alone is not identity evidence.

- [ ] **Step 5: Stop at the physical hardware gate**

Before starting Bridge, require the operator to confirm USB connection, Standard topology, external VPWR 7.0 V, current limit, PZT wiring, and reset. No automatic retry is permitted. Core may remain stopped as well so the final two-service start uses one known state.

- [ ] **Step 6: Validate Compose and start the two services from the already-built ARM64 candidate image**

Set `USAC_CORE_IMAGE` to the immutable ARM64 candidate tag, run `docker compose config`, recreate Core and Bridge once, and confirm separate persistent mounts, Core health, authenticated device identity, configuration state, and Web/API reachability. Do not rebuild the image during `compose up`.

- [ ] **Step 7: Run one bounded Pulse=1 real capture**

Apply/read back the accepted configuration, execute exactly one authorized capture, and verify 2048 raw samples, one committed capture ID, zero pending spool records, valid history/download, and byte identity between bridge frame, SQLite, and exported `.usac`/`.u16le`.

- [ ] **Step 8: Record Jetson evidence**

Record the exact commit, ARM64 image identifier, AMD64 OCI hash, locked dependency result, device identity in non-sensitive form, configuration hash/CRC, capture ID, sample count, relevant hashes, pending count, and absence of automatic retry.

- [ ] **Step 9: Commit Jetson acceptance evidence from the release branch**

Return to the release branch containing the Windows evidence, add only the Jetson results to the acceptance/manifest documents, and verify `git diff --exit-code $env:V1_CANDIDATE_SHA HEAD -- . ':(exclude)docs/**'` remains empty.

Commit message: `test: record v1 jetson acceptance`

---

### Task 13: Preserve unique local evidence, clean obsolete worktrees/caches, and publish `v1.0.0`

**Files:**
- Update if needed: `docs/release/v1.0.0-manifest.md`
- Local cleanup targets only after inspection: `.worktrees/m6-external-review-followup`, `.worktrees/m3-windows-waveform`, `.worktrees/archive/*`, `.pytest_cache`, and generated `firmware/build` directories other than separately saved release evidence.

**Interfaces:**
- Produces: clean `main`, matching `origin/main`, Git tag `v1.0.0`, synchronized clean Jetson checkout, and no obsolete local worktree copies inside the project.

- [ ] **Step 1: Audit every cleanup target for unique local content**

For registered worktrees, verify clean status and that their branch tips are ancestors of the release branch. For stale directories, compare first-party files with tracked commits and copy genuinely unique evidence to `D:/Desktop/TUSS4470_data/release/v1.0.0/legacy-local/` before removal.

- [ ] **Step 2: Inspect all Junctions before removal**

Resolve `.venv` and `.tools` link targets under stale worktrees. Remove only the Junction objects; never recursively delete their targets or the main repository environment/toolchain.

- [ ] **Step 3: Remove obsolete worktrees with the appropriate mechanism**

Use `git worktree remove` for registered worktrees after verification. Use explicit `-LiteralPath` operations for confirmed stale directories under `D:/Desktop/TUSS4470_software/.worktrees/`. Do not use broad globs or recursive deletion against an unresolved path.

- [ ] **Step 4: Clean generated caches after evidence preservation**

Remove only confirmed generated `.pytest_cache`, `__pycache__`, and obsolete `firmware/build` outputs. Preserve the release evidence already copied outside the repository.

- [ ] **Step 5: Re-run final repository checks**

Run `git status`, `git diff --check`, current-name hygiene, sensitive-data scan, and targeted Python/Node documentation-adjacent smoke tests. Do not rebuild accepted container images or create a new artifact set.

- [ ] **Step 6: Integrate through a normal merge and push**

Review the branch as a whole, merge it into `main` without rewriting history, push `main`, and verify local/remote SHA equality.

- [ ] **Step 7: Prove the merged main differs from the accepted candidate only under `docs/`**

On the clean, merged `main`, before creating a tag, run:

```powershell
git diff --exit-code $env:V1_CANDIDATE_SHA HEAD -- . ':(exclude)docs/**'
```

Expected: no output and exit code 0. This covers every non-document path, including root files such as `.dockerignore`, `.python-version`, `README.md`, project metadata, deployment inputs, source, tests, and scripts. Any non-`docs/` difference blocks the tag.

- [ ] **Step 8: Create and push the annotated release tag**

Create annotated tag `v1.0.0` only at the accepted main commit. The manifest must name `V1_CANDIDATE_SHA` as the artifact-build SHA and `v1.0.0` as the final release tag; the tag message must state software `1.0.0`, firmware `0.2.0.2`, protocol `v1`, and reference the manifest. Push the tag and verify it resolves remotely to the same final documentation-inclusive commit.

- [ ] **Step 9: Assign final local image tags without rebuilding**

On Jetson, retag the already accepted ARM64 candidate image as `tuss4470-acquisition-core:1.0.0`. Record old candidate tag, final tag, and unchanged image ID/digest. Keep the AMD64 cross-build as the hashed candidate OCI artifact recorded in the manifest; Windows is not required to load it. Do not rebuild either platform artifact.

- [ ] **Step 10: Synchronize final main and tag to Jetson**

Fetch, fast-forward to the released main commit, fetch tags, verify `v1.0.0` resolves correctly, and leave the Jetson checkout clean.

- [ ] **Step 11: Remove the completed release worktree**

After the branch has been merged, the tag pushed, and evidence preserved, verify the release worktree is clean and remove it with `git worktree remove`. Prune only stale worktree metadata and leave the main checkout at the released commit.

- [ ] **Step 12: Report the frozen release**

Report the final commit, tag, firmware hash, Docker identifier, Windows and Jetson gates, archived/removed components, retained limitations, data/evidence locations, and confirmation that no protocol, database, or intended hardware-control behavior changed.

---

## Final acceptance criteria

- Exactly four public commands exist: `usac-core`, `usac-bridge`, `usac-cli`, and `usac-export`.
- Active host, Web, firmware, test, build, deployment, and current-document filenames use responsibility names rather than M0-M6 identities.
- Historical milestone names remain only in clearly marked archived evidence or unavoidable source-commit references.
- Formal hardware deployment explicitly uses `usac-core --backend bridge`; simulator remains the safe development default.
- Offline export works while Core is stopped; `.usac` and `.u16le` reproduce stored BLOBs byte-for-byte, while parsed `.json` fields exactly match the documented metadata contract and database record.
- The V1 firmware builds from `scripts/build-firmware.ps1` to the documented `0.2.0.2` release artifact.
- Post-rename normalized loadable bytes and addresses, memory sizes, interrupt vectors, compile/link settings, USB DMA exclusion, and hardware-critical disassembly match the accepted baseline.
- All retained clock, SPI, reset/IO2, VDRV, ADC/DMA, TA1, Burst, STOP/lease, synchronization/event, protocol, spool/commit, API, UI, and cross-platform checks pass.
- Windows and Jetson use the same source commit, protocol, database schema, firmware, and primary business logic.
- One bounded Jetson Pulse=1 capture confirms 2048 raw samples, SQLite commit, zero pending spool, and byte-identical export without automatic retry.
- V1 current documentation clearly separates operation, deployment, release evidence, known limitations, and archived history.
- Python metadata is `1.0.0`, Docker image is tagged `1.0.0`, firmware remains `0.2.0.2`, protocol remains `v1`, and annotated Git tag `v1.0.0` points to the accepted release commit.
- The manifest records `V1_CANDIDATE_SHA` as the artifact-build SHA and `v1.0.0` as the final release tag; the tagged tree differs from the candidate only in acceptance/release documentation.
- Local and remote main SHA values match, Jetson is synchronized and clean, and obsolete local worktrees/caches have been removed only after unique evidence and Junction targets were checked.

## Explicit non-goals

- No SOC/SOH prediction or acoustic feature extraction.
- No wire-protocol, REST route-version, parameter-schema, or SQLite-schema redesign.
- No new TUSS4470 register behavior or acquisition mode.
- No timing calibration claim.
- No replacement of the accepted 10,000 ms lease compromise or 5 Hz scheduling behavior.
- No M7 security, stress, long-duration, replay-hardening, or production-installation expansion.
- No automatic firmware flashing, automatic Burst retry, or hardware action without the existing physical and operator gates.
