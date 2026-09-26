"""Synthetic UI navigation tests: no viewer, installed profiles or live bridge."""
import json
import os
from pathlib import Path

import pytest

from firestorm_mcp.server import Tools
from firestorm_mcp.ui_map import FLOATER_ROOT, UIMap, read_controls


@pytest.fixture
def viewer(tmp_path):
    directory = tmp_path / "viewer/skins/default/xui/en"
    directory.mkdir(parents=True)
    (directory / "floater_live_lsleditor.xml").write_text('''<floater name="script ed float">
      <floater.string name="not a control">Private source string</floater.string>
      <text name="obj_name"/><panel name="script ed panel"/>
      <check_box name="running" label="Running"/>
    </floater>''', encoding="utf-8")
    (directory / "panel_script_ed.xml").write_text('''<panel name="script panel">
      <text_editor name="Script Editor"/><button name="edit_btn_2" label="Edit..." tool_tip="External editor"/>
      <scroll_list name="lsl errors"><column name="Error"/></scroll_list>
    </panel>''', encoding="utf-8")
    return directory.parents[3]


def test_task_map_expands_factory_without_viewer_contact(viewer, tmp_path):
    tools = Tools(tmp_path / "state", viewer)
    tools.client.call = lambda *a, **kw: pytest.fail("Offline map must not contact viewer")
    tools.client.rpc = tools.client.call
    assert len(tools.call("ui_task", {})["tasks"]) == 6
    task = tools.call("ui_task", {"task": "script_object"})
    edit = next(e for e in task["controls"] if e["name"] == "edit_btn_2")
    assert edit["source"] == "panel_script_ed.xml"
    assert edit["candidate_path"] == FLOATER_ROOT + "/script ed float/script ed panel/edit_btn_2"
    assert not edit["live_verified"] and not task["live_contacted"]
    page = tools.call("ui_map", {"query": "external editor", "document": "floater_live_lsleditor.xml"})
    assert page["controls"] == [edit]
    assert not tools.call("ui_map", {"query": "not a control"})["controls"]
    assert not tools.call("ui_map", {"query": "Error", "document": "panel_script_ed.xml"})["controls"][0]["candidate_path"]


