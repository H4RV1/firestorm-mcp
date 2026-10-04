"""Read-only export checks and comparison evidence. Never claims simulator validation."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import struct
import xml.etree.ElementTree as ET

from PIL import Image, ImageChops, ImageStat


def normalize_attachment_path(filename):
    """Accept the attachment-style /C:/ prefix only on its native host."""
    filename = os.fspath(filename)
    if re.match(r"^/[A-Za-z]:[/\\]", filename):
        if os.name != "nt":
            raise ValueError("Windows attachment path requires a Windows host; provide a local asset path")
        filename = filename[1:]
    return filename


def local_asset_path(filename):
    return Path(normalize_attachment_path(filename)).resolve(strict=True)


def gltf_frame_metadata(data):
    """Describe declared node frames; do not predict a particular importer."""
    nodes = []
    defaults = {"translation": [0, 0, 0], "rotation": [0, 0, 0, 1], "scale": [1, 1, 1],
                "matrix": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}
    for index, node in enumerate(data.get("nodes", [])):
        transforms = {key: node[key] for key in defaults if key in node}
        nodes.append({"node_index": index, "name": node.get("name"), "mesh_index": node.get("mesh"),
                      "children": node.get("children", []), "declared_transform": transforms,
                      "nonidentity_transform": any(value != defaults[key] for key, value in transforms.items())})
    meshes = []
    accessors = data.get("accessors", [])
    for index, mesh in enumerate(data.get("meshes", [])):
        primitives = []
        for face, primitive in enumerate(mesh.get("primitives", [])):
            accessor_index = primitive.get("attributes", {}).get("POSITION")
            accessor = (accessors[accessor_index] if isinstance(accessor_index, int)
                        and 0 <= accessor_index < len(accessors) else {})
            primitives.append({"primitive_index": face, "material_index": primitive.get("material"),
                               "position_accessor": accessor_index, "declared_min": accessor.get("min"),
                               "declared_max": accessor.get("max")})
        meshes.append({"mesh_index": index, "name": mesh.get("name"), "primitives": primitives})
    return {"nodes": nodes, "meshes": meshes, "scene_index": data.get("scene"),
            "scenes": data.get("scenes", []), "bounds_evidence": "declared_accessor_metadata",
            "native_axes_verified": False, "native_pivots_verified": False,
            "importer_mapping_verified": False,
            "warnings": (["Nonidentity node transforms may be baked by the importer; verify native axes and pivots."]
                         if any(node["nonidentity_transform"] for node in nodes) else [])}


def file_record(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def inspect_asset(filename: str):
    path = local_asset_path(filename)
    result = {**file_record(path), "evidence_kind": "local_export_metadata", "simulator_verified": False}
    suffix = path.suffix.lower()
    if suffix == ".dae":
        if path.stat().st_size > 256 * 1024 * 1024:
            raise ValueError("DAE inspection is limited to 256 MiB")
        document = ET.parse(path)
        root = document.getroot()
        ns = {"c": root.tag.split("}")[0].removeprefix("{")} if "}" in root.tag else {}
        def findall(name):
            return root.findall(".//c:" + name, ns) if ns else root.findall(".//" + name)
        unit = findall("unit")
        up = findall("up_axis")
        images = []
        for item in findall("image"):
            source = next((e.text for e in item.iter() if e.tag.rsplit("}", 1)[-1] == "init_from"), None)
            images.append({"id": item.get("id"), "source": source})
        primitives = []
        for kind in ("triangles", "polylist", "polygons", "lines", "trifans", "tristrips"):
            for item in findall(kind):
                primitives.append({"kind": kind, "count": int(item.get("count", 0)), "material_symbol": item.get("material")})
        result.update(format="COLLADA", version=root.get("version"),
                      unit_meter=float(unit[0].get("meter", 1)) if unit else 1,
                      up_axis=up[0].text if up else "Y_UP (COLLADA default)",
                      geometry_count=len(findall("geometry")), primitives=primitives,
                      declared_triangles=sum(p["count"] for p in primitives if p["kind"] == "triangles"),
                      material_count=len(findall("material")), image_references=images)
    elif suffix in (".gltf", ".glb"):
        if path.stat().st_size > 256 * 1024 * 1024:
            raise ValueError("glTF inspection is limited to 256 MiB")
        if suffix == ".glb":
            with path.open("rb") as stream:
                magic, version, total = struct.unpack("<4sII", stream.read(12))
                if magic != b"glTF" or version != 2 or total != path.stat().st_size:
                    raise ValueError("Invalid GLB v2 header")
                length, chunk_type = struct.unpack("<II", stream.read(8))
                if chunk_type != 0x4E4F534A or length > total - 20:
                    raise ValueError("Invalid GLB JSON chunk")
                data = json.loads(stream.read(length))
        else:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        result.update(format="glTF", asset=data.get("asset"), mesh_count=len(data.get("meshes", [])),
                      materials=data.get("materials", []), images=data.get("images", []),
                      extensions_used=data.get("extensionsUsed", []),
                      frame_audit=gltf_frame_metadata(data),
                      note="File inspection does not establish support by the viewer's mesh or material importer.")
    else:
        with Image.open(path) as img:
            result.update(format=img.format, width=img.width, height=img.height, mode=img.mode,
                          channels=img.getbands())
    return result


def capture_quality(image):
    """Flag unusable flat frames without claiming that other frames show the subject."""
    rgb = image.convert("RGB")
    extrema = rgb.getextrema()
    reasons = []
    if max(high for low, high in extrema) <= 2:
        reasons.append("black_or_nearly_black")
    if max(high - low for low, high in extrema) <= 2:
        reasons.append("uniform_or_nearly_uniform")
    if "A" in image.getbands() and image.getchannel("A").getextrema()[1] == 0:
        reasons.append("fully_transparent")
    return {"status": "blank_or_nearly_blank" if reasons else "nonblank",
            "blank_detected": bool(reasons), "reasons": reasons,
            "channel_extrema_rgb_0_255": [list(pair) for pair in extrema],
            "visual_content_verified": False,
            "note": "A flagged frame is not useful scene evidence. Nonblank frames still require visual review; this does not detect all rendering failures."}


def compare_images(reference: str, observed: str, output: Path):
    with Image.open(reference) as ref, Image.open(observed) as obs:
        a, b = ref.convert("RGB"), obs.convert("RGB")
        if a.size != b.size:
            raise ValueError(f"Image dimensions differ: {a.size} vs {b.size}. Align captures before pixel comparison.")
        difference = ImageChops.difference(a, b)
        difference.save(output)
        stats = ImageStat.Stat(difference)
        return {"reference": file_record(Path(reference)), "observed": file_record(Path(observed)),
                "difference": str(output), "mean_absolute_error_rgb_0_255": stats.mean,
                "evidence_kind": "pixel_comparison", "semantic_match_verified": False,
                "note": "Lighting, camera, tone mapping and renderer differences affect this metric."}
