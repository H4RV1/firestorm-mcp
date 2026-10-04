"""Compile actual patched viewer methods with synthetic dependencies only.

Requires C++17 (a VS developer environment on Windows). Reads source but never
starts a viewer, accesses runtime state or contacts the simulator.
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile


def method(source, signature):
    start = source.index(signature)
    body = source.index('{', start)
    depth = 0
    for end in range(body, len(source)):
        if source[end] == '{':
            depth += 1
        elif source[end] == '}':
            depth -= 1
            if not depth:
                return source[start:end + 1]
    raise ValueError('Incomplete method')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = args.checkout / 'indra/newview'
    panel = (source / 'llpanelobjectinventory.cpp').read_text(encoding='utf-8')
    window = (source / 'llwindowlistener.cpp').read_text(encoding='utf-8')
    bodies = [method(panel, signature) for signature in (
        'void LLPanelObjectInventory::doToSelected(',
        'bool LLPanelObjectInventory::handleKeyHere(')]
    bodies += [method(window, 'void LLWindowListener::' + name + '(') for name in ('keyDown', 'keyUp')]
    fixture = (root / 'tests/native_inventory_guard.cpp').read_text(encoding='utf-8')
    compiler = shutil.which('cl') or shutil.which('c++')
    if not compiler:
        raise RuntimeError('C++17 compiler environment required')
    with tempfile.TemporaryDirectory(prefix='fsmcp-inventory-guard-') as temp:
        temp = Path(temp)
        cpp = temp / 'inventory.cpp'
        cpp.write_text(fixture.replace('// GENERATED_METHODS', '\n\n'.join(bodies)), encoding='utf-8')
        exe = temp / 'inventory.exe'
        if Path(compiler).stem.lower() == 'cl':
            command = [compiler, '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX', '/Fe:' + str(exe), str(cpp)]
        else:
            command = [compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-o', str(exe), str(cpp)]
        subprocess.run(command, cwd=temp, check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
