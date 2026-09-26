"""Read-only observations for an unmodified official viewer."""
import hashlib
import os
from pathlib import Path
import re
import struct
import sys
import xml.etree.ElementTree as ET

from .process_identity import parent_viewer


def binary_identity(filename):
    """Fingerprint bytes on disk, without loading code or opening process memory."""
    path = Path(filename).resolve(strict=True)
    with path.open("rb") as handle:
        before = os.fstat(handle.fileno())
        header = handle.read(64)
        if len(header) != 64 or header[:2] != b"MZ":
            raise ValueError("Expected a Windows PE executable")
        offset = struct.unpack_from("<I", header, 60)[0]
        if offset < 64 or offset > before.st_size - 24:
            raise ValueError("Invalid PE header offset")
        handle.seek(offset)
        signature = handle.read(6)
        if signature[:4] != b"PE\0\0":
            raise ValueError("Invalid PE signature")
        machine = struct.unpack_from("<H", signature, 4)[0]
        handle.seek(0)
        sha256 = hashlib.file_digest(handle, "sha256").hexdigest()
        after = os.fstat(handle.fileno())
    current = path.stat()
    def state(stat):
        # Windows fstat/stat can disagree on ctime (creation vs metadata change).
        # Compare ctime only between calls using the same file-handle API.
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns
    if (state(before) != state(after) or state(after) != state(current)
            or before.st_ctime_ns != after.st_ctime_ns):
        raise ValueError("Viewer executable changed during inspection; inspect again")
    version = None
    if sys.platform == "win32":
        import win32api
        try:
            info = win32api.GetFileVersionInfo(str(path), "\\")
            ms, ls = info["FileVersionMS"], info["FileVersionLS"]
            version = ".".join(str(value) for value in (ms >> 16, ms & 65535, ls >> 16, ls & 65535))
        except Exception:
            # Synthetic executables and some builds do not contain version resources.
            pass
    return {"filename": path.name, "sha256": sha256, "bytes": before.st_size,
            "machine": {0x8664: "x64", 0x14c: "x86", 0xaa64: "arm64"}.get(machine, hex(machine)),
            "file_version": version, "identity_scope": "on_disk_executable",
            "running_image_verified": False, "process_memory_read": False,
            "runtime_injection_adapter_status": "not_implemented", "injection_attempted": False}


def connected_binary_identity(client):
    status = client.rpc("status")
    if not status.get("connected"):
        raise ConnectionError("No viewer bridge is connected")
    viewer = parent_viewer(status["helper_pid"])
    if sys.platform != "win32":
        raise ValueError("Executable fingerprinting currently supports Windows viewers only")
    return binary_identity(viewer.exe())


def selection_control(viewer_dir):
    document = ET.parse(Path(viewer_dir) / "skins/default/xui/en/floater_tools.xml").getroot()
    paths = []
    def visit(element, parent):
        name = element.get("name")
        path = parent + "/" + name if name else parent
        if name == "link_num_obj_count":
            paths.append(path)
        for child in element:
            if not child.tag.endswith(".string"):
                visit(child, path)
    visit(document, "/main_view/menu_stack/world_panel/Floater View")
    if len(paths) != 1:
        raise ValueError("Installed viewer has no unique link/face summary control")
    labels = {element.get("name"): (element.text or "").strip()
              for element in document.findall("floater.string")}
    return paths[0], labels


def selection_summary(client, viewer_dir):
    path, labels = selection_control(viewer_dir)
    info = client.call("LLWindow", "getInfo", {"path": path}, expect_reply=True, timeout=5)
    result = {"path": path, "evidence": "build_panel_text", "object_id": None,
              "link_number": None, "selected_faces": None, "all_sides": None,
              "full_linkset_available": False, "selection_identity_verified": False,
              "selection_changed": False, "mode": "unavailable", "raw_text": None}
    # Hidden/disabled labels can hold stale selection data. Never parse them.
    if info.get("visible_chain") is not True or info.get("enabled_chain") is not True:
        result["reason"] = "Build summary is hidden, disabled or has unknown state; open Build/Edit and select a prim"
        return result
    raw = info.get("value")
    if not isinstance(raw, str):
        result["reason"] = "Control does not expose text in this viewer"
        return result
    result["raw_text"] = raw
    text = raw.strip()
    # Labels come from installed XUI. Different active translations return raw
    # text with unknown semantics rather than being guessed from punctuation.
    for key, mode in (("link_number", "link_number"), ("selected_faces", "faces")):
        label = labels.get(key, "")
        if not label or not text.startswith(label):
            continue
        value = text[len(label):].strip()
        if mode == "link_number" and re.fullmatch(r"[0-9]{1,6}", value):
            result.update(mode=mode, link_number=int(value))
            return result
        if mode == "faces" and value == "ALL_SIDES":
            result.update(mode=mode, all_sides=True)
            return result
        if mode == "faces" and re.fullmatch(r"[0-9]{1,3}(?:\s*,\s*[0-9]{1,3})*", value):
            faces = [int(part.strip()) for part in value.split(",")]
            if len(set(faces)) == len(faces) and all(face < 256 for face in faces):
                result.update(mode=mode, selected_faces=faces, all_sides=False)
                return result
    result["reason"] = "No recognized selection summary; retain raw text without inferring IDs or numbers"
    return result
