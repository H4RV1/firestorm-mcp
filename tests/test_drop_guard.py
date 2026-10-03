import hashlib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('drop_guard', ROOT / 'scripts/apply_drop_guard.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    root = tmp_path / 'indra/newview'
    root.mkdir(parents=True)
    # Synthetic source anchors only: no copied upstream implementation.
    text = '''#include "lltooldraganddrop.h"
void dropMaterial()
{
    LLSelectNode* nodep = nullptr;
}
void dropTexture()
{
    LLSelectNode* nodep = nullptr;
}
void materialOne() {
    if (hit_face == -1) return;
}
void textureOne() {
    if (hit_face == -1) return;
}
bool is_water_exclusion_face(LLViewerObject* obj, S32 face)
{
}
bool is_water_exclusion_surface(LLViewerObject* obj, S32 face, bool all_faces)
{
}
void apply() {
    if (mask & MASK_CONTROL) { dropInventory(); return; }
    if (cargo_type == DAD_TEXTURE && (mask & MASK_ALT) == 0)
    { readTextureFace(); }
}
'''
    (root / 'lltooldraganddrop.cpp').write_text(text, encoding='utf-8')
    monkeypatch.setattr(installer, 'BASELINE_SHA256', hashlib.sha256(text.encode()).hexdigest())
    return tmp_path, root


def test_drop_guard_install_and_order(checkout):
    checkout, root = checkout
    assert installer.apply(checkout)['written']
    source = (root / 'lltooldraganddrop.cpp').read_text()
    assert source.count('fsmcpValidDropSurface(hit_obj, hit_face, all_faces)') == 2
    assert source.count('fsmcpValidDropFace(hit_obj, hit_face)') == 2
    assert source.index('dropInventory()') < source.index('!fsmcpValidDropSurface(obj, face, (mask') < source.index('readTextureFace()')
    assert '(cargo_type == DAD_TEXTURE || cargo_type == DAD_MATERIAL)' in source
    assert (root / 'fsmcpdropguard.h').read_bytes() == (ROOT / 'viewer-extension/fsmcpdropguard.h').read_bytes()
    with pytest.raises(ValueError, match='Unknown/modified'):
        installer.apply(checkout)


def test_drop_guard_dry_run(checkout):
    checkout, root = checkout
    before = (root / 'lltooldraganddrop.cpp').read_bytes()
    assert not installer.apply(checkout, dry_run=True)['written']
    assert before == (root / 'lltooldraganddrop.cpp').read_bytes()
    assert not (root / 'fsmcpdropguard.h').exists()


def test_drop_guard_unknown_source_is_untouched(checkout):
    checkout, root = checkout
    source = root / 'lltooldraganddrop.cpp'
    source.write_text('unreviewed upstream update')
    with pytest.raises(ValueError, match='Unknown/modified'):
        installer.apply(checkout)
    assert source.read_text() == 'unreviewed upstream update'
    assert not (root / 'fsmcpdropguard.h').exists()


def test_drop_guard_unknown_anchor_fails():
    with pytest.raises(ValueError, match='anchor'):
        installer.patch_source('#include "lltooldraganddrop.h"\n')
