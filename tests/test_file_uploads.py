"""Synthetic files/transport only. Never contact a viewer, spend or open dialogs."""
import base64
import copy
import io
import json
import struct

from PIL import Image
import pytest

from firestorm_mcp.asset_contract import AssetError, validate
from firestorm_mcp.file_assets import document, inspect_upload, material_payload, texture_payload
from firestorm_mcp.server import Tools
from firestorm_mcp.executor import validate_plan
from test_asset_api import gateway, uid, expected


@pytest.fixture
def files(tmp_path):
    image = tmp_path / 'image.png'
    Image.new('RGBA', (16, 32), (8, 55, 120, 71)).save(image)
    model = {'asset': {'version': '2.0'}, 'images': [{'uri': image.name}],
             'textures': [{'source': 0}], 'materials': [{'pbrMetallicRoughness': {
                 'baseColorTexture': {'index': 0}, 'metallicFactor': 0.25, 'roughnessFactor': 0.8},
                 'alphaMode': 'BLEND', 'doubleSided': True}]}
    path = tmp_path / 'material.gltf'
    path.write_text(json.dumps(model))
    return image, path, model


def test_texture_normalization_preserves_pixels_and_alpha(files):
    image, _, _ = files
    payload, meta = texture_payload(str(image))
    with Image.open(io.BytesIO(payload)) as output, Image.open(image) as original:
        assert output.mode == 'RGBA' and output.tobytes() == original.tobytes()
    assert (meta['width'], meta['height']) == (16, 32)
    assert len(meta['payloadSha256']) == 64


@pytest.mark.parametrize('dimensions', [(17, 32), (16, 4096), (2, 8)])
def test_no_silent_resize(tmp_path, dimensions):
    path = tmp_path / 'bad.png'
    Image.new('RGB', dimensions).save(path)
    with pytest.raises(ValueError, match='dimensions'):
        texture_payload(str(path))


def test_material_dependencies_bind_uploaded_ids_and_preserve_factors(files):
    image, path, _ = files
    inspected = inspect_upload(str(path))
    assert inspected['dependencies'][0]['image_index'] == 0
    assert not inspected['dependencies'][0]['bound_asset_id']
    assert inspected['dependencies'][0]['bytes'] == image.stat().st_size
    with pytest.raises(ValueError, match='dependency'):
        material_payload(str(path))
    asset = uid()
    payload, _ = material_payload(str(path), texture_bindings={'0': asset})
    data = json.loads(payload)
    assert data['images'] == [{'uri': asset}]
    assert data['materials'][0]['pbrMetallicRoughness']['metallicFactor'] == 0.25
    assert data['materials'][0]['doubleSided'] is True
    assert str(image) not in payload.decode()
    a, _ = texture_payload(str(path), 0)
    b, _ = texture_payload(str(image))
    assert a == b


def test_reuse_uuid_requires_no_disk_dependency(files):
    _, path, model = files
    asset = uid(); model['images'][0]['uri'] = asset
    path.write_text(json.dumps(model))
    payload, meta = material_payload(str(path))
    assert json.loads(payload)['images'][0]['uri'] == asset
    assert meta['dependencies'][0]['existing_asset_id'] == asset


@pytest.mark.parametrize('uri', ['https://example.invalid/image.png', '../outside.png', '%2e%2e/outside.png', 'file:///tmp/x', '//server/share/x', '..\\outside.png'])
def test_external_or_traversing_dependency_refused(files, uri):
    _, path, model = files
    model['images'][0]['uri'] = uri
    path.write_text(json.dumps(model))
    with pytest.raises((ValueError, FileNotFoundError)):
        material_payload(str(path), inspect_only=True)


