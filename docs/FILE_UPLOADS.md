# Direct local texture and PBR uploads — Builder.5

The MCP reads local files, stages bounded bytes and uses the avatar already
logged into Firestorm. No Windows picker, desktop input, second login or UI
preview is involved. Builder.5 requires updated Python/helper code **and** its
native viewer. Installing Python alone does not update a running viewer.
Reload the agent's MCP connection/tool catalog after deploying the matching
package; restarting the viewer-owned helper does not refresh an already running
host's Python server or tool list. The four new tools must be discoverable.

This implementation has isolated tests and a separate development build.
**Live paid texture upload, material creation, simulator rendering and fees
still require acceptance.** Compiling the viewer does not validate these effects.
No live upload or spending was performed during implementation.

## Contract and sequence

Discover `assets_status`: require `contractVersion:1`, `bridgeContractVersion:1`,
`connected:true`, `regionReady:true`, plus `prepareUpload` and `commitUpload` in
`operations`. `fileUploads.version:1` advertises bounds. Only Agni/Aditi are
supported. Reuse the existing `expected` avatar/grid/generation envelope,
bounded lease and persistent client. Account/capability changes invalidate
preparations; a new helper generation changes the lease identity.

| Tool | Purpose |
| --- | --- |
| `assets_file_inspect(filename, material_index=0)` | Local texture metadata or one material's image dependencies. No live calls. |
| `assets_prepare_texture(..., filename, image_index=null)` | Normalize RGB/RGBA PNG, stage 8 KiB chunks, encode JPEG2000 on a native worker and obtain a server price. Optional image index extracts a glTF/GLB dependency. |
| `assets_prepare_material(..., filename, texture_bindings, material_index=0)` | Bind already uploaded image UUIDs, serialize a native PBR material and retain it without creating inventory. |
| `assets_commit_upload(request_id, expected, preparation_request_id, approved_cost)` | Consume one preparation, recheck price where applicable, upload and verify fresh inventory. |

Both prepare tools also require `request_id`, `expected`, `folder_id`, `name`
and `description`. Use a unique description marker for every intended inventory
item. Names are 1–63 UTF-8 bytes, descriptions 1–255, printable, no `|` or
surrounding whitespace. New assets grant next-owner copy/modify/transfer and no
group/everyone permissions, matching the existing API's explicit defaults.

Preparation returns an asynchronous job. Poll `assets_job`; its successful
`result` contains `uploadId`, `assetType`, `cost`, `costSource`, `serverQuote`,
`sourceSha256`, `payloadSha256`, destination/name/description, `assetBytes`, and
`expiresInSeconds:300`. Expiry starts when preparation finishes, not when polled;
`expiresAtViewerSeconds` is a native monotonic deadline, not wall-clock time.
There are at most four preparations, each at most 8 MiB. Cancellation of its
preparation job discards the retained payload. TTL also bounds abandoned data.

Source hashes describe the exact bytes read (for an extracted image, its image
bytes); payload hashes describe normalized staged bytes. Native JPEG2000/material
asset bytes differ from these inputs. Neither hash proves simulator rendering.
The viewer receives bytes, not paths or file-dialog commands. Codec failures
occur before upload. Paths, payload bytes and capability URLs are not journaled.

Commit needs a **new** request UUID, the original preparation request UUID and
the exact cost authorized for that item. Tool availability is not spending
authority. Texture commits request a fresh server quote and refuse a changed,
missing or non-integer price before sending bytes. The prepared content is
single-use, consumed before any asynchronous boundary; changing the commit
request UUID cannot reuse it. Releasing and reacquiring the same client lease
may preserve identity, but switching clients/helpers does not.

Material preparation reports `cost:0`,
`costSource:"viewer_material_creation"`, `serverQuote:false`: this is the
viewer's existing no-charge create/update workflow, **not a server texture
quote**. It creates an inventory material, checks its identity, then uses
`UpdateMaterialAgentInventory`. An explicit nonzero/invalid update fee is
refused. An empty material item can remain after interruption; it is not success.

Poll the commit job for `state:"succeeded"`; result supplies confirmed
`itemId`/`assetId`, `freshness:"server"`, `assetType`, `approvedCost`, input
hashes. The approved amount is not a transaction-history receipt. Missing
completion replies, post-submission timeouts or session changes stay unknown;
saved acknowledgements remain available. Query `assets_request` with the
original commit UUID, then `assets_reconcile` where possible. Reconciliation
requires an acknowledged asset UUID and matching fresh inventory. Never replay
an uncertain commit under another ID or assume absence proves upload failure.

