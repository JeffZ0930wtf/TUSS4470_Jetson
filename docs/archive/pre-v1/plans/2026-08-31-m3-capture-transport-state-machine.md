# M3 Capture Transport State Machine Implementation Plan

## 文档说明

本文档把已批准的 M3 采集帧传输设计转化为可验证的实施步骤，解决完整
`CAPTURE_DATA` 帧在 MSP430 USB CDC 输出途中停滞的问题。它适用于 M3 首条
真实波形的固件传输与主机接收闭环，依赖
`docs/m3-capture-transport-design.md`，不扩展采集参数、原始数据格式或 BMS
功能边界。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace application-level 64-byte CDC transactions with a four-segment, commit-after-completion M3 transport that preserves the unique raw waveform buffer and can later accept delivery confirmation and retry policies.

**Architecture:** `usac_m3_capture_stream` remains the protocol-frame source and exposes four immutable regions without advancing on inspection. A small transport-neutral `usac_m3_capture_tx` session owns READY/IN_FLIGHT/COMPLETE/FAILED transitions; the MSP430 adapter maps TI CDC STARTED, BUSY, completion, and fatal results into that session. The host retains bounded reads and idle-progress timeout.

**Tech Stack:** C11-compatible MSP430 GCC, TI MSP430 USB CDC API, PowerShell build/static gates, C simulator tests, Python 3.12/pytest host tests.

## Global Constraints

- Do not change TUSS4470 registers, ADC12, Timer_B, DMA, IO2, Burst timing, `Pulse=1`, 200 kS/s, 2048 samples, or 64-sample pretrigger behavior.
- Keep exactly one 4096-byte raw sample buffer; never interpolate, transform, or duplicate samples.
- The wire frame remains one continuous 4324-byte `CAPTURE_DATA` frame; transport segments are not protocol fields.
- BUSY never advances a segment and never triggers another capture or Burst.
- No COM access, flashing, or Burst until all offline gates pass and the operator separately confirms the hardware step.
- Do not commit or push partial M3 work; the milestone receives one reviewed commit and push only after real-hardware acceptance.

---

### Task 1: Four-region frame source

**Files:**
- Modify: `firmware/include/usac_m3_capture_stream.h`
- Modify: `firmware/src/usac_m3_capture_stream.c`
- Modify: `firmware/tests/test_m2_core.c`

**Interfaces:**
- Produces: `usac_m3_capture_stream_peek(const usac_m3_capture_stream_t *, const uint8_t **, uint16_t *) -> uint8_t`
- Produces: `usac_m3_capture_stream_commit(usac_m3_capture_stream_t *) -> uint8_t`
- Preserves: frame bytes, CRC, metadata length 208, sample address, and capture identity.

- [x] **Step 1: Write failing C tests for stable peek and four committed regions**

Replace the old chunk-loop assertion with checks equivalent to:

```c
static const uint16_t expected_lengths[4] = {16u, 208u, 4096u, 4u};
for (index = 0u; index < 4u; ++index) {
    const uint8_t *again;
    uint16_t again_length;
    CHECK(usac_m3_capture_stream_peek(&stream, &chunk, &chunk_length) == 1u);
    CHECK(chunk_length == expected_lengths[index]);
    CHECK(usac_m3_capture_stream_peek(&stream, &again, &again_length) == 1u);
    CHECK(again == chunk && again_length == chunk_length);
    CHECK(usac_m3_capture_stream_commit(&stream) == 1u);
}
CHECK(usac_m3_capture_stream_peek(&stream, &chunk, &chunk_length) == 0u);
```

Also assert region pointers are `frame_header`, `metadata`, `g_usac_m3_waveform`, and `frame_crc` in that order.

- [x] **Step 2: Run the simulator test and observe RED**

Run: `& .\scripts\test-firmware-unit.ps1`

