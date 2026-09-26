# Script editing through Firestorm

Start the viewer through `firestorm-mcp-launch --script-editor` (plus the normal
viewer and data-directory options). This adds an ExternalEditor command to the
launcher's session settings. It does not edit Firestorm's installed files.
The live setting was read back successfully on 7.2.4.80712.

1. Open a script you have permission to edit and click Firestorm's **Edit** /
   **External Edit** button. Firestorm exports a temporary file and launches our
   registration helper. Keep the viewer's script editor open.
2. Use `script_sessions` to find the registered file, then `script_read` to get
   the UTF-8 source and its `sha256`.
3. Acquire a control lease on the same MCP connection. Call `script_write` with
   `session_id`, the complete replacement `source`, and `expected_sha256` from
   the read. Release the lease in cleanup.
4. Inspect the viewer's compiler errors and save status before claiming success.
   Firestorm normally watches the exported file and automatically saves changes
   into Second Life. A file write is therefore an intentional script-save action.

The tool returns a backup path and a new hash, but deliberately returns
`compile_verified:false` and `simulator_save_verified:false`. It does not bypass
permissions or read arbitrary script assets. The temporary basename contains a
hash of object/item IDs; those IDs cannot be recovered and are reported as unknown.
No temporary directory scan is performed: only registered files are listed.

Normal writes may wait up to roughly a second because the native file watcher
uses whole-second modification timestamps. Backups live under the chosen data
directory, never in tracked project files. Viewer restarts, deleted/replaced
files, mismatched hashes, another viewer, and a missing lease all reject writes.
If a process crashes while holding a file lock, inspect the lock and process
before explicit local recovery; the tool never steals another writer's lock.

Automated tests exercise Unicode, conflict handling, backup fidelity, stale
sessions and concurrency boundaries using synthetic files. Live Windows testing
also passed inventory/in-object registration, UTF-8 readback, stale-hash rejection,
backup comparison, a deliberate compiler error, successful correction and save,
in-world execution, and exact source readback after closing/reopening the editor.
See [the acceptance record and remaining scope](BUILDER_VALIDATION.md).
Compiler/save results still require separate observation on every edit; these
tests do not turn a local file-write response into a compiler acknowledgement.
