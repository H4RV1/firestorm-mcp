"""Version 1 asset contract. Pure validation; never opens a viewer or account."""
import base64
import hashlib
import json
import struct
from uuid import UUID
from typing import Literal
from typing_extensions import TypedDict


class ExpectedSession(TypedDict):
    avatarId: str
    grid: Literal['agni', 'aditi', 'opensim', 'unknown']
    generation: str

MAX_AUDIO = 8 * 1024 * 1024
CHUNK_BYTES = 48 * 1024
WRITES = {'createFolder', 'trashEmptyFolder', 'uploadSound', 'createNotecard', 'deliverItem', 'dialogReply', 'touch'}
KINDS = WRITES | {'listInventory', 'searchFolders', 'objectInfo', 'taskInventory', 'reconcile'}


class AssetError(ValueError):
    def __init__(self, code, message, unknown=False, **ids):
        super().__init__(message)
        self.details = dict(code=code, message=message, unknownOutcome=unknown, **ids)


def fail(code, message):
    raise AssetError(code, message)


def identifier(value):
    try:
        result = str(UUID(str(value)))
        if UUID(result).int:
            return result
    except (ValueError, TypeError, AttributeError):
        pass
    fail('invalid_request', 'A nonzero UUID is required.')


def fingerprint(kind, arguments, expected):
    return hashlib.sha256(json.dumps([kind, arguments, expected], sort_keys=True,
        separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def validate_ogg(data):
    """Validate framing, CRC, one mono Vorbis stream, and bounded EOS duration.

    Native libvorbis additionally decodes the stream on a worker before submission.
    This parser does not claim successful codec decoding.
    """
    if not 0 < len(data) <= MAX_AUDIO:
        fail('invalid_audio', 'Ogg payload must be between 1 byte and 8 MiB.')
    offset = sequence = 0
    serial = None
    packet = bytearray()
    identified = ended = continued = False
    while offset < len(data):
        if ended or offset + 27 > len(data) or data[offset:offset+5] != b'OggS\x00':
            fail('invalid_audio', 'Invalid Ogg page or chained stream.')
        flags = data[offset+5]
        granule, page_serial, page_seq, checksum = struct.unpack_from('<QIII', data, offset+6)
        n = data[offset+26]
        end_header = offset + 27 + n
        if end_header > len(data):
            fail('invalid_audio', 'Truncated Ogg segment table.')
        laces = data[offset+27:end_header]
        end = end_header + sum(laces)
        if end > len(data) or flags & ~7 or bool(flags & 1) != continued:
            fail('invalid_audio', 'Invalid Ogg packet boundaries.')
        if serial is None:
            serial = page_serial
            if flags != 2:
                fail('invalid_audio', 'Ogg must begin with a single BOS page.')
        elif flags & 2:
            fail('invalid_audio', 'Chained Ogg is unsupported.')
        if page_serial != serial or page_seq != sequence:
            fail('invalid_audio', 'Ogg stream sequence changed.')
        page = bytearray(data[offset:end]); page[22:26] = b'\0'*4
        crc = 0
        for byte in page:
            crc = ((crc << 8) & 0xffffffff) ^ _CRC[((crc >> 24) ^ byte) & 255]
        if crc != checksum:
            fail('invalid_audio', 'Ogg checksum mismatch.')
        pos = end_header
        for size in laces:
            if not identified:
                packet.extend(data[pos:pos+size])
                if len(packet) > 4096:
                    fail('invalid_audio', 'Oversized Vorbis identification packet.')
                if size < 255:
                    if len(packet) != 30 or packet[:7] != b'\x01vorbis' or packet[7:11] != b'\0'*4 or packet[11] != 1 or struct.unpack_from('<I', packet, 12)[0] != 44100 or not packet[29] & 1:
                        fail('invalid_audio', 'Expected mono 44.1 kHz Ogg Vorbis.')
                    identified = True
            pos += size
        if laces:
            continued = laces[-1] == 255
        if flags & 4:
            ended = True
            if continued or not 0 < granule <= 30*44100:
                fail('invalid_audio', 'Sound duration must be positive and at most 30 seconds.')
        sequence += 1; offset = end
    if not identified or not ended:
        fail('invalid_audio', 'Missing Vorbis identification or Ogg EOS.')
    return data


def _crc_table():
    out = []
    for value in range(256):
        crc = value << 24
        for _ in range(8):
            crc = ((crc << 1) ^ (0x04c11db7 if crc & 0x80000000 else 0)) & 0xffffffff
        out.append(crc)
    return out


_CRC = _crc_table()


def decode_audio(value):
    if not isinstance(value, str) or len(value) > 4*((MAX_AUDIO+2)//3):
        fail('payload_too_large', 'Decoded audio limit is 8 MiB.')
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        fail('invalid_audio', 'Invalid base64 sound payload.')
    return validate_ogg(data)


def validate(kind, args, expected):
    if kind not in KINDS or not isinstance(args, dict):
        fail('unsupported_operation', 'Unsupported asset operation.')
    if not isinstance(expected, dict) or set(expected) != {'avatarId', 'grid', 'generation'} or expected['grid'] not in ('agni', 'aditi', 'opensim', 'unknown'):
        fail('invalid_request', 'Expected avatarId, grid and generation are required.')
    identifier(expected['avatarId']); identifier(expected['generation'])
    required = {
        'createFolder': {'folderId', 'parentId', 'name'},
        'trashEmptyFolder': {'folderId', 'parentFolderId', 'name', 'creationRequestId'},
        'uploadSound': {'folderId', 'name', 'description', 'expectedCost', 'audioSha256'},
        'createNotecard': {'folderId', 'name', 'description', 'text'},
        'deliverItem': {'folderId', 'itemId', 'objectId'}, 'objectInfo': {'objectId'},
        'taskInventory': {'objectId'}, 'touch': {'objectId', 'face'},
        'dialogReply': {'objectId', 'dialogId', 'buttonIndex', 'buttonLabel'},
        'searchFolders': {'query', 'maxResults'}, 'reconcile': {'originalRequestId'}, 'listInventory': set(),
    }[kind]
    optional = {'listInventory': {'folderId'}, 'uploadSound': {'stageId'},
                'createNotecard': {'existingItemId'}, 'trashEmptyFolder': {'inspectOnly'}}.get(kind, set())
    if not required <= args.keys() or args.keys() - required - optional:
        fail('invalid_request', 'Missing or unexpected operation arguments.')
    for key in ('folderId', 'parentId', 'parentFolderId', 'existingItemId', 'itemId', 'objectId', 'creationRequestId', 'dialogId', 'originalRequestId', 'stageId'):
        if key in args:
            identifier(args[key])
    for key, limit in (('name', 63), ('description', 255)):
        if key in args:
            value = args[key]
            if not isinstance(value, str) or not 1 <= len(value.encode('utf-8')) <= limit or any(ord(c) < 32 for c in value) or '|' in value or value != value.strip():
                fail('invalid_request', key + ' must be bounded printable UTF-8 with no pipe or surrounding whitespace.')
    if kind == 'uploadSound' and (type(args.get('expectedCost')) is not int or args['expectedCost'] != 0):
        fail('cost_not_zero', 'Only explicit expectedCost: 0 is supported.')
    if kind == 'createNotecard':
        value = args.get('text')
        if not isinstance(value, str) or '\0' in value or len(value.encode('utf-8')) > 65536:
            fail('invalid_request', 'Notecard text must be UTF-8, at most 65536 bytes, without NUL.')
    if len(json.dumps(args).encode()) > 128*1024:
        fail('payload_too_large', 'Metadata exceeds 128 KiB; stage sound data in bounded chunks.')
