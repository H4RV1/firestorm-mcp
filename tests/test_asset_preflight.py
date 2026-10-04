import json
import os
import struct

import pytest

from firestorm_mcp.assets import inspect_asset, local_asset_path


@pytest.mark.parametrize("suffix", [".gltf", ".glb"])
def test_declared_frames_warn_about_baking_without_claiming_native_mapping(tmp_path, suffix):
    document = {"asset": {"version": "2.0"}, "nodes": [
        {"name": "rotated", "mesh": 0, "rotation": [0, 0, 1, 0]},
        {"name": "identity", "mesh": 0}],
        "meshes": [{"name": "synthetic", "primitives": [
            {"attributes": {"POSITION": 0}, "material": 1},
            {"attributes": {"POSITION": 99}}]}],
        "accessors": [{"min": [-1, -2, -3], "max": [1, 2, 3]}]}
    path = tmp_path / ("fixture" + suffix)
    payload = json.dumps(document).encode()
    if suffix == ".glb":
        payload += b" " * (-len(payload) % 4)
        path.write_bytes(struct.pack("<4sIIII", b"glTF", 2, 20 + len(payload),
                                     len(payload), 0x4E4F534A) + payload)
    else:
        path.write_bytes(payload)
    result = inspect_asset(str(path))
    audit = result["frame_audit"]
    assert audit["nodes"][0]["nonidentity_transform"] is True
    assert audit["nodes"][1]["nonidentity_transform"] is False
    assert audit["meshes"][0]["primitives"][0]["declared_min"] == [-1, -2, -3]
    assert audit["meshes"][0]["primitives"][1]["declared_min"] is None
    assert audit["warnings"]
    assert audit["native_axes_verified"] is False
    assert audit["native_pivots_verified"] is False
    assert audit["importer_mapping_verified"] is False


def test_attachment_windows_path_is_host_aware(tmp_path):
    if os.name == "nt":
        path = tmp_path / "fixture.gltf"
        path.write_text('{"asset":{"version":"2.0"}}')
        assert local_asset_path("/" + path.as_posix()) == path.resolve()
    else:
        with pytest.raises(ValueError, match="Windows host"):
            local_asset_path("/C:/fixture.gltf")
