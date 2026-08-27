# TUSS4470 Ultrasonic Acquisition Module

This repository contains the acquisition-only submodule for the
MSP-EXP430F5529LP and BOOSTXL-TUSS4470. It does not calculate ultrasonic
features and does not predict SOC or SOH.

## Hardware safety boundary

- M0 builds tools and a non-flashed firmware skeleton only. It must not trigger
  TUSS4470 transmission.
- USB-only operation is limited to development and no-Burst diagnostics.
- Later transmission requires the approved Standard power profile, external
  VPWR 7.0 V, internal VDRV 5 V, SPI readback, VDRV_READY, fault checks, and the
  explicit hardware gate defined by the controlled design.
- Never commit captures, spool files, SQLite databases, credentials, firmware
  binaries, or large instrument exports.

## Implemented through M1; M2 candidate under hardware verification

- Cross-platform runtime configuration and serial transport boundary.
- USAC v1 little-endian frame codec, CRC-32/ISO-HDLC, bounded host stream
  parser, exact message lengths, timeout, and deterministic resynchronization.
- Explicit first-version payload codecs for HELLO, configuration, single
  capture, ACK/ERROR, CAPTURE_DATA, bridge delivery, and commit confirmation.
- Complete TUSS4470 user-field plus acquisition/run parameter schema at
  `protocol/schema/tuss4470-parameters-v1.yaml`.
- `AcquisitionConfigV2`, D10x4 canonical binary profile, shared C/Python fixed
  vectors, and TUSS4470 16-bit MSB-first odd-parity SPI vector encoder.
- A software-only deterministic simulator that returns exactly 2048 raw
  uint16 samples and rejects configurations unsafe for the approved BOOSTXL
  direct-drive profile.

M1 needs no connected LaunchPad or TUSS4470. The simulator never enumerates
USB, opens SPI, flashes firmware, or emits a Burst.

The M2 candidate adds reset-safe IO, USB CDC, bounded MCU parsing, stable
identity, TUSS4470 SPI configuration/readback, VDRV status checks, and explicit
Standby/Sleep transitions. Its public `CAPTURE_ONCE` path always returns
`INVALID_STATE`; no M2 source path can drive IO2 low or start the Burst timer.
Every session-end and configuration-failure path clears trigger state, puts
VDRV in Hi-Z, and leaves the TUSS4470 in Standby so an idle IO_MODE 3 profile
is not armed across an MCU reset.
The last verified configuration snapshot remains reportable across a clean
DTR close, but the hardware profile is marked inactive until it is explicitly
reapplied and read back; these are separate safety states.
The verified bring-up SPI rate is 1 MHz (24 MHz SMCLK divided by 24). This is
inside TI's allowed range and is intentionally below the 8 MHz maximum; the
SPI link is a control path and is not the ADC sample clock.

## M2 no-Burst hardware checks

Build first; this does not flash the LaunchPad:

```powershell
. ./.venv/Scripts/Activate.ps1
./scripts/build-firmware-m2.ps1
./scripts/test-m2-safety.ps1
```

Flashing is a separate controlled action. Turn external VPWR off while keeping
the LaunchPad USB/debug connection present, close the TI GUI and any process
holding its ports, then run:

```powershell
./scripts/flash-firmware-m2.ps1 -ExternalVpwrOffConfirmed
```

The script targets only the fixed M2 no-Burst ELF and uses TI DSLite with
erase, flash, and verify. It refuses to run without the physical-power
confirmation flag. Re-enumeration after flashing is expected, so the old COM
number must not be assumed.

After the controlled flashing step, use the same Python command on Windows
(`COMx`) or Jetson (`/dev/ttyACM*`). With external VPWR off, only verify USB,
the DTR session gate, and identity:

```powershell
usac-m2-smoke --port COM8 --hello-only
```

`--hello-only` sends HELLO only. It does not access TUSS4470 configuration and
never sends CAPTURE. Before configuration verification, apply the approved
Standard topology: J6 only 3-4 fitted, J8 fitted, external VPWR 7.0 V with
correct polarity and current limit, J2=TX, J3=RX, R12 removed, J1=8 nF, and
J4=6.8 nF. Reset/re-enumerate the LaunchPad after VPWR is stable, then run:

```powershell
usac-m2-smoke --port COM8
usac-m2-smoke --port COM8 --apply-same-config
```

The first command reads the configuration. The second reapplies exactly the
verified bytes and requires an ACK after SPI readback; it is not a general raw
register writer. All three modes emit JSON with `burst_command_sent: false`.
The port name is an example and must be replaced by the enumerated device.

## Development checks

Each checkout owns its own project environment at `.venv`. Do not copy this
directory between Windows and Jetson, and do not install this module into the
future BMS-wide environment. The module will be integrated through its
versioned data/API boundary in later milestones.

Windows PowerShell (development, tests, and MSP430 compile):

```powershell
./scripts/bootstrap-dev.ps1
. ./.venv/Scripts/Activate.ps1
./scripts/check-env.ps1
./scripts/test-all.ps1
```

Jetson shell (ARM64 tests/container execution and AMD64 cross-build check):

```sh
./scripts/bootstrap-dev.sh
. .venv/bin/activate
./scripts/check-env.sh
./scripts/test-all.sh
```

The Jetson host-wide `~/.venvs/base` environment is reserved for generic host
diagnostics and temporary tools. It is not the repository environment and must
not receive bridge/core project dependencies. Production bridge/core processes
will run in their own containers; `.venv` exists for checkout-local development
and verification only.

Windows does not require Docker Desktop or a flashing utility for M0/M1. It
requires the official Windows MSP430 compiler. On the Jetson, Docker, Compose,
Buildx, and a host C compiler are required; the non-native MSP430 compiler is
not. `scripts/test-all.sh` validates the C/Python vectors, runs the ARM64 image,
and exports an AMD64 OCI image from the same source.

Runtime paths and serial ports are supplied by TOML or `USAC_*` environment
variables. Application code must not contain fixed Windows drive paths.
