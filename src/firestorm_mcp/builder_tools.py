"""Sidecar builder workflows; optional native endpoints remain capability-gated."""
import statistics
import time
from uuid import UUID

from .script_workspace import ScriptWorkspace
from .sidecar import connected_binary_identity, selection_summary


def register_builder_tools(tools):
    reg, client = tools.register, tools.client
    scripts = ScriptWorkspace(tools.root)

    def native(operation, arguments):
        if "FSMCPBuilder" not in client.apis:
            client.rpc("discover")
        ops = {op["name"] for op in client.apis.get("FSMCPBuilder", {}).get("ops", [])}
        if operation not in ops:
            raise ValueError("This viewer does not expose FSMCPBuilder." + operation +
                             ". Launch the separately built MCP viewer to use native object tools. "
                             "builder_selection_summary can read the visible Build panel's link/face label; "
                             "it cannot enumerate full object data.")
        result = client.call("FSMCPBuilder", operation, arguments, expect_reply=True, timeout=5)
        if not isinstance(result, dict) or result.get("schema_version") != 1:
            raise ValueError("Unsupported FSMCPBuilder response schema; update the MCP/viewer pair")
        return result

    @reg("Report sidecar builder capabilities from live discovery. External-file editing requires External Edit registration. Complete object APIs are unavailable without a compatible native endpoint; runtime injection is not implemented. Discovery is not a live-effect test.", True)
    def builder_capabilities():
        client.rpc("discover")
        def has(api, operation):
            return any(op["name"] == operation for op in client.apis.get(api, {}).get("ops", []))
        return {"inventory_query": has("LLInventory", "collectDescendantsIf"),
                "integration_mode": "external_sidecar",
                "custom_viewer_required_for_sidecar": False,
                "runtime_injection_implemented": False,
                "build_panel_summary_api": has("LLWindow", "getInfo"),
                "nearby_objects": has("LLAgent", "getNearbyObjectsList"),
                "selection": has("FSMCPBuilder", "getSelection"),
                "linkset": has("FSMCPBuilder", "getLinkset"),
                "faces": has("FSMCPBuilder", "getFaces"),
                "script_editing": "registered_external_editor_files",
                "script_sessions": scripts.list(),
                "direct_script_asset_read": False, "compile_result_api": False,
                "evidence": "live_api_discovery"}

    @reg("Read the visible Build panel's displayed link number or selected face indices through stock LEAP. Leaves selection untouched. Hidden/disabled labels return unknown; no object UUID, full linkset or complete face metadata is inferred.", True)
    def builder_selection_summary():
        return selection_summary(client, tools.viewer_dir)

    @reg("Fingerprint the connected Windows viewer's executable on disk for build diagnostics. Does not inject, read process memory, or prove the running image matches the file.", True)
    def viewer_runtime_identity():
        return connected_binary_identity(client)

    @reg("List script files explicitly registered by Firestorm's External Edit button. Does not scan inventory or temporary directories. Active file is not proof that the editor is still open.", True)
    def script_sessions():
        return scripts.list()

    @reg("Read a registered script's UTF-8 source and SHA256 for conflict detection. This reads the external-editor file, not the simulator asset.", True)
    def script_read(session_id: str):
        return scripts.read(session_id)

    @reg("Write a registered script with a required prior SHA256 and backup. Requires a control lease. Firestorm may automatically compile/save to the simulator; this call verifies only the local file. Inspect compiler results before retrying.")
    def script_write(session_id: str, source: str, expected_sha256: str):
        identity = client.rpc("assert_control")
        return scripts.write(session_id, source, expected_sha256, identity["viewer_pid"])

    @reg("Read selected object UUIDs and selected texture-entry face indices using the native FSMCPBuilder extension. Stock Firestorm returns an explicit unsupported error.", True)
    def object_selection():
        return native("getSelection", {})

    @reg("Read a loaded object's linkset using native FSMCPBuilder. Link numbers follow the viewer's current child order; simulator completeness is not guaranteed.", True)
    def object_linkset(object_id: str):
        return native("getLinkset", {"object_id": {"$uuid": str(UUID(object_id))}})

    @reg("Read native FSMCPBuilder texture entries for one loaded prim: face indices, texture IDs, color and UV parameters. Does not claim mesh triangles are faces or resolve PBR assets.", True)
    def object_faces(object_id: str):
        return native("getFaces", {"object_id": {"$uuid": str(UUID(object_id))}})

    @reg("Measure 1-20 sequential bridge plus viewer event-loop ping round trips in milliseconds. No world mutation. Does not measure simulator, asset loading or script compile latency.", True)
    def viewer_latency(samples: int = 5):
        if not 1 <= samples <= 20:
            raise ValueError("samples must be between 1 and 20")
        times = []
        for _ in range(samples):
            started = time.perf_counter()
            client.rpc("ping")
            times.append((time.perf_counter() - started) * 1000)
        return {"samples": samples, "median_ms": round(statistics.median(times), 3),
                "min_ms": round(min(times), 3), "max_ms": round(max(times), 3),
                "round_trips_ms": [round(value, 3) for value in times],
                "measured": "local_http_and_leap_event_loop", "simulator_latency_measured": False}
