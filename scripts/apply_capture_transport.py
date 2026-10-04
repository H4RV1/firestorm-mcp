"""Upgrade the recorded builder.3 capture transport and MCP helper supervision."""
import argparse
import hashlib
import json
from pathlib import Path
BASELINES = {'fsmcpui.cpp': '0da55f91978500dc24b40b3e4da8ffe2d72b01fbf54d888725bec3d00af8c8a6', 'fsmcpui.h': '5206a2066d9a788f02e62b55e885f74930ee51ec7da1b6c3caa4177d61b45d1c', 'llappviewer.cpp': '2d906024bef6696e5ff7d62b934e6a8eb6bc03280cb09070c04ee5e412634e77'}


def apply(checkout, dry_run=False):
    root = Path(checkout).resolve(strict=True) / 'indra/newview'
    source = Path(__file__).resolve().parents[1] / 'viewer-extension'
    edits = {}
    for name, expected in BASELINES.items():
        path = root / name
        current = path.read_text(encoding='utf-8')
        managed_current = name != 'llappviewer.cpp' and current == (source / name).read_text(encoding='utf-8')
        if hashlib.sha256(current.encode()).hexdigest() != expected and not managed_current:
            raise ValueError(f'Unknown/modified {name}; no files written')
        if name == 'llappviewer.cpp':
            anchor = '#include "llleap.h"\n'
            call = '            LLLeap::create("", leap, false); // exception=false'
            if current.count(anchor) != 1 or current.count(call) != 1:
                raise ValueError('Unexpected LEAP startup anchors; no files written')
            edits[path] = current.replace(anchor, anchor + '#include "fsmcpui.h"\n').replace(call, '            fsmcpStartLeap(leap.asString());')
        else:
            edits[path] = (source / name).read_text(encoding='utf-8')
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
