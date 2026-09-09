# M6 Jetson real-hardware validation checkpoint

## Document overview

This document records the in-progress M6 verification performed on the real
Jetson Orin Nano, MSP-EXP430F5529LP, BOOSTXL-TUSS4470, and D10x4 hardware
chain. It preserves reproducible evidence for ARM64 deployment, Linux USB CDC,
the first real capture, data identity, and container persistence. It
complements the controlled roadmap and is not an M6 closure summary; unchecked
M6/G3J items remain mandatory.

## Verified platform and revision

- Dates: 2026-09-08 through 2026-09-09 (Asia/Shanghai).
- Jetson: `172.20.149.177`, JetPack 7.2.1 / Jetson Linux 39.2.1 / ARM64.
- Isolated verification worktree:
  `/home/yizhouzhao/workspace/TUSS4470_verification/worktrees/m6-host-3-0-increment`.
- Verified candidate revisions through `c297095`.
- The Jetson main worktree remained clean at the closed M5 baseline
  `a7fc178cc8ade60f287179a45b7234bff7ca9991`.
- Device ID: `c5fa4769c16da8710b8688c70ba34cf7`.
- Firmware CDC endpoint was `/dev/ttyACM2` before a Jetson reboot and
  `/dev/ttyACM0` after it. The stable identity path is:
  `/dev/serial/by-id/usb-Texas_Instruments_MSP430-USB_Example_c5fa4769c16da8710b8688c70ba34cf7-if00`.
  The two `MSP Tools Driver` endpoints are eZ-FET interfaces and must not be
  selected by their changing ordinal names.

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

### Known diagnostic limitation found by this check

The three distinct sample BLOBs had different SHA-256 values, but the exposed
`transport_crc32`/bridge `inner_frame_crc32` value was identical. Source review
confirmed that this CRC is currently calculated over the complete already-CRC-
protected USAC frame. A valid CRC codeword has a fixed residue, so this value is
not a useful content fingerprint. This did not invalidate the batch: the
native USAC decoder independently validates the frame-body CRC before parsing,
core stores an SHA-256 of every terminal processing decision, and archived
sample BLOBs are derived from the validated frame without interpolation.

The field should be corrected before it is presented as a diagnostic content
checksum in a production release, for example by calculating the wrapper CRC
over the inner frame excluding its existing CRC trailer. Changing that
cross-component semantic requires an explicit protocol-compatibility test and
is not folded into this hardware-verification batch.

## Offline Compose checkpoint

The already-built ARM64 images were tested without an external Docker network.
Core and bridge were attached only to a Docker network inspected as
`Internal=true`, both services were restarted in that state, and bridge reached
core over the private Compose path. The device identity remained stable. The
D10x4 baseline then applied through the ordinary REST/core/bridge/USB path and
read back all ten register/value pairs with profile SHA-256
`b8826eaf278d7360189d49aced322ff9e404d8266a25e76a011065c2fda5c998` and
configuration CRC32 `1565508230`. No image pull, package download, external
route, capture, or Burst was needed for this checkpoint.

## Complete configuration field-group checkpoint

The shared schema and validator were used for nine safe non-default field-group
applications. Every apply completed a real TUSS4470 SPI write/readback and
returned a changed configuration CRC:

| Safe field group | Readback CRC32 |
|---|---:|
| BPF/HPF trim and Q | 4110405185 |
| log-amplifier intercept/slope | 3998316186 |
| LNA, VOUT, and GM stages | 1028950696 |
| IO mode, driver, and pulse filter | 739798724 |
| VDRV listening policy | 2212348289 |
| echo interrupt comparator | 3436785313 |
| zero-cross comparator | 3991623274 |
| Burst/driver fields | 3191629663 |
| trigger and power-state fields | 3007423402 |

Nine values that are legal schema drafts but unsafe for the current BOOSTXL
profile were rejected before hardware side effects: `BURST_PULSE`,
`CMD_TRIGGER`, `PRE_DRIVER_MODE`, `SLEEP_MODE_EN`, `STDBY_MODE_EN`,
`VDRV_CURRENT_LEVEL`, `VDRV_HI_Z`, `VDRV_VOLTAGE_LEVEL`, and
`VOUT_SCALE_SEL`. The baseline was restored and the device ended
`NORMAL/IDLE`, with `VDRV_READY=1` and `TUSS_DEV_STAT=8`.

## Real range, run-plan, event, and sweep checkpoints

Four bounded real captures exercised the supported endpoints without automatic
retry:

