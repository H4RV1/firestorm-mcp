"""Installed-XUI navigation index. Source candidates are never live UI evidence."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
import urllib.parse
import xml.etree.ElementTree as ET

FLOATER_ROOT = "/main_view/menu_stack/world_panel/Floater View"
# These panels are created by C++ factory callbacks rather than XML includes.
# llpreviewscript.cpp: LLPreviewLSL/LLLiveLSLEditor::mFactoryMap.
FACTORY_PANELS = {
    ("floater_script_preview.xml", "script panel"): "panel_script_ed.xml",
    ("floater_live_lsleditor.xml", "script ed panel"): "panel_script_ed.xml",
}
NON_VIEWS = {"string", "strings", "item", "combo_item", "column", "row", "menu_item_separator"}

TASKS = {
    "script_object": {
        "title": "Edit and inspect a script inside an object",
        "keywords": "script lsl compiler compile save error external edit running reset",
        "documents": ["floater_live_lsleditor.xml"],
        "controls": ["obj_name", "Script Editor", "edit_btn_2", "save_btn_2", "lsl errors", "running", "mono", "Reset"],
        "steps": ["Open the intended script through the object's Contents panel; keep only the intended script editor open.",
                  "Read obj_name and the editor source explicitly to confirm the target. XUI paths do not identify object/item UUIDs.",
                  "Use ui_click on the live-verified edit_btn_2 path without a floater registry argument; keyed editors may not resolve through the registry.",
                  "Use script_sessions, script_read and script_write with a lease and the previous source hash.",
                  "Observe compiler/save completion and verify the intended in-world result before declaring success."],
        "limits": ["Stock getInfo/getValue does not expose compiler scroll-list rows. A null errors value is not successful compilation.",
                   "Multiple editor instances can share the same path; instance identity is not verified.",
                   "The preprocessor editor may add controls not present in the base script panel."],
        "preferred_tools": ["script_sessions", "script_read", "script_write"],
    },
    "script_inventory": {
        "title": "Edit an inventory script",
        "keywords": "inventory script lsl external edit compile save",
        "documents": ["floater_script_preview.xml"],
        "controls": ["path_txt", "Script Editor", "edit_btn_2", "save_btn_2", "lsl errors"],
        "steps": ["Open the intended inventory script and verify its location/source using targeted reads.",
                  "Click the live-verified External Edit control, then use script_sessions/read/write.",
                  "Check the compiler and save status; an inventory script does not execute until placed in-world."],
        "limits": ["Keep only the intended editor open; source paths do not distinguish keyed instances.",
                   "Compiler rows require separate evidence; null is not success."],
        "preferred_tools": ["script_sessions", "script_read", "script_write"],
    },
    "object_build": {
        "title": "Inspect selected objects, links, faces and contents",
        "keywords": "build object prim link linkset face texture material content selection",
        "documents": ["floater_tools.xml"],
        "controls": ["link_num_obj_count", "General", "Object", "Features", "Texture", "Contents", "contents_inventory", "contents_filter", "button refresh"],
        "steps": ["Prefer native object_selection/object_linkset/object_faces when builder_capabilities reports them available.",
                  "Use the Build map only for visible UI state or actions not exposed by semantic tools.",
                  "Verify object identity and permissions before changing contents or properties."],
        "limits": ["Inventory rows and tab buttons may be generated at runtime and absent from XUI.",
                   "The Texture tab is inserted by C++ according to FSUseNewTexturePanel; search panel_fs_tools_texture.xml or panel_tools_texture.xml and discover its runtime mount.",
                   "Texture entries are not resolved PBR materials."],
        "preferred_tools": ["builder_capabilities", "object_selection", "object_linkset", "object_faces", "builder_selection_summary"],
    },
    "mesh_upload": {
        "title": "Inspect mesh import and upload preview",
        "keywords": "mesh upload import lod physics fee preview",
        "documents": ["floater_model_preview.xml"],
        "controls": ["preview_panel", "calculate_btn", "ok_btn", "cancel_btn", "import_scale", "description_form", "lod_panel", "physics_panel", "lod_source_high", "physics_lod_combo"],
        "steps": ["Use mesh_upload_status for the existing preview and its validation fields.",
                  "Locate a needed control in this document, inspect it, then use a targeted action and fresh readback.",
                  "Calculating a fee and submitting an upload are separate actions requiring the appropriate authority."],
        "limits": ["Preview values do not prove uploaded assets or simulator delivery.", "Native file pickers are outside XUI; use native_file_dialogs/native_file_choose where supported."],
        "preferred_tools": ["mesh_upload_status", "mesh_preview_camera", "native_file_dialogs"],
    },
    "inventory": {
        "title": "Find inventory controls without enumerating the inventory tree",
        "keywords": "inventory search filter folder item contents",
        "documents": ["floater_my_inventory.xml"],
        "controls": ["inventory search editor", "filter_combo_box", "inventory filter tabs", "show_filters_inv_btn"],
        "steps": ["Use LLInventory semantic operations for folder/item data when available.",
                  "Search installed XUI for search/filter controls; inspect exact candidates.",
                  "Never enumerate the whole live inventory tree to find a button."],
        "limits": ["Dynamic item rows and UUIDs are not part of the source map.", "Standalone panels need an observed runtime mount path."],
        "preferred_tools": ["viewer_api_inspect", "viewer_call"],
    },
    "preferences": {
        "title": "Locate viewer preference controls",
        "keywords": "preferences settings graphics sound audio interface controls",
        "documents": ["floater_preferences.xml"],
        "controls": ["OK", "Cancel", "search_prefs_edit"],
        "steps": ["Search ui_map by label, tooltip or control name, optionally narrowing to a panel document.",
                  "Check the current viewer setting through its semantic API when possible.",
                  "Verify the live control, apply only the authorized change and read back its state."],
        "limits": ["Custom skins, translations and C++ panel factories can change runtime hierarchy.", "Source control_name identifies a setting binding, not permission to change it."],
        "preferred_tools": ["viewer_api_inspect", "viewer_call"],
    },
}


class UIMap:
    def __init__(self, viewer_dir):
        self.directory = Path(viewer_dir) / "skins/default/xui/en"
        self.signature = None
        self.entries = []
        self.by_id = {}
        self.revision = None
        self.warnings = []
        self.search_text = {}

    def load(self, refresh=False):
        base = self.directory.resolve()
        files = sorted(self.directory.glob("*.xml"))
        if not files:
            raise ValueError("Installed default English XUI files are unavailable; configure --viewer-dir")
        if len(files) > 2500:
            raise ValueError("XUI file limit exceeded")
        stats = []
        for path in files:
            stat = path.stat()
            if stat.st_size > 2_000_000:
                raise ValueError("XUI document size limit exceeded")
            stats.append((path.name, stat.st_size, stat.st_mtime_ns))
        signature = tuple(stats)
        if sum(stat[1] for stat in stats) > 64_000_000:
            raise ValueError("Total XUI size limit exceeded")
        if not refresh and signature == self.signature:
            return True
        documents, warnings = {}, []
        digest = hashlib.sha256()
        for path in files:
            if path.resolve().parent != base:
                raise ValueError("XUI files must stay inside the configured resource directory")
            raw = path.read_bytes()
            if len(raw) > 2_000_000 or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
                raise ValueError("Oversized XUI or XML entity declarations are not supported")
            digest.update(path.name.encode() + b"\0" + raw + b"\0")
            try:
                documents[path.name] = ET.fromstring(raw)
            except ET.ParseError:
                warnings.append({"document": path.name, "reason": "invalid_xml"})
        entries = []

        def visit(element, document, source, ancestry, parent_path, ordinal, stack):
            if len(entries) >= 150_000 or len(stack) > 12 or len(ancestry) > 80:
                raise ValueError("XUI expansion limit exceeded")
            if "." in element.tag or element.tag in NON_VIEWS:
                return
            name = element.get("name")
            path = parent_path
            lineage = ancestry + [(element.tag, name, ordinal)]
            if name:
                path = (parent_path + "/" + urllib.parse.quote(name, safe=" ")) if parent_path else None
                identity = json.dumps([document, lineage], ensure_ascii=True, separators=(",", ":"))
                entry = {"id": "xui:" + hashlib.sha256(identity.encode()).hexdigest()[:24],
                         "document": document, "source": source, "name": name, "kind": element.tag,
                         "label": element.get("label", element.get("title", ""))[:512],
                         "tooltip": element.get("tool_tip", "")[:512],
                         "setting": element.get("control_name"), "candidate_path": path,
                         "live_verified": False}
                entries.append(entry)
            elif element.tag not in {"root"}:
                # Unnamed runtime widgets may add a path component we cannot infer.
                path = None
            include = element.get("filename") or FACTORY_PANELS.get((document, name))
            included_children = []
            if include:
                if Path(include).name != include or include not in documents or include in stack:
                    warnings.append({"document": document, "reason": "unresolved_or_cyclic_include", "include": include})
                else:
                    included_children = list(documents[include])
            # Explicit inline children override same-name included children.
            local_names = {child.get("name") for child in element if child.get("name")}
            children = [(child, include) for child in included_children if child.get("name") not in local_names]
            children += [(child, source) for child in element]
            for i, (child, origin) in enumerate(children):
                visit(child, document, origin, lineage, path, i, stack + ([include] if included_children else []))

        for filename, root in documents.items():
            mount = FLOATER_ROOT if root.tag in {"floater", "multi_floater"} else None
            visit(root, filename, filename, [], mount, 0, [filename])
        # Equal source paths are ambiguous; do not silently pick one.
        counts = {}
        for entry in entries:
            if entry["candidate_path"]:
                key = (entry["document"], entry["candidate_path"])
                counts[key] = counts.get(key, 0) + 1
        for entry in entries:
            parts = (entry["candidate_path"] or "").split("/")
            entry["source_path_ambiguous"] = any(
                counts.get((entry["document"], "/".join(parts[:end])), 0) > 1
                for end in range(1, len(parts) + 1))
        by_id = {entry["id"]: entry for entry in entries}
        if len(by_id) != len(entries):
            raise ValueError("XUI control ID collision")
        self.entries, self.by_id = entries, by_id
        self.signature, self.revision, self.warnings = signature, digest.hexdigest(), warnings
        self.search_text = {entry["id"]: " ".join(str(entry.get(k) or "") for k in
                            ("document", "name", "label", "tooltip", "setting")).casefold() for entry in entries}
        return False

    def search(self, query="", document=None, limit=30, offset=0, refresh=False):
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Use limit 1-100 and nonnegative offset")
        if len(query) > 256 or (document is not None and len(document) > 200):
            raise ValueError("Search query or document name is too long")
        cached = self.load(refresh)
        words = query.casefold().split()
        matches = [entry for entry in self.entries if (document is None or entry["document"] == document)
                   and all(word in self.search_text[entry["id"]] for word in words)]
        matches.sort(key=lambda e: (e["name"].casefold() != query.casefold(), e["document"], e["id"]))
        selected = matches[offset:offset + limit]
        return {"source": "installed_default_english_xui", "revision": self.revision, "cache_hit": cached,
                "live_contacted": False, "active_skin_verified": False, "total_controls": len(self.entries),
                "total_matches": len(matches), "controls": selected,
                "next_offset": offset + len(selected) if offset + len(selected) < len(matches) else None,
                "warnings": self.warnings[:20], "warning_count": len(self.warnings),
                "note": "Source candidates only. Use ui_read before input. Null paths need an observed runtime mount; duplicate runtime instances are not identified."}

    def task(self, task=None):
        if task is None:
            return {"tasks": [{"id": key, "title": value["title"], "keywords": value["keywords"]}
                              for key, value in TASKS.items()], "live_contacted": False}
        if task not in TASKS:
            raise ValueError("Unknown task; call ui_task without task to list IDs")
        self.load()
        guide = TASKS[task]
        controls = [entry for entry in self.entries if entry["document"] in guide["documents"]
                    and entry["name"] in guide["controls"]]
        return {"task": task, **guide, "requested_control_names": guide["controls"], "controls": controls,
                "missing_control_names": sorted(set(guide["controls"]) - {e["name"] for e in controls}),
                "revision": self.revision, "live_contacted": False, "live_verified": False,
                "next": "ui_read with selected control IDs, then existing ui_click/ui_press_key/ui_set_text with verified paths and a control lease"}

    def resolve(self, controls):
        if not 1 <= len(controls) <= 20 or len(set(controls)) != len(controls):
            raise ValueError("Supply 1-20 distinct control IDs or exact paths")
        if any(control.startswith("xui:") for control in controls):
            self.load()
        targets = []
        for control in controls:
            if control.startswith("xui:"):
                entry = self.by_id.get(control)
                if not entry:
                    raise ValueError("Unknown/stale control ID; search ui_map again")
                if not entry["candidate_path"] or entry["source_path_ambiguous"]:
                    raise ValueError("Control has no unambiguous source path; use a scoped runtime discovery")
                path = entry["candidate_path"]
            else:
                path = control
            if not path.startswith("/main_view/") or "//" in path or len(path) > 2048:
                raise ValueError("Use exact /main_view/... paths without recursive // selectors")
            targets.append((control, path))
        return targets


def read_controls(index, client, controls, include_values=False, max_chars=1000, timeout=10):
    if not 1 <= max_chars <= 16384 or not 1 <= timeout <= 30:
        raise ValueError("Use max_chars 1-16384 and timeout 1-30 seconds")
    targets = index.resolve(controls)  # Validate every selector before contacting viewer.
    deadline = time.monotonic() + timeout
    results = []
    disconnected = False
    for control, path in targets:
        result = {"control": control, "path": path, "path_resolved": False}
        remaining = deadline - time.monotonic()
        if remaining < 0.05 or disconnected:
            result["error"] = "not_attempted_connection_lost" if disconnected else "not_attempted_budget_exhausted"
            results.append(result)
            continue
        try:
            info = client.call("LLWindow", "getInfo", {"path": path}, expect_reply=True, timeout=min(2, remaining))
            if not isinstance(info, dict) or info.get("error") or not isinstance(info.get("path"), str):
                raise ValueError("Viewer did not return control information")
            result.update(path_resolved=True, info={k: info[k] for k in
                          ("path", "class", "available", "visible", "visible_chain", "enabled", "enabled_chain", "rect") if k in info},
                          value_available=False)
            if include_values and info.get("visible_chain") is True and "value" in info:
                value = info["value"]
                encoded = json.dumps(value, ensure_ascii=False)
                if len(encoded) > max_chars:
                    result.update(value_preview=encoded[:max_chars], value_truncated=True)
                else:
                    result.update(value=value, value_available=True, value_truncated=False)
            elif include_values:
                result["value_reason"] = "hidden_or_unknown_visibility" if info.get("visible_chain") is not True else "not_exposed"
        except ConnectionError:
            result["error"] = "viewer_connection_lost"
            disconnected = True
        except (ValueError, RuntimeError, TimeoutError) as exc:
            result["error"] = str(exc)[:500]
        results.append(result)
    return {"controls": results, "evidence": "live_exact_path_readback", "atomic": False,
            "instance_identity_verified": False, "selection_changed": False,
            "note": "One getInfo per attempted path; no tree enumeration, focus, opening or input. Values may be stale; null is not an empty list or compiler success."}


def register_ui_map_tools(tools):
    index = UIMap(tools.viewer_dir)

    @tools.register("Search a cached local map of installed XUI control IDs, labels and tooltips, without contacting the viewer. Narrow by document. Candidate paths need ui_read verification; custom skins and duplicate instances are not verified.", True)
    def ui_map(query: str = "", document: str | None = None, limit: int = 30, offset: int = 0, refresh: bool = False):
        return index.search(query, document, limit, offset, refresh)

    @tools.register("List task IDs or retrieve a task guide and relevant source control IDs for scripts, Build, inventory, mesh previews or preferences. Does not open anything. Prefer listed semantic tools, then ui_read before UI input.", True)
    def ui_task(task: str | None = None):
        return index.task(task)

    @tools.register("Read 1-20 exact UI paths or ui_map IDs in one request, using targeted getInfo calls and a total viewer-wait budget. No tree scans or input. Values are opt-in, hidden values suppressed and long values truncated. Does not distinguish duplicate editor instances.", True)
    def ui_read(controls: list[str], include_values: bool = False, max_chars: int = 1000, timeout: float = 10):
        return read_controls(index, tools.client, controls, include_values, max_chars, timeout)
