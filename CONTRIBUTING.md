# Project development standards

## Document overview

This document defines repository-wide maintenance rules for the TUSS4470
ultrasonic acquisition submodule. It applies to V1 and all later development,
including release maintenance and work that follows the archived milestones.
It complements current release, protocol, deployment, ADR, and implementation
plans; it does not replace their technical requirements.

## Milestone workflow

Every development milestone or release starts from and closes against its
controlled roadmap or implementation plan. A task plan or ADR may refine how
a requirement is met, but it must not silently remove, weaken, or mark a
requirement complete.

Before milestone implementation:

1. Read the roadmap's global constraints, current milestone, exit gate, and
   adjacent milestone boundaries.
2. Require the preceding `milestone(Mx)` commit to be present on `origin/main`,
   with local and remote SHA equal and a clean main worktree.
3. Mark the new milestone `in progress` in the roadmap and confirm its task
   checklist, exclusions, hardware conditions, and evidence plan before code.
4. Create the milestone branch/worktree from the verified main commit.

Before milestone closure:

1. Audit every roadmap item. Use `[x]` only with code, test, or hardware
   evidence. Leave incomplete items `[ ]` and record the reason, impact,
   destination milestone, or the user's explicit decision to accept a
   non-blocking limitation.
2. Update the roadmap status, README, milestone verification summary, and
   relevant ADRs. Never describe a device-to-CLI frame as bridge/core/SQLite
   success.
3. Run the full milestone verification, whitespace/diff checks, staged-scope
   review, and sensitive-literal check.
4. Integrate to `main`, create the exact non-empty `milestone(Mx)` commit named
   by the roadmap, push `main` without rewriting history, and verify the local
   and remote 40-character SHA values are identical.
5. Sync the Jetson repository to the closed main commit, verify a clean
   worktree, then archive/remove the completed milestone worktree according to
   ownership rules.

Only after all closure steps pass may the next milestone be marked ready. Its
implementation still begins with a fresh execution of the start procedure.

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
