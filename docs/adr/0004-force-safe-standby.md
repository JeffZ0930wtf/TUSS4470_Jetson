# ADR-0004: Leave TUSS4470 in Standby at the no-Burst safety boundary

Status: Accepted for M2 candidate re-verification

## Context

The original M2 `force_safe` sequence cleared `CMD_TRIGGER`, disabled the
internal VDRV regulator, and left `TOF_CONFIG=0x00`. The requested profile kept
`IO_MODE=3`, so the TUSS4470 remained in Listen mode after the host closed DTR.

During the first S3 reset test, the pre-reset and post-reset HELLO calls used
different boot IDs as required, but the post-reset device state was FAULT.
Read-only DSLite RAM extraction from the already-running image showed:

- `TUSS4470_CONFIG_DRIVER_FAULT` (result 5);
- raw DEVICE_ID `0xB9` and REV_ID `0x02`;
- DEV_STAT `0x0A`, which is `VDRV_READY | DRV_PULSE_FLT`.

TI data sheet ZHCSKL2A Section 7.3.2 defines an IO2 falling edge as both Burst
enable and Burst start in IO_MODE 3. Section 7.3.2.1 defines
`DRV_PULSE_FLT` as a Burst-time stuck-clock diagnostic and states that Standby
or Sleep clears it. Section 7.4 states that Standby shuts down the other analog
blocks while SPI and VDRV-state management remain available.

The observed status therefore proves that leaving Listen + IO_MODE3 armed
across an MCU reset is not an acceptable M2 safety boundary. A static 3.3 V
multimeter reading on IO2 cannot exclude the reset-time transition.

## Decision

`tuss4470_force_safe` performs all three writes, even if an earlier write
fails:

1. `TOF_CONFIG=0x00` to clear command, charging trigger, and low-power bits;
2. `VDRV_CTRL=0x20` to disable the internal VDRV regulator;
3. `TOF_CONFIG=0x40` to leave the TUSS4470 in Standby.

The first error is returned after all safe transitions have been attempted.
All configuration-failure and session-end paths use this function. On the next
MCU initialization, IO2 is made GPIO-high before TUSS4470 configuration exits
Standby and reapplies the requested profile.

## Consequences

- An idle, closed, or failed M2 session does not leave IO_MODE3 armed in Listen.
- The regression suite requires `TOF_CONFIG=0x40` after explicit force-safe,
  driver-fault, and VDRV-timeout paths.
- Existing hardware evidence belongs to the pre-fix ELF and cannot validate
  the new candidate. The new image must be flashed with VPWR off and the
  no-Burst HELLO/config/reset sequence repeated.
- This change reduces the demonstrated reset risk but does not replace the
  independent IO2/SCLK trace required before the first authorized Burst.
