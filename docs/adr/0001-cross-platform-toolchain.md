# ADR-0001: Cross-platform M0 toolchain

Status: Accepted for M0

## Document overview

This ADR records the cross-platform toolchain and environment decision that
made the M0 repository reproducible on Windows and Jetson. It applies to all
later milestones unless replaced by another accepted ADR and complements the
repository bootstrap scripts and development standards.

## Decision

- Host code targets CPython 3.12 and uses only the standard library at runtime
  during M0. Pytest is a development-only dependency.
- Runtime configuration is TOML plus `USAC_*` environment overrides. Serial
  names and storage paths are opaque configuration values.
- Firmware targets MSP430F5529 with TI's official MSP430 GCC distribution and
  is compiled only in M0; it is not flashed.
- Container builds target both `linux/amd64` and `linux/arm64` from the same
  Dockerfile. The M0 image contains no native Python dependencies.
- Windows is the M0 source-development, Python-test, and official MSP430
  compile host. Docker Desktop and a flashing utility are optional there.
- Jetson is the M0 native `linux/arm64` build/run host and performs an
  `linux/amd64` OCI cross-build check from the same Dockerfile. Docker Engine,
  Compose, and Buildx are required there; MSP430 compilation is not.

## Environment ownership

- Every repository checkout creates a local `.venv` from the committed
  `.python-version` and `uv.lock`. A Windows `.venv` is never copied to Jetson,
  nor is a Jetson `.venv` copied back to Windows.
- The future BMS application has a separate environment. This acquisition
  module is consumed through a versioned API/data contract, not by merging all
  development packages into one mutable environment.
- Jetson's user-level `~/.venvs/base` is for generic host diagnostics and
  temporary non-project tools only. Repository dependencies belong to the
  checkout-local `.venv` during development and to bridge/core images during
  deployment.

## Reproducible inputs

- CPython is constrained to 3.12 by `.python-version` and `pyproject.toml`;
  dependencies are resolved by `uv.lock` and installed with `uv sync --frozen`.
- Windows firmware compilation uses TI MSP430 GCC 9.3.1.11 with MSP430 support
  files 1.212. Local downloads live under ignored `.tools`; CI or another host
  may provide `MSP430_GCC_ROOT` and `MSP430_SUPPORT_ROOT` instead.
- The core image base is pinned to an immutable multi-architecture digest in
  `deploy/Dockerfile.core`.

## aarch64 assessment

The M0 runtime has no third-party dependencies. Pytest is used only on the
development host and is pure Python. The base image is the official multi-arch
`python:3.12-slim` image. Native dependencies introduced after M0 require a
new ADR entry documenting an available aarch64 wheel or a reproducible source
build before they enter the core path.

## Consequences

- Windows and Jetson share the same Python package and configuration model.
- COM names and `/dev/ttyACM*` remain in example configuration only.
- Required tools are checked per platform role. Missing required tools fail the
  corresponding script; optional tools are reported without being silently
  substituted.
