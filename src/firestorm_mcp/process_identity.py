"""Resolve a viewer-owned helper through the Windows Python venv redirector."""
import os
from pathlib import Path
import sys

import psutil


def parent_viewer(helper_pid=None):
    parent = psutil.Process(os.getpid() if helper_pid is None else helper_pid).parent()
    # CPython on Windows launches the base interpreter through one venv shim.
    # Do not search arbitrary ancestor chains or accept unrelated launchers.
    if parent is not None and sys.platform == "win32" and Path(parent.exe()).name.lower() in {"python.exe", "pythonw.exe"}:
        parent = parent.parent()
    if parent is None or "firestorm" not in Path(parent.exe()).name.lower():
        raise ValueError("Helper must be launched by Firestorm (directly or through one Python venv redirector)")
    return parent
