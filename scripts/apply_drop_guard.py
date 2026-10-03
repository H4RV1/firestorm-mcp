"""Guard texture/material drop faces in a reviewed Firestorm source checkout.

Never compiles, launches or changes an installed viewer. Refuses an unknown
baseline rather than applying a partial or ambiguous source edit.
"""
import argparse
import hashlib
import json
from pathlib import Path

# Normalized LF source, upstream 10bd3c9f930c76e1427ddd4ecece6cdf36b4406d.
BASELINE_SHA256 = 'c2dc2de85b73ee0abd7ee845ca122776072ce8b0b1c240bc3486ad6f9aa54c57'


def patch_source(text):
    def replace(old, new, count=1):
        nonlocal text
        if text.count(old) != count:
            raise ValueError('Unknown/already modified drop guard anchor; no files written')
        text = text.replace(old, new)

    anchor = '#include "lltooldraganddrop.h"\n'
    replace(anchor, anchor + '#include "fsmcpdropguard.h"\n')
    # Revalidate the two entrypoints also used by delayed no-copy confirmations.
    anchor = '{\n    LLSelectNode* nodep = nullptr;\n'
    replace(anchor, '{\n    if (!fsmcpValidDropSurface(hit_obj, hit_face, all_faces)) return;\n'
            '    LLSelectNode* nodep = nullptr;\n', 2)
    replace('    if (hit_face == -1) return;',
            '    if (!fsmcpValidDropFace(hit_obj, hit_face)) return;', 2)
    anchor = 'bool is_water_exclusion_face(LLViewerObject* obj, S32 face)\n{\n'
    replace(anchor, anchor + '    if (!fsmcpValidDropFace(obj, face)) return false;\n')
    anchor = 'bool is_water_exclusion_surface(LLViewerObject* obj, S32 face, bool all_faces)\n{\n'
    replace(anchor, anchor + '    if (!fsmcpValidDropSurface(obj, face, all_faces)) return false;\n')
    # After Ctrl inventory delivery, before any single-face texture/PBR reads.
    anchor = '    if (cargo_type == DAD_TEXTURE && (mask & MASK_ALT) == 0)\n'
    replace(anchor,
        '    // A missed surface pick is -1, not face 255 or face zero.\n'
        '    if ((cargo_type == DAD_TEXTURE || cargo_type == DAD_MATERIAL) &&\n'
        '        !fsmcpValidDropSurface(obj, face, (mask & MASK_SHIFT) != 0))\n'
        '    {\n        return ACCEPT_NO;\n    }\n\n' + anchor)
    return text


def apply(checkout, dry_run=False):
    root = Path(checkout).resolve(strict=True) / 'indra/newview'
    path = root / 'lltooldraganddrop.cpp'
    text = path.read_text(encoding='utf-8')
    if hashlib.sha256(text.encode()).hexdigest() != BASELINE_SHA256:
        raise ValueError('Unknown/modified drop source; no files written')
    header = root / 'fsmcpdropguard.h'
    if header.exists():
        raise ValueError('Drop guard header already exists; no files written')
    edits = {path: patch_source(text), header:
        (Path(__file__).resolve().parents[1] / 'viewer-extension/fsmcpdropguard.h').read_text(encoding='utf-8')}
    if not dry_run:
        for path, value in edits.items():
            path.write_text(value, encoding='utf-8', newline='\n')
    return {'written': not dry_run, 'files': [p.name for p in edits], 'compiled': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkout', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    print(json.dumps(apply(args.checkout, args.dry_run)))
