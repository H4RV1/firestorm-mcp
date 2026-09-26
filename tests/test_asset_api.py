"""Isolated bridge contract tests. No live runtime, credentials or viewer calls."""
import base64
import hashlib
import json
import sqlite3
from pathlib import Path
import struct
import time
import uuid

import pytest

from firestorm_mcp.asset_contract import AssetError, MAX_AUDIO, CHUNK_BYTES, _CRC, validate, validate_ogg, decode_audio
from firestorm_mcp.asset_gateway import AssetGateway
from firestorm_mcp.asset_journal import AssetJournal
from firestorm_mcp.server import Tools


def uid(): return str(uuid.uuid4())


def expected(): return dict(avatarId=uid(), grid='agni', generation=uid())


class FakeNative:
    def __init__(self):
        self.owner = 'client-a'; self.lease_until = time.monotonic()+60
        self.generation = uid(); self.apis = {'FSMCPAssets': {}}
        self.calls = []; self.jobs = {}; self.lose_submit = False; self.next_failure = None

    def call(self, api, op, args, **kw):
        assert api == 'FSMCPAssets'
        self.calls.append((op, args))
        if op == 'submit':
            job = dict(schema_version=1, ok=True, jobId=uid(), requestId=args['requestId'], fingerprint=args['fingerprint'], state='queued', submitted=False)
            self.jobs[job['jobId']] = job
            if self.lose_submit: raise TimeoutError('synthetic lost reply')
            if self.next_failure:
                return dict(schema_version=1, ok=False, failure=dict(code=self.next_failure, message='Synthetic refusal.', unknownOutcome=False))
            return job
        if op == 'job':
            if 'requestId' in args:
                return next((j for j in self.jobs.values() if j['requestId'] == args['requestId']),
                    dict(schema_version=1, ok=False, failure=dict(code='job_missing', message='Not retained', unknownOutcome=False)))
            return self.jobs.get(args['jobId'], dict(schema_version=1, ok=False, failure=dict(code='job_missing', message='Not retained', unknownOutcome=False)))
        if op == 'cancel':
            job = self.jobs[args['jobId']]; job['cancelRequested'] = True
            return job
        if op == 'status':
            return dict(schema_version=1, ok=True, contractVersion=1, connected=False, soundUploadCost=None)
        return dict(schema_version=1, ok=True)


@pytest.fixture
def gateway(tmp_path):
    return AssetGateway(FakeNative(), AssetJournal(tmp_path / 'private' / 'assets.sqlite3'))


def folder_request(**changes):
    value = dict(requestId=uid(), kind='createFolder', expected=expected(), arguments=dict(folderId=uid(), parentId=uid(), name='Synthetic folder'))
    value.update(changes); return value


def test_durable_duplicate_never_replays(gateway):
    request = folder_request(); first = gateway.handle('submit', request)
    second = gateway.handle('submit', request)
    assert first['jobId'] == second['jobId'] and second['state'] == 'unknown'
    assert sum(op == 'submit' for op, _ in gateway.bridge.calls) == 1
    assert gateway.journal.get(request['requestId'])['unknownOutcome']


@pytest.mark.parametrize('boundary', ['reserve', 'update'])
def test_journal_failure_never_exposes_paths_or_permits_replay(gateway, monkeypatch, boundary):
    request = folder_request()
    def unavailable(*args, **kwargs):
        raise sqlite3.OperationalError('Synthetic private filesystem path')
    with monkeypatch.context() as patch:
        patch.setattr(gateway.journal, boundary, unavailable)
        result = gateway.handle('submit', request)
    assert result['failure']['code'] == 'journal_unavailable'
    assert result['failure']['unknownOutcome']
    assert result['failure']['requestId'] == request['requestId']
    assert 'private filesystem' not in json.dumps(result)
    sent = sum(op == 'submit' for op, _ in gateway.bridge.calls)
    assert sent == (boundary == 'update')
    if boundary == 'update':
        assert gateway.handle('request', {'requestId': request['requestId']})['state'] == 'queued'
        gateway.handle('submit', request)
        assert sum(op == 'submit' for op, _ in gateway.bridge.calls) == 1


