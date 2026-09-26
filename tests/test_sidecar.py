import hashlib
import os
import struct

import pytest

from firestorm_mcp.sidecar import binary_identity, selection_summary


@pytest.fixture
def viewer(tmp_path):
    xui = tmp_path / "skins/default/xui/en"
    xui.mkdir(parents=True)
    (xui / "floater_tools.xml").write_text('''<floater name="toolbox floater">
        <floater.string name="link_number">Link number:</floater.string>
        <floater.string name="selected_faces">Faces:</floater.string>
        <text name="link_num_obj_count" /></floater>''')
    return tmp_path


class Panel:
    def __init__(self, text, visible=True, enabled=True):
        self.info = dict(value=text, visible_chain=visible, enabled_chain=enabled)

    def call(self, api, operation, arguments, **kwargs):
        assert (api, operation) == ("LLWindow", "getInfo")
        assert arguments["path"].endswith("/toolbox floater/link_num_obj_count")
        return self.info


@pytest.mark.parametrize("visible,enabled", [(False, True), (True, False), (None, True)])
def test_hidden_or_unknown_panel_does_not_expose_stale_numbers(viewer, visible, enabled):
    result = selection_summary(Panel("Link number: 8", visible, enabled), viewer)
    assert result["link_number"] is None and result["raw_text"] is None


@pytest.mark.parametrize("text,field,value", [
    ("Link number: 0", "link_number", 0),
    ("Link number: 12", "link_number", 12),
    ("Faces: 0, 2, 7", "selected_faces", [0, 2, 7]),
    ("Faces: ALL_SIDES", "all_sides", True),
])
def test_panel_numbers_keep_evidence_limits(viewer, text, field, value):
    result = selection_summary(Panel(text), viewer)
    assert result[field] == value
    assert result["object_id"] is None
    assert not result["selection_identity_verified"]
    assert not result["full_linkset_available"]


@pytest.mark.parametrize("text", ["Faces: 256", "Faces: 1, 1", "Objects: 14", "[DESC] [NUM]", "Faces: -1"])
def test_unrecognized_labels_remain_unknown(viewer, text):
    result = selection_summary(Panel(text), viewer)
    assert result["mode"] == "unavailable"
    assert result["selected_faces"] is None and result["link_number"] is None


def test_disk_fingerprint_validates_pe_and_states_its_limits(tmp_path):
    binary = bytearray(128)
    binary[:2] = b"MZ"
    struct.pack_into("<I", binary, 60, 64)
    binary[64:68] = b"PE\0\0"
    struct.pack_into("<H", binary, 68, 0x8664)
    path = tmp_path / "Firestorm-test.exe"
    path.write_bytes(binary)
    # Copied build outputs preserve mtime while Windows creation/change times differ.
    os.utime(path, (1_600_000_000, 1_600_000_000))
    result = binary_identity(path)
    assert result["sha256"] == hashlib.sha256(binary).hexdigest()
    assert result["machine"] == "x64"
    assert not result["running_image_verified"] and not result["process_memory_read"]
    path.write_bytes(b"not an executable")
    with pytest.raises(ValueError, match="PE executable"):
        binary_identity(path)
