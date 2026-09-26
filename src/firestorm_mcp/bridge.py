"""Viewer-owned LEAP child. Its HTTP endpoint is an authenticated local IPC channel."""
from __future__ import annotations

import argparse
import collections
import concurrent.futures
import hmac
import json
import logging
import os
from pathlib import Path
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import uuid
import xml.etree.ElementTree as ET

from .protocol import FrameDecodeError, decode_typed, encode_frame, json_default, read_frame
from .paths import viewer_directory
from .process_identity import parent_viewer

LOG = logging.getLogger(__name__)


class LeapBridge:
    def __init__(self, incoming, outgoing):
        self.incoming, self.outgoing = incoming, outgoing
        hello = read_frame(incoming)
        self.reply_pump = str(hello["pump"])
        self.command_pump = str(hello["data"]["command"])
        self.features = hello["data"].get("features", {})
        self.pending: dict[str, concurrent.futures.Future] = {}
        self.lock = threading.RLock()
        self.write_lock = threading.Lock()
        self.operation_lock = threading.RLock()
        self.connected = True
        self.sequence = 0
        self.events = collections.deque(maxlen=1000)
        self.apis = {}
        self.started = time.time()
        self.generation = str(uuid.uuid4())
        self.assets = None
        self.viewer_dir = viewer_directory()
        self.owner = None
        self.owner_label = None
        self.lease_until = 0
        self.decode_errors = 0
        self.repaired_duplicate_blocks = 0
        self.debug_protocol_dir = None
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()

    def _read_loop(self):
        try:
            while True:
                try:
                    event = read_frame(self.incoming)
                except FrameDecodeError as exc:
                    self.decode_errors += 1
                    if self.debug_protocol_dir:
                        (self.debug_protocol_dir / "last-invalid-frame.bin").write_bytes(exc.body)
                    with self.lock:
                        for future in self.pending.values():
                            if not future.done():
                                future.set_exception(ValueError("Malformed viewer reply; the request result is unknown. Inspect state before retrying."))
                        self.pending.clear()
                    LOG.warning("Rejected malformed LLSD frame (%d bytes); connection retained", len(exc.body))
                    continue
                self.repaired_duplicate_blocks += event.pop("_leap_repaired_duplicate_blocks", 0)
                data = event["data"]
                reqid = str(data.get("reqid", "")) if isinstance(data, dict) else ""
                with self.lock:
                    future = self.pending.pop(reqid, None)
                    if future is None:
                        future = self.pending.pop("pump:" + str(event["pump"]), None)
                    if future is not None:
                        if not future.done():
                            future.set_result(data)
                    else:
                        self.sequence += 1
                        self.events.append({"cursor": self.sequence, "timestamp": time.time(), **event})
        except Exception as exc:
            self.connected = False
            with self.lock:
                for future in self.pending.values():
                    if not future.done():
                        future.set_exception(ConnectionError("Firestorm LEAP disconnected"))
                self.pending.clear()
            LOG.info("LEAP ended: %s", exc)

    def request(self, pump, data, timeout=15, isolated=False):
        if not self.connected:
            raise ConnectionError("Firestorm is disconnected")
        request_id = uuid.uuid4().hex
        reply_pump = self.reply_pump
        if isolated:
            created = self.request(self.command_pump, {"op": "newpump", "name": "mcp-" + request_id})
            reply_pump = created["name"]
        future = concurrent.futures.Future()
        with self.lock:
            self.pending[request_id] = future
            if isolated:
                self.pending["pump:" + reply_pump] = future
        try:
            self.send(pump, {**data, "reply": reply_pump, "reqid": request_id})
            result = future.result(timeout=timeout)
            if isinstance(result, dict):
                result = {k: v for k, v in result.items() if k != "reqid"}
                if result.get("error"):
                    raise ValueError(str(result["error"]))
            return result
        except concurrent.futures.TimeoutError:
            raise TimeoutError("Viewer reply timed out; the action may have occurred. Read state before retrying.") from None
        finally:
            with self.lock:
                self.pending.pop(request_id, None)
                if isolated:
                    self.pending.pop("pump:" + reply_pump, None)
            if isolated and self.connected:
                self.send(self.command_pump, {"op": "stoplistening", "source": reply_pump, "listener": "llleap"})

    def send(self, pump, data):
        with self.write_lock:
            self.outgoing.write(encode_frame(pump, decode_typed(data)))
            self.outgoing.flush()

    def discover(self):
        names = self.request(self.command_pump, {"op": "getAPIs"})
        result = {}
        for name, entry in names.items():
            if name == self.command_pump or not isinstance(entry, dict):
                continue
            api = self.request(self.command_pump, {"op": "getAPI", "api": name})
            if api.get("name"):
                result[name] = api
        self.apis = result
        return result

    def call(self, api, op, arguments=None, expect_reply=None, timeout=15):
        if api not in self.apis:
            self.discover()
        if api not in self.apis:
            raise ValueError(f"API {api!r} is not exposed by this viewer")
        descriptor = self.apis[api]
        operations = {item["name"]: item for item in descriptor.get("ops", [])}
        if op not in operations:
            raise ValueError(f"Operation {api}.{op} is not exposed by this viewer")
        arguments = dict(arguments or {})
        dispatch_key = descriptor.get("key", "op")
        if {"reply", "reqid", dispatch_key} & arguments.keys():
            raise ValueError("Transport fields cannot be supplied as arguments")
        required = operations[op].get("required") or {}
        if isinstance(required, dict):
            missing = set(required) - {"reply"} - arguments.keys()
            if missing:
                raise ValueError(f"Missing arguments: {', '.join(sorted(missing))}")
        if api == "LLViewerWindow" and op == "saveSnapshot":
            if arguments.get("type", "COLOR") not in ("COLOR", "DEPTH"):
                raise ValueError("Snapshot type must be COLOR or DEPTH (invalid values crash the viewer)")
            for key in ("width", "height"):
                if key in arguments and (not isinstance(arguments[key], int) or not 16 <= arguments[key] <= 8192):
                    raise ValueError(f"{key} must be between 16 and 8192")
        if api == "UI" and op == "call":
            raise ValueError("Use ui_invoke_menu with a discovered menu entry. An unknown UI.call function can crash Firestorm.")
        if expect_reply is None:
            expect_reply = ("reply" in required or '"reply"' in operations[op].get("desc", "") or
                            (api == "LLFloaterReg" and op == "clickButton"))
        data = {dispatch_key: op, **arguments}
        if expect_reply:
            return self.request(api, data, timeout, isolated=(api == "LLFloaterReg" and op == "clickButton"))
        self.send(api, data)
        # A ping is an event-loop barrier, not proof of a simulator-side effect.
        self.request(self.command_pump, {"op": "ping"}, timeout)
        return {"status": "dispatched", "verified_effect": False, "api": api, "operation": op}

    def handle(self, request):
        method = request.get("method")
        if method == "status":
            return {"connected": self.connected, "helper_pid": os.getpid(), "started": self.started,
                    "bridge_generation": self.generation, "asset_bridge_contract": 1 if self.assets else None,
                    "api_count": len(self.apis), "event_cursor": self.sequence,
                    "decode_errors": self.decode_errors,
                    "repaired_duplicate_blocks": self.repaired_duplicate_blocks,
                    "control_owner": self.owner_label if self.lease_until > time.monotonic() else None}
        if method == "events":
            after = int(request.get("after", 0))
            with self.lock:
                return {"cursor": self.sequence, "events": [e for e in self.events if e["cursor"] > after],
                        "dropped": bool(self.events and after and after < self.events[0]["cursor"] - 1)}
        with self.operation_lock:
            if self.lease_until <= time.monotonic():
                self.owner = self.owner_label = None
            client_id = request.get("client_id")
            if method == "acquire":
                if not client_id:
                    raise ValueError("Client identity is required")
                if self.owner and self.owner != client_id:
                    raise RuntimeError("Viewer control is held by " + str(self.owner_label))
                seconds = min(1800, max(30, float(request.get("seconds", 300))))
                acquired_new = self.owner != client_id
                self.owner, self.owner_label = client_id, request.get("label", "agent")
                self.lease_until = max(self.lease_until, time.monotonic() + seconds)
                if self.assets and "FSMCPAssets" in self.apis:
                    self.assets.sync_lease()
                return {"acquired": True, "acquired_new": acquired_new, "owner": self.owner_label,
                        "expires_in_seconds": self.lease_until - time.monotonic()}
            if method == "release":
                if self.owner and self.owner != client_id:
                    raise RuntimeError("Only the controlling client can release its lease")
                self.owner = self.owner_label = None
                self.lease_until = 0
                if self.assets:
                    self.assets.revoked()
                return {"released": True}
            if method == "discover":
                return self.discover()
            if self.owner and self.owner != client_id:
                if method == "call" and request.get("api") == "FSMCPAssets":
                    return {"schema_version": 1, "ok": False, "failure": {
                        "code": "lease_conflict", "message": "Another client holds viewer control.", "unknownOutcome": False}}
                raise RuntimeError("Viewer control is held by " + str(self.owner_label))
            if method == "assert_control":
                if not self.connected or not self.owner or self.owner != client_id:
                    raise RuntimeError("Acquire an active viewer control lease before saving scripts")
                return {"viewer_pid": parent_viewer().pid, "connected": True}
            if method == "ping":
                return self.request(self.command_pump, {"op": "ping"}, timeout=5)
            if method == "menu":
                entry = request["entry"]
                matches = []
                for elem in ET.parse(self.viewer_dir / "skins/default/xui/en/menu_viewer.xml").getroot().iter():
                    for child in elem:
                        if elem.get("name") == entry.get("name") and child.tag.endswith("on_click"):
                            matches.append((child.get("function"), child.get("parameter", "")))
                if len(matches) != 1 or matches[0] != (entry.get("function"), entry.get("parameter", "")):
                    raise ValueError("Callback does not match one installed menu entry")
                self.send("UI", {"op": "call", "function": matches[0][0], "parameter": matches[0][1]})
                self.request(self.command_pump, {"op": "ping"})
                return {"status": "dispatched", "menu": entry["name"], "verified_effect": False}
            if method == "call":
                if request["api"] == "FSMCPAssets":
                    if not self.assets:
                        raise RuntimeError("Asset gateway/journal is unavailable; restart the separate development viewer when convenient")
                    return self.assets.handle(request["op"], request.get("arguments"))
                return self.call(request["api"], request["op"], request.get("arguments"),
                                 request.get("expect_reply"), min(60, max(1, float(request.get("timeout", 15)))))
            if method == "subscribe":
                source = request["source"]
                return self.request(self.command_pump, {"op": "listen", "source": source, "listener": "firestorm-mcp"})
            if method == "unsubscribe":
                return self.request(self.command_pump, {"op": "stoplistening", "source": request["source"], "listener": "firestorm-mcp"})
        raise ValueError("Unknown local bridge method")


