# M6 host 3.0 and Jetson first-version verification

## Document overview

This document is the closure summary for M6 of the TUSS4470 ultrasonic
acquisition submodule. It answers whether the host 3.0 increment and the same
software/firmware stack have passed the real Jetson G3J gate. Detailed capture
identities and intermediate evidence remain in `jetson-validation.md`; the
controlled roadmap remains authoritative for scope and milestone state.

## Status

**Closed — 2026-09-09.** All M6 functional, cross-platform, real-hardware, and
final regression checks are complete. The prescribed
`milestone(M6): complete host 3.0 and Jetson first version` commit is
`9559ea7819489f5adc636202bcf3656996d25e6e`; it reached `origin/main` with
matching local/remote SHA values. Jetson main was synchronized, its running
containers were recreated from the formal main path with the stable USB
identity, and both completed M6 worktrees were removed.

## Host 3.0 increment

- Web/API starts without the device and reports readable primary health and
  secondary activity instead of a bare state number.
- Parameter Bank contains device and waveform parameters; one acquisition panel
  selects single, periodic, or single-field sweep mode.
- `SAVE_ALL`, `SAVE_LAST`, and `SAVE_NONE` share one Web/CLI/REST contract and
  close acquired/saved/policy-discarded counts without misreporting transient
  data as archived.
- Chinese/English operator text switches in the upper-right corner without
  changing protocol values, database content, parameter identifiers, or raw
  samples.
- No M6 host increment changed MSP430 acquisition timing, ADC/DMA behavior,
  Burst generation, or the USAC v1 wire frame.

## Jetson G3J evidence

- The project environment and image run natively on JetPack 7.2.1 / Jetson
  Linux 39.2.1 / ARM64 using the same source, lock file, protocol, schema,
  migrations, and firmware `0.2.0.2` as Windows.
- Core and bridge use separate containers and bind mounts at
  `/var/lib/tuss4470/core` and `/var/lib/tuss4470/bridge/spool`; runtime data
  does not enter the source worktree.
- Prebuilt images started with only an internal Docker network, then enumerated
  the real device, read identity, applied the D10x4 profile, and completed SPI
  readback without external network access.
- Nine safe non-default device field groups applied/read back; nine legal but
  unsafe current-profile fields were saved as drafts and rejected before
  hardware side effects.
- Real captures covered sample ticks 120/960, Burst ticks 24/50/800, Pulse
  1/2/63, IO_MODE 0 through 3, Master and Slave synchronization, empty/ambiguous
  event reporting, and a two-value single-field sweep.
- Finite periodic completion, explicit STOP, and firmware lease-expiry shutdown
  returned the device to idle with no active schedule.
- The real save-policy matrix archived all, only the last, or no raw frame as
  requested while bridge pending returned to zero.
- Raw delivery remained exact: every accepted frame contained 2048 unmodified
  `uint16` samples and 4096 sample bytes. The accepted Slave capture
  `fabe00644d8f16a721734d93e174315c` also retained its 4324-byte wire frame and
  full RunPlan in SQLite before core reported success.
- Core/bridge restart preserved both bind mounts and continued acquisition.
  USB ordinal reassignment across a Jetson reboot confirmed that deployment
  must select the `MSP430-USB Example` stable `by-id` identity rather than a
  fixed `/dev/ttyACM*` number.

## Accepted first-version limitations

- Captures retain `TIMING_UNCALIBRATED`; calibrated TOF and IO/event timing need
  external timing instruments and remain M7 work.
- The current transport CRC diagnostic is the fixed residue of an already
  CRC-protected frame and is not a content fingerprint. Native frame CRC
  validation and terminal-decision SHA-256 remain effective; semantic cleanup
  is assigned to M7.
- The M5 10000 ms lease accommodation and non-lossless 5 Hz scheduling result
  remain first-version limitations. Lease scheduling/storage decoupling and
  long unattended operation remain M7.
- The observed stale bridge session after deliberate network/device disruption
  recovered by restarting core. Separating bridge handshake wait from command
  timeout and hardening replacement-session preemption remain M7 reliability
  work; ordinary core/bridge restart and persistence gates passed.

These limitations do not alter hardware safety, raw-sample identity, explicit
save semantics, or the completed bounded M6 checks. They prohibit describing
this milestone as production-ready or suitable for unattended long-term
experiments.

## Closure checklist

- [x] Windows host 3.0 offline regression and operator review.
- [x] Native ARM64 environment, image, and full-suite checkpoint.
- [x] Real device identity, configuration, SPI readback, and safe rejection.
- [x] Single, periodic, STOP, lease, range, synchronization, event, and sweep
      checks on real Jetson hardware.
- [x] Three save policies, SQLite/spool closure, persistence, and raw-data
      identity.
- [x] Offline Compose/private-network operation.
- [x] Final Windows and Jetson regressions: 235 tests passed on each platform;
      the Windows full script also passed every firmware build and static/unit
      gate without flashing.
- [x] `milestone(M6)` integration and push to `origin/main` with matching SHA.
- [x] Jetson main synchronization, formal-main container migration, and
      completed-worktree cleanup.
