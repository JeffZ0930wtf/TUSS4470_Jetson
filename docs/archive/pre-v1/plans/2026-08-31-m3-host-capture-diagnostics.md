# M3 Host Capture Diagnostics Implementation Plan

## 文档说明

本文档把已批准的 M3 主机采集阶段诊断设计转化为精简实施步骤，适用于首次
真实波形失败定位。它依赖 `docs/m3-host-capture-diagnostics-design.md`，只增加
观察性进度信息，不授权新的硬件采集，也不改变固件、协议或重试策略。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add minimal, immediate host-side progress evidence that locates an M3 capture failure without changing firmware, protocol, hardware behavior, or retry policy.

**Architecture:** `run_m3_capture` accepts an optional observation-only callback and emits stable phase events. The existing CLI renders those events to stderr while preserving stdout for the successful JSON result. Existing frame readers gain an optional byte-progress callback only where CAPTURE_DATA is read.

**Tech Stack:** Python 3.12, pyserial-compatible connection interface, pytest.

## Global Constraints

- Do not change MCU firmware, wire protocol, acquisition parameters, or hardware safety gates.
- Do not retry or send more than one `CAPTURE_ONCE` per invocation.
- Diagnostics go to stderr; successful machine-readable JSON remains on stdout.
- A caller that omits the callback observes the existing API behavior.

---

### Task 1: Optional capture progress reporting

**Files:**
- Modify: `packages/usac_runtime/src/usac_runtime/m3_capture.py`
- Modify: `packages/usac_runtime/src/usac_runtime/m3_cli.py`
- Test: `packages/usac_runtime/tests/test_m3_capture.py`
- Test: `packages/usac_runtime/tests/test_m3_cli.py`

**Interfaces:**
- Consumes: existing `SerialConnection`, `_read_raw_frame`, and `run_m3_capture` flow.
- Produces: optional `progress` callback receiving a compact immutable event with `stage`, `received_bytes`, and optional `expected_bytes`.

- [x] **Step 1: Add failing tests**

Add simulated ACK-timeout and partial-CAPTURE_DATA-timeout cases asserting the last stage and exact received-byte count. Add a CLI test proving progress is printed to stderr and not stdout.

- [x] **Step 2: Verify the tests fail for the missing callback API**

Run: `.venv/Scripts/python.exe -m pytest packages/usac_runtime/tests/test_m3_capture.py packages/usac_runtime/tests/test_m3_cli.py -q`

Expected: FAIL because `run_m3_capture` does not yet accept or emit progress events.

- [x] **Step 3: Implement the minimum callback and stderr renderer**

Add one immutable event type, optional callbacks in the capture-only read path, and a small CLI formatter. Preserve original exceptions while appending the last phase and byte progress; never retry.

- [x] **Step 4: Verify targeted and complete offline gates**

Run targeted pytest, then `scripts/test-all.ps1`. Expected: all tests and M0/M1/M2/M3 compile/static safety gates pass without COM access or flashing.

- [x] **Step 5: Review the diff**

Run `git diff --check` and confirm no firmware or protocol files changed as part of this diagnostic task.
