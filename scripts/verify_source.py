"""Exercise the source ZIP installer in isolation as a new user would."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('archive', type=Path)
args = parser.parse_args()
with tempfile.TemporaryDirectory(prefix='firestorm-setup-') as folder:
    root = Path(folder).resolve()  # macOS /var and /private/var refer to the same directory.
    with zipfile.ZipFile(args.archive) as archive:
        # This checks an internally built, allowlisted release, not user input.
        archive.extractall(root)
    projects = list(root.glob('firestorm-mcp-*'))
    assert len(projects) == 1
    project = projects[0]
    env = os.environ.copy()
    env.pop('PYTHONPATH', None)
    env['FIRESTORM_MCP_HOME'] = str(root / 'isolated state')
    subprocess.run([sys.executable, str(project / 'install.py')], cwd=root, env=env, check=True, timeout=300)
    python = project / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    result = subprocess.run([str(python), '-m', 'firestorm_mcp.configure'], cwd=root, env=env,
                            check=True, capture_output=True, text=True, timeout=30)
    entry = json.loads(result.stdout)['mcpServers']['firestorm']
    assert Path(entry['command']).absolute() == python.absolute()
    result = subprocess.run([entry['command'], '-m', 'firestorm_mcp.probe', *entry['args'][2:]],
                            cwd=root, env=env, capture_output=True, text=True, timeout=90)
    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report['mcp_initialized'] and report['tool_count'] == 72
    assert report['connection']['connected'] is False and report['viewer_input_sent'] is False
    assert not (root / 'isolated state/runtime/session-settings.xml').exists()
    print(json.dumps({'source_install': 'passed', 'generated_config': 'passed',
                      'offline_mcp': 'passed', 'viewer_started': False}))