## Examples

Illustrative values below are placeholders; use observed session/folder IDs.
All viewer calls occur in one leased client session, released in cleanup.

```python
session = {"avatarId": avatar_id, "grid": "agni", "generation": generation}
prepared = call("assets_prepare_texture", {
    "request_id": prepare_uuid, "expected": session,
    "folder_id": folder_id, "name": "Stone albedo",
    "description": "Upload receipt " + prepare_uuid,
    "filename": absolute_image_path,
})
# Poll prepared.jobId to terminal state. Read result.cost; obtain task authority.
committed = call("assets_commit_upload", {
    "request_id": commit_uuid, "expected": session,
    "preparation_request_id": prepare_uuid,
    "approved_cost": authorized_exact_cost,
})
# Poll committed.jobId and preserve confirmed itemId/assetId.
```

For a material, inspect first. For every missing dependency, use
`assets_prepare_texture` with `filename` set to the material file and
`image_index` set to that dependency's index. Commit each under its authorized
cost, preserve confirmed IDs, then prepare the material:

```json
{
  "request_id": "<new material preparation UUID>",
  "expected": {"avatarId": "<avatar UUID>", "grid": "agni", "generation": "<generation UUID>"},
  "folder_id": "<folder UUID>",
  "name": "Stone PBR",
  "description": "<unique material receipt marker>",
  "filename": "<absolute .gltf or .glb path>",
  "material_index": 0,
  "texture_bindings": {"0": "<base-color asset UUID>", "1": "<normal asset UUID>"}
}
```

`texture_bindings` keys are **image indices**, not texture slots or indices in
the `textures` array. Existing UUID image URIs may be reused with an empty map.
There is no implicit batch spending. If one dependency fails, previously
confirmed textures remain reusable; do not upload them again or delete them
automatically. UUID references are not proof of asset availability or permissions.

## Supported inputs and deliberate limits

- Absolute local paths; sources up to 32 MiB, normalized stages up to 8 MiB.
- Static PNG/JPEG/BMP/TGA, RGB/RGBA normalized without resizing. Dimensions must
  be powers of two between 4 and 2048. Other dimensions fail with instructions
  to resize explicitly. JPEG2000 is encoded by the viewer; no lossless promise.
- glTF 2.0 JSON or GLB v2, one explicitly indexed material per job. Supports
  base color, normal, ORM and emissive UUIDs, scalar/color factors, alpha mode,
  cutoff and double-sided flag.
- Dependencies may be local relative files within the source directory,
  base64 data URIs, GLB buffer-view images or existing asset UUIDs. No remote
  downloads or paths escaping the source directory.
- Unsupported material extensions, texture transforms, nonzero UV sets,
  nondefault normal scaling, non-repeating samplers and separate occlusion maps fail explicitly.
  Occlusion must share ORM, with default strength/UVs. Bake those features first.
- Mesh import settings/LOD/physics and animation upload remain their existing
  workflows. This API does not replace their importers or apply a material to a face.

## File-picker fallback

Windows Open dialogs are not part of Firestorm XUI. For older viewers, the
existing `native_file_dialogs`/`native_file_choose` tools handle recognized
English dialogs owned by the configured viewer installation. Never use a viewer
UI-tree scan to find their filename field. No global keys/mouse are sent, but
the dialog can take focus; this route is excluded from background-only plans.

## Build and acceptance

For a fresh integration, `apply_assets_extension.py` includes the current
sources. To upgrade the recorded Builder.4 checkout, use
`python scripts/apply_file_uploads.py CHECKOUT --dry-run`, inspect, then run
without `--dry-run`. Unknown source hashes are refused before writes. Compile
and stage to a new directory with `stage_custom_viewer.py`; do not overwrite a
running viewer. Install the matching Python package and restart/switch only when
the user authorizes it.

Isolated validation covers input bounds and pixel preservation, GLB/data-URI
dependencies, traversal/unsupported-feature rejection, strict cost/session
checks, private durable intent and no replay after lost acknowledgements.
Native policy regression covers exact-price approval, lease/generation/expiry
and single-use claims. Native compilation validates integration; it is not an
end-to-end codec or simulator test.

Pending live acceptance: paid texture quote/commit and final fee, material with
reused UUIDs, material with newly uploaded dependencies, interrupted material
creation/reconciliation, inventory visibility and rendered appearance, and
no-focus behavior while another application is active. Use disposable synthetic
assets and an explicitly authorized upload budget for those checks.
