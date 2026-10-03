---
name: firestorm-builder
description: "Use Firestorm MCP for nearby-object discovery, link/unlink plans, face/material inspection and edits, External Edit scripts, and builder asset uploads. Use when a task involves building in an already running Firestorm session or recovering its MCP connection."
---

# Firestorm builder

Use semantic MCP tools first. Keep one MCP session for acquire/work/release; a new
server process has a different client identity. Do not repeatedly restart MCP
just to execute another tool. Use `workflow_read` to group independent explicit
reads in one tool call. A missing native capability is a version gap, not a reason
to send guessed raw commands or restart a shared viewer.

1. Read `connection_status`, then `capabilities_refresh` once per bridge generation.
   Read `builder_capabilities`; for uploads also read `assets_status`.
2. Acquire a bounded control lease for the authorized task. Release in cleanup.
   Human input remains possible: reinspect affected selection/controls afterward.
3. Choose the workflow below. Use exact UUIDs and face indices from observations.
4. Report evidence precisely: source file, viewer cache, UI compiler rows, dispatch,
   and simulator effects are different. Never turn a null or timeout into success.

## Objects and surfaces

- `object_search` filters loaded prims in the viewer by radius, owned/root flags and
  cached name. Follow `next_offset`; pages can shift. Unknown names are excluded
  by a text query. An empty result is not proof that an object is absent in-world.
- For selection, read `object_selection`, then `object_select` with its exact
  `selection_identity`. Wait for properties through fresh reads; do not assume
  selected roots or the desired link root from the order you requested.
- Link/unlink: inspect `object_link_plan`'s selection and candidate root, then
  consume the authorized plan with `object_link_apply` within 30 seconds. Read
  every affected UUID's `object_linkset`. `dispatched` is not link success.
  `confirmation_required_no_dispatch` means the viewer preference prevented the
  action; complete it manually or leave it pending. Do not disable that setting.
- Surface edits: `object_faces` -> `material_face_plan` -> inspect before/preview ->
  `material_face_apply` -> fresh `object_faces`. Supports color, UV transforms,
  glow and fullbright; PBR assets are not edited by these tools. A script-driven
  face change invalidates the plan instead of being overwritten.

## UI and scripts

Use `ui_task` for task IDs and `ui_map` for labels/IDs without a live scan. Verify
only the needed controls with `ui_read`. In a compatible viewer, 1-20 controls use
one native round trip and ambiguous runtime names are rejected. Use `ui_tree`
for bounded runtime mounts, and `ui_rows` for visible compiler/error lists.
Do not call raw `LLWindow.getPaths`; its legacy traversal can flood the bridge.

For scripts, register the intended editor through its External Edit control,
then `script_sessions` -> `script_read` -> `script_write` with the prior SHA256.
Never write an arbitrary temp file. Local writes trigger Firestorm's watcher but
do not prove compilation. Read the exact editor's compiler rows, verify save,
then verify execution when relevant. Do not guess which duplicate editor is open.

## Uploads and reconnects

Read [the asset and recovery procedure](references/assets-and-recovery.md) when
uploading, handling timeouts, changing connections or running a saved plan.
No workflow in this skill authorizes spending, chat or extra world changes.