def test_glb_embedded_and_data_uri_images(files):
    image, path, model = files
    raw = image.read_bytes()
    model['images'][0] = {'bufferView': 0, 'mimeType': 'image/png'}
    model['buffers'] = [{'byteLength': len(raw)}]
    model['bufferViews'] = [{'buffer': 0, 'byteOffset': 0, 'byteLength': len(raw)}]
    encoded = json.dumps(model).encode(); encoded += b' ' * (-len(encoded) % 4)
    binary = raw + b'\0' * (-len(raw) % 4)
    glb = path.with_suffix('.glb')
    glb.write_bytes(struct.pack('<4sII', b'glTF', 2, 28 + len(encoded) + len(binary)) +
                    struct.pack('<II', len(encoded), 0x4e4f534a) + encoded +
                    struct.pack('<II', len(binary), 0x004e4942) + binary)
    assert texture_payload(str(glb), 0)[0] == texture_payload(str(image))[0]
    model['images'][0] = {'uri': 'data:image/png;base64,' + base64.b64encode(raw).decode()}
    path.write_text(json.dumps(model))
    assert texture_payload(str(path), 0)[0] == texture_payload(str(image))[0]
    broken = glb.read_bytes()[:-1]; glb.write_bytes(broken)
    with pytest.raises(ValueError): document(str(glb))


@pytest.mark.parametrize('change', ['transform', 'occlusion', 'nan', 'uv', 'scale', 'extension', 'index', 'sampler'])
def test_unsupported_or_invalid_material_not_silently_changed(files, change):
    _, path, model = files
    mat = model['materials'][0]; info = mat['pbrMetallicRoughness']['baseColorTexture']
    if change == 'transform': info['extensions'] = {'KHR_texture_transform': {'rotation': 1}}
    if change == 'occlusion': mat['occlusionTexture'] = {'index': 0}
    if change == 'nan': mat['alphaCutoff'] = float('nan')
    if change == 'uv': info['texCoord'] = 1
    if change == 'scale': mat['normalTexture'] = {'index': 0, 'scale': 0.5}
    if change == 'extension': mat['extensions'] = {'KHR_materials_unlit': {}}
    if change == 'index': info['index'] = -1
    if change == 'sampler':
        model['textures'][0]['sampler'] = 0
        model['samplers'] = [{'wrapS': 33071}]
    path.write_text(json.dumps(model))
    with pytest.raises(ValueError): material_payload(str(path), texture_bindings={'0': uid()})


def prepared(gateway, cost=10):
    request = uid(); session = expected()
    args = dict(assetType='texture', folderId=uid(), name='Synthetic texture', description='Unique receipt ' + uid(),
                sourceSha256='a' * 64, payloadSha256='b' * 64)
    # Synthetic successful native preparation; commit still exercises gateway policy/journal.
    from firestorm_mcp.asset_contract import fingerprint
    gateway.journal.reserve(request, fingerprint('prepareUpload', args, session), 'prepareUpload', args, session)
    gateway.journal.update(request, state='succeeded', result={'uploadId': uid(), 'cost': cost})
    return dict(requestId=uid(), kind='commitUpload', expected=session,
                arguments=dict(preparationRequestId=request, approvedCost=cost))


@pytest.mark.parametrize('cost', [True, -1, 1.5, None, '10'])
def test_explicit_integer_cost_required(cost):
    with pytest.raises(AssetError):
        validate('commitUpload', {'preparationRequestId': uid(), 'approvedCost': cost}, expected())


def test_cost_mismatch_never_submits(gateway):
    request = prepared(gateway); request['arguments']['approvedCost'] = 11
    assert gateway.handle('submit', request)['failure']['code'] == 'cost_mismatch'
    assert not any(op == 'submit' for op, _ in gateway.bridge.calls)


def test_wrong_session_missing_preparation_or_forged_id_never_submits(gateway):
    request = prepared(gateway)
    changed = copy.deepcopy(request); changed['expected']['generation'] = uid()
    assert gateway.handle('submit', changed)['failure']['code'] == 'session_changed'
    changed = copy.deepcopy(request); changed['arguments']['uploadId'] = uid()
    assert gateway.handle('submit', changed)['failure']['code'] == 'reserved_field'
    changed = copy.deepcopy(request); changed['arguments']['preparationRequestId'] = uid()
    assert gateway.handle('submit', changed)['failure']['code'] == 'preparation_missing'
    assert not any(op == 'submit' for op, _ in gateway.bridge.calls)


