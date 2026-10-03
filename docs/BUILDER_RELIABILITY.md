# Local builder.2 integration

This branch combines the generic asset/inventory integration and the XUI map.
It adds bounded native observations and guarded builder actions. Consumer rules,
music assets, credentials and product-specific station logic remain outside this
repository. The installed/running viewer is not automatically replaced.

## Tools and limits

| Workflow | Interface | Evidence/limits |
| --- | --- | --- |
| Nearby prims | `object_search(distance, owned_only, roots_only, query, limit, offset)` | Native cache traversal; <=4096 scanned entries or 8 ms per call; <=100 results within <=256 m. Names use received selection properties or an existing Area Search cache. Does not open Area Search or fetch missing names. |
| Exact selection | `object_selection`, `object_select(object_ids, expected_selection)` | <=32 owned modifiable roots, exact ordered prior selection identity, lease required. Normal selection can affect focus and physics; reinspect. |
| Link/unlink | `object_link_plan(action)`, `object_link_apply(plan_id)` | <=256 selected prims; 30-second, single-use native plan. Agent/region, ordered selection, root IDs and permissions rechecked before dispatch. |
| Surfaces | `object_faces`, `material_face_plan(object_id, face, changes)`, `material_face_apply(plan_id)` | Color/UV/glow/fullbright only. Compare the entire prior texture entry and root before dispatch. No texture UUID, normal/specular or PBR asset edits. |
| UI knowledge | `ui_task`, `ui_map` | Local cached default-English XUI, 8 task guides; source candidates require live verification. |
| Live UI paths | `ui_tree(under, max_depth, limit, offset)` | <=2048 visited nodes, depth<=8, <=200 paths, <=64 KiB of path text, 8 ms traversal budget. Narrow when no continuation fits. |
| Live controls | `ui_read` | On FSMCPUI: 1 native request for <=20 exact paths; metadata without implicit text reads. Values opt-in, <=4096 bytes each; line-editor values suppressed because this baseline lacks a public password-state getter. |
| Compiler rows | `ui_rows(path, offset, limit)` | Visible LLScrollListCtrl only; <=50 rows, <=8 columns, <=1024 bytes/cell, <=32 KiB text. Not semantic compile/save confirmation. |
| Read grouping | `workflow_read(calls, timeout)` | 1-16 allowlisted reads, full-plan schema validation first, <=2 MiB returned data, stop on first error. Budget checked between calls; each operation retains its own timeout. No input or automatic lease acquisition. |
| Persistent plans | `python -m firestorm_mcp.executor` | One real MCP SDK session, <=32 calls, prevalidation, generation checks and bounded owned lease with cleanup. Stops at pending jobs/errors; does not replay. |

`FSMCPUI` reports schema_version 1. Exact paths use URI-escaped name segments.
The resolver rejects duplicate names at every ancestor; it never chooses the
first of multiple script editors. This verifies uniqueness **at read time**,
not a stable handle across later human interaction. `ui_read.atomic` stays false:
one event-loop turn is not a simulator transaction.

Tree/list cursors are indices into a new live query, not snapshots. Truncation,
depth limits, unknown names and incomplete region loading never prove absence.
Source map IDs are not native object IDs. Native and Python query limits are
enforced separately so raw dynamic/`viewer_call` access cannot bypass the old
`getPaths` guard.

## Builder action examples

First discover capabilities and acquire the task lease. Illustrative UUIDs below
are placeholders; use actual observations, not these values.

```json
{"distance":32,"owned_only":true,"roots_only":true,"limit":50}
```

Call `object_selection` and pass its returned `selection_identity` unchanged:

```json
{"object_ids":["11111111-1111-4111-8111-111111111111"],"expected_selection":[]}
```

After properties arrive, prepare `object_link_plan` with `{"action":"unlink"}`.
Review its `selection`, `candidate_root_id` and `expires_in_seconds`. Apply the
returned plan exactly once using `{"plan_id":"<returned UUID>"}`. A normal
dispatch returns:

```json
{"schema_version":1,"action":"unlink","status":"dispatched","verified_effect":false}
```

If the viewer's unlink preference requires confirmation, the result is
`confirmation_required_no_dispatch`. The API does not queue the normal delayed
confirmation callback: it could act on a different selection later. The plan
is consumed; handle the viewer action manually. No settings are changed.

For surface changes, prepare:

```json
{"object_id":"11111111-1111-4111-8111-111111111111","face":2,
 "changes":{"color":[1,0.5,0.25,1],"scale":[2,2],"glow":0.05}}
```

