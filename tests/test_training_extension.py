"""Offline installer checks. Never use a real viewer tree or runtime."""
import importlib.util
from pathlib import Path
import xml.etree.ElementTree as ET
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("training_installer", ROOT / "scripts/apply_training_extension.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    monkeypatch.setenv("FIRESTORM_MCP_HOME", str(tmp_path / "isolated-state"))
    view = tmp_path / "indra/newview"
    files = {
        "CMakeLists.txt": "    llagentlistener.cpp\n    llagentlistener.h\n",
        "llappviewer.cpp": '#include "llleap.h"\n    {\n        // Iterate over --leap command-line options.\n',
        "pipeline.cpp": '#include "llviewerprecompiledheaders.h"\n    LL::GLTFSceneManager::instance().renderDebug();\n',
        "llgesturemgr.cpp": '#include "llviewerprecompiledheaders.h"\n    // Reset gesture to first step\n',
        "app_settings/settings.xml": '<llsd><map>\n  <key>FSLandmarkCreatedNotification</key><map/></map></llsd>',
        "skins/default/xui/en/menu_viewer.xml": '<menu_bar><menu\n     name="Develop"\n     tear_off="true"\n     visible="false">\n</menu></menu_bar>',
        "../llcommon/indra_constants.h": 'const std::string APP_NAME = "FirestormMCP";\n',
    }
    for name, text in files.items():
        path = view / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text, encoding="utf-8")
    return tmp_path, view


def contents(root):
    return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_dry_run_apply_and_reapplication(checkout):
    root, view = checkout
    before = contents(root)
    assert not installer.apply(root, dry_run=True)["written"]
    assert before == contents(root)
    assert installer.apply(root)["written"]
    assert 'APP_NAME = "FirestormMCPTraining"' in (root / "indra/llcommon/indra_constants.h").read_text()
    for name in ("app_settings/settings.xml", "skins/default/xui/en/menu_viewer.xml", "skins/default/xui/en/floater_fsmcp_training.xml"):
        ET.parse(view / name)
    after = contents(root)
    with pytest.raises(ValueError, match="already present"):
        installer.apply(root)
    assert after == contents(root)


@pytest.mark.parametrize("failure", ["anchor", "destination", "profile"])
def test_failure_does_not_partially_patch(checkout, failure):
    root, view = checkout
    if failure == "anchor": (view / "pipeline.cpp").write_text("unsupported version")
    if failure == "destination": (view / "fsmcptraining.cpp").write_text("unrelated work")
    before = contents(root)
    with pytest.raises(ValueError):
        installer.apply(root, profile_name="normal-profile" if failure == "profile" else "FirestormMCPTraining")
    assert before == contents(root)


def test_controls_have_declared_settings_and_overlay_starts_off():
    xml = ET.parse(ROOT / "viewer-extension/floater_fsmcp_training.xml")
    declared = {"FSMCPTraining" + key for key in installer.SETTINGS}
    for control in xml.iter():
        if control.get("control_name"): assert control.get("control_name") in declared
    enabled = installer.SETTINGS["Enabled"]
    assert enabled[2] == "0" and enabled[4] == 0
    assert installer.SETTINGS["TargetGesture"][2] == ""
    assert installer.SETTINGS["AttackGesture"][2] == ""
    assert installer.SETTINGS["EligibleOnly"][2] == "0"


def test_native_training_model_when_portable_compiler_available(tmp_path):
    compiler = next((shutil.which(name) for name in ("c++", "g++", "clang++") if shutil.which(name)), None)
    if compiler is None:
        pytest.skip("No portable C++ compiler on PATH; run native_training_model.cpp in a developer shell")
    executable = tmp_path / "training-model-test.exe"
    subprocess.run([compiler, "-std=c++17", str(ROOT / "tests/native_training_model.cpp"), "-o", str(executable)], check=True, timeout=60)
    subprocess.run([str(executable)], check=True, timeout=10)
