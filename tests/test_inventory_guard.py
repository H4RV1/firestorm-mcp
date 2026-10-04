import hashlib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('inventory_guard', ROOT / 'scripts/apply_inventory_guard.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    root = tmp_path / 'indra/newview'
    root.mkdir(parents=True)
    sources = {
        'llpanelobjectinventory.cpp':
            'void LLPanelObjectInventory::doToSelected(const LLSD& userdata)\n{\n    open();\n}\n'
            'bool LLPanelObjectInventory::handleKeyHere( KEY key, MASK mask )\n{\n    open();\n}\n',
        'llinventoryfunctions.cpp':
            'void LLInventoryAction::doToSelected(LLInventoryModel* model, LLFolderView* root, const std::string& action, bool user_confirm)\n{\n    readSelection();\n}\n',
        'llwindowlistener.cpp': '#include "llviewerinput.h"\n' +
            ('            gFocusMgr.setKeyboardFocus(target_view);\n    dispatchKey();\n' * 2),
    }
    for name, source in sources.items():
        (root / name).write_text(source, encoding='utf-8')
    monkeypatch.setattr(installer, 'BASELINES', {
        name: hashlib.sha256(source.encode()).hexdigest() for name, source in sources.items()})
    return tmp_path, root, sources


def test_inventory_guard_applies_once(checkout):
    checkout, root, _ = checkout
    assert installer.apply(checkout)['written']
    panel = (root / 'llpanelobjectinventory.cpp').read_text()
    assert panel.index('if (!mFolders) return;') < panel.index('open();')
    assert 'if (!mFolders) return false;' in panel
    generic = (root / 'llinventoryfunctions.cpp').read_text()
    assert generic.index('if (!root) return;') < generic.index('readSelection();')
    keys = (root / 'llwindowlistener.cpp').read_text()
    assert keys.count('inventory->getRootFolder()') == 4
    assert keys.count('gFocusMgr.getKeyboardFocus() != target_view') == 2
    with pytest.raises(ValueError, match='Unknown/modified'):
        installer.apply(checkout)


def test_inventory_guard_dry_run(checkout):
    checkout, root, sources = checkout
    assert not installer.apply(checkout, dry_run=True)['written']
    assert sources == {name: (root / name).read_text() for name in sources}


def test_last_file_mismatch_leaves_every_source_untouched(checkout):
    checkout, root, sources = checkout
    (root / 'llwindowlistener.cpp').write_text('unknown upstream revision')
    before = {name: (root / name).read_bytes() for name in sources}
    with pytest.raises(ValueError, match='Unknown/modified'):
        installer.apply(checkout)
    assert before == {name: (root / name).read_bytes() for name in sources}


def test_inventory_guard_unknown_anchor():
    with pytest.raises(ValueError, match='anchor'):
        installer.patch_source('llwindowlistener.cpp', '#include "llviewerinput.h"\n')
