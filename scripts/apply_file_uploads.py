"""Upgrade only recorded Builder.4 asset sources, never an installed viewer."""
import argparse
import hashlib
import json
from pathlib import Path

BASELINES = {
    'fsmcpassets.cpp': 'd66c9bbf6dc636c432541e2b7733fd98933eabfd4f86e8c0a79402923b32ddf6',
    'fsmcpassetpolicy.h': '7a9111fe40333a0af652c7c022171e845955729cb21f149c62c5e19c0a2353e0',
}


def apply(checkout, dry_run=False):
    directory = Path(checkout).resolve(strict=True) / 'indra/newview'
    source = Path(__file__).resolve().parents[1] / 'viewer-extension'
    pending = {}
    for name, digest in BASELINES.items():
        target = directory / name
        text = target.read_text(encoding='utf-8')
        replacement = (source / name).read_text(encoding='utf-8')
        if text != replacement and hashlib.sha256(text.encode()).hexdigest() != digest:
            raise ValueError('Unknown/modified ' + name + '; no files written')
        if text != replacement:
            pending[target] = replacement
    if not dry_run:
        for path, text in pending.items():
            path.write_text(text, encoding='utf-8', newline='\n')
    return dict(written=not dry_run, files=[p.name for p in pending], compiled=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkout', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    print(json.dumps(apply(args.checkout, args.dry_run)))
