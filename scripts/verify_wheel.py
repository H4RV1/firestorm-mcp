"""Build-independent wheel smoke check in a fresh venv and isolated state."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import venv

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('wheel', type=Path)
parser.add_argument('--wheelhouse', type=Path, help='Install with --no-index from this prepared local wheel directory')
args = parser.parse_args()
with tempfile.TemporaryDirectory(prefix='firestorm-mcp-wheel-') as temporary:
    temp = Path(temporary)
    environment = temp / 'environment'
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    source = ['--no-index', '--find-links', str(args.wheelhouse.resolve())] if args.wheelhouse else []
    subprocess.run([str(python), '-m', 'pip', '--disable-pip-version-check', 'install', *source, '--upgrade', 'pip>=26.2,<27'], check=True)
    subprocess.run([str(python), '-m', 'pip', '--disable-pip-version-check', 'install', *source, str(args.wheel.resolve())], check=True)
    env = os.environ.copy()
    env.pop('PYTHONPATH', None)
    env['FIRESTORM_MCP_HOME'] = str(temp / 'offline-state')
    result = subprocess.run([str(python), '-m', 'firestorm_mcp.probe'], cwd=temp, env=env,
                            capture_output=True, text=True, timeout=90)
    report = json.loads(result.stdout)
    assert result.returncode == 2, (result.returncode, result.stderr)
    assert report['mcp_initialized'] and report['tool_count'] == 72
    assert report['connection']['connected'] is False
    assert report['lease_acquired'] is False and report['viewer_input_sent'] is False
    check = subprocess.run([str(python), '-c',
        'from pathlib import Path; import firestorm_mcp; '
        'assert all(Path(firestorm_mcp.__file__).with_name(name).is_file() '
        'for name in ("leap_entry.py", "script_entry.py", "script_workspace.py", "builder_tools.py", '
        '"asset_tools.py", "asset_gateway.py", "asset_journal.py", "asset_contract.py"))'],
        cwd=temp, env=env, capture_output=True, text=True)
    assert check.returncode == 0, check.stderr
    print(json.dumps({'wheel_install': 'passed', 'offline_mcp': 'passed', 'workflow_tools': 72,
                      'viewer_started': False, 'packaged_leap_entry': 'present', 'offline_install': bool(args.wheelhouse)}))
