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


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def code_state(cwd: Path = REPO_ROOT) -> CodeState:
    try:
        sha = _git(["rev-parse", "HEAD"], cwd)
    except subprocess.CalledProcessError:
        sha = "unborn"
    dirty = bool(_git(["status", "--porcelain", "--untracked-files=no"], cwd))
    remote = _git(["config", "--get", "remote.origin.url"], cwd) or str(cwd)
    return CodeState(repo=remote, sha=sha, dirty=dirty)
