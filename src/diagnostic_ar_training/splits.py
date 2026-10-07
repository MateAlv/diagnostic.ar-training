"""Frozen, publication-grouped splits of patient cohorts, with sealed parts.

Patients from the same publication share authors, phenotyping style and often
family members, so the unit of assignment is the connected component of
patients linked by any shared PMID. Each component goes to a part by a salted
hash of its smallest PMID: deterministic, order-independent, and stable when
the cohort grows. See docs/EVAL_PROTOCOL.md.

Phase 2 (ADR-0017) adds two kinds of split:
- a derived split (`p2-v1`) re-partitions the sealed publication groups of a frozen split by whether E0
  could have seen them;
- a fresh split (`p2-fresh-v1`) takes the patients of a pinned phenopacket-store snapshot that are new since
  the cohort release and whose publications E0 never saw.
"""

import hashlib
import json
import re
import tarfile
import zipfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from diagnostic_ar_training import SPLITS_DIR
from diagnostic_ar_training.cohorts import phenopackets
from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.lineage import ledger
from diagnostic_ar_training.lineage.hashing import sha256_json
from diagnostic_ar_training.lineage.registry import LineageError, Purpose, Role, load_sources, open_source


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
    source: str = ""
    """Cohort source. A fresh split names its snapshot when frozen, and the frozen file records it."""
    salt: str = ""
    parent: str = ""
    """A derived split re-partitions the publication groups of this frozen split."""
    fresh: bool = False


SPECS = {
    "r1-v1": SplitSpec("r1-v1", "phenopacket_store", salt="diagnostic.ar-training/r1-v1"),
    "p2-v1": SplitSpec("p2-v1", "phenopacket_store", parent="r1-v1"),
    "p2-fresh-v1": SplitSpec("p2-fresh-v1", fresh=True),
}

# What E0 could have seen (ADR-0017 §2), and what bounds the fresh split (§4): the cohort release and the
# annotations the knowledge rules use.
E0_RELEASE = "phenopacket_store_0_1_25"
E0_ANNOTATIONS = "hpo_annotations_2025_11_24"
COHORT_RELEASE = "phenopacket_store"
CURRENT_ANNOTATIONS = "hpo_annotations"

POST_E0 = "post_e0"
IN_E0_RELEASE = "in_0_1_25"
CITED_E0 = "cited_hpo_2025_11_24"
NO_PMID = "no_pmid"
GROUP_STATUSES = (POST_E0, IN_E0_RELEASE, CITED_E0, NO_PMID)


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
    if spec.fresh:
        frozen = load_frozen(spec.split_id)
        wanted = {i for ids in frozen["case_ids"].values() for i in ids}
        path = open_source(frozen["cohort_source"], Purpose.EVAL)
        packets = _unique_packets(iter_snapshot_packets(path), Counter())
        parsed = (phenopackets.parse_packet(p, drops) for p in packets if p["id"] in wanted)
        return [c for c in parsed if c is not None], drops
    path = open_source(spec.source, Purpose.EVAL)
    return list(phenopackets.iter_cases(path, drops)), drops


def _part_stats(assignment: dict[Part, list[str]], cases: list[Case], groups: dict[str, str]) -> dict:
    by_id = {c.case_id: c for c in cases}
    stats = {}
    for part, ids in assignment.items():
        members = [by_id[i] for i in ids]
        stats[part.value] = {
            "cases": len(members),
            "publications": len({groups[i] for i in ids}),
            "genes": len({c.gene for c in members}),
            "with_excluded": sum(1 for c in members if c.excluded),
            "with_known_sex": sum(1 for c in members if c.sex != "unknown"),
            "with_age": sum(1 for c in members if c.age_years is not None),
            "with_onset": sum(1 for c in members if c.onset_years is not None or c.onset_term),
        }
    return stats


def compute(spec: SplitSpec) -> dict:
    if spec.parent:
        return _compute_derived(spec)
    if spec.fresh:
        raise LineageError(f"{spec.split_id} is built from a snapshot: run `dxt split freeze-fresh`")
    cases, drops = _all_cases(spec)
    groups = _components(cases)
    assignment: dict[Part, list[str]] = {part: [] for part, _ in BOUNDS}
    for case in cases:
        assignment[_part_of(_bucket(spec.salt, groups[case.case_id]))].append(case.case_id)
    source = load_sources()[spec.source]
    body = {
        "split_id": spec.split_id,
        "source": source.as_input(),
        "salt": spec.salt,
        "rule": "part by sha256(salt:min PMID of publication-linked component) % 100; "
        + ", ".join(f"{p.value}<{u}" for p, u in BOUNDS),
        "sealed_parts": sorted(p.value for p in SEALED),
        "parse_drops": dict(sorted(drops.items())),
        "stats": _part_stats(assignment, cases, groups),
        "case_ids": {part.value: sorted(ids) for part, ids in assignment.items()},
    }
    body["content_sha256"] = sha256_json(body)
    return body


