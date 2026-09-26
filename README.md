# Firestorm MCP

**Let AI agents inspect exports, operate mesh previews and capture evidence in the Firestorm viewer for Second Life.**

[Download](#download) · [Install](#install) · [Tools](docs/TOOLS.md) · [Agent guide](docs/AGENT_GUIDE.md) · [Contribute](CONTRIBUTING.md)

**0.3.0a3+builder.1 · Local development version · MIT**

This checkout extends [AochiToxx/firestorm-mcp](https://github.com/AochiToxx/firestorm-mcp)
with builder capability checks, measured viewer latency, and registered external-script
editing with conflict detection and backups. See [research and capability map](docs/BUILDER_RESEARCH.md)
and [script editing](docs/SCRIPT_EDITING.md). The read-only [native object/face hook](viewer-extension/README.md)
has been compiled into a separate development viewer. Live Windows checks passed
script compile/error/recovery and a 17-prim, 28-face linkset comparison against
LSL. See [the acceptance record and remaining scope](docs/BUILDER_VALIDATION.md).
The downloads below are upstream releases and do not contain these local additions.
Advanced native features use a [separate development viewer](docs/CUSTOM_VIEWER.md)
with its own installation and settings profile. Official updates do not upgrade
that build; we must reapply the patch and rebuild when adopting a newer release.

Firestorm MCP connects your agent to an installed Firestorm viewer through its LEAP interface. It runs locally beside the viewer and works with MCP hosts that support stdio servers.

**Built mostly by AI coding agents, under human direction.** People and AI agents are welcome to contribute.

## Download

**[Download the setup ZIP](https://github.com/AochiToxx/firestorm-mcp/releases/download/v0.3.0a3/firestorm-mcp-0.3.0a3-source.zip)** — includes the installer, source, guides and tests.

[Python wheel](https://github.com/AochiToxx/firestorm-mcp/releases/download/v0.3.0a3/firestorm_mcp-0.3.0a3-py3-none-any.whl) · [Checksums](https://github.com/AochiToxx/firestorm-mcp/releases/download/v0.3.0a3/SHA256SUMS.txt) · [Release notes](https://github.com/AochiToxx/firestorm-mcp/releases/tag/v0.3.0a3)

Optional: [mesh-preview agent skill](https://github.com/AochiToxx/firestorm-mcp/releases/download/skill-v0.1.1/firestorm-mesh-preview-0.1.1.zip). It teaches the importer workflow; install the MCP separately. [Skill setup](docs/SKILLS.md).

Downloads are on GitHub Releases. The project is not yet on PyPI or the MCP Registry.

## Install

1. Install **Python 3.11–3.14** and a compatible [Firestorm viewer](https://www.firestormviewer.org/). Live control requires both on the same desktop and user account.
2. Extract the setup ZIP into a permanent, user-writable folder.
3. Run **`Install.cmd`** on Windows or **`sh Install.sh`** in a terminal on Linux/macOS. The installer creates its own Python environment and prints your MCP configuration.
4. Add the printed entry to your agent's MCP settings. Use the [configuration generator](docs/INSTALLATION.md#agent-configuration) for Codex or VS Code. Keep your other server entries.
5. Run **`Start-FirestormMCP.cmd`** or **`sh Start-FirestormMCP.sh`**, sign in, then run the matching **`Check-FirestormMCP`** script.

The launcher leaves an already-running viewer alone. Close it normally when convenient, then start through the launcher: LEAP connects at viewer startup.

[Custom paths, diagnostics and upgrades](docs/INSTALLATION.md).

## Platforms

| System | Current support |
| --- | --- |
| Windows x64 | Live viewer workflow tested. Automated package tests cover Python 3.11–3.14. |
| Linux x64 | Package tests pass. Viewer launch is experimental; select files manually. |
| macOS Intel / Apple Silicon | Package tests pass on both architectures. Viewer launch is experimental; select files manually. |
| Linux ARM64 / Raspberry Pi | Ubuntu ARM64 package tests pass. Pi hardware, Raspberry Pi OS and a compatible Firestorm viewer are unverified. |
| Headless / remote systems | Offline file tools may work. Remote viewer control is not implemented. |

Automated tests use simulated viewers. They do not certify live desktop control. [Platform details](docs/PLATFORMS.md).

## What it can do

| Area | Capabilities |
| --- | --- |
| Export inspection | Read COLLADA, glTF, GLB and image metadata, hashes, dimensions and references. |
| Mesh previews | Open Local Mesh or the model importer; inspect LODs, physics, warnings, dimensions and displayed fees; adjust the preview camera. |
| Viewer UI | Find and inspect controls, click registered buttons, enter text, send targeted keys and invoke menus. Windows supports recognized native file pickers. |
| Camera and images | Set the world camera, capture images and orbit views, save manifests and compare pixels. |
| Avatar and scene | Read position, start/poll/stop walking, query nearby objects and search an inventory folder. |
| Settings and events | Read/change viewer settings, subscribe to events and coordinate agents through control leases. |
| Live viewer APIs | Discover additional operations, including teleport, appearance, gestures and chat, through `viewer_call`. |

This development server has **53 workflow tools**, including three object tools that require the custom viewer's native extension. Stock Firestorm **7.2.4.80712** exposed **94 further operations across 18 APIs**. Availability varies by viewer and login state; discovery is not test coverage.

Generated configuration uses the **compact** profile: 53 listed tools, with discovered operations available through `viewer_call`. The `all` profile also lists those operations individually after refresh. Both profiles have the same authority.

[Tool reference](docs/TOOLS.md) · [Input schemas](docs/tool-catalog.json) · [MCP compatibility](docs/COMPATIBILITY.md)

## For agents

1. Check `connection_status`, including platform support and the control owner. Refresh live capabilities with `capabilities_refresh`.
2. Inspect unfamiliar operations with `viewer_api_inspect`. For mesh work, read the [preview skill](skills/firestorm-mesh-preview/SKILL.md).
3. Acquire a bounded control lease and keep the same MCP session. An existing preview may belong to someone else; establish permission before opening, focusing or replacing it.
4. Use scoped UI queries, verify state after input and inspect captured images. Distinguish source metadata, local preview and simulator results.
5. Restore temporary settings where supported and release your lease in cleanup. Preserve the user's requested final state.

[Agent guide and SDK example](docs/AGENT_GUIDE.md).

## Known limits

- **Viewer behavior varies.** Some combos require selection followed by commit; some checkboxes require a targeted key. The agent guide records the tested procedures.
- **Preview evidence has limits.** Filenames do not prove loaded file bytes, displayed fees may be stale, and a nonblank image may show the wrong subject. Upload and simulator behavior need separate verification.
- **Controls are incomplete.** No one-call multi-file import, full object/face/material or script lifecycle suite, exact camera restoration, or Unicode text-entry fallback is provided.
- **Control is cooperative.** Leases do not block human input. Cancelling an MCP request does not undo an action already sent to the viewer.
- **Consequential actions need authority.** Uploads, spending, chat and inventory/world changes require the user's permission. Generic tools do not enforce a universal no-spend policy. Local Mesh's **Rez Selected** creates simulator objects.

## Tested scope

The upstream baseline has **85 tests**, with eight CI jobs covering Windows, Linux x64/ARM64 and macOS Intel/ARM64. This local extension adds synthetic builder/script regressions; its validation is local Windows testing, not a new cross-platform CI certification. Checks include fresh installs and MCP protocol behavior.

Live evidence comes from the Windows `0.3.0a1` workflow: explicit LOD/physics imports, control readback, preview zoom/orbit, captures and cleanup. The public release does not add live platform acceptance. [Verification record](docs/VALIDATION.md).

## Contribute

Help improve installation, platform support, viewer tools or agent workflows. Open an [issue](https://github.com/AochiToxx/firestorm-mcp/issues) with a small reproducible example, or use [Discussions](https://github.com/AochiToxx/firestorm-mcp/discussions) for questions and ideas.

Read [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md) before a pull request. Keep credentials, private captures and product assets out of contributions.

Pull requests must pass CI and security checks. For private vulnerability reports and security boundaries, see [SECURITY.md](SECURITY.md).

This independent project uses the [MIT licence](LICENSE). Firestorm and other dependencies keep their own licences; see [THIRD_PARTY.md](THIRD_PARTY.md).
