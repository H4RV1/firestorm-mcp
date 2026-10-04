# Reliability audit against the October 4 improvement report

This audit maps the engineering report's sixteen sections to the current
builder.5 development source. It uses source review and isolated synthetic
tests. No viewer, account, simulator, paid upload or consumer project was used.
The report's product assets, identifiers and local source paths are excluded.

The initial checkout was the older asset integration. The changes were rebased
onto the newer background-UI/file-upload development baseline before final
validation. Merge conflicts were reviewed by separate transport, workflow and
skill agents, then checked by the coordinating agent. Existing capture and
helper-recovery contracts were preserved.

## Implemented safeguards

- Reopening a registered External Edit file supersedes its previous session.
  Registration and writes share a canonical-path exclusive lock; another
  process's lock is never stolen. Session lists identify superseded, missing,
  replaced and ended sessions. These are local registrations, not simulator item
  or editor-instance identities.
- Script writes persist a local intent receipt before replacement. Receipts
  identify the write and before/requested/observed hashes. A persistence failure
  after replacement reports `external_write_outcome_unknown` as a structured MCP
  tool error. A local successful write still has `compile_verified:false` and
  `simulator_save_verified:false`.
  The executor preserves structured failure receipts and their uncertainty
  instead of discarding them when stopping a plan.
- Asset submit/job/request replies must match the retained request identity and
  fingerprint before journal updates. Known job cancellation verifies that
  identity before dispatch. Reconciliation intents and original-request bindings
  survive helper restart; polling never replays a mutation.
- Native lease refusals fail acquisition. Failed synchronization restores local
  ownership and attempts native restoration; a failed renewal invalidates its
  cache so restoration is actually sent. An unknown native restoration remains
  uncertain. Status exposes remaining seconds and same-client ownership.
- Connection identity includes bridge generation. Cached descriptors are cleared
  on changes, and the identity is checked again between reply inference and
  dispatch. Existing two-second operation queue rejection, lease invalidation,
  bounded recovery and transport budgets remain intact. Refresh server capability
  descriptions explicitly after a generation change.
- Selection preflight canonicalizes equivalent UUID forms, including typed UUID
  values in expected identities, and rejects equivalent duplicate roots and null
  identities before dispatch. The existing native exact-selection guard remains;
  this does not add a human-input revision cursor.
- Local asset inspection reports declared glTF node frames, hierarchy, accessor
  bounds and primitive/material indices. Nonidentity node transforms warn about
  importer baking. Native axes, pivots and importer mapping remain unverified.
  Windows attachment-style paths are normalized on Windows; upload preparation
  still rejects relative and network paths.
- Repository and installed builder skills provide concise tool routing,
  same-session renewal, scoped reads, source-bound evidence and no-replay guidance.

## Report coverage and remaining acceptance

| Report section | Current coverage | Remaining work |
| --- | --- | --- |
| 1. Stable script identity | Supersession, shared locking, explicit local state and write receipts added | Native object/item/editor binding, permission-aware simulator source and semantic reopen |
| 2. Compile/save/runtime | Old compiler rows explicitly excluded as proof; local write uncertainty structured | Source-bound native compile/save jobs, diagnostics, installed revision and runtime signals |
| 3. Complete object readback | Existing cache linkset/faces preserve incomplete evidence | Complete transforms, lights/projectors, physics, material overrides and simulator confirmation |
| 4. Selection identity | Canonical UUID preflight and duplicate/null rejection; exact native comparison retained | Native revision cursor, explicit guarded clear and property-readiness completion |
| 5. Inventory readiness | Existing task inventory fetch verifies typed identities/serial; native empty-tree guard retained | Semantic item activation tied to object/inventory/editor revision |
| 6. Background UI | Existing bounded native scene/control/row tools and background executor preserved | Stable action IDs, semantic inventory activation and human-input telemetry |
| 7. Actual camera pose | Guidance separates requested pose from observed composition | Native actual pose/override readback, tolerances and interruption signals |
| 8. Capture transfer | Existing `ui_capture` aggregates and validates chunks to ImageContent/local artifact | Larger negotiated chunks, immutable resume-safe ranges, native checksum, discard and pose receipt |
| 9. Complete surface edits | Existing CAS legacy surface plans preserved | Texture/specular/alpha/PBR/light edits, preservation masks and ordered heterogeneous commits |
| 10. Transform transactions | No unsupported transform mutation advertised | Native guarded root/child batch transactions and authoritative readback |
| 11. Import frame audit | Declared source frame/bounds/material metadata added | Importer-derived baking/pivot/LOD mapping and post-upload source-to-prim identity |
| 12. Asset identities | Existing typed inventory and upload receipts; host-aware input paths added | Stable snapshot pagination, revision queries and generic ordered manifests |
| 13. Recovery/uncertainty | Existing bounded native helper supervisor preserved; generation checks and durable reconciliation hardened | Live helper-exit acceptance and durable status for non-asset world mutations |
| 14. Human collaboration | Remaining-time metadata, renewal guidance and sync rollback added; executor already renews | Human-input cursors, domain conflicts and resumable verified checkpoints |
| 15. Prefab lifecycle | No product-specific lifecycle or unsolicited world mutation added | Generic take/store/rez identity jobs, permission audit and lifecycle receipts |
| 16. Costs/performance | Source/cache/compiler/render evidence kept separate | Authoritative LI/script costs, render/GPU metadata and repeatable multi-viewer performance measurements |

The native backlog is not implemented or certified by these Python fixes.
Existing native build records describe earlier source/builds; they do not certify
new binary behavior. Activating a development viewer and live mutations require
their own authorized acceptance run.

## Validation

Final validation on Windows/Python 3.13: **316 tests passed** in a separate Python
environment with temporary `FIRESTORM_MCP_HOME`. Both repository and installed
builder skill format checks passed. The catalog was regenerated offline;
whitespace/conflict-marker checks passed. A freshly built wheel installed from a
local wheelhouse into a fresh environment passed the offline MCP probe with 93
workflow tools and no viewer started, input sent or lease acquired. The source
archive passed its allowlist and private-path/credential scan. These checks do not
certify live native behavior or a speed improvement.

Skill scenarios reviewed: duplicate script names cannot select a target;
stale successful compiler rows cannot verify new source; human selection changes
require fresh inspection; nearing expiry requires same-session renewal; absent
native capabilities produce a gap rather than guessed raw calls; capture failure
does not authorize foreground input or mutation replay. This is instruction
review, not a live speed benchmark.