def test_commit_ack_lost_never_replayed_and_reconcile_has_saved_intent(gateway):
    request = prepared(gateway); gateway.bridge.lose_submit = True
    assert gateway.handle('submit', request)['failure']['unknownOutcome']
    gateway.bridge.lose_submit = False
    again = gateway.handle('submit', request)
    assert again['state'] == 'unknown'
    assert sum(op == 'submit' for op, _ in gateway.bridge.calls) == 1
    gateway.handle('submit', dict(kind='reconcile', requestId=uid(), expected=request['expected'],
                                 arguments={'originalRequestId': request['requestId']}))
    sent = [a for op, a in gateway.bridge.calls if op == 'submit'][-1]
    assert sent['arguments']['intent']['arguments']['assetType'] == 'texture'
    assert 'payloadSha256' in sent['arguments']['intent']['arguments']


def test_file_wrapper_chunks_and_deduplicates_without_paths_in_journal(gateway, files, tmp_path):
    image, _, _ = files
    # Incompressible deterministic pixels ensure multiple staging chunks.
    import random
    Image.frombytes('RGB', (128, 128), random.Random(8).randbytes(128 * 128 * 3)).save(image)
    tools = Tools(root=tmp_path / 'client', viewer_dir=tmp_path, tool_profile='compact')
    tools.client.apis = {'FSMCPAssets': {}}
    original = gateway.bridge.call
    def call(api, op, args, **kw):
        result = original(api, op, args, **kw)
        if op == 'status': result['operations'] = ['prepareUpload', 'commitUpload']
        return result
    gateway.bridge.call = call
    tools.client.call = lambda api, op, args, **kw: gateway.handle(op, args)
    args = dict(request_id=uid(), expected=expected(), folder_id=uid(), name='Image', description='Marker ' + uid(), filename=str(image))
    first = tools.call('assets_prepare_texture', args)
    assert first['state'] == 'queued'
    chunks = [base64.b64decode(a['data']['$binary_base64']) for op, a in gateway.bridge.calls if op == 'stage']
    assert len(chunks) > 1 and all(len(c) <= 8192 for c in chunks)
    assert b''.join(chunks) == texture_payload(str(image))[0]
    assert str(image) not in json.dumps(gateway.journal.get(args['request_id']))
    assert tools.call('assets_prepare_texture', args)['jobId'] == first['jobId']
    assert sum(op == 'submit' for op, _ in gateway.bridge.calls) == 1
    assert not gateway.stages


def test_background_executor_accepts_direct_upload_but_not_native_picker():
    plan = {'version': 1, 'calls': [{'tool': 'assets_commit_upload', 'arguments': {}}]}
    validate_plan(plan, allow_writes=True, background_only=True)
    with pytest.raises(ValueError): validate_plan(plan, background_only=True)
    plan['calls'][0]['tool'] = 'native_file_choose'
    with pytest.raises(ValueError): validate_plan(plan, allow_writes=True, background_only=True)


def test_source_upgrader_preserves_unknown_files_and_supports_dry_run(tmp_path, monkeypatch):
    import hashlib
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('file_upload_installer', root / 'scripts/apply_file_uploads.py')
    installer = importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)
    native = tmp_path / 'indra/newview'; native.mkdir(parents=True)
    for name in installer.BASELINES:
        (native / name).write_text('synthetic baseline')
    monkeypatch.setattr(installer, 'BASELINES', {name: hashlib.sha256(b'synthetic baseline').hexdigest() for name in installer.BASELINES})
    assert not installer.apply(tmp_path, dry_run=True)['written']
    assert all(p.read_text() == 'synthetic baseline' for p in native.iterdir())
    (native / 'fsmcpassetpolicy.h').write_text('custom work')
    with pytest.raises(ValueError, match='no files written'): installer.apply(tmp_path)
    assert (native / 'fsmcpassets.cpp').read_text() == 'synthetic baseline'
    (native / 'fsmcpassetpolicy.h').write_text('synthetic baseline')
    assert len(installer.apply(tmp_path)['files']) == 2
    assert installer.apply(tmp_path)['files'] == []
    assert all(p.read_bytes() == (root / 'viewer-extension' / p.name).read_bytes() for p in native.iterdir())
