import concurrent.futures
import io
import socket
import threading
import time
import uuid

import pytest
import llsd

from firestorm_mcp.bridge import LeapBridge
from firestorm_mcp.protocol import encode_frame, read_frame, decode_typed


class Fragmented(io.BytesIO):
    def read(self, n=-1):
        return super().read(min(n, 3))


def test_modern_viewer_binary_greeting():
    data = {"pump": "reply", "data": {"command": "command", "features": {"binary": True}}}
    body = llsd.format_binary(data)
    assert read_frame(Fragmented(str(len(body)).encode() + b":" + body)) == data


def test_assets_cannot_bypass_another_client_lease(channel):
    bridge, _, _ = channel
    bridge.owner = 'other-client'
    bridge.owner_label = 'Synthetic owner'
    bridge.lease_until = time.monotonic() + 30
    result = bridge.handle({'method': 'call', 'client_id': 'consumer',
                            'api': 'FSMCPAssets', 'op': 'submit', 'arguments': {}})
    assert result['failure']['code'] == 'lease_conflict'
    assert result['failure']['unknownOutcome'] is False


def test_assets_gateway_required_even_via_viewer_call(channel):
    bridge, _, _ = channel
    with pytest.raises(RuntimeError, match='gateway/journal'):
        bridge.handle({'method': 'call', 'client_id': 'consumer',
                       'api': 'FSMCPAssets', 'op': 'submit', 'arguments': {}})


@pytest.mark.parametrize("offset", [5000, 16377, 73721])
def test_windows_apr_duplicate_chunk_recovery(offset):
    data = {"pump": "reply", "data": {"reqid": "test-id", "paths": ["/test/panel/" + str(i) + "/" + "x" * 97 for i in range(1000)]}}
    body = llsd.format_binary(data)
    damaged = body[:offset] + body[offset - 4096:offset] + body[offset:]
    next_frame = encode_frame("reply", {"next": True})
    stream = io.BytesIO(str(len(body)).encode() + b":" + damaged + next_frame)
    actual = read_frame(stream)
    assert actual.pop("_leap_repaired_duplicate_blocks") == 1
    assert actual == data
    assert read_frame(stream)["data"] == {"next": True}


def test_valid_repeated_content_is_not_repaired():
    data = {"pump": "reply", "data": {"content": "x" * 16384}}
    body = llsd.format_binary(data)
    assert read_frame(io.BytesIO(str(len(body)).encode() + b":" + body)) == data


def test_two_duplicate_pipe_chunks():
    data = {"pump": "reply", "data": {"paths": ["/panel/" + str(i) + "/" + "abc" * 40 for i in range(1000)]}}
    body = llsd.format_binary(data)
    offset = 73721
    damaged = body[:offset] + body[offset - 4096:offset] * 2 + body[offset:]
    result = read_frame(io.BytesIO(str(len(body)).encode() + b":" + damaged))
    assert result.pop("_leap_repaired_duplicate_blocks") == 2
    assert result == data


def test_unicode_and_typed_partial_frame():
    uid = uuid.uuid4()
    payload = decode_typed({"text": "木材 café 🦊", "id": {"$uuid": str(uid)}, "binary": {"$binary_base64": "AAE="}})
    frame = encode_frame("test", payload)
    prefix, body = frame.split(b":", 1)
    assert int(prefix) == len(body)
    assert read_frame(Fragmented(frame)) == {"pump": "test", "data": payload}


@pytest.mark.parametrize("frame", [b"0:", b"-1:", b"x:", b"9999999999:", b"16777217:", b"10:short"])
def test_bad_frames(frame):
    with pytest.raises((EOFError, ValueError)):
        read_frame(io.BytesIO(frame))


@pytest.fixture
def channel():
    a, b = socket.socketpair()
    incoming, outgoing = a.makefile("rb", buffering=0), a.makefile("wb", buffering=0)
    viewer_in, viewer_out = b.makefile("rb", buffering=0), b.makefile("wb", buffering=0)
    viewer_out.write(encode_frame("reply", {"command": "command"}))
    bridge = LeapBridge(incoming, outgoing)
    yield bridge, viewer_in, viewer_out
    b.shutdown(socket.SHUT_RDWR)
    bridge.reader.join(1)
    for stream in (incoming, outgoing, viewer_in, viewer_out):
        stream.close()
    a.close()
    b.close()


def respond(outgoing, request, value, correlated=True):
    data = {**value}
    if correlated:
        data["reqid"] = request["data"]["reqid"]
    outgoing.write(encode_frame(request["data"]["reply"], data))


