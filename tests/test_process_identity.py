import pytest

from firestorm_mcp import process_identity as identity


class Process:
    pid = 123

    def __init__(self, filename, parent=None):
        self.filename, self._parent = filename, parent

    def exe(self):
        return self.filename

    def parent(self):
        return self._parent


def resolve(monkeypatch, parent, platform="win32"):
    monkeypatch.setattr(identity.sys, "platform", platform)
    monkeypatch.setattr(identity.psutil, "Process", lambda pid: Process("python.exe", parent))
    return identity.parent_viewer(99)


def test_direct_and_windows_venv_viewer_parent(monkeypatch):
    viewer = Process("FirestormOS-MCP-Development.exe")
    assert resolve(monkeypatch, viewer) is viewer
    assert resolve(monkeypatch, Process("python.exe", viewer)) is viewer
    assert resolve(monkeypatch, Process("pythonw.exe", viewer)) is viewer


@pytest.mark.parametrize("names", [[], ["cmd.exe"], ["cmd.exe", "Firestorm.exe"],
    ["python.exe", "python.exe", "Firestorm.exe"], ["python.exe", "unrelated.exe"]])
def test_no_arbitrary_ancestor_search(monkeypatch, names):
    parent = None
    for name in reversed(names):
        parent = Process(name, parent)
    with pytest.raises(ValueError, match="launched by Firestorm"):
        resolve(monkeypatch, parent)


def test_posix_does_not_skip_python_ancestors(monkeypatch):
    with pytest.raises(ValueError):
        resolve(monkeypatch, Process("python.exe", Process("Firestorm.exe")), "linux")
