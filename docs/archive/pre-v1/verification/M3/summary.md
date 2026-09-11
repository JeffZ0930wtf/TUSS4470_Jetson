# M3 verification summary

Status: Closed with explicitly accepted limitations

Date: 2026-08-31

## Document overview

This record preserves the automated and real-hardware evidence for the M3
single-waveform acquisition milestone. It demonstrates one safely gated Burst,
one complete unmodified 2048-sample ADC capture, and lossless delivery of the
corresponding protocol frame to the Windows host. It applies to the M3 firmware
and host CLI only. It complements the protocol specification, the M3 capture
transport design, and the staged roadmap; it does not claim battery-state
interpretation, calibrated acoustic timing, periodic acquisition, or BMS
integration.

## Accepted M3 configuration

- Hardware: MSP-EXP430F5529LP plus BOOSTXL-TUSS4470, separate J2 TX and J3 RX,
  R12 removed, D10x4 transducers, external VPWR at 7 V, and USB CDC on COM9.
- Safety loopback: pin 40 through 2.2 kohm to pin 38.
- Excitation: one authorized Burst with `BURST_PULSE=1`; the host did not retry.
- Acquisition: 200 kS/s nominal, 2048 real ADC samples, 64-sample pretrigger,
  and no interpolation.
- D10x4 profile identity: SHA-256
  `b8826eaf278d7360189d49aced322ff9e404d8266a25e76a011065c2fda5c998`;
  device configuration CRC32 `0x5D4FC286`.

## Final automated verification

A fresh completion run on 2026-08-31 exited with code 0 and did not access
COM9:

- all 84 Python protocol, runtime, CLI, and project-layout tests passed;
- MSP430 simulator unit tests passed;
- the TI official C4 USB CDC smoke build passed;
- M0 safe, M2 no-Burst, and M3 acceptance firmware builds passed;
- M2 static safety, M3 loopback safety, M3 acquisition, and M3 no-Burst
  DMAREQ diagnostic audits passed;
- the M3 image contained exactly one 4096-byte waveform buffer and used
  5530 bytes of static RAM; and
- `git diff --check` reported no whitespace error (line-ending notices only).

The feature-worktree rebuild reproduced the exact flashed ELF SHA-256. A final
clean-main rebuild used a different absolute source path, so its complete ELF
contained different path-dependent debug metadata. Converting both ELFs to
their loadable binary image produced identical 48128-byte files with SHA-256
`da4a9d89d1cb5363367af7b05e480e04389c2cc6dfd7317f3ac43cc1ac044dd1`.
No loadable firmware byte changed during milestone documentation closure.

The clean-main gate also exposed two test-entrypoint dependencies on ignored
historical build products: pytest's configured parent directory was not
created, and the ADC/DMA diagnostic static audit assumed its ELF already
existed. Both were corrected red-green. `test-all.ps1` now creates the ASCII
pytest build parent and explicitly builds the diagnostic image before auditing
it, so a cleaned checkout can reproduce the complete M3 offline gate.

## Firmware and startup gate

With external VPWR off, TI DSLite programmed and verified
`firmware/build/m3/usac-m3-acceptance.elf`. The flashed ELF SHA-256 was
`7f99b44fb42c0e742eb6be94b8d1cc3856a5dcd94b32db5cc66be782aa6bc719`.
Flashing did not open COM9 or issue a Burst.

After external 7 V was restored and S3 RST was pressed, a read-only HELLO plus
GET_CONFIG session returned:

- device ID `c5fa4769c16da8710b8688c70ba34cf7`;
- firmware version `0.2.0.2`;
- device state 6 (`IDLE_SAFE`);
- the expected profile SHA-256 and configuration CRC32;
- sample interval 120 SMCLK ticks; and
- Burst period 50 SMCLK ticks.

The read-only command reported `burst_command_sent=false` and did not perform
SET_CONFIG, CAPTURE, or Burst.

## Single real capture evidence

After separate operator authorization, the M3 CLI issued exactly one
CAPTURE_ONCE request. The loopback gate passed before the Burst. The device
ACKed the request and the host received one continuous 4324-byte CAPTURE_DATA
frame. Receive progress advanced through the complete frame without the former
128-byte transport stall. No automatic retry or second Burst occurred.

