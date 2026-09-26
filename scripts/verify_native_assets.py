"""Compile/run shared native policy and codec tests in a temporary directory.

Windows: run in a VS developer environment. Requires FFmpeg and the separate
viewer's configured packages; never starts the viewer or makes network requests.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    packages = args.checkout / 'build-vc170-64/packages'
    compiler = shutil.which('cl')
    ffmpeg = shutil.which('ffmpeg')
    if not compiler or not ffmpeg:
        raise RuntimeError('Run in a VS developer environment with FFmpeg available')
    with tempfile.TemporaryDirectory(prefix='fsmcp-native-assets-') as temp:
        temp = Path(temp)
        for name in ('policy', 'sound'):
            cmd = [compiler, '/nologo', '/std:c++17', '/EHsc', '/MD', '/O2',
                   '/I' + str(packages / 'include'), '/Fo:' + str(temp / (name + '.obj')),
                   '/Fe:' + str(temp / (name + '.exe')), str(root / 'tests' / ('native_asset_' + name + '.cpp'))]
            if name == 'sound':
                cmd += [str(packages / 'lib/release' / lib) for lib in ('libvorbisfile.lib', 'libvorbis.lib', 'libogg.lib')]
            subprocess.run(cmd, cwd=temp, check=True)
        fixtures = []
        for name, rate, layout in (('mono', 44100, 'mono'), ('stereo', 44100, 'stereo'), ('rate', 48000, 'mono')):
            path = temp / (name + '.ogg'); fixtures.append(str(path))
            subprocess.run([ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                '-i', f'anullsrc=r={rate}:cl={layout}', '-t', '0.25', '-c:a', 'libvorbis', '-q:a', '4', str(path)], check=True)
        subprocess.run([str(temp / 'policy.exe')], check=True)
        subprocess.run([str(temp / 'sound.exe'), *fixtures], check=True)
        print(json.dumps({'native_policy': 'passed', 'native_codec': 'passed', 'simulator_contacted': False}))


if __name__ == '__main__':
    main()
