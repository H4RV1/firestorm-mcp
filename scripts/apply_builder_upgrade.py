"""Upgrade the recorded builder-v1 hook in a development source checkout only.

Use apply_viewer_extension.py for a fresh checkout. This installer validates
every source anchor/hash before writing, refuses unknown edits, and never
compiles, launches or replaces an installed viewer.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_background_ui import display_hook

BUILDER_V1_HASH = '7753f7ac907c25ec11ff5a76e5974923ccf6894a6c6c21bad78df83907ada96b'


def apply(checkout, dry_run=False):
    source = Path(__file__).resolve().parents[1] / 'viewer-extension'
    newview = Path(checkout).resolve(strict=True) / 'indra/newview'
    builder = newview / 'fsmcpbuilder.cpp'
    current = builder.read_text(encoding='utf-8')
    if hashlib.sha256(current.encode()).hexdigest() != BUILDER_V1_HASH:
        raise ValueError('Unknown/modified builder source; review it instead of overwriting')
    cmake = newview / 'CMakeLists.txt'
    text = cmake.read_text(encoding='utf-8')
    for ext in ('cpp', 'h'):
        anchor = f'    fsmcpbuilder.{ext}\n'
        if text.count(anchor) != 1 or f'fsmcpui.{ext}' in text or (newview / f'fsmcpui.{ext}').exists():
            raise ValueError('Unknown/already installed UI integration; no files written')
        text = text.replace(anchor, anchor + f'    fsmcpui.{ext}\n', 1)
    display = newview / 'llviewerdisplay.cpp'
    edits = {cmake: text, display: display_hook(display.read_text(encoding='utf-8'))}
    for name in ('fsmcpbuilder.cpp', 'fsmcpui.cpp', 'fsmcpui.h'):
        edits[newview / name] = (source / name).read_text(encoding='utf-8')
    if not dry_run:
        for path, value in edits.items():
            path.write_text(value, encoding='utf-8', newline='\n')
    return {'files': [p.name for p in edits], 'written': not dry_run, 'compiled': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkout', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    print(json.dumps(apply(args.checkout, args.dry_run)))