Inspect `before` and `preview`, then call `material_face_apply` with its plan ID.
Changes require an owned, modifiable, nonpermanent, nonattachment in-region
object and respect the viewer's edit restrictions. Plans expire after 30 seconds
and are consumed before dispatch. On timeout, inspect every affected UUID/face;
creating another plan is a new action, never automatic recovery. Local texture
entry readback is not server confirmation, and legacy properties may not control
the rendered appearance of a PBR surface.

## Upload coverage

The existing [asset contract](ASSET_API.md) is retained: prepared Ogg/Vorbis sound,
populated UTF-8 notecards, fresh inventory, folder receipts, generic copyable-item
delivery and filtered object interaction. Each consumer keeps its own MCP client
identity and obeys bounded leases. Firestorm owns the login and network session.

Mesh remains the inspected viewer preview workflow (LOD, physics, quote, upload).
Texture and animation uploads still use viewer dialogs. This change does not add
unattended native upload for every asset type or automatically approve charges.

The asset gateway now reuses its current native lease across staging chunks and
job polls. It resynchronizes when ownership changes, expiry approaches or the
bridge lease is extended. Native execution still checks its own lease/session.
An 8 MiB upload has 171 chunks: those chunks no longer need 171 redundant native
lease calls while the same lease remains valid. This is a measured call-count
improvement in isolation, not an in-world throughput measurement.

## Connection behavior

- Metadata has `rpc_contract:2` and a non-secret `bridge_generation`. The local
  authenticated RPC remains internal; consumers use persistent MCP stdio.
- Clients invalidate descriptors when URL/token/session identity changes. An old
  lease cannot continue writes in a new helper generation. Explicitly reacquire
  and rediscover; nothing is automatically replayed or restarted.
- HTTP waits follow the requested viewer timeout plus a margin. Requests/replies
  are capped at 16 MiB. Bridge operation-lock contention fails before dispatch
  after two seconds instead of building an unbounded wait queue.
- LEAP payloads above 16 MiB and within the 128 MiB framing ceiling are drained
  in 64 KiB blocks without LLSD decoding. Malformed framed replies fail pending
  requests with unknown outcome. An invalid length prefix is terminal; no guessed
  stream resynchronization is attempted. This is not a crash-proof guarantee.
- Pending replies are capped at 64. Events are bounded by count and total bytes;
  oversized events and overflow have loss cursors. Late correlated replies are
  counted separately and never retained as subscription events.
- `connection_status` includes pending requests, event bytes/loss, decode errors,
  late replies, and the UI-tree policy. It does not prove a logged-in SL session;
  use `assets_status` for actual readiness.

## Development and validation

Source changes are local on `codex/builder-reliability`. Automated tests use a
separate virtual environment, temporary state, synthetic transports and assets.
No live viewer requests, uploads, object mutations, restarts or configuration
switches were performed for this implementation. The active viewer remains
separate from the newly staged development executable.

The new native C++ compiles against the recorded 7.2.4 assets baseline. Use
`apply_viewer_extension.py` followed by `apply_assets_extension.py` for a fresh
baseline. `apply_builder_upgrade.py` upgrades only the exact recorded builder-v1
source and refuses unknown edits. See the adjacent native build provenance JSON.

Isolated tests cover frame bounds/recovery, raw tree guard, generation/lease
checks, batched UI reads, surface argument validation, executor stop/cleanup,
asset request recovery and MCP compatibility. The final isolated Python suite passed **208 tests**. A fresh offline wheel
installation initialized with **84 workflow tools** and confirmed no viewer
contact or startup. The consumer focused suite passed **26 tests**, maintained
outside this repository. Native compilation and portable staging succeeded;
startup and live behavior of the new native code remain unverified.
See [build hashes and provenance](../viewer-extension/builder-reliability-build.json).

Still pending in the separately launched development viewer:

1. Large inventory/tree queries: confirm responsiveness, truncation and subsequent
   ping; compare 1 vs 20 controls without screenshots and inspect duplicate editors.
2. Compiler row readback after one valid and one invalid synthetic script, with
   save/reopen and independent in-world execution evidence.
3. Disposable owned prims: select exact roots, link, unlink, expected-root/order
   checks, changed-selection rejection, expiry, permissions and confirmation preference.
4. One disposable face: color/UV/glow/fullbright, local vs simulator readback,
   changed-entry rejection, PBR preservation, permission and session changes.
5. Synthetic zero-cost asset upload, inventory reconciliation and delivery from
   the consumer. Existing mocks are not upload/catalog acceptance.

The previous [builder live record](BUILDER_VALIDATION.md) applies to the earlier
script/read-only inspection build, not these new operations.
