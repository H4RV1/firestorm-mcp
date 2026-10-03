"""Synthetic perception/capture/policy tests; no live viewer or desktop access."""
import asyncio
import base64
import copy
import io
from uuid import uuid4

import pytest
from PIL import Image

from firestorm_mcp.background_ui import render_structure, revision
from firestorm_mcp.executor import execute, validate_plan
from firestorm_mcp.server import Tools, result_content
from test_executor import Session, plan
from test_transport import channel


def scene():
    root = {'path': '/main_view/panel', 'rect': {'left': 0, 'right': 320, 'bottom': 0, 'top': 200},
            'visible_chain': True, 'enabled_chain': True, 'name': 'panel', 'role': 'view'}
    return {'schema_version': 1, 'root': root, 'controls': [root], 'truncated': False,
            'depth_limited': True, 'context': {'window_minimized': True, 'app_has_focus': False}}


def fake_tools(tmp_path, reply):
    tools = Tools(tmp_path)
    tools.client.apis = {'FSMCPUI': {'ops': [{'name': op} for op in
        ('getScene', 'getContext', 'requestCapture', 'captureResult')]}}
    calls = []
    def rpc(method, **kw):
        calls.append(method)
        return {'connected': True}
    def call(api, op, args, **kw):
        assert api == 'FSMCPUI'
        calls.append(op)
        return reply(op, args)
    tools.client.rpc, tools.client.call = rpc, call
    return tools, calls


def test_minimized_structure_visualization_and_focus_insensitive_revision(tmp_path):
    tools, calls = fake_tools(tmp_path, lambda op, args: scene())
    value = tools.call('ui_visualize', {'under': '/main_view/panel'})
    assert value['evidence'] == 'ui_structure_not_pixels' and value['context']['window_minimized']
    assert calls == ['getScene']
    with Image.open(value['_image_path']) as img:
        assert img.size == (320, 230)
    changed = scene(); changed['context']['app_has_focus'] = True
    assert revision(changed) == revision(scene())
    changed['controls'][0]['enabled_chain'] = False
    assert revision(changed) != revision(scene())


def test_capture_refuses_suspended_render_without_fallback(tmp_path):
    tools, calls = fake_tools(tmp_path, lambda op, args: {'schema_version': 1, 'state': 'unavailable', 'reason': 'render_suspended'})
    assert tools.call('ui_capture', {'path': '/main_view'})['reason'] == 'render_suspended'
    assert calls == ['assert_control', 'requestCapture']
    assert not list(tools.captures.glob('*.png'))


def png_result(width=10, metadata_width=10):
    buf = io.BytesIO(); Image.new('RGB', (width, 10), 'green').save(buf, 'PNG')
    return {'schema_version': 1, 'state': 'ready', 'result': {'state': 'ready', 'width': metadata_width, 'height': 10,
        'png': {'$binary_base64': base64.b64encode(buf.getvalue()).decode()}}}


def test_capture_waits_for_requested_frame_returns_native_mcp_image(tmp_path, monkeypatch):
    ticket = str(uuid4()); results = [{'schema_version': 1, 'state': 'pending'}, png_result()]
    def reply(op, args):
        if op == 'requestCapture': return {'schema_version': 1, 'state': 'pending', 'capture_id': ticket}
        assert args == {'capture_id': ticket}
        return results.pop(0)
    monkeypatch.setattr('firestorm_mcp.background_ui.time.sleep', lambda _: None)
    tools, calls = fake_tools(tmp_path, reply)
    value = tools.call('ui_capture', {'path': '/main_view/panel'})
    assert value['capture_id'] == ticket and value['focus_requested'] is False
    assert calls == ['assert_control', 'requestCapture', 'captureResult', 'captureResult']
    content = result_content(value)
    assert any(item.type == 'image' for item in content)


@pytest.mark.parametrize('result', [png_result(metadata_width=11), png_result(width=1601),
    {'schema_version': 1, 'state': 'ready', 'result': {'png': {'$binary_base64': '!invalid!'}}}])
def test_capture_rejects_malformed_or_oversize_pixels(tmp_path, result):
    tools, _ = fake_tools(tmp_path, lambda op, args: {'schema_version': 1, 'state': 'pending', 'capture_id': str(uuid4())}
                          if op == 'requestCapture' else result)
    with pytest.raises(ValueError): tools.call('ui_capture', {'path': '/main_view'})
    assert not list(tools.captures.glob('*.png'))


def test_wait_stops_on_scoped_geometry_change(tmp_path, monkeypatch):
    initial = scene(); changed = copy.deepcopy(initial); changed['controls'][0]['rect']['top'] = 100
    states = [initial, changed]
    tools, calls = fake_tools(tmp_path, lambda op, args: states.pop(0))
    monkeypatch.setattr('firestorm_mcp.background_ui.time.sleep', lambda _: None)
    value = tools.call('ui_wait_change', {'under': '/main_view/panel', 'previous_revision': revision(initial)})
    assert value['changed'] and calls == ['assert_control', 'getScene', 'getScene']


@pytest.mark.parametrize('tool', ['snapshot', 'ui_click', 'ui_set_text', 'ui_press_key', 'viewer_call', 'floater_open', 'workflow_read'])
def test_background_plan_rejects_input_before_any_contact(tmp_path, tool):
    session = Session(tmp_path)
    with pytest.raises(ValueError, match='background'):
        asyncio.run(execute(session, plan('object_selection', tool), allow_writes=True, background_only=True))
    assert session.calls == []


def test_background_write_still_needs_write_flag():
    with pytest.raises(ValueError, match='allow-writes'):
        validate_plan(plan('script_write'), background_only=True)
    validate_plan(plan('script_write'), allow_writes=True, background_only=True)
    validate_plan(plan('object_select'), allow_writes=True, background_only=True)


def test_unavailable_capture_stops_plan_and_releases(tmp_path):
    from types import SimpleNamespace
    import json
    session = Session(tmp_path)
    original = session.call_tool
    async def call(name, args):
        if name == 'ui_capture':
            session.calls.append(name)
            return SimpleNamespace(is_error=False, content=[SimpleNamespace(type='text', text=json.dumps({'state': 'unavailable'}))])
        return await original(name, args)
    session.call_tool = call
    p = {'version': 1, 'calls': [{'tool': 'ui_capture', 'arguments': {'path': '/main_view'}}, {'tool': 'script_sessions', 'arguments': {}}]}
    result = asyncio.run(execute(session, p, background_only=True))
    assert result['stopped'] == 'operation_incomplete'
    assert 'script_sessions' not in session.calls and session.calls[-1] == 'control_release'


@pytest.mark.parametrize('op', ['requestCapture', 'captureResult'])
def test_capture_raw_rpc_requires_lease(channel, op):
    bridge, _, _ = channel
    bridge.call = lambda *a, **kw: pytest.fail('No dispatch without control')
    with pytest.raises(RuntimeError, match='lease'):
        bridge.handle({'method': 'call', 'api': 'FSMCPUI', 'op': op, 'client_id': 'no-lease'})
