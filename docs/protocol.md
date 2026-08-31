# USAC protocol and parameter contract

Status: frozen for M1
Wire protocol version: 1
Parameter schema: `tuss4470-parameters-v1`

## Document overview

This document freezes the M1 wire-protocol and parameter contract shared by
the MSP430 firmware, host libraries, simulator, and future bridge/core. It
solves byte-level interoperability and configuration-traceability problems for
the acquisition module. The machine-readable schemas and fixed vectors are
authoritative when prose and encoded bytes must be compared.

## Scope

This contract connects future MSP430 firmware, bridge, core, and the M1
software simulator. It transports raw acquisition data and its exact hardware
configuration. It does not calculate peaks, TOF, energy, SOC, or SOH.

M1 is software-only. Nothing in the protocol tests opens USB/SPI or authorizes
a real Burst.

## Authoritative artifacts

- `protocol/schema/usac-protocol-v1.json`: frame fields, CRC parameters,
  endpoint limits, and first M1 message layouts.
- `protocol/schema/tuss4470-parameters-v1.yaml`: every public TUSS4470 user bit
  plus all approved acquisition/run fields. The file uses the JSON-compatible
  subset of YAML 1.2 so the runtime can parse it without another dependency.
- `protocol/vectors/hello-request-v1.hex`: complete HELLO request frame.
- `protocol/vectors/d10x4-profile-canonical-v2.hex`: the 35-byte canonical
  D10x4 profile input shared by CRC-32 and SHA-256.
- `protocol/vectors/capture-data-v1.hex`: complete CAPTURE_DATA frame with four
  samples and one event for serializer interoperability tests.

## Frame

Every multibyte scalar is little-endian. The fixed 16-byte header is `USAC`,
protocol version, message type, flags, sequence, and payload length. A 4-byte
CRC-32/ISO-HDLC follows the payload and covers the bytes from protocol version
through the end of the payload; Magic is excluded.

The host payload limit is 8192 bytes and its receive-buffer hard limit is 16424
bytes. Candidate assembly expires after 2000 ms. A bad version, type, reserved
flag, type-specific length, or CRC discards only the first byte of the candidate
Magic before scanning again. Magic inside a valid payload is never scanned.

The MCU-side limit remains a separate contract: at most 192 command-payload
bytes in a 256-byte receive ring. CAPTURE_DATA is transmitted incrementally
from the single waveform buffer and is not an MCU inbound message. The wire
frame is continuous and has no transport-chunk boundaries: USB endpoint packet
size and firmware send-segment size are implementation details that must not be
encoded into, or inferred from, this protocol.

## Configuration

`AcquisitionConfigV2` explicitly serializes timing ticks, sample geometry,
ADC/VREF, ordered register pairs, profile SHA-256, and configuration CRC. It
never serializes a compiler structure or uses a requested floating-point
frequency as device authority.

For `d10x4_v1`:

- canonical profile length: 35 bytes;
- wire configuration length: 72 bytes;
- `device_config_crc32`: `0x5D4FC286`;
- `profile_sha256`:
  `B8826EAF278D7360189D49ACED322FF9E404D8266A25E76A011065C2FDA5C998`;
- sample count: exactly 2048, without interpolation;
- default timing: 120 sample ticks and 50 Burst-period ticks;
- default register image:
  `10:2E 11:00 12:00 13:00 14:03 16:40 17:07 18:14 1A:01 1B:02`.

The schema distinguishes TI reset values from the project default. Encoding
every field's project default must reproduce that D10x4 register image.

## Official TUSS4470 mapping

The register addresses, masks, reset values, enum codes, and conversions come
from the local TI TUSS4470 data sheet ZHCSKL2A, tables 7-1 through 7-19. SPI
framing comes from the data sheet programming section and TI application report
SLAA941: 16 bits, MSB first, SPI Mode 1, and odd parity in bit 8.

In particular, `BPF_FC_TRIM_FRC` is bit 7 of `BPF_CONFIG_1` at address `0x10`.
It is not part of `BPF_CONFIG_2`; the controlled design table was corrected
during M1 to match the official register map.

## Draft versus APPLIED safety

The schema describes every data-sheet-legal semantic value so future UI, CLI,
and REST clients can display and edit the full parameter surface. Legal syntax
does not imply permission to activate hardware.

The current BOOSTXL direct-drive profile rejects these values at the APPLIED
boundary:

- `BURST_PULSE=0` continuous transmission;
- external pre-driver mode;
- 5 V VOUT on the approved 3.3 V ADC chain;
- internal VDRV other than the approved 5 V / 10 mA setting;
- reserved bits, incomplete register images, unsupported sample timing, or a
  sample count other than 2048;
- stable configurations with CMD trigger, standby, or sleep asserted.

M1 enforces these rules in the simulator. Real supply, VDRV_READY, SPI readback,
fault, and Burst gates belong to the M2 firmware state machine.

## Deterministic simulator

The simulator accepts HELLO, SET_CONFIG, GET_CONFIG, and CAPTURE_ONCE. A valid
single-capture request returns ACK followed by CAPTURE_DATA with exactly 2048
uint16 little-endian samples. Its fixed sequence is
`sample[i] = (37*i + 211) & 0x0FFF`.

Repeating the identical type, sequence, and payload returns the cached response
byte-for-byte and does not create a second simulated capture. The simulator is
a protocol test double only; its waveform has no physical or electrochemical
meaning.
