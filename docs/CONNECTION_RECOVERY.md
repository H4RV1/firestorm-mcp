# Builder.4 capture transport and helper recovery

## Incident evidence and limits

On 2026-10-04 UTC the viewer remained alive while its LEAP helper disappeared
and `connection.json` was absent. Agent-side MCP servers were still running.
The last successful operation in the available task record was a large
`FSMCPUI.captureResult` reply; the next call found no connection metadata.
The active viewer log did not contain this helper's exit reason. Therefore the
exact exception/exit trigger is **unconfirmed**. The last operation is a lead,
not proof that the screenshot caused the exit.

Upstream `LLProcess::WritePipeImpl` documents a Windows APR nonblocking-pipe
problem that can duplicate written chunks. The Python transport has a bounded
repair for that pattern, but a monolithic PNG puts substantially more data
through it. The changes below address that transport exposure and the confirmed
recovery/diagnostic gaps. They are not a claim to have reproduced this exact exit.

## Capture contract

`requestCapture` still waits for the next normal render frame, with no desktop
input, activation, forced redraw or minimized-window restore. Pending expiry is
five seconds. One result is retained, at most 4 MiB PNG and 1600 pixels per edge.

In the new native build, `captureResult` returns state and metadata instead of
embedding PNG bytes. Ready metadata includes `png_transfer:"chunks_v1"` and
`png_size`. Retrieve `captureChunk` with the same `capture_id` and initial
`offset:0`. Each response contains `capture_id`, `offset`, `next_offset`, `done`
and `data` (LLSD binary, JSON `{"$binary_base64":"..."}`), at most 8192 bytes.
Supply the exact returned `next_offset` for the next call. The last chunk consumes
the result. Repeated/out-of-order offsets are rejected. The result expires 30
seconds after rendering even if it is being transferred.

The updated `ui_capture` wrapper performs this exchange and validates the full
PNG before saving/displaying it. Its transfer deadline is 25 seconds. Loss,
identity mismatch, malformed chunks or a reconnect stop the operation; nothing
is replayed. Every native capture operation, including chunk consumption, needs
the current control lease. Old viewers remain supported by the wrapper's legacy
binary-reply branch; that branch does not gain the new transport bounds.

Use the matching updated Python server with this viewer. Old raw clients must
implement the chunk contract; an old wrapper expecting `result.png` will fail.
Prefer `ui_capture` for images over embedding base64 through `viewer_call`.

## Helper supervision

Startup supervises the configured command containing the `firestorm_mcp/leap_entry.py`
entrypoint (both path separators accepted). Other configured LEAP commands keep
their existing startup behavior. A native two-second event timer keeps a weak
reference to the owned helper. A live helper is never killed/replaced. After its
exit, at most three restarts are attempted per viewer run, after approximately
2, 4 and 8 seconds respectively. The timer stops at viewer shutdown or exhaustion.
It runs from the event loop, not the renderer, so minimization does not require
restoring a window. A stuck but still-live helper is not force-restarted.

Each restart uses the same configured command and creates a fresh bridge
generation. Old control leases and descriptors are invalidated by existing
client checks. No request queue or workflow is replayed. Preserve the existing
asset journal and request IDs; an upload or script save already sent can have an
unknown outcome and must be inspected before any retry.

## Persistent diagnostics

Before normal helper cleanup, `runtime/last-disconnect.json` records a timestamp,
generation, exception type, unknown pending-result count, malformed-frame and
duplicate-block counters, and last API/operation names. It excludes tokens,
arguments, pixel data, chat and scripts. `connection_status` exposes this bounded
record as historical evidence when the bridge cannot be reached. It does not
label the last operation as the cause. Abrupt OS termination or startup failure
before the bridge initializes may still leave no report.

## Build and validation

Apply `scripts/apply_capture_transport.py CHECKOUT --dry-run`, then apply without
`--dry-run`, after the builder/asset/background hooks. It validates the recorded
source hashes; exact current managed UI sources are also accepted for a fresh
integration. Existing custom edits are refused. Build and stage into a new folder.
The earlier face and inventory crash fixes remain separate and must be retained.

Isolated tests cover exact multichunk reconstruction, rejection without partial
image/replay, disconnect diagnostics, source-patch atomic validation, lease
requirements and old capture compatibility. `scripts/verify_native_leap_watch.py`
compiles the actual watcher class with synthetic child lifetimes, checking no
duplicate launch, backoff, three-attempt budget and viewer-shutdown handling.
No automated test launches, stops or contacts a live viewer.

The separate Windows build and offline package results are recorded in
[transport-build.json](../viewer-extension/transport-build.json). Live large-image
transfer, throughput and helper-exit/reconnect acceptance are **pending**. The
running older viewer was preserved. These native changes cannot be retrofitted
into its existing process; activating them requires a later authorized switch.
