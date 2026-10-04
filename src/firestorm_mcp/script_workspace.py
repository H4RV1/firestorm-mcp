"""Registered Firestorm external-editor files; no scanning of unrelated temp files."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sys
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
        _cleanup(temporary)


class ScriptConflict(ValueError):
    """Conflict evidence for registered external files, never simulator identity."""
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code = code
        self.details = dict(code=code, message=message, unknownOutcome=False)
        self.details.update(details)


class ScriptCleanupError(OSError):
    """Owned cleanup failed; the write wrapper supplies effect evidence."""


def _cleanup(path, identity=None):
    original = sys.exception()
    try:
        if identity is not None and path.exists():
            stat = path.stat()
            if [stat.st_dev, stat.st_ino] != identity[:2] or path.read_text(encoding="utf-8") != identity[2]:
                raise ScriptCleanupError("Owned lock was replaced; it was not removed")
        path.unlink(missing_ok=True)
    except OSError:
        if original is not None:
            # Retain the primary failure and its structured outcome evidence.
            if isinstance(original, ScriptConflict):
                original.details['cleanup_verified'] = False
            original.add_note("Owned cleanup could not be confirmed; retained locks require explicit local recovery.")
            return
        raise ScriptCleanupError("Owned cleanup could not be confirmed; retained locks require explicit local recovery.") from None


class ScriptWorkspace:
    def __init__(self, root):
        self.root = Path(root) / "scripts"
        self.sessions = self.root / "sessions"

    @contextmanager
    def _path_lock(self, path):
        locks = self.root / "locks"
        locks.mkdir(parents=True, exist_ok=True)
        # Shared by registration and writes, including different session IDs.
        key = digest(os.path.normcase(str(Path(path).resolve())).encode("utf-8"))
        lock = locks / (key + ".lock")
        token = str(os.getpid()) + ":" + uuid.uuid4().hex
        with lock.open("x", encoding="utf-8") as handle:
            handle.write(token)
            stat = os.fstat(handle.fileno())
            identity = [stat.st_dev, stat.st_ino, token]
        try:
            yield
        finally:
            _cleanup(lock, identity)

    def register(self, path, viewer):
        with self._path_lock(path):
            return self._register(path, viewer)

    def _register(self, path, viewer):
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
        # Persist supersession before publishing the replacement session.
        for previous in self.sessions.glob("*.json"):
            try:
                old = json.loads(previous.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if (isinstance(old, dict) and isinstance(old.get("path"), str)
                    and os.path.normcase(old["path"]) == os.path.normcase(str(path))
                    and old.get("viewer") == viewer):
                old.update(state="superseded", superseded_by=session_id)
                _atomic_json(previous, old)
        record["state"] = "registered"
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
        if record.get("state") == "superseded":
            raise ScriptConflict("superseded", "Script registration was superseded; use the reopened session")
        try:
            current = viewer_identity(record["viewer"]["pid"])
        except psutil.NoSuchProcess:
            raise ScriptConflict("viewer_ended", "Viewer session has ended; reopen the script with External Edit") from None
        if current != record["viewer"]:
            raise ScriptConflict("viewer_ended", "Viewer session has ended; reopen the script with External Edit")
        path = Path(record["path"])
        if not path.exists():
            raise ScriptConflict("file_missing", "External script file is missing; reopen the script with External Edit")
        if (path.is_symlink() or path.parent.resolve() != Path(tempfile.gettempdir()).resolve()
                or self._file_id(path) != record["file_id"]):
            raise ScriptConflict("file_replaced", "External file was replaced; reopen the script with External Edit")
        return record, path

    @contextmanager
    def _lock(self, session_id):
        # Never steal another process's lock. A crash requires explicit local recovery.
        lock = self._record_path(session_id).with_suffix(".lock")
        token = str(os.getpid()) + ":" + uuid.uuid4().hex
        with lock.open("x", encoding="utf-8") as handle:
            handle.write(token)
            stat = os.fstat(handle.fileno())
            identity = [stat.st_dev, stat.st_ino, token]
        try:
            yield
        finally:
            _cleanup(lock, identity)

    def list(self):
        result = []
        for record_path in sorted(self.sessions.glob("*.json")):
            try:
                record, path = self._load(record_path.stem)
                result.append({"session_id": record["session_id"], "name": record["name"],
                               "active_file": True, "state": "registered", "bytes": path.stat().st_size,
                               "object_id": None, "item_id": None})
            except (OSError, ValueError, KeyError, psutil.Error) as exc:
                state = getattr(exc, "code", "file_missing" if isinstance(exc, FileNotFoundError) else "unavailable")
                result.append({"session_id": record_path.stem, "active_file": False, "state": state})
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
        write_id = uuid.uuid4().hex
        try:
            return self._write(session_id, source, expected_sha256, viewer_pid, write_id)
        except ScriptCleanupError:
            receipt_path = self.root / "receipts" / session_id / (write_id + ".json")
            try:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                receipt = {}
            fields = {key: receipt[key] for key in
                      ("write_id", "previous_sha256", "source_sha256", "sha256", "file_write_verified")
                      if key in receipt}
            if receipt:
                try:
                    observed = self.read(session_id)
                    fields.update(sha256=observed['sha256'],
                                  file_write_verified=observed['sha256'] == receipt['source_sha256'])
                except (OSError, ValueError, psutil.Error):
                    pass
            fields.update(session_id=session_id, cleanup_verified=False,
                          unknownOutcome=receipt.get("unknownOutcome", False),
                          compile_verified=False, simulator_save_verified=False)
            if receipt:
                fields['receipt_path'] = str(receipt_path)
            raise ScriptConflict("external_write_cleanup_failed",
                "Owned cleanup failed. Inspect the write receipt before retrying; retained locks require explicit local recovery.",
                **fields) from None

    def _write(self, session_id, source, expected_sha256, viewer_pid, write_id):
        if not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
            raise ValueError("expected_sha256 must be the hash returned by script_read")
        data = source.encode("utf-8")
        if b"\0" in data or len(data) > MAX_SCRIPT_BYTES:
            raise ValueError("Script must contain no NUL bytes and be at most 1 MiB")
        record, path = self._load(session_id)
        with self._path_lock(path), self._lock(session_id):
            record, path = self._load(session_id)
            if record["viewer"]["pid"] != viewer_pid:
                raise ScriptConflict("viewer_mismatch", "Script belongs to a different viewer than the connected bridge")
            before = self._read(path)
            if digest(before) != expected_sha256:
                raise ScriptConflict("source_changed", "Script changed since it was read; read and merge before writing")
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
                raise ScriptConflict("source_changed", "Script changed while preparing the write; read and merge before writing")
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
                    raise ScriptConflict("source_changed", "Script changed before replacement; nothing was submitted")
                # Record intent before replacing the watched file. An interrupted
                # metadata update must never look like a safe-to-retry failure.
                receipts = self.root / "receipts" / session_id
                receipts.mkdir(parents=True, exist_ok=True)
                receipt_path = receipts / (write_id + ".json")
                receipt = {"write_id": write_id, "session_id": session_id,
                           "previous_sha256": expected_sha256, "source_sha256": digest(data),
                           "source_origin": "registered_external_file", "state": "prepared",
                           "unknownOutcome": True, "compile_verified": False,
                           "simulator_save_verified": False}
                _atomic_json(receipt_path, receipt)
                # Preparing a receipt takes filesystem time; revalidate again.
                self._load(session_id)
                if self._read(path) != before:
                    raise ScriptConflict("source_changed", "Script changed before replacement; nothing was submitted")
                os.replace(temporary, path)
                registration_updated = False
                try:
                    record["file_id"] = self._file_id(path)
                    _atomic_json(self._record_path(session_id), record)
                    registration_updated = True
                    after = self._read(path)
                    receipt.update(state="external_file_written", sha256=digest(after),
                                   file_write_verified=after == data, unknownOutcome=False)
                    _atomic_json(receipt_path, receipt)
                except ScriptCleanupError:
                    raise
                except (OSError, ValueError):
                    try:
                        observed = self._read(path)
                    except (OSError, ValueError):
                        observed = None
                    raise ScriptConflict("external_write_outcome_unknown",
                        "The external file was replaced but its receipt or registration could not be confirmed. Inspect the file and receipt before another write.",
                        write_id=write_id, session_id=session_id,
                        previous_sha256=expected_sha256, source_sha256=digest(data),
                        sha256=digest(observed) if observed is not None else None,
                        file_write_verified=observed == data if observed is not None else None,
                        registration_update_verified=registration_updated,
                        unknownOutcome=True, compile_verified=False,
                        simulator_save_verified=False, receipt_path=str(receipt_path)) from None
            finally:
                _cleanup(temporary)
            return {"write_id": write_id, "receipt_path": str(receipt_path), "status": "external_file_written", "session_id": session_id,
                    "sha256": digest(after), "previous_sha256": expected_sha256,
                    "source_origin": "registered_external_file", "file_write_verified": after == data,
                    "backup_path": str(backup), "compile_verified": False,
                    "simulator_save_verified": False,
                    "note": "Firestorm normally reloads and saves this file automatically. Check editor compile results before another edit."}
