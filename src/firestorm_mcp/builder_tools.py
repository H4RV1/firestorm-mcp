"""Sidecar builder workflows; optional native endpoints remain capability-gated."""
import statistics
import time
import typing
import math
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
                "bounded_nearby": has("FSMCPBuilder", "getNearby"),
                "link_plans": has("FSMCPBuilder", "prepareLink") and has("FSMCPBuilder", "commitLink"),
                "object_select": has("FSMCPBuilder", "selectObjects"),
                "bounded_ui": has("FSMCPUI", "getControls"),
                "background_ui_scene": has("FSMCPUI", "getScene"),
                "background_frame_capture": has("FSMCPUI", "requestCapture") and has("FSMCPUI", "captureResult"),
                "compiler_rows": has("FSMCPUI", "getRows"),
                "legacy_surface_plans": has("FSMCPBuilder", "prepareFace") and has("FSMCPBuilder", "commitFace"),
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

    @reg("Search loaded prims with viewer-side distance, ownership, root and result limits. Names use selection properties or an existing Area Search cache; query excludes unknown names. next_offset is a changing cache index, not a snapshot. No selection changes or property fetches.", True)
    def object_search(distance: float = 32, owned_only: bool = False, roots_only: bool = True,
                      query: str = "", limit: int = 50, offset: int = 0):
        if not 0 < distance <= 256 or not 1 <= limit <= 100 or offset < 0 or len(query.encode()) > 128:
            raise ValueError("Use distance (0,256], limit 1-100, offset>=0, query<=128 bytes")
        return native("getNearby", dict(distance=distance, owned_only=owned_only, roots_only=roots_only,
                                       query=query, limit=limit, offset=offset))

    @reg("Select 1-32 explicit loaded owned modifiable root UUIDs. Requires lease and exact prior object_selection.selection_identity, including order. Reinspect selection/properties before planning link/unlink. Does not link or change materials.")
    def object_select(object_ids: list[str], expected_selection: list[dict]):
        if not 1 <= len(object_ids) <= 32 or len(set(object_ids)) != len(object_ids) or len(expected_selection) > 256:
            raise ValueError("Supply 1-32 distinct roots and at most 256 prior selection identities")
        expected = []
        for item in expected_selection:
            if set(item) != {"object_id", "root_id"}:
                raise ValueError("Each selection identity requires exactly object_id and root_id")
            expected.append({key: {"$uuid": str(UUID(value))} for key, value in item.items()})
        client.rpc("assert_control")
        return native("selectObjects", {"object_ids": [{"$uuid": str(UUID(x))} for x in object_ids], "expected_selection": expected})

    @reg("Prepare a single-use link or unlink plan for the current owned modifiable selection. Returns exact selection, candidate root and 30-second expiry. No world change. Requires explicit task authority before commit.", True)
    def object_link_plan(action: typing.Literal["link", "unlink"]):
        return native("prepareLink", {"action": action})

    @reg("Consume an object_link_plan once under a control lease. Refuses changed/expired selection or session. Uses the viewer's normal link/unlink action, including its confirmation preferences. Returns dispatch only; inspect each affected UUID/root afterward. Never blindly repeat after timeout.")
    def object_link_apply(plan_id: str):
        client.rpc("assert_control")
        return native("commitLink", {"plan_id": {"$uuid": str(UUID(plan_id))}})

    @reg("Prepare an explicit prim/face surface edit without changing the world. Supported changes: color [r,g,b,a] 0..1, scale [u,v] -100..100, offset [u,v] -1..1, rotation radians +/-2pi, glow 0..1, fullbright boolean. Returns before/preview and a 30-second single-use plan. PBR, textures, normal/specular assets remain unchanged.", True)
    def material_face_plan(object_id: str, face: int, changes: dict):
        if not 0 <= face <= 255 or not changes or set(changes) - {"color", "scale", "offset", "rotation", "glow", "fullbright"}:
            raise ValueError("Use a valid face index and supported legacy surface fields")
        for key, value in changes.items():
            if key == "fullbright":
                if type(value) is not bool: raise ValueError("fullbright must be boolean")
                continue
            low, high, count = {"color": (0, 1, 4), "scale": (-100, 100, 2), "offset": (-1, 1, 2),
                                "rotation": (-2*math.pi, 2*math.pi, 0), "glow": (0, 1, 0)}[key]
            values = value if count else [value]
            if not isinstance(values, list) or (count and len(values) != count) or any(type(x) not in (int, float) or not math.isfinite(x) or not low <= x <= high for x in values):
                raise ValueError("Invalid bounded surface value: " + key)
        return native("prepareFace", {"object_id": {"$uuid": str(UUID(object_id))}, "face": face, "changes": changes})

    @reg("Apply one material_face_plan under a lease after native session/permissions/texture-entry revalidation. The plan is consumed before dispatch. Returns local preview plus dispatched status; reread object_faces and verify simulator/rendered effects independently. Never blindly replay.")
    def material_face_apply(plan_id: str):
        client.rpc("assert_control")
        return native("commitFace", {"plan_id": {"$uuid": str(UUID(plan_id))}})

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
