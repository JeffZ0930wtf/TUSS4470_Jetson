# M4 Windows end-to-end pipeline verification

## Document overview

This document records the scope, commands, evidence, accepted limitations, and
closure status for milestone M4 of the ultrasonic acquisition submodule. It
applies only to the Windows bridge-to-core-to-SQLite vertical pipeline defined
by the controlled design and M4 roadmap. M3 remains the authority for firmware
and single-Burst hardware acceptance; M5 owns full parameter editing and
periodic acquisition.

## Status

**Closed with the evidence and boundaries recorded here.** Host implementation,
software regression, ARM64 container validation, and the Windows real-hardware
end-to-end capture have passed. This summary is the non-functional payload of
the required M4 milestone commit. The authoritative roadmap records whether
that commit reached `origin/main`, whether local/remote SHA values matched,
whether Jetson `main` was synchronized, and whether the stage worktree was
retired; any failure in that outer transaction reopens M4.

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

Final completion run on 2026-08-31 exited with code 0 and did not access COM9:

- Python: `109 passed`;
- M0 safe firmware compile: PASS;
- MSP430 simulator unit tests: PASS;
- TI official USB CDC stack smoke build: PASS;
- M2 no-Burst firmware build and static safety audit: PASS;
- M3 acceptance firmware build, loopback audit, and acquisition static audit:
  PASS;
- M3 no-Burst ADC/DMA diagnostic build and static audit: PASS;
- bridge/CLI SQLite-compatible source ID and safety-gate regression: PASS; and
- core rejection of a non-`CAPTURE_DATA` inner frame: PASS.

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

## ARM64 container evidence

Jetson container validation used committed source `9781735181a087ceb2358f51430a4b3340c08dba`
in the ordered verification directory later archived under
`/home/yizhouzhao/workspace/TUSS4470_verification/archive/M4/m4-9781735-source`.
The transferred source archive matched on both hosts:

```text
SHA-256 d487345a31557fcda9a2d3c0f44e293eb1c3f781f3671f996f2649e92cad48b4
```

`deploy/Dockerfile.core` built and started successfully on the real Jetson:

```text
image ID  sha256:cea13c4f5e94f83266881528d47f17227a7378abb535b3b827e8ff68b58fc5ef
platform  linux/arm64
size      43516394 bytes
```

One M1 protocol fixed vector was delivered through the running container to
its external SQLite bind directory. The bridge reported `DELIVERED=1` and
`PENDING=0`; the container exited normally after its one configured
connection. Independent database inspection found exactly one row,
`WIRE_MATCH=True`, `SAMPLES_MATCH=True`, and 8 exact sample bytes. This is a
container/data-contract check only; it does not substitute for the pending
2048-point Windows real-device G3W capture.

## Windows real-device G3W evidence

After explicit operator confirmation of external 7 V, reset, and the existing
pin-40 through 2.2 kΩ to pin-38 loopback, the formal `usac-bridge` entry point
opened the stable USB CDC device on COM9. One and only one `Pulse=1` capture was
executed; the host did not retry. The loopback gate passed, CAPTURE_ONCE was
ACKed, receive progress reached exactly 4324 bytes, and the bridge reported:

```text
capture_id       d0c46e41f33a6b020d3cdaf7895389a6
device_id        c5fa4769c16da8710b8688c70ba34cf7
sample_count     2048
delivered        1
sqlite_committed true
interpolated     false
```

Before this authorized command, an attempted `python -m usac_runtime.bridge_cli`
invocation returned without calling `main`; a direct SQLite count confirmed
zero capture rows. It did not open COM9 or send a Burst. The subsequent formal
entry-point command above is therefore the sole real capture in this M4 run.

The committed record retained the fixed M3 contract: 120 sample ticks, 50
Burst-period ticks, 64 pretrigger samples, profile SHA-256
`b8826eaf278d7360189d49aced322ff9e404d8266a25e76a011065c2fda5c998`,
quality flags `0x00000020` (`TIMING_UNCALIBRATED`), and TUSS4470 DEV_STAT
`0x08`. The quality flag preserves the accepted lack of external clock
calibration; it is not a truncation or interpolation flag.

Evidence is retained outside Git under `D:\Desktop\TUSS4470_data`:

