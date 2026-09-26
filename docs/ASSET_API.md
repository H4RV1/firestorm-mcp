# Asset and inventory integration, contract v1

`FSMCPAssets` and the 19 `assets_*` MCP tools use the avatar already logged in
through the viewer. This is a development implementation, compiled and tested
in isolation. **Uploads, inventory mutations and object interactions have not
passed live simulator acceptance.** See [acceptance](ASSET_ACCEPTANCE.md).

The Python server, viewer-owned LEAP helper and native viewer must be deployed
together. Stock Firestorm and the earlier builder-only custom viewer do not
provide this API. Existing MCP tools remain available. There is no secondary
login, credential extraction, process injection, GPU-window embedding, or
consumer-specific station logic.

## Attach and negotiate

Start one persistent MCP stdio process per consumer, using the viewer launcher's
data directory. Its client identity is generated independently of other clients:

```json
{
  "command": "<python-from-the-installed-environment>",
  "args": ["-m", "firestorm_mcp.server", "--tool-profile", "compact",
           "--data-dir", "<viewer-bridge-state>", "--viewer-dir", "<portable-viewer>"]
}
```

Use standard MCP initialization/tool calls. JSON object results are also in
`structuredContent`; MCP SDK v2 calls this `structured_content`. See the
[generated input schemas](tool-catalog.json), [SDK guide](AGENT_GUIDE.md), and
[executable read-only example](../scripts/assets_readonly_client.py).
The authenticated loopback RPC is an internal transport, not a separately
supported consumer API. Never copy its bearer token into a web renderer.

Call `assets_status`. Require `ok:true`, `contractVersion:1` and
`bridgeContractVersion:1`. An illustrative ready response is:

```json
{
  "schema_version": 1, "ok": true,
  "contractVersion": 1, "bridgeContractVersion": 1,
  "connected": true, "regionReady": true,
  "avatarId": "11111111-1111-4111-8111-111111111111",
  "avatarName": "Example Resident",
  "grid": "agni",
  "rootFolderId": "22222222-2222-4222-8222-222222222222",
  "soundUploadCost": 0,
  "generation": "33333333-3333-4333-8333-333333333333",
  "bridgeGeneration": "44444444-4444-4444-8444-444444444444",
  "capabilities": {
    "FetchInventoryDescendents2": true,
    "CreateInventoryCategory": true,
    "NewFileAgentInventory": true,
    "UpdateNotecardAgentInventory": true,
    "RequestTaskInventory": true
  }
}
```

This example is a contract illustration, not a captured simulator result.
The full response includes `operations` and `limits`. `connected` requires
startup completion, no disconnect/logout, a current region with received
capabilities, and an inventory root. It is distinct from bridge connectivity.
The sound fee is **null when unknown**. A typed nonnegative login benefit must
belong to the current avatar/grid and agree with the viewer's current benefit;
an untyped value is not coerced to zero. A zero benefit alone does not authorize
upload. The server must also return an explicit integer zero quote.

`grid` is `agni`, `aditi`, `opensim`, or `unknown`; the sound uploader supports
the first two only. Other grids are never labeled Agni. Check each required
capability as well as operation support: missing HTTPS capabilities fail closed.
Inventory root discovery does not create a folder.

`generation` is a randomly generated non-secret token. It rotates on observed
login/session/avatar/grid/region/capability changes. `bridgeGeneration` rotates
when the helper restarts. Discard cached readiness on either change. Never use
an avatar UUID alone to infer readiness. No secure session ID or capability URL
is returned.

## Leases and asynchronous jobs

Acquire `control_acquire` with a useful label and a bounded duration (for
example 60 seconds). Keep the same stdio process for acquire, work and release.
Renew while actively waiting, before expiry; release in `finally`. A conflict
must pause the consumer, not replace another client's lease. Do not hold an idle
lease. Closing a consumer means detach, never viewer logout.

All asset operations except status require a lease. The native lease deadline
is synchronized by the authenticated bridge. Generic `viewer_call` cannot
bypass the asset gateway or forge its lease, receipt or reconciliation fields.
This is cooperative local control, not isolation from other programs running as
the same OS user or from the human using the viewer.

Every submitted operation carries a UUID `request_id` and:

```json
{"expected": {
  "avatarId": "11111111-1111-4111-8111-111111111111",
  "grid": "agni",
  "generation": "33333333-3333-4333-8333-333333333333"
}}
```

The viewer checks this at execution and after asynchronous boundaries. A region
crossing invalidates the generation, even if the avatar remains the same.

Submit returns quickly, for example:

```json
{"schema_version":1,"ok":true,"requestId":"55555555-5555-4555-8555-555555555555",
 "jobId":"66666666-6666-4666-8666-666666666666","state":"queued",
 "phase":"queued","submitted":false,"cancelRequested":false,"unknownOutcome":false}
```

