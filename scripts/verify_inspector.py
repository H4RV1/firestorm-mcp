"""Check an isolated offline server with the pinned official Inspector CLI."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

INSPECTOR = "@modelcontextprotocol/inspector@2.6.0"
npx = shutil.which("npx.cmd" if os.name == "nt" else "npx")
if not npx:
    raise SystemExit("Install Node >=22.19.0 with npx to run the optional Inspector check")

with tempfile.TemporaryDirectory(prefix="firestorm-inspector-") as temporary:
    command = [npx, "--yes", INSPECTOR, "--cli", sys.executable,
               "-m", "firestorm_mcp.server", "--data-dir", str(Path(temporary) / "offline-state"),
               "--tool-profile", "compact", "--"]

    def inspect(*options):
        result = subprocess.run([*command, *options, "--format", "json"],
                                capture_output=True, text=True, encoding="utf-8", timeout=120)
        if result.returncode:
            raise RuntimeError(f"Inspector exited {result.returncode}: {result.stderr[:1000]}")
        return json.loads(result.stdout)

    catalog = inspect("--method", "tools/list", "--strict")
    assert len(catalog["result"]["tools"]) == 56
    assert not catalog.get("schemaFindings"), catalog.get("schemaFindings")
    status = inspect("--method", "tools/call", "--tool-name", "connection_status", "--tool-args-json", "{}")
    assert not status["result"].get("isError")
    assert json.loads(status["result"]["content"][0]["text"])["connected"] is False
    print(json.dumps({"inspector": INSPECTOR, "workflow_tools": 56,
                      "schema_findings": 0, "offline_status_call": "passed", "viewer_started": False}))