# --- Post-E0 publication groups (ADR-0017 §2) -------------------------------------------------------


def packet_pmids(packet: dict) -> set[str]:
    refs = packet.get("metaData", {}).get("externalReferences") or []
    ids = (str(r.get("id", "")).strip() for r in refs)
    return {i for i in ids if i.startswith("PMID:")}


def release_index(zip_path: Path) -> dict[str, set[str]]:
    """Phenopacket id -> PMIDs of a phenopacket-store release; reads ids and references, never patients."""
    out: dict[str, set[str]] = {}
    with zipfile.ZipFile(zip_path) as archive:
        for name in sorted(archive.namelist()):
            if not name.endswith(".json"):
                continue
            try:
                doc = json.loads(archive.read(name))
            except ValueError:
                continue
            if isinstance(doc, dict) and "id" in doc:
                out.setdefault(doc["id"], set()).update(packet_pmids(doc))
    return out


def cited_pmids(hpoa_path: Path) -> set[str]:
    """PMIDs in the `reference` column of an HPO phenotype.hpoa."""
    out: set[str] = set()
    column = None
    with open(hpoa_path) as handle:
        for line in handle:
            if line.startswith("#"):
                continue
            cols = line.rstrip("\n").split("\t")
            if column is None:
                column = cols.index("reference")
                continue
            if len(cols) > column:
                out |= {x.strip() for x in cols[column].split(";") if x.strip().startswith("PMID:")}
    return out


def _e0_seen() -> tuple[set[str], set[str]]:
    """(PMIDs in phenopacket-store 0.1.25, PMIDs cited in HPO 2025-11-24)."""
    release = release_index(open_source(E0_RELEASE, Purpose.EVAL))
    return set().union(*release.values()), cited_pmids(open_source(E0_ANNOTATIONS, Purpose.EVAL))


