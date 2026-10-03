"""Focus-free UI perception. Pixel capture never falls back to desktop input."""
import base64
import hashlib
import io
import json
import time
import uuid

from PIL import Image, ImageDraw

from .assets import file_record
from .ui_native import call_ui

# Explicit reviewed routes, not a naming heuristic. Callback/key/picker tools are
# excluded: callbacks may launch modal OS dialogs even without synthetic input.
BACKGROUND_READS = frozenset({
    'connection_status', 'builder_capabilities', 'assets_status', 'object_search',
    'object_selection', 'object_linkset', 'object_faces', 'script_sessions', 'script_read',
    'ui_map', 'ui_task', 'ui_tree', 'ui_read', 'ui_rows', 'ui_scene', 'ui_visualize',
    'ui_capture', 'ui_wait_change', 'background_status', 'asset_inspect',
})
BACKGROUND_WRITES = frozenset({
    'script_write', 'object_select', 'object_link_plan', 'object_link_apply', 'material_face_plan',
    'material_face_apply', 'assets_list_inventory', 'assets_search_folders',
    'assets_create_folder', 'assets_trash_empty_folder', 'assets_upload_sound',
    'assets_create_notecard', 'assets_job', 'assets_request', 'assets_cancel', 'assets_reconcile',
})


def exact_path(path):
    if not (path == '/main_view' or path.startswith('/main_view/')) or '//' in path or path.endswith('/') or len(path) > 2048:
        raise ValueError('Use an exact /main_view path')
    return path


def revision(scene):
    # Exclude timestamps and desktop focus so switching to another app does not
    # masquerade as a change to the scoped controls. No field values are read.
    data = {k: scene[k] for k in ('root', 'controls', 'truncated', 'depth_limited')}
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def render_structure(scene, max_size=1280):
    """A labelled schematic, explicitly not a screenshot or pixel evidence."""
    rect = scene['root']['rect']
    width, height = rect['right'] - rect['left'], rect['top'] - rect['bottom']
    if width <= 0 or height <= 0:
        raise ValueError('UI root has no drawable geometry')
    factor = min(1, max_size / max(width, height))
    image = Image.new('RGB', (max(1, int(width * factor)), max(1, int(height * factor)) + 30), '#151b26')
    draw = ImageDraw.Draw(image)
    draw.text((6, 7), 'STRUCTURAL UI MAP - NOT A SCREENSHOT', fill='white')
    legend = []
    for index, item in enumerate(scene['controls']):
        r = item['rect']
        box = [(r['left'] - rect['left']) * factor, 30 + (rect['top'] - r['top']) * factor,
               (r['right'] - rect['left']) * factor, 30 + (rect['top'] - r['bottom']) * factor]
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        color = '#7bdcb5' if item.get('enabled_chain') else '#747b88'
        draw.rectangle(box, outline=color, width=1)
        draw.text((box[0] + 2, box[1] + 1), str(index), fill=color)
        legend.append({'index': index, 'path': item['path'], 'name': item.get('name'), 'role': item.get('role')})
    return image, legend