def test_cache_invalidates_and_refresh_handles_preserved_mtime(viewer):
    index = UIMap(viewer)
    first = index.search("Running")
    assert not first["cache_hit"] and index.search("Running")["cache_hit"]
    document = index.directory / "floater_live_lsleditor.xml"
    previous = document.stat()
    document.write_text(document.read_text().replace('label="Running"', 'label="Stopped"'))
    os.utime(document, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    changed = index.search("Stopped", refresh=True)
    assert not changed["cache_hit"] and changed["revision"] != first["revision"]
    assert changed["controls"][0]["id"] == first["controls"][0]["id"]
    document.write_text(document.read_text().replace('label="Stopped"', 'label="New label"'))
    assert index.search("New label")["controls"]


def test_includes_overrides_pagination_and_path_escaping(viewer):
    directory = UIMap(viewer).directory
    (directory / "part.xml").write_text('<panel name="ignored"><button name="a/b%" label="Original"/><button name="second"/></panel>')
    (directory / "example.xml").write_text('<floater name="Test"><panel name="Mount" filename="part.xml"><button name="second" label="Override"/></panel></floater>')
    index = UIMap(viewer)
    page = index.search(document="example.xml", limit=2)
    rest = index.search(document="example.xml", offset=page["next_offset"], limit=2)
    entries = page["controls"] + rest["controls"]
    assert len(entries) == page["total_matches"] == 4
    assert next(e for e in entries if e["name"] == "a/b%")["candidate_path"].endswith('/Mount/a%2Fb%25')
    assert next(e for e in entries if e["name"] == "second")["label"] == "Override"
    assert rest["next_offset"] is None


def test_broken_cyclic_and_traversal_includes_are_reported(viewer):
    directory = UIMap(viewer).directory
    (directory / "bad.xml").write_text('<floater')
    (directory / "cycle.xml").write_text('<floater name="Cycle"><panel name="child" filename="cycle.xml"/></floater>')
    (directory / "escape.xml").write_text('<floater name="Escape"><panel name="child" filename="../secret.xml"/></floater>')
    result = UIMap(viewer).search()
    assert result["warning_count"] == 3
    assert {w["reason"] for w in result["warnings"]} == {"invalid_xml", "unresolved_or_cyclic_include"}


def test_entity_declarations_rejected(viewer):
    (UIMap(viewer).directory / "entity.xml").write_text('<!DOCTYPE x [<!ENTITY x "text">]><floater name="a"/>')
    with pytest.raises(ValueError, match="entity"):
        UIMap(viewer).load()


def test_duplicate_source_paths_not_silently_resolved(viewer):
    (UIMap(viewer).directory / "dupes.xml").write_text('''<floater name="Duplicate">
      <button name="same"/><button name="same"/>
      <panel name="Parent"><button name="unique"/></panel><panel name="Parent"/>
    </floater>''')
    index = UIMap(viewer)
    entries = index.search("same", document="dupes.xml")["controls"]
    assert len(entries) == 2 and entries[0]["id"] != entries[1]["id"]
    assert all(e["source_path_ambiguous"] for e in entries)
    with pytest.raises(ValueError, match="unambiguous"):
        index.resolve([entries[0]["id"]])
    child = index.search("unique", document="dupes.xml")["controls"][0]
    assert child["source_path_ambiguous"]
    with pytest.raises(ValueError, match="unambiguous"):
        index.resolve([child["id"]])


def test_exact_reads_do_not_enumerate_and_values_are_opt_in(viewer, tmp_path):
    tools = Tools(tmp_path / "state", viewer)
    controls = tools.call("ui_task", {"task": "script_object"})["controls"]
    ids = [e["id"] for e in controls if e["name"] in {"running", "Script Editor"}]
    calls = []
    def reply(api, op, args, **kw):
        calls.append((api, op, args, kw))
        assert (api, op) == ("LLWindow", "getInfo")
        return {"path": args["path"], "visible_chain": True, "enabled_chain": True,
                "value": "private source", "class": "test"}
    tools.client.call = reply
    result = tools.call("ui_read", {"controls": ids})
    assert len(calls) == 2 and all(c[3]["timeout"] <= 2 for c in calls)
    assert "private source" not in json.dumps(result)
    assert all(r["path_resolved"] for r in result["controls"])
    assert not result["atomic"] and not result["instance_identity_verified"]
    values = tools.call("ui_read", {"controls": ids, "include_values": True})
    assert values["controls"][0]["value"] == "private source"


def test_partial_errors_hidden_null_and_truncation(viewer):
    class Client:
        def call(self, api, op, args, **kw):
            name = args["path"].split('/')[-1]
            if name == "gone":
                raise ValueError("no such view")
            return {"path": args["path"], "visible_chain": name != "hidden", "value": None if name == "null" else "secret" * 50}
    paths = ['/main_view/test/' + name for name in ('gone', 'hidden', 'null', 'long')]
    results = read_controls(UIMap(viewer), Client(), paths, True, 30)["controls"]
    assert results[0]["path_resolved"] is False
    assert "value" not in results[1] and "secret" not in json.dumps(results[1])
    assert results[2]["value"] is None  # Never coerce null to [] or false.
    assert results[3]["value_truncated"] and len(results[3]["value_preview"]) == 30
    assert not results[3]["value_available"]


def test_selectors_validated_before_any_live_call(viewer):
    class Client:
        def call(self, *a, **kw):
            pytest.fail("Invalid batch must not partly dispatch")
    for controls in [[], ['/main_view/a'] * 2, ['/main_view/a', 'xui:unknown'], ['/main_view//recursive']]:
        with pytest.raises(ValueError):
            read_controls(UIMap(viewer), Client(), controls)


def test_read_budget_and_disconnect_stop_further_calls(viewer, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr('firestorm_mcp.ui_map.time.monotonic', lambda: clock[0])
    class Client:
        calls = 0
        def call(self, api, op, args, **kw):
            self.calls += 1
            clock[0] += 2
            return {"path": args["path"], "visible_chain": True}
    client = Client()
    result = read_controls(UIMap(viewer), client, ['/main_view/a', '/main_view/b'], timeout=1)
    assert client.calls == 1 and result["controls"][1]["error"] == 'not_attempted_budget_exhausted'
    class Disconnected:
        calls = 0
        def call(self, *a, **kw):
            self.calls += 1
            raise ConnectionError('offline')
    client = Disconnected()
    result = read_controls(UIMap(viewer), client, ['/main_view/a', '/main_view/b'])
    assert client.calls == 1 and result["controls"][1]["error"] == 'not_attempted_connection_lost'


@pytest.mark.parametrize('under', ['/', '/main_view', FLOATER_ROOT, FLOATER_ROOT + '/', '/main_view//Inventory',
                                    FLOATER_ROOT.replace(' ', '%20'), '/%6dain_view'])
def test_broad_scans_rejected_without_viewer_contact(tmp_path, under):
    tools = Tools(tmp_path)
    tools.client.call = lambda *a, **kw: pytest.fail("Broad scan reached viewer")
    with pytest.raises(ValueError, match="Broad"):
        tools.call('ui_find', {"query": "button", "under": under})