@pytest.mark.parametrize('change', ['body', 'account', 'grid', 'generation'])
def test_changed_identity_or_body_refused_for_same_request(gateway, change):
    request = folder_request(); gateway.handle('submit', request)
    request = json.loads(json.dumps(request))
    if change == 'body': request['arguments']['name'] = 'Different'
    elif change == 'account': request['expected']['avatarId'] = uid()
    elif change == 'grid': request['expected']['grid'] = 'aditi'
    else: request['expected']['generation'] = uid()
    result = gateway.handle('submit', request)
    assert result['failure']['code'] == 'request_conflict'
    assert sum(op == 'submit' for op, _ in gateway.bridge.calls) == 1


def test_lost_submission_ack_and_restart_are_unknown(gateway):
    gateway.bridge.lose_submit = True; request = folder_request()
    lost = gateway.handle('submit', request)
    assert lost['failure']['unknownOutcome'] is True
    new = AssetGateway(FakeNative(), AssetJournal(gateway.journal.path))
    result = new.handle('submit', request)
    assert result['state'] == 'unknown' and result['unknownOutcome']
    assert not any(op == 'submit' for op, _ in new.bridge.calls)


def test_lost_ack_recovers_retained_job_by_request_without_replay(gateway):
    gateway.bridge.lose_submit = True; request = folder_request()
    assert gateway.handle('submit', request)['failure']['unknownOutcome']
    observed = gateway.handle('request', {'requestId': request['requestId']})
    assert observed['state'] == 'queued' and observed['jobId']
    assert sum(op == 'submit' for op, _ in gateway.bridge.calls) == 1


def test_actual_folder_id_and_acknowledged_ids_persist(gateway):
    request = folder_request(); result = gateway.handle('submit', request)
    actual = uid(); item = uid()
    gateway.bridge.jobs[result['jobId']].update(state='unknown', submitted=True,
        acknowledged=dict(folderId=uuid.UUID(actual), itemId=uuid.UUID(item)),
        failure=dict(code='session_changed', message='Changed', unknownOutcome=True))
    gateway.handle('job', {'jobId': result['jobId']})
    saved = gateway.journal.get(request['requestId'])
    assert saved['acknowledged'] == dict(folderId=actual, itemId=item)
    assert saved['state'] == 'unknown'


def test_terminal_result_survives_native_restart(gateway):
    request = folder_request(); job = gateway.handle('submit', request)
    actual = uid(); result = dict(id=actual, requestedId=request['arguments']['folderId'], folderIdMatchesRequested=False)
    gateway.bridge.jobs[job['jobId']].update(state='succeeded', result=result)
    gateway.handle('job', {'jobId': job['jobId']})
    new = AssetGateway(FakeNative(), AssetJournal(gateway.journal.path))
    assert new.handle('submit', request)['result'] == result
    assert not any(op == 'submit' for op, _ in new.bridge.calls)


def test_evicted_native_job_does_not_turn_unknown_into_failure(gateway):
    request = folder_request(); result = gateway.handle('submit', request)
    gateway.bridge.jobs.clear()
    value = gateway.handle('job', {'jobId': result['jobId']})
    assert value['state'] == 'unknown' and value['unknownOutcome']
    assert gateway.journal.get(request['requestId'])['state'] == 'queued'


def test_reconciliation_uses_saved_intent_and_never_replays_write(gateway):
    request = folder_request(); gateway.handle('submit', request)
    current = dict(request['expected'], generation=uid())
    value = gateway.handle('submit', dict(kind='reconcile', requestId=uid(), expected=current,
        arguments=dict(originalRequestId=request['requestId'])))
    _, sent = gateway.bridge.calls[-1]
    assert sent['kind'] == 'reconcile' and sent['arguments']['intent']['arguments'] == request['arguments']
    assert 'stageId' not in sent['arguments']['intent']['arguments']
    gateway.bridge.jobs[value['jobId']].update(state='succeeded', result={'id': 'confirmed'})
    gateway.handle('job', {'jobId': value['jobId']})
    assert gateway.journal.get(request['requestId'])['reconciled']


def test_reconcile_wrong_account_or_grid_refused(gateway):
    request = folder_request(); gateway.handle('submit', request)
    result = gateway.handle('submit', dict(kind='reconcile', requestId=uid(), expected=expected(), arguments=dict(originalRequestId=request['requestId'])))
    assert result['failure']['code'] == 'session_changed'


