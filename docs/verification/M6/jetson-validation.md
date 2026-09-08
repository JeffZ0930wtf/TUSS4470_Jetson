# M6 Jetson real-hardware validation checkpoint

## Document overview

This document records the in-progress M6 verification performed on the real
Jetson Orin Nano, MSP-EXP430F5529LP, BOOSTXL-TUSS4470, and D10x4 hardware
chain. It preserves reproducible evidence for ARM64 deployment, Linux USB CDC,
the first real capture, data identity, and container persistence. It
complements the controlled roadmap and is not an M6 closure summary; unchecked
M6/G3J items remain mandatory.

## Verified platform and revision

- Date: 2026-09-08 (Asia/Shanghai).
- Jetson: `172.20.149.177`, JetPack 7.2.1 / Jetson Linux 39.2.1 / ARM64.
- Isolated verification worktree:
  `/home/yizhouzhao/workspace/TUSS4470_verification/worktrees/m6-host-3-0-increment`.
- Verified revision: `012ec4f3ae2bca85b6d2f2010e26ba99ec6fea81`.
- The Jetson main worktree remained clean at the closed M5 baseline
  `a7fc178cc8ade60f287179a45b7234bff7ca9991`.
- Device ID: `c5fa4769c16da8710b8688c70ba34cf7`.
- Firmware CDC endpoint: `/dev/ttyACM2` during this run; stable identity path:
  `/dev/serial/by-id/usb-Texas_Instruments_MSP430-USB_Example_c5fa4769c16da8710b8688c70ba34cf7-if00`.
  `/dev/ttyACM0` and `/dev/ttyACM1` were eZ-FET interfaces and were not used as
  the acquisition transport.

## ARM64 and deployment evidence

- `uv 0.12.5` created the isolated project environment with
  `uv sync --frozen --extra dev`.
- The initial Jetson full suite passed with `234 passed`. After the bridge
  entry-point correction, its focused regression passed and the complete
  Jetson suite passed with `235 passed in 16.40s`.
- The ARM64 candidate image was built successfully and inspected as
  `linux/arm64`. Candidate tag:
  `tuss4470-acquisition-core:m6-validation-940bd11`; image/manifest ID begins
  `sha256:956ad5`.
- The Compose deployment ran separate bridge and core containers. Host paths
  `/var/lib/tuss4470/bridge/spool` and `/var/lib/tuss4470/core` were mounted at
  `/var/lib/usac/spool` and `/var/lib/usac/database`, respectively. Runtime
  databases did not appear in the source worktree.
- During bring-up, Compose exposed a real deployment defect: invoking
  `python -m usac_runtime.bridge_cli` returned without starting the bridge.
  A failing module-entry regression was added before the minimal
  `__main__` entry point was implemented. Fix commit:
  `012ec4f3ae2bca85b6d2f2010e26ba99ec6fea81`.

## Read-only hardware preflight

With external 7 V absent, HELLO succeeded but the firmware correctly remained
in its safe fault/config-invalid state and GET_CONFIG was rejected. After the
operator enabled 7 V and reset the board, HELLO and GET_CONFIG reported:

- firmware `0.2.0.2`;
- device state `IDLE_SAFE` (`6`);
- profile SHA-256
  `b8826eaf278d7360189d49aced322ff9e404d8266a25e76a011065c2fda5c998`;
- configuration CRC32 `0x5d4fc286`;
- sampling ticks `120` and Burst ticks `50`;
- `VDRV_READY=1` and `TUSS_DEV_STAT=8`.

The same D10x4 configuration was applied and all ten register/value pairs read
back identically before capture. This operation did not create a Burst.

## First real Jetson capture

The operator explicitly authorized one real Jetson capture at external 7 V,
with `Pulse=1` and no automatic retry. Exactly one request was issued.

- Capture ID: `8427aee93a94fbc7ddcca6dcda08b6ae`.
- Session ID: `2ad92179f031480f88e35c642179b5ee`.
- Request ID: `8edbf6ada3dbf09baa43b43432060437`.
- Boot ID: `d2046dcc1fa93a57e08a3f1de37d8a6a`.
- Sequence: `1`.
- Result: `2048` real samples, `4096` sample bytes, `4324` raw USAC frame
  bytes, no clipping, no interpolation.
