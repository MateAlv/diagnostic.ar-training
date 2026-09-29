"""Frozen, publication-grouped splits of patient cohorts, with sealed parts.

Patients from the same publication share authors, phenotyping style and often
family members, so the unit of assignment is the connected component of
patients linked by any shared PMID. Each component goes to a part by a salted
hash of its smallest PMID: deterministic, order-independent, and stable when
the cohort grows. See docs/EVAL_PROTOCOL.md.
"""

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum

from diagnostic_ar_training import SPLITS_DIR
from diagnostic_ar_training.cohorts import phenopackets
from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.lineage import ledger
from diagnostic_ar_training.lineage.hashing import sha256_json
from diagnostic_ar_training.lineage.registry import LineageError, Purpose, load_sources, open_source


class Part(StrEnum):
    TRAIN = "train"
    DEV = "dev"
    TEST = "test"
    VAULT = "vault"


# Upper bucket bound (exclusive) of each part, out of 100.
BOUNDS = ((Part.TRAIN, 40), (Part.DEV, 60), (Part.TEST, 80), (Part.VAULT, 100))
SEALED = {Part.TEST, Part.VAULT}
ALLOWED: dict[Part, set[Purpose]] = {
    Part.TRAIN: {Purpose.TRAIN, Purpose.KB, Purpose.SIMULATE, Purpose.EVAL},
    Part.DEV: {Purpose.EVAL},
    Part.TEST: {Purpose.EVAL},
    Part.VAULT: {Purpose.EVAL},
}


@dataclass(frozen=True)
class SplitSpec:
    split_id: str
    source: str
    salt: str


SPECS = {
    "r1-v1": SplitSpec("r1-v1", "phenopacket_store", "diagnostic.ar-training/r1-v1"),
}


