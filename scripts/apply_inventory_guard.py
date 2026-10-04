"""Patch the reviewed native inventory/key crash paths in source only."""
import argparse
import hashlib
import json
from pathlib import Path

BASELINES = {
    'llpanelobjectinventory.cpp': '083f0c0a7eecfe3b720ee106bb6033f572f2ffd07a2372ac70b274f6491ca607',
    'llinventoryfunctions.cpp': '0945733276a2ea77bb9509bf8cca2e79bd0480d4c8b86889ba4918ad74e61c11',
    'llwindowlistener.cpp': 'bf369b16afec6a3e8ec1360a662d85f74b0289ef028e9d31700550926cd5dc2c',
}


def patch_source(name, text):
    def replace(old, new, count=1):
        nonlocal text
        if text.count(old) != count:
            raise ValueError(f'Unknown/already modified anchor in {name}; no files written')
        text = text.replace(old, new)

    if name == 'llpanelobjectinventory.cpp':
        anchor = 'void LLPanelObjectInventory::doToSelected(const LLSD& userdata)\n{\n'
        replace(anchor, anchor + '    // Selection refresh can clear the tree while the panel remains alive.\n'
                '    if (!mFolders) return;\n\n')
        anchor = 'bool LLPanelObjectInventory::handleKeyHere( KEY key, MASK mask )\n{\n'
        replace(anchor, anchor + '    if (!mFolders) return false;\n\n')
    elif name == 'llinventoryfunctions.cpp':
        anchor = 'void LLInventoryAction::doToSelected(LLInventoryModel* model, LLFolderView* root, const std::string& action, bool user_confirm)\n{\n'
        replace(anchor, anchor + '    // Callers may outlive a cleared/rebuilt inventory tree.\n'
                '    if (!root) return;\n\n')
    elif name == 'llwindowlistener.cpp':
        anchor = '#include "llviewerinput.h"\n'
        replace(anchor, anchor + '#include "llpanelobjectinventory.h"\n')
        # Apply to targeted keyboard branches only, not mouse handlers.
        old = '            gFocusMgr.setKeyboardFocus(target_view);\n'
        new = '''            auto* inventory = dynamic_cast<LLPanelObjectInventory*>(target_view);
            if (inventory && !inventory->getRootFolder())
            {
                response.error("Object inventory is not ready; no key dispatched");
                return;
            }
            auto target_handle = target_view->getHandle();
            gFocusMgr.setKeyboardFocus(target_view);
            // Focus callbacks/modal focus locks can invalidate or reject a target.
            if (target_handle.get() != target_view ||
                gFocusMgr.getKeyboardFocus() != target_view || !target_view->isAvailable())
            {
                response.error("Key target lost availability or did not receive focus; no key dispatched");
                return;
            }
            inventory = dynamic_cast<LLPanelObjectInventory*>(target_view);
            if (inventory && !inventory->getRootFolder())
            {
                response.error("Object inventory was cleared during focus; no key dispatched");
                return;
            }
'''
        replace(old, new, 2)
    else:
        raise ValueError('Unsupported source file')
    return text


def apply(checkout, dry_run=False):
    root = Path(checkout).resolve(strict=True) / 'indra/newview'
    edits = {}
    for name, expected in BASELINES.items():
        path = root / name
        text = path.read_text(encoding='utf-8')
        if hashlib.sha256(text.encode()).hexdigest() != expected:
            raise ValueError(f'Unknown/modified {name}; no files written')
        edits[path] = patch_source(name, text)
    if not dry_run:
        for path, text in edits.items():
            path.write_text(text, encoding='utf-8', newline='\n')
    return {'written': not dry_run, 'files': [p.name for p in edits], 'compiled': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkout', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    print(json.dumps(apply(args.checkout, args.dry_run)))