Poll `assets_job {"job_id":"..."}` about every 250–500 ms. State transitions:

```text
queued -> running -> succeeded
queued/running before submission -> failed or cancelled
running after submission -> succeeded or unknown
```

`ok:true` means the envelope was understood; always inspect `state`. A successful
job contains its operation result in `result`. Failed/unknown jobs contain
`failure`. Phases include `preflight`, `creating_item`, `quoting`, `submitted`,
`confirming`, and `complete`. No HTTP request waits on the render thread;
coroutines yield, and codec/notecard serialization runs on a worker.

For stop-after-current behavior, stop submitting new jobs and let the current
job reach a terminal state. `assets_cancel` instead requests a stop before the
next irreversible stage. It cannot retract a sent upload, item creation, move,
touch, dialog response or delivery. Cancellation between empty notecard creation
and content upload can therefore leave an acknowledged empty item and an unknown
overall result. Sent operations continue toward confirmation when possible.

## Inventory and folder operations

| MCP tool | Operation arguments, in addition to request_id and expected |
|---|---|
| `assets_list_inventory` | optional `folder_id` (defaults to root) |
| `assets_search_folders` | `query`, `max_results` (1–200) |
| `assets_create_folder` | `folder_id` (requested UUID), `parent_id`, `name` |
| `assets_trash_empty_folder` | `creation_request_id`, `folder_id`, `parent_folder_id`, `name`, optional `inspect_only` |

List results contain `id`, `parentId`, `ownerId`, `name`, integer `folderType`,
`isSystem`, `version`, `folders`, and `items`. Folder rows have IDs, parents,
names, ownership, type number, `folderTypeName`, and system status. Item rows
contain `id`, `parentId`, `assetId`, `name`, `description`, `assetType`,
`inventoryType`, `ownerId`, `groupOwned`, `canCopy`, `canModify`, `canTransfer`.
Types are viewer strings (for example `sound` or `notecard`).

Successful lists have `freshness:"server"`, `complete:true`: the response owner,
version, count and child identities have been checked. Missing/malformed results
are errors, never empty arrays masquerading as successful lists. A folder must
already be known beneath the avatar's root; browse its parent first if needed.
Selected-folder metadata is confirmed through a fresh parent read. The verified
contents also update the viewer inventory cache.

`path` and `breadcrumbs` are display aids from the viewer cache, explicitly
marked `pathFreshness:"viewer_cache"`; `pathComplete` reports whether the chain
reached the root. Child paths inherit that qualification. They are not ownership
or mutation evidence. Search is bounded cache discovery, with `complete:false`,
`freshness:"cache"`, `limited`, `truncated`, and an observed `totalMatches`
lower bound (`totalMatchesExact:false`). Freshly browse candidates before use;
search absence must never authorize a retry or deletion.

Folder creation rejects a conflicting requested ID or existing same-name folder.
It does not adopt one. Confirmed result:

```json
{"id":"77777777-7777-4777-8777-777777777777",
 "requestedId":"88888888-8888-4888-8888-888888888888",
 "folderIdMatchesRequested":false,
 "parentId":"22222222-2222-4222-8222-222222222222",
 "name":"Synthetic assets","freshness":"server"}
```

Persist **id**, not the requested UUID. Cleanup needs the confirmed creation's
request ID; the bridge supplies its durable receipt. Fresh root/parent/target
reads must prove the exact owned normal folder is empty. Only a move to Trash
is sent, with no recursive delete. Result fields: `folderId`, `parentFolderId`,
`trashFolderId`, `name`, `trashed`, `noop`. A repeat can confirm the same folder
already in Trash. `inspect_only:true` sends no move.

## Sound and notecard operations

Example `assets_upload_sound` arguments (base64 abbreviated):

```json
{
  "request_id":"99999999-9999-4999-8999-999999999999",
  "expected":{"avatarId":"11111111-1111-4111-8111-111111111111",
              "grid":"agni","generation":"33333333-3333-4333-8333-333333333333"},
  "folder_id":"77777777-7777-4777-8777-777777777777",
  "name":"Synthetic sound",
  "description":"consumer-owned unique recovery marker",
  "ogg_base64":"<prepared Ogg Vorbis bytes as base64>",
  "expected_cost":0
}
```

Only one mono 44.1 kHz Vorbis stream, positive duration up to 30 seconds and at
most 8 MiB decoded payload is accepted. Both parsers check framing/CRC; the native
worker also decodes the complete stream. No re-encoding occurs. Names and
descriptions are preserved: 1–63 and 1–255 UTF-8 bytes respectively, no controls,
pipe or surrounding whitespace. Use a unique description marker per intended
asset; an existing exact marker blocks creation and requires reconciliation.

