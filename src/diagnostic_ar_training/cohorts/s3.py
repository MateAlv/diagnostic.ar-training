"""S3 cohort: simulated patients for the question-agent evaluation (EVAL_PROTOCOL §8).

A case's truth (`true_present`) is kept apart from the Case that systems see, and
only `eval.interactive.interview` joins them. The starting presentation is the
reported present terms plus sex, age and onset: the simulator's own asked-and-absent
terms are dropped, because in S3 every negation comes from the questioner.
"""

import gzip
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from diagnostic_ar_training import SPLITS_DIR
from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.lineage import ledger
from diagnostic_ar_training.lineage.hashing import sha256_file, sha256_json
from diagnostic_ar_training.lineage.registry import LineageError

PARTS = ("dev", "test")
SEALED = {"test"}


@dataclass(frozen=True)
class S3Spec:
    """What an S3 version is made of: its dataset, the knowledge split its KBs must drop, its exclusions."""

    split_id: str
    dataset_artifact: str
    annotation_split: str
    exclusion_artifact: str | None


SPECS = {
    "s3-v1": S3Spec("s3-v1", "s3-data-v1", "annot-split-v1", None),
    "s3-v2": S3Spec("s3-v2", "s3-data-v2", "annot-split-v2", "s3-data-v2-excl-v1"),
}


def spec(split_id: str) -> S3Spec:
    if split_id not in SPECS:
        raise ValueError(f"split must be one of {sorted(SPECS)}, got {split_id!r}")
    return SPECS[split_id]


def check_kb_split(split_id: str, heldout_annotations_dropped: str | None) -> None:
    """A KB may serve an S3 version only if it was built without that version's half B."""
    wanted = spec(split_id).annotation_split
    if heldout_annotations_dropped != wanted:
        raise ValueError(
            f"{split_id} needs a KB built without half B of {wanted}, not {heldout_annotations_dropped!r}"
        )


def read_dataset(path: Path, cohort: str) -> list[tuple[Case, frozenset[str]]]:
    out = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            r = json.loads(line)
            case = Case(
                case_id=f"{cohort}:{r['case_id']}",
                cohort=cohort,
                gene=r["gene"],
                present=tuple(sorted(r["present"])),
                sex=r["sex"],
                age_years=r["age_years"],
                onset_years=r["onset_years"],
            )
            out.append((case, frozenset(r["true_present"])))
    return out


def read_entities(path: Path, cohort: str, case_ids: set[str]) -> dict[str, str]:
    """case_id -> the disease entity the generator drew the case from, for the given cases only.

    Analysis only; systems never see it.
    """
    out = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            r = json.loads(line)
            case_id = f"{cohort}:{r['case_id']}"
            if case_id in case_ids:
                out[case_id] = r["entity"]
    return out


def _part(salt: str, case_id: str) -> str:
    return PARTS[int(hashlib.sha256(f"{salt}:{case_id}".encode()).hexdigest(), 16) % 2]


def freeze(split_id: str, dataset: Path, dataset_manifest_sha: str) -> dict:
    cases = read_dataset(dataset, split_id)
    salt = f"diagnostic.ar-training/{split_id}"
    ids = {p: sorted(c.case_id for c, _ in cases if _part(salt, c.case_id) == p) for p in PARTS}
    body = {
        "split_id": split_id,
        "dataset": {"sha256": sha256_file(dataset), "manifest_output_sha256": dataset_manifest_sha},
        "salt": salt,
        "rule": "part by sha256(salt:case_id) % 2: 0 -> dev, 1 -> test",
        "sealed_parts": sorted(SEALED),
        "counts": {p: len(v) for p, v in ids.items()},
        "case_ids": ids,
    }
    body["content_sha256"] = sha256_json(body)
    path = SPLITS_DIR / f"{split_id}.json"
    if path.exists():
        frozen = json.loads(path.read_text())
        if frozen["content_sha256"] != body["content_sha256"]:
            raise LineageError(f"{split_id} is frozen and recomputing it gives different content")
        return frozen
    path.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n")
    return body


def load_part(
    split_id: str, part: str, dataset: Path, exp_id: str | None = None, reason: str = ""
) -> list[tuple[Case, frozenset[str]]]:
    """(case, truth) pairs of one part; the sealed part needs a ledgered read and DXT_SEALED_READ=<exp_id>."""
    if part in SEALED:
        if exp_id is None:
            raise LineageError(f"{split_id}/{part} is sealed: pass exp_id and reason")
        ledger.require_sealed_read_env(split_id, part, exp_id)
    path = SPLITS_DIR / f"{split_id}.json"
    body = json.loads(path.read_text())
    content = {k: v for k, v in body.items() if k != "content_sha256"}
    if sha256_json(content) != body["content_sha256"]:
        raise LineageError(f"data/splits/{split_id}.json was edited by hand")
    if sha256_file(dataset) != body["dataset"]["sha256"]:
        raise LineageError(f"{dataset} is not the dataset {split_id} was frozen on")
    if part in SEALED:
        ledger.record_access(split_id, part, exp_id, reason)
    wanted = set(body["case_ids"][part])
    return [(c, t) for c, t in read_dataset(dataset, split_id) if c.case_id in wanted]
