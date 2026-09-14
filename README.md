# TUSS4470 Ultrasonic Acquisition Module V1

[English](README.md) | [简体中文](README.zh-CN.md)

## Document overview

This README is the operator and developer entry point for V1.0.1 of the
standalone ultrasonic acquisition submodule. It explains what the module
does, how to build and run it on Windows or Jetson, where data is stored, and
which safety limits remain. Protocol details, platform procedures, release
evidence, and historical development records live in the linked documents.

V1.0.1 adds one-shot Jetson startup from Windows or the Jetson desktop. It
uses `tuss4470-acquisition-core:1.0.1`, built from the released V1.0.1 source;
the acquisition runtime and firmware are unchanged. See the
[V1.0.1 release notes](docs/release/v1.0.1-release-notes.md) for verification
scope and the distinction between this source release and the runtime image.

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

## Functional code map

This table is the shortest route from a visible function to its maintained
implementation. Historical M1-M6 material under `docs/archive/pre-v1/` is
evidence and design history, not the entry point for current development.

| Function | Maintained implementation |
|---|---|
| Windows remote Jetson launcher | [`scripts/start-jetson.ps1`](scripts/start-jetson.ps1) |
| Jetson Core/Bridge launcher | [`scripts/start-jetson.sh`](scripts/start-jetson.sh) |
| Container deployment | [`deploy/compose.jetson.yaml`](deploy/compose.jetson.yaml), [`deploy/Dockerfile.core`](deploy/Dockerfile.core) |
| Core process entry | [`core_server.py`](packages/usac_runtime/src/usac_runtime/core_server.py) |
| REST API routes | [`api.py`](packages/usac_runtime/src/usac_runtime/api.py) |
| Acquisition orchestration and state | [`application.py`](packages/usac_runtime/src/usac_runtime/application.py) |
| Parameter validation and application | [`parameter_service.py`](packages/usac_runtime/src/usac_runtime/parameter_service.py) |
| Periodic and sweep run plans | [`run_plan.py`](packages/usac_runtime/src/usac_runtime/run_plan.py), [`periodic_lease.py`](packages/usac_runtime/src/usac_runtime/periodic_lease.py) |
| Core SQLite persistence | [`core_store.py`](packages/usac_runtime/src/usac_runtime/core_store.py) |
| Bridge process and device session | [`bridge_cli.py`](packages/usac_runtime/src/usac_runtime/bridge_cli.py), [`bridge_device_client.py`](packages/usac_runtime/src/usac_runtime/bridge_device_client.py) |
| Bridge forwarding, reconnect, and pending spool | [`bridge_session.py`](packages/usac_runtime/src/usac_runtime/bridge_session.py), [`reconnect.py`](packages/usac_runtime/src/usac_runtime/reconnect.py), [`spool.py`](packages/usac_runtime/src/usac_runtime/spool.py) |
| REST CLI and offline SQLite export | [`client_cli.py`](packages/usac_runtime/src/usac_runtime/client_cli.py), [`export_cli.py`](packages/usac_runtime/src/usac_runtime/export_cli.py) |
| Web page, behavior, and styling | [`index.html`](packages/usac_runtime/src/usac_runtime/web/index.html), [`app.js`](packages/usac_runtime/src/usac_runtime/web/app.js), [`styles.css`](packages/usac_runtime/src/usac_runtime/web/styles.css) |
| Wire messages and stream parsing | [`packages/usac_protocol`](packages/usac_protocol/src/usac_protocol), [`docs/protocol.md`](docs/protocol.md) |
| Parameter names, ranges, and dependencies | [`tuss4470-parameters-v1.yaml`](protocol/schema/tuss4470-parameters-v1.yaml) |
| Firmware entry and command state machine | [`main.c`](firmware/src/main.c), [`usac_firmware_app.c`](firmware/src/usac_firmware_app.c) |
| TUSS4470 register configuration | [`tuss4470_configurator.c`](firmware/src/tuss4470_configurator.c), [`tuss4470_profile.c`](firmware/src/tuss4470_profile.c) |
| ADC/DMA capture and MSP430 hardware binding | [`usac_capture.c`](firmware/src/usac_capture.c), [`usac_acquisition_platform_msp430.c`](firmware/src/usac_acquisition_platform_msp430.c) |
| Burst safety and capture scheduling | [`usac_burst_plan.c`](firmware/src/usac_burst_plan.c), [`usac_capture_schedule.c`](firmware/src/usac_capture_schedule.c) |
| Firmware build, flash, and full gates | [`build-firmware.ps1`](scripts/build-firmware.ps1), [`flash-firmware.ps1`](scripts/flash-firmware.ps1), [`test-all.ps1`](scripts/test-all.ps1), [`test-all.sh`](scripts/test-all.sh) |

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

