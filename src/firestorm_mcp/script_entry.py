"""Firestorm ExternalEditor entry point. Registers only the file passed by the viewer."""
import argparse
import json
from pathlib import Path
import sys

# Direct file execution is needed by Firestorm's command parser.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from firestorm_mcp.script_workspace import ScriptWorkspace, viewer_identity
from firestorm_mcp.process_identity import parent_viewer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("filename", type=Path)
    args = parser.parse_args()
    record = ScriptWorkspace(args.data_dir).register(args.filename, viewer_identity(parent_viewer().pid))
    if sys.stdout is not None:
        print(json.dumps({"registered": True, "session_id": record["session_id"]}))


if __name__ == "__main__":
    main()
