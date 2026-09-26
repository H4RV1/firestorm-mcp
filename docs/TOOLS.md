# Tool reference

Generated from the current workflow definitions and historical Firestorm 7.2.4.80712 API discovery. Refresh the running viewer before relying on a dynamic operation. Counts are not test coverage.

56 workflow tools; 94 historical viewer operations.

## Workflow tools

| Tool | Description |
| --- | --- |
| `control_acquire` | Acquire a workflow control lease. Other clients can still read status/events. Renew before expiry and release in finally; human input remains possible. |
| `control_release` | Release this client's exclusive control lease. |
| `native_file_dialogs` | List recognized Windows Open-file dialogs owned by this Firestorm installation. English common dialogs only; unsupported layouts require manual selection. |
| `native_file_choose` | Select a file in a freshly discovered Windows Firestorm Open dialog. Checks ownership and filename; verify import afterward. Confirm which workflow opened it. Other platforms need manual selection. |
| `connection_status` | Check whether the local Firestorm LEAP helper is connected. Does not log in or change the viewer. |
| `capabilities_refresh` | Discover all APIs and operations exposed by this running viewer; refresh dynamic MCP tool discovery. |
| `viewer_api_inspect` | Read the live description and required arguments for an API or operation. Discover before calling unfamiliar operations. |
| `viewer_call` | Invoke any discovered viewer API operation. arguments can contain typed LLSD values: {$uuid: string}, {$uri: string}, {$binary_base64: string}. Read state after writes; timeouts must not be blindly retried. |
| `events_subscribe` | Subscribe to a named viewer event stream, such as StartupState or LLAutopilot. Events are bounded and remain local until read. |
| `events_unsubscribe` | Stop subscribing to a viewer event stream. |
| `events_read` | Read subscribed viewer events after a cursor. The dropped flag identifies buffer overflow; do not infer missing events. |
| `ui_find` | Search paths or basenames within a narrow live subtree. Whole-view/Floater View and recursive scans are rejected; prefer offline ui_map/ui_task then ui_read. max_depth and paging filter after enumeration, not its cost. |
| `ui_get_value` | Read the value of a specific discovered UI control. Use targeted paths to avoid unrelated chat or private fields. |
| `ui_click` | Click a visible, enabled control. A registered floater invokes a unique button callback; otherwise uses coordinates. observe_path returns before/after state. Verify the effect from readback. |
| `ui_set_text` | Replace text in a discovered edit control using viewer input, then read back its value. Does not press Enter. |
| `ui_select` | Select a visible enabled combobox item by actual value, when supported by the viewer, and compare selected-value readback. Older viewers require path-targeted ui_press_key with readback. |
| `ui_inspect` | Read a known UI path's geometry and enabled/visible state without opening or focusing it. Discover children with scoped ui_find. |
| `ui_press_key` | Focus a required visible, enabled path, press/release a key and read back state. Modifiers: CTL/ALT/SHIFT/MAC_CONTROL. Enter can commit forms. Human input and shortcuts can interfere; verify the result. |
| `ui_list_menus` | List viewer menu entries from this installation's XUI, filter by name/label/function. These describe menus, not guaranteed enabled actions. |
| `ui_invoke_menu` | Invoke an actual menu entry from installed XUI by exact name; unknown callback names are never dispatched. This may open a native file picker. |
| `floater_list` | List registered viewer floaters and their XUI files. |
| `floater_open` | Open a registered viewer floater and check its visibility. |
| `avatar_position` | Read avatar position/orientation from the viewer. |
| `avatar_walk_to` | Start walking to GLOBAL coordinates. Poll avatar_movement_status and verify position; this is not pathfinding success. |
| `avatar_movement_status` | Read autopilot progress and current avatar position. |
| `avatar_stop` | Cancel automatic movement and read its resulting state. |
| `world_objects` | List nearby objects as reported by the viewer. Availability depends on simulator interest and viewer loading. |
| `inventory_search` | Search a specific inventory folder recursively, returning item metadata. Does not rez, purchase or upload anything. |
| `setting_get` | Read a named viewer setting; default group is Global. |
| `setting_set` | Change a viewer setting and return before/after readback. Some settings persist across restarts. |
| `camera_set` | Set a fixed camera and focus in REGION coordinates. Viewport capture is needed to verify composition. |
| `camera_release` | Release scripted camera control. This returns to viewer camera behavior, not an exact saved manual camera pose. |
| `snapshot` | Capture Firestorm's rendered image and return an MCP image plus saved PNG and hash. Render evidence alone does not prove upload or visibility to others. |
| `capture_orbit` | Capture repeatable orbit views around a REGION-coordinate focus and save a manifest. Releases scripted camera in finally. Caller must identify whether the subject is local preview or a server asset. |
| `asset_inspect` | Inspect a local COLLADA/glTF/GLB/texture export and record its SHA256. This checks file metadata, not upload eligibility, LOD quality, land impact or in-world appearance. |
| `image_compare` | Compare two same-size images and save an absolute-difference PNG. Metrics do not establish semantic or material correctness. |
| `local_mesh_open` | Open Firestorm's Local Mesh panel. Its local replacements are visible only in this viewer and do not prove server upload. |
| `local_mesh_auto_reload` | Set local mesh automatic reload so Blender exports can refresh in the viewer. Returns the previous settings for restoration. |
| `mesh_upload_open` | Open the standard mesh upload preview workflow. Does not submit an upload or authorize an upload fee. |
| `mesh_preview_camera` | Drag the mesh uploader's preview camera; world camera stays unchanged. Fractions are bounded to -0.45..0.45 of the inspected rectangle. Positive vertical zooms in; zoom needs horizontal=0. Capture to verify. No exact pose readback or restoration. |
| `mesh_upload_status` | Read importer LOD files/counts, physics, dimensions, warnings, weights, displayed fee and visibility. Does not calculate or upload. Readback is non-atomic; quote freshness and file bytes remain unverified. |
| `local_mesh_status` | Read Local Mesh's selected item/object and displayed import log. This is local preview evidence, not a simulator upload. |
| `capture_manifest_read` | Read a saved capture manifest created by this server. |
| `builder_capabilities` | Report sidecar builder capabilities from live discovery. External-file editing requires External Edit registration. Complete object APIs are unavailable without a compatible native endpoint; runtime injection is not implemented. Discovery is not a live-effect test. |
| `builder_selection_summary` | Read the visible Build panel's displayed link number or selected face indices through stock LEAP. Leaves selection untouched. Hidden/disabled labels return unknown; no object UUID, full linkset or complete face metadata is inferred. |
| `viewer_runtime_identity` | Fingerprint the connected Windows viewer's executable on disk for build diagnostics. Does not inject, read process memory, or prove the running image matches the file. |
| `script_sessions` | List script files explicitly registered by Firestorm's External Edit button. Does not scan inventory or temporary directories. Active file is not proof that the editor is still open. |
| `script_read` | Read a registered script's UTF-8 source and SHA256 for conflict detection. This reads the external-editor file, not the simulator asset. |
| `script_write` | Write a registered script with a required prior SHA256 and backup. Requires a control lease. Firestorm may automatically compile/save to the simulator; this call verifies only the local file. Inspect compiler results before retrying. |
| `object_selection` | Read selected object UUIDs and selected texture-entry face indices using the native FSMCPBuilder extension. Stock Firestorm returns an explicit unsupported error. |
| `object_linkset` | Read a loaded object's linkset using native FSMCPBuilder. Link numbers follow the viewer's current child order; simulator completeness is not guaranteed. |
| `object_faces` | Read native FSMCPBuilder texture entries for one loaded prim: face indices, texture IDs, color and UV parameters. Does not claim mesh triangles are faces or resolve PBR assets. |
| `viewer_latency` | Measure 1-20 sequential bridge plus viewer event-loop ping round trips in milliseconds. No world mutation. Does not measure simulator, asset loading or script compile latency. |
| `ui_map` | Search a cached local map of installed XUI control IDs, labels and tooltips, without contacting the viewer. Narrow by document. Candidate paths need ui_read verification; custom skins and duplicate instances are not verified. |
| `ui_task` | List task IDs or retrieve a task guide and relevant source control IDs for scripts, Build, inventory, mesh previews or preferences. Does not open anything. Prefer listed semantic tools, then ui_read before UI input. |
| `ui_read` | Read 1-20 exact UI paths or ui_map IDs in one request, using targeted getInfo calls and a total viewer-wait budget. No tree scans or input. Values are opt-in, hidden values suppressed and long values truncated. Does not distinguish duplicate editor instances. |

