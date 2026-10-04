---
name: firestorm-builder
description: "Use Firestorm MCP for nearby-object discovery, link/unlink plans, face/material inspection and edits, External Edit scripts, and builder asset uploads. Use when a task involves building in an already running Firestorm session or recovering its MCP connection."
---

# Firestorm builder

Use semantic MCP tools first. Keep one MCP session for acquire/work/release; a new
server process has a different client identity. Do not repeatedly restart MCP
just to execute another tool. Use `workflow_read` to group independent explicit
reads in one tool call; keep dependent writes sequential. A missing native capability is a version gap, not a reason
to send guessed raw commands or restart a shared viewer.

1. Read `connection_status`, then `capabilities_refresh` once per bridge generation.
   Read `builder_capabilities`; for uploads also read `assets_status`.
2. Acquire a bounded control lease for the authorized task. Release in cleanup.
   Check expiry before long reasoning, waits or captures; renew with
   `control_acquire` in the same session before expiry. After expiry or a bridge
   generation change, reacquire and reinspect targets and pending outcomes.
   Human input remains possible: reinspect affected selection/controls afterward.
3. Choose the workflow below. Use exact UUIDs and face indices from observations.
4. Report evidence precisely: source file, viewer cache, UI compiler rows, dispatch,
   and simulator effects are different. Never turn a null or timeout into success.

## Choose tools quickly

| Need | Start with | Evidence / limit |
| --- | --- | --- |
| Nearby loaded objects | `object_search` | Cached names/loading; empty is not absence |
| Selection / linkset / faces | `object_selection`, `object_linkset`, `object_faces` | Exact UUIDs, current selection identity; viewer cache provenance |
| Link / surface mutation | Matching plan -> inspect -> apply -> fresh object read | Expiring single-use plans; dispatch is not simulator confirmation |
| UI controls / compile rows | `ui_task` / `ui_map` -> `ui_read` / `ui_rows` | Exact editor instance; read only required values |
| Registered script | `script_sessions` -> `script_read` -> CAS `script_write` | Local file/backup; compile, save and runtime separately verified |
| Background perception | `background_status` -> `ui_scene` or `ui_capture` | Structure and pixels differ; read [background procedure](references/background-ui.md) |
| Upload / recovery | `assets_status` -> asset route -> `assets_job` | Read [asset recovery](references/assets-and-recovery.md); preserve request IDs |
| Mesh preflight | `asset_inspect`, `mesh_upload_status` | Source, importer readback and simulator axes differ |
| Unfamiliar operation | `viewer_api_inspect` -> `viewer_call` | Discover actual schema and authority first |

Use the connected MCP's listed schemas and native capability receipts together.
Inspect only the chosen route's schemas; a skill adds no runtime capabilities.
Stable script open/compile jobs, complete simulator transforms/light/physics/PBR
readback and measured camera poses remain capability gaps. Do not substitute
stale compiler rows, thumbnails or requested camera settings for verified effects.

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

When the user needs to keep working in another application, use
[background perception](references/background-ui.md). Prefer scoped structure
and native next-frame capture over any desktop-control fallback.

Use `ui_task` for task IDs and `ui_map` for labels/IDs without a live scan. Verify
only the needed controls with `ui_read`. In a compatible viewer, 1-20 controls use
one native round trip and ambiguous runtime names are rejected. Use `ui_tree`
for bounded runtime mounts, and `ui_rows` for visible compiler/error lists.
Do not call raw `LLWindow.getPaths`; its legacy traversal can flood the bridge.

For object contents, a visible panel can have no inventory tree after a selection
change. Before opening an item with a key, verify its live `task inventory` tree
and intended row in a scoped read. Avoid Enter on the generic contents container.
An `inventory not ready` or focus-rejected error means no key was dispatched;
reinspect selection/tree before any further input. Earlier development viewers
can crash on this empty-tree path. This guidance does not replace the native fix.

For scripts, register the intended editor through its External Edit control,
then `script_sessions` -> `script_read` -> `script_write` with the prior SHA256.
Never write an arbitrary temp file. Local writes trigger Firestorm's watcher but
do not prove compilation. Read the exact editor's compiler rows, verify save,
then verify execution when relevant. Do not guess which duplicate editor is open.
Closing/reopening can remove the temporary file or register another session. An
active file does not prove object/item/editor binding; never choose the newest
same-name session. An old successful compiler row does not verify this write:
require evidence tied to the new source or leave compile/save unknown.

## Uploads and reconnects

Read [the asset and recovery procedure](references/assets-and-recovery.md) when
uploading, handling timeouts, changing connections or running a saved plan.
No workflow in this skill authorizes spending, chat or extra world changes.
