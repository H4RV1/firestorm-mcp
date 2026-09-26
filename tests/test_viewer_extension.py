import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location("extension_installer",
    Path(__file__).resolve().parents[1] / "scripts/apply_viewer_extension.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


@pytest.fixture
def checkout(tmp_path):
    path = tmp_path / "indra/newview"
    path.mkdir(parents=True)
    (path / "CMakeLists.txt").write_text("    llagentlistener.cpp\n    llagentlistener.h\n")
    (path / "llappviewer.cpp").write_text('#include "llleap.h"\nvoid init()\n    {\n        // Iterate over --leap command-line options.\n')
    return tmp_path, path


def test_extension_dry_run_then_apply_and_no_double_patch(checkout):
    root, path = checkout
    before = (path / "llappviewer.cpp").read_bytes()
    assert not installer.apply(root, dry_run=True)["written"]
    assert (path / "llappviewer.cpp").read_bytes() == before
    assert not (path / "fsmcpbuilder.cpp").exists()
    assert installer.apply(root)["written"]
    assert "initFSMCPBuilder();" in (path / "llappviewer.cpp").read_text()
    assert "fsmcpbuilder.cpp" in (path / "CMakeLists.txt").read_text()
    with pytest.raises(ValueError, match="already present"):
        installer.apply(root)


def test_mismatched_source_fails_before_writing_any_file(checkout):
    root, path = checkout
    before = (path / "CMakeLists.txt").read_bytes()
    (path / "llappviewer.cpp").write_text("different source version")
    with pytest.raises(ValueError, match="integration anchor"):
        installer.apply(root)
    assert (path / "CMakeLists.txt").read_bytes() == before
    assert not (path / "fsmcpbuilder.cpp").exists()


def test_separate_profile_is_validated_before_any_writes(checkout):
    root, path = checkout
    constants = root / "indra/llcommon/indra_constants.h"
    constants.parent.mkdir()
    constants.write_text('const std::string APP_NAME = "Firestorm";\n')
    with pytest.raises(ValueError, match="Profile name"):
        installer.apply(root, profile_name='Firestorm") bad')
    assert not (path / "fsmcpbuilder.cpp").exists()
    installer.apply(root, profile_name="FirestormMCP")
    assert 'APP_NAME = "FirestormMCP"' in constants.read_text()
