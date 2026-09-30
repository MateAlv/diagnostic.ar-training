"""Interviewed simulated training cases (ADR-0010 §2): negatives produced the way the app produces them.

A declared subsample of the simulator's train and val splits (the k cases per gene with the smallest
sha256(salt:case_id), after the exclusion artifact) is interviewed exactly like S3
(`eval.s3_run.interview_cases`):
- the starting presentation is the reported present terms plus sex, age and onset; the simulator's own
  `excluded` terms are dropped;
- E0 (the production ONNX) ranks it; the questioner picks questions from E0's candidates and a KB without
  half B; the case's `true_present` answers them;
- "yes" answers join `present`, "no" answers become `excluded`.

Rows keep the simulator export's fields, so `gnn.data.read_export` reads the artifact as it reads the
source dataset. The file is gzip with mtime 0 and sorted keys, in (split, case_id) order, so the same
inputs give the same bytes.
"""

import gzip
import hashlib
import io
import json
import math
import multiprocessing
from collections import defaultdict
from collections.abc import Iterable, Iterator
from pathlib import Path

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.gnn.data import overlap_key

SPLIT_ORDER = ("train", "val")


def selection_key(salt: str, case_id: str) -> str:
    return hashlib.sha256(f"{salt}:{case_id}".encode()).hexdigest()


def select(rows: Iterable[tuple[str, str, str]], per_gene: dict[str, int], salt: str) -> dict[str, list[str]]:
    """(split, gene, case_id) rows -> per split, the kept ids: per gene, the `per_gene[split]` smallest."""
    by_gene: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for split, gene, case_id in rows:
        if split in per_gene:
            by_gene[split, gene].append((selection_key(salt, case_id), case_id))
    out: dict[str, list[str]] = {s: [] for s in per_gene}
    for (split, _), keyed in by_gene.items():
        out[split] += [case_id for _, case_id in sorted(keyed)[: per_gene[split]]]
    return {s: sorted(ids) for s, ids in out.items()}


def iter_source(path: Path, exclude: frozenset[str]) -> Iterator[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            r = json.loads(line)
            if r["case_id"] not in exclude:
                yield r


def initial_case(r: dict) -> Case:
    """What the clinician reports before any question: present terms, sex, age, onset. No negations."""
    return Case(
        case_id=r["case_id"],
        cohort="sim",
        gene=r["gene"],
        present=tuple(sorted(set(r["present"]))),
        sex=r["sex"],
        age_years=r["age_years"],
        onset_years=r["onset_years"],
    )


def output_row(r: dict, questions: list[str], after: Case, initial: Case) -> dict:
    return {
        "case_id": r["case_id"],
        "gene": r["gene"],
        "gene_index": r["gene_index"],
        "split": r["split"],
        "present": list(after.present),
        "excluded": list(after.excluded),
        "sex": r["sex"],
        "age_years": r["age_years"],
        "onset_years": r["onset_years"],
        "questions": questions,
        "yes": len(set(after.present) - set(initial.present)),
        "no": len(after.excluded),
    }


_WORKER: dict = {}


def _init_worker(kb_path: str, n_candidates: int, n_questions: int) -> None:
    from diagnostic_ar_training.lineage.registry import Purpose, open_source
    from diagnostic_ar_training.ontology import Ontology
    from diagnostic_ar_training.rerank import kb
    from diagnostic_ar_training.rerank.features import GeneKnowledge
    from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

    ontology = Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
    _WORKER.update(
        ontology=ontology,
        knowledge=GeneKnowledge(kb.read(Path(kb_path)), ontology),
        e0=GenPheniaV3(),
        n_candidates=n_candidates,
        n_questions=n_questions,
    )


def interview_record(r: dict) -> tuple[dict, dict]:
    """One source record -> (output row, E0's rank of the true gene before and after the answers)."""
    from diagnostic_ar_training.eval import s3_run

    w = _WORKER
    initial = initial_case(r)
    [done] = s3_run.interview_cases(
        [(initial, frozenset(r["true_present"]))],
        w["e0"],
        w["knowledge"],
        w["ontology"],
        w["n_candidates"],
        w["n_questions"],
    )
    after_probs = w["e0"].score(done.after).probs
    ranks = {
        "initial": s3_run.rank(done.initial_probs, w["e0"].genes, r["gene"]),
        "answers": s3_run.rank(after_probs, w["e0"].genes, r["gene"]),
    }
    return output_row(r, done.questions, done.after, initial), ranks


def interview_parallel(
    records: list[dict], kb_path: Path, n_candidates: int, n_questions: int, workers: int, chunksize: int = 32
) -> list[tuple[dict, dict]]:
    """In input order; each worker loads its own E0 session, ontology and KB."""
    ctx = multiprocessing.get_context("fork")
    with ctx.Pool(workers, _init_worker, (str(kb_path), n_candidates, n_questions)) as pool:
        return list(pool.imap(interview_record, records, chunksize))


def write_rows(path: Path, rows: Iterable[dict]) -> None:
    """Deterministic gzip JSONL: no name or mtime in the header, sorted keys, compact separators."""
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0) as handle:
        for row in rows:
            handle.write((json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode())
    path.write_bytes(buffer.getvalue())


def contamination(
    rows: list[dict], cohorts: dict[str, set[tuple[str, frozenset[str]]]]
) -> dict[str, list[str]]:
    """Per cohort, the ids of interviewed cases whose (gene, present set) equals one of the cohort's keys."""
    return {
        name: [r["case_id"] for r in rows if overlap_key(r["gene"], r["present"]) in keys]
        for name, keys in cohorts.items()
    }


def mrr(ranks: Iterable[float]) -> float:
    ranks = list(ranks)
    return sum(0.0 if math.isinf(r) else 1.0 / r for r in ranks) / max(len(ranks), 1)
