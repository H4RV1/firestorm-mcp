"""Consumer regressions with synthetic UI replies; never contact a viewer."""
import pytest
from PIL import Image

from firestorm_mcp.assets import capture_quality
from firestorm_mcp.server import Tools


def test_search_names_depth_and_complete_pages(tmp_path):
    tools = Tools(tmp_path)
    base = "/panel/Physics"
    paths = [base, base + "/Physics tab"] + [base + f"/hidden/child{i:03}" for i in range(240)]
    tools.client.call = lambda *a, **k: {"paths": paths[::-1]}
    names = tools.call("ui_find", {"query": "physics", "under": base, "search_in": "name", "max_depth": 1})
    assert names["paths"] == [base, base + "/Physics tab"]
    first = tools.call("ui_find", {"query": "", "under": base, "limit": 200})
    assert first["truncated"] and first["next_offset"] == 200 and first["total_matches"] == 242
    last = tools.call("ui_find", {"query": "", "under": base, "offset": first["next_offset"]})
    assert not last["truncated"] and last["next_offset"] is None
    assert first["paths"] + last["paths"] == sorted(paths)
    exact = tools.call("ui_find", {"query": "PHYSICS TAB", "under": base, "match": "exact", "search_in": "name"})
    assert exact["paths"] == [base + "/Physics tab"]
    glob = tools.call("ui_find", {"query": "child00?", "under": base, "match": "glob", "search_in": "name"})
    assert len(glob["paths"]) == 10


def test_keys_require_target_and_hidden_target_never_receives_input(tmp_path):
    tools = Tools(tmp_path)
    calls = []
    def reply(api, op, args, **kw):
        calls.append(op)
        return {"visible_chain": False, "enabled_chain": True}
    tools.client.call = reply
    with pytest.raises(Exception, match="path.*required"):
        tools.call("ui_press_key", {"keysym": "Enter"})
    assert not calls
    with pytest.raises(ValueError, match="hidden"):
        tools.call("ui_press_key", {"keysym": "Enter", "path": "/hidden"})
    assert calls == ["getInfo"]


def test_uninspectable_search_item_does_not_discard_page(tmp_path):
    tools = Tools(tmp_path)
    paths = ["/panel/A", "/panel/Cosine%", "/panel/Z"]
    def reply(api, op, args, **kw):
        if op == "getPaths":
            return {"paths": paths}
        if args["path"].endswith("%"):
            raise ValueError("Viewer rejected this returned path")
        return {"path": args["path"], "available": True}
    tools.client.call = reply
    page = tools.call("ui_find", {"query": "", "under": "/panel", "limit": 2, "include_info": True})
    assert page["paths"] == paths[:2] and page["next_offset"] == 2
    assert page["info"][0]["available"] is True
    assert page["info"][1] == {"path": paths[1], "available": False, "error": "Viewer rejected this returned path"}


def test_keys_target_both_events_and_return_selection_readback(tmp_path):
    tools = Tools(tmp_path)
    selected = "High"
    sent = []
    def reply(api, op, args, **kw):
        nonlocal selected
        assert args["path"] == "/panel/lod"
        if op.startswith("key"):
            assert kw["expect_reply"] is True
            sent.append(op)
            selected = "Lowest"
        if op == "getValue":
            return {"value": selected}
        return {"visible_chain": True, "enabled_chain": True}
    tools.client.call = reply
    result = tools.call("ui_press_key", {"keysym": "End", "path": "/panel/lod"})
    assert sent == ["keyDown", "keyUp"]
    assert result["before"]["value"] == "High" and result["after"]["value"] == "Lowest"
    assert result["verified_effect"] is False


def test_native_key_rejection_stops_dispatch_without_retry(tmp_path):
    tools = Tools(tmp_path)
    calls = []
    def reply(api, op, args, **kw):
        calls.append(op)
        if op == "keyDown":
            raise ValueError("Object inventory is not ready; no key dispatched")
        return {"visible_chain": True, "enabled_chain": True}
    tools.client.call = reply
    with pytest.raises(ValueError, match="inventory is not ready"):
        tools.call("ui_press_key", {"keysym": "Enter", "path": "/synthetic/contents"})
    assert calls.count("keyDown") == 1
    assert calls[-1] == "keyDown" and "keyUp" not in calls


