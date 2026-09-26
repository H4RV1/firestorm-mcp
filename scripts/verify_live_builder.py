"""Explicit opt-in live read-only check. Never part of automated package tests."""
import argparse
import asyncio
import json
from pathlib import Path
import statistics
import time

from mcp import Client, StdioServerParameters
from firestorm_mcp.configure import configuration
from firestorm_mcp.probe import unpack


async def verify(root, viewer, require_native=False):
    params = StdioServerParameters(**configuration(root, viewer)["mcpServers"]["firestorm"])
    async with Client(params) as session:
        async def call(tool_name, **arguments):
            return unpack(await session.call_tool(tool_name, arguments))
        status = await call("connection_status")
        if not status.get("connected"):
            raise ConnectionError("Start Firestorm through the LEAP launcher first")
        await call("control_acquire", label="Read-only builder connection verification", seconds=120)
        try:
            capabilities = await call("builder_capabilities")
            latency = await call("viewer_latency", samples=20)
            setting = await call("setting_get", key="ExternalEditor")
            identity = await call("viewer_call", api="LLAgent", operation="getID", expect_reply=True)
            native = {"tested": False}
            if require_native:
                if not all(capabilities.get(key) for key in ("selection", "linkset", "faces")):
                    raise RuntimeError("The connected viewer lacks the required native builder APIs")
                timings = []
                for _ in range(10):
                    started = time.perf_counter()
                    selection = await call("object_selection")
                    timings.append((time.perf_counter() - started) * 1000)
                    if selection.get("schema_version") != 1 or not isinstance(selection.get("objects"), list):
                        raise RuntimeError("Native selection returned an unexpected schema")
                rejected = []
                for tool in ("object_linkset", "object_faces"):
                    try:
                        await call(tool, object_id="00000000-0000-0000-0000-000000000000")
                    except RuntimeError as exc:
                        if "not a loaded prim" not in str(exc):
                            raise
                        rejected.append(tool)
                    else:
                        raise RuntimeError("Native object lookup accepted the null UUID")
                native = {"tested": True, "schema_version": 1,
                          "selection_count": len(selection["objects"]),
                          "selection_samples": len(timings),
                          "mcp_selection_median_ms": round(statistics.median(timings), 3),
                          "invalid_object_rejected_by": rejected,
                          "in_world_link_numbers_verified": False,
                          "in_world_faces_verified": False}
            # Store no avatar UUID, script source, location or credentials in the report.
            return {"connected": True, "capabilities": capabilities, "latency": latency,
                    "external_editor_configured": "script_entry.py" in json.dumps(setting),
                    "identity_reply_received": isinstance(identity, dict),
                    "world_mutations_sent": False, "script_compile_tested": False,
                    "native_extension_tested": native["tested"], "native_checks": native}
        finally:
            await call("control_release")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--viewer", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-native", action="store_true", help="Test selection and missing-object handling in the custom viewer")
    args = parser.parse_args()
    report = asyncio.run(verify(args.data_dir, args.viewer, args.require_native))
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
