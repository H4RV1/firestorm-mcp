"""Wire-level tests independent of the Python client SDK; never use a live viewer."""
import base64
from contextlib import contextmanager
import io
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer

from PIL import Image
import pytest

from firestorm_mcp.bridge import make_handler
from firestorm_mcp.server import Tools, UnknownToolError, result_content

VERSIONS = ["2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28"]
FIXTURE = Path(__file__).parent / "fixtures/synthetic-cube.dae"


class Wire:
    def __init__(self, process, version):
        self.process, self.version = process, version
        self.messages = queue.Queue()
        self.notifications = []
        self.counter = 0
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        for line in self.process.stdout:
            try:
                self.messages.put(json.loads(line))
            except ValueError:
                self.messages.put({"invalid_stdout": line})

    def receive(self):
        message = self.messages.get(timeout=10)
        assert "invalid_stdout" not in message, "Non-JSON content contaminated MCP stdout"
        return message

    def send(self, method, params=None, notification=False):
        params = dict(params or {})
        if self.version == "2026-07-28":
            params["_meta"] = {
                "io.modelcontextprotocol/protocolVersion": self.version,
                "io.modelcontextprotocol/clientCapabilities": {},
            }
        message = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notification:
            self.counter += 1
            message["id"] = self.counter
        self.process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self.process.stdin.flush()
        return message.get("id")

    def request(self, method, params=None):
        request_id = self.send(method, params)
        while True:
            message = self.receive()
            if message.get("id") == request_id:
                return message
            self.notifications.append(message)

    def connect(self):
        if self.version == "2026-07-28":
            response = self.request("server/discover")
            info = response["result"]["_meta"]["io.modelcontextprotocol/serverInfo"]
            assert self.version in response["result"]["supportedVersions"]
        else:
            response = self.request("initialize", {
                "protocolVersion": self.version, "capabilities": {},
                "clientInfo": {"name": "firestorm-offline-test", "version": "1"},
            })
            assert response["result"]["protocolVersion"] == self.version
            info = response["result"]["serverInfo"]
            self.send("notifications/initialized", notification=True)
        assert info["name"] == "firestorm-mcp"
        assert response["result"]["capabilities"]["tools"]["listChanged"] is True
        return response["result"]


