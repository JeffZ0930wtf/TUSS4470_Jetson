# ADR-0003: M2 LaunchPad clock and TUSS4470 SPI bring-up

Status: Accepted for M2

## Document overview

This ADR records the verified MSP430 clock and TUSS4470 SPI bring-up choices,
including the 24 MHz clock tree and conservative 1 MHz control link. It applies
to the M2 firmware baseline and supplies hardware rationale used by later
acquisition work; it does not authorize a Burst.

## Decision

- Map MSP430F5529 P5.2/P5.3 to the XT2 peripheral before starting the 4 MHz
  crystal. This follows the initialization order in TI's MSP430 USB stack.
- Generate 24 MHz MCLK/SMCLK from the 4 MHz XT2 FLL reference with VCORE level
  3 and DCORSEL 6. A missing XT2 or DCO fault blocks USB enumeration and leaves
  the reset-safe outputs active.
- Use REFO for ACLK. An XT1 fault is therefore diagnostic but not fatal;
  DCOFFG and XT2OFFG remain fatal.
- Operate the TUSS4470 SPI control link at 1 MHz during M2 and subsequent
  acquisition bring-up: 24 MHz SMCLK divided by 24. Keep MSB-first, CPOL 0,
  CPHA 1 (MSP430 UCCKPL=0 and UCCKPH=0).
- Never correct an apparent SPI bit shift by shifting received register data in
  software. DEVICE_ID and REV_ID must match their complete raw data bytes.

## Evidence and basis

The local controlled copies of the TUSS4470 data sheet and software
development guide specify a 16-bit, MSB-first, odd-parity frame; SDO sampled on
SCLK's falling edge; SDI shifted on its rising edge; and SPI mode 1. The
software guide permits up to 8 MHz.

Hardware bring-up initially produced DEVICE_ID 0x5C and REV_ID 0x01 at 8 MHz,
exact right shifts of the required 0xB9 and 0x02. At 1 MHz, the unmodified raw
bytes passed identity, complete configuration/readback, VDRV_READY, and fault
checks. The lower rate is retained because SPI is not in the ADC sample path
and the extra timing margin has no acquisition-throughput penalty.

The first custom image also proved that XT2 cannot start unless P5.2/P5.3 are
mapped before `UCS_turnOnXT2WithTimeout`. After matching TI's USB stack order,
the application CDC enumerated with the derived 32-character serial number.

## Consequences

- M2 and M3 use a stable 1 MHz SPI control bus; any future rate increase needs
  logic-analyzer evidence and a separate review.
- The 200 kS/s ADC timing remains derived independently from the 24 MHz SMCLK
  and is unaffected by this SPI decision.
- All clock and SPI failures remain fail-closed with IO2 high and Burst
  unavailable.