def make_handler(bridge, token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reject_request(self, status):
            # Closing with an unread small POST body can reset the Windows socket
            # before the peer receives the HTTP error. Drain only a bounded body,
            # never parse it or pass it to the bridge, and do not wait on a slow peer.
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if 0 < size <= 16384 and not self.headers.get("Transfer-Encoding"):
                    self.connection.settimeout(1)
                    self.rfile.read(size)
            except (ValueError, OSError):
                pass
            self.send_error(status)

        def do_POST(self):
            if self.path != "/rpc":
                self.reject_request(404)
                return
            if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                self.reject_request(401)
                return
            if self.headers.get("Origin"):
                self.reject_request(403)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 16 * 1024 * 1024:
                    raise ValueError("Invalid request size")
                self.connection.settimeout(70)
                request = json.loads(self.rfile.read(size))
                result = {"result": bridge.handle(request)}
                status = 200
            except Exception as exc:
                result = {"error": {"type": type(exc).__name__, "message": str(exc)}}
                status = 400
            body = json.dumps(result, default=json_default, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--viewer-dir", type=Path, default=viewer_directory())
    parser.add_argument("--debug-protocol", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    if os.name == "nt":
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    bridge = LeapBridge(sys.stdin.buffer, sys.stdout.buffer)
    bridge.viewer_dir = args.viewer_dir
    args.runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    from .asset_gateway import AssetGateway
    from .asset_journal import AssetJournal
    bridge.assets = AssetGateway(bridge, AssetJournal(args.runtime.parent / "asset-journal.sqlite3"))
    if args.debug_protocol:
        bridge.debug_protocol_dir = args.runtime
    token = secrets.token_urlsafe(32)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(bridge, token))
    server.daemon_threads = True
    connection = {"url": f"http://127.0.0.1:{server.server_port}/rpc", "token": token,
                  "pid": os.getpid(), "session_id": uuid.uuid4().hex, "started": time.time()}
    connection_file = args.runtime / "connection.json"
    temporary = args.runtime / f"connection-{os.getpid()}.tmp"
    # Restrict session credentials from the first byte, even with a permissive
    # POSIX umask. Windows continues to use its user-directory ACLs.
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(connection, handle)
    temporary.replace(connection_file)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        while bridge.connected:
            time.sleep(0.25)
    finally:
        server.shutdown()
        server.server_close()
        try:
            if json.loads(connection_file.read_text())["session_id"] == connection["session_id"]:
                connection_file.unlink()
        except (OSError, ValueError, KeyError):
            pass


if __name__ == "__main__":
    main()
