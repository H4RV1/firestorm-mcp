# Experimental native builder extension

The additional `FSMCPAssets` source in this directory has its own
[contract](../docs/ASSET_API.md), [build record](assets-build-baseline.json) and
[pending live acceptance](../docs/ASSET_ACCEPTANCE.md). The startup checks below
describe the earlier builder-only viewer, not the new assets build.

`fsmcpbuilder.cpp` adds three read-only LEAP operations: `getSelection`,
`getLinkset`, and `getFaces`. The standalone MCP already has typed wrappers.
This source was **compiled successfully on Windows** against the pinned release
below. The separate viewer started and passed real MCP checks: all three
operations discovered, ten empty-selection reads, and missing-object errors for
linkset/face lookups. In-world link numbers, actual faces and attachments remain
unverified. Stock Firestorm does not have these APIs.

Apply to a separate Firestorm source checkout, never an installed binary:

```powershell
python scripts/apply_viewer_extension.py C:/src/phoenix-firestorm --profile-name FirestormMCP --dry-run
python scripts/apply_viewer_extension.py C:/src/phoenix-firestorm --profile-name FirestormMCP
```

The installer validates all source anchors before writing, adds two CMake entries,
and registers the API just before LEAP child startup. Reapplication or unexpected
source versions fail explicitly. Review the resulting diff, then follow the
[official Windows build instructions](https://github.com/FirestormViewer/phoenix-firestorm/blob/master/doc/building_windows.md).
Use a distinct build/channel so the existing installation remains available.
Use the separate profile option too: channel names alone do not isolate user
settings. See [build and upgrade procedure](../docs/CUSTOM_VIEWER.md).

The source baseline is the `Firestorm_7.2.4` release branch. The Windows Release
build passed with zero warnings/errors at
`10bd3c9f930c76e1427ddd4ecece6cdf36b4406d`. Source anchors were also inspected on master at
`0acb5f440a5d6dad4383d429442a262c068b7a37`; that master version was not built.

The hook runs on the viewer event thread, reads cached state, and performs no
network requests, inventory mutations, script saves or object changes. Missing
objects return errors. Missing names remain undefined. Faces are texture-entry
indices, not mesh triangle indices; serialized texture entries are not resolved
PBR materials. Link numbers follow Firestorm's current child order with explicit
flags that complete simulator agreement has not been established.

Required acceptance: build the viewer; discover the three APIs through MCP;
compare unlinked/root/child numbering against LSL; inspect multi-face prims and
mesh slots; check attachments, unloaded/deleted objects and partial properties;
verify calls remain bounded and do not alter selection. No native acceptance
result is implied by Python tests.
