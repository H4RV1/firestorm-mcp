"""Apply the experimental builder hook to an explicit Firestorm source checkout.

Does not touch an installed viewer, download dependencies or compile anything.
All anchors and destinations are validated before any writes.
"""
import argparse
from pathlib import Path
import re


def apply(checkout, dry_run=False, profile_name=None):
    source = Path(__file__).resolve().parents[1] / "viewer-extension"
    newview = Path(checkout).resolve(strict=True) / "indra/newview"
    edits = {}
    cmake = newview / "CMakeLists.txt"
    app = newview / "llappviewer.cpp"
    anchors = {
        cmake: [("    llagentlistener.cpp\n", "    fsmcpbuilder.cpp\n    llagentlistener.cpp\n"),
                ("    llagentlistener.h\n", "    fsmcpbuilder.h\n    llagentlistener.h\n")],
        app: [('#include "llleap.h"\n', '#include "llleap.h"\n#include "fsmcpbuilder.h"\n'),
              ("    {\n        // Iterate over --leap command-line options.",
               "    initFSMCPBuilder();\n\n    {\n        // Iterate over --leap command-line options.")],
    }
    if profile_name is not None:
        if not re.fullmatch(r"FirestormMCP[A-Za-z0-9_-]{0,32}", profile_name):
            raise ValueError("Profile name must start with FirestormMCP and contain only letters, digits, _ or -")
        constants = newview.parent / "llcommon/indra_constants.h"
        anchors[constants] = [('const std::string APP_NAME = "Firestorm";',
                               f'const std::string APP_NAME = "{profile_name}";')]
    for path, replacements in anchors.items():
        text = path.read_text(encoding="utf-8")
        if "fsmcpbuilder" in text.lower():
            raise ValueError(f"Hook already present in {path.name}; review instead of reapplying")
        for anchor, replacement in replacements:
            if text.count(anchor) != 1:
                raise ValueError(f"Expected one integration anchor in {path.name}; source version needs review")
            text = text.replace(anchor, replacement, 1)
        edits[path] = text
    for name in ("fsmcpbuilder.cpp", "fsmcpbuilder.h"):
        destination = newview / name
        if destination.exists():
            raise ValueError(f"Refusing to overwrite {destination}")
        edits[destination] = (source / name).read_text(encoding="utf-8")
    if not dry_run:
        for path, text in edits.items():
            path.write_text(text, encoding="utf-8", newline="\n")
    return {"files": [str(path) for path in edits], "written": not dry_run, "compiled": False}


if __name__ == "__main__":
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--profile-name", help="Separate settings/cache profile, e.g. FirestormMCP")
    args = parser.parse_args()
    print(json.dumps(apply(args.checkout, args.dry_run, args.profile_name), indent=2))
