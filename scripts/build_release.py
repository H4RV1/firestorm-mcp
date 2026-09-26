"""Create an allowlisted source ZIP and hashes, excluding runtime/user evidence."""
import argparse
import hashlib
from pathlib import Path
import re
import tomllib
import zipfile

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir', type=Path, default=root / 'dist')
args = parser.parse_args()
version = tomllib.loads((root / 'pyproject.toml').read_text())['project']['version']
root_names = {'README.md', 'LICENSE', 'CONTRIBUTING.md', 'AGENTS.md', 'SECURITY.md',
              'CHANGELOG.md', 'THIRD_PARTY.md', 'pyproject.toml', 'requirements-lock.txt',
              'Install.cmd', 'Install.ps1', 'Start-FirestormMCP.cmd', 'Start-FirestormMCP.ps1',
              'Check-FirestormMCP.cmd', '.gitignore', '.gitattributes', 'MANIFEST.in',
              'install.py', 'Install.sh', 'Start-FirestormMCP.sh', 'Check-FirestormMCP.sh'}
trees = {'src', 'tests', 'docs', 'scripts', 'skills', '.github', 'viewer-extension'}
suffixes = {'.py', '.dae', '.md', '.json', '.yml', '.yaml', '.txt', '.cpp', '.h'}
files = []
for path in sorted(root.rglob('*')):
    if not path.is_file():
        continue
    relative = path.relative_to(root)
    if '__pycache__' in relative.parts or any(part.endswith('.egg-info') for part in relative.parts):
        continue
    if str(relative) not in root_names and not (relative.parts[0] in trees and path.suffix in suffixes):
        continue
    if path.is_symlink():
        raise ValueError(f'Symlink cannot enter a release: {relative}')
    text = path.read_text(encoding='utf-8')
    # These detect accidental local profiles or common credential literals, not every possible secret.
    if re.search(r'(?i)[A-Z]:[/\\]+Users[/\\]+[^/\\\s]+', text):
        raise ValueError(f'Personal profile path in {relative}')
    if re.search(r'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', text):
        raise ValueError(f'Credential-like content in {relative}')
    files.append((path, relative))
destination = args.output_dir.resolve()
destination.mkdir(parents=True, exist_ok=True)
archive = destination / f'firestorm-mcp-{version}-source.zip'
with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
    for path, relative in files:
        info = zipfile.ZipInfo(f'firestorm-mcp-{version}/{relative.as_posix()}', (2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        bundle.writestr(info, path.read_bytes())
with zipfile.ZipFile(archive) as bundle:
    assert bundle.testzip() is None
hashes = []
for path in sorted(destination.iterdir()):
    if path.is_file() and path.name != 'SHA256SUMS.txt':
        hashes.append(f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}')
(destination / 'SHA256SUMS.txt').write_text('\n'.join(hashes) + '\n', encoding='utf-8')
print(f'Created {archive.name}: {len(files)} allowlisted files. Review contents before publication.')