Expected: compilation fails because `usac_m3_capture_stream_peek` and `commit` do not exist, or the old 64-byte behavior violates the four-region assertions.

- [x] **Step 3: Implement non-mutating peek and explicit commit**

Remove `phase_offset` and `USAC_M3_CAPTURE_CHUNK_MAX`. `peek` returns the entire current region without mutation:

```c
uint8_t usac_m3_capture_stream_peek(
    const usac_m3_capture_stream_t *stream,
    const uint8_t **data,
    uint16_t *length);

uint8_t usac_m3_capture_stream_commit(usac_m3_capture_stream_t *stream);
```

`commit` increments `phase` exactly once and clears `active` after phase 3. Invalid, inactive, or null calls fail closed without changing state.

- [x] **Step 4: Run the simulator test and observe GREEN**

Run: `& .\scripts\test-firmware-unit.ps1`

Expected: simulator unit tests pass and the fixed Python-compatible CRC vector remains unchanged.

### Task 2: Transport-neutral send session

**Files:**
- Create: `firmware/include/usac_m3_capture_tx.h`
- Create: `firmware/src/usac_m3_capture_tx.c`
- Modify: `firmware/tests/test_m2_core.c`
- Modify: `scripts/build-firmware-m2.ps1`
- Modify: `scripts/test-firmware-unit.ps1`

**Interfaces:**
- Consumes: `usac_m3_capture_stream_peek` and `usac_m3_capture_stream_commit`.
- Produces: `usac_m3_capture_tx_init`, `usac_m3_capture_tx_peek`, `usac_m3_capture_tx_on_start_result`, `usac_m3_capture_tx_on_send_completed`, and `usac_m3_capture_tx_abort`.

- [x] **Step 1: Write failing state-transition tests**

Define public states `IDLE`, `READY`, `IN_FLIGHT`, `COMPLETE`, and `FAILED`, plus start results `STARTED`, `BUSY`, and `FATAL`. Test these behaviors:

```c
usac_m3_capture_tx_init(&tx, &stream);
CHECK(tx.state == USAC_M3_TX_READY);
CHECK(usac_m3_capture_tx_peek(&tx, &data, &length) == 1u);
CHECK(length == 16u);

usac_m3_capture_tx_on_start_result(&tx, USAC_M3_TX_START_BUSY);
CHECK(tx.state == USAC_M3_TX_READY);
CHECK(usac_m3_capture_tx_peek(&tx, &again, &again_length) == 1u);
CHECK(again == data && again_length == length);

usac_m3_capture_tx_on_start_result(&tx, USAC_M3_TX_START_STARTED);
CHECK(tx.state == USAC_M3_TX_IN_FLIGHT);
CHECK(usac_m3_capture_tx_peek(&tx, &again, &again_length) == 0u);
usac_m3_capture_tx_on_send_completed(&tx);
CHECK(tx.state == USAC_M3_TX_READY);
CHECK(usac_m3_capture_tx_peek(&tx, &again, &again_length) == 1u);
CHECK(again_length == 208u);
```

Complete all four segments and assert `COMPLETE`; separately inject `FATAL` and assert `FAILED` without committing the current segment.

- [x] **Step 2: Run simulator tests and observe RED**

Run: `& .\scripts\test-firmware-unit.ps1`

Expected: compilation fails because the transport session interface is absent.

- [x] **Step 3: Implement the minimal pure-C state machine**

The session stores only a stream pointer and state. BUSY is a no-op in READY; STARTED changes READY to IN_FLIGHT; completion commits exactly one stream region and selects READY or COMPLETE; invalid transitions fail closed; abort selects FAILED. It owns no sample memory and invokes no hardware API.

- [x] **Step 4: Link the new source into simulator and firmware builds**

Add `firmware/src/usac_m3_capture_tx.c` to the existing M3-enabled source lists only. M0/M2 no-Burst behavior and image composition remain unchanged.

- [x] **Step 5: Run simulator tests and observe GREEN**

