# Pre-V1 documentation and evidence archive

## Document overview

This index maps the completed M0–M6 development records to their archived
locations. These documents preserve design rationale, hardware evidence,
failed experiments, and review history for traceability. They are historical
and non-normative; current operation and release claims are defined by the
root README, active ADRs, protocol, deployment guides, and `docs/release/`.

## Path mapping

| Former location | Archived location | Purpose |
|---|---|---|
| `docs/verification/M0` … `M6` | `verification/M0` … `M6` | Detailed milestone and real-hardware evidence |
| `docs/superpowers/plans/` completed feature plans | `plans/` | Implemented host, review, and waveform work plans |
| `docs/superpowers/specs/` completed feature specs | `specs/` | Implemented review and waveform designs |
| `docs/m3-*-design.md` | `designs/` | Historical capture/diagnostic designs |
| `docs/adr/0007-m3-adc-dma-software-trigger-diagnostic.md` | `adr/` | One-time diagnostic decision |
| `docs/archive/M2` | `prior-archive/M2` | Material already superseded before V1 |

The active V1 consolidation plan remains outside this archive until the
release is complete. Deleted superseded source and scripts remain recoverable
from Git history at the baseline recorded in
`docs/release/v1.0.0-baseline.md`.

## Evidence status

Archiving does not invalidate accepted evidence. In particular,
`verification/M6/summary.md` and `verification/M6/jetson-validation.md` remain
the detailed basis for current Jetson and real-hardware claims. The concise
current view is `docs/release/v1.0.0-acceptance.md`, and all accepted caveats
are carried into `docs/release/v1.0.0-known-limitations.md`.
