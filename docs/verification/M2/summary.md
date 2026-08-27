# M2 verification summary

Status: Hardware verification in progress

Date: 2026-08-27

## Scope

M2 configures and verifies USB CDC, the bounded device protocol, MSP430 reset
safety, TUSS4470 SPI/register state, and the approved internal-VDRV profile.
It intentionally has no usable Burst or capture path.

## Automated verification

- Fresh final-candidate full-suite rerun on 2026-08-27: exit code 0.
- Python protocol/runtime suite: 64 tests passed in 0.19 s.
- MSP430 simulator unit suite: passed through the explicit GDB completion
  breakpoint and result variable.
- TI MSP430 USB Developer's Package C4 CDC smoke build: passed.
- Full M2 ELF: linked successfully with project sources warning-clean.
- Static safety audit: passed; IO2 has no low-going write, TA2 remains stopped,
  CAPTURE_ONCE returns INVALID_STATE, and SPI is fixed at 1 MHz.
- Final-candidate image measurement: 16366 B text, 98 B data,
  818 B BSS; 916 B static RAM including initialized data.
- SHA-256 of the pre-fix ELF used for hardware evidence through the first S3
  reset test:
  `363adb63bfa86b9e08c761f5d12ff0e1c5271fefd3a57fbb456f3d2627a9de35`.
- SHA-256 of the first reset-safety candidate:
  `aed872b71e359944191474e109cc6d1faf0685de374f0fa425e0653323e5031e`.
- SHA-256 of the intermediate clean-session correction:
  `74684db4084fc52ecab2efee9b5f6ed6794c84192bd60f860f0d689ec0e68be5`.
- SHA-256 of the final candidate flashed and verified after separating the
  valid configuration snapshot from the active hardware profile:
  `10d8fe3f78432d1ab9dc96b8553c7fc93ef560ad8410e2c73bbc07841f983d6a`.

## Real hardware evidence completed

- Board: MSP-EXP430F5529LP plus BOOSTXL-TUSS4470.
- Controlled topology reported by operator: J6 only 3-4 fitted, J8 fitted,
  external VPWR set to 7.0 V with current limit approximately 0.10 A, J2=TX,
  J3=RX, R12 removed, J1=8 nF, and J4=6.8 nF.
- TI DSLite erased, programmed, and verified the fixed
  `usac-m2-no-burst.elf`; external VPWR was off during flashing.
- Application CDC enumerated as COM9 with USB serial/device ID
  `c5fa4769c16da8710b8688c70ba34cf7`.
- USB-only HELLO succeeded with `burst_command_sent=false`; state FAULT was
  expected because TUSS4470 was unpowered.
- With external 7.0 V stable and after S3 RST, HELLO plus GET_CONFIG succeeded
  in IDLE_SAFE. Profile SHA-256 was
  `b8826eaf278d7360189d49aced322ff9e404d8266a25e76a011065c2fda5c998`;
  device config CRC32 was `5d4fc286`; sample interval was 120 ticks and Burst
  period was 50 ticks.
- In a separately authorized session, the host read that configuration and
  sent the exact same bytes with SET_CONFIG. The device ACKed only after SPI
  application/readback. No CAPTURE or Burst command was sent.
- The final candidate was then flashed and TI DSLite verified the exact image
  whose SHA-256 is `10d8fe3f...f983d6a`. With external 7 V disconnected,
  HELLO-only returned the stable device ID and expected FAULT state because
  the TUSS4470 power/configuration gate could not complete; its boot ID was
  `98bc45adfb4258ea2035fab19eecb36c`. After 7 V was restored and S3 was
  pressed, a first independent session returned IDLE_SAFE, boot ID
  `78020bdc14c5e53763004d57ee6c8d96`, and the same profile
  hash and configuration CRC32. A second independent DTR session then
  completed GET_CONFIG followed by exact-byte SET_CONFIG and SPI readback,
  returning IDLE_SAFE with boot ID `be5adfc1c2adb32d96da6ea381f8fd45`.
  Both calls reported `burst_command_sent=false`. This closes the reproduced
  cross-session `ERROR 5` defect on real hardware.
- Raw identity at the retained 1 MHz SPI rate passed DEVICE_ID 0xB9 and REV_ID
  0x02 checks, followed by VDRV_READY and zero masked driver faults.
- Operator DC measurements with the powered M2 profile were VPWR = 7.07 V and
  VDRV = 4.54 V. The latter is inside the 4.5 V to 5.3 V guaranteed interval
  for `VDRV_VOLTAGE_LEVEL=0x0` in TUSS4470 data sheet ZHCSKL2A, Section 6.5,
  although it is close to the lower limit. DC rail Gate A therefore passed.
- No logic analyzer or oscilloscope was available on 2026-08-26. Gate B is
  explicitly pending; no claim is made about reset-time IO2 transients or an
  independently measured SCLK rate.
- With the device idle, the operator measured IO2 = 3.3 V and SCLK = 0 V
  relative to J7/GND. These readings pass the preliminary static-level check:
  IO2 is safe-high and SCLK is idle-low. A multimeter cannot exclude short
  transients or establish the active SPI clock rate, so Gate B remains pending.
