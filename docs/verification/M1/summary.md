# M1 verification summary

Date: 2026-08-24
Milestone: `milestone(M1): complete protocol and simulator`

## Scope and hardware state

M1 freezes the minimum USAC wire contract, complete first-version parameter
schema, shared fixed vectors, and deterministic software device simulator.
The LaunchPad/TUSS4470 was not required, connected, configured, flashed, or
triggered. The existing MSP430 M0 safety skeleton was compiled only.

## Implemented contract

- Explicit 16-byte header, little-endian scalar encoding, protocol version 1,
  flags, sequence, payload length, and CRC-32/ISO-HDLC.
- Host limits of 8192-byte payload, 16424-byte receive buffer, and 2000 ms frame
  assembly timeout, with deterministic one-byte candidate resynchronization.
- Type-specific layouts for the M1 message set: HELLO, GET/SET_CONFIG,
  CAPTURE_ONCE, CAPTURE_DATA, BRIDGE_CAPTURE_DELIVERY, CAPTURE_COMMITTED,
  ACK, and ERROR.
- Explicit 72-byte D10x4 `AcquisitionConfigV2`, 35-byte canonical profile,
  configuration CRC, profile SHA-256, ordered register pairs, and no C padding.
- All 32 public TUSS4470 user fields and all 15 acquisition/run fields in one
  schema. Register masks cover exactly the 10 official write masks without
  overlap or reserved-bit leakage.
- Six official TUSS4470 SPI odd-parity vectors, transmitted high byte first.
- A software simulator completing HELLO, configuration, and a deterministic
  2048-point single capture while rejecting hardware-unsafe draft values.
- Complete CAPTURE_DATA vector parsed and re-encoded byte-for-byte in Python;
  HELLO, profile, and CAPTURE_DATA vectors independently checked/re-encoded by
  a native C test program on Jetson.

## Windows verification

- CPython 3.12.14 / pytest 8.4.2.
- `scripts/test-all.ps1`: 60 tests passed; no warnings.
- MSP430 safety skeleton: text 48 B, data 0 B, bss 4 B, total 52 B.
- No flashing tool was invoked.

## Jetson verification

Target: Jetson Orin Nano, JetPack 7.2.1 / Jetson Linux 39.2.1 / Ubuntu 24.04
ARM64.

- CPython 3.12.3 / uv 0.12.5 aarch64.
- Docker Engine 29.1.3, Compose 2.40.3, Buildx 0.30.1.
- Python suite: 60 tests passed.
- Native C11 vector checker built with `cc -Wall -Wextra -Werror` and printed
  `C protocol vectors: PASS`.
- Native `linux/arm64` core image built and printed `usac-core-m1:ready`.
- ARM64 image ID:
  `sha256:8b4f3742769a9cf2f226c559888f3e37f068b192391d80982e8fb06b5f91924b`.
- `linux/amd64` OCI cross-build completed from the same Dockerfile without
  executing a foreign-architecture image.
- AMD64 OCI size: 43,231,744 B; SHA-256:
  `23c35d02ff30a4240d33812e72d118024c2c905502216feff7cf3a892181a858`.
- Final source snapshot SHA-256:
  `ca3d0a8ca27b4ef3b6f112f4a99a5818fbd48c2482b09d50867f38e563571c32`.

## Official-source audit

The schema was checked against the local TI TUSS4470 data sheet ZHCSKL2A
register map and tables 7-1 through 7-19, plus TI software development guide
SLAA941. One controlled-design grouping error was corrected: `BPF_FC_TRIM_FRC`
belongs to `BPF_CONFIG_1(0x10)` bit 7, while `BPF_CONFIG_2(0x11)` contains
`BPF_FC_TRIM` and `BPF_Q_SEL`.

## Explicit limitations

- The simulator waveform is deterministic test data, not measured ultrasound.
- M1 does not implement USB CDC enumeration, MCU receive buffers, TUSS4470 SPI
  I/O, register readback, VDRV charging, ADC/DMA, or real Burst authorization.
- Runtime bridge/core services and SQLite persistence are not claimed complete;
  M1 defines and tests their relevant byte contracts only.
- No captured waveform, database, spool file, key, compiler archive, virtual
  environment, OCI image, or generated binary is committed.
