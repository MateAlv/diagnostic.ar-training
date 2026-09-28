"""Manifests for derived artifacts: what went in, which code, which params, what came out."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from diagnostic_ar_training import MANIFESTS_DIR, REPO_ROOT
from diagnostic_ar_training.lineage.gitinfo import code_state
from diagnostic_ar_training.lineage.hashing import sha256_file, sha256_json
from diagnostic_ar_training.lineage.registry import LineageError


class InputRef(BaseModel):
    id: str
    sha256: str


class OutputRef(BaseModel):
    path: str
    sha256: str
    bytes: int


class Manifest(BaseModel):
    artifact_id: str
    kind: str
    created_at: str
    code: dict
    inputs: list[InputRef]
    params: dict[str, Any]
    params_hash: str
    outputs: list[OutputRef]
    notes: str = ""

    @property
    def path(self) -> Path:
        return MANIFESTS_DIR / f"{self.artifact_id}.json"


def build_manifest(
    artifact_id: str,
    kind: str,
    inputs: list[dict],
    params: dict[str, Any],
    outputs: list[Path],
    notes: str = "",
    allow_dirty: bool = False,
) -> Manifest:
    """Describe an artifact. Refuses a dirty tree: the code SHA must reproduce it."""
    state = code_state()
    if state.dirty and not allow_dirty:
        raise LineageError("working tree has uncommitted changes; commit before producing artifacts")
    refs = []
    for out in outputs:
        out = Path(out).resolve()
        rel = out.relative_to(REPO_ROOT) if out.is_relative_to(REPO_ROOT) else out
        refs.append(OutputRef(path=str(rel), sha256=sha256_file(out), bytes=out.stat().st_size))
    return Manifest(
        artifact_id=artifact_id,
        kind=kind,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        code=state.as_dict(),
        inputs=[InputRef(**i) for i in inputs],
        params=params,
        params_hash=sha256_json(params),
        outputs=refs,
        notes=notes,
    )


def write_manifest(manifest: Manifest, overwrite: bool = False) -> Path:
    if manifest.path.exists() and not overwrite:
        raise LineageError(f"{manifest.path.name} exists; artifact ids are immutable, pick a new one")
    manifest.path.parent.mkdir(parents=True, exist_ok=True)
    manifest.path.write_text(manifest.model_dump_json(indent=2) + "\n")
    return manifest.path


def load_manifest(artifact_id: str) -> Manifest:
    return Manifest.model_validate_json((MANIFESTS_DIR / f"{artifact_id}.json").read_text())


def verify_outputs(manifest: Manifest) -> list[str]:
    """Outputs that are missing or whose bytes no longer match the manifest."""
    problems = []
    for out in manifest.outputs:
        path = Path(out.path) if Path(out.path).is_absolute() else REPO_ROOT / out.path
        if not path.is_file():
            problems.append(f"{out.path}: missing")
        elif sha256_file(path) != out.sha256:
            problems.append(f"{out.path}: sha256 mismatch")
    return problems
