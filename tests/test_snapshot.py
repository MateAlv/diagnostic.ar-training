import pytest

from diagnostic_ar_training.lineage import registry, snapshot
from diagnostic_ar_training.lineage.hashing import sha256_file
from diagnostic_ar_training.lineage.registry import LineageError, Role


def commit(sha, date):
    return {"sha": sha, "commit": {"committer": {"date": date}}}


COMMITS = [
    commit("c" * 40, "2026-10-20T00:00:00Z"),
    commit("b" * 40, "2026-10-19T21:15:00Z"),
    commit("a" * 40, "2026-10-18T09:00:00Z"),
]


def test_resolve_commit_takes_the_last_commit_strictly_before():
    urls = []

    def get_json(url):
        urls.append(url)
        return COMMITS

    sha, when = snapshot.resolve_commit("o/r", "main", "2026-10-20T00:00:00Z", get_json)
    assert (sha, when) == ("b" * 40, "2026-10-19T21:15:00Z")
    assert "repos/o/r/commits?sha=main&until=2026-10-20T00:00:00Z" in urls[0]
    with pytest.raises(LineageError):
        snapshot.resolve_commit("o/r", "main", "2026-10-01T00:00:00Z", get_json)


def test_snapshot_downloads_once_and_prints_a_loadable_sources_entry(tmp_path):
    downloads = []

    def download(url, dest):
        downloads.append(url)
        dest.write_bytes(b"tarball")

    snap = snapshot.snapshot_github(
        "ps_main",
        "o/phenopacket-store",
        "main",
        "2026-10-20T00:00:00Z",
        tmp_path,
        lambda u: COMMITS,
        download,
    )
    again = snapshot.snapshot_github(
        "ps_main",
        "o/phenopacket-store",
        "main",
        "2026-10-20T00:00:00Z",
        tmp_path,
        lambda u: COMMITS,
        download,
    )
    assert downloads == [f"https://github.com/o/phenopacket-store/archive/{'b' * 40}.tar.gz"]
    assert snap == again and snap.path == tmp_path / "ps_main" / f"phenopacket-store-{'b' * 40}.tar.gz"
    assert snap.sha256 == sha256_file(snap.path)

    yaml_file = tmp_path / "sources.yaml"
    yaml_file.write_text(snap.sources_entry("CC-BY-4.0"))
    source = registry.load_sources(yaml_file)["ps_main"]
    assert source.role is Role.COHORT
    assert (source.sha256, source.filename, source.version) == (snap.sha256, snap.path.name, "main@bbbbbbb")
