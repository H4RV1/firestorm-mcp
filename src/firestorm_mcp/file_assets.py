"""Bounded local upload inputs. No viewer, network fetches or file-picker input."""
import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import struct
from urllib.parse import unquote, urlsplit

from PIL import Image

from .asset_contract import identifier
from .assets import normalize_attachment_path

MAX_SOURCE = 32 * 1024 * 1024
MAX_PAYLOAD = 8 * 1024 * 1024


def read_file(filename):
    filename = normalize_attachment_path(filename)
    path = Path(filename)
    if not path.is_absolute() or str(filename).startswith(('//', '\\\\')):
        raise ValueError('Use an absolute local file path')
    path = path.resolve(strict=True)
    with path.open('rb') as stream:
        data = stream.read(MAX_SOURCE + 1)
    if not 0 < len(data) <= MAX_SOURCE:
        raise ValueError('Source must contain 1 byte to 32 MiB')
    return path, data


def digest(data):
    return hashlib.sha256(data).hexdigest()


def document(filename):
    path, data = read_file(filename)
    binary = None
    if path.suffix.lower() == '.glb':
        if len(data) < 20 or struct.unpack_from('<4sII', data) != (b'glTF', 2, len(data)):
            raise ValueError('Invalid GLB v2 header')
        offset, chunks = 12, []
        while offset < len(data):
            if offset + 8 > len(data):
                raise ValueError('Truncated GLB chunk')
            length, kind = struct.unpack_from('<II', data, offset)
            offset += 8
            if length % 4 or offset + length > len(data):
                raise ValueError('Invalid GLB chunk length')
            chunks.append((kind, data[offset:offset + length]))
            offset += length
        if not chunks or chunks[0][0] != 0x4e4f534a or len(chunks) > 2 or (len(chunks) == 2 and chunks[1][0] != 0x004e4942):
            raise ValueError('Expected GLB JSON and optional BIN chunks')
        model = json.loads(chunks[0][1])
        binary = chunks[1][1] if len(chunks) == 2 else None
    elif path.suffix.lower() == '.gltf':
        model = json.loads(data.decode('utf-8-sig'))
    else:
        raise ValueError('Material source must be glTF or GLB')
    if not isinstance(model, dict) or model.get('asset', {}).get('version') != '2.0':
        raise ValueError('Expected glTF 2.0')
    return path, data, model, binary


def resource(path, uri):
    if not isinstance(uri, str):
        raise ValueError('Invalid image/buffer URI')
    if uri.startswith('data:'):
        header, sep, value = uri.partition(',')
        if not sep or not header.endswith(';base64') or len(value) > (MAX_SOURCE + 2) // 3 * 4:
            raise ValueError('Expected bounded base64 data URI')
        return base64.b64decode(value, validate=True)
    parsed = urlsplit(uri)
    decoded = unquote(parsed.path)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or '\\' in decoded or ':' in decoded:
        raise ValueError('Only local relative dependencies are supported')
    dependency = (path.parent / decoded).resolve(strict=True)
    if not dependency.is_relative_to(path.parent):
        raise ValueError('Dependency escapes source directory')
    return read_file(dependency)[1]


def indexed(rows, index):
    if not isinstance(rows, list) or type(index) is not int or not 0 <= index < len(rows):
        raise ValueError('Invalid glTF index')
    return rows[index]


def image_bytes(path, model, binary, index):
    image = indexed(model.get('images'), index)
    if 'uri' in image:
        return resource(path, image['uri'])
    view = indexed(model.get('bufferViews'), image.get('bufferView'))
    buffer_index = view.get('buffer')
    buffer = indexed(model.get('buffers'), buffer_index)
    data = resource(path, buffer['uri']) if 'uri' in buffer else binary if buffer_index == 0 else None
    start, length, declared = view.get('byteOffset', 0), view.get('byteLength'), buffer.get('byteLength')
    if data is None or any(type(v) is not int for v in (start, length, declared)) or start < 0 or length <= 0 or start + length > declared or declared > len(data):
        raise ValueError('Invalid embedded image bounds')
    return data[start:start + length]


def texture_payload(filename, image_index=None):
    if image_index is None:
        _, data = read_file(filename)
    else:
        path, _, model, binary = document(filename)
        data = image_bytes(path, model, binary, image_index)
    with Image.open(io.BytesIO(data)) as image:
        if image.format not in {'PNG', 'JPEG', 'BMP', 'TGA'} or getattr(image, 'n_frames', 1) != 1:
            raise ValueError('Use a static PNG, JPEG, BMP or TGA image')
        width, height = image.size
        if any(n < 4 or n > 2048 or n & (n - 1) for n in (width, height)):
            raise ValueError('Texture dimensions must be powers of two from 4 to 2048; resize explicitly before uploading')
        # Preserve alpha (including palette transparency), without silent resizing.
        image = image.convert('RGBA' if 'A' in image.getbands() or 'transparency' in image.info else 'RGB')
        output = io.BytesIO()
        image.save(output, format='PNG')
    payload = output.getvalue()
    if len(payload) > MAX_PAYLOAD:
        raise ValueError('Normalized PNG exceeds the 8 MiB stage limit')
    return payload, dict(sourceSha256=digest(data), payloadSha256=digest(payload), width=width, height=height)