| Evidence | Size | SHA-256 |
|---|---:|---|
| Exported raw `.usac` frame | 4324 B | `a2d3278a1bbcabb8c7445316165c2bba712cf3f43a22f4c260318187854b6fd8` |
| Exported raw `.u16le` samples | 4096 B | `1951531fc14d9142afed332a8420bdbd5074e33ef14f3157250030958dab7014` |
| Exported metadata JSON | 530 B | `3cd89bbb77a321aff8e24c7aa65622d986026da84fc950ff2448a774f4bd44b1` |
| Core SQLite after shutdown | 24576 B | `50f0bfe65c456a45dc80b799c7e36a8f0bf72639495c3d42ab7b27ee1d318fce` |
| Bridge spool SQLite | 28672 B | `80eb3f90e699be9152f32b0a04e20e1d9595e5669f370ee7799c4c6ba8c780b6` |

Independent read-only verification passed every check: normative protocol
CRC, 4324-byte wire length, 2048 decoded samples, 4096-byte sample BLOB,
pretrigger/timer metadata, raw export equality, sample export equality, and
`interpolated=false`. Core SQLite contained exactly one capture. Bridge spool
contained zero pending rows and one matching committed tombstone; its capture
identity and inner-frame CRC matched the SQLite record. The core process was
then stopped, so no M4 service remains running in the background.

## Pending closure evidence

- [x] Build and start the M4 core container from committed source on the real
      Jetson, then verify one fixed-vector spool/commit/download-equivalent
      byte contract through an external SQLite bind directory.
- [x] Enumerate the real Windows device and confirm its stable identifier.
- [x] With the accepted M3 physical gates satisfied, perform exactly one real
      `Pulse=1`, 200 kS/s, 2048-point capture through `usac-bridge`.
- [x] Confirm the bridge reports success only after SQLite commit.
- [x] Compare device wire-frame samples, bridge-spooled inner frame, SQLite
      sample BLOB, and downloaded `.u16le` bytes exactly.
- [x] Record capture ID, non-sensitive file hashes, database path, spool state,
      and CLI inspection/download evidence.
- [x] Rerun the complete Windows software gate; sensitive-data and final Git
      diff checks are performed immediately before staging the closure commit.
- [x] Prepare this summary as the required non-empty milestone closure update.
      The subsequent push, SHA equality, Jetson synchronization, and worktree
      retirement are recorded in the authoritative roadmap because this commit
      cannot contain its own future SHA.

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

Relative to M3 milestone `c199987e4880f65542e75cfeda5a34c7009f373b`, M4
includes exactly these tracked paths before the final roadmap-only closure:

- `README.md`
- `config/jetson.example.toml`
- `config/windows.example.toml`
- `deploy/Dockerfile.core`
- `deploy/compose.yaml`
- `docs/verification/M4/summary.md`
- `packages/usac_runtime/src/usac_runtime/bridge.py`
- `packages/usac_runtime/src/usac_runtime/bridge_cli.py`
- `packages/usac_runtime/src/usac_runtime/core_service.py`
- `packages/usac_runtime/src/usac_runtime/core_store.py`
- `packages/usac_runtime/src/usac_runtime/delivery.py`
- `packages/usac_runtime/src/usac_runtime/m4_cli.py`
- `packages/usac_runtime/src/usac_runtime/spool.py`
- `packages/usac_runtime/tests/test_bridge.py`
- `packages/usac_runtime/tests/test_bridge_cli.py`
- `packages/usac_runtime/tests/test_core_service.py`
- `packages/usac_runtime/tests/test_core_store.py`
- `packages/usac_runtime/tests/test_delivery.py`
- `packages/usac_runtime/tests/test_m4_cli.py`
- `packages/usac_runtime/tests/test_spool.py`
- `pyproject.toml`
- `scripts/bootstrap-dev.ps1`
- `tests/integration/test_project_layout.py`

## Formal milestone closure

Functional implementation and real-hardware evidence entered `main` at
`c7ad5e2e6637834a7b82befcb82b750da2475835`. This final update changes no
runtime, protocol, firmware, hardware control, database schema, or captured
data. It exists so the required
`milestone(M4): complete Windows end-to-end pipeline` commit is non-empty and
reviewable. The controlled roadmap is the final record of the pushed 40-character
SHA, Jetson synchronization, and worktree retirement.
