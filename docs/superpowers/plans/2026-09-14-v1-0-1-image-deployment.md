# V1.0.1 Image Deployment Follow-up

## Document overview

This plan completes the user's request to run the latest version on Jetson.
It supplements the initial V1.0.1 release, which had synchronized source and
Python environments while retaining the earlier runtime image.

**Goal:** Build the released V1.0.1 image, make it the startup default, and
switch the two Jetson services while retaining their existing persistent data.

**Architecture:** Build the ARM64 image from the exact `v1.0.1` archive at
`f52af4455e6247aab7cad50614729c9156ec2897`. Follow-up source changes affect only
host-side image selection, regression checks, and documentation. Preserve the
published tag and the previous image for rollback.

## Constraints

- Keep firmware, protocol, runtime code, data paths, and schema unchanged.
- Do not Apply configuration, request a capture, or flash firmware.
- Check that acquisition is idle before restarting services.
- Before opening the physical Bridge again, obtain the operator's current
  external 7 V/reset confirmation required by `docs/deployment/jetson.md`.
- Keep the existing untracked editor swap file untouched.

## Preparation

- [x] Inspect live services and mounts; observe the device idle.
- [x] Build the released source as `tuss4470-acquisition-core:1.0.1`.
- [x] Verify ARM64, OCI version/revision, pinned dependencies, protocol
  roundtrip, and both command entrypoints in device-free temporary containers.
- [x] Demonstrate that regression assertions reject the old default image.
- [x] Select 1.0.1 in both Compose files and the Jetson launcher; run the
  applicable software checks and review the exact configuration diff.
  All 29 project-layout/launcher tests passed after the three expected
  default-selection failures were demonstrated.

## Publication and deployment procedure

Commit and synchronize the default-selection correction without moving the
existing `v1.0.1` tag. The image provenance remains the released source SHA
above; the newer host-side commit only selects that image.

After the physical confirmation, recheck idle status, snapshot the current
mounts/configuration, recreate Core and Bridge using the new image, and verify
both containers' image identity and the HTTP/device state. Preserve the
database/spool mounts and old image. Record actual completion outside Git under
the V1.0.1 deployment evidence directory; a published tag is not rewritten to
update an operational checklist.
