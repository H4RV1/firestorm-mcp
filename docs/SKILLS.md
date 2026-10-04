# Mesh-preview agent skill

For the local builder.2 package, [firestorm-builder](../skills/firestorm-builder/SKILL.md)
adds nearby-object, link/unlink, surface, script, bounded UI and asset recovery
procedures. Copy that entire directory into your host's skills directory. It is
independent of MCP runtime installation and adds no permissions. Its packaged
instructions are validated; a live skill-driven performance benchmark is pending.

The MCP supplies tools. The optional **firestorm-mesh-preview** skill supplies the importer procedure: source commits, LOD/physics checks, captures and cleanup.

It follows the [Agent Skills format](https://agentskills.io/specification). It adds instructions, not viewer capabilities or permissions. A speed improvement has not been measured.

The [builder skill](../skills/firestorm-builder/SKILL.md) routes object plans,
registered script edits, bounded UI and asset jobs. Use its quick routing table
and load only the reference relevant to the task. Keep personal copies aligned
with this source. Tools still need the matching native capabilities; proposed
script lifecycle, camera pose and complete simulator readback APIs are not
implemented by skill instructions. Renew control in the same session before
long waits and reinspect after human changes or bridge recovery.

## Install

1. [Download skill 0.1.1](https://github.com/AochiToxx/firestorm-mcp/releases/download/skill-v0.1.1/firestorm-mesh-preview-0.1.1.zip) and extract it.
2. Import the complete `firestorm-mesh-preview` folder through your host's skill loader or documented skills directory. Keep `SKILL.md`, `references/importer.md` and `LICENSE` together.
3. Configure Firestorm MCP separately, then select the skill and provide your files and requested check.

Example request:

> Compare my High and Lowest exports in the importer. Capture the differences and leave upload for a separate decision.

If the host has no skill loader but can read files, ask it to read `SKILL.md` and the linked procedure. Adding the skill does not require a viewer restart. It does not register the MCP or reduce the host's tool catalog automatically.

## Supported workflow

The procedures were observed on Windows with Firestorm **7.2.4.80712** and MCP **0.3.0a1**. They use the same tools in the current release.

Check `connection_status.local_platform` first. Linux/macOS need manual file selection; the skill does not add native picker adapters or a Pi viewer. See [platform support](PLATFORMS.md).

Format, package and offline instruction checks are separate from live testing. Host-specific automatic activation and a new skill-driven live benchmark remain unverified. [Verification record](VALIDATION.md).

## Improve the skill

Edit [the source folder](../skills/firestorm-mesh-preview) and describe the request, failure and correction in a pull request. Keep API fixes in the runtime and follow [CONTRIBUTING.md](../CONTRIBUTING.md).

Build a standalone ZIP with `python3 scripts/build_skill.py --output-dir dist` (`python` on Windows). It includes both skill documents and the MIT licence. The runtime wheel does not install personal skill files.