Run: `& .\scripts\test-firmware-unit.ps1`

Expected: all stream and transport transition tests pass.

### Task 3: TI CDC adapter integration

**Files:**
- Modify: `firmware/src/m2_main.c`
- Modify: `scripts/test-m3-acquisition-static.ps1`

**Interfaces:**
- Consumes: transport-neutral session from Task 2.
- Maps: `USBCDC_SEND_STARTED -> STARTED`, `USBCDC_INTERFACE_BUSY_ERROR -> BUSY`, all other send errors -> FATAL.

- [x] **Step 1: Write failing static integration checks**

Require the M3 main path to peek before `USBCDC_sendData`, map BUSY without ending the app session, call `on_send_completed` only for a capture segment marked IN_FLIGHT, and remove the old `USAC_M3_CAPTURE_CHUNK_MAX 64u` requirement.

- [x] **Step 2: Run the static check and observe RED**

Run: `& .\scripts\test-m3-acquisition-static.ps1`

Expected: fail because the main loop still calls the advancing `stream_next` API and treats BUSY as fatal.

- [x] **Step 3: Integrate the send session**

Initialize the frame source and TX session together. Send only the region returned by `usac_m3_capture_tx_peek`. Map the TI result into `on_start_result`; call `usac_tx_gate_started` only for STARTED. On the USB completion event, call `on_send_completed` before releasing the one-in-flight gate. Clear `app.capture_pending` only after TX state becomes COMPLETE. Reset or abort the TX session on DTR loss, USB reset, or fatal send error.

- [x] **Step 4: Run static, simulator, and build checks**

Run:

```powershell
& .\scripts\test-firmware-unit.ps1
& .\scripts\build-firmware-m3.ps1
& .\scripts\test-m3-acquisition-static.ps1
```

Expected: all pass; M3 ELF still contains exactly one 4096-byte waveform buffer and no TI USB DMA-copy symbols.

### Task 4: Offline regression and controlled hardware acceptance

**Files:**
- Modify after evidence exists: `docs/verification/M3/summary.md`
- Store local raw evidence under: `artifacts/m3/` or ignored `archive/local/` according to repository policy.

**Interfaces:**
- Consumes: unchanged `CAPTURE_DATA` wire frame and host M3 CLI.
- Produces: one complete raw frame, metadata JSON, and 4096-byte sample file.

- [x] **Step 1: Run complete offline verification**

Run:

```powershell
. .\.venv\Scripts\Activate.ps1
& .\scripts\test-all.ps1
& .\scripts\test-m3-adc-dma-diagnostic-static.ps1
git diff --check
```

Expected: all Python, simulator, M0, TI USB, M2, M3 build/static checks pass with no COM access.

- [x] **Step 2: Controlled flash gate**

Ask the operator to turn external 7 V off. Only after explicit confirmation, flash the verified M3 image and require DSLite program verification success.

- [x] **Step 3: Read-only startup gate**

Ask the operator to restore 7 V and press S3 RST. Run only HELLO and GET_CONFIG; require firmware `0.2.0.2`, the expected device identity, profile hash, configuration CRC, 120 sample ticks, and 50 Burst ticks.

- [x] **Step 4: Single authorized capture**

Obtain explicit authorization for exactly one real capture. Run the M3 CLI once with no automatic retry. Require 4324 received frame bytes, valid frame CRC, exactly 2048 raw `uint16` samples, 4096 sample bytes, pretrigger 64, and `interpolated: false`.

- [x] **Step 5: Close M3 only from fresh evidence**

Write `docs/verification/M3/summary.md` with commands, hashes, artifact sizes, hardware conditions, and any remaining timing limitation. Run the completion verification again, then create the single M3 milestone commit and push it to the configured GitHub repository. Archive or remove the temporary worktree only after the branch is safely integrated or otherwise retained according to the user's chosen branch workflow.
