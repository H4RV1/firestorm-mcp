# Asset API verification and pending acceptance

## Completed without contacting a simulator

The final Windows verification run includes **167 Python tests**, **30 shared
native policy assertions** and **9 real-codec fixture assertions**. Fresh wheel
and source installations passed using a local dependency wheelhouse with pip's
network index disabled; the isolated MCP probes exposed all 72 workflow tools.
The separate viewer compiled with zero compiler errors/warnings and was staged
without launching it. The [build record](../viewer-extension/assets-build-baseline.json)
pins its revision, channel, profile and executable hash. These are local checks;
they do not establish upstream platform CI or live simulator acceptance.

- Separate Windows x64 Firestorm 7.2.4 source build, using the pinned baseline
  and `MCP-Assets-Development` channel / `FirestormMCPAssets` profile.
- Shared native policy tests: session/account/grid/generation mismatch, missing
  or nonzero quotes, changing benefits, incomplete inventory, no-copy/group/foreign
  ownership refusal, and cancellation after submission staying unknown.
- Shared native Vorbis worker: real synthetic mono fixture accepted; stereo,
  wrong sample rate, empty/oversized/truncated/chained/trailing/corrupt data refused.
- Python fake-transport/journal tests: changed body and expected identity,
  duplicate requests, lost acknowledgement, native job eviction, restart recovery,
  actual returned folder IDs, retained acknowledged IDs, read-only reconciliation,
  cancellation observation, structured errors, lease expiry/conflict/forgery,
  chunk offset/hash/owner/size/count/TTL, durable journal capacity, and stock-viewer
  refusal. Existing transport, script/builder and MCP compatibility tests remain.
- Patch installer verifies all anchors before writes, refuses repeated patching,
  and includes the typed login-benefit and human-dialog-response hooks.

These checks exercise real shared policy/codec code and simulated protocol
boundaries. They **do not prove** a simulator's quote format, inventory response
shape, delivery behavior or live timing. The development viewer must still pass
startup/login acceptance. The previous running builder-only viewer was queried
read-only under a bounded released lease; it exposed 19 APIs/97 operations and
no FSMCPAssets endpoint. It was not replaced, closed, or used for mutations.

## Smallest live acceptance, requiring authorization

Run this only after the desktop owner authorizes a viewer restart and the listed
synthetic inventory/world actions. Do not use prepared production songs.

1. Close the previous viewer normally. Start the separately staged assets build
   through the launcher with a separate bridge-state directory. Log in through
   Firestorm. No consumer credentials are supplied. Negotiate contract v1 and
   require the expected Agni/Aditi grid, actual ready state and required caps.
2. Attach the read-only example with a 60-second lease. Browse one small owned
   folder and compare names/types/permissions to the viewer. Confirm incomplete
   capability replies are errors. Release and detach; the avatar must stay online.
3. With a separate explicit mutation grant, create one uniquely named synthetic
   folder under the chosen parent. Record requested and returned UUIDs and verify
   the fresh parent response. Create a second empty test folder and move **only
   that** folder to Trash via its creation receipt; confirm both locations.
4. If the account advertises a verified zero sound fee, submit one synthetic
   0.25-second mono 44.1 kHz Vorbis clip, under 8 MiB, with a unique marker and
   `expected_cost:0`. Confirm the metadata response explicitly quotes zero before
   bytes are sent. If no quote exists, stop: the implementation must refuse it.
   Compare confirmed item/asset IDs, name and description with fresh inventory.
   Do not approve any paid notification. A paid/unknown account is a refusal test.
5. Create a tiny UTF-8 notecard with a known last character and no trailing blank
   line. Verify it is populated and readable in the viewer. Explicitly update the
   same verified item using a new request ID; confirm the new asset UUID.
6. Exercise duplicate request ID with unchanged body (no duplicate item), then a
   changed body (request_conflict). During a separate synthetic attempt, stop the
   consumer after submission; reattach and inspect/reconcile instead of resending.
   A missing item must remain unknown. Confirm an empty acknowledged notecard is
   not reported as a completed content upload.
7. On one owned modifiable synthetic prim with an owner-only test script, inspect
   fresh properties/task inventory. Deliver the copyable test card; confirm its
   exact asset and metadata arrived and the source remains. Test no-copy refusal
   using an explicitly authorized fixture without sending it. Observe only this
   prim's owner-chat/dialog; validate index/label response and reject expired or
   human-answered dialogs. A touch is dispatch evidence, not business success.
8. Observe region crossing, logout, bridge restart and capability refresh during
   a queued/preflight synthetic operation. New writes must refuse stale identity;
   already-sent operations remain unknown unless independently confirmed. Verify
   lease expiry/conflict and release do not log out the viewer.

Leave the test assets for inspection unless deletion is separately authorized.
A consumer's station/catalog parser and end-to-end business success require a
separate acceptance in that consumer project. This repository cannot certify it.

## Remaining engineering limits

- Only the pinned Windows x64 build has been compiled here. Other platforms and
  future Firestorm baselines need build and live validation.
- Strict pre-upload quote behavior is intentionally conservative; some grid
  capability responses may omit price and therefore be unusable through this API.
- Task inventory requires the HTTPS capability; no legacy cached/UDP fallback
  is presented as fresh evidence.
- No simultaneous atomic lock spans human actions, server inventory and object
  properties. Fresh snapshots and matching receipts reduce uncertainty; they do
  not provide a simulator transaction or exactly-once crash guarantee.
- Full-folder results are bounded, not paginated. Oversized results fail closed.
  Search and display paths remain explicitly cached/incomplete.
