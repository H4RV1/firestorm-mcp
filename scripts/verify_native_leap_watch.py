"""Compile the actual watchdog class against synthetic child-process lifetimes."""
from pathlib import Path
import shutil
import subprocess
import tempfile

from verify_native_inventory_guard import method


def main():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'viewer-extension/fsmcpui.cpp').read_text(encoding='utf-8')
    body = method(source, 'class MCPLeapWatch final') + ';'
    fixture = (root / 'tests/native_leap_watch.cpp').read_text(encoding='utf-8')
    compiler = shutil.which('cl') or shutil.which('c++')
    if not compiler:
        raise RuntimeError('C++17 compiler environment required')
    with tempfile.TemporaryDirectory(prefix='fsmcp-watch-') as temp:
        temp = Path(temp)
        cpp, exe = temp / 'watch.cpp', temp / 'watch.exe'
        cpp.write_text(fixture.replace('// GENERATED_WATCH', body), encoding='utf-8')
        if Path(compiler).stem.lower() == 'cl':
            cmd = [compiler, '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX', '/Fe:' + str(exe), str(cpp)]
        else:
            cmd = [compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-o', str(exe), str(cpp)]
        subprocess.run(cmd, cwd=temp, check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
