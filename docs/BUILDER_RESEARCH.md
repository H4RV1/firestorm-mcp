# Firestorm builder integration research

Research date: 2026-09-26. This is a development extension of
[AochiToxx/firestorm-mcp](https://github.com/AochiToxx/firestorm-mcp), imported at
`a9ec850ffa7f63762d30d361181e4d6429b28a39` under its MIT license.
The upstream license and attribution are retained.

## Existing projects assessed

| Project | What it provides | Decision |
| --- | --- | --- |
| [Firestorm MCP](https://github.com/AochiToxx/firestorm-mcp) | Standalone Python MCP and viewer-owned LEAP bridge; Windows-tested against 7.2.4.80712; inventory, UI, camera, mesh previews; explicitly incomplete script/face lifecycle | Reuse this base and extend it |
| [MikoStorm](https://github.com/DDynamic-Evolution/MikoStorm) | Firestorm fork with an embedded HTTP MCP; documented tools cover navigation, chat, inventory and notecards | Useful precedent, but switching the entire viewer does not provide the requested complete builder suite |
| [opensim-metaverse2mcp](https://github.com/opensim-stack/opensim-metaverse2mcp) | libremetaverse-based bot with its own login/session | Different architecture from controlling the user's running viewer |
| [second-life-mcp-server](https://github.com/Treeeeeeeeeeeeee/second-life-mcp-server) | LSL reference information | Potential complementary coding reference, not live viewer control |
| [outleap](https://github.com/SaladDais/outleap) | Python LEAP client library | Protocol reference; its Firestorm warning predates the functioning integration observed here |

Searches used both web search and GitHub's repository search API. This is an assessment of found projects, not a claim that no others exist.

## Sources and runtime evidence

Firestorm master snapshot examined: `0acb5f440a5d6dad4383d429442a262c068b7a37`.
Release branch `Firestorm_7.2.4` resolved to `10bd3c9f930c76e1427ddd4ecece6cdf36b4406d`.
Source availability is distinct from runtime availability. Master has operations that the installed release does not expose.

The installed **7.2.4.80712** was restarted with the LEAP session launcher and successfully contacted by a real MCP stdio client. Live discovery returned **18 APIs / 94 operations**. The bundled [viewer descriptors](viewer-api-reference.json) and [tool catalog](TOOLS.md) document the available argument descriptions. Use `capabilities_refresh` and `viewer_api_inspect` against the current session before calling unfamiliar operations.

Twenty sequential live bridge + LEAP event-loop pings: median **50.057 ms**, minimum **34.021 ms**, maximum **51.311 ms**. These numbers exclude model thinking, MCP-host scheduling, simulator round trips, asset loading and script compilation. They are one local sample, not an SLA. No world/inventory mutation was sent during this check.

The separate custom viewer built with zero warnings/errors and started with its
own `FirestormMCP` profile. At its login screen, the three native operations were
discovered. Ten empty-selection MCP calls had a median **83.713 ms**; null-object
linkset and face requests returned the expected errors. Twenty bridge pings had
a median **85.472 ms**. These are different runtime conditions, not a controlled
speed comparison with the stock session. No in-world link/face acceptance or
script compile/save test has yet passed.

## Capability map

| Need | Current route | Limit / next hook |
| --- | --- | --- |
| API discovery | LEAP `getAPIs` / `getAPI`; `viewer_api_inspect` | Discover again after reconnect/login/version changes |
| Inventory metadata and search | `LLInventory` | Does not read script asset bytes or object contents |
| Nearby prims | `LLAgent.getNearbyObjectsList` | Loaded objects only; does not return complete properties or linksets |
| Movement, touch, camera, animation | `LLAgent` operations | Dispatched is not proof of simulator completion |
| UI state and actions | `LLWindow`, `UI`, `LLFloaterReg` | UI fallback; path and visibility must be verified |
| Read/edit scripts | New `script_sessions`, `script_read`, `script_write`; Firestorm External Edit file watcher | Script must be open and explicitly registered. Readback is local-file evidence. No compile acknowledgement yet |
| Selected objects/faces | Compiled `FSMCPBuilder.getSelection` hook | Empty-selection startup check passed; populated in-world selection still unverified |
| Link numbers | Compiled `FSMCPBuilder.getLinkset` hook | Missing-object check passed; uses cached child order; completeness and server numbering remain unverified |
| Texture-entry face data | Compiled `FSMCPBuilder.getFaces` hook | Missing-object check passed; real prim/mesh faces unverified; not triangle indices or resolved PBR assets |
| Object inventory / script by UUID | Native asynchronous inventory + asset API still needed | Must enforce normal viewer permissions and wait for callbacks |
| Compile/save results, reset/start/stop | Native script lifecycle API still needed | Must return completion/job IDs and diagnostics, not infer success from a button click |
| Object transforms/material writes | Native validated write API still needed | Require object UUID, expected state and readback; no blanket arbitrary C++ execution |

## Relevant source locations

All links below are pinned to the inspected master snapshot:

- [LEAP startup](https://github.com/FirestormViewer/phoenix-firestorm/blob/0acb5f440a5d6dad4383d429442a262c068b7a37/indra/newview/llappviewer.cpp): launches helper processes after settings load.
- [Discovery and event subscriptions](https://github.com/FirestormViewer/phoenix-firestorm/blob/0acb5f440a5d6dad4383d429442a262c068b7a37/indra/llcommon/llleaplistener.cpp): enumerate APIs, inspect operations, subscribe and ping.
- [Agent API](https://github.com/FirestormViewer/phoenix-firestorm/blob/0acb5f440a5d6dad4383d429442a262c068b7a37/indra/newview/llagentlistener.cpp) and [inventory API](https://github.com/FirestormViewer/phoenix-firestorm/blob/0acb5f440a5d6dad4383d429442a262c068b7a37/indra/newview/llinventorylistener.cpp): existing semantic operations.
- [Script editor](https://github.com/FirestormViewer/phoenix-firestorm/blob/0acb5f440a5d6dad4383d429442a262c068b7a37/indra/newview/llpreviewscript.cpp): `openInExternalEditor`, `getTmpFileName`, `onExternalChange`, script save paths and compiler callbacks.
- [External editor launcher](https://github.com/FirestormViewer/phoenix-firestorm/blob/0acb5f440a5d6dad4383d429442a262c068b7a37/indra/newview/llexternaleditor.cpp): `%s` substitution and argument parsing.
- [File watcher](https://github.com/FirestormViewer/phoenix-firestorm/blob/0acb5f440a5d6dad4383d429442a262c068b7a37/indra/llcommon/lllivefile.cpp): compares whole-second mtime with `>`; script watcher interval is one second.
- [Build panel](https://github.com/FirestormViewer/phoenix-firestorm/blob/0acb5f440a5d6dad4383d429442a262c068b7a37/indra/newview/llfloatertools.cpp): selected face enumeration and viewer link-number calculation.
- [Selection manager](https://github.com/FirestormViewer/phoenix-firestorm/blob/0acb5f440a5d6dad4383d429442a262c068b7a37/indra/newview/llselectmgr.h), [viewer objects](https://github.com/FirestormViewer/phoenix-firestorm/blob/0acb5f440a5d6dad4383d429442a262c068b7a37/indra/newview/llviewerobject.h), [texture entries](https://github.com/FirestormViewer/phoenix-firestorm/blob/0acb5f440a5d6dad4383d429442a262c068b7a37/indra/llprimitive/lltextureentry.h): selection metadata, root/children, permissions and per-face properties.
- [Object inventory listener](https://github.com/FirestormViewer/phoenix-firestorm/blob/0acb5f440a5d6dad4383d429442a262c068b7a37/indra/newview/llvoinventorylistener.cpp): asynchronous object contents; despite its name, this is not an exposed LEAP API.

## Responsiveness and reliability design

Keep the persistent viewer-owned bridge and correlated requests. Avoid screenshots and full UI-tree scans when a semantic operation exists. Cache discovered schemas, not mutable object/script state. Preserve serialized state-changing workflows and bounded control leases. Keep timeouts bounded and do not retry writes whose outcome is unknown. Keep the connection loopback-only with a per-session token.

Script writes require a previous content hash, back up exact bytes, reject stale file/viewer identities, and replace the file atomically. The one-second file-watcher limit is accounted for without future-dating files. Cooperative locks serialize our writers; Firestorm/human edits do not share those locks, so a narrow external-writer race remains. Full atomic conflict detection belongs in the native script API.

## Next development milestone

The selected route is a separate custom viewer with a small compiled LEAP API,
plus the existing external MCP. See [build and update maintenance](CUSTOM_VIEWER.md).
The stock sidecar remains useful: `builder_selection_summary` reads only a
visible Build panel's displayed link/face label, and `viewer_runtime_identity`
fingerprints the executable on disk. Neither is native object access or injection.

Validate a synthetic unlinked prim, a multi-prim linkset, selected faces, mesh material slots and attachment roots in the compiled viewer. Compare link numbers and face counts against an owned in-world script. Then add permission-aware object inventory, script source retrieval, save/compile jobs and diagnostics. Only after that should direct transform/material/script-state writes be added. The current package is a working foundation, not full viewer coverage.

## Runtime injection alternative

Follow-up inspection of the installed 7.2.4.80712 executable found 488 exported
names, but none matching `LLSelectMgr`, `LLViewerObject`, `LLEventAPI`,
`LLEventPumps`, `gObjectList` or `LLAppViewer`. No PDB was present in the
installation root. This does not establish whether matching symbols can be
obtained elsewhere. The executable was inspected read-only; no injection was attempted.

Runtime DLL injection is technically a possible alternative to a custom build.
It would still need a version-specific way to locate the live viewer's internal
objects/functions and schedule access on the viewer thread. Compiling the native
hook as a DLL does not automatically provide those bindings. Loading another
copy of viewer libraries could create separate global registries instead of
accessing the viewer's existing state. Binary-specific integration must reject
unsupported builds; a release update can invalidate addresses and C++ layouts.

The existing [media plugin architecture](https://github.com/FirestormViewer/phoenix-firestorm/blob/10bd3c9f930c76e1427ddd4ecece6cdf36b4406d/indra/llplugin/llpluginprocessparent.cpp)
launches a separate process, so it is not an in-process object/selection extension
API. LEAP discovery enumerates already registered operations and event streams;
it cannot by itself add arbitrary C++ access to missing viewer internals.

For maintainable runtime updates, a small custom host extension could export a
versioned C interface and a viewer-thread command queue, with optional DLL logic
loaded after startup. This still requires an initial viewer build. Later module
updates could avoid rebuilds while they stay within that host interface; adding
new native capabilities or changing the ABI may require another build. Safe
module reload also requires stopping requests and unregistering callbacks before
unloading. Initialization should occur outside `DllMain`, following
[Microsoft's DLL guidance](https://learn.microsoft.com/en-us/windows/win32/dlls/dynamic-link-library-best-practices).

Recommendation: keep the existing external MCP/LEAP path as the main integration.
Treat stock-binary injection as an experiment whose compatibility and stability
must be proven, rather than a prerequisite for the working integration.