def register_background_tools(tools):
    client = tools.client

    @tools.register('Report native background observation support and window render state without activation. Minimized windows support structure but cannot supply fresh rendered pixels. Capability discovery is not effect verification.', True)
    def background_status():
        state = call_ui(client, 'getContext', {})
        return {**state, 'background_reads': sorted(BACKGROUND_READS),
                'background_writes': sorted(BACKGROUND_WRITES),
                'desktop_input_used': False, 'minimized_pixels_supported': False,
                'ui_callbacks_in_background_executor': False,
                'note': 'Semantic writes still change the shared viewer/world state; task authority is required.'}

    @tools.register('Read a bounded scoped live UI scene with names, roles, geometry and a revision. No editable values or desktop input. Works while rendering is suspended; truncation/depth limits mean incomplete coverage. Paths are observations, not stable action handles.', True)
    def ui_scene(under: str, limit: int = 80, max_depth: int = 3):
        exact_path(under)
        if not 1 <= limit <= 128 or not 0 <= max_depth <= 8:
            raise ValueError('Use limit 1-128 and depth 0-8')
        scene = call_ui(client, 'getScene', dict(under=under, limit=limit, max_depth=max_depth))
        scene['revision'] = revision(scene)
        scene['observed_at'] = time.time()
        return scene

    @tools.register('Return an MCP image showing a numbered structural UI map plus exact-path legend. This is a schematic, never a screenshot. Works without foregrounding/restoring Firestorm, including minimized windows with live UI structure.', True)
    def ui_visualize(under: str, limit: int = 80, max_depth: int = 3, max_size: int = 1280):
        if not 64 <= max_size <= 1600:
            raise ValueError('max_size must be 64-1600')
        scene = ui_scene(under, limit, max_depth)
        image, legend = render_structure(scene, max_size)
        path = tools.captures / ('ui-structure-' + uuid.uuid4().hex + '.png')
        image.save(path, 'PNG')
        return {**file_record(path), 'evidence': 'ui_structure_not_pixels',
                'revision': scene['revision'], 'truncated': scene['truncated'],
                'depth_limited': scene['depth_limited'], 'context': scene['context'],
                'legend': legend, 'desktop_input_used': False, '_image_path': str(path)}

    @tools.register('Capture a scoped fresh normal Firestorm render frame as an MCP image. No OS screenshot, cursor movement, activation, forced redraw or restore. Requires a lease. Returns unavailable when minimized/rendering suspended. Up to 4M source pixels, 1600 output edge and 4MiB PNG. Viewer panels can occlude the target.', True)
    def ui_capture(path: str, max_size: int = 1280):
        exact_path(path)
        if not 64 <= max_size <= 1600:
            raise ValueError('max_size must be 64-1600')
        client.rpc('assert_control')
        ticket = call_ui(client, 'requestCapture', dict(path=path, max_size=max_size))
        if ticket.get('state') != 'pending':
            return ticket
        capture_id = str(uuid.UUID(ticket['capture_id']))
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            value = call_ui(client, 'captureResult', {'capture_id': capture_id})
            if value.get('state') == 'pending':
                time.sleep(.2)
                continue
            if value.get('state') != 'ready':
                return value
            result = dict(value['result'])
            encoded = result.pop('png')
            if not isinstance(encoded, dict) or set(encoded) != {'$binary_base64'} or not isinstance(encoded['$binary_base64'], str) or len(encoded['$binary_base64']) > 5592408:
                raise ValueError('Invalid bounded capture payload')
            png = base64.b64decode(encoded['$binary_base64'], validate=True)
            if len(png) > 4 * 1024 * 1024:
                raise ValueError('Capture exceeds 4 MiB')
            with Image.open(io.BytesIO(png)) as image:
                if image.format != 'PNG' or not 1 <= image.width <= 1600 or not 1 <= image.height <= 1600:
                    raise ValueError('Invalid capture dimensions/format')
                if [image.width, image.height] != [result.get('width'), result.get('height')]:
                    raise ValueError('Capture dimensions disagree with metadata')
                image.verify()
            filename = tools.captures / ('ui-frame-' + capture_id + '.png')
            filename.write_bytes(png)
            return {**result, **file_record(filename), 'capture_id': capture_id,
                    'desktop_input_used': False, 'focus_requested': False,
                    'simulator_effect_verified': False, '_image_path': str(filename)}
        return {'state': 'unavailable', 'reason': 'frame_deadline', 'capture_id': capture_id,
                'retry_performed': False, 'note': 'The bounded native request expires; no forced rendering was attempted.'}

    @tools.register('Wait up to ten seconds for a scoped structural UI revision to change, with bounded polling. Does not compare editable values or pixels. Returns the latest scene; incomplete scopes cannot prove absence or full UI stability.', True)
    def ui_wait_change(under: str, previous_revision: str, timeout: float = 5, limit: int = 80, max_depth: int = 3):
        exact_path(under)
        if len(previous_revision) != 64 or any(c not in '0123456789abcdef' for c in previous_revision) or not 0 <= timeout <= 10:
            raise ValueError('Use a scene revision and timeout 0-10 seconds')
        client.rpc('assert_control')
        deadline = time.monotonic() + timeout
        while True:
            scene = ui_scene(under, limit, max_depth)
            changed = scene['revision'] != previous_revision
            if changed or time.monotonic() >= deadline:
                return {'changed': changed, 'scene': scene, 'comparison': 'bounded_structure_only'}
            time.sleep(min(.25, max(0, deadline - time.monotonic())))
