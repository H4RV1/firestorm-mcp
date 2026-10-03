import hashlib
import importlib.util
from pathlib import Path

import pytest


def test_upgrade_checks_every_destination_before_writing(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('upgrade', Path(__file__).parents[1] / 'scripts/apply_builder_upgrade.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    root = tmp_path / 'indra/newview'; root.mkdir(parents=True)
    (root / 'fsmcpbuilder.cpp').write_text('synthetic old source\n')
    monkeypatch.setattr(module, 'BUILDER_V1_HASH', hashlib.sha256(b'synthetic old source\n').hexdigest())
    (root / 'CMakeLists.txt').write_text('    fsmcpbuilder.cpp\n    fsmcpbuilder.h\n')
    (root / 'fsmcpui.h').write_text('existing human work')
    with pytest.raises(ValueError, match='no files written'):
        module.apply(tmp_path)
    assert (root / 'fsmcpbuilder.cpp').read_text() == 'synthetic old source\n'
    (root / 'fsmcpui.h').unlink()
    assert module.apply(tmp_path, dry_run=True)['written'] is False
    assert not (root / 'fsmcpui.cpp').exists()
    assert module.apply(tmp_path)['written'] is True
    assert 'fsmcpui.cpp' in (root / 'CMakeLists.txt').read_text()
    with pytest.raises(ValueError, match='modified builder'):
        module.apply(tmp_path)