Capture identity: `83bcdbec99e257d91cd7eafb552d0d46`.

The locally archived evidence has these properties:

| Evidence | Size | SHA-256 |
|---|---:|---|
| Raw `.usac` frame | 4324 B | `65a9b512ebe73059eefe73affcb7749ad09c21e4e453999434e2243d6e736f13` |
| Raw `.u16le` samples | 4096 B | `43136c5957d4b82f9ce934f8c6b460944ab8272702dab2f699a54104edc953e2` |
| Metadata JSON | 1669 B | `7b7582b0f87a5c37fe3ed775e96db8b0ba5a0f22587719223817f14d16874218` |

The repository protocol decoder accepted the frame. The 4304-byte payload and
stored CRC32 `0x1F26BA31` matched a fresh CRC-32/ISO-HDLC calculation over the
normative `protocol_version`-through-payload range. The decoded data contained
exactly 2048 unsigned 16-bit samples and a 64-sample pretrigger. The separate
sample file contained exactly 4096 bytes. Its observed values ranged from 1116
to 2505 ADC counts with an arithmetic mean of 2168.2080078125 counts. These
statistics are descriptive only; the raw values were neither corrected nor
interpolated.

Metadata explicitly records `interpolated=false`. Quality flag `0x00000020`
means `TIMING_UNCALIBRATED`: the nominal 24 MHz clock has not been measured
against an external time reference. It does not indicate a truncated frame or
failed ADC capture.

## Transport defect closed by this candidate

The earlier firmware divided every logical region into application-level
64-byte CDC sends and advanced its stream iterator before TI USB accepted and
completed a transfer. Exact packet-sized transactions therefore mixed protocol
progress with endpoint scheduling and could leave the host stalled after a
partial frame.

The accepted candidate exposes four immutable regions (16-byte frame header,
208-byte metadata, 4096-byte sample buffer, and 4-byte CRC) and advances only
after the TI CDC completion callback. A transport-neutral state machine keeps
the same pointer and length on BUSY, permits only one segment in flight, and
fails closed on fatal or unknown start results. TI's USB stack remains
responsible for endpoint packetization. The protocol frame itself is unchanged.

Future retry, delivery acknowledgement, periodic backpressure, and bridge/core
spooling attach outside this frame source and transport state machine. Their
extension boundaries and invariants are defined in
`docs/m3-capture-transport-design.md`; they are not implemented or claimed by
M3.

## Accepted limitations

- The clock is nominal rather than externally calibrated, so absolute sample
  time and derived TOF must carry the timing-uncalibrated quality flag.
- DMA destination increment and sample ordering passed pure-C incremental
  vectors, static configuration checks, and continuous real-frame delivery,
  but no real known analogue ramp was applied to the ADC. The user accepted
  this as non-blocking for M3; the independent known-input HIL remains in M7.
- M3 retained the corrected M2 reset-safe startup and forced Standby after the
  authorized capture, but did not execute a complete post-Burst WDT/PUC reset
  matrix. The user accepted this as non-blocking for controlled single
  captures; the full reset matrix remains in M7.
- The recorded waveform proves acquisition and lossless output, not that a
  particular interval represents an internal battery echo.
- M3 supports the controlled single-capture path. Periodic acquisition,
  durable delivery acknowledgement, SQLite ingestion, and Jetson validation
  remain later roadmap work.
- This milestone does not establish SOC, SOH, temperature, ageing, gas, or
  lithium-plating relationships.

The local binary evidence is retained under
`archive/local/M3/first-waveform-four-segment-tx-20260831/` according to the
repository archive policy. Its hashes above are the reviewable link from this
committed summary to the unmodified local files.

## Formal milestone closure

The M3 implementation commit `cda696d` contains the accepted firmware, host
runtime, tests, design records, and real-capture evidence summary. This closure
update is intentionally non-functional: it aligns README, repository-wide
development rules, and accepted limitations before the required
`milestone(M3): complete Windows hardware waveform` commit is pushed to
`origin/main`. The authoritative roadmap records the final local/remote SHA
after that push; M4 code must not start before the SHA check and worktree
archive complete.
