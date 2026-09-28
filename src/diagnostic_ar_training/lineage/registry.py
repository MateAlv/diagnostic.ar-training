"""Pinned external sources (data/sources.yaml) and the rules on what each may feed."""

import re
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import yaml

from diagnostic_ar_training import DATA_DIR, RAW_DIR, REPO_ROOT
from diagnostic_ar_training.lineage.hashing import sha256_file

SOURCES_FILE = DATA_DIR / "sources.yaml"
GITHUB_RELEASE = re.compile(r"^https://github\.com/([^/]+/[^/]+)/releases/download/([^/]+)/([^/]+)$")


class Role(StrEnum):
    KNOWLEDGE = "knowledge"
    COHORT = "cohort"
    EVAL = "eval"
    BASELINE = "baseline"


class Purpose(StrEnum):
    TRAIN = "train"
    KB = "kb"
    SIMULATE = "simulate"
    EVAL = "eval"
    BASELINE = "baseline"


# Cohort sources are allowed any purpose here because the frozen split decides
# per case what it may feed (see splits.py); eval sources never feed learning.
ALLOWED: dict[Role, set[Purpose]] = {
    Role.KNOWLEDGE: {Purpose.TRAIN, Purpose.KB, Purpose.SIMULATE, Purpose.EVAL},
    Role.COHORT: set(Purpose),
    Role.EVAL: {Purpose.EVAL},
    Role.BASELINE: {Purpose.BASELINE, Purpose.EVAL},
}


class LineageError(RuntimeError):
    pass


@dataclass(frozen=True)
class Source:
    name: str
    role: Role
    version: str
    filename: str
    url: str
    sha256: str
    license: str = ""
    notes: str = ""
    upstream_url: str = ""
    local_candidates: tuple[str, ...] = field(default_factory=tuple)

    @property
    def path(self) -> Path:
        return RAW_DIR / self.name / self.filename

    def as_input(self) -> dict:
        return {"id": f"source:{self.name}@{self.version}", "sha256": self.sha256}


def load_sources(path: Path = SOURCES_FILE) -> dict[str, Source]:
    raw = yaml.safe_load(path.read_text())
    sources = {}
    for name, spec in raw.items():
        spec = dict(spec)
        spec["role"] = Role(spec["role"])
        spec["local_candidates"] = tuple(spec.get("local_candidates", ()))
        sources[name] = Source(name=name, **spec)
    return sources


def require_role(source: Source, purpose: Purpose) -> None:
    if purpose not in ALLOWED[source.role]:
        raise LineageError(f"source {source.name!r} has role {source.role}; it may not be used for {purpose}")


def verify(source: Source) -> bool:
    return source.path.is_file() and sha256_file(source.path) == source.sha256


def fetch(source: Source, allow_download: bool = True) -> Path:
    """Materialise a source into data/raw, verifying its sha256 whatever the origin."""
    if verify(source):
        return source.path
    source.path.parent.mkdir(parents=True, exist_ok=True)
    tmp = source.path.with_suffix(source.path.suffix + ".partial")

    for candidate in source.local_candidates:
        candidate_path = (REPO_ROOT / candidate).resolve()
        if candidate_path.is_file() and sha256_file(candidate_path) == source.sha256:
            shutil.copyfile(candidate_path, tmp)
            tmp.replace(source.path)
            return source.path

    if not allow_download:
        raise LineageError(f"{source.name}: no verified local copy and downloads are disabled")
    _download(source.url, tmp)
    actual = sha256_file(tmp)
    if actual != source.sha256:
        tmp.unlink()
        raise LineageError(f"{source.name}: sha256 {actual} != pinned {source.sha256}")
    tmp.replace(source.path)
    return source.path


def _download(url: str, dest: Path) -> None:
    """Release assets go through `gh`, which also reaches our private repos."""
    release = GITHUB_RELEASE.match(url)
    if release and shutil.which("gh"):
        repo, tag, asset = release.groups()
        with dest.parent.joinpath(asset).open("wb") as handle:
            subprocess.run(
                ["gh", "release", "download", tag, "-R", repo, "-p", asset, "-O", "-"],
                check=True,
                stdout=handle,
            )
        dest.parent.joinpath(asset).replace(dest)
        return
    urllib.request.urlretrieve(url, dest)


def open_source(name: str, purpose: Purpose) -> Path:
    """The only sanctioned way for code to get a source's path."""
    source = load_sources()[name]
    require_role(source, purpose)
    if not verify(source):
        raise LineageError(f"{name}: missing or modified in data/raw; run `dxt sources fetch`")
    return source.path