def material_payload(filename, material_index=0, texture_bindings=None, inspect_only=False):
    path, source, model, binary = document(filename)
    material = copy.deepcopy(indexed(model.get('materials'), material_index))
    if model.get('extensionsRequired') or material.get('extensions'):
        raise ValueError('Material extensions are not supported by this uploader')
    supported = {'name', 'extras', 'pbrMetallicRoughness', 'normalTexture', 'occlusionTexture', 'emissiveTexture',
                 'emissiveFactor', 'alphaMode', 'alphaCutoff', 'doubleSided'}
    if set(material) - supported:
        raise ValueError('Unsupported material properties')
    material.pop('extras', None)
    pbr = material.get('pbrMetallicRoughness', {})
    if set(pbr) - {'baseColorTexture', 'metallicRoughnessTexture', 'baseColorFactor', 'metallicFactor', 'roughnessFactor'}:
        raise ValueError('Unsupported PBR properties')
    def factor(obj, key, size=None, upper=1):
        if key not in obj:
            return
        values = obj[key] if size else [obj[key]]
        if not isinstance(values, list) or (size and len(values) != size) or any(type(v) not in (int, float) or not 0 <= v <= upper for v in values):
            raise ValueError('Invalid material factor: ' + key)
    for key in ('metallicFactor', 'roughnessFactor'):
        factor(pbr, key)
    factor(pbr, 'baseColorFactor', 4)
    factor(material, 'emissiveFactor', 3)
    factor(material, 'alphaCutoff')
    if material.get('alphaMode', 'OPAQUE') not in {'OPAQUE', 'MASK', 'BLEND'} or type(material.get('doubleSided', False)) is not bool:
        raise ValueError('Invalid alpha mode or doubleSided flag')
    refs = [(pbr, 'baseColorTexture'), (pbr, 'metallicRoughnessTexture'), (material, 'normalTexture'), (material, 'emissiveTexture')]
    occlusion = material.get('occlusionTexture')
    if occlusion:
        orm = pbr.get('metallicRoughnessTexture')
        if not orm or occlusion.get('index') != orm.get('index') or occlusion.get('strength', 1) != 1 or occlusion.get('texCoord', 0) != 0 or occlusion.get('extensions'):
            raise ValueError('Occlusion must share the metallic/roughness texture with default strength and UVs')
        material.pop('occlusionTexture')
    bindings = texture_bindings or {}
    textures, images, dependencies, used = [], [], [], set()
    for parent, slot in refs:
        if slot not in parent:
            continue
        info = parent[slot]
        if info.get('texCoord', 0) != 0 or info.get('extensions') or info.get('scale', 1) != 1 or set(info) - {'index', 'texCoord', 'scale'}:
            raise ValueError('Texture transforms, alternate UVs and normal scaling must be baked before upload')
        texture = indexed(model.get('textures'), info.get('index'))
        index = texture.get('source')
        original = indexed(model.get('images'), index)
        if texture.get('extensions'):
            raise ValueError('Texture extensions are unsupported')
        if 'sampler' in texture:
            sampler = indexed(model.get('samplers'), texture['sampler'])
            if sampler.get('wrapS', 10497) != 10497 or sampler.get('wrapT', 10497) != 10497 or sampler.get('extensions'):
                raise ValueError('Non-repeating texture samplers must be baked before upload')
        existing = None
        try:
            existing = identifier(original.get('uri'))
        except ValueError:
            pass
        key = str(index)
        asset = identifier(bindings[key]) if key in bindings else existing
        used.add(key)
        if key not in {str(d['image_index']) for d in dependencies}:
            dependency = dict(image_index=index, existing_asset_id=existing, bound_asset_id=asset)
            if not existing and not asset:
                raw = image_bytes(path, model, binary, index)
                dependency.update(source_sha256=digest(raw), bytes=len(raw))
            dependencies.append(dependency)
        if not asset and not inspect_only:
            raise ValueError('Upload dependency image_index ' + key + ' first, then provide its confirmed texture UUID in texture_bindings')
        parent[slot] = {'index': len(textures)}
        textures.append({'source': len(images)})
        images.append({'uri': asset or '00000000-0000-0000-0000-000000000000'})
    if set(bindings) - used:
        raise ValueError('Texture bindings contain unused image indices')
    normalized = {'asset': {'version': '2.0'}, 'materials': [material], 'textures': textures, 'images': images}
    payload = json.dumps(normalized, separators=(',', ':'), allow_nan=False).encode()
    if len(payload) > 16384:
        raise ValueError('Material definition exceeds 16 KiB')
    return payload, dict(sourceSha256=digest(source), payloadSha256=digest(payload), dependencies=dependencies,
                         material_index=material_index, texture_references_verified=False)


def inspect_upload(filename, material_index=0):
    if Path(filename).suffix.lower() in {'.gltf', '.glb'}:
        _, metadata = material_payload(filename, material_index, inspect_only=True)
        kind = 'material'
    else:
        _, metadata = texture_payload(filename)
        kind = 'texture'
    return dict(schema_version=1, asset_type=kind, evidence_kind='local_upload_input',
                upload_verified=False, **metadata)
