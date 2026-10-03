# Background UI — local builder.3

Agents can inspect Firestorm without taking desktop focus or moving the mouse.
This build adds a bounded structural UI scene, a numbered schematic, and scoped
captures from the next normal viewer render frame. It uses the existing LEAP
connection. No computer-use plugin, desktop screenshot service, telemetry or
additional login is required.

## What background means

| Operation | Viewer behind another app | Viewer minimized |
| --- | --- | --- |
| Semantic object, script, inventory reads | Available while the event loop runs | Available while the event loop runs |
| Scoped scene / structural visualization | Available | Available; layout may reflect the last window size |
| Fresh rendered UI pixels | Available if normal rendering continues | Explicit `unavailable`; no automatic restore |
| Authorized native builder/script/asset writes | Use the existing guarded semantic tools | Depend on their normal session, permission and state checks |
| Arbitrary buttons, typing, file pickers | Excluded from background-only plans | Excluded |

Background work still shares the viewer's selection, editors and world session.
It is not an independent avatar or isolated copy of the user's UI. Human changes
invalidate observations and guarded plans. A lease coordinates MCP clients; it
does not prevent human input. Existing task authorization is still required for
writes, spending and communication.

## Perception contract

All operations are schema version 1 and capability-gated by live discovery.

- `background_status()` reports native window/render state and the executor's
  explicit allowed routes. `app_has_focus` is viewer state, not an OS focus lock.
- `ui_scene(under, limit=80, max_depth=3)` visits at most 1,024 nodes / 8 ms and
  returns at most 128 visible controls / 64 KiB of path text. Includes names,
  coarse roles, rects, enabled/visible state and a content revision. Editable
  values are excluded. Hidden subtrees are skipped. Depth limits and truncation
  mean incomplete coverage; narrow the path. Paths can be ambiguous and are not
  stable handles for writes. Exact `ui_read` retains ambiguity rejection.
- `ui_visualize(under, ...)` returns an MCP PNG image, a saved file/hash, and a
  numbered exact-path legend. It is visibly labelled **structural map**, not a
  screenshot. No editable values are included. It remains useful when rendering
  is suspended.
- `ui_capture(path, max_size=1280)` requests the next normally rendered frame,
  crops to the control's visible window intersection, and returns an MCP PNG.
  Requires an owned bounded lease. The path and weak native view handle must
  still resolve to the same instance and geometry at capture time. Other viewer
  panels may occlude this area; this is not isolated panel rendering. It does
  not read other applications, activate windows, move the cursor, force redraw,
  change render settings, invoke snapshot animation, or restore minimized UI.
- `ui_wait_change(under, previous_revision, timeout=5, ...)` polls a bounded
  scene at 250 ms intervals for up to ten seconds. It compares structural state,
  not editable values or pixels. Keep the same scope/limit/depth when comparing.
  Desktop focus changes alone do not change the revision. A timeout is a bounded
  observation, not proof of overall UI stability or task completion.

Native capture uses `FSMCPUI.requestCapture` / `captureResult`, with one pending
or unconsumed result at a time. Pending requests expire after five seconds;
completed results expire after ten seconds and are consumed on first retrieval.
Source crops are limited to 4,194,304 pixels, output edge to 1,600 pixels and PNG
to 4 MiB. No capture is retained as a fallback for a later request. Failures
report `unavailable` or a tool error; no screenshot or desktop-input fallback is
attempted. Lost replies are not replayed automatically.

The frame hook runs immediately before the normal swap. It saves/restores pixel
readback state and refuses unexpected framebuffer/pack-buffer bindings. Readback
and PNG encoding run on the viewer thread, so large captures can briefly delay a
frame. Prefer a small relevant panel and structural reads for routine work.
Fresh-frame evidence does not establish compiler success or simulator effects.

## One-session execution

```json
{"version":1,"calls":[
  {"tool":"background_status","arguments":{}},
  {"tool":"ui_scene","arguments":{"under":"/main_view/menu_stack","limit":40,"max_depth":2}},
  {"tool":"object_search","arguments":{"distance":32,"owned_only":true,"limit":20}}
]}
```

