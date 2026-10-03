"""Upgrade the recorded builder.2 UI hook; never touches installed binaries."""
import argparse
import hashlib
import json
from pathlib import Path

UI_V2 = '162c6821ebc2f39487146174b10f8dbbbef9ca27d4e6eb146696c70bb1c4329e'


def display_hook(text):
    anchor = '#include "llviewerwindow.h"\n'
    swap = '        gViewerWindow->getWindow()->swapBuffers();\n'
    # Only swap() after normal render; startup capture remains explicitly pending
    # until a normal world/UI frame is available.
    block = '    if (gDisplaySwapBuffers)\n    {\n' + swap
    if 'fsmcpUICaptureFrame' in text or text.count(anchor) != 1 or text.count(block) != 1:
        raise ValueError('Unknown/already modified display hook; no files written')
    return text.replace(anchor, anchor + '#include "fsmcpui.h"\n', 1).replace(block,
        '    if (gDisplaySwapBuffers)\n    {\n        fsmcpUICaptureFrame();\n' + swap, 1)


def apply(checkout, dry_run=False):
    root = Path(checkout).resolve(strict=True) / 'indra/newview'
    source = Path(__file__).resolve().parents[1] / 'viewer-extension'
    current = (root / 'fsmcpui.cpp').read_text(encoding='utf-8')
    if hashlib.sha256(current.encode()).hexdigest() != UI_V2:
        raise ValueError('Unknown/modified builder.2 UI source; no files written')
    if (root / 'fsmcpui.h').read_text(encoding='utf-8') != '// SPDX-License-Identifier: MIT\n#pragma once\nvoid initFSMCPUI();\n':
        raise ValueError('Unknown UI header; no files written')
    display = root / 'llviewerdisplay.cpp'
    edits = {display: display_hook(display.read_text(encoding='utf-8'))}
    for name in ('fsmcpui.cpp', 'fsmcpui.h'):
        edits[root / name] = (source / name).read_text(encoding='utf-8')
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
