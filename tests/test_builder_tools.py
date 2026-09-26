import json
import os
from pathlib import Path
import time
import uuid
import xml.etree.ElementTree as ET

import pytest

from firestorm_mcp import script_workspace as sw
from firestorm_mcp.launcher import session_settings
from firestorm_mcp.server import Tools


@pytest.fixture
def script(tmp_path, monkeypatch):
    monkeypatch.setattr(sw.tempfile, "gettempdir", lambda: str(tmp_path))
    identity = {"pid": 123, "started": 100.0}
    monkeypatch.setattr(sw, "viewer_identity", lambda pid: identity)
    path = tmp_path / ("sl_script_Test_" + "a" * 32 + ".lsl")
    path.write_bytes(b'default { state_entry() {} }\r\n')
    os.utime(path, (time.time() - 3, time.time() - 3))
    workspace = sw.ScriptWorkspace(tmp_path / "state")
    record = workspace.register(path, identity)
    return workspace, record["session_id"], path


def test_script_unicode_backup_and_hash_conflict(script):
    workspace, sid, path = script
    old = workspace.read(sid)
    new = '// café 木材\n' + old["source"]
    result = workspace.write(sid, new, old["sha256"], 123)
    assert result["file_write_verified"]
    assert not result["compile_verified"] and not result["simulator_save_verified"]
    assert Path(result["backup_path"]).read_bytes() == old["source"].encode()
    assert path.read_bytes() == new.encode()
    assert workspace.read(sid)["sha256"] == result["sha256"]
    with pytest.raises(ValueError, match="changed since"):
        workspace.write(sid, "stale edit", old["sha256"], 123)
    assert path.read_bytes() == new.encode()


def test_unregistered_files_never_listed_or_read(script):
    workspace, sid, path = script
    (path.parent / "private.lsl").write_text("not a registered file")
    assert [r["session_id"] for r in workspace.list()["sessions"]] == [sid]
    with pytest.raises(ValueError, match="Invalid script"):
        workspace.read("../../private")
    with pytest.raises(ValueError, match="Unrecognized"):
        workspace.register(path.parent / "private.lsl", {"pid": 123, "started": 100.0})


def test_script_deleted_or_viewer_restarted_is_stale(script, monkeypatch):
    workspace, sid, path = script
    monkeypatch.setattr(sw, "viewer_identity", lambda pid: {"pid": pid, "started": 101.0})
    with pytest.raises(ValueError, match="Viewer session has ended"):
        workspace.read(sid)
    assert workspace.list()["sessions"][0]["active_file"] is False
    path.unlink()
    assert workspace.list()["sessions"][0]["active_file"] is False


def test_file_replacement_invalidates_session(script):
    workspace, sid, path = script
    replacement = path.with_suffix(".tmp")
    replacement.write_text("replacement")
    os.replace(replacement, path)
    with pytest.raises(ValueError, match="replaced"):
        workspace.read(sid)


def test_other_viewer_and_foreign_lock_cannot_write(script):
    workspace, sid, path = script
    original = workspace.read(sid)
    with pytest.raises(ValueError, match="different viewer"):
        workspace.write(sid, "change", original["sha256"], 124)
    lock = workspace.sessions / (sid + ".lock")
    lock.write_text("another process")
    with pytest.raises(FileExistsError):
        workspace.write(sid, "change", original["sha256"], 123)
    assert lock.read_text() == "another process"
    assert workspace.read(sid)["sha256"] == original["sha256"]


def test_unchanged_script_does_not_trigger_save(script):
    workspace, sid, path = script
    old = workspace.read(sid)
    stat = path.stat()
    assert workspace.write(sid, old["source"], old["sha256"], 123)["status"] == "unchanged"
    assert path.stat().st_mtime_ns == stat.st_mtime_ns
    assert not (workspace.root / "backups").exists()


def test_future_timestamp_is_not_silently_missed(script):
    workspace, sid, path = script
    old = workspace.read(sid)
    os.utime(path, (time.time() + 100, time.time() + 100))
    with pytest.raises(ValueError, match="future"):
        workspace.write(sid, "change", old["sha256"], 123)
    assert workspace.read(sid)["sha256"] == old["sha256"]


def test_human_edit_during_watcher_delay_is_preserved(script, monkeypatch):
    workspace, sid, path = script
    old = workspace.read(sid)
    now = time.time()
    os.utime(path, (now, now))
    monkeypatch.setattr(sw.time, "sleep", lambda seconds: path.write_text("human edit"))
    with pytest.raises(ValueError, match="changed while"):
        workspace.write(sid, "agent edit", old["sha256"], 123)
    assert path.read_text() == "human edit"


def test_script_settings_are_opt_in_and_preserve_spaces(tmp_path):
    args = (tmp_path / "Python Path/python.exe", tmp_path / "leap_entry.py",
            tmp_path / "State Path/runtime", tmp_path / "Viewer Path")
    plain = session_settings(*args)
    assert "ExternalEditor" not in plain
    configured = ET.fromstring(session_settings(*args, script_editor=True))
    serialized = ET.tostring(configured, encoding="unicode")
    assert "ExternalEditor" in serialized and '"%s"' in serialized
    assert "State Path" in serialized and "script_entry.py" in serialized


def test_script_write_requires_bridge_lease_first(script):
    workspace, sid, path = script
    tools = Tools(workspace.root.parent)
    def deny(*a, **kw):
        raise RuntimeError("Acquire an active viewer control lease")
    tools.client.rpc = deny
    original = workspace.read(sid)
    with pytest.raises(RuntimeError, match="lease"):
        tools.call("script_write", {"session_id": sid, "source": "change", "expected_sha256": original["sha256"]})
    assert workspace.read(sid)["sha256"] == original["sha256"]


def test_native_tools_fail_explicitly_on_stock_viewer(tmp_path):
    tools = Tools(tmp_path)
    tools.client.rpc = lambda *a, **kw: {}
    with pytest.raises(ValueError, match="does not expose FSMCPBuilder"):
        tools.call("object_faces", {"object_id": str(uuid.uuid4())})
    with pytest.raises(ValueError):
        tools.call("object_linkset", {"object_id": "not-an-id"})


def test_native_face_request_uses_typed_uuid(tmp_path):
    tools = Tools(tmp_path)
    tools.client.apis = {"FSMCPBuilder": {"ops": [{"name": "getFaces"}]}}
    calls = []
    tools.client.call = lambda *a, **kw: calls.append((a, kw)) or {"schema_version": 1, "faces": []}
    oid = str(uuid.uuid4())
    assert tools.call("object_faces", {"object_id": oid}) == {"schema_version": 1, "faces": []}
    assert calls[0][0] == ("FSMCPBuilder", "getFaces", {"object_id": {"$uuid": oid}})
    assert calls[0][1]["expect_reply"] is True


def test_native_incompatible_schema_rejected(tmp_path):
    tools = Tools(tmp_path)
    tools.client.apis = {"FSMCPBuilder": {"ops": [{"name": "getSelection"}]}}
    tools.client.call = lambda *a, **kw: {"schema_version": 2, "objects": []}
    with pytest.raises(ValueError, match="response schema"):
        tools.call("object_selection", {})


def test_latency_is_bounded_and_reports_only_event_loop(tmp_path):
    tools = Tools(tmp_path)
    calls = []
    tools.client.rpc = lambda method: calls.append(method) or {}
    report = tools.call("viewer_latency", {"samples": 3})
    assert calls == ["ping"] * 3
    assert report["median_ms"] >= 0 and not report["simulator_latency_measured"]
    with pytest.raises(ValueError):
        tools.call("viewer_latency", {"samples": 100})
