# Invalid-face material drop crash

On 2026-10-03 the development viewer stopped with
`LLViewerObject::getTEImage: Requested Image from invalid face: 255/8`.
The private crash dump was symbolized against the matching build PDB. Its stack
ran from the native mouse-up handler through `dad3dMaterialObject`,
`dad3dApplyToObject`, `is_water_exclusion_surface`, `is_water_exclusion_face`
and `getTEImage`. The apply function received face `-1`, the no-face pick
sentinel. Passing it to a texture accessor taking `U8` converted it to `255`.
The object had eight texture entries. No MCP capture or dispatch handler
appeared in that stack. This identifies this crash; it does not establish that
every future crash has the same cause.

The affected drag/drop source was unchanged from the pinned upstream baseline
`10bd3c9f930c76e1427ddd4ecece6cdf36b4406d`. The fix belongs to general viewer
surface editing, with no consumer-specific behavior.

## Fix

Single-face texture/material drops reject negative, out-of-range or missing
texture entries before any texture/PBR read or application. The water-exclusion
helpers have the same defensive check. The drop entrypoints also recheck the
face when invoked by a delayed confirmation, so a changed face count cannot
reuse an out-of-range index. Null/dead objects and zero-face surfaces are rejected.
This is range validation, not a redesign of the existing callbacks' object lifetime.

Shift-to-apply-to-all still ignores the pick sentinel and enumerates actual
faces. Ctrl inventory delivery remains before surface validation, and mesh drops
are outside the new face requirement. Invalid picks do not substitute face zero
or all faces. The fatal invariant in `getTEImage` is unchanged.

## Reproduce the source/build

Apply after the desired viewer extensions and before compilation, in the
separate source checkout only:

```powershell
python scripts/apply_drop_guard.py C:/src/firestorm --dry-run
python scripts/apply_drop_guard.py C:/src/firestorm
```

The installer verifies the entire normalized drag/drop source hash and every
anchor before writing. It refuses reapplication or unknown upstream changes.
The shared header needs no additional compilation unit. Inspect the source diff,
then use the [development build and staging procedure](CUSTOM_VIEWER.md).
Preserve the old portable installation; stage into a new directory. Reapply the
machine-local LEAP startup configuration separately and retain the existing
private journal when switching builds.

## Validation

- The actual shared C++ guard passed a standalone compiled regression with
  assertions and compiler warnings treated as errors. Cases include `-1`, `255`,
  both integer extremes, face-count boundaries, valid faces 0/7 of 8, Shift's
  sentinel, a changed face count, missing entries, null/dead objects and no faces.
  Invalid indices never reach the synthetic narrowing accessor.
- Four isolated installer tests cover placement after Ctrl delivery and before
  texture access, the two mutation entrypoints, dry run, repeat application and
  refusal of unknown source/anchors. These are source-wiring checks, not live
  modifier-key acceptance.
- The Windows x64 Release development viewer compiled successfully.
- All 230 isolated Python tests and the fresh offline wheel check passed. A
  separate portable viewer is staged with machine-local MCP autostart settings;
  the previous installation was preserved. The corrected executable has not yet
  been launched. See [build provenance](../viewer-extension/drop-guard-build.json).
- Live in-world drag/drop acceptance is **pending**. No material, texture,
  inventory or world mutation was performed to reproduce the user's crash.

Run the regression from a VS developer environment (or with a C++17 compiler):

```powershell
python scripts/verify_native_drop_guard.py
python -m pytest -q tests/test_drop_guard.py
```

For manual acceptance use a disposable owned copy: repeat the original material
drop, verify a valid single-face material/texture drop, Shift all-face behavior,
Ctrl contents delivery and a pick that has no face. Inspect the resulting faces
and simulator state; a surviving viewer alone does not prove a successful edit.
Paid/no-copy items are unnecessary for this check.

Raw logs, dumps, private paths and captures stay outside the tracked repository.
