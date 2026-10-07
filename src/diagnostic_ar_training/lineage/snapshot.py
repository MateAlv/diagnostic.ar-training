"""Pin a GitHub branch as it stood before a timestamp: the commit's tarball and its data/sources.yaml entry.

Used for `p2-fresh-v1` (ADR-0017 §4), whose source is phenopacket-store `main` at its last commit before
2026-10-20T00:00Z. The tarball of a commit has fixed content; its sha256 is pinned like any other source.
"""

import json
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from diagnostic_ar_training.lineage.hashing import sha256_file
from diagnostic_ar_training.lineage.registry import LineageError

GITHUB_API = "https://api.github.com"


def archive_url(repo: str, sha: str) -> str:
    return f"https://github.com/{repo}/archive/{sha}.tar.gz"


@dataclass(frozen=True)
class Snapshot:
    name: str
    repo: str
    branch: str
    before: str
    sha: str
    committed: str
    path: Path
    sha256: str

    def sources_entry(self, license: str) -> str:
        entry = {
            "role": "cohort",
            "version": f"{self.branch}@{self.sha[:7]}",
            "filename": self.path.name,
            "url": archive_url(self.repo, self.sha),
            "upstream_url": f"https://github.com/{self.repo}/commit/{self.sha}",
            "sha256": self.sha256,
            "license": license,
            "notes": (
                f"{self.repo} {self.branch} at its last commit before {self.before} ({self.sha}, committed "
                f"{self.committed}), as the GitHub tarball of that commit. Patients only through the fresh "
                "split frozen from it (ADR-0017 §4)."
            ),
        }
        return yaml.safe_dump({self.name: entry}, sort_keys=False, allow_unicode=True, width=1000)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _get_json(url: str):
    request = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json", "User-Agent": "diagnostic.ar-training"}
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())


def _download(url: str, dest: Path) -> None:
    urllib.request.urlretrieve(url, dest)


def resolve_commit(
    repo: str, branch: str, before: str, get_json: Callable[[str], list] = _get_json
) -> tuple[str, str]:
    """(sha, committer date) of the last commit on `branch` committed strictly before `before` (UTC)."""
    limit = _parse_time(before)
    commits = get_json(f"{GITHUB_API}/repos/{repo}/commits?sha={branch}&until={before}&per_page=100")
    dated = [(_parse_time(c["commit"]["committer"]["date"]), c["sha"]) for c in commits]
    earlier = [(when, sha) for when, sha in dated if when < limit]
    if not earlier:
        raise LineageError(f"no commit on {repo}@{branch} before {before}")
    when, sha = max(earlier)
    return sha, when.isoformat().replace("+00:00", "Z")


def snapshot_github(
    name: str,
    repo: str,
    branch: str,
    before: str,
    raw_dir: Path,
    get_json: Callable[[str], list] = _get_json,
    download: Callable[[str, Path], None] = _download,
) -> Snapshot:
    """Download the commit tarball into <raw_dir>/<name>/ (once) and describe it for data/sources.yaml."""
    sha, committed = resolve_commit(repo, branch, before, get_json)
    dest = raw_dir / name / f"{repo.split('/')[-1]}-{sha}.tar.gz"
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        partial = dest.with_suffix(dest.suffix + ".partial")
        download(archive_url(repo, sha), partial)
        partial.replace(dest)
    return Snapshot(name, repo, branch, before, sha, committed, dest, sha256_file(dest))
