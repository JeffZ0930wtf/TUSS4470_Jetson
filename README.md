# TUSS4470 Ultrasonic Acquisition Module V1

## Document overview

This README is the operator and developer entry point for V1.0.0 of the
standalone ultrasonic acquisition submodule. It explains what the module
does, how to build and run it on Windows or Jetson, where data is stored, and
which safety limits remain. Protocol details, platform procedures, release
evidence, and historical development records live in the linked documents.

The module configures TUSS4470, controls bounded ultrasonic acquisition, and
outputs exact raw envelope samples plus capture metadata. It does not extract
features or predict battery SOC/SOH; those responsibilities belong to the
future BMS integration layer.

## V1 components

- MSP430 firmware: reset-safe TUSS4470 configuration, finite Burst control,
  ADC/DMA acquisition, exactly 2048 unmodified `uint16` samples, scheduling,
  synchronization inputs, event capture, STOP, and lease expiry.
- Bridge: exclusive USB CDC access, wire validation, reconnect handling, and
  a durable pending spool until Core confirms SQLite commit.
- Core: configuration policy, acquisition sessions, SQLite persistence, REST,
  CLI, and the bilingual Web workbench.
- Web workbench: raw/normalized display, continuous sample windows, and up to
  20 compatible overlaid captures without modifying stored bytes.

## Public commands

V1 exposes exactly four installed commands:

- `usac-core`: REST/Web and acquisition Core. Use `--backend bridge` for real
  hardware or `--backend simulator` for offline UI/API checks.
- `usac-bridge`: long-running USB CDC-to-Core Bridge. Service arguments are
  passed directly; there is no `serve` subcommand.
- `usac-cli`: REST client for status, configuration, capture, sessions,
  history, and sample download.
- `usac-export`: direct offline SQLite inspection and complete `.usac`,
  `.u16le`, and `.json` export without requiring Core to run.

## Development and verification

Each checkout owns a repository-local `.venv`:

```powershell
./scripts/bootstrap-dev.ps1
. ./.venv/Scripts/Activate.ps1
./scripts/check-env.ps1
./scripts/test-all.ps1
```

The Windows aggregate gate runs Python, Web, MSP430 simulator, TI USB-stack,
production firmware, and static safety checks. It does not open a COM port,
flash firmware, or produce a Burst. Windows does not require Docker.

Jetson uses its own checkout-local environment:

```sh
./scripts/bootstrap-dev.sh
. .venv/bin/activate
./scripts/check-env.sh
./scripts/test-all.sh
```

The Jetson gate runs the same host tests, C protocol vectors, one native ARM64
image build/runtime check, and one AMD64 OCI cross-build.

## Firmware

Build the only formal firmware target with:

```powershell
./scripts/build-firmware.ps1
```

The output is
`firmware/build/release/tuss4470-acquisition-fw-0.2.0.2.elf`. Building never
accesses hardware. Flashing is deliberately separate:

```powershell
./scripts/flash-firmware.ps1 -ExternalVpwrOffConfirmed
```

Run it only after physically switching external VPWR off. The script invokes
TI DSLite but sends no serial command and cannot request a Burst.

## Run on Windows

Real operation uses Core with `--backend bridge` and a separate native Bridge.
The current configuration example uses `COM9`; replace it if the verified
LaunchPad application CDC port changes.

```powershell
usac-core --backend bridge --host 127.0.0.1 --port 8000 --bridge-host 127.0.0.1 --bridge-port 8765 --database D:/Desktop/TUSS4470_data/core/acquisition.sqlite3 --host-database-path D:/Desktop/TUSS4470_data/core/acquisition.sqlite3
usac-bridge --config config/windows.example.toml --core-host 127.0.0.1 --core-port 8765 --confirm-external-vpwr-7v
```

Open `http://127.0.0.1:8000/`. Detailed host/container alternatives are in
[Windows deployment](docs/deployment/windows.md).

For UI/API checks without hardware:

```powershell
usac-core --backend simulator --host 127.0.0.1 --port 8000 --database D:/Desktop/TUSS4470_data/core/simulator.sqlite3 --host-database-path D:/Desktop/TUSS4470_data/core/simulator.sqlite3
```

The simulator never opens USB/SPI, flashes firmware, or produces a Burst.

## Run on Jetson

Jetson runs Core and Bridge as separate containers. Select the LaunchPad by
its verified `/dev/serial/by-id/...` identity through `USAC_SERIAL_DEVICE`, not
by a changing `/dev/ttyACM*` ordinal. Follow
[Jetson deployment](docs/deployment/jetson.md) for host/container paths and
Compose commands.

## Data and offline export

Runtime data stays outside the source repository:

- Windows SQLite: `D:/Desktop/TUSS4470_data/core/acquisition.sqlite3`
- Windows Bridge spool: `D:/Desktop/TUSS4470_data/bridge/spool`
- Jetson SQLite host directory: `/var/lib/tuss4470/core`
- Jetson Bridge spool host directory: `/var/lib/tuss4470/bridge/spool`

Use `USAC_CORE_DATA_DIR`, `USAC_BRIDGE_SPOOL_DIR`, and
`USAC_SERIAL_DEVICE` to change deployment paths. To export a committed frame
without running Core:

```powershell
usac-export show --sqlite D:/Desktop/TUSS4470_data/core/acquisition.sqlite3 --capture-id <capture_id>
usac-export download --sqlite D:/Desktop/TUSS4470_data/core/acquisition.sqlite3 --capture-id <capture_id> --output-dir D:/Desktop/TUSS4470_data/exports
```

## Hardware safety

- Verified topology: J2=TX, J3=RX, R12 removed, J1=8 nF, J4=6.8 nF.
- Transmission requires Standard power, external VPWR near 7.0 V with verified
  polarity/current limit, internal VDRV 5 V, SPI readback, `VDRV_READY`, no
  TUSS fault, an applied safe profile, and explicit operator authorization.
- USB-only operation is for development and no-Burst checks; it must not be
  presented as transmission-ready.
- V1 supports finite pulses and leased periodic work. It does not authorize an
  unbounded driver-on state.
- Never commit captures, spool/SQLite files, credentials, firmware binaries,
  or bulky instrument exports.

## Authoritative documents

- [Wire protocol](docs/protocol.md)
- [Windows deployment](docs/deployment/windows.md)
- [Jetson deployment](docs/deployment/jetson.md)
- [V1 acceptance](docs/release/v1.0.0-acceptance.md)
- [V1 known limitations](docs/release/v1.0.0-known-limitations.md)
- [Pre-V1 evidence archive](docs/archive/pre-v1/README.md)
- [Development standards](CONTRIBUTING.md)
