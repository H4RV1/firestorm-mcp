import asyncio
import json
from pathlib import Path
import sys

import pytest
from PIL import Image
from mcp import Client, StdioServerParameters

from firestorm_mcp.assets import inspect_asset, compare_images
from firestorm_mcp.server import Tools

FIXTURE = Path(__file__).parent / "fixtures/synthetic-cube.dae"


def test_collada_metadata():
    result = inspect_asset(str(FIXTURE))
    assert result["geometry_count"] == 1
    assert result["declared_triangles"] == 12
    assert result["unit_meter"] == 1
    assert result["up_axis"] == "Z_UP"
    assert result["simulator_verified"] is False
    assert len(result["sha256"]) == 64


def test_image_comparison_dimensions_and_difference(tmp_path):
    a, b, c = [tmp_path / name for name in ("a.png", "b.png", "diff.png")]
    Image.new("RGB", (32, 32), (10, 20, 30)).save(a)
    Image.new("RGB", (32, 32), (20, 40, 60)).save(b)
    result = compare_images(str(a), str(b), c)
    assert result["mean_absolute_error_rgb_0_255"] == [10, 20, 30]
    assert result["semantic_match_verified"] is False
    Image.new("RGB", (64, 32)).save(b)
    with pytest.raises(ValueError, match="dimensions differ"):
        compare_images(str(a), str(b), c)


def test_no_false_connection_success(tmp_path):
    tools = Tools(tmp_path)
    assert tools.call("connection_status", {})["connected"] is False
    with pytest.raises(ConnectionError):
        tools.call("snapshot", {})


@pytest.mark.parametrize("fee,expected", [("Upload fee: L$ 17", 17),
    ("Upload fee: L$ 0", 0), ("Upload fee: L$ TBD", None),
    ("Upload fee: L$ 17 (old)", None)])
def test_preview_readback_never_claims_fresh_quote_or_hidden_warning(tmp_path, fee, expected):
    viewer = tmp_path / "viewer"
    xui = viewer / "skins/default/xui/en"
    xui.mkdir(parents=True)
    (xui / "floater_model_preview.xml").write_text(
        '<floater name="Model Preview"><text name="upload_fee"/>'
        '<text name="warning_message"/><text name="physics_file"/></floater>')
    tools = Tools(tmp_path, viewer)

    def reply(api, op, arguments, **kwargs):
        name = arguments["path"].rsplit("/", 1)[-1]
        if api == "UI":
            if name == "physics_file":
                return {}  # No value is different from an empty filename.
            return {"value": fee if name == "upload_fee" else "You cannot upload"}
        if name == "physics_file":
            return {}  # Unknown visibility must not be reported as visible/hidden.
        return {"visible_chain": name != "warning_message", "enabled_chain": True}

    tools.client.call = reply
    status = tools.call("mesh_upload_status", {})
    assert status["quote"]["amount_linden_dollars"] == expected
    assert status["quote"]["freshness_verified"] is False
    assert status["quote"]["calculation_requested"] is False
    assert status["upload_verified"] is False
    assert status["file_content_bindings_verified"] is False
    assert status["readback_atomic"] is False
    controls = status["controls"]
    assert controls["warning_message"]["value"] == "You cannot upload"
    assert controls["warning_message"]["visible"] is False
    assert controls["physics_file"]["available"] is False
    assert controls["physics_file"]["visible"] is None
    assert controls["lod_file_low"]["available"] is False
    assert "not present" in controls["lod_file_low"]["error"]


def test_real_mcp_stdio_handshake_offline(tmp_path):
    async def scenario():
        params = StdioServerParameters(command=sys.executable, args=["-m", "firestorm_mcp.server", "--root", str(tmp_path)])
        async with Client(params) as session:
            assert session.server_info.name == "firestorm-mcp"
            assert session.protocol_version == "2026-07-28"
            listed = await session.list_tools()
            assert len(listed.tools) == 56
            guide = await session.call_tool("ui_task", {})
            assert not guide.is_error
            task_result = json.loads(guide.content[0].text)
            assert len(task_result["tasks"]) == 6 and task_result["live_contacted"] is False
            response = await session.call_tool("asset_inspect", {"filename": str(FIXTURE.resolve())})
            assert not response.is_error
            assert '"declared_triangles": 12' in response.content[0].text
            missing = await session.call_tool("viewer_call", {"api": "missing", "operation": "missing"})
            assert missing.is_error
    asyncio.run(asyncio.wait_for(scenario(), 30))