def _components(cases: list[Case]) -> dict[str, str]:
    """case_id -> group key (smallest PMID of its publication-linked component)."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for case in cases:
        keys = list(case.pmids) or [f"case:{case.case_id}"]
        for other in keys[1:]:
            a, b = find(keys[0]), find(other)
            if a != b:
                parent[max(a, b)] = min(a, b)
    return {c.case_id: find((list(c.pmids) or [f"case:{c.case_id}"])[0]) for c in cases}


def _bucket(salt: str, key: str) -> int:
    return int(hashlib.sha256(f"{salt}:{key}".encode()).hexdigest(), 16) % 100


def _part_of(bucket: int) -> Part:
    return next(part for part, upper in BOUNDS if bucket < upper)


def _all_cases(spec: SplitSpec) -> tuple[list[Case], Counter]:
    drops: Counter = Counter()
    path = open_source(spec.source, Purpose.EVAL)
    return list(phenopackets.iter_cases(path, drops)), drops


def compute(spec: SplitSpec) -> dict:
    cases, drops = _all_cases(spec)
    groups = _components(cases)
    assignment: dict[Part, list[str]] = {part: [] for part, _ in BOUNDS}
    group_part: dict[str, Part] = {}
    for case in cases:
        part = _part_of(_bucket(spec.salt, groups[case.case_id]))
        assignment[part].append(case.case_id)
        group_part[groups[case.case_id]] = part

    by_id = {c.case_id: c for c in cases}
    stats = {}
    for part, ids in assignment.items():
        members = [by_id[i] for i in ids]
        stats[part.value] = {
            "cases": len(members),
            "publications": sum(1 for p in group_part.values() if p == part),
            "genes": len({c.gene for c in members}),
            "with_excluded": sum(1 for c in members if c.excluded),
            "with_known_sex": sum(1 for c in members if c.sex != "unknown"),
            "with_age": sum(1 for c in members if c.age_years is not None),
            "with_onset": sum(1 for c in members if c.onset_years is not None or c.onset_term),
        }
    source = load_sources()[spec.source]
    body = {
        "split_id": spec.split_id,
        "source": source.as_input(),
        "salt": spec.salt,
        "rule": "part by sha256(salt:min PMID of publication-linked component) % 100; "
        + ", ".join(f"{p.value}<{u}" for p, u in BOUNDS),
        "sealed_parts": sorted(p.value for p in SEALED),
        "parse_drops": dict(sorted(drops.items())),
        "stats": stats,
        "case_ids": {part.value: sorted(ids) for part, ids in assignment.items()},
    }
    body["content_sha256"] = sha256_json(body)
    return body


def freeze(split_id: str) -> dict:
    """Write data/splits/<id>.json once; re-freezing must reproduce it byte for byte."""
    body = compute(SPECS[split_id])
    path = SPLITS_DIR / f"{split_id}.json"
    if path.exists():
        frozen = json.loads(path.read_text())
        if frozen["content_sha256"] != body["content_sha256"]:
            raise LineageError(f"{split_id} is frozen and recomputing it gives different content")
        return frozen
    path.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n")
    return body


def load_frozen(split_id: str) -> dict:
    path = SPLITS_DIR / f"{split_id}.json"
    if not path.exists():
        raise LineageError(f"{split_id} is not frozen; run `dxt split freeze {split_id}`")
    body = json.loads(path.read_text())
    content = {k: v for k, v in body.items() if k != "content_sha256"}
    if sha256_json(content) != body["content_sha256"]:
        raise LineageError(f"data/splits/{split_id}.json was edited by hand")
    return body


def load_part(
    split_id: str,
    part: Part,
    purpose: Purpose,
    exp_id: str | None = None,
    reason: str = "",
) -> list[Case]:
    """The only sanctioned way to get patients of a cohort source.

    Sealed parts require a pre-registered experiment and are logged in the ledger;
    the vault opens once, for the final report.
    """
    part = Part(part)
    if purpose not in ALLOWED[part]:
        raise LineageError(f"{split_id}/{part} may not be used for {purpose}")
    frozen = load_frozen(split_id)
    if part in SEALED:
        if exp_id is None:
            raise LineageError(f"{split_id}/{part} is sealed: pass exp_id and reason")
        if part is Part.VAULT and ledger.entries(split_id, part):
            raise LineageError(f"{split_id}/vault was already opened (see docs/TEST_LEDGER.md)")
        ledger.record_access(split_id, part, exp_id, reason)
    wanted = set(frozen["case_ids"][part.value])
    cases, _ = _all_cases(SPECS[split_id])
    return [c for c in cases if c.case_id in wanted]


# heldout: dev/test/vault publications, which every KB and simulator profile must mask.
# all: every R1 publication, for anything fitted on R1-train patients, so that a train
#      patient's features never come from annotations curated from their own paper.
MASK_SCOPES = {"heldout": (Part.DEV, Part.TEST, Part.VAULT), "all": tuple(Part)}


def mask_pmids(split_id: str, scope: str = "heldout") -> set[str]:
    frozen = load_frozen(split_id)
    wanted = {i for part in MASK_SCOPES[scope] for i in frozen["case_ids"][part.value]}
    cases, _ = _all_cases(SPECS[split_id])
    return {pmid for c in cases if c.case_id in wanted for pmid in c.pmids}


def mask_path(split_id: str, scope: str = "heldout"):
    return SPLITS_DIR / f"{split_id}.{scope}-pmids.txt"


def write_mask(split_id: str, scope: str = "heldout") -> str:
    """Export a masking list; refuses if a committed list drifted from what the split implies."""
    text = "".join(f"{p}\n" for p in sorted(mask_pmids(split_id, scope)))
    path = mask_path(split_id, scope)
    if path.exists() and path.read_text() != text:
        raise LineageError(f"{path.name} differs from what {split_id} implies")
    path.write_text(text)
    return hashlib.sha256(text.encode()).hexdigest()


def heldout_pmids(split_id: str) -> set[str]:
    return mask_pmids(split_id, "heldout")


def heldout_pmids_path(split_id: str):
    return mask_path(split_id, "heldout")


def write_heldout_pmids(split_id: str) -> str:
    return write_mask(split_id, "heldout")


def publication_groups(split_id: str) -> dict[str, str]:
    """case_id -> publication group; the resampling unit for R1 confidence intervals."""
    cases, _ = _all_cases(SPECS[split_id])
    return _components(cases)