- Configuration: sampling ticks `120`, Burst ticks `50`, `Pulse=1`.
- Quality flags: `32` (`TIMING_UNCALIBRATED`, the accepted current hardware
  limitation); `TUSS_DEV_STAT=8`.
- Save resolution: `RAW_ARCHIVED`; requested/acquired/saved/discarded counts
  were `1/1/1/0`; session terminal state was `COMPLETED`.

Evidence paths:

- Jetson:
  `/var/lib/tuss4470/core/evidence/8427aee93a94fbc7ddcca6dcda08b6ae.u16le`
  and the corresponding `.usac` file.
- Windows archive:
  `D:\Desktop\TUSS4470_data\verification\M6\8427aee93a94fbc7ddcca6dcda08b6ae.u16le`
  and the corresponding `.usac` file.
- Raw frame SHA-256:
  `e0ce13de42e0a4c75115701696ae2299e305d4cf92b2b8591cf5ee0a6463944a`.
- Sample BLOB SHA-256:
  `6464fb56d7e1011630dc4eb5b143055006a0ac57b7a0eaa69c6a3f4be9e77fa4`.

The raw USAC frame was decoded independently and its 2048-value sample tuple
was byte-for-byte equal to the SQLite-exported 4096-byte BLOB. The bridge spool
then reported zero pending frames and one committed tombstone, closing the
first-frame device-to-SQLite delivery path without a silent drop.

## Restart and persistence checkpoint

Core and bridge were each restarted once without issuing another capture. Both
containers returned healthy, the device reconnected with normal health, the
capture remained queryable, and the host database/spool files remained present
(`98304` and `28672` bytes at the checkpoint). The new bridge session correctly
downgraded the prior applied configuration to DRAFT, requiring explicit
re-application before another capture.

After that restart, the save-policy batch below successfully performed another
single capture. This closes the M6 restart/persistence item: both bind mounts
survived service restart and the recovered stack continued real acquisition.

## Real save-policy matrix

The operator authorized five additional `Pulse=1` acquisitions at external
7 V with no automatic retry. The existing D10x4 draft was applied unchanged
first; all ten TUSS4470 register/value pairs read back identically. Exactly one
POST was issued for each single acquisition or periodic start operation.

- `SAVE_ALL`: one new single frame completed with requested/acquired/saved/
  policy-discarded counts `1/1/1/0`. Together with the first Jetson frame above,
  the real Jetson database contains the required two `SAVE_ALL` archives.
- `SAVE_LAST`: one finite periodic task acquired three frames at a 1 s period
  and completed with counts `3/3/1/2`. Only the final capture was present in
  `captures`; the first two retained bounded `ROLLING_LATEST` decisions, and
  the final decision was `RAW_ARCHIVED`. No rolling BLOB remained after
  completion.
- `SAVE_NONE`: one single frame completed with counts `1/1/0/1` and decision
  `DISCARDED_BY_POLICY`. No immutable capture row was created. The bounded
  transient endpoint returned exactly 4096 sample bytes with storage marker
  `TRANSIENT`; its sample SHA-256 was
  `feb2687a4741297f8fc85904dd9ab06ca8b4f848e7572428b4993662de0b4da6`.
- After all five new frames, the bridge spool contained zero pending records
  and six committed tombstones in total (the first Jetson frame plus this
  five-frame batch).

Core SQLite contained exactly two new immutable rows for this batch: the
`SAVE_ALL` frame and the final `SAVE_LAST` frame. Each held a 4096-byte sample
BLOB and a 4324-byte original wire frame. This matches the requested save
semantics; neither superseded `SAVE_LAST` frames nor the `SAVE_NONE` frame were
reported as archived.

## Remaining before M6/G3J closure

- Prove Compose startup with external network unavailable.
- Complete safe non-default device-field-group apply/readback coverage.
- Complete the real-hardware sampling/frequency/Burst/IO_MODE, sync, sweep, and
  OUT3/OUT4 checks required by the roadmap.
- Complete periodic STOP and lease-expiry checks; the finite three-frame
  periodic natural-completion path is now verified.
- Complete the milestone Git/Jetson synchronization closure.