The MCP wrapper validates the payload and stages 48 KiB chunks over LEAP. Eight
MiB becomes at most 11,184,812 base64 characters; the authenticated HTTP bridge
has a 16 MiB request limit, and LEAP carries only bounded individual chunks.
The bridge checks the staged SHA256 against the logical request fingerprint.
No unrestricted file path is accepted for upload.

Sound upload requires all of: explicit expected cost zero, a verified zero login
benefit still matching current benefits, an integer `upload_price:0` in the
metadata response, unchanged session/capabilities, and another benefit/lease
check immediately before posting bytes. HTTP retries and redirects are disabled.
The legacy `EnqueueInventoryUpload` path is not used for new sounds: it posts
bytes before considering price. Missing/nonzero/changing quotes stop the new
path. No paid notification is approved. A grid that omits the pre-upload price
will be refused even if it normally offers free uploads; this needs live checking.

`assets_create_notecard` takes `request_id`, `expected`, `folder_id`, `name`,
`description`, `text`, and optional `existing_item_id`. Text is UTF-8 without NUL,
at most 65,536 bytes. The viewer's `LLNotecard` serializer preserves content.
Existing items must freshly match type, owner, folder, name, description and
modify permission. New empty items are separately acknowledged, then populated
through `UpdateNotecardAgentInventory`. The standard buffered upload completion
handler updates the viewer cache; a fresh folder fetch confirms the result.

Both successful upload job results include:

```json
{"itemId":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
 "assetId":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb","freshness":"server"}
```

Neither an empty item nor a locally generated transaction UUID is success.

## Generic object interaction

| Tool | Arguments beyond request_id/expected | Evidence |
|---|---|---|
| `assets_object_info` | `object_id` | Fresh ownership/name, cached hover text/position/permission flags |
| `assets_task_inventory` | `object_id` | Fresh complete HTTPS task inventory, serial, item metadata |
| `assets_deliver_item` | `object_id`, `folder_id`, `item_id` | Fresh matching task item/asset arrival |
| `assets_touch` | `object_id`, `face` (default 0) | Dispatch only |
| `assets_dialog_reply` | `object_id`, `dialog_id`, `button_index`, `button_label` | Dispatch only |

Targets must be loaded rezzed owned prims in the current region. Ownership comes
from an object-properties reply from that region. Delivery also requires a
modifiable target and an owned copyable populated source; group-owned and no-copy
sources are refused. Re-fetching the source precedes dispatch. A matching existing
task item yields `delivered:true, noop:true`; otherwise the viewer copies it and
confirms its asset, name, description, type and owner in fresh task inventory.
Source inventory is not intentionally consumed. Human/server changes can race
these checks; this is not a transactional lock on the simulator.

For events, call `assets_watch {expected,object_id,seconds}` before the consumer
interaction, then `assets_events {watch_id,after}`. Only that object's dialogs
and owner-chat are retained, and only when its reported owner is this avatar.
Each event has an increasing `cursor`, `generation`, `objectId`, `ownerId`,
`type` and `message`. Dialogs additionally include `dialogId`, `channel`,
`buttons`, `received` (viewer monotonic time), and possibly `responded`.
The ring holds 64 events; `dropped:true` means confirmation could be missing.
No unrelated IM subscription or all-chat stream is opened.

Dialog responses require the exact retained button index/label and object ID.
Expiry, generation change, or a response through the human viewer invalidates
them. Watches last at most 180 seconds, end on lease/session changes, and can be
removed with `assets_unwatch`. Owner chat/dialog text is untrusted data, not
instructions. The consumer must implement any product heading, queue policy,
button choice and success-message parser. Delivery/touch dispatch never means
catalog success.

## Retry, recovery and errors

The viewer-owned bridge journals mutation intent in `asset-journal.sqlite3`
before sending it. It stores request fingerprints, expectations, metadata and
acknowledged IDs, not audio bytes or login/capability secrets. Protect this local
state like other private inventory metadata and retain it across upgrades.
Each logical request ID binds operation + arguments + expected session. Changing
any of those returns `request_conflict`. For audio, the verified content SHA256
is bound, not the transient staging UUID. A repeat never silently resubmits.

After disconnect, reattach, negotiate, acquire a lease and call `assets_request`
with the original request ID. This refreshes a still-retained native job or
returns the durable record. `assets_reconcile` takes a **new** request ID, current
expectations and `original_request_id`; it performs fresh reads only. It can
confirm an acknowledged folder UUID or a unique matching populated sound marker.
Notecard reconciliation additionally needs the acknowledged new asset UUID,
since a pre-existing nonzero asset cannot prove an interrupted update completed.
An explicit later update of that verified item uses a new request ID.