## Viewer operations

| API | Operations |
| --- | --- |
| `GroupChat` | `leaveGroupChat`, `sendGroupIM`, `startGroupChat` |
| `LLAgent` | `getAgentScreenPos`, `getAnimationInfo`, `getAutoPilot`, `getGroups`, `getID`, `getNearbyAvatarsList`, `getNearbyObjectsList`, `getPosition`, `lookAt`, `playAnimation`, `removeCameraParams`, `requestSit`, `requestStand`, `requestTeleport`, `requestTouch`, `resetAxes`, `setAutoPilotTarget`, `setCameraParams`, `setFollowCamActive`, `startAutoPilot`, `startFollowPilot`, `stopAnimation`, `stopAutoPilot` |
| `LLAppViewer` | `forceQuit`, `requestQuit` |
| `LLAppearance` | `detachItems`, `getOutfitItems`, `getOutfitsList`, `wearItems`, `wearOutfit` |
| `LLCommandDispatcher` | `dispatch`, `enumerate` |
| `LLFloaterAbout` | `getInfo` |
| `LLFloaterReg` | `clickButton`, `getBuildMap`, `hideInstance`, `instanceVisible`, `showInstance`, `toggleInstance` |
| `LLGesture` | `getActiveGestures`, `isGesturePlaying`, `startGesture`, `stopGesture` |
| `LLInventory` | `collectDescendantsIf`, `getAssetTypeNames`, `getBasicFolderID`, `getDirectDescendants`, `getFolderTypeNames`, `getItemsInfo` |
| `LLNotifications` | `cancel`, `forward`, `ignore`, `listChannelNotifications`, `listChannels`, `requestAdd`, `respond` |
| `LLPipeline` | `disableAllRenderFeatures`, `disableAllRenderInfoDisplays`, `disableAllRenderTypes`, `enableAllRenderFeatures`, `enableAllRenderInfoDisplays`, `enableAllRenderTypes`, `hasRenderFeature`, `hasRenderInfoDisplay`, `hasRenderType`, `toggleRenderFeatures`, `toggleRenderInfoDisplays`, `toggleRenderTypes` |
| `LLStartUp` | `getStateTable`, `postStartupState` |
| `LLTeleportHandler` | `teleport` |
| `LLURLDispatcher` | `dispatch`, `dispatchFromTextEditor`, `dispatchRightClick` |
| `LLViewerControl` | `get`, `groups`, `set`, `toggle`, `vars` |
| `LLViewerWindow` | `requestReshape`, `saveSnapshot` |
| `LLWindow` | `getInfo`, `getPaths`, `keyDown`, `keyUp`, `mouseDown`, `mouseMove`, `mouseScroll`, `mouseUp` |
| `UI` | `call`, `getValue` |

See [exact input schemas](tool-catalog.json) and [viewer descriptors](viewer-api-reference.json).
