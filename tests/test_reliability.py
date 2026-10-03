"""Synthetic transport and workflow regressions; never start/contact a viewer."""
import io
import json
import time
import concurrent.futures
from types import SimpleNamespace
from uuid import uuid4

import pytest

from firestorm_mcp.client import BridgeClient
from firestorm_mcp.protocol import FrameDecodeError, encode_frame, read_frame
from firestorm_mcp.server import Tools
from firestorm_mcp.asset_gateway import AssetGateway
from test_transport import channel, respond


def test_oversized_frame_is_drained_then_next_frame_survives(monkeypatch):
    monkeypatch.setattr('firestorm_mcp.protocol.MAX_DECODE_FRAME', 128)
    class Limited(io.BytesIO):
        def read(self, size=-1):
            assert 0 < size <= 65536
            return super().read(size)
    stream = Limited(b'200000:' + b'x' * 200000 + encode_frame('reply', {'ok': True}))
    with pytest.raises(FrameDecodeError, match='Oversized') as exc:
        read_frame(stream)
    assert exc.value.body == b''
    assert read_frame(stream)['data']['ok']


def test_raw_tree_cannot_bypass_native_bounds(channel):
    bridge, _, _ = channel
    bridge.apis = {'LLWindow': {'ops': [{'name': 'getPaths'}]}}
    bridge.discover = lambda: bridge.apis
    with pytest.raises(ValueError, match='Unbounded'):
        bridge.call('LLWindow', 'getPaths', {'under': '/main_view'})
    bridge.apis['FSMCPUI'] = {'ops': [{'name': 'getPaths', 'required': {'reply': None, 'under': None}}]}
    calls = []
    bridge.request = lambda *a, **kw: calls.append((a, kw)) or {'paths': [], 'truncated': True}
    result = bridge.call('LLWindow', 'getPaths', {'under': '/main_view', 'limit': 999999})
    assert calls[0][0][0] == 'FSMCPUI'
    assert calls[0][0][1]['limit'] == 200
    assert result['truncated']


def test_generation_and_write_lease_checks_precede_dispatch(channel):
    bridge, _, _ = channel
    bridge.call = lambda *a, **kw: pytest.fail('No native dispatch expected')
    with pytest.raises(ConnectionError, match='generation'):
        bridge.handle({'method': 'call', 'expected_bridge_generation': 'old', 'api': 'FSMCPBuilder', 'op': 'commitLink'})
    with pytest.raises(RuntimeError, match='lease'):
        bridge.handle({'method': 'call', 'client_id': 'one', 'api': 'FSMCPBuilder', 'op': 'commitLink'})


def test_event_byte_budget_and_loss_cursor_without_retaining_late_replies(channel):
    bridge, incoming, outgoing = channel
    with concurrent.futures.ThreadPoolExecutor() as pool:
        waiting = pool.submit(bridge.request, 'api', {'op': 'barrier'})
        request = read_frame(incoming)
        for _ in range(8): outgoing.write(encode_frame('events', {'text': 'x' * 200000}))
        outgoing.write(encode_frame('reply', {'reqid': 'expired-request', 'text': 'x' * 300000}))
        respond(outgoing, request, {'ok': True})
        assert waiting.result(2)['ok']
    assert bridge.event_bytes <= 1024 * 1024 and len(bridge.events) <= 5
    assert bridge.late_replies == 1
    result = bridge.handle({'method': 'events', 'after': 0})
    assert result['dropped'] and all('_bytes' not in event for event in result['events'])
    assert not bridge.handle({'method': 'events', 'after': result['cursor']})['dropped']


def test_client_restart_invalidates_descriptors_and_old_lease(tmp_path):
    p = tmp_path / 'connection.json'
    p.write_text(json.dumps({'url': 'http://127.0.0.1:1/rpc', 'token': 'a', 'session_id': 'a'}))
    client = BridgeClient(tmp_path)
    client.connection()
    client.lease_identity = client.connection_identity
    client.apis = {'old': {}}
    p.write_text(json.dumps({'url': 'http://127.0.0.1:1/rpc', 'token': 'b', 'session_id': 'b'}))
    client.opener = SimpleNamespace(open=lambda *a, **k: pytest.fail('No HTTP dispatch'))
    with pytest.raises(ConnectionError, match='generation'):
        client.rpc('call', api='old', op='write')
    assert client.apis == {}


def test_upload_chunks_reuse_native_lease_but_renew_and_revoke():
    bridge = SimpleNamespace(generation='test', owner='one', lease_until=time.monotonic()+120)
    gateway = AssetGateway(bridge, None)
    calls = []
    gateway.native = lambda op, args: calls.append((op, args)) or {'ok': True}
    first = gateway.sync_lease()
    for _ in range(170): assert gateway.sync_lease() == first
    assert len(calls) == 1
    bridge.lease_until += 31
    gateway.sync_lease()
    assert len(calls) == 2
    bridge.owner = None; bridge.lease_until = 0
    gateway.sync_lease()
    assert calls[-1][1]['leaseId'] == ''


