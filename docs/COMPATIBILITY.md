# MCP compatibility

The server uses the official **MCP Python SDK v2** (`mcp>=2.2,<3`) over local stdio. It can start and list tools without a connected viewer.

## Supported protocol behavior

| Area | Implementation |
| --- | --- |
| Protocol revisions | Wire tests cover `2024-11-05`, `2025-03-26`, `2025-06-18`, `2025-11-25` and `2026-07-28`. |
| Discovery | Explicit viewer refresh; legacy tool-list notifications and current subscriptions. |
| Results | JSON text, PNG blocks and structured content. Non-object structured results use a `result` wrapper. |
| Validation | Extra workflow arguments are rejected before dispatch. Unknown tools return a protocol error. |
| Tool profiles | `compact` lists 72 workflow tools; `all` also lists discovered viewer operations. `viewer_call` is available in both. |

The [SDK migration guide](https://py.sdk.modelcontextprotocol.io/migration/) and [2026-07-28 revision notes](https://modelcontextprotocol.io/specification/2026-07-28/changelog) describe the protocol changes. Profiles affect discovery, not permissions.

Tools-only MCP servers are valid. Resources, prompts, sampling, elicitation and long-running tasks are not required by this integration. [Capability negotiation](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle).

## Hosts and platforms

Generated configuration supports common MCP JSON, Codex TOML and VS Code's extension-host format. Claude Desktop, Claude Code, Cursor and VS Code application UIs have not all been exercised. Use the [installation guide](INSTALLATION.md) and record host/version when reporting a problem.

The offline CI matrix covers Windows, Linux x64/ARM64 and macOS Intel/ARM64. Live viewer evidence remains the Windows workflow. See [platform support](PLATFORMS.md) and [completed checks](VALIDATION.md).

Remote HTTP MCP transport is not implemented. The helper's authenticated loopback `/rpc` service is internal IPC and cannot be used as a host's MCP URL.

## Projects consulted

The September 2026 review used these projects as design references:

| Project | Relevant lesson |
| --- | --- |
| [Blender MCP](https://github.com/ahujasid/blender-mcp) | Separate the application connection from the MCP host setup. |
| [Playwright MCP](https://github.com/microsoft/playwright-mcp) | Prefer semantic tools and explicit state checks over assuming a click worked. |
| [MikoStorm](https://github.com/DDynamic-Evolution/MikoStorm) | Compare viewer capabilities; this project uses standard Firestorm instead of a custom viewer. MikoStorm was not installed or copied. |
| [MCP reference servers](https://github.com/modelcontextprotocol/servers) | Add protocol features for an actual workflow, not catalog size. |
| [MCP Inspector](https://github.com/modelcontextprotocol/inspector) | Check discovery and schemas with an independent client. CI pins version 2.6.0. |

## Open work

- Test more viewer builds and host applications with visible readback.
- Add reliable multi-file workflows and clearer progress/cancellation reporting.
- Test native file-picker adapters on Linux/macOS.
- Consider [MCP bundles](https://github.com/modelcontextprotocol/mcpb), PyPI and [Registry publication](https://modelcontextprotocol.io/registry/package-types) to simplify discovery and installation. They are not available yet.
- Design authentication and session isolation before offering a remote service.

See [CONTRIBUTING.md](../CONTRIBUTING.md) for focused changes. The project's [MIT licence](../LICENSE) and [dependency notices](../THIRD_PARTY.md) are separate from MCP protocol compatibility.