def group_pmids(cases: Iterable[Case], groups: dict[str, str]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    for case in cases:
        out[groups[case.case_id]].update(case.pmids)
    return dict(out)


def group_status(pmids: set[str], e0_release: set[str], e0_cited: set[str]) -> str:
    """Post-E0: the group has a PMID, none in phenopacket-store 0.1.25 and none cited in HPO 2025-11-24."""
    if not pmids:
        return NO_PMID
    if pmids & e0_release:
        return IN_E0_RELEASE
    if pmids & e0_cited:
        return CITED_E0
    return POST_E0


def _status_counts(statuses: Iterable[str]) -> dict[str, int]:
    counts = Counter(statuses)
    return {s: counts.get(s, 0) for s in GROUP_STATUSES}


DERIVED_RULE = (
    "train = {p} train; dev = {p} dev; test = {p} test and vault publication groups that are not post-E0; "
    "vault = {p} test and vault publication groups that are post-E0. Groups are {p}'s publication groups. "
    "A group is post-E0 when it has a PMID and none of its PMIDs appears in any phenopacket of "
    "phenopacket-store 0.1.25 (metaData.externalReferences) or in the reference column of HPO phenotype.hpoa "
    "2025-11-24 (ADR-0017)"
)


def _compute_derived(spec: SplitSpec) -> dict:
    parent = load_frozen(spec.parent)
    parent_part = {cid: Part(p) for p, ids in parent["case_ids"].items() for cid in ids}
    cases, _ = _all_cases(SPECS[spec.parent])
    if {c.case_id for c in cases} != set(parent_part):
        raise LineageError(f"{spec.parent}'s source no longer gives the cases it froze")
    groups = publication_groups(spec.parent)
    e0_release, e0_cited = _e0_seen()
    status = {g: group_status(p, e0_release, e0_cited) for g, p in group_pmids(cases, groups).items()}

    assignment: dict[Part, list[str]] = {part: [] for part, _ in BOUNDS}
    for case in cases:
        part = parent_part[case.case_id]
        if part in SEALED:
            part = Part.VAULT if status[groups[case.case_id]] == POST_E0 else Part.TEST
        assignment[part].append(case.case_id)
    stats = _part_stats(assignment, cases, groups)
    for part, ids in assignment.items():
        stats[part.value]["post_e0_publications"] = len(
            {groups[i] for i in ids if status[groups[i]] == POST_E0}
        )

    parent_groups: dict[str, set[str]] = defaultdict(set)
    for cid, part in parent_part.items():
        parent_groups[part.value].add(groups[cid])
    sources = load_sources()
    body = {
        "split_id": spec.split_id,
        "source": sources[spec.source].as_input(),
        "inputs": [
            {"id": f"split:{spec.parent}", "sha256": parent["content_sha256"]},
            sources[E0_RELEASE].as_input(),
            sources[E0_ANNOTATIONS].as_input(),
        ],
        "rule": DERIVED_RULE.format(p=spec.parent),
        "sealed_parts": sorted(p.value for p in SEALED),
        "parse_drops": parent["parse_drops"],
        "group_status_by_parent_part": {
            part: _status_counts(status[g] for g in gs) for part, gs in sorted(parent_groups.items())
        },
        "stats": stats,
        "case_ids": {part.value: sorted(ids) for part, ids in assignment.items()},
    }
    body["content_sha256"] = sha256_json(body)
    return body


# --- Fresh split from a phenopacket-store snapshot (ADR-0017 §4) -----------------------------------------

SNAPSHOT_PACKET = re.compile(r"^[^/]+/notebooks/[^/]+/phenopackets/[^/]+\.json$")


def iter_snapshot_packets(tar_path: Path) -> Iterator[dict]:
    """Phenopackets (notebooks/<cohort>/phenopackets/*.json) of a phenopacket-store tarball, by path."""
    raw: dict[str, bytes] = {}
    with tarfile.open(tar_path, "r:gz") as archive:
        for member in archive:
            if member.isfile() and SNAPSHOT_PACKET.match(member.name):
                raw[member.name] = archive.extractfile(member).read()
    for name in sorted(raw):
        try:
            doc = json.loads(raw[name])
        except ValueError:
            continue
        if isinstance(doc, dict) and "id" in doc:
            yield doc


def _unique_packets(packets: Iterable[dict], exclusions: Counter) -> Iterator[dict]:
    seen: set[str] = set()
    for packet in packets:
        if packet["id"] in seen:
            exclusions["duplicate_id"] += 1
            continue
        seen.add(packet["id"])
        yield packet


PATIENT_EXCLUSIONS = ("duplicate_id", "id_in_0_1_27", "parser")
GROUP_EXCLUSIONS = ("pmid_in_0_1_27", NO_PMID, IN_E0_RELEASE, CITED_E0, "cited_hpo_2026_02_16")


@dataclass(frozen=True)
class FreshSelection:
    cases: list[Case]
    groups: dict[str, str]
    excluded_patients: dict[str, int]
    excluded_groups: dict[str, int]
    parse_drops: dict[str, int]


def select_fresh(
    packets: Iterable[dict],
    cohort_release: dict[str, set[str]],
    e0_release: set[str],
    e0_cited: set[str],
    now_cited: set[str],
) -> FreshSelection:
    """Patients of a snapshot that are new since the cohort release and whose publication group E0 never saw.

    Patient-level, in order: a duplicate id, an id in the cohort release, a parser drop.
    Group-level, over the publication groups of the remaining patients, first reason wins: a PMID in the
    cohort release; not post-E0 (no PMID, a PMID in 0.1.25, a PMID cited in HPO 2025-11-24); a PMID cited in
    the HPO annotations the knowledge rules use (2026-02-16).
    """
    exclusions: Counter = Counter()
    drops: Counter = Counter()
    release_pmids = set().union(*cohort_release.values()) if cohort_release else set()
    candidates = []
    for packet in _unique_packets(packets, exclusions):
        if packet["id"] in cohort_release:
            exclusions["id_in_0_1_27"] += 1
            continue
        case = phenopackets.parse_packet(packet, drops)
        if case is None:
            exclusions["parser"] += 1
            continue
        candidates.append(case)

    groups = _components(candidates)
    reason = {}
    for group, pmids in group_pmids(candidates, groups).items():
        status = group_status(pmids, e0_release, e0_cited)
        if pmids & release_pmids:
            reason[group] = "pmid_in_0_1_27"
        elif status != POST_E0:
            reason[group] = status
        elif pmids & now_cited:
            reason[group] = "cited_hpo_2026_02_16"
    kept = []
    for case in candidates:
        why = reason.get(groups[case.case_id])
        if why:
            exclusions[why] += 1
        else:
            kept.append(case)
    group_counts = Counter(reason.values())
    return FreshSelection(
        cases=kept,
        groups={c.case_id: groups[c.case_id] for c in kept},
        excluded_patients={k: exclusions.get(k, 0) for k in PATIENT_EXCLUSIONS + GROUP_EXCLUSIONS},
        excluded_groups={k: group_counts.get(k, 0) for k in GROUP_EXCLUSIONS},
        parse_drops=dict(sorted(drops.items())),
    )


FRESH_RULE = (
    "vault = every patient of the snapshot whose phenopacket id is not in phenopacket-store 0.1.27 and who "
    "passes the parser r1-v1 uses, when their publication group (patients linked by a shared PMID, among "
    "those) has a PMID, no PMID in 0.1.27, is post-E0 (no PMID in 0.1.25 nor in the reference column of HPO "
    "phenotype.hpoa 2025-11-24) and has no PMID in the reference column of HPO phenotype.hpoa 2026-02-16 "
    "(ADR-0017 §4)"
)


def compute_fresh(spec: SplitSpec, snapshot: str) -> dict:
    if not spec.fresh:
        raise LineageError(f"{spec.split_id} is not a fresh split")
    sources = load_sources()
    if snapshot not in sources or sources[snapshot].role != Role.COHORT:
        raise LineageError(f"{snapshot!r} must be a cohort source in data/sources.yaml")
    e0_release, e0_cited = _e0_seen()
    selection = select_fresh(
        iter_snapshot_packets(open_source(snapshot, Purpose.EVAL)),
        release_index(open_source(COHORT_RELEASE, Purpose.EVAL)),
        e0_release,
        e0_cited,
        cited_pmids(open_source(CURRENT_ANNOTATIONS, Purpose.EVAL)),
    )
    assignment = {Part.VAULT: [c.case_id for c in selection.cases]}
    stats = _part_stats(assignment, selection.cases, selection.groups)
    stats[Part.VAULT.value]["post_e0_publications"] = stats[Part.VAULT.value]["publications"]
    names = (COHORT_RELEASE, E0_RELEASE, E0_ANNOTATIONS, CURRENT_ANNOTATIONS)
    body = {
        "split_id": spec.split_id,
        "source": sources[snapshot].as_input(),
        "cohort_source": snapshot,
        "inputs": [sources[n].as_input() for n in names],
        "rule": FRESH_RULE,
        "sealed_parts": [Part.VAULT.value],
        "parse_drops": selection.parse_drops,
        "exclusions": {
            "patients": selection.excluded_patients,
            "publication_groups": selection.excluded_groups,
        },
        "stats": stats,
        "case_ids": {Part.VAULT.value: sorted(assignment[Part.VAULT])},
    }
    body["content_sha256"] = sha256_json(body)
    return body


def _write_or_check(split_id: str, body: dict) -> dict:
    path = SPLITS_DIR / f"{split_id}.json"
    if path.exists():
        frozen = json.loads(path.read_text())
        if frozen["content_sha256"] != body["content_sha256"]:
            raise LineageError(f"{split_id} is frozen and recomputing it gives different content")
        return frozen
    path.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n")
    return body


def freeze_fresh(split_id: str, snapshot: str) -> dict:
    """Write a fresh split once from a pinned snapshot source; re-freezing must reproduce it byte for byte."""
    return _write_or_check(split_id, compute_fresh(SPECS[split_id], snapshot))


def freeze(split_id: str) -> dict:
    """Write data/splits/<id>.json once; re-freezing must reproduce it byte for byte."""
    spec = SPECS[split_id]
    if spec.fresh and (SPLITS_DIR / f"{split_id}.json").exists():
        return freeze_fresh(split_id, load_frozen(split_id)["cohort_source"])
    return _write_or_check(split_id, compute(spec))


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

    Sealed parts require a pre-registered experiment, DXT_SEALED_READ=<exp_id> in the
    environment, and are logged in the ledger;
    the vault opens once, for the final report.
    """
    part = Part(part)
    if purpose not in ALLOWED[part]:
        raise LineageError(f"{split_id}/{part} may not be used for {purpose}")
    frozen = load_frozen(split_id)
    if part.value not in frozen["case_ids"]:
        raise LineageError(f"{split_id} has no {part} part")
    if part in SEALED:
        if exp_id is None:
            raise LineageError(f"{split_id}/{part} is sealed: pass exp_id and reason")
        ledger.require_sealed_read_env(split_id, part.value, exp_id)
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
    wanted = {i for part in MASK_SCOPES[scope] for i in frozen["case_ids"].get(part.value, ())}
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


def presentation_keys(split_id: str) -> set[tuple[str, frozenset[str]]]:
    """(gene upper-cased, present set) of every patient in every part, for contamination checks only.

    Like `mask_pmids`, it returns keys, never cases: training material is checked against the sealed
    parts without evaluating anything on them (EVAL_PROTOCOL §4.2, §9.7).
    """
    cases, _ = _all_cases(SPECS[split_id])
    return {(c.gene.upper(), frozenset(c.present)) for c in cases}


def publication_groups(split_id: str) -> dict[str, str]:
    """case_id -> publication group; the resampling unit for R1 confidence intervals."""
    cases, _ = _all_cases(SPECS[split_id])
    return _components(cases)