def test_registry_click_checks_unique_path_and_observes_effect(tmp_path):
    viewer = tmp_path / "viewer"
    xui = viewer / "skins/default/xui/en"
    xui.mkdir(parents=True)
    (xui / "preview.xml").write_text('<floater name="Preview"/>')
    tools = Tools(tmp_path, viewer)
    base = "/main_view/menu_stack/world_panel/Floater View/Preview"
    button, panel = base + "/Physics tab", base + "/physics"
    visible, duplicate = False, False
    clicks = []
    def reply(api, op, args=None, **kw):
        nonlocal visible
        if op == "getBuildMap":
            return {"preview": "preview.xml"}
        if op == "getPaths":
            return {"paths": [button, panel] + ([base + "/duplicate/Physics tab"] if duplicate else [])}
        if op == "clickButton":
            clicks.append(args)
            visible = True
            return {}
        if op == "getValue":
            return {}
        return {"visible_chain": visible if args["path"] == panel else True, "enabled_chain": True}
    tools.client.call = reply
    result = tools.call("ui_click", {"path": button, "floater": "preview", "observe_path": panel})
    assert result["method"] == "registry_callback"
    assert result["before"]["info"]["visible_chain"] is False
    assert result["after"]["info"]["visible_chain"] is True
    assert clicks == [{"name": "preview", "button": "Physics tab"}]
    duplicate = True
    with pytest.raises(ValueError, match="uniquely"):
        tools.call("ui_click", {"path": button, "floater": "preview"})
    assert len(clicks) == 1


@pytest.mark.parametrize("color", [(0, 0, 0), (1, 1, 2), (255, 255, 255), (100, 80, 60)])
def test_uniform_captures_are_flagged(color):
    result = capture_quality(Image.new("RGB", (32, 32), color))
    assert result["blank_detected"] and not result["visual_content_verified"]


def test_nonblank_capture_still_requires_visual_review(tmp_path):
    tools = Tools(tmp_path)
    def reply(api, op, args, **kw):
        frame = Image.new("RGB", (32, 32), "black")
        frame.paste("red", (8, 8, 24, 24))
        frame.save(args["filename"])
        return {"ok": True}
    tools.client.call = reply
    result = tools.call("snapshot", {})
    assert result["quality"]["status"] == "nonblank"
    assert result["quality"]["visual_content_verified"] is False
    assert result["requested_size"] == [1280, 720] and result["width"] == 32


@pytest.mark.parametrize("mode,mask", [("zoom", []), ("pan", ["CTL", "SHIFT"]), ("orbit", ["CTL"])])
def test_preview_camera_targets_bounded_rectangle_and_releases(tmp_path, monkeypatch, mode, mask):
    xui = tmp_path / "viewer/skins/default/xui/en"
    xui.mkdir(parents=True)
    (xui / "floater_model_preview.xml").write_text('<floater name="Preview"><panel name="preview_panel"/></floater>')
    tools = Tools(tmp_path, tmp_path / "viewer")
    calls = []
    def reply(api, op, args, **kw):
        assert api == "LLWindow" and args["path"].endswith("/Preview/preview_panel")
        calls.append((op, args))
        return {"visible_chain": True, "enabled_chain": True, "handled": True,
                "rect": {"left": 600, "right": 920, "bottom": 100, "top": 660}}
    tools.client.call = reply
    monkeypatch.setattr("firestorm_mcp.server.time.sleep", lambda _: None)
    result = tools.call("mesh_preview_camera", {"mode": mode, "vertical": 0.2})
    inputs = [(op, args) for op, args in calls if op.startswith("mouse")]
    assert [op for op, args in inputs] == ["mouseDown", "mouseMove", "mouseUp"]
    assert all(args["mask"] == mask for op, args in inputs)
    assert result["start_ui_pixels"] == [760, 380] and result["end_ui_pixels"] == [760, 492]
    assert not result["verified_effect"] and not result["camera_pose_observed"]
    calls.clear()
    with pytest.raises(ValueError, match="fractions"):
        tools.call("mesh_preview_camera", {"vertical": 1})
    assert calls == []


def test_failed_camera_move_still_releases_mouse(tmp_path):
    xui = tmp_path / "viewer/skins/default/xui/en"
    xui.mkdir(parents=True)
    (xui / "floater_model_preview.xml").write_text('<floater name="Preview"><panel name="preview_panel"/></floater>')
    tools = Tools(tmp_path, tmp_path / "viewer")
    operations = []
    def reply(api, op, args, **kw):
        operations.append(op)
        if op == "mouseMove":
            raise RuntimeError("synthetic movement failure")
        return {"visible_chain": True, "enabled_chain": True, "handled": True,
                "rect": {"left": 600, "right": 920, "bottom": 100, "top": 660}}
    tools.client.call = reply
    with pytest.raises(RuntimeError, match="synthetic"):
        tools.call("mesh_preview_camera", {})
    assert operations[-1] == "mouseUp"