def test_script_assertion_requires_same_active_connected_lease(channel, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr("firestorm_mcp.bridge.parent_viewer", lambda: SimpleNamespace(pid=123))
    bridge, _, _ = channel
    with pytest.raises(RuntimeError, match="lease"):
        bridge.handle({"method": "assert_control", "client_id": "one"})
    bridge.handle({"method": "acquire", "client_id": "one", "label": "synthetic writer", "seconds": 30})
    assert bridge.handle({"method": "assert_control", "client_id": "one"}) == {"connected": True, "viewer_pid": 123}
    with pytest.raises(RuntimeError, match="held by"):
        bridge.handle({"method": "assert_control", "client_id": "two"})
    bridge.connected = False
    with pytest.raises(RuntimeError, match="lease"):
        bridge.handle({"method": "assert_control", "client_id": "one"})
    bridge.handle({"method": "release", "client_id": "one"})


def test_out_of_order_responses_and_unsolicited_event(channel):
    bridge, incoming, outgoing = channel
    with concurrent.futures.ThreadPoolExecutor() as pool:
        one = pool.submit(bridge.request, "api", {"op": "one"})
        first = read_frame(incoming)
        two = pool.submit(bridge.request, "api", {"op": "two"})
        second = read_frame(incoming)
        outgoing.write(encode_frame("events", {"state": "ready"}))
        respond(outgoing, second, {"value": 2})
        respond(outgoing, first, {"value": 1})
        assert one.result(1) == {"value": 1}
        assert two.result(1) == {"value": 2}
    assert bridge.handle({"method": "events"})["events"][0]["data"] == {"state": "ready"}


def test_late_response_never_completes_new_request(channel):
    bridge, incoming, outgoing = channel
    with pytest.raises(TimeoutError, match="may have occurred"):
        bridge.request("api", {"op": "old"}, timeout=0.01)
    old = read_frame(incoming)
    with concurrent.futures.ThreadPoolExecutor() as pool:
        current = pool.submit(bridge.request, "api", {"op": "new"})
        new = read_frame(incoming)
        respond(outgoing, old, {"wrong": True})
        respond(outgoing, new, {"correct": True})
        assert current.result(1) == {"correct": True}


def test_bad_llsd_request_fails_but_next_frame_works(channel):
    bridge, incoming, outgoing = channel
    with concurrent.futures.ThreadPoolExecutor() as pool:
        damaged = pool.submit(bridge.request, "api", {"op": "damaged"})
        read_frame(incoming)
        outgoing.write(b"3:bad")
        with pytest.raises(ValueError, match="Malformed viewer reply"):
            damaged.result(1)
        next_request = pool.submit(bridge.request, "api", {"op": "next"})
        request = read_frame(incoming)
        respond(outgoing, request, {"ok": True})
        assert next_request.result(1) == {"ok": True}
        assert bridge.connected
        assert bridge.decode_errors == 1


def test_uncorrelated_button_response_has_unique_pump(channel):
    bridge, incoming, outgoing = channel
    with concurrent.futures.ThreadPoolExecutor() as pool:
        result = pool.submit(bridge.request, "LLFloaterReg", {"op": "clickButton"}, 1, True)
        create = read_frame(incoming)
        assert create["data"]["op"] == "newpump"
        respond(outgoing, create, {"name": "isolated-reply"})
        click = read_frame(incoming)
        assert click["data"]["reply"] == "isolated-reply"
        respond(outgoing, click, {"ok": True}, correlated=False)
        assert result.result(1) == {"ok": True}
        assert read_frame(incoming)["data"]["op"] == "stoplistening"


def test_control_lease(channel):
    bridge, _, _ = channel
    assert bridge.handle({"method": "acquire", "client_id": "one", "label": "blender"})["acquired"]
    with pytest.raises(RuntimeError, match="held by blender"):
        bridge.handle({"method": "acquire", "client_id": "two"})
    with pytest.raises(RuntimeError, match="controlling"):
        bridge.handle({"method": "release", "client_id": "two"})
    assert bridge.handle({"method": "release", "client_id": "one"})["released"]


def test_crash_prone_inputs_rejected(channel):
    bridge, _, _ = channel
    bridge.apis = {"UI": {"ops": [{"name": "call"}]}, "LLViewerWindow": {"ops": [{"name": "saveSnapshot"}]}}
    with pytest.raises(ValueError, match="crash"):
        bridge.call("UI", "call", {"function": "does-not-exist"})
    with pytest.raises(ValueError, match="Snapshot type"):
        bridge.call("LLViewerWindow", "saveSnapshot", {"type": "BOGUS"})
