"""Registered Firestorm external-editor files; no scanning of unrelated temp files."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
import uuid

import psutil

MAX_SCRIPT_BYTES = 1024 * 1024


def digest(data):
    return hashlib.sha256(data).hexdigest()


def viewer_identity(pid):
    process = psutil.Process(pid)
    if "firestorm" not in Path(process.exe()).name.lower():
        raise ValueError("The external editor must be launched by Firestorm")
    return {"pid": process.pid, "started": process.create_time()}


def _atomic_json(path, value):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class ScriptWorkspace:
    def __init__(self, root):
        self.root = Path(root) / "scripts"
        self.sessions = self.root / "sessions"

    def register(self, path, viewer):
        """Called only by the viewer-launched editor entry point."""
        path = Path(path).absolute()
        if path.is_symlink() or path.parent.resolve() != Path(tempfile.gettempdir()).resolve():
            raise ValueError("Expected a Firestorm script in the OS temporary directory")
        if not re.fullmatch(r"sl_script_(?:.*_)?[a-fA-F0-9]{32}\.lsl", path.name):
            raise ValueError("Unrecognized Firestorm external-script filename")
        path = path.resolve(strict=True)
        if path.stat().st_size > MAX_SCRIPT_BYTES:
            raise ValueError("Script exceeds the 1 MiB editing limit")
        # A new registration invalidates the previous identity, even for a reused filename.
        session_id = uuid.uuid4().hex
        self.sessions.mkdir(parents=True, exist_ok=True)
        record = {"session_id": session_id, "path": str(path), "viewer": viewer,
                  "registered_at": time.time(), "file_id": self._file_id(path),
                  "name": path.name, "object_id": None, "item_id": None}
        _atomic_json(self.sessions / (session_id + ".json"), record)
        return record

    @staticmethod
    def _file_id(path):
        stat = path.stat()
        return [stat.st_dev, stat.st_ino]

    def _record_path(self, session_id):
        if not re.fullmatch(r"[a-f0-9]{32}", session_id):
            raise ValueError("Invalid script session ID")
        return self.sessions / (session_id + ".json")

    def _load(self, session_id):
        record = json.loads(self._record_path(session_id).read_text(encoding="utf-8"))
        if record.get("session_id") != session_id:
            raise ValueError("Script registration identity mismatch")
        current = viewer_identity(record["viewer"]["pid"])
        if current != record["viewer"]:
            raise ValueError("Viewer session has ended; reopen the script with External Edit")
        path = Path(record["path"])
        if (path.is_symlink() or path.parent.resolve() != Path(tempfile.gettempdir()).resolve()
                or self._file_id(path) != record["file_id"]):
            raise ValueError("External file was replaced; reopen the script with External Edit")
        return record, path

    @contextmanager
    def _lock(self, session_id):
        # Never steal another process's lock. A crash requires explicit local recovery.
        lock = self._record_path(session_id).with_suffix(".lock")
        with lock.open("x", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        try:
            yield
        finally:
            lock.unlink()

    def list(self):
        result = []
        for record_path in sorted(self.sessions.glob("*.json")):
            try:
                record, path = self._load(record_path.stem)
                result.append({"session_id": record["session_id"], "name": record["name"],
                               "active_file": True, "bytes": path.stat().st_size,
                               "object_id": None, "item_id": None})
            except (OSError, ValueError, KeyError, psutil.Error):
                result.append({"session_id": record_path.stem, "active_file": False})
        return {"sessions": result, "source": "registered_external_editor_files",
                "note": "An active file does not prove the script editor is still open or a save has compiled."}

    @staticmethod
    def _read(path):
        with path.open("rb") as handle:
            data = handle.read(MAX_SCRIPT_BYTES + 1)
        if len(data) > MAX_SCRIPT_BYTES:
            raise ValueError("Script exceeds the 1 MiB editing limit")
        return data

    def read(self, session_id):
        record, path = self._load(session_id)
        data = self._read(path)
        return {"session_id": session_id, "name": record["name"], "source": data.decode("utf-8"),
                "sha256": digest(data), "bytes": len(data), "object_id": None, "item_id": None,
                "evidence": "external_file", "compile_verified": False}

    def write(self, session_id, source, expected_sha256, viewer_pid):
        if not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
            raise ValueError("expected_sha256 must be the hash returned by script_read")
        data = source.encode("utf-8")
        if b"\0" in data or len(data) > MAX_SCRIPT_BYTES:
            raise ValueError("Script must contain no NUL bytes and be at most 1 MiB")
        with self._lock(session_id):
            record, path = self._load(session_id)
            if record["viewer"]["pid"] != viewer_pid:
                raise ValueError("Script belongs to a different viewer than the connected bridge")
            before = self._read(path)
            if digest(before) != expected_sha256:
                raise ValueError("Script changed since it was read; read and merge before writing")
            if before == data:
                return {"status": "unchanged", "sha256": expected_sha256, "compile_verified": False}
            # Firestorm's watcher compares whole-second mtimes with >, not !=.
            # Wait for the next real second rather than setting a future timestamp.
            old_second = int(path.stat().st_mtime)
            delay = old_second + 1.05 - time.time()
            if delay > 2:
                raise ValueError("Script timestamp is in the future; cannot reliably trigger the watcher")
            if delay > 0:
                time.sleep(delay)
            record, path = self._load(session_id)
            if self._read(path) != before:
                raise ValueError("Script changed while preparing the write; read and merge before writing")
            backups = self.root / "backups" / session_id
            backups.mkdir(parents=True, exist_ok=True)
            backup = backups / (uuid.uuid4().hex + ".lsl")
            backup.write_bytes(before)
            temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
            try:
                with temporary.open("xb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                # Narrow the race with human edits; Firestorm doesn't share our lock.
                self._load(session_id)
                if self._read(path) != before:
                    raise ValueError("Script changed before replacement; nothing was submitted")
                os.replace(temporary, path)
                record["file_id"] = self._file_id(path)
                _atomic_json(self._record_path(session_id), record)
            finally:
                temporary.unlink(missing_ok=True)
            after = self._read(path)
            return {"status": "external_file_written", "session_id": session_id,
                    "sha256": digest(after), "file_write_verified": after == data,
                    "backup_path": str(backup), "compile_verified": False,
                    "simulator_save_verified": False,
                    "note": "Firestorm normally reloads and saves this file automatically. Check editor compile results before another edit."}