- The ordinary S3 reset session test recorded pre-reset boot ID
  `c3aabca8786d544e7ea1d232068674c5` and post-reset boot ID
  `c5240bb513f3c4b34c147e6c2704d993`; the stable device ID remained
  `c5fa4769c16da8710b8688c70ba34cf7`. Both host calls were HELLO-only and
  reported `burst_command_sent=false`. This proves a new logical boot session,
  but the post-reset HELLO reported device state 7 (FAULT), not IDLE_SAFE.
  Reset recovery was not accepted and triggered the diagnosis below.
- Read-only DSLite RAM extraction from the faulted pre-fix image found
  configuration result 5 (`TUSS4470_CONFIG_DRIVER_FAULT`), raw DEVICE_ID
  `0xB9`, REV_ID `0x02`, and DEV_STAT `0x0A`. The status is
  `VDRV_READY | DRV_PULSE_FLT`, proving that the TUSS4470 recognized a Burst
  start followed by a stuck drive clock while the MCU was being reset.

## Reset-safety correction and hardware re-verification

ADR-0004 changes `tuss4470_force_safe` to finish in Standby
(`TOF_CONFIG=0x40`) after clearing triggers and putting VDRV in Hi-Z. TI states
that Standby clears `DRV_PULSE_FLT` and disables the non-standby analog blocks.
The change was developed red-green: the old implementation failed the new
Standby assertion at source line 228; the minimal correction and all related
failure-path assertions then passed the complete suite. With external VPWR
confirmed off, TI DSLite 8 erased, programmed, and verified this exact
post-fix candidate on 2026-08-27. After external 7.0 V was restored and S3 was
pressed, HELLO plus GET_CONFIG returned IDLE_SAFE, stable device ID, profile
SHA-256 `b8826eaf278d7360189d49aced322ff9e404d8266a25e76a011065c2fda5c998`,
configuration CRC32 `5d4fc286`, sample interval 120 ticks, and Burst period
50 ticks. The pre-reset boot ID for the corrected reset test is
`dd1bef08c4309152376cdab8ce2b6d08`. The call reported
`burst_command_sent=false`. After S3 reset, HELLO-only returned post-reset boot
ID `055d4b8366213c2c0e875fccc5e1a92a`, the same stable device ID, and
IDLE_SAFE state 6. This confirms that the corrected image no longer enters the
previous `DRV_PULSE_FLT` reset failure. The final candidate retains the same
Standby safety sequence and passed the powered post-flash S3/GET_CONFIG check
described above.

## USB-side MAIN backfeed observation

With the external 7 V source physically disconnected, the operator measured
approximately 2.18 V at red J5 MAIN immediately after USB was connected. When
USB was removed, the voltage decayed progressively more slowly toward zero.
SLAU822A Table 1 and Figure 23 show that Standard mode keeps both J8 shunts
fitted, coupling the LaunchPad 3.3 V rail and MAIN through the TPS7B6933 LDO
network. The observed USB-correlated rise and capacitor-like decay are
therefore recorded as a high-impedance USB-side backfeed/residual-charge
condition, not as an enabled external 7 V source. The external supply remained
physically disconnected during programming. Do not treat J5 as isolated or
short it for discharge while USB is connected.

## Bring-up defects found and corrected

1. TI DSLite 8 could not parse the Chinese installation path. The controlled
   script now uses an ASCII NTFS junction under ignored `.tools` and verifies
   the fixed image after programming.
2. XT2 startup initially failed because P5.2/P5.3 were not mapped to the
   peripheral before oscillator start. The order now matches TI's USB stack.
3. Global OFIFG included unused XT1. The gate now ignores only XT1 while still
   rejecting DCO and XT2 faults; ACLK explicitly uses REFO.
4. At the 8 MHz maximum, raw identity bytes appeared shifted. No data was
   repaired in software. The SPI control link was reduced to 1 MHz, where the
   complete raw identity and configuration closure passed.
5. A clean DTR close correctly entered Standby but also cleared the flag that
   made the last verified configuration reportable. Consequently a later
   independent HELLO succeeded while GET_CONFIG returned `INVALID_STATE(5)`.
   A red-green regression now requires a clean session end to preserve the
   verified configuration snapshot; only a failed safe transition invalidates
   it and enters FAULT. The final image passed the previously failing two-
   connection sequence on real hardware.
6. The original state name `config_applied` became unsafe after the clean-
   session correction because Standby intentionally changes transient device
   registers. ADR-0005 separates `config_valid` (the last verified snapshot is
   reportable and usable for optimistic concurrency) from `profile_active`
   (the requested operational register state is currently active). Clean
   session end preserves the former and clears the latter; SET_CONFIG success
   sets both; any failed apply or failed safe transition clears both.

## Remaining physical evidence before M2 milestone commit

The controlled procedure and exact official-board references are recorded in
`hardware-gate.md`.

- Observe IO2 with a logic analyzer or oscilloscope during power-up, S3 reset,
  successful configuration, and a forced configuration failure; it must never
  go low in M2.
- Record the analyzer trace showing SCLK idle-low and the 1 MHz SPI transfer;
  no IO2 Burst edges may occur.
- Ordinary S3 reset and new boot-session behavior have passed functionally.
  Inject WDT/PUC reset and confirm reset-safe IO2 when a logic analyzer or
  oscilloscope is available.
- Rerun the complete Windows suite after the final evidence/document update.
- Commit with `milestone(M2): complete safe firmware configuration`, push to
  `origin/main`, verify local/remote SHA equality, and require a clean tree.

Until these items are complete, M2 is not declared complete and M3 Burst is
not authorized.