Each checkout owns a repository-local `.venv`. Bootstrap, environment checks,
the Windows/Jetson test split, and firmware verification responsibilities are
maintained in [CONTRIBUTING.md](CONTRIBUTING.md). The aggregate gates do not
open a serial port, flash firmware, or produce a Burst.

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

To operate the Jetson-hosted real system from Windows, first confirm external
VPWR is 7 V and press S3 RST after the supply is stable, then run:

```powershell
.\scripts\start-jetson.ps1 -ExternalVpwr7VConfirmed
```

The script asks the Jetson launcher to start the containers, reuses or creates
the local SSH tunnel, and opens `http://127.0.0.1:18080/`. It never starts a
capture or Burst.

Native Windows Core/Bridge operation and the no-hardware simulator remain
available through the command line. Their complete commands, data paths, and
stop procedure are maintained in
[Windows deployment](docs/deployment/windows.md). The simulator never opens
USB/SPI, flashes firmware, or produces a Burst.

## Run on Jetson

Jetson runs Core and Bridge as separate containers. Select the LaunchPad by
its verified `/dev/serial/by-id/...` identity through `USAC_SERIAL_DEVICE`, not
by a changing `/dev/ttyACM*` ordinal. After checking 7 V and pressing S3 RST,
run:

```sh
./scripts/start-jetson.sh --confirm-external-vpwr-7v
```

The script opens the Jetson browser when a graphical desktop is available and
prints the local URL otherwise. Follow
[Jetson deployment](docs/deployment/jetson.md) for host/container paths,
launcher configuration, and manual Compose commands.

## Web workbench semantics

- The horizontal axis is the original sample index; V1 does not present it as
  calibrated physical time.
- Raw mode displays the stored ADC codes. Normalized mode independently maps
  the complete 2048-point frame to `0–1` using its own minimum and maximum; a
  constant frame is shown as zero. Neither mode changes stored samples.
- Overlay compatibility requires exact equality of `sample_interval_ticks`,
  `pretrigger_count`, and `sample_count`. V1 performs no alignment or
  interpolation.
- At most 20 distinct capture IDs may be selected at once. The main trace,
  hidden selected traces, and selected traces still loading all count toward
  that limit; removing a trace releases its slot.
- Viewing historical data pauses `follow latest` only for the canvas. It does
  not pause or stop acquisition. Restoring follow-latest rebuilds the display
  around the newest frame.
- A frame visible in the canvas may be transient or rolling-latest data; being
  visible does not by itself mean that the frame has been archived in SQLite.

## Data and offline export

Runtime data stays outside the source repository:

- Windows SQLite: `D:/Desktop/TUSS4470_data/core/acquisition.sqlite3`
- Windows Bridge spool: `D:/Desktop/TUSS4470_data/bridge/spool`
- Jetson SQLite host directory: `/var/lib/tuss4470/core`
- Jetson Bridge spool host directory: `/var/lib/tuss4470/bridge/spool`

Use `USAC_CORE_DATA_DIR`, `USAC_BRIDGE_SPOOL_DIR`, and
`USAC_SERIAL_DEVICE` to change deployment paths. The exact offline export
commands are in the Windows deployment guide. `usac-export` reads committed
SQLite data without requiring Core.

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
- [V1.0.1 release notes](docs/release/v1.0.1-release-notes.md)
- [V1 runtime baseline acceptance](docs/release/v1.0.0-acceptance.md)
- [V1 known limitations](docs/release/v1.0.0-known-limitations.md)
- [Pre-V1 evidence archive](docs/archive/pre-v1/README.md)
- [Development standards](CONTRIBUTING.md)
