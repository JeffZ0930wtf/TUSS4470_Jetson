# Project development standards

## Document overview

This document defines repository-wide maintenance rules for the TUSS4470
ultrasonic acquisition submodule. It applies to V1 and all later development,
including release maintenance and work that follows the archived milestones.
It complements current release, protocol, deployment, ADR, and implementation
plans; it does not replace their technical requirements.

## V1 maintenance workflow

M0-M6 are complete and their milestone process is historical. Current work
starts from the published V1 contract: read the affected README, protocol,
deployment guide, ADR, release acceptance, and known limitations before
changing behavior. A plan is appropriate for multi-step or high-risk work;
small, bounded documentation or maintenance changes do not require a new plan.

For every change:

1. Start from a clean, current `main` and use an isolated branch/worktree for
   non-trivial work. Preserve unrelated local files and external evidence.
2. State the scope and classify the change as documentation-only, host
   software, firmware/hardware-control, deployment, or release work.
3. Update the current normative document with the implementation. Completed
   plans and investigation notes belong in `docs/archive/`, not the active
   documentation set.
4. Run the checks appropriate to the changed surface, then inspect whitespace,
   links, diff scope, and sensitive literals. A device-to-CLI frame is not
   evidence of Bridge/Core/SQLite success.
5. Integrate without rewriting history, push, verify local/remote SHA equality,
   and synchronize Jetson when the deployed source or instructions changed.

Documentation-only work runs link/layout checks and the relevant host tests;
it does not require a firmware rebuild when no firmware input changed. Host
software changes run targeted tests plus the aggregate platform gate. Firmware
or hardware-control changes additionally require the production build and all
retained firmware checks; flashing or Burst requires the documented physical
power gate and explicit operator authorization. Release work also records the
exact source SHA, artifacts/images, lock inputs, platform evidence, and known
limitations.

## Environment and aggregate gates

Each checkout owns its local environment. On Windows:

```powershell
./scripts/bootstrap-dev.ps1
. ./.venv/Scripts/Activate.ps1
./scripts/check-env.ps1
./scripts/test-all.ps1
```

On Jetson/Linux:

```sh
./scripts/bootstrap-dev.sh
. .venv/bin/activate
./scripts/check-env.sh
./scripts/test-all.sh
```

The Windows gate covers Python, Web, the MSP430 simulator, the pinned TI USB
stack, production firmware, and static safety checks without requiring Docker.
The Jetson gate covers host tests, C protocol vectors, one native ARM64 image
build/runtime check, and one AMD64 OCI cross-build. Neither gate opens a serial
port, flashes firmware, or requests a Burst.

The retained firmware gate owns these current invariants:

- 24 MHz XT2/FLL clocking, runtime clock-fault shutdown, 1 MHz TUSS4470 SPI,
  ordered register readback, reset-safe IO2/NCS, Standby/VDRV Hi-Z, and unsafe
  profile rejection;
- one 4096-byte buffer containing exactly 2048 unmodified `uint16` samples,
  variable sample ticks and pretrigger accounting, TB0.1 ADC triggering,
  TB0CCR2 DMA ownership, exact completion evidence, bounded RAM, and no sample
  synthesis or interpolation;
- protocol framing/CRC/resynchronization, segmented CDC transmission, TX buffer
  ownership, CDC-busy non-advancement, and exclusion of USB DMA;
- finite 1-63 pulse plans, all IO modes, periodic/STOP/lease behavior,
  synchronization and events, reset/session invalidation, and TA1 ownership
  after TI `USB_setup()`.

Diagnostic-only startup, reduced-RAM, software-trigger, and single-word DMA
checks were retired with those non-production paths. Their rationale remains in
the archived V1.0.0 firmware-check migration record.

## Formal documentation

Every new or materially updated formal development document must begin with a
short `Document overview` section (or `文档说明` in Chinese). The section must
state:

- the document's purpose;
- the problem or decision it addresses;
- the module, platform, or milestone to which it applies; and
- its relationship to other authoritative design, roadmap, protocol, ADR, or
  verification documents when that relationship is relevant.

Readers must be able to determine a document's role without reading it in
full. Archived documents must be clearly labelled historical or superseded and
must not be cited as current normative requirements.

## Code comments

First-party core code must explain information that is not obvious from the
statements themselves. Comments or docstrings are required where they clarify:

- a module or external library's responsibility;
- a public function's contract, important inputs and outputs, or side effects;
- hardware register access, pin behavior, clocking, power, or reset ordering;
- wire-protocol framing, validation, bounded parsing, or retry behavior;
- state-machine transitions and safety gates;
- a non-obvious implementation choice, limitation, invariant, or design
  reason.

Do not add comments that merely translate a statement into prose or narrate
obvious control flow. Keep comments synchronized with behavior whenever the
code changes. Vendor sources, generated files, toolchains, and virtual
environments are not modified to satisfy this project rule.

## Maintenance-only changes

Documentation and comment-only maintenance must not include feature work,
protocol expansion, unrelated refactoring, or hardware-control behavior
changes. Run the existing automated suite and relevant static safety checks
after such maintenance. If a firmware build is expected to be behaviorally
identical, compare its executable output with the pre-maintenance baseline and
stop if machine code changes unexpectedly.

## Archive policy

Use `docs/archive/` for small historical documents and reviewable textual
evidence that remain useful for traceability. Use ignored `archive/local/` for
ordinary raw local logs or bulky machine-generated evidence that should not be
committed. Version-release artifacts and hashes belong under the separately
managed `D:/Desktop/TUSS4470_data/release/<version>/` evidence directory.
Git history is the source archive for deleted superseded code and scripts;
do not copy dead code back into the active tree merely as an archive. Archived
material is non-normative unless restored to an active location and reviewed
again.