| Sequence | IO mode | Sample ticks | Burst ticks | Pulse | Capture ID |
|---:|---:|---:|---:|---:|---|
| 1 | 0 | 960 | 800 | 1 | `74bf5c957b7fe0a8f2ba32cd9c8d49d3` |
| 2 | 1 | 120 | 24 | 2 | `e6b77a89b1577f69bbd77d21c42dba71` |
| 3 | 2 | 120 | 50 | 1 | `a0439a1a14ba7079e071b63f2aa4ed63` |
| 4 | 3 | 120 | 50 | 63 | `019e5c6a9dae67909f1f22375569f928` |

Every capture contained exactly 2048 samples and 4096 sample bytes. This covers
the 25/200 kS/s sampling endpoints, 30/1000 kHz Burst-period endpoints, finite
Pulse endpoints, and IO_MODE 0 through 3 while retaining the same schema and
data contract as Windows.

`EXTERNAL_SYNC_MASTER` completed capture
`c53140cb18e4f0ee412538791c56bb6d`. Real OUT3 and OUT4 enabled captures
`3abe3a8408d59390a6f8ba8833671989` and
`47a426c28193d66ca954ebaf045061d2`; the current signal produced no event edges,
which is a valid empty event list. OUT3 retained the expected
`TIMING_UNCALIBRATED|EVENT_TIME_AMBIGUOUS` degradation and OUT4 retained
`TIMING_UNCALIBRATED`. A two-value BPF sweep completed session
`58c643e7304b45aca177c99ae3891a31`, acquired two frames, saved only the last
under `SAVE_LAST`, and restored the baseline afterward.

## Periodic STOP and lease-expiry checkpoints

A finite two-frame periodic session
`b86700bdf6b140608078386d6b54abd8` completed naturally. An infinite session
`0ca01b42d6ac43c39e69a2a5704cf35a` was explicitly stopped after two frames;
its capture sequence remained stable afterward and the device returned to
idle with no active schedule.

For the firmware lease check, infinite 200 ms scheduling began as session
`7713652972fc46648f90e1dea5e7a5d7` with schedule
`e8f789bc0be54c868918ed469f0a2cd6` and a 3000 ms lease. Core was then paused
for longer than the lease. Firmware cleared the schedule, reported
`LEASE_EXPIRED`, and the observed sequence remained fixed at 120 for a further
1.1 seconds after core resumed. Tool-output latency allowed 107 frames before
the deliberate pause; this does not represent a requested count gate, and no
frame was silently lost.

## Slave synchronization checkpoint

BOOSTXL pin 11/P8.1 was connected through 2.2 kOhm to pin 20/GND for the low
state; pin 13 remained disconnected. A 1000 ms Slave request returned the
expected structured device error 26 with capture sequence unchanged at zero,
proving that timeout starts no Burst.

For the accepted capture, the input was held low while a single 60000 ms Slave
request armed, then moved through the same resistor to pin 1/3.3 V. The one
low-to-high edge completed capture `fabe00644d8f16a721734d93e174315c`,
sequence 1. Core SQLite contains exactly 2048 samples, a 4096-byte sample BLOB,
a 4324-byte wire frame, and the full `EXTERNAL_SYNC_SLAVE` RunPlan. Bridge
pending was zero after the matching commit confirmation. The device ended
`NORMAL/IDLE`, `last_error=0`, `missed_capture_count=0`, `VDRV_READY=1`, and
`TUSS_DEV_STAT=8`.

Two earlier manual attempts expired before the operator edge reached the
60-second firmware window. Both returned error 26, left sequence zero, and
started no Burst; they were not automatically retried.

## Reboot and USB-device-name observation

A Jetson reboot recovered a host-controller enumeration failure, but also
demonstrated why `/dev/ttyACM*` ordinals are not identities: the firmware CDC
moved from `ttyACM2` to `ttyACM0`, while the eZ-FET endpoints took the other
numbers. The stable `by-id` link continued to identify the firmware by product
name and its 32-character device serial. Recreating bridge with the real CDC
mapping and restarting a core whose previous bridge-accept path was occupied
restored HELLO without flashing or a Burst. Deployment instructions now require
the stable identity path and explicitly prohibit identifying the acquisition
port by ordinal alone.

## Remaining before M6/G3J closure

All functional and real-hardware items in roadmap section 9.2 are complete.
Only the prescribed full regression, milestone summary, Git integration/push,
Jetson main synchronization, and completed-worktree cleanup remain.
