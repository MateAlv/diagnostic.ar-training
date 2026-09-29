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
    release: str = ""
    """GitHub release tag of this repo holding the output files, if published (ADR-0005)."""

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


def ensure_new(artifact_id: str) -> None:
    """Call before building: an id that already has a manifest is never rebuilt or republished."""
    if (MANIFESTS_DIR / f"{artifact_id}.json").exists():
        raise LineageError(f"{artifact_id} already exists; artifact ids are immutable, pick a new one")


def publish(manifest: Manifest, tag: str) -> Manifest:
    """Upload the outputs as a release of this repo and record the tag."""
    import subprocess

    files = [str(output_path(o)) for o in manifest.outputs]
    subprocess.run(
        [
            "gh",
            "release",
            "create",
            tag,
            *files,
            "--title",
            tag,
            "--notes",
            f"Artifact {manifest.artifact_id}; lineage in data/manifests/{manifest.artifact_id}.json",
        ],
        check=True,
        cwd=REPO_ROOT,
    )
    return manifest.model_copy(update={"release": tag})


def fetch_outputs(manifest: Manifest) -> list[Path]:
    """Download a published artifact's files and check them against the manifest."""
    import subprocess

    if not manifest.release:
        raise LineageError(f"{manifest.artifact_id} was never published")
    paths = []
    for out in manifest.outputs:
        path = output_path(out)
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["gh", "release", "download", manifest.release, "-p", path.name, "-D", str(path.parent)],
                check=True,
                cwd=REPO_ROOT,
            )
        paths.append(path)
    if problems := verify_outputs(manifest):
        raise LineageError("; ".join(problems))
    return paths


def write_manifest(manifest: Manifest, overwrite: bool = False) -> Path:
    if manifest.path.exists() and not overwrite:
        raise LineageError(f"{manifest.path.name} exists; artifact ids are immutable, pick a new one")
    manifest.path.parent.mkdir(parents=True, exist_ok=True)
    manifest.path.write_text(manifest.model_dump_json(indent=2) + "\n")
    return manifest.path


def load_manifest(artifact_id: str) -> Manifest:
    return Manifest.model_validate_json((MANIFESTS_DIR / f"{artifact_id}.json").read_text())


def output_path(out: OutputRef) -> Path:
    return Path(out.path) if Path(out.path).is_absolute() else REPO_ROOT / out.path


def verify_outputs(manifest: Manifest) -> list[str]:
    """Outputs whose bytes no longer match, or missing ones that were never published."""
    problems = []
    for out in manifest.outputs:
        path = output_path(out)
        if not path.is_file():
            if not manifest.release:
                problems.append(f"{out.path}: missing")
        elif sha256_file(path) != out.sha256:
            problems.append(f"{out.path}: sha256 mismatch")
    return problems