def test_cancel_after_submit_does_not_claim_retraction(gateway):
    request = folder_request(); job = gateway.handle('submit', request)
    gateway.bridge.jobs[job['jobId']].update(state='running', submitted=True)
    result = gateway.handle('cancel', {'jobId': job['jobId']})
    assert result['cancelRequested'] and result['submitted'] and result['state'] == 'running'
    gateway.bridge.jobs[job['jobId']].update(state='succeeded', result={'id': uid()})
    assert gateway.handle('job', {'jobId': job['jobId']})['state'] == 'succeeded'


@pytest.mark.parametrize('code', ['inventory_incomplete', 'permission_denied', 'cost_not_zero', 'not_ready', 'session_changed'])
def test_native_refusal_is_structured_and_not_unknown(gateway, code):
    gateway.bridge.next_failure = code
    request = folder_request(); result = gateway.handle('submit', request)
    assert result['failure']['code'] == code and result['failure']['unknownOutcome'] is False
    assert gateway.journal.get(request['requestId'])['state'] == 'failed'


def test_expired_lease_blocks_even_generic_submit(gateway):
    gateway.bridge.lease_until = time.monotonic()-1
    result = gateway.handle('submit', folder_request())
    assert result['failure']['code'] == 'lease_required'
    assert not gateway.bridge.calls


@pytest.mark.parametrize('op,args', [('lease', {}), ('submit', {'leaseId': 'forged'})])
def test_cannot_inject_bridge_lease(gateway, op, args):
    assert gateway.handle(op, args)['failure']['code'] == 'reserved_operation'


def stage(gateway, stage_id, data, offset=0):
    return gateway.handle('stage', dict(stageId=stage_id, offset=offset, data={'$binary_base64': base64.b64encode(data).decode()}))


def test_stage_bounds_offsets_owner_and_hash(gateway):
    stage_id = uid(); assert stage(gateway, stage_id, b'abc')['ok']
    assert stage(gateway, stage_id, b'd', 0)['failure']['code'] == 'stage_offset'
    assert stage(gateway, stage_id, b'x'*(CHUNK_BYTES+1), 3)['failure']['code'] == 'payload_too_large'
    gateway.bridge.owner = 'different client'
    assert stage(gateway, stage_id, b'd', 3)['failure']['code'] == 'stage_offset'
    gateway.bridge.owner = 'client-a'
    args = dict(folderId=uid(), name='Sound', description='unique marker', expectedCost=0, stageId=stage_id, audioSha256='0'*64)
    result = gateway.handle('submit', dict(kind='uploadSound', requestId=uid(), expected=expected(), arguments=args))
    assert result['failure']['code'] == 'stage_mismatch'
    args['audioSha256'] = hashlib.sha256(b'abc').hexdigest()
    request = dict(kind='uploadSound', requestId=uid(), expected=expected(), arguments=args)
    assert gateway.handle('submit', request)['ok']
    saved = gateway.journal.get(request['requestId'])
    assert 'stageId' not in saved['arguments'] and 'oggBase64' not in json.dumps(saved)


def test_stage_count_and_expiry_are_bounded(gateway):
    for _ in range(4): assert stage(gateway, uid(), b'a')['ok']
    assert stage(gateway, uid(), b'a')['failure']['code'] == 'stage_limit'
    for entry in gateway.stages.values(): entry['expires'] = 0
    assert stage(gateway, uid(), b'a')['ok'] and len(gateway.stages) == 1


def test_journal_capacity_does_not_evict_uncertain_writes(gateway):
    gateway.journal.LIMIT = 1
    first = folder_request(); gateway.handle('submit', first)
    assert gateway.handle('submit', folder_request())['failure']['code'] == 'journal_full'
    assert gateway.journal.get(first['requestId']) is not None


def test_cleanup_receipt_cannot_be_forged(gateway):
    request = folder_request(); request['arguments']['creationReceipt'] = {'fake': True}
    assert gateway.handle('submit', request)['failure']['code'] == 'reserved_field'


