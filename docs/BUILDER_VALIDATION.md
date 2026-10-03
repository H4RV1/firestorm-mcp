# Live builder acceptance — 2026-09-26

Script editing and native inspection passed the checks below in a logged-in
Second Life session on Windows x64. This is one owned, modifiable 17-prim
linkset, not certification of every object type or viewer version.

## Environment and authority

- MCP implementation: `eeb155fa397ca8ad2f34f0de4eb9ea580034eba7`,
  `0.3.0a3+builder.1`, Python 3.13.9, real persistent MCP stdio client.
- Separate builder-only viewer: Firestorm-MCP-Development 7.2.4.1, built from
  `10bd3c9f930c76e1427ddd4ecece6cdf36b4406d` with `FSMCPBuilder`.
- Executable SHA-256:
  `1d7fd15e05a44f2444930f1c4756c9c2417fbe128ed2f1e3361a5a14841d36f7`.
- The owner authorized the fixture and a viewer restart. Mutations used the same
  MCP client with a renewable 180-second control lease, released in cleanup.
- A separate synthetic diagnostic script used only read operations and
  `llOwnerSay`. Existing scripts were not edited. Raw source/session records,
  object identifiers, chat and captures are private and excluded from this repo.

## Observed results

| Check | Evidence / result |
| --- | --- |
| External Edit registration | Inventory and in-object editors each registered a temporary source file; `script_sessions` and `script_read` worked through MCP. |
| UTF-8 source | A comment containing `café Ω` matched the local readback and viewer editor text exactly. |
| Conflict handling | A deliberately stale `expected_sha256` was rejected; the source hash remained unchanged. |
| Backup fidelity | Backup bytes matched the pre-write source for the inventory write and in-object error test. |
| Compile failure | Writing `integer count = ;` through `script_write` caused the viewer to show `(6, 24) : ERROR : Syntax error`. File-write success was not mistaken for compiler success. |
| Compile/save correction | Corrected source produced **Compile successful!** and **Save complete.**; the new marker ran in-world and emitted a complete diagnostic result. |
| Persisted source | Closing and reopening the in-object editor loaded the corrected source exactly, including UTF-8 text. |
| Linkset numbering | All 17 `(link number, object UUID)` pairs matched `llGetLinkKey` results. A child UUID resolved to the same root/linkset as a root lookup. |
| Face enumeration | Every prim's `texture_entry_count` and `object_faces` length matched `llGetLinkNumberOfSides`: 28 total faces, with per-prim counts of 1, 2, 3 and 5. Every returned face was available and indexed contiguously from zero. |
| Selected face | Native selection reported face 2 of a five-face child; the Build panel and `builder_selection_summary` both displayed `Faces: 2`. |
| Texture-entry values | That face's legacy scale (~0.85377 on both axes), zero offsets/rotation/glow, fullbright off and zero transparency agreed with the Blinn-Phong panel. This is a spot check, not full material validation. |
| Read-only behavior | Repeated native reads preserved selection, including the selected face. All 17 cached prim positions remained unchanged. |
| Cleanup | The diagnostic was stopped, its stopped state verified after reopening, and its editor closed. Registered temporary files became inactive. The lease was released and the viewer remained logged in. |

Ten sequential populated `object_linkset` calls through the persistent client
took 49.23–68.01 ms (median 50.85 ms). This includes the local test-client/MCP/
bridge round trip; it excludes model reasoning and script compilation. It is
a small local sample, not a latency guarantee.

The fixture already had animated effects. Some glow/alpha/emissive values changed
between reads; material snapshots are not atomic. No material or transform
writes were issued by the diagnostic. The inventory copy and stopped in-object
diagnostic were retained for owner review.

## Reproduce the core comparison

With explicit authority, register a disposable script through External Edit.
Read its hash and write a synthetic script that emits a unique marker, the result
of `llGetNumberOfPrims()`, and one row per link containing `llGetLinkKey(link)`
and `llGetLinkNumberOfSides(link)`. Use owner-only output. Compare these rows
with `object_linkset` and `object_faces`; do not infer correctness from matching
counts alone. This linked-object probe is not an unlinked-prim numbering test.

Write a deliberate syntax error using the current hash, observe the compiler
failure, read again, and correct it using the new hash and a new output marker.
Require compiler/save UI evidence and the new in-world marker. Close/reopen the
editor and compare the entire source. Stop the diagnostic, verify that state,
and release the lease in cleanup.

## Reliability finding and remaining scope

A broad UI-tree query under `Floater View`, while a large inventory was open,
produced a malformed approximately 80 MB LEAP reply and disconnected the helper.
The viewer remained running. An owner-authorized restart restored the bridge;
the successful acceptance checks then used exact editor/Build/chat subtrees.
`max_depth` and paging filter results after enumeration and do not bound native
traversal or reply size. Broad-query transport robustness remains unresolved.

Unlinked prim numbering, attachments, deleted/unloaded objects, permission-denied
objects, relinking/streaming completeness, systematic primitive-versus-mesh
coverage, and other OS/viewer builds still need live validation. A transient
`properties_received:false` / `name:null` was observed immediately after changing
selection, but controlled partial-property acceptance was not performed.
Resolved PBR assets and a native asynchronous compile/save/status API remain
outside the implemented scope.

Per-call flags stay conservative: `compile_verified:false`,
`simulator_save_verified:false`, `server_link_numbers_verified:false` and
`complete_verified:false`. The tools do not perform the independent acceptance
checks above on each request. Passing this fixture does not change that contract.
