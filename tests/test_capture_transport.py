import base64
import hashlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image

from firestorm_mcp.bridge import write_disconnect
from firestorm_mcp.server import Tools
from test_background_ui import fake_tools


def capture_fixture(tmp_path, mutate=lambda chunk: None):
    output = io.BytesIO()
    Image.new('RGB', (120, 120), 'green').save(output, 'PNG', compress_level=0)
    png, ticket, offsets = output.getvalue(), str(uuid4()), []
    def reply(op, args):
        if op == 'requestCapture':
            return {'schema_version': 1, 'state': 'pending', 'capture_id': ticket}
        if op == 'captureResult':
            return {'schema_version': 1, 'state': 'ready', 'result': {
                'state': 'ready', 'width': 120, 'height': 120,
                'png_transfer': 'chunks_v1', 'png_size': len(png)}}
        assert op == 'captureChunk'
        assert args['capture_id'] == ticket
        offset = args['offset']; offsets.append(offset)
        part = png[offset:offset+8192]; end = offset + len(part)
        chunk = {'schema_version': 1, 'capture_id': ticket, 'offset': offset,
                 'next_offset': end, 'done': end == len(png),
                 'data': {'$binary_base64': base64.b64encode(part).decode()}}
        mutate(chunk)
        return chunk
    tools, calls = fake_tools(tmp_path, reply)
    return tools, png, offsets


def test_multichunk_capture_reassembles_exact_pixels(tmp_path):
    tools, expected, offsets = capture_fixture(tmp_path)
    result = tools.call('ui_capture', {'path': '/main_view/panel'})
    assert Path(result['_image_path']).read_bytes() == expected
    assert offsets == list(range(0, len(expected), 8192))


@pytest.mark.parametrize('change', [
    {'capture_id': str(uuid4())}, {'offset': 5}, {'next_offset': 0},
    {'done': True}, {'data': {'$binary_base64': ''}},
    {'data': {'$binary_base64': 'A' * 11000}},
])
def test_bad_chunk_stops_without_replay_or_partial_image(tmp_path, change):
    tools, _, offsets = capture_fixture(tmp_path, lambda chunk: chunk.update(change))
    with pytest.raises(ValueError):
        tools.call('ui_capture', {'path': '/main_view/panel'})
    assert offsets == [0]
    assert not list(tools.captures.glob('*.png'))


def test_transfer_disconnect_is_not_replayed(tmp_path):
    def disconnect(chunk):
        if chunk['offset']: raise ConnectionError('synthetic lost reply')
    tools, _, offsets = capture_fixture(tmp_path, disconnect)
    with pytest.raises(ConnectionError):
        tools.call('ui_capture', {'path': '/main_view/panel'})
    assert offsets == [0, 8192]
    assert not list(tools.captures.glob('*.png'))


def test_disconnect_report_is_private_bounded_history(tmp_path):
    bridge = SimpleNamespace(generation='synthetic-generation', last_disconnect_reason='ValueError',
        pending_at_disconnect=2, decode_errors=1, repaired_duplicate_blocks=3,
        last_operation={'api': 'FSMCPUI', 'operation': 'captureResult'}, token='must-not-persist')
    runtime = tmp_path / 'runtime'; runtime.mkdir()
    write_disconnect(runtime, bridge)
    report = runtime / 'last-disconnect.json'
    assert report.stat().st_size < 4096
    assert 'must-not-persist' not in report.read_text()
    tools = Tools(tmp_path)
    tools.client.rpc = lambda *a, **k: (_ for _ in ()).throw(ConnectionError('offline'))
    result = tools.call('connection_status', {})
    assert result['last_disconnect']['pending_results_unknown'] == 2
    assert result['last_disconnect']['last_operation_is_cause'] is False
    assert result['last_disconnect_is_historical'] and not result['connected']


def test_capture_installer_validates_all_files_before_write(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'scripts/apply_capture_transport.py'
    spec = importlib.util.spec_from_file_location('capture_installer', path)
    installer = importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)
    root = tmp_path / 'indra/newview'; root.mkdir(parents=True)
    sources = {'fsmcpui.cpp': 'old cpp', 'fsmcpui.h': 'old header',
        'llappviewer.cpp': '#include "llleap.h"\n            LLLeap::create("", leap, false); // exception=false'}
    for name, text in sources.items(): (root / name).write_text(text, encoding='utf-8')
    monkeypatch.setattr(installer, 'BASELINES', {n:hashlib.sha256(t.encode()).hexdigest() for n,t in sources.items()})
    assert not installer.apply(tmp_path, True)['written']
    assert sources == {n:(root/n).read_text() for n in sources}
    (root/'llappviewer.cpp').write_text('unknown')
    with pytest.raises(ValueError, match='Unknown/modified'): installer.apply(tmp_path)
    assert (root/'fsmcpui.cpp').read_text() == 'old cpp'
    (root/'llappviewer.cpp').write_text(sources['llappviewer.cpp'])
    assert installer.apply(tmp_path)['written']
    assert 'fsmcpStartLeap(leap.asString())' in (root/'llappviewer.cpp').read_text()
    with pytest.raises(ValueError): installer.apply(tmp_path)
