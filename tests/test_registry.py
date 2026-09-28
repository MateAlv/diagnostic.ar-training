import pytest

from diagnostic_ar_training.lineage import registry
from diagnostic_ar_training.lineage.hashing import sha256_file
from diagnostic_ar_training.lineage.registry import LineageError, Purpose, Role, Source


def make_source(tmp_path, role=Role.KNOWLEDGE, content=b"hello", sha=None):
    original = tmp_path / "origin.txt"
    original.write_bytes(content)
    return Source(
        name="demo",
        role=role,
        version="1",
        filename="demo.txt",
        url="https://invalid.example/demo.txt",
        sha256=sha or sha256_file(original),
        local_candidates=(str(original),),
    )


def test_registry_file_parses_and_every_source_is_pinned():
    sources = registry.load_sources()
    assert sources
    for s in sources.values():
        assert len(s.sha256) == 64 and s.url.startswith("https://"), s.name


@pytest.mark.parametrize(
    "role,purpose,allowed",
    [
        (Role.EVAL, Purpose.TRAIN, False),
        (Role.EVAL, Purpose.KB, False),
        (Role.EVAL, Purpose.SIMULATE, False),
        (Role.EVAL, Purpose.EVAL, True),
        (Role.KNOWLEDGE, Purpose.SIMULATE, True),
        (Role.BASELINE, Purpose.TRAIN, False),
    ],
)
def test_roles_limit_what_a_source_may_feed(tmp_path, role, purpose, allowed):
    source = make_source(tmp_path, role=role)
    if allowed:
        registry.require_role(source, purpose)
    else:
        with pytest.raises(LineageError):
            registry.require_role(source, purpose)


def test_fetch_copies_a_verified_local_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "RAW_DIR", tmp_path / "raw")
    source = make_source(tmp_path)
    path = registry.fetch(source, allow_download=False)
    assert path.read_bytes() == b"hello" and registry.verify(source)


def test_fetch_rejects_a_local_copy_with_the_wrong_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "RAW_DIR", tmp_path / "raw")
    source = make_source(tmp_path, sha="0" * 64)
    with pytest.raises(LineageError):
        registry.fetch(source, allow_download=False)


def test_a_modified_raw_file_no_longer_verifies(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "RAW_DIR", tmp_path / "raw")
    source = make_source(tmp_path)
    registry.fetch(source, allow_download=False).write_bytes(b"tampered")
    assert not registry.verify(source)
