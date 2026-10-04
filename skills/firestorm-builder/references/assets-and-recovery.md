# Asset jobs, task plans and recovery

`assets_status` must report contractVersion 1, bridgeContractVersion 1, connected
and regionReady true. Sound upload cost is nullable. Require exactly zero for
the native sound path; never coerce unknown to zero. Preserve the non-secret
avatarId/grid/generation and bridgeGeneration. Login belongs to Firestorm.

Use `assets_list_inventory` for a fresh folder result; cached search results
cannot prove absence or emptiness. `assets_create_folder`, `assets_upload_sound`
and `assets_create_notecard` return jobs. Supply an explicit UUID request ID and
expected session. Poll `assets_job`; retain actual returned item/asset/folder IDs.
An upload sound request accepts already prepared mono 44.1 kHz Ogg/Vorbis within
the negotiated duration/size limits. No re-encoding or second login is needed.

After a lost reply, query `assets_request` using the original request ID. Use
`assets_reconcile` when the contract supports it. Unknown stays unknown: do not
generate a new ID to repeat a potentially completed upload. Delivery and object
interaction are generic primitives; product-specific station/catalog rules stay
in the consumer. Detach closes the consumer connection, never logs out Firestorm.

For mesh, use `asset_inspect`, the `mesh_upload` UI task and `mesh_upload_status`.
Validate LODs/physics and reread the quote after preview changes. Calculation and
submission are distinct. For texture/PBR files use the direct Builder.5 route
below. Animation and older viewer imports still need viewer UI.

## Direct texture and PBR files (Builder.5)

Require `prepareUpload` and `commitUpload` in `assets_status.operations`, from
the current helper and native viewer. `assets_file_inspect` reads an absolute
local path without opening a picker. Use `assets_prepare_texture`, poll
`assets_job`, inspect `cost`, `costSource`, source/payload hashes and destination,
then call `assets_commit_upload` with a new request ID, `preparation_request_id`
and the exact authorized `approved_cost`. Keep the same client/lease/session;
preparations expire 300 seconds after they finish. Commit rechecks the texture
server price before sending bytes. A prepared job is not an uploaded asset.

For glTF/GLB, inspect dependencies first. Reuse known texture asset UUIDs or
prepare/upload each missing `image_index` from the same file using the texture
tool. Save each confirmed asset ID before starting another upload. Then call
`assets_prepare_material` with `texture_bindings` mapping string image indices
to those UUIDs. No textures are uploaded implicitly. Material creation uses the
viewer's zero-cost create/update workflow; `serverQuote:false` distinguishes
this from a texture server quote. Reference UUID availability/permissions remain
unverified until checked in-world. Unsupported features fail instead of being
silently removed. Do not treat partial dependency success as complete material
success or automatically delete paid textures if a later step fails.

Cancel an unused preparation with `assets_cancel` and its preparation job ID.
For uncertain commits read `assets_request` with the original commit request ID,
then reconcile if needed. Never make a second commit ID to retry an uncertain
upload. These direct tools are allowed in background-only plans; no dialog or
desktop input is needed. See the repository's `docs/FILE_UPLOADS.md` for the
contract, supported file restrictions and live-validation status.

Windows Open dialogs belong to the OS, not Firestorm's XUI tree. On an older
viewer, use `native_file_dialogs` then `native_file_choose` only when the task
permits that dialog workflow. They do not use global keyboard/mouse input, but
the dialog can take focus. Never scan `ui_find`/`ui_tree` for its filename field
or fall back to desktop automation for a background-only task.

The installed package offers `python -m firestorm_mcp.executor PLAN.json
--data-dir STATE --viewer-dir VIEWER`. The JSON shape is:

```json
{"version":1,"calls":[
  {"tool":"object_search","arguments":{"distance":32,"owned_only":true}},
  {"tool":"object_selection","arguments":{}}
]}
```

The executor validates the whole plan, opens one real MCP SDK session, holds its
own bounded lease, checks bridge generation between calls, stops at errors and
cleans up. It never starts/restarts the viewer. Writes require `--allow-writes`
and existing task authority; the flag is not authority by itself. Plans contain
literal arguments, not substitutions, sleeps or retries. Job results may remain
queued/running after a call returns. Inspect them before dependent work.

If disconnected, read status/diagnostics and inspect saved requests. An invalid
length prefix is terminal; guessing a new frame boundary could misassociate a
reply. Builder.4 preserves a historical disconnect summary and its native viewer
can restart its configured helper up to three times (roughly 2/4/8-second delays),
without replaying any action. Check connection status for a fresh generation,
then rediscover, reacquire and reinspect before continuing. A still-live stuck
helper is not killed. The saved last operation does not prove the exit cause.
Older viewers lack this recovery. Coordinate a viewer restart only when authorized,
preserving any active human task. New helper generation invalidates cached descriptors and old leases.
Never delete another client's lock or kill its process to take control.
