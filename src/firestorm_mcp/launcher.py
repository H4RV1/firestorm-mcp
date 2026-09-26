"""Opt-in desktop viewer launcher. Never closes or replaces a running viewer."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

from .paths import data_root, find_viewer


def running_viewers():
    import psutil
    result = []
    for process in psutil.process_iter(["pid", "name", "exe"], ad_value=None):
        try:
            identity = (process.info["name"] or "") + " " + Path(process.info["exe"] or "").name
            if "firestorm" in identity.lower() and process.info["pid"] != os.getpid():
                result.append({"pid": process.info["pid"], "name": process.info["name"]})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return result


def editor_command(python, root):
    python = Path(python)
    if os.name == "nt" and python.with_name("pythonw.exe").is_file():
        python = python.with_name("pythonw.exe")
    values = [str(value).replace("\\", "/") for value in
              (python, Path(__file__).with_name("script_entry.py").resolve(), root)]
    if any(any(c in value for c in ('"', "\n", "\r", "\0", "%")) for value in values):
        raise ValueError("External editor paths must not contain quotes, percent signs or newlines")
    return f'"{values[0]}" "{values[1]}" --data-dir "{values[2]}" "%s"'


def session_settings(python, helper, runtime, viewer_dir, script_editor=False):
    # LLProcess treats backslashes as escapes. Quote forward-slash paths.
    raw_values = [str(p) for p in (python, helper, runtime, viewer_dir)]
    if os.name != "nt" and any("\\" in value for value in raw_values):
        raise ValueError("POSIX LEAP paths must not contain literal backslashes")
    values = [value.replace("\\", "/") for value in raw_values]
    if any(any(c in value for c in ('"', "\n", "\r", "\0")) for value in values):
        raise ValueError("Paths must not contain quotes or newlines")
    command = f'"{values[0]}" "{values[1]}" --runtime "{values[2]}" --viewer-dir "{values[3]}"'
    root = ET.Element("llsd")
    settings = ET.SubElement(root, "map")
    ET.SubElement(settings, "key").text = "LeapCommand"
    value = ET.SubElement(settings, "map")
    ET.SubElement(value, "key").text = "Type"
    ET.SubElement(value, "string").text = "LLSD"
    ET.SubElement(value, "key").text = "Value"
    ET.SubElement(ET.SubElement(value, "array"), "string").text = command
    if script_editor:
        ET.SubElement(settings, "key").text = "ExternalEditor"
        editor = ET.SubElement(settings, "map")
        ET.SubElement(editor, "key").text = "Type"
        ET.SubElement(editor, "string").text = "String"
        ET.SubElement(editor, "key").text = "Value"
        ET.SubElement(editor, "string").text = editor_command(python, Path(runtime).parent)
    return ET.tostring(root, encoding="unicode")


def launch(viewer: Path, root: Path, login_screen=False, dry_run=False, script_editor=False):
    installed = find_viewer(viewer)
    active = running_viewers()
    if active:
        raise RuntimeError("Firestorm is already running. No process was changed; coordinate a later launcher start.")
    runtime = root.expanduser().resolve() / "runtime"
    helper = Path(__file__).with_name("leap_entry.py").resolve(strict=True)
    settings = runtime / "session-settings.xml"
    xml = session_settings(Path(sys.executable), helper, runtime, installed.resources, script_editor)
    args = [str(installed.executable), "--sessionsettings", str(settings)]
    if login_screen:
        args.extend(["--set", "AutoLogin", "false"])
    if dry_run:
        return {"status": "dry_run", "viewer_started": False, "arguments": args, "helper": str(helper),
                "viewer_resources": str(installed.resources)}
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    # A creation lock prevents simultaneous launches by cooperating clients.
    lock = runtime / "launch.lock"
    with lock.open("x", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
    try:
        if running_viewers():
            raise RuntimeError("Firestorm started during preparation; no second process was launched")
        settings.write_text(xml, encoding="utf-8")
        # This is the viewer UI explicitly requested by the caller, not a hidden helper.
        process = subprocess.Popen(args, cwd=installed.cwd)
        return {"status": "process_started", "pid": process.pid, "viewer_started": True,
                "bridge_connection_verified": False, "note": "Run firestorm-mcp-check to verify LEAP; sign in in the viewer."}
    finally:
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--viewer", type=Path, help="Windows .exe, macOS .app, or Linux distribution's firestorm script")
    parser.add_argument("--data-dir", type=Path, default=data_root())
    parser.add_argument("--login-screen", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--script-editor", action="store_true", help="Register External Edit scripts with MCP for this viewer session")
    args = parser.parse_args()
    try:
        print(json.dumps(launch(args.viewer, args.data_dir, args.login_screen, args.dry_run, args.script_editor), indent=2))
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"{type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    main()