def test_native_ui_read_is_one_round_trip_and_preserves_unknown(tmp_path):
    tools = Tools(tmp_path)
    tools.client.apis = {'FSMCPUI': {'ops': [{'name': 'getControls'}]}}
    calls = []
    def reply(api, op, args, **kw):
        calls.append((api, op, args))
        return {'schema_version': 1, 'controls': [{'path': p, 'visible_chain': True, 'value': None, 'value_available': True} for p in args['paths']]}
    tools.client.call = reply
    result = tools.call('ui_read', {'controls': ['/main_view/A', '/main_view/B'], 'include_values': True})
    assert len(calls) == 1 and result['viewer_round_trips'] == 1
    assert result['controls'][0]['value'] is None
    assert result['instance_identity_verified']


def test_rows_gated_no_unbounded_fallback(tmp_path):
    tools = Tools(tmp_path)
    tools.client.rpc = lambda *a, **kw: {}
    tools.client.call = lambda *a, **kw: pytest.fail('No UI fallback')
    with pytest.raises(ValueError, match='FSMCPUI'):
        tools.call('ui_rows', {'path': '/main_view/panel/errors'})


def test_read_plan_validates_all_steps_before_executing(tmp_path):
    tools = Tools(tmp_path)
    tools.local['connection_status'] = lambda: pytest.fail('Invalid later step prevents every call')
    with pytest.raises(ValueError, match='allowlisted'):
        tools.call('workflow_read', {'calls': [{'tool': 'connection_status', 'arguments': {}}, {'tool': 'ui_click', 'arguments': {'path': '/main_view/button'}}]})


def test_read_plan_stops_after_transport_failure(tmp_path):
    tools = Tools(tmp_path)
    tools.local['object_selection'] = lambda: (_ for _ in ()).throw(ConnectionError('synthetic disconnect'))
    tools.local['script_sessions'] = lambda: pytest.fail('Do not continue after failure')
    result = tools.call('workflow_read', {'calls': [{'tool': 'object_selection', 'arguments': {}}, {'tool': 'script_sessions', 'arguments': {}}]})
    assert not result['complete'] and len(result['results']) == 1


def test_builder_plan_schema_and_selection_validation(tmp_path):
    tools = Tools(tmp_path)
    tools.client.apis = {'FSMCPBuilder': {'ops': [{'name': 'commitLink'}, {'name': 'selectObjects'}]}}
    calls = []
    tools.client.rpc = lambda op, **kw: calls.append(op) or {'viewer_pid': 1}
    tools.client.call = lambda api, op, args, **kw: calls.append((op, args)) or {'schema_version': 1, 'verified_effect': False}
    plan = str(uuid4())
    result = tools.call('object_link_apply', {'plan_id': plan})
    assert calls == ['assert_control', ('commitLink', {'plan_id': {'$uuid': plan}})]
    assert not result['verified_effect']
    with pytest.raises(ValueError, match='distinct'):
        tools.call('object_select', {'object_ids': [plan, plan], 'expected_selection': []})


@pytest.mark.parametrize('changes', [{'color': [1, 1, 1, 2]}, {'glow': True}, {'pbr': 'anything'}, {'offset': [2, 0]}, {'fullbright': 1}, {'rotation': float('nan')}])
def test_material_invalid_plan_never_dispatches(tmp_path, changes):
    tools = Tools(tmp_path)
    tools.client.call = lambda *a, **kw: pytest.fail('Invalid plan must not contact viewer')
    tools.client.rpc = tools.client.call
    with pytest.raises(ValueError):
        tools.call('material_face_plan', {'object_id': str(uuid4()), 'face': 0, 'changes': changes})


def test_material_plan_preserves_explicit_target_and_native_evidence(tmp_path):
    tools = Tools(tmp_path)
    tools.client.apis = {'FSMCPBuilder': {'ops': [{'name': 'prepareFace'}]}}
    calls = []
    tools.client.call = lambda api, op, args, **kw: calls.append((op, args)) or {'schema_version': 1, 'world_changed': False, 'preview': {'glow': 0.5}}
    uid = str(uuid4())
    result = tools.call('material_face_plan', {'object_id': uid, 'face': 2, 'changes': {'glow': 0.5}})
    assert calls == [('prepareFace', {'object_id': {'$uuid': uid}, 'face': 2, 'changes': {'glow': 0.5}})]
    assert not result['world_changed']
