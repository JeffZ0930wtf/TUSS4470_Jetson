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

## M0 quick checks

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

M0 intentionally does not require Docker Desktop or a flashing utility on the
Windows host. It requires the official Windows MSP430 compiler there. On the
Jetson, Docker, Compose, and Buildx are required; the non-native MSP430 compiler
is not.

Runtime paths and serial ports are supplied by TOML or `USAC_*` environment
variables. Application code must not contain fixed Windows drive paths.
