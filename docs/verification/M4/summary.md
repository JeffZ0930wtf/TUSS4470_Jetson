# M4 Windows end-to-end pipeline verification

## Document overview

This document records the scope, commands, evidence, accepted limitations, and
closure status for milestone M4 of the ultrasonic acquisition submodule. It
applies only to the Windows bridge-to-core-to-SQLite vertical pipeline defined
by the controlled design and M4 roadmap. M3 remains the authority for firmware
and single-Burst hardware acceptance; M5 owns full parameter editing and
periodic acquisition.

## Status

**In progress.** Host implementation and software regression are complete.
Container validation and the final Windows real-hardware end-to-end capture
are not yet recorded, so M4 and gate G3W are not closed.

## Implemented scope

- A complete `CAPTURE_DATA` frame is validated and durably written to the
  bridge pending spool before delivery.
- The core validates the inner frame again and atomically stores the original
  wire frame, exact sample BLOB, and capture/configuration metadata in SQLite.
- `CAPTURE_COMMITTED` is sent only after SQLite commit; a matching receipt is
  required before the bridge deletes pending data.
- Replayed deliveries are idempotent by `(device_id, boot_id, capture_id)` and
  conflicting bytes are rejected.
- Windows capture, pending replay, committed-record inspection, and exact raw
  download are available through small command-line entry points.
- Runtime SQLite, WAL/SHM, spool, staging, and exports are configured outside
  the Git repository. No waveform feature calculation or interpolation occurs.

## Automated verification completed

Windows aggregate gate, run from the isolated M4 worktree with its local
virtual environment:

```powershell
./scripts/test-all.ps1
```

Result on 2026-08-31:

- Python: `107 passed` before the final two regression tests were added;
- M0 safe firmware compile: PASS;
- MSP430 simulator unit tests: PASS;
- TI official USB CDC stack smoke build: PASS;
- M2 no-Burst firmware build and static safety audit: PASS;
- M3 acceptance firmware build, loopback audit, and acquisition static audit:
  PASS;
- M3 no-Burst ADC/DMA diagnostic build and static audit: PASS.

Targeted tests added after that aggregate run:

- bridge/CLI SQLite-compatible source ID and safety-gate regression: `6 passed`;
- core wrong-inner-message rejection: PASS as part of the existing validation
  path.

The aggregate gate must be rerun after documentation and final code changes
before closure; the final count and transcript hash will replace the interim
figures above.

## Restart and delivery evidence

Automated tests cover:

- reopening the bridge spool with a pending frame still present;
- loss of the core receipt after the core has committed, followed by bridge
  restart/replay without a duplicate SQLite row;
- core unavailability leaving pending data intact;
- rejection of a mismatched commit receipt before pending deletion;
- exact record inspection and byte-for-byte raw frame/sample download.

## Runtime path evidence

Windows production defaults:

```text
D:\Desktop\TUSS4470_data\
├─ core\acquisition.sqlite3
└─ bridge\
   ├─ spool\bridge-spool.sqlite3
   └─ staging\
```

The project layout test rejects configurations that place these runtime files
inside `D:\Desktop\TUSS4470_software`.

## Pending closure evidence

- [ ] Build and start the M4 core container from the committed source.
- [ ] Enumerate the real Windows device and confirm its stable identifier.
- [ ] With the accepted M3 physical gates satisfied, perform exactly one real
      `Pulse=1`, 200 kS/s, 2048-point capture through `usac-bridge`.
- [ ] Confirm the bridge reports success only after SQLite commit.
- [ ] Compare device wire-frame samples, bridge-spooled inner frame, SQLite
      sample BLOB, and downloaded `.u16le` bytes exactly.
- [ ] Record capture ID, non-sensitive file hashes, database path, spool state,
      and CLI inspection/download evidence.
- [ ] Rerun the complete Windows gate, sensitive-data scan, and Git diff checks.
- [ ] Create and push the required non-empty milestone commit, verify local and
      remote 40-character SHA equality, sync Jetson, and archive the worktree.

## Known boundaries

- M4 retains the fixed M3 profile: D10x4, nominal 200 kS/s, 2048 real samples,
  64 pretrigger samples, IO_MODE 3, and one pulse.
- Full device/acquisition parameter editing, periodic acquisition, leases, and
  Web/REST parameter surfaces remain M5.
- Jetson real-hardware acquisition remains M6. The M4 container is packaged
  for cross-platform reuse but does not claim G3J.
- External absolute clock calibration, known-input DMA ordering HIL, and the
  full abnormal-reset matrix retain the accepted M3/M7 disposition.

## Files included in M4

The final exact list will be generated from the M3 milestone commit through the
M4 closure commit. At this stage it includes the bridge, spool, delivery,
SQLite store, core service, operator CLI, tests, deployment files, runtime
configuration examples, bootstrap adjustment, README, and this summary.
