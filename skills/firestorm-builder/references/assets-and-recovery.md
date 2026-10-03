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
submission are distinct. Texture/animation uploads still need viewer UI; do not
invent an unattended native endpoint.

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
reply. Coordinate a viewer restart only when authorized, preserving any active
human task. New helper generation invalidates cached descriptors and old leases.
Never delete another client's lock or kill its process to take control.
