import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('assets_installer', ROOT / 'scripts/apply_assets_extension.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


@pytest.fixture
def checkout(tmp_path):
    path = tmp_path / 'indra/newview'; path.mkdir(parents=True)
    (path / 'CMakeLists.txt').write_text('    fsmcpbuilder.cpp\n    fsmcpbuilder.h\n')
    (path / 'llappviewer.cpp').write_text('#include "fsmcpbuilder.h"\ninitFSMCPBuilder();')
    (path / 'llstartup.cpp').write_text('#include "llviewerprecompiledheaders.h"\nLLSD response = LLLoginInstance::getInstance()->getResponse();\n\n    // <FS:Ansariel> OpenSim legacy economy support')
    (path / 'llviewermessage.cpp').write_text('''#include "llviewerprecompiledheaders.h"
void process_object_properties_family(LLMessageSystem *msg, void**user_data)
{
}
void process_chat_from_simulator(LLMessageSystem *msg, void **user_data)
{
}
void process_script_dialog(LLMessageSystem* msg, void**)
{
}
        msg->newMessage("ScriptDialogReply");
''')
    return tmp_path, path


def test_install_native_assets_once(checkout):
    root, path = checkout
    installer.apply(root, ROOT / 'viewer-extension')
    assert 'fsmcpAssetsLoginBenefits' in (path / 'llstartup.cpp').read_text()
    assert 'fsmcpAssetsDialogAnswered' in (path / 'llviewermessage.cpp').read_text()
    for name in ('fsmcpassets.cpp', 'fsmcpassets.h', 'fsmcpassetpolicy.h', 'fsmcpsound.h'):
        assert (path / name).read_bytes() == (ROOT / 'viewer-extension' / name).read_bytes()
    with pytest.raises(ValueError, match='Already patched'):
        installer.apply(root, ROOT / 'viewer-extension')


def test_changed_anchor_fails_before_any_write(checkout):
    root, path = checkout
    (path / 'llstartup.cpp').write_text('Different baseline')
    before = {p.name: p.read_bytes() for p in path.iterdir()}
    with pytest.raises(ValueError, match='anchor'):
        installer.apply(root, ROOT / 'viewer-extension')
    assert before == {p.name: p.read_bytes() for p in path.iterdir()}
