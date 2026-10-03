"""Native bounded UI reads, with explicit capability gating and no tree fallback."""


def call_ui(client, operation, arguments, timeout=5):
    if "FSMCPUI" not in client.apis:
        client.rpc("discover")
    if not any(op["name"] == operation for op in client.apis.get("FSMCPUI", {}).get("ops", [])):
        raise ValueError("This viewer lacks FSMCPUI." + operation + ". Use capability discovery and the compatible development build; no desktop-input fallback was attempted.")
    result = client.call("FSMCPUI", operation, arguments, expect_reply=True, timeout=timeout)
    if not isinstance(result, dict) or result.get("schema_version") != 1:
        raise ValueError("Unsupported FSMCPUI response schema")
    return result


def register_native_ui_tools(tools):
    @tools.register("Read a bounded live subtree: native traversal stops at 2048 nodes, 8 ms, 64 KiB of paths, or limit. max_depth<=8. No stock unbounded fallback. Follow next_offset or narrow under when the budget is exhausted; pagination is not a snapshot.", True)
    def ui_tree(under: str, limit: int = 100, max_depth: int = 2, offset: int = 0):
        if not under.startswith("/main_view") or "//" in under or len(under) > 2048:
            raise ValueError("Use an exact absolute /main_view path")
        if not 1 <= limit <= 200 or not 0 <= max_depth <= 8 or not 0 <= offset <= 2048:
            raise ValueError("Use limit 1-200, depth 0-8 and offset 0-2048")
        return call_ui(tools.client, "getPaths", dict(under=under, limit=limit, max_depth=max_depth, offset=offset))

    @tools.register("Read visible compiler/error or other scroll-list rows by exact path through FSMCPUI. At most 50 rows, 8 columns, 1024 bytes per cell and 32 KiB total. Ambiguous instances rejected. UI rows alone are not simulator execution evidence.", True)
    def ui_rows(path: str, offset: int = 0, limit: int = 20):
        if not path.startswith("/main_view/") or "//" in path or len(path) > 2048:
            raise ValueError("Use an exact absolute control path")
        if not 0 <= offset <= 100000 or not 1 <= limit <= 50:
            raise ValueError("Use offset 0-100000 and limit 1-50")
        return call_ui(tools.client, "getRows", dict(path=path, offset=offset, limit=limit))
