from pathlib import Path

import pytest

from rbk.runbook import RunbookError
from rbk.workspace import find_workspace


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "runbooks").mkdir(parents=True)
    return root


def test_explicit_dir(workspace):
    assert find_workspace(workspace) == (workspace / "runbooks").resolve()


def test_explicit_dir_may_be_the_runbooks_dir(workspace):
    assert find_workspace(workspace / "runbooks") == (workspace / "runbooks").resolve()


def test_env_dir(workspace, monkeypatch):
    monkeypatch.setenv("RBK_DIR", str(workspace))
    assert find_workspace() == (workspace / "runbooks").resolve()


def test_explicit_dir_beats_env(tmp_path, workspace, monkeypatch):
    other = tmp_path / "other"
    (other / "runbooks").mkdir(parents=True)
    monkeypatch.setenv("RBK_DIR", str(workspace))
    assert find_workspace(other) == (other / "runbooks").resolve()


def test_discovers_by_walking_up(workspace, monkeypatch):
    deep = workspace / "runbooks" / "nested" / "deeper"
    deep.mkdir(parents=True)
    monkeypatch.chdir(deep)
    assert find_workspace() == (workspace / "runbooks").resolve()


def test_discovers_from_start_argument(workspace):
    deep = workspace / "runbooks" / "nested"
    deep.mkdir(parents=True)
    assert find_workspace(start=deep) == (workspace / "runbooks").resolve()


def test_no_workspace_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("RBK_DIR", raising=False)
    with pytest.raises(RunbookError, match="--dir"):
        find_workspace(start=tmp_path)


def test_explicit_dir_without_runbooks_raises(tmp_path):
    with pytest.raises(RunbookError, match=r"no runbooks/"):
        find_workspace(tmp_path)


def test_env_dir_without_runbooks_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("RBK_DIR", str(tmp_path))
    with pytest.raises(RunbookError, match="RBK_DIR"):
        find_workspace()
