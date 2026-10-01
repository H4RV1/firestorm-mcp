"""Add an opt-in local range/timing overlay to a separate Firestorm source tree.

No network, viewer launch, installed-binary patching, or combat actions.
Validate every source anchor and destination before writing anything.
"""
import argparse
import json
from pathlib import Path
import re
from xml.sax.saxutils import escape


SETTINGS = {
    "Enabled": ("Boolean", "integer", "0", "Show the local training prediction overlay; never sends attacks.", 0),
    "Range": ("F32", "real", "2", "Example training range in meters; configure to match the external system.", 1),
    "HalfAngle": ("F32", "real", "90", "Half-angle from forward in degrees. This is a configurable model, not a detected weapon rule.", 1),
    "Cooldown": ("F32", "real", "2", "Local rehearsal cooldown in seconds; not simulator-confirmed.", 1),
    "EligibleOnly": ("Boolean", "integer", "0", "Start cooldown only for locally predicted eligible attempts. False includes misses.", 1),
    "TargetGesture": ("String", "string", "", "Optional active gesture inventory ID observed for local nearest-target acquisition.", 1),
    "AttackGesture": ("String", "string", "", "Optional active gesture inventory ID observed for local attack rehearsal.", 1),
    "TargetShortcut": ("String", "string", "", "Fallback unmodified gesture key, e.g. T; blank disables shortcut matching. An explicit gesture ID takes priority.", 1),
    "AttackShortcut": ("String", "string", "", "Fallback unmodified gesture key, e.g. F12; blank disables shortcut matching. An explicit gesture ID takes priority.", 1),
}


def settings_xml():
    return "".join(
        f"  <key>FSMCPTraining{name}</key>\n  <map>\n"
        f"    <key>Comment</key><string>{escape(comment)}</string>\n"
        f"    <key>Persist</key><integer>{persist}</integer>\n"
        f"    <key>Type</key><string>{kind}</string>\n"
        f"    <key>Value</key><{tag}>{value}</{tag}>\n  </map>\n"
        for name, (kind, tag, value, comment, persist) in SETTINGS.items())


MENU = '''        <menu label="Training" name="FSMCP Training" tear_off="true">
          <menu_item_check label="Show range overlay" name="FSMCP Training Overlay">
            <menu_item_check.on_check function="CheckControl" parameter="FSMCPTrainingEnabled"/>
            <menu_item_check.on_click function="ToggleControl" parameter="FSMCPTrainingEnabled"/>
          </menu_item_check>
          <menu_item_call label="Range and timing controls..." name="FSMCP Training Controls">
            <menu_item_call.on_click function="Floater.Toggle" parameter="fsmcp_training"/>
          </menu_item_call>
        </menu>
'''


def apply(checkout, dry_run=False, profile_name="FirestormMCPTraining"):
    if not re.fullmatch(r"FirestormMCP[A-Za-z0-9_-]{1,32}", profile_name):
        raise ValueError("Use a separate FirestormMCP-prefixed profile name")
    source = Path(__file__).resolve().parents[1] / "viewer-extension"
    root = Path(checkout).resolve(strict=True)
    view = root / "indra/newview"
    menu_anchor = '     name="Develop"\n     tear_off="true"\n     visible="false">\n'
    replacements = {
        view / "CMakeLists.txt": [
            ("    llagentlistener.cpp\n", "    fsmcptraining.cpp\n    llagentlistener.cpp\n"),
            ("    llagentlistener.h\n", "    fsmcptraining.h\n    fsmcptrainingmodel.h\n    llagentlistener.h\n")],
        view / "llappviewer.cpp": [
            ('#include "llleap.h"\n', '#include "llleap.h"\n#include "fsmcptraining.h"\n'),
            ('    {\n        // Iterate over --leap command-line options.',
             '    initFSMCPTraining();\n\n    {\n        // Iterate over --leap command-line options.')],
        view / "pipeline.cpp": [
            ('#include "llviewerprecompiledheaders.h"\n', '#include "llviewerprecompiledheaders.h"\n#include "fsmcptraining.h"\n'),
            ('    LL::GLTFSceneManager::instance().renderDebug();\n',
             '    if (!hud_only && !sReflectionRender && !sShadowRender) renderFSMCPTraining();\n\n    LL::GLTFSceneManager::instance().renderDebug();\n')],
        view / "llgesturemgr.cpp": [
            ('#include "llviewerprecompiledheaders.h"\n', '#include "llviewerprecompiledheaders.h"\n#include "fsmcptraining.h"\n'),
            ('    // Reset gesture to first step\n',
             '    observeFSMCPTrainingGesture(gesture);\n\n    // Reset gesture to first step\n')],
        view / "skins/default/xui/en/menu_viewer.xml": [(menu_anchor, menu_anchor + MENU)],
        view / "app_settings/settings.xml": [("<map>\n  <key>FSLandmarkCreatedNotification", "<map>\n" + settings_xml() + "  <key>FSLandmarkCreatedNotification")],
    }
    pending = {}
    for path, edits in replacements.items():
        text = path.read_text(encoding="utf-8")
        if "fsmcptraining" in text.lower() or "FSMCP Training" in text:
            raise ValueError(f"Training extension already present: {path.name}")
        for before, after in edits:
            if text.count(before) != 1:
                raise ValueError(f"Expected one integration anchor in {path.name}; review source version")
            text = text.replace(before, after, 1)
        pending[path] = text
    constants = root / "indra/llcommon/indra_constants.h"
    text = constants.read_text(encoding="utf-8")
    pattern = r'const std::string APP_NAME = "Firestorm(?:MCP[A-Za-z0-9_-]*)?";'
    if len(re.findall(pattern, text)) != 1:
        raise ValueError("Expected one profile integration anchor")
    pending[constants] = re.sub(pattern, f'const std::string APP_NAME = "{profile_name}";', text)
    for name in ("fsmcptraining.cpp", "fsmcptraining.h", "fsmcptrainingmodel.h", "floater_fsmcp_training.xml"):
        destination = view / ("skins/default/xui/en" if name.endswith(".xml") else "") / name
        if destination.exists():
            raise ValueError(f"Refusing to overwrite {destination.name}")
        pending[destination] = (source / name).read_text(encoding="utf-8")
    if not dry_run:
        for path, text in pending.items():
            path.write_text(text, encoding="utf-8", newline="\n")
    return {"written": not dry_run, "files": [str(p) for p in pending], "compiled": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--profile-name", default="FirestormMCPTraining")
    args = parser.parse_args()
    print(json.dumps(apply(args.checkout, args.dry_run, args.profile_name), indent=2))