```text
python -m firestorm_mcp.executor plan.json --data-dir STATE --viewer-dir VIEWER --background-only
```

The executor validates every step before dispatch, discovers the connection,
owns/renews a bounded lease and releases it in cleanup. It refuses arbitrary
viewer calls, legacy snapshots, camera operations, input, panel opening and OS
file pickers. This is an executor policy, not a sandbox for all other MCP clients.
Writes additionally require `--allow-writes` and task authority. Use explicit
native operations for script files, link/surface plans and assets. Plans contain
literal arguments; dependent work needs a fresh observation before constructing
the next plan. Image tools return MCP image content to image-aware hosts; the
CLI prints the text/file metadata and does not inline image bytes.

## Research and implementation choice

The local Firestorm 7.2.4 source explicitly skips rendering when hidden/minimized
(`llviewerdisplay.cpp`, `display`). Its legacy `rawSnapshot` path changes cursor
and render state. A normal-frame tap avoids those effects and its synchronous
rerender path. A structural image handles the minimized case honestly.

[Firestorm source](https://github.com/FirestormViewer/phoenix-firestorm/blob/master/indra/newview/llviewerdisplay.cpp)
and [viewer snapshots](https://github.com/FirestormViewer/phoenix-firestorm/blob/master/indra/newview/llviewerwindow.cpp)
were compared with native Windows capture options.
[Windows Graphics Capture](https://learn.microsoft.com/en-us/windows/apps/develop/media-authoring-processing/screen-capture)
can acquire window frames but adds a platform capture dependency and does not
provide Firestorm control identities.
[PrintWindow](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-printwindow)
is synchronous and asks the target application to draw into a supplied context;
it is not a replacement for Firestorm's rendered UI tree or an assurance of
fresh OpenGL pixels. No external desktop-capture implementation was imported.

## Integration and validation

Use `scripts/apply_background_ui.py` to upgrade the recorded builder.2 source.
It validates the old UI hash, header and display anchors before any write. Fresh
and builder.1 installers include the same display hook. Installed binaries and
running profiles are never patched by these scripts. Direct-start bridge
configuration remains local installation configuration, outside source packages.

Automated tests use synthetic transports and temporary state. Native compilation
is distinct from live validation. Record live focus/cursor checks, pixel capture,
minimized structural access and lease cleanup separately; do not label simulator
mutations or uploads validated based on these UI observations.

### Recorded results, 2026-10-03

- 226 isolated tests passed, including malformed/oversized image rejection,
  capture refusal without fallback, lease enforcement, structural revisions,
  and background plan rejection before any dispatch.
- Fresh offline wheel installed and initialized 89 workflow tools with no live
  viewer contact, launch or lease.
- Windows x64 native build compiled and staged separately. See
  [native provenance](../viewer-extension/background-ui-build.json).
- Direct executable launch started the bridge; the viewer reached region-ready
  status. Native structure and fresh PNG capture passed while the viewer reported
  `app_has_focus:false`. OS foreground window and cursor position were unchanged
  around each of three reads; the owned lease was released afterward.
- Single-sample end-to-end timings: scene 123.88 ms, structural visualization
  150.30 ms, and fresh frame capture 991.86 ms. These are observations, not a
  general performance guarantee. The actual rendered PNG was visually inspected.
- Minimized live validation passed: native state reported minimized/inactive;
  scene returned 19 controls (80.91 ms), the structural PNG rendered (104.44 ms),
  and capture returned `unavailable/render_suspended` (359.13 ms). No window
  restore occurred; desktop foreground remained unchanged and the lease was
  released. Cursor position differed across the two structural-read samples,
  so those samples cannot establish cursor stability or attribute movement.
  The minimized capture-refusal sample preserved cursor position.
- New UI work does not validate link/unlink, material mutation, script
  compilation or uploads in-world. No such actions were performed by these tests.
