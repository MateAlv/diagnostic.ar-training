import subprocess
from dataclasses import dataclass
from pathlib import Path

from diagnostic_ar_training import REPO_ROOT


@dataclass(frozen=True)
class CodeState:
    repo: str
    sha: str
    dirty: bool

    def as_dict(self) -> dict:
        return {"repo": self.repo, "sha": self.sha, "dirty": self.dirty}


def _run_git(args: list[str], cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def _git(args: list[str], cwd: Path) -> str:
    return _run_git(args, cwd).strip()


# Files that runs themselves write; changes to them do not make the code irreproducible.
OUTPUT_PATHS = ("docs/TEST_LEDGER.md", "docs/BITACORA.md", "results/", "data/manifests/")


def code_state(cwd: Path = REPO_ROOT) -> CodeState:
    try:
        sha = _git(["rev-parse", "HEAD"], cwd)
    except subprocess.CalledProcessError:
        sha = "unborn"
    porcelain = _run_git(["status", "--porcelain", "--untracked-files=no"], cwd)
    changed = [line[3:] for line in porcelain.splitlines() if line.strip()]
    dirty = any(not path.startswith(OUTPUT_PATHS) for path in changed)
    remote = _git(["config", "--get", "remote.origin.url"], cwd) or str(cwd)
    return CodeState(repo=remote, sha=sha, dirty=dirty)


def is_committed_unchanged(path: Path, cwd: Path = REPO_ROOT) -> bool:
    rel = str(Path(path).resolve().relative_to(cwd))
    try:
        _git(["ls-files", "--error-unmatch", rel], cwd)
    except subprocess.CalledProcessError:
        return False
    return not _git(["status", "--porcelain", "--", rel], cwd)
