# Project development standards

## Document overview

This document defines repository-wide maintenance rules for the TUSS4470
ultrasonic acquisition submodule. It applies to M3 and every later milestone,
as well as maintenance changes to completed milestones. It complements the
controlled design and staged roadmap; it does not replace their technical
requirements.

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
raw local logs or bulky machine-generated evidence that should not be committed.
Archived material is non-normative unless it is restored to an active location
and reviewed again.
