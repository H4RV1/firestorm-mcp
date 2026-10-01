# Local range and timing trainer

The optional native `FSMCPTraining` extension adds **Developer > Training** to
a separate development viewer. It draws a configurable, depth-tested sensor
sector around the local avatar and a cross at a locally selected target's
position. Its controls display range, angle, cooldown and the last attempted
action. It never moves an avatar, plays gestures, sends chat or applies damage.

This is a manual rehearsal and observation tool. It is not a combat bot, a
simulator hitbox display, or a source of confirmed hits. Product-specific rules,
gesture identifiers, accounts and training records belong outside this repo.

## Manual operation

1. Open **Developer > Training > Range and timing controls...**.
2. Enable **Show local training overlay**. The feature starts off each launch.
3. Set the range, half-angle and cooldown to match the external combat system.
   The supplied example is 2 meters, 90 degrees half-angle and 2 seconds. Those
   are editable demonstration values, not universal Second Life combat rules.
4. Use **Select nearest locally** to lock the nearest loaded same-region avatar.
   Selection considers 3D distance, excludes self and animesh control avatars,
   and does not restrict the search to the hit sector. Moving closer to another
   avatar does not switch the target. Selecting again does not reset cooldown.
5. Use **Rehearse attack (local only)** to sample current geometry and timing.
   There is no swing windup. An attempt made while ready starts the configured
   cooldown even if it misses. An input during cooldown is classified too early
   and does not extend the running deadline. This distinction is local rehearsal
   behavior and must be matched against the actual weapon before bot use.
6. Optionally select the active target and attack gestures from the dropdowns.
   Labels include their shortcut. **Refresh** reloads the active gesture list.
   Play them normally: the extension observes their start, then normal viewer
   gesture processing continues unchanged. The panel never plays them itself.

Green means local geometry is eligible and the local timer is ready; amber means
cooldown; red means outside range/angle; gray means unknown geometry. Text gives
the same information without depending on color. Geometry uses avatar position
points, not animated limbs or rendered mesh surfaces. The outer sector boundary
is a sphere of the configured radius, not a flat cone cap. The angle is measured
from agent forward, or camera forward in mouselook, and includes vertical angle.
Range is full 3D distance and includes the exact configured boundary.

For key-based binding without selecting inventory IDs, the optional debug
settings `FSMCPTrainingTargetShortcut` and `FSMCPTrainingAttackShortcut` accept
unmodified gesture keys such as `T` and `F12`. They are blank by default. An
explicit dropdown gesture ID takes priority. These observe an active gesture
actually played by Firestorm; they do not intercept raw keys or replace keybinds.
If a combat HUD handles an input without playing a gesture, it needs a different
adapter. Conflicting target/attack bindings produce an error instead of an
ambiguous action. Selecting no explicit gesture leaves shortcut fallback active.

Turning the overlay off or changing region/account clears the local target,
timer and last sample. It does not reset a combat system's target or cooldown.
If the selected avatar unloads, geometry becomes unknown; the extension never
silently acquires a replacement. Re-enabling mid-combat can therefore leave the
local timer out of sync until a subsequent known attack establishes timing.

## Native API, version 1

After runtime capability discovery, `viewer_call` can access `FSMCPTraining`:

| Operation | Arguments | Effect |
| --- | --- | --- |
| `getState` | `reply` | Read current local prediction. |
| `acquireNearest` | `reply` | Set the local training target only. |
| `recordAttempt` | `reply` | Sample geometry and advance the local rehearsal timer if ready. |

All replies contain `schema_version: 1`, `evidence: local_viewer_prediction`,
`simulator_hit_verified: false` and `target_selection_verified: false`. The last
flag means that nearest selection has not been reconciled with the combat HUD's
selection result. MCP live use still requires a bounded control lease.

`distance_m`, `angle_degrees`, `in_range`, `in_front`, `range_margin_m` and
`predicted_eligible` are undefined when geometry cannot be established. Do not
interpret undefined as zero or false. Other observations include positions in
viewer agent coordinates, current velocity vectors in meters per second,
forward direction, cooldown remaining, and a `last_attempt_sample` containing
the target, distance, angle, configured range/angle and pre-attempt cooldown.
`sample_local_time_seconds` is the viewer's local clock; it is not simulator
time. `simulator_sample_age_seconds` remains undefined because this extension
does not establish packet age or server sample freshness. Positions are not
region/global coordinates and their origin can change.

These observations can support a later controller, but no movement/attack
automation is included. Accurate pursuit, turns and evasion require calibration
against simulator movement and actual attack outcomes. A perfect local timer
cannot remove network latency, simulator scheduling, interpolation, packet loss
or gesture steps that delay the actual combat action. This hook observes gesture
start, not delivery of a particular chat/animation step within a gesture.

## Build separately

Read [CUSTOM_VIEWER.md](CUSTOM_VIEWER.md). Apply to an explicit source checkout
at the pinned Firestorm 7.2.4 revision. The builder hook is optional for the
training patch; its source anchors also allow the existing builder extension.

```powershell
python scripts/apply_training_extension.py D:/FirestormMCP-build/viewer --dry-run
python scripts/apply_training_extension.py D:/FirestormMCP-build/viewer
```

The installer preflights every anchor and destination before writing, refuses
reapplication, and sets a distinct `FirestormMCPTraining` settings/cache profile.
Configure with `--chan MCP-Training-Development`, compile using the existing
isolated viewer build environment, and stage into a new portable directory:

```powershell
python scripts/stage_custom_viewer.py --checkout D:/FirestormMCP-build/viewer --destination D:/FirestormMCP-build/portable-training
```

Never overwrite an installed viewer. Keep the normal installation and profiles.
The source archive includes the XUI file; the Python wheel remains an external
MCP server and cannot add these native features to stock Firestorm.

## Verification and acceptance

The [Windows build record](../viewer-extension/training-build-baseline.json)
records successful compilation with zero warnings/errors and a separate portable
staging. The offline suite passed 172 tests; the compiler-discovery test skipped
on Windows, and its C++ model test passed separately under MSVC. The fresh wheel
check passed without network or viewer access. Startup, rendered overlay and
in-world targeting/hit accuracy have **not** been verified. These distinctions
are intentional; successful compilation is not live acceptance.

Run the synthetic installer tests with a temporary `FIRESTORM_MCP_HOME`:
`python -m pytest tests/test_training_extension.py tests/test_viewer_extension.py`.
Compile/run `tests/native_training_model.cpp` with C++17 and assertions enabled
to check distance/angle boundaries, unknown inputs, height, cooldown misses and
early input. These tests never launch or contact a viewer.

Native compilation and manual live acceptance are separate. Before relying on
this for training, use an authorized partner or synthetic fixture and verify:

- Panel/menu availability, settings, mouselook and normal-camera orientation.
- Loaded nearest-target identity versus the combat system's real selected target.
- Distances just below/above the configured limit, height differences and angles.
- Actual attack gesture timing, misses, repeated input and target changes.
- Unknown target on unload, reset on region change and disabled overlay behavior.
- Simulator-confirmed outcomes during running, narrow turns and both directions
  of movement; record latency and mismatch rates instead of claiming precision.

The half-angle model does not infer a target-side accuracy penalty. A reported
difference between front/back and side attacks may have other causes. Keep it
unmodeled until scripts or controlled measurements establish the rule.
