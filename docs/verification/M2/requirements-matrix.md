# M2 requirement and evidence matrix

Date: 2026-08-27

This matrix maps the M2 roadmap checklist and G2 hardware gate to evidence.
`Complete` means the requirement is closed for M2. `Partial` means useful
evidence exists but the roadmap's physical acceptance method is not yet
available. A Partial G2 item continues to prohibit the first Burst.

| Roadmap item | Status | Evidence |
|---|---|---|
| Reset-first IO2 safe-high and acquisition timers disabled | Partial | Source/static audit and simulator tests pass; idle IO2 measured 3.3 V. Instrumented reset transient remains unobserved. |
| USB CDC and stable device identity | Complete | COM9 enumerated with USB serial equal to stable 16-byte device ID; repeated HELLO and resets preserved it. |
| Bounded MCU parser, ACK/ERROR and timeout | Complete | Fixed 192-byte payload/256-byte parser storage; malformed length, CRC, resynchronization and timeout tests pass. |
| TUSS4470 SPI, parity, masks, semantic fields, readback and fault reporting | Complete | Shared fixed vectors and schema tests pass; 1 MHz real-hardware identity, full default application/readback, VDRV_READY and fault closure pass. |
| Candidate-image validation and raw/semantic configuration response | Complete | AcquisitionConfigV2 carries timing, profile hash/CRC and register pairs; decode/encode round trips pass; SET_CONFIG validates offline before ordered apply/readback. |
| Explicit transient-state handling | Complete | Trigger/low-power fields are validated separately; all session/failure exits clear commands, set VDRV Hi-Z and finish in Standby. |
| Timing ranges 120..960 and 24..800 ticks | Complete for M2 | Boundary tests pass and real GET_CONFIG reports 120/50 ticks. M2 intentionally does not start acquisition timers. |
| No public raw SPI/register/IO-force API | Complete | Protocol and static audit expose no such command; CAPTURE_ONCE is rejected. |
| Approved power profile, VDRV_READY and fault gates | Complete | Standard topology confirmed; VPWR 7.07 V, VDRV 4.54 V; same-config hardware apply/readback passed. |
| Ordinary and WDT/PUC reset injection | Partial | Ordinary S3 reset changes boot ID and returns IDLE_SAFE after the Standby fix. WDT/PUC injection and physical IO2 trace remain pending. |
| Burst forbidden throughout M2 | Complete | Static audit finds no IO2-low/Burst-timer path; all hardware smoke outputs state `burst_command_sent=false`. |

## G2 first-Burst gate

| Gate evidence | Status | Remaining work |
|---|---|---|
| J2=TX, J3=RX, R12 removed, J1=8 nF, J4=6.8 nF | Partial | Operator confirmed topology; retain a reviewable wiring/jumper photograph before G2 closure. |
| Standard J6/J8 topology and external 7.0 V supply | Complete | VPWR measured 7.07 V. USB-side high-impedance MAIN backfeed is documented in `summary.md`; it is not external 7 V authorization. |
| SPI readback, VDRV_READY, zero driver fault, measured rails | Complete | Real same-byte SET_CONFIG/readback and DC Gate A passed. |
| IO2 safe during power-up, reset and configuration failure | Partial | Static and DC evidence only; acquire a digital trace for all required transitions. |
| Logic analyzer connected before first Pulse=1 Burst | Pending | No logic analyzer or oscilloscope is currently available. |
| M2 Git milestone closure | Pending | Final verification passed; commit/push only after the user decides how to handle the physical Partial/Pending items. |

## Decision boundary

The M2 implementation is functionally ready for review, but G2 is not closed.
No M3 CAPTURE or Burst is authorized until the pending IO2/SCLK/reset traces
and the first-Burst logic-analyzer setup are accepted. Committing the M2 code
does not by itself waive those physical safety gates.
