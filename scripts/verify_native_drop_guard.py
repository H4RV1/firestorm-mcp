"""Compile/run the actual shared face guard in isolation; no viewer or network.

Use a Visual Studio developer environment on Windows, or a C++17 compiler.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    root = Path(__file__).resolve().parents[1]
    source = root / 'tests/native_drop_guard.cpp'
    compiler = shutil.which('cl') or shutil.which('c++')
    if not compiler:
        raise RuntimeError('A C++ compiler environment is required')
    with tempfile.TemporaryDirectory(prefix='fsmcp-drop-guard-') as temp:
        executable = Path(temp) / 'drop-guard.exe'
        if Path(compiler).stem.lower() == 'cl':
            args = [compiler, '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX',
                    '/Fe:' + str(executable), str(source)]
        else:
            args = [compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-o', str(executable), str(source)]
        subprocess.run(args, cwd=temp, check=True)
        subprocess.run([str(executable)], check=True)


if __name__ == '__main__':
    main()