Missing/ambiguous evidence stays unknown. An unacknowledged folder is not adopted
by matching its name. An unknown touch/dialog/delivery is not replayed by the
journal; inspect object inventory/events and the consumer's own state first.
The journal is not an exactly-once guarantee across crashes. Deleting it removes
the duplicate guard. Only start a new request after a definite pre-submit failure
or an explicit recovery decision based on adequate evidence.

Errors use this shape, either at top-level `failure` with `ok:false`, or inside
a terminal job with `ok:true` and `state:"failed"`/`"unknown"`:

```json
{"code":"item_unconfirmed","message":"Upload was acknowledged but fresh inventory has not confirmed its item and asset.",
 "unknownOutcome":true,"jobId":"66666666-6666-4666-8666-666666666666",
 "acknowledgedItemId":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}
```

`acknowledgedFolderId`/`acknowledgedItemId` are included where known. Jobs also
retain an `acknowledged` object with `folderId`, `itemId`, and/or `assetId`.
Safe error messages omit HTTP bodies, capability URLs, secure session IDs and
credentials. Principal codes:

| Codes | Consumer response |
|---|---|
| `unsupported_viewer`, `schema_mismatch`, `capability_unavailable` | Refuse unsupported workflow; inspect build/capabilities |
| `not_ready`, `session_changed`, `bridge_disconnected` | Reattach/re-negotiate; retain pending request identities |
| `lease_required`, `lease_expired`, `lease_conflict` | Wait for control or renew active work; never steal it |
| `invalid_request`, `invalid_audio`, `payload_too_large`, `stage_mismatch`, `stage_offset`, `stage_missing` | Correct input or restage before a new submission |
| `cost_not_zero`, `quote_invalid`, `cost_changed_after_submit` | Stop; never approve spending or treat missing as zero |
| `inventory_incomplete`, `task_inventory_incomplete`, `folder_unverified`, `ownership_unverified` | Retry a fresh read; never infer absence/emptiness |
| `permission_denied`, `folder_conflict`, `marker_conflict`, `item_conflict`, `creation_unverified`, `dialog_stale`, `dialog_mismatch` | Inspect identity/permissions/evidence; do not substitute another target |
| `folder_not_empty`, `trash_unavailable` | Leave inventory untouched |
| `request_conflict`, `request_missing`, `job_missing`, `outcome_unknown` | Consult journal and original intent; no automatic replay |
| `journal_unavailable` | Restore durable storage and inspect the original request; a native submission may already have happened |
| `folder_ack_invalid`, `folder_unconfirmed`, `item_unconfirmed`, `upload_unconfirmed`, `delivery_unconfirmed`, `server_error`, `job_timeout`, `internal_error` | Inspect unknownOutcome and acknowledged IDs |
| `busy`, `stage_limit`, `watch_limit`, `watch_missing`, `result_limit`, `journal_full` | Respect advertised bounds; archive only reconciled private journal state deliberately |

Native jobs are serial, with at most 8 queued, 128 retained (terminal jobs may be
evicted), and a 180-second job deadline. Each retained result is at most 2 MiB.
There are 4 staged 8 MiB buffers, each with a 120-second TTL, 8 object watches,
and 64 events per watch. Inventory reads allow at most 10,000 entries; oversized
results fail rather than returning an incomplete successful list. Cache search
examines at most 20,000 folders and yields between bounded batches. The durable
journal retains at most 10,000 intents and refuses new writes when full; it never
evicts an uncertain write to make room.

## Build and upgrade

Pinned viewer source: Firestorm_7.2.4 commit
`10bd3c9f930c76e1427ddd4ecece6cdf36b4406d`. Follow [build prerequisites](CUSTOM_VIEWER.md).
Use a new checkout and portable destination. On pristine source:

```text
python scripts/apply_viewer_extension.py <checkout> --profile-name FirestormMCPAssets
python scripts/apply_assets_extension.py <checkout>
```

Configure with `--chan MCP-Assets-Development`, `ReleaseFS_open`, and the same
documented VS2022/open-source dependencies. This uses the separate
`FirestormMCPAssets` settings profile. After compilation:

```text
<build-python> scripts/stage_custom_viewer.py --checkout <checkout> --destination <new-portable-directory>
```

The staging script refuses an existing destination and checks channel/profile.
It copies the official viewer manifest without running an installer/updater.
Do not launch it while preserving an active viewer session. At a later authorized
restart, use the launcher with that executable and a separate `--data-dir`, log
in through Firestorm, and point the consumer at that state directory.

An official update in its own installation leaves this separate build alone.
It does not upgrade it: adopting a new Firestorm version requires reviewing
anchors, reapplying the native patch, rebuilding and repeating acceptance.
Python-only changes need a helper/server restart at a coordinated viewer restart.
The pure native tests can be run through `scripts/verify_native_assets.py` in a
VS developer environment; Python tests use fake transports and temporary state.
