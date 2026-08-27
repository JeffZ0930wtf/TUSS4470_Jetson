# M0 verification summary

Date: 2026-08-24
Milestone: `milestone(M0): complete cross-platform skeleton`

## Document overview

This record summarizes the evidence used to close M0. It applies only to the
cross-platform skeleton and safe non-flashed firmware build; later milestone
summaries supersede it for implemented functionality but not for historical
toolchain evidence.

## Scope and safety result

M0 establishes the cross-platform repository, reproducible Python environment,
configuration/serial abstractions, safe MSP430F5529 compile skeleton, and
multi-architecture container smoke test. It does not configure TUSS4470, issue
a Burst, flash the LaunchPad, acquire a waveform, or connect to a cell.

The firmware skeleton sets the future IO2 output (`P2.5`) high, configures no
timer, and enters low-power mode. The produced ELF was compiled but not flashed.

## Windows evidence

Validated in PowerShell from `D:\Desktop\TUSS4470_software` using the repository
`.venv`:

- Windows project Python: CPython 3.12.14.
- `uv`: 0.12.5; environment synchronized from committed `uv.lock` with
  `uv sync --frozen --extra dev`.
- Git: 2.54.0.windows.1.
- TI MSP430 GCC: 9.3.1.11.
- TI MSP430 support files: 1.212.
- `scripts/test-all.ps1`: Python tests pass and `firmware/build/m0-safe.elf`
  compiles successfully.
- Firmware size: text 48 B, data 0 B, bss 4 B, total 52 B.
- Docker Desktop: not installed; optional for the approved Windows M0 role.
- MSP430 flashing utility: not installed; optional in M0, and no flashing
  command is present in the M0 test path.
- Connected TI/LaunchPad USB CDC device: not present during the final PnP
  probe, so no active-device driver version could be recorded. The environment
  checker reports this explicitly as an optional M0 item; USB enumeration and
  driver acceptance remain part of the later real-hardware gate.

The official tool archives were checksum-verified before local extraction.
They remain under ignored `.tools` and are not repository content:

- `msp430-gcc-9.3.1.11_win64.zip`:
  `9afcebfdb60e45b6f471fe1c16e970390198e323a77cdf4629cd239811a5c567`
- MSP430 support files 1.212 archive:
  `3b1a39f10a344dfefb767e60ac35becef4c065013be86993195b138a5fb0b8d6`
- `uv` 0.12.5 Windows archive:
  `4c4d49d8738847d9b71ba319e49a5688c93eac0fe6204b1df24e98528dddf39a`

## Jetson evidence

Validated on the target Jetson Orin Nano running JetPack 7.2.1 / Jetson Linux
39.2.1 / Ubuntu 24.04 ARM64, from a temporary M0 source snapshot with its own
checkout-local `.venv`:

- Host Python: 3.12.3; project environment synchronized from the same `uv.lock`.
- `uv`: 0.12.5 aarch64.
- Git: 2.43.0.
- Docker Engine: 29.1.3.
- Docker Compose: 2.40.3.
- Docker Buildx: 0.30.1.
- Python test suite: 13 passed.
- Native `linux/arm64` image built and ran, printing
  `usac-core-skeleton:ready`.
- ARM64 image ID:
  `sha256:3ec943062089412085928ca469a2feac9c161243b55d5aefa9c60af366bb4ef5`.
- `linux/amd64` OCI image cross-build completed without emulation or target
  execution. Output size was 43,210,752 B; SHA-256:
  `a74a5a729aaefb600ed5a38736fb45d81a21dbe0f8497e693324ce955f0e7788`.
- MSP430 GCC is absent on ARM64 and is intentionally optional for the Jetson
  role.

## Configuration and portability checks

- Windows serial example uses `COM7`; Jetson uses `/dev/ttyACM0`; the runtime
  treats both as injected opaque values.
- Storage paths come from TOML configuration or `USAC_*` environment variables;
  business code contains no hard-coded Windows drive.
- The runtime package has no third-party runtime dependency in M0.
- The core image uses one Dockerfile and an immutable multi-architecture Python
  base-image digest.
- `.gitattributes` enforces LF for shell scripts, preventing Windows checkout
  conversion from breaking Jetson execution.

## Explicit M0 limitations

- The AMD64 image was cross-built as an OCI artifact on Jetson but was not run;
  no AMD64 Docker engine is present in the approved M0 platform split.
- Actual USB CDC enumeration, LaunchPad flashing, TUSS4470 SPI access, and real
  hardware acquisition are outside M0.
- The present container is a core import/startup smoke image. Bridge/core
  protocol and services begin in later milestones.

Generated `.venv`, `.tools`, firmware binaries, OCI archives, captures, spool
data, databases, and credentials are excluded from version control.
