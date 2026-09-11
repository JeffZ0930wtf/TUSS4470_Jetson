# M2 requirement and evidence matrix

Date: 2026-08-27

## Document overview

This matrix maps the accepted M2 no-Burst scope to available evidence. It
separates completed M2 requirements from measurements deferred to a future
transmission milestone. A deferred item is not presented as measured or
passed, and M2 closure does not authorize M3 CAPTURE or Burst.

| Roadmap item | Status | Evidence |
|---|---|---|
| Reset-first IO2 safe-high and acquisition timers disabled | Accepted for M2 | Source/static audit and simulator tests pass; idle IO2 measured 3.3 V. Instrumented reset transients remain deferred and unclaimed. |
| USB CDC and stable device identity | Complete | COM9 enumerated with USB serial equal to stable 16-byte device ID; repeated HELLO and resets preserved it. |
| Bounded MCU parser, ACK/ERROR and timeout | Complete | Fixed 192-byte payload/256-byte parser storage; malformed length, CRC, resynchronization and timeout tests pass. |
| TUSS4470 SPI, parity, masks, semantic fields, readback and fault reporting | Complete | Shared fixed vectors and schema tests pass; 1 MHz real-hardware identity, full default application/readback, VDRV_READY and fault closure pass. |
| Candidate-image validation and raw/semantic configuration response | Complete | AcquisitionConfigV2 carries timing, profile hash/CRC and register pairs; decode/encode round trips pass; SET_CONFIG validates offline before ordered apply/readback. |
| Explicit transient-state handling | Complete | Trigger/low-power fields are validated separately; all session/failure exits clear commands, set VDRV Hi-Z and finish in Standby. |
| Timing ranges 120..960 and 24..800 ticks | Complete for M2 | Boundary tests pass and real GET_CONFIG reports 120/50 ticks. M2 intentionally does not start acquisition timers. |
| No public raw SPI/register/IO-force API | Complete | Protocol and static audit expose no such command; CAPTURE_ONCE is rejected. |
| Approved power profile, VDRV_READY and fault gates | Complete | Standard topology confirmed; VPWR 7.07 V, VDRV 4.54 V; same-config hardware apply/readback passed. |
| Ordinary reset recovery | Complete | S3 reset changes boot ID and returns IDLE_SAFE after the Standby fix. |
| WDT/PUC dynamic IO2 trace | Deferred | No external timing instrument is available; this is not claimed as M2 evidence and does not block the accepted no-Burst scope. |
| Burst forbidden throughout M2 | Complete | Static audit finds no IO2-low/Burst-timer path; all hardware smoke outputs state `burst_command_sent=false`. |

## Deferred first-transmission evidence

| Gate evidence | Status | Remaining work |
|---|---|---|
| J2=TX, J3=RX, R12 removed, J1=8 nF, J4=6.8 nF | Recorded | Operator confirmed the topology; a later transmission gate may request a reviewable photograph. |
| Standard J6/J8 topology and external 7.0 V supply | Complete | VPWR measured 7.07 V. USB-side high-impedance MAIN backfeed is documented in `summary.md`; it is not external 7 V authorization. |
| SPI readback, VDRV_READY, zero driver fault, measured rails | Complete | Real same-byte SET_CONFIG/readback and DC Gate A passed. |
| Dynamic IO2 behavior during power-up, reset, and failure | Deferred | Static and DC evidence only; an external digital trace may be added by a future timing-calibration activity. |
| First Pulse=1 Burst safety gate | Not started | M3 is explicitly outside the current work and no transmission is authorized. |
| M2 Git milestone closure | In progress | Final software verification and repository normalization precede the required milestone commit and push. |

## Decision boundary

M2 is accepted as the completed no-Burst baseline. Deferred dynamic timing
items remain explicitly unverified. M3 has not started, and this decision does
not authorize CAPTURE, Burst, protocol expansion, or hardware-control changes.
