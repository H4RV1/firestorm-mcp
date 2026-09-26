# Separate MCP development viewer

The selected architecture is an external Python MCP server, a persistent LEAP
bridge, and a small compiled `FSMCPBuilder` API in a separate viewer. Python
workflow changes usually need only a server restart. New native APIs require a
viewer rebuild. Runtime DLL injection is not used.

## What survives an official update

Install/run the development viewer in its own directory. Use the distinct
`Firestorm-MCP-Development` channel and patch `APP_NAME` to `FirestormMCP`.
The latter matters: a channel name alone does not separate Firestorm's settings
and cache profile. Keep the external MCP source and state outside both viewer
installations. Do not install an official update over the development directory.

An official update to the normal installation does not replace these files.
It also does not upgrade our development viewer. Adopting a newer viewer release
requires applying the patch, compiling, and validating it again. Old versions
may eventually be unsupported; a separate installation is not indefinite
compatibility. Keep the last working build until its replacement passes checks.

## Reproduce the first Windows build

The exact source revision and feature choices are in
[build-baseline.json](../viewer-extension/build-baseline.json). Use a short path
without spaces for the source/build tree, separate from Program Files. Follow
the [upstream Windows prerequisites](https://github.com/FirestormViewer/phoenix-firestorm/blob/10bd3c9f930c76e1427ddd4ecece6cdf36b4406d/doc/building_windows.md).
Visual Studio 2022 C++, CMake, Cygwin including patch, Git and Python are required.

In these examples `D:/FirestormMCP-build` is a new, dedicated build directory.
Clone the viewer and `https://github.com/FirestormViewer/fs-build-variables.git`
there as `viewer` and `variables`. Use `git -c core.autocrlf=false clone` and
check out the exact viewer commit. Create a `codex/mcp-builder` branch. Create a
Python venv named `env`, then install the viewer's `requirements.txt` into it.
Record the variables repository commit and `pip freeze` alongside build logs.

From this MCP repository, apply the integration once:

```powershell
python scripts/apply_viewer_extension.py D:/FirestormMCP-build/viewer --profile-name FirestormMCP --dry-run
python scripts/apply_viewer_extension.py D:/FirestormMCP-build/viewer --profile-name FirestormMCP
```

Open a Visual Studio x64 Native Tools command prompt, activate the build venv,
put CMake and Cygwin on PATH, and set these environment variables:

```bat
set AUTOBUILD_VSVER=170
set AUTOBUILD_VARIABLES_FILE=D:\FirestormMCP-build\variables\variables
cd /d D:\FirestormMCP-build\viewer
autobuild configure -A 64 -c ReleaseFS_open -- --chan MCP-Development -DLL_TESTS:BOOL=FALSE -DPython3_EXECUTABLE:FILEPATH=D:/FirestormMCP-build/env/Scripts/python.exe -DPYTHON_EXECUTABLE:FILEPATH=D:/FirestormMCP-build/env/Scripts/python.exe
autobuild build -A 64 -c ReleaseFS_open --no-configure
```

The initial configuration uses OpenSim support and also connects to Second Life.
It omits FMOD audio, Kakadu and Havok. This revision enables OpenAL instead;
audio playback and streaming parity have not been verified. It is a development build, not feature
parity with the official release. The shallow checkout's displayed build number
is derived from its local commit count; identify builds by commit and executable
hash, not that number alone.

Use the build's viewer-manifest resource staging to prepare the runnable folder.
From the MCP repository, with the build environment's Python:

```powershell
D:/FirestormMCP-build/env/Scripts/python.exe scripts/stage_custom_viewer.py --checkout D:/FirestormMCP-build/viewer --destination D:/FirestormMCP-build/portable-v1
```

The destination must be new; the helper refuses to overwrite an existing build.
No system installer is required for local testing. Do not copy over the official
installation or register new URL handlers. Launch through the MCP launcher with
an explicit executable and separate `--data-dir`; use `--login-screen` for the
first test. The new profile starts without the normal viewer's saved login.

## Upgrade and acceptance

For a newer release, create a separate source checkout at the chosen revision.
Run the integration dry-run, inspect the diff, then apply. An anchor mismatch is
a porting task; do not force a patch into an unfamiliar layout. Keep the API
response schema version explicit; the MCP rejects unsupported schemas.

Before switching users to a build:

1. Verify startup, runtime discovery, empty selection, and invalid-object errors.
2. Compare an owned unlinked prim and linkset against LSL link numbers; verify
   root/child, attachment and selected-face behavior without changing selection.
3. Exercise deleted/unloaded objects, partial properties and permission limits.
4. Measure native round trips and check that errors do not hang the viewer.
5. Keep script file writes separate from proven simulator compile/save results.

Next native features are object inventory, permission-aware script retrieval,
and asynchronous compile/save jobs with diagnostics. Transform/material writes
should follow with expected-state checks and explicit readback. Never add
arbitrary C++ execution as a shortcut.
