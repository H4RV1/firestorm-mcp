# Empty object-inventory key crash

The 2026-10-04 00:26 UTC crash dump was symbolized against the matching local
builder.3 drop-fix executable/PDB. It confirms a null `LLFolderView* root` in
`LLInventoryAction::doToSelected`, reached with action `task_open` through
`LLPanelObjectInventory::handleKeyHere`, viewer key handling and
`LLWindowListener::keyDown` dispatched by LEAP. Thus an MCP/LEAP key event
triggered this crash. This is separate from the earlier invalid-face material drop.

Object selection refresh can clear `mFolders` while leaving its contents panel
alive. The Return handler and selected-action callback lacked checks before
passing that pointer to the generic inventory dispatcher, which dereferenced it.
The dump proves the null pointer and dispatch path; it does not identify the
exact earlier selection transition or establish the state of script saves.
Private logs, dumps and object/script identifiers are not included here.

## Changes

- Object-inventory key handling returns unhandled when its tree is absent.
- Selected-action callbacks return without dispatch when the tree is absent.
- The generic inventory action dispatcher also rejects a null root before reading
  the selection, protecting other callers.
- Targeted LEAP key down/up reject an object-inventory panel with no tree. They
  also verify the weak target handle, actual keyboard focus and availability
  after focus callbacks, then recheck the inventory tree before input dispatch.
  They return an explicit error when rejected. Existing bridge error propagation
  stops the key sequence without retrying or sending key-up after rejected down.

These guards do not make keyboard injection a background-safe semantic action.
Keyboard input is still excluded by the background-only executor. No global
shortcut behavior or inventory permissions are bypassed. No saved script, asset
journal, consumer content or object is changed by the fix.

## Build and regression

Apply this independent, hash-checked source patch before building/staging the
separate development viewer. Preserve the earlier material drop fix too:

```powershell
python scripts/apply_inventory_guard.py C:/src/firestorm --dry-run
python scripts/apply_inventory_guard.py C:/src/firestorm
python scripts/verify_native_inventory_guard.py --checkout C:/src/firestorm
python -m pytest -q tests/test_inventory_guard.py tests/test_ui_reliability.py
```

The native regression requires a C++17 compiler (VS developer environment on
Windows). It extracts the actual panel action/key and LEAP key down/up methods
from the specified viewer checkout and compiles them with synthetic dependencies.
It covers absent/cleared trees, valid Return handling, modifier rejection, hidden
targets, rejected focus, a tree cleared during focus, target invalidation, normal
controls and missing paths. No viewer or simulator is contacted by these tests.

The installer validates all three full source hashes and every anchor before
writing anything. A new baseline needs source review; never bypass its checks.
No extra native translation unit or CMake registration is required.

See [build provenance](../viewer-extension/inventory-guard-build.json) for the
exact tested/staged executable and status. In-world script opening, saving,
compiling and assembly outcomes require separate acceptance. Preserve pre-crash
script backups and inspect the actual simulator state before resuming edits.
