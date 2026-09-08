# M6 host 3.0 increment review checkpoint

## Document overview

This document records the Windows/software checkpoint for the M6 host 3.0
increment of the ultrasonic acquisition submodule. It identifies what is
implemented, what was verified without hardware, and what remains before M6
can close. It complements the controlled design and roadmap; it is not M6
closure evidence and does not claim Jetson or physical-device verification.

## Implemented scope

- Core HTTP/Web starts before a bridge or USB device is available. Schema,
  draft editing, and validation remain available; hardware operations return
  HTTP 503 until a fully initialized bridge session is published.
- The device endpoint separates connection health, current activity, and
  backend type. The Web UI renders readable Chinese status instead of raw
  firmware state numbers.
- The parameter bank renders only device and single-frame waveform fields.
  Single, periodic, and single-field sweep execution share one acquisition
  card with one save-policy selector.
- `SAVE_ALL`, `SAVE_NONE`, and `SAVE_LAST` apply to all three modes. Every
  received frame is completely validated before the core returns a durable
  processing resolution to the bridge delivery path.
- `SAVE_NONE` retains only the bounded in-process latest waveform for display.
  `SAVE_LAST` keeps one SQLite rolling frame per session and archives that last
  frame when the run completes, stops, fails, or is reconciled after restart.
- Session summaries persist requested/acquired/saved/policy-discarded counts,
  last acquired/saved IDs, state, and terminal reason. An open session found
  at core startup is marked `INTERRUPTED`; acquisition is never auto-resumed.
- REST, CLI, and Web use the same application and persistence semantics. No
  firmware source, firmware image, or USAC wire-frame layout changed.
- The Web console uses one in-browser Chinese/English text catalogue. Chinese
  is the default; the top-right language control switches the complete operator
  interface and stores only the language preference in browser local storage.
  Parameter identifiers, protocol values, raw samples, and SQLite records are
  never translated or rewritten.

## Verification performed

- `python -m pytest -q`: 234 tests passed.
- The aggregate Windows gate was run in bounded segments: the same host suite
  passed, followed by all existing M0, TI USB, M2, M3, and M5 build/static and
  simulator gates. No segment accessed a COM port or flashed firmware.
- JavaScript syntax: Node `--check` passed for `m5-app.js`.
- Browser smoke with the deterministic simulator: configuration apply/readback,
  one 2048-point capture, waveform rendering, SQLite history, and four counters
  were observed.
- Browser language smoke: every operator label and dynamic capture/status item
  switched to English, the selection survived reload, and the interface then
  switched back to Chinese without losing the active configuration or history.
- Browser smoke with the bridge backend and no bridge attached: **未检测到设备**
  was shown; apply/capture were disabled while draft editing and validation
  remained usable.

## Still open

- Windows operator review of the host UI and save-policy behavior passed on
  2026-09-08, including the Chinese/English switch.
- Migration of this same revision to Jetson and the roadmap's real ARM64/
  physical-device checks.
- M6 milestone merge, closure commit, push, and worktree cleanup.
