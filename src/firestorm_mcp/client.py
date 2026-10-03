from __future__ import annotations

import json
from pathlib import Path
import urllib.error
import urllib.request
import urllib.parse
import uuid


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A local response must never forward the bearer token or action elsewhere.
        return None


class BridgeClient:
    def __init__(self, runtime: Path):
        self.runtime = Path(runtime)
        self.client_id = uuid.uuid4().hex
        self.apis = {}
        self.connection_identity = None
        self.lease_identity = None
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def connection(self):
        try:
            value = json.loads((self.runtime / "connection.json").read_text(encoding="utf-8"))
            identity = (value["url"], value["token"], value.get("session_id"))
            if not isinstance(value["url"], str) or not isinstance(value["token"], str) or not 1 <= len(value["token"]) <= 256 or any(ord(c) < 33 or ord(c) > 126 for c in value["token"]):
                raise ValueError("Invalid metadata")
        except (OSError, ValueError, KeyError, TypeError):
            self.apis = {}
            raise ConnectionError("Firestorm bridge connection metadata is unavailable. Check viewer/bridge state before coordinating a launcher start.") from None
        if identity != self.connection_identity:
            self.apis = {}
            self.connection_identity = identity
        return value

    def rpc(self, method, **arguments):
        connection = self.connection()
        if self.lease_identity is not None and self.lease_identity != self.connection_identity and method not in {"status", "discover", "acquire"}:
            raise ConnectionError("Bridge generation changed; the previous lease is lost. Reinspect and explicitly acquire control before continuing. No action was replayed.")
        endpoint = urllib.parse.urlsplit(connection["url"])
        if (endpoint.scheme != "http" or endpoint.hostname != "127.0.0.1" or endpoint.username is not None
                or endpoint.password is not None or endpoint.path != "/rpc" or endpoint.query or endpoint.fragment):
            raise ValueError("Bridge endpoint must be loopback")
        payload = {"method": method, "client_id": self.client_id, **arguments}
        if connection.get("bridge_generation"):
            payload["expected_bridge_generation"] = connection["bridge_generation"]
        body = json.dumps(payload, allow_nan=False).encode("utf-8")
        if len(body) > 16 * 1024 * 1024:
            raise ValueError("Bridge request exceeds 16 MiB")
        request = urllib.request.Request(connection["url"], body,
            {"Content-Type": "application/json", "Authorization": "Bearer " + connection["token"]})
        try:
            # Explicitly bypass system proxies for this local-only connection.
            timeout = min(65, max(3, float(arguments.get("timeout", 60 if method == "discover" else 15)) + 2))
            with self.opener.open(request, timeout=timeout) as response:
                data = response.read(16 * 1024 * 1024 + 1)
                if len(data) > 16 * 1024 * 1024:
                    raise ConnectionError("Bridge response exceeds 16 MiB; inspect state before retrying")
                result = json.loads(data)
                if not isinstance(result, dict) or "result" not in result:
                    raise ConnectionError("Bridge returned a malformed result; inspect state before retrying")
        except urllib.error.HTTPError as exc:
            try:
                error = json.load(exc)["error"]
                raise RuntimeError(error["type"] + ": " + error["message"]) from None
            except (ValueError, KeyError):
                raise ConnectionError(f"Bridge HTTP error {exc.code}") from None
        except urllib.error.URLError as exc:
            raise ConnectionError("Firestorm bridge is unavailable at the recorded endpoint. Check viewer/bridge state; do not restart a shared session solely for tool discovery.") from exc
        if method == "discover":
            self.apis = result["result"]
        if method == "acquire" and result["result"].get("acquired"):
            self.lease_identity = self.connection_identity
        elif method == "release":
            self.lease_identity = None
        return result["result"]

    def call(self, api, op, arguments=None, **kwargs):
        self.connection()  # Invalidate descriptors even when expect_reply is explicit.
        if kwargs.get("expect_reply") is None:
            if api not in self.apis:
                self.rpc("discover")
            descriptor = next((item for item in self.apis.get(api, {}).get("ops", []) if item["name"] == op), {})
            kwargs["expect_reply"] = ("reply" in (descriptor.get("required") or {}) or
                                      '"reply"' in descriptor.get("desc", "") or
                                      (api == "LLFloaterReg" and op == "clickButton"))
        return self.rpc("call", api=api, op=op, arguments=arguments or {}, **kwargs)
