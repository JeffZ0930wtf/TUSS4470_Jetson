# ADR-0005: Separate valid configuration from active hardware profile

Status: Accepted for M2 final candidate

## Document overview

This ADR separates a reportable verified configuration from a register profile
that is currently active in hardware. It solves an M2 cross-session state bug
and defines an invariant that later milestones must preserve when they add
acquisition states.

## Context

M2 ends every clean DTR session by clearing trigger state, disabling the
internal VDRV regulator, and placing TUSS4470 in Standby. The last verified
configuration must remain available to GET_CONFIG and optimistic concurrency
in a later connection, but its operational register image is no longer fully
active while the device is in Standby.

Using one `config_applied` flag for both meanings caused two failures. Clearing
it made the documented multi-connection smoke sequence fail with
`INVALID_STATE(5)`. Keeping it set would invite M3 to treat a Standby device as
ready for acquisition.

## Decision

The application tracks two explicit facts:

- `config_valid`: the last configuration passed validation, SPI application,
  and readback, and its snapshot/hash may be returned by GET_CONFIG;
- `profile_active`: the requested operational register state is currently
  active in hardware.

Initialization after a successful TUSS4470 configuration and successful
SET_CONFIG set both flags. Clean session end preserves `config_valid` and
clears `profile_active` after entering Standby. Failed application or failed
safe transition clears both and enters FAULT where applicable.

M2 does not expose a capture path. M3 must not authorize Burst from
`config_valid` alone; it must explicitly reactivate and verify the profile and
then evaluate all G2 power, status, and human-authorization gates.

## Verification

The change was developed red-green. The new simulator assertions failed to
compile before the state split, then the complete firmware unit suite passed.
The final no-Burst ELF SHA-256 is
`10d8fe3f78432d1ab9dc96b8553c7fc93ef560ad8410e2c73bbc07841f983d6a`.
On real hardware, one independent HELLO/GET_CONFIG connection followed by a
second HELLO/GET_CONFIG/exact-byte SET_CONFIG connection returned IDLE_SAFE,
the same configuration hash/CRC, and `burst_command_sent=false`.
