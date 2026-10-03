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

The native frame request expires after five seconds. A completed PNG is consumed
once and expires after ten seconds. On a lost reply, report unavailable/unknown
instead of claiming a cached image is fresh. Keep captures private and distinguish
structural, rendered, compiler and simulator evidence.
