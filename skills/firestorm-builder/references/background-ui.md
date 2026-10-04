# Observe Firestorm without taking desktop control

Discover `background_status` and check native capabilities first. Do not restart
a shared viewer just because these endpoints are absent. Keep one bounded lease
for capture/wait/action work and release it in cleanup.

1. Use `ui_task` / `ui_map` to identify the relevant panel, then `ui_scene` on a
   narrow runtime path. Names/geometry come from live UI; editable values are
   excluded. Truncation and depth limits are incomplete coverage.
2. Use `ui_visualize` when a numbered structural image helps navigate. It is a
   schematic, not pixel evidence, and works when the viewer is minimized.
3. Use `ui_capture` only when actual rendered pixels matter. It waits for the
   next normal frame, leaves desktop focus/cursor alone, and may include another
   viewer panel covering the requested area. It refuses suspended rendering.
   Do not restore/foreground the viewer or use computer input as an automatic
   fallback. Narrow overly large crops instead.
4. Use `ui_wait_change` with the same scope/limit/depth and prior scene revision
   for layout changes. It does not compare editable values, compilation or world
   effects. Read exact controls/rows or semantic results for those checks.

Run saved plans with `--background-only`; it rejects unsafe tool routes before
starting. Semantic writes still need task authority and `--allow-writes`.
Arbitrary control callbacks can open OS dialogs, so they are excluded along with
typing, mouse input, file pickers, camera changes and legacy snapshots. This
does not isolate the viewer's selection/world state from the human; reinspect
after their changes and stop if a target or bridge generation changes.

The native frame request expires after five seconds. Builder.4 returns small
metadata followed by ordered 8 KiB `captureChunk` replies; prefer `ui_capture`
to assemble/validate them and emit an MCP image. It expires after 30 seconds
and is consumed at the final chunk. Older viewers use one PNG reply and ten-second
expiry; an older Python wrapper cannot consume the new chunk contract.
On a lost reply, report unavailable/unknown
instead of claiming a cached image is fresh. Keep captures private and distinguish
structural, rendered, compiler and simulator evidence.

Before capture, check lease expiry and renew in the same MCP session when needed.
Prefer `ui_capture` over manual `captureChunk` loops: the wrapper validates the
transfer and returns image content without raw base64 in agent context. A lost
reply or expired result stays unknown; do not replay a capture automatically.
Exact camera pose is unavailable, so inspect composition before labelling views.
