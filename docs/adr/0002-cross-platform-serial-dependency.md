# ADR-0002: Cross-platform serial dependency

Status: Accepted for M2

## Decision

- Use pyserial 3.5 behind the existing `SerialConnection` structural boundary
  for M2 host-to-MSP430 USB CDC communication.
- Resolve it through the committed `uv.lock`; each Windows or Jetson checkout
  runs `uv sync --frozen --extra dev` in its own `.venv`.
- Treat port names as opaque configuration values. Windows supplies `COMx` and
  Linux/Jetson supplies `/dev/ttyACM*`; business and protocol code must not
  branch on those spellings.
- Keep DTR session establishment in the thin CLI/bridge adapter: observed low,
  then a real low-to-high edge. Protocol exchange remains transport-agnostic.

## Architecture assessment

pyserial 3.5 is a pure Python distribution with no platform-specific wheel or
native extension. The locked artifact is therefore usable by both CPython 3.12
on Windows amd64 and Jetson Linux arm64. No JetPack-specific library enters the
protocol or runtime packages.

## Safety consequence

The M2 smoke entry point has no CAPTURE implementation. Its default mode sends
HELLO and GET_CONFIG; `--hello-only` sends HELLO alone; and the explicit
`--apply-same-config` mode can only reapply the configuration it just read and
verified. Hardware transmission remains prohibited independently in firmware.