@contextmanager
def wire_server(root, version="2026-07-28", profile="all"):
    root.mkdir(parents=True, exist_ok=True)
    with (root / "server-stderr.txt").open("w", encoding="utf-8") as errors:
        process = subprocess.Popen([
            sys.executable, "-m", "firestorm_mcp.server", "--data-dir", str(root),
            "--tool-profile", profile,
        ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
            text=True, encoding="utf-8", bufsize=1)
        wire = Wire(process, version)
        try:
            yield wire
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                # This is only our synthetic MCP subprocess, never a viewer process.
                process.kill()
                process.wait(timeout=3)
                pytest.fail("MCP did not stop after stdin closed")
            wire.reader.join(2)
            process.stdout.close()


@pytest.mark.parametrize("version", VERSIONS)
def test_wire_versions_validation_images_and_clean_stdout(tmp_path, version):
    root = tmp_path / "state with spaces"
    with wire_server(root, version) as wire:
        wire.connect()
        listed = wire.request("tools/list")["result"]
        names = [tool["name"] for tool in listed["tools"]]
        assert names == sorted(names) and len(names) == 72
        if version == "2026-07-28":
            assert listed["ttlMs"] == 0 and listed["cacheScope"] == "private"
            assert listed["resultType"] == "complete"
        status = wire.request("tools/call", {"name": "connection_status", "arguments": {}})["result"]
        assert not status["isError"] and json.loads(status["content"][0]["text"])["connected"] is False
        missing = wire.request("tools/call", {"name": "does_not_exist"})
        assert missing["error"]["code"] == -32602
        invalid = wire.request("tools/call", {"name": "asset_inspect", "arguments": {}})["result"]
        assert invalid["isError"] is True
        extra = wire.request("tools/call", {"name": "connection_status", "arguments": {"typo": True}})["result"]
        assert extra["isError"] is True
        inspected = wire.request("tools/call", {"name": "asset_inspect", "arguments": {"filename": str(FIXTURE.resolve())}})["result"]
        assert json.loads(inspected["content"][0]["text"])["declared_triangles"] == 12
        if version >= "2025-06-18":
            assert inspected["structuredContent"]["declared_triangles"] == 12
        a, b = root / "caf\u00e9-a.png", root / "caf\u00e9-b.png"
        Image.new("RGB", (16, 16), "red").save(a)
        Image.new("RGB", (16, 16), "blue").save(b)
        compared = wire.request("tools/call", {"name": "image_compare", "arguments": {"reference": str(a), "observed": str(b)}})["result"]
        assert not compared["isError"]
        block = next(part for part in compared["content"] if part["type"] == "image")
        assert block["mimeType"] == "image/png"
        with Image.open(io.BytesIO(base64.b64decode(block["data"]))) as image:
            assert image.size == (16, 16)
        assert "_image_path" not in compared["content"][0]["text"]


@pytest.fixture
def mock_runtime(tmp_path):
    class FakeViewer:
        def __init__(self):
            self.requests = []
        def handle(self, request):
            self.requests.append(request)
            if request["method"] == "discover":
                return {"TestViewer": {"ops": [{"name": "getValue", "required": {"reply": None}, "desc": "Read a synthetic value"}]}}
            if request["method"] == "call":
                return {"value": "synthetic"}
            return {"connected": True}
    viewer = FakeViewer()
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(viewer, "synthetic-test-token"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state = tmp_path / "mock-state"
    (state / "runtime").mkdir(parents=True)
    (state / "runtime/connection.json").write_text(json.dumps({
        "url": f"http://127.0.0.1:{server.server_port}/rpc", "token": "synthetic-test-token",
    }), encoding="utf-8")
    try:
        yield state, viewer
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


@pytest.mark.parametrize("version", ["2025-11-25", "2026-07-28"])
def test_refresh_notifies_negotiated_clients_and_validates_dynamic_tools(mock_runtime, version):
    state, viewer = mock_runtime
    with wire_server(state, version) as wire:
        wire.connect()
        assert viewer.requests == []  # Startup must not contact even a reachable viewer.
        if version == "2026-07-28":
            wire.send("subscriptions/listen", {"notifications": {"toolsListChanged": True}})
            assert wire.receive()["method"] == "notifications/subscriptions/acknowledged"
        refresh = wire.request("tools/call", {"name": "capabilities_refresh"})["result"]
        assert not refresh["isError"]
        if not wire.notifications:
            wire.notifications.append(wire.receive())
        assert any(note.get("method") == "notifications/tools/list_changed" for note in wire.notifications)
        names = [tool["name"] for tool in wire.request("tools/list")["result"]["tools"]]
        assert "viewer_TestViewer_getValue" in names
        calls_before = len(viewer.requests)
        invalid = wire.request("tools/call", {"name": "viewer_TestViewer_getValue", "arguments": {"timeout": 1000}})["result"]
        assert invalid["isError"] and len(viewer.requests) == calls_before
        read = wire.request("tools/call", {"name": "viewer_TestViewer_getValue", "arguments": {}})["result"]
        assert read["structuredContent"] == {"value": "synthetic"}


def test_compact_profile_keeps_generic_access_without_expanding_catalog(mock_runtime):
    state, viewer = mock_runtime
    with wire_server(state, profile="compact") as wire:
        wire.connect()
        wire.request("tools/call", {"name": "capabilities_refresh"})
        assert len(wire.request("tools/list")["result"]["tools"]) == 72
        result = wire.request("tools/call", {"name": "viewer_call", "arguments": {"api": "TestViewer", "operation": "getValue"}})["result"]
        assert result["structuredContent"]["value"] == "synthetic"
        assert not wire.notifications


def test_unknown_tools_and_image_results_do_not_mutate_state(tmp_path):
    tools = Tools(tmp_path)
    tools.client.rpc = lambda *a, **kw: pytest.fail("Unknown tool attempted viewer discovery")
    with pytest.raises(UnknownToolError):
        tools.call("made_up_name", {})
    filename = tmp_path / "image.png"
    Image.new("RGB", (16, 16)).save(filename)
    value = {"_image_path": str(filename), "ok": True}
    assert len(result_content(value)) == 2
    assert "_image_path" in value


def test_cancelled_queued_call_does_not_reach_viewer(mock_runtime):
    state, viewer = mock_runtime
    entered, proceed = threading.Event(), threading.Event()
    original = viewer.handle

    def blocking_status(request):
        if request["method"] == "status":
            entered.set()
            assert proceed.wait(5)
        return original(request)

    viewer.handle = blocking_status
    try:
        with wire_server(state) as wire:
            wire.connect()
            running = wire.send("tools/call", {"name": "connection_status"})
            assert entered.wait(5)
            queued = wire.send("tools/call", {"name": "viewer_call", "arguments": {"api": "TestViewer", "operation": "getValue"}})
            wire.send("notifications/cancelled", {"requestId": queued, "reason": "synthetic queued cancellation"}, notification=True)
            # A separate request proves the transport remains responsive while
            # one viewer operation is in flight and its successor is cancelled.
            assert len(wire.request("tools/list")["result"]["tools"]) == 72
            proceed.set()
            assert wire.receive()["id"] == running
            wire.request("tools/list")
            assert [item["method"] for item in viewer.requests] == ["status"]
    finally:
        proceed.set()
