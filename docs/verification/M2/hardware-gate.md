# M2 physical hardware gate (no Burst)

This procedure is limited to the M2 no-Burst image. It must not be used with
an image whose identity and SHA-256 have not been checked against the M2 build
evidence. Do not send `CAPTURE_ONCE`, start a periodic task, or manually drive
IO2 low.

## Official board references

- TI *TUSS44x0 EVM for Ultrasonic Sensors User's Guide*, SLAU822A, Table 1
  (page 6): Standard mode uses J6 3-4, leaves J6 1-2 and 5-6 open, keeps both
  J8 shunts fitted, powers the LaunchPad from USB, and powers MAIN/VPWR from
  J5 or J6 pin 6.
- SLAU822A, Figure 23 (page 27): BOOSTXL-TUSS4470 schematic and signal names.
- SLAU822A, Figure 24 (page 34): top-side positions labelled `SCLK`, `IO2`,
  `VDRV`, `MAIN`, and `GND`.
- SLAU822A, Table 9 (page 33): TP1 through TP10 have fitted quantity zero.
  The labelled plated holes may therefore be present without test-point
  hardware.

## Preconditions

1. M2 no-Burst firmware is already flashed and verified while external VPWR
   was off.
2. J6 has only the 3-4 shunt fitted; both J8 shunts are fitted.
3. The external supply is set to 7.0 V with a conservative current limit and
   correct polarity: positive to red J5 `MAIN`, negative to black J7 `GND`.
4. USB is connected to the LaunchPad, the external supply is on, and S3 `RST`
   has been pressed once after VPWR became stable.
5. The meter is in DC-voltage mode. Do not use resistance or current mode on
   the powered board. Insulate probe shanks so only the tip is exposed.

## Gate A: DC rail measurements

Keep the black meter probe on black J7 `GND` for both measurements.

1. Touch the red probe to red J5 `MAIN`; record this as `VPWR_measured_V`.
2. Touch the red probe to the top-side plated hole labelled `VDRV`, at the
   lower-right edge in TI Figure 24; record this as `VDRV_measured_V`.
3. Stop immediately if either probe can bridge adjacent conductors, VPWR is
   outside the intended 7.0 V setting, VDRV is not close to the configured
   5 V level, a fault LED appears, current rises unexpectedly, or a component
   becomes hot.

For the M2 profile, `VDRV_VOLTAGE_LEVEL=0x0`. TI TUSS4470 data sheet
ZHCSKL2A, Section 6.5, specifies 4.5 V minimum, 5.0 V typical, and 5.3 V
maximum when VPWR has the required headroom. Use that guaranteed interval as
the DC acceptance range; retain the actual measured value in the evidence.

Do not infer the physical voltage solely from the configured register or
`VDRV_READY`. M2 requires both the status check and an external measurement.

## Gate B: no-Burst digital trace

Use a logic analyzer or oscilloscope with a common ground connected to J7
`GND`. Observe these top-side labelled plated holes from TI Figure 24:

- channel 1: `IO2`;
- channel 2: `SCLK`.

Use at least 10 MS/s for the 1 MHz SPI trace. Capture each of the following:

1. external-power application;
2. S3 reset;
3. one authorized HELLO plus GET_CONFIG session;
4. one authorized same-byte SET_CONFIG session;
5. a controlled configuration failure that does not require altering the
   approved hardware topology.

Acceptance criteria:

- IO2 stays at the safe high level throughout every trace and has no low
  pulse;
- SCLK is low while idle;
- active SCLK is approximately 1 MHz during TUSS4470 register traffic;
- no Burst waveform occurs on IO2.

If no suitable instrument is available, record Gate B as pending. A static
multimeter reading on IO2 is useful as a preliminary check but cannot prove
absence of short reset-time pulses and does not close this gate.

## Gate C: reset-session behavior

With IO2 still observed, press S3 once during an idle authenticated session.
The device must return to safe output state, detach and re-enumerate USB, and
require a new DTR/HELLO session. Record the pre-reset and post-reset `boot_id`;
they must differ. No CAPTURE or Burst command is permitted in this gate.

## Evidence record

Record the instrument model, probe points, supply current limit, measured
VPWR/VDRV, trace sample rate, trace filenames, device ID, both boot IDs, the
firmware version, and the M2 ELF SHA-256 in `summary.md`. Raw trace files are
laboratory evidence and must remain outside Git if they are large or binary.
