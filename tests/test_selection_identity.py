from uuid import uuid4

import pytest

from firestorm_mcp.server import Tools


def test_equivalent_uuid_forms_use_canonical_typed_native_boundary(tmp_path):
    tools = Tools(tmp_path)
    uid = str(uuid4())
    calls = []
    tools.client.apis = {"FSMCPBuilder": {"ops": [{"name": "selectObjects"}]}}
    tools.client.rpc = lambda *a, **k: {}
    tools.client.call = lambda api, op, args, **k: calls.append(args) or {"schema_version": 1}
    for value in [uid.upper(), {"$uuid": uid.upper()}]:
        tools.call("object_select", {"object_ids": [uid.upper()], "expected_selection": [
            {"object_id": value, "root_id": uid}]})
    assert calls[0] == calls[1]
    assert calls[0]["expected_selection"][0]["object_id"] == {"$uuid": uid}


def test_equivalent_duplicate_roots_rejected_before_lease_or_dispatch(tmp_path):
    tools = Tools(tmp_path)
    uid = str(uuid4())
    tools.client.rpc = tools.client.call = lambda *a, **k: pytest.fail("No dispatch")
    with pytest.raises(ValueError, match="distinct"):
        tools.call("object_select", {"object_ids": [uid, uid.upper()], "expected_selection": []})


def test_null_selection_identity_rejected_before_dispatch(tmp_path):
    tools = Tools(tmp_path)
    tools.client.rpc = tools.client.call = lambda *a, **k: pytest.fail("No dispatch")
    with pytest.raises(ValueError, match="nonzero"):
        tools.call("object_select", {"object_ids": [str(uuid4())], "expected_selection": [
            {"object_id": "00000000-0000-0000-0000-000000000000", "root_id": str(uuid4())}]})
