import pytest

from diagnostic_ar_training.lineage import gitinfo, ledger, manifest
from diagnostic_ar_training.lineage.gitinfo import CodeState


@pytest.fixture(autouse=True)
def _never_write_the_real_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "LEDGER", tmp_path / "TEST_LEDGER.md")
    monkeypatch.delenv(ledger.SEALED_READ_ENV, raising=False)


@pytest.fixture
def clean_tree(monkeypatch):
    state = CodeState(repo="test", sha="a" * 40, dirty=False)
    monkeypatch.setattr(gitinfo, "code_state", lambda *a, **k: state)
    monkeypatch.setattr(ledger, "code_state", lambda *a, **k: state)
    monkeypatch.setattr(manifest, "code_state", lambda *a, **k: state)
    return state


@pytest.fixture
def dirty_tree(monkeypatch):
    state = CodeState(repo="test", sha="b" * 40, dirty=True)
    monkeypatch.setattr(ledger, "code_state", lambda *a, **k: state)
    monkeypatch.setattr(manifest, "code_state", lambda *a, **k: state)
    return state


@pytest.fixture
def docs(tmp_path, monkeypatch):
    exp_dir = tmp_path / "experiments"
    exp_dir.mkdir()
    monkeypatch.setattr(ledger, "LEDGER", tmp_path / "TEST_LEDGER.md")
    monkeypatch.setattr(ledger, "EXPERIMENTS_DIR", exp_dir)
    monkeypatch.setattr(ledger, "is_preregistered", lambda path: path.read_text() != "draft")
    return tmp_path
