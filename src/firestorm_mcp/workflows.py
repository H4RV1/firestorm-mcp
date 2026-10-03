"""Bounded read executor; writable workflows retain explicit individual dispatch."""
import json
import time

from .protocol import json_default

READ_TOOLS = frozenset({
    "connection_status", "builder_capabilities", "assets_status", "object_search",
    "object_selection", "object_linkset", "object_faces", "script_sessions", "script_read",
    "ui_map", "ui_task", "ui_tree", "ui_read", "ui_rows", "ui_scene", "ui_wait_change", "background_status", "mesh_upload_status", "asset_inspect",
})


def register_workflow_tools(tools):
    @tools.register("Execute 1-16 explicit semantic read calls in one MCP request. Prevalidates the entire plan, returns per-step timing, stops on the first error or budget exhaustion between calls, and never performs input, opens panels, retries or acquires control. Use for nearby/selection/faces/script/UI inspection after acquiring your lease.", True)
    def workflow_read(calls: list[dict], timeout: float = 20):
        import jsonschema
        if not 1 <= len(calls) <= 16 or not 1 <= timeout <= 60:
            raise ValueError("Use 1-16 reads and timeout 1-60 seconds")
        for step in calls:
            if set(step) != {"tool", "arguments"} or step["tool"] not in READ_TOOLS:
                raise ValueError("Each step requires an allowlisted read tool and arguments; writes and nested plans are refused")
            jsonschema.validate(step["arguments"], tools.definitions[step["tool"]].input_schema)
        started = time.monotonic()
        results, size = [], 0
        for step in calls:
            elapsed = time.monotonic() - started
            if elapsed >= timeout:
                return {"results": results, "complete": False, "stopped": "budget_exhausted", "atomic": False}
            before = time.perf_counter()
            try:
                value = tools.call(step["tool"], step["arguments"])
                size += len(json.dumps(value, default=json_default).encode("utf-8"))
                if size > 2 * 1024 * 1024:
                    return {"results": results, "complete": False, "stopped": "result_byte_limit", "atomic": False}
                results.append({"tool": step["tool"], "result": value, "elapsed_ms": round((time.perf_counter()-before)*1000, 2)})
            except (ValueError, RuntimeError, ConnectionError, TimeoutError) as exc:
                results.append({"tool": step["tool"], "error": str(exc)[:500]})
                return {"results": results, "complete": False, "stopped": "step_error", "atomic": False}
        return {"results": results, "complete": True, "atomic": False,
                "elapsed_ms": round((time.monotonic()-started)*1000, 2)}