def page(payload, flags, seq, granule=0):
    laces = bytes([255])*(len(payload)//255) + bytes([len(payload)%255])
    out = bytearray(b'OggS\0'+bytes([flags])+struct.pack('<QIII', granule, 42, seq, 0)+bytes([len(laces)])+laces+payload)
    crc = 0
    for b in out: crc = ((crc << 8) & 0xffffffff) ^ _CRC[((crc >> 24) ^ b) & 255]
    struct.pack_into('<I', out, 22, crc)
    return bytes(out)


def framed_audio():
    ident = b'\x01vorbis' + b'\0'*4 + b'\x01' + struct.pack('<I',44100) + b'\0'*12 + b'\xb8\x01'
    return page(ident, 2, 0) + page(b'synthetic packet; not a real codec fixture', 4, 1, 44100)


def test_structural_validation_does_not_claim_codec_decode():
    data = framed_audio()
    assert validate_ogg(data) == data  # native libvorbis test separately rejects invalid codec packets
    damaged = bytearray(data); damaged[-1] ^= 1
    for invalid in (b'', bytes(damaged), data[:-1], data+data, data+b'garbage', b'x'*(MAX_AUDIO+1)):
        with pytest.raises(AssetError): validate_ogg(invalid)


@pytest.mark.parametrize('value', ['?', 'abcd=', 'A'*(4*((MAX_AUDIO+2)//3)+1)], ids=['invalid', 'padding', 'oversized'])
def test_base64_invalid_and_oversized(value):
    with pytest.raises(AssetError): decode_audio(value)


@pytest.mark.parametrize('cost', [-1, 1, None, True, '0'])
def test_explicit_integer_zero_required(cost):
    args = dict(folderId=uid(), name='Sound', description='marker', expectedCost=cost, audioSha256='0'*64)
    with pytest.raises(AssetError): validate('uploadSound', args, expected())


def test_utf8_limits_and_exact_metadata():
    args = dict(folderId=uid(), name='café', description='Exact marker', text='text\nwith no extra newline')
    validate('createNotecard', args, expected())
    for text in ('a\0b', 'x'*65537, '木'*22000):
        with pytest.raises(AssetError): validate('createNotecard', dict(args, text=text), expected())


def test_stock_viewer_gates_assets_without_mutation(tmp_path):
    tools = Tools(root=tmp_path, viewer_dir=tmp_path, tool_profile='compact')
    tools.client.rpc = lambda method: {}  # only discovery
    result = tools.local['assets_status']()
    assert result['failure']['code'] == 'unsupported_viewer'
    assert len(tools.local) == 72
    assert tools.definitions['assets_upload_sound'].input_schema['properties']['expected']['$ref']


def test_bridge_generation_is_nonsecret_and_fee_stays_unknown(gateway):
    status = gateway.handle('status', {})
    assert status['soundUploadCost'] is None and not status['connected']
    assert status['bridgeGeneration'] == gateway.bridge.generation
    assert 'sessionId' not in status and 'token' not in status


def test_typed_sound_wrapper_chunks_exact_bytes_and_preserves_metadata(gateway, tmp_path):
    tools = Tools(root=tmp_path / 'client', viewer_dir=tmp_path, tool_profile='compact')
    tools.client.apis = {'FSMCPAssets': {}}
    tools.client.call = lambda api, op, args, **kwargs: gateway.handle(op, args)
    ident = b'\x01vorbis' + b'\0'*4 + b'\x01' + struct.pack('<I',44100) + b'\0'*12 + b'\xb8\x01'
    data = page(ident, 2, 0) + page(b'x'*60000, 4, 1, 44100)
    request = dict(request_id=uid(), expected=expected(), folder_id=uid(), name='Exact 01',
                   description='Unique marker 01', ogg_base64=base64.b64encode(data).decode(), expected_cost=0)
    result = tools.call('assets_upload_sound', request)
    assert result['state'] == 'queued'
    chunks = [base64.b64decode(a['data']['$binary_base64']) for op, a in gateway.bridge.calls if op == 'stage']
    assert len(chunks) == 2 and all(len(c) <= CHUNK_BYTES for c in chunks) and b''.join(chunks) == data
    sent = next(a for op, a in gateway.bridge.calls if op == 'submit')
    assert sent['arguments']['name'] == request['name'] and sent['arguments']['description'] == request['description']
    assert gateway.stages == {}
    # Retry uses journal before staging: no new payload frames or new submit.
    assert tools.call('assets_upload_sound', request)['jobId'] == result['jobId']
    assert sum(op == 'stage' for op, _ in gateway.bridge.calls) == 2
    assert sum(op == 'submit' for op, _ in gateway.bridge.calls) == 1
