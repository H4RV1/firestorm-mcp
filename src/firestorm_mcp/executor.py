"""Run an explicit bounded plan over one persistent SDK MCP session."""
import argparse
import asyncio
import json
from pathlib import Path
import sys

from .probe import unpack
from .workflows import READ_TOOLS


def validate_plan(plan, allow_writes=False):
    if not isinstance(plan, dict) or set(plan) != {"version", "calls"} or plan["version"] != 1:
        raise ValueError("Plan requires version:1 and calls")
    if not isinstance(plan["calls"], list) or not 1 <= len(plan["calls"]) <= 32:
        raise ValueError("Plan requires 1-32 calls")
    for step in plan["calls"]:
        if not isinstance(step, dict) or set(step) != {"tool", "arguments"} or not isinstance(step["arguments"], dict):
            raise ValueError("Each call requires tool and arguments")
        if step["tool"] in {"control_acquire", "control_release"}:
            raise ValueError("The executor owns its bounded lease")
        if not allow_writes and step["tool"] not in READ_TOOLS | {"workflow_read", "object_link_plan"}:
            raise ValueError("This plan needs --allow-writes and task authority; no calls were sent")


async def execute(session, plan, allow_writes=False):
    validate_plan(plan, allow_writes)
    # Validate against the running server before taking a lease or executing.
    import jsonschema
    listed = await session.list_tools()
    schemas = {entry.name: entry.input_schema for entry in listed.tools}
    for step in plan["calls"]:
        if step["tool"] not in schemas:
            raise ValueError("Plan tool is unsupported: " + step["tool"])
        jsonschema.validate(step["arguments"], schemas[step["tool"]])
    async def call(name, args):
        result = await session.call_tool(name, args)
        if result.is_error:
            raise RuntimeError("MCP operation failed; inspect state before retrying")
        return unpack(result)
    status = await call("connection_status", {})
    if not status.get("connected"):
        return {"complete": False, "results": [], "stopped": "disconnected"}
    generation = status.get("bridge_generation")
    if not generation:
        raise ValueError("A bridge generation is required")
    await call("capabilities_refresh", {})
    acquired = await call("control_acquire", {"label": "Explicit MCP task plan", "seconds": 120})
    if acquired.get("acquired") is not True:
        raise RuntimeError("Could not acquire control")
    results = []
    try:
        for step in plan["calls"]:
            current = await call("connection_status", {})
            if not current.get("connected") or current.get("bridge_generation") != generation:
                return {"complete": False, "results": results, "stopped": "connection_changed"}
            lease = await call("control_acquire", {"label": "Explicit MCP task plan", "seconds": 120})
            if lease.get("acquired") is not True or lease.get("acquired_new") is True:
                return {"complete": False, "results": results, "stopped": "lease_lost"}
            try:
                value = await call(step["tool"], step["arguments"])
            except Exception:
                return {"complete": False, "results": results, "stopped": "step_error", "unknownOutcome": True,
                        "failed_tool": step["tool"], "retry_performed": False}
            results.append({"tool": step["tool"], "result": value})
            if isinstance(value, dict) and value.get("state") in {"queued", "running"}:
                return {"complete": False, "results": results, "stopped": "job_pending"}
            if isinstance(value, dict) and (value.get("ok") is False or value.get("complete") is False or value.get("state") in {"failed", "unknown", "cancelled"}):
                return {"complete": False, "results": results, "stopped": "operation_incomplete"}
        return {"complete": True, "results": results, "meaning": "plan_calls_returned; inspect each result for job/dispatch/evidence status"}
    finally:
        try:
            await call("control_release", {})
        except Exception:
            pass  # Own bounded lease expires; never steal another client's lease.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--viewer-dir", type=Path, required=True)
    parser.add_argument("--allow-writes", action="store_true")
    args = parser.parse_args()
    if args.plan.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("Plan exceeds 2 MiB; submit large assets using persistent MCP directly")
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    validate_plan(plan, args.allow_writes)
    async def run():
        from mcp import Client, StdioServerParameters
        params = StdioServerParameters(command=sys.executable, args=["-m", "firestorm_mcp.server",
            "--tool-profile", "compact", "--data-dir", str(args.data_dir), "--viewer-dir", str(args.viewer_dir)])
        async with Client(params) as session:
            return await execute(session, plan, args.allow_writes)
    print(json.dumps(asyncio.run(run()), ensure_ascii=False))


if __name__ == "__main__":
    main()
