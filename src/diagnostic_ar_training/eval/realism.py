"""Realism of a simulated dataset: the ANALYSIS-001 metrics and the ADR-0012 G2 gate metrics.

- G2a: literature panel, simulated emission (ancestor closure of the reported terms) vs
  literature prevalence;
- G2b: mean per-gene Spearman of term frequencies vs R1-dev (genes with >= 10 dev patients);
- G2c: Wasserstein-1 distance of terms per case to R1-train;
- G2d: classifier two-sample test against R1-train on source-neutral features;
- G2e: |E0 MRR on the dataset - E0 in-vocab MRR on R1-train|.

R1-dev is read here only as a check (ADR-0011, ADR-0012). Nothing in this module fits a
simulator parameter.
"""

import csv
import gzip
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from diagnostic_ar_training.ontology import PHENOTYPIC_ABNORMALITY, Ontology

MIN_DEV_PATIENTS = 10
FREQUENCY_BINS = ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0001))
E0_TARGET_MRR = 0.512
C2ST_MAX_AUC = 0.75
E0_MAX_GAP = 0.10


@dataclass(frozen=True)
class SimCase:
    case_id: str
    gene: str
    present: tuple[str, ...]
    excluded: tuple[str, ...] | None
    """None when the generator never produces negations (UP)."""
    sex: str = "unknown"


def load_export(path: Path) -> list[SimCase]:
    """rare-disease-simulator export (JSON lines, gzip)."""
    out = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            r = json.loads(line)
            out.append(
                SimCase(
                    r["case_id"],
                    r["gene"],
                    tuple(r["present"]),
                    tuple(r.get("excluded") or ()),
                    r.get("sex") or "unknown",
                )
            )
    return out


def load_graphens(path: Path) -> list[SimCase]:
    """GraPhens' simulator output: {gene: [[HPO ids], ...]}; present terms only."""
    data = json.loads(Path(path).read_text())
    out = []
    for gene in sorted(data):
        if gene == "-":
            continue
        for i, terms in enumerate(data[gene]):
            if terms and all(t.startswith("HP:") for t in terms):
                out.append(SimCase(f"up:{gene}:{i}", gene, tuple(sorted(set(terms))), None))
    return out


class Closure:
    """Reported terms plus every ancestor; ids resolved to current HPO."""

    def __init__(self, ontology: Ontology) -> None:
        self.ontology = ontology
        self._cache: dict[str, frozenset[str]] = {}

    def term(self, t: str) -> frozenset[str]:
        if t not in self._cache:
            r = self.ontology.resolve(t)
            self._cache[t] = frozenset({r, *self.ontology.ancestors(r)}) if r else frozenset()
        return self._cache[t]

    def __call__(self, terms: Iterable[str]) -> set[str]:
        out: set[str] = set()
        for t in terms:
            out |= self.term(t)
        return out


def spearman(a, b) -> float:
    from scipy.stats import spearmanr

    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if len(a) < 3 or np.ptp(a) == 0 or np.ptp(b) == 0:
        return float("nan")
    return float(spearmanr(a, b).statistic)


def rates(closures: list[set[str]], universe: Iterable[str]) -> dict[str, float]:
    counts: Counter = Counter()
    for c in closures:
        counts.update(c)
    return {t: counts[t] / len(closures) for t in universe}


def per_gene_rho(
    dev_by_gene: dict[str, list[set[str]]],
    sim_by_gene: dict[str, list[set[str]]],
    universe: Callable[[str], set[str]],
    min_patients: int = MIN_DEV_PATIENTS,
) -> dict:
    """G2b: Spearman(real rate, simulated rate) over each gene's annotated terms, averaged over genes."""
    per_gene = {}
    missing = []
    for gene, real in sorted(dev_by_gene.items()):
        if len(real) < min_patients:
            continue
        if not sim_by_gene.get(gene):
            missing.append(gene)
            continue
        terms = sorted(universe(gene))
        fr, fs = rates(real, terms), rates(sim_by_gene[gene], terms)
        per_gene[gene] = {
            "dev_patients": len(real),
            "sim_cases": len(sim_by_gene[gene]),
            "terms": len(terms),
            "rho": spearman([fr[t] for t in terms], [fs[t] for t in terms]),
        }
    values = [g["rho"] for g in per_gene.values() if not math.isnan(g["rho"])]
    return {
        "min_dev_patients": min_patients,
        "genes_eligible": len(per_gene) + len(missing),
        "genes_scored": len(values),
        "genes_missing_from_dataset": missing,
        "mean_rho": float(np.mean(values)) if values else None,
        "per_gene": per_gene,
    }


def distribution(values: list[int]) -> dict:
    arr = np.asarray(values, dtype=float)
    return {
        "n": int(arr.size),
        "mean": float(arr.mean()),
        "percentiles": {str(p): float(np.percentile(arr, p)) for p in (10, 25, 50, 75, 90)},
    }


def wasserstein(a: list[int], b: list[int]) -> float:
    from scipy.stats import wasserstein_distance

    return float(wasserstein_distance(a, b))


def frequency_calibration(
    dev_by_gene: dict[str, list[set[str]]],
    sim_by_gene: dict[str, list[set[str]]],
    gene_terms: Callable[[str], dict[str, float | None]],
    min_patients: int = 5,
) -> dict:
    """HPOA frequency bin -> mean real (R1-dev) and simulated reporting rate over the same (gene, term)s."""
    acc: dict[str, list[list[float]]] = defaultdict(lambda: [[], []])
    genes = 0
    for gene, real in dev_by_gene.items():
        if len(real) < min_patients or not sim_by_gene.get(gene):
            continue
        terms = gene_terms(gene)
        if not terms:
            continue
        genes += 1
        fr, fs = rates(real, terms), rates(sim_by_gene[gene], terms)
        for t, f in terms.items():
            label = (
                "unknown"
                if f is None
                else next(f"{lo:.1f}-{min(hi, 1):.1f}" for lo, hi in FREQUENCY_BINS if f < hi)
            )
            acc[label][0].append(fr[t])
            acc[label][1].append(fs[t])
    order = [f"{lo:.1f}-{min(hi, 1):.1f}" for lo, hi in FREQUENCY_BINS] + ["unknown"]
    return {
        "genes": genes,
        "min_dev_patients": min_patients,
        "bins": [
            {"hpoa_frequency": b, "pairs": len(acc[b][0]), "real_rate": float(np.mean(acc[b][0])),
             "sim_rate": float(np.mean(acc[b][1]))}
            for b in order if acc[b][0]
        ],
    }  # fmt: skip


PANEL_ALIASES = {
    "hpo_id": ("hpo_id", "suggested_hpo_id"),
    "prevalence": ("literature_prevalence", "prevalence"),
}


def read_panel(path: Path) -> tuple[list[dict], bool]:
    """(rows with gene, hpo_id, prevalence, sex, source_kind, label; whether source_kind was present)."""
    with Path(path).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader((line for line in handle if not line.startswith("#")), delimiter="\t")
        raw = list(reader)
        fields = set(reader.fieldnames or ())
    has_kind = "source_kind" in fields
    out = []
    for r in raw:
        pick = {k: next((r[a] for a in aliases if r.get(a)), "") for k, aliases in PANEL_ALIASES.items()}
        out.append(
            {
                "gene": r["gene"],
                "label": r.get("feature_label", ""),
                "hpo_id": pick["hpo_id"],
                "prevalence": float(pick["prevalence"]),
                "sex": (r.get("sex") or "").strip().lower(),
                "source_kind": (r.get("source_kind") or "").strip().lower(),
            }
        )
    return out, has_kind


def panel_errors(
    rows: list[dict], sim: dict[str, list[SimCase]], closure: Closure, has_source_kind: bool
) -> dict:
    """G2a. Primary: rows not sourced from Orphanet; secondary: all rows."""
    if not has_source_kind:
        print(
            "warning: panel has no source_kind column; every row is treated as independent", file=sys.stderr
        )
    scored = []
    for r in rows:
        cases = [c for c in sim.get(r["gene"], []) if not r["sex"] or c.sex == r["sex"]]
        term = closure.ontology.resolve(r["hpo_id"])
        if not cases or term is None:
            scored.append({**r, "sim_cases": len(cases), "emission": None, "abs_error": None})
            continue
        emission = sum(term in closure(c.present) for c in cases) / len(cases)
        scored.append(
            {**r, "sim_cases": len(cases), "emission": emission, "abs_error": abs(emission - r["prevalence"])}
        )

    def mae(subset):
        errs = [s["abs_error"] for s in subset if s["abs_error"] is not None]
        return {"rows": len(subset), "rows_scored": len(errs), "mae": float(np.mean(errs)) if errs else None}

    independent = [s for s in scored if s["source_kind"] != "orphanet"]
    return {
        "source_kind_column": has_source_kind,
        "primary": {"rows": "source_kind != orphanet", **mae(independent)},
        "all_rows": mae(scored),
        "per_row": scored,
    }


# --- G2d: classifier two-sample test --------------------------------------------------------------


class CaseFeatures:
    """Source-neutral features of one case's present terms (ADR-0012 G2d)."""

    def __init__(self, ontology: Ontology, annotation_counts: Counter, n_diseases: int, knowledge) -> None:
        self.ontology = ontology
        self.systems = sorted(
            t for t, ps in ((t, ontology.parents(t)) for t in ontology.labels) if PHENOTYPIC_ABNORMALITY in ps
        )
        self.annotation_counts = annotation_counts
        self.n_diseases = n_diseases
        self.knowledge = knowledge
        self._depth: dict[str, int] = {}
        self._direct: dict[str, set[str]] = {}

    def depth(self, t: str) -> int:
        if t not in self._depth:
            ps = self.ontology.parents(t)
            self._depth[t] = 0 if not ps else 1 + min(self.depth(p) for p in ps)
        return self._depth[t]

    def direct_terms(self, gene: str) -> set[str]:
        if gene not in self._direct:
            kb = self.knowledge.kb["diseases"]
            self._direct[gene] = {t for d in self.knowledge.diseases(gene) for t in kb[d]["phenotypes"]}
        return self._direct[gene]

    def names(self) -> list[str]:
        return [
            "term_count", "log_term_count", "mean_ic", "mean_depth",
            "annotated_share", "noise_share", *[f"system:{s}" for s in self.systems], "system:other",
        ]  # fmt: skip

    def __call__(self, gene: str, present: Iterable[str]) -> list[float]:
        terms = [r for t in present if (r := self.ontology.resolve(t))]
        n = len(terms)
        if not n:
            return [0.0] * len(self.names())
        ic = [-math.log((self.annotation_counts.get(t, 0) + 1) / (self.n_diseases + 1)) for t in terms]
        direct = self.direct_terms(gene)
        annotated = sum(t in direct for t in terms) / n
        noise = sum(self.knowledge.term_probability(gene, t) == 0 for t in terms) / n
        hist = Counter()
        for t in terms:
            under = [s for s in self.systems if self.ontology.is_a(t, s)]
            hist.update(under or ["other"])
        return [
            float(n), math.log(n), float(np.mean(ic)), float(np.mean([self.depth(t) for t in terms])),
            annotated, noise, *[hist[s] / n for s in self.systems], hist["other"] / n,
        ]  # fmt: skip


def _fold_of(key: str, folds: int, salt: str) -> int:
    return int(hashlib.sha256(f"{salt}:{key}".encode()).hexdigest(), 16) % folds


def matched_pairs(
    real: list[tuple[str, str]], sim_by_gene: dict[str, list[int]], n_sim: int, seed: int
) -> list[tuple[int, int]]:
    """(real index, sim index) pairs: a simulated case of the same gene when one is left, else any unused one.

    `real` is (case id, gene) per real patient; each simulated case is used once.
    """
    rng = np.random.default_rng(seed)
    pools = {g: list(rng.permutation(idx)) for g, idx in sorted(sim_by_gene.items())}
    used: set[int] = set()
    pairs, unmatched = [], []
    for i in rng.permutation(len(real)):
        pool = pools.get(real[i][1], [])
        while pool and pool[-1] in used:
            pool.pop()
        if pool:
            j = int(pool.pop())
            used.add(j)
            pairs.append((int(i), j))
        else:
            unmatched.append(int(i))
    free = [j for j in rng.permutation(n_sim) if j not in used]
    for i, j in zip(unmatched, free, strict=False):
        pairs.append((i, int(j)))
    return sorted(pairs)


def _expand(X: np.ndarray, n_scalar: int) -> np.ndarray:
    """Adds squares of the scalar features so the logistic classifier can bend."""
    return np.hstack([X, X[:, :n_scalar] ** 2])


def c2st(
    X_real: np.ndarray,
    X_sim: np.ndarray,
    groups: list[str],
    pairs: list[tuple[int, int]],
    n_scalar: int,
    folds: int = 5,
    seed: int = 0,
    n_boot: int = 1000,
) -> dict:
    """Out-of-fold AUC of real (1) vs simulated (0), folds by the real patient's publication group.

    Each simulated case sits in the fold of the real patient it is paired with; the CI
    resamples publication groups (with their paired simulated cases).
    """
    from diagnostic_ar_training.knowledge.report_model import auc, fit, logit

    fold = np.asarray([_fold_of(groups[i], folds, "c2st") for i, _ in pairs])
    X = _expand(np.vstack([X_real[[i for i, _ in pairs]], X_sim[[j for _, j in pairs]]]), n_scalar)
    y = np.r_[np.ones(len(pairs)), np.zeros(len(pairs))]
    f = np.r_[fold, fold]
    columns = tuple(range(X.shape[1]))
    score = np.zeros(len(y))
    for k in range(folds):
        train, test = f != k, f == k
        if not test.any():
            continue
        model = fit(X[train], y[train], columns)
        score[test] = logit(model, X[test], columns)
    value = auc(y, score)
    rng = np.random.default_rng(seed)
    pair_groups = np.asarray([groups[i] for i, _ in pairs])
    unique = np.unique(pair_groups)
    members = {g: np.nonzero(pair_groups == g)[0] for g in unique}
    boots = []
    for _ in range(n_boot):
        chosen = np.concatenate([members[g] for g in rng.choice(unique, size=len(unique))])
        idx = np.r_[chosen, chosen + len(pairs)]
        boots.append(auc(y[idx], score[idx]))
    return {
        "auc": value,
        "ci95": [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))],
        "pairs": len(pairs),
        "folds": folds,
        "ci_resample_unit": "publication",
        "classifier": "logistic regression on standardised features + squares of the scalar features",
    }


# --- G2e ------------------------------------------------------------------------------------------


def subsample(cases: list, n: int, seed: int) -> list:
    if len(cases) <= n:
        return list(cases)
    idx = np.random.default_rng(seed).choice(len(cases), size=n, replace=False)
    return [cases[i] for i in sorted(idx)]


def e0_difficulty(system, cases: list[SimCase], target: float = E0_TARGET_MRR) -> dict:
    from diagnostic_ar_training.cohorts.schema import Case
    from diagnostic_ar_training.eval import harness

    as_cases = [Case(case_id=c.case_id, cohort="sim", gene=c.gene, present=c.present) for c in cases]
    records = harness.run(system, as_cases, view="present")
    summary = harness.summarize(records)
    in_vocab = summary.get("gene_in_vocab", {}).get("mrr")
    return {
        "cases": len(cases),
        "mrr": summary["all"]["mrr"],
        "mrr_in_vocab": in_vocab,
        "gene_not_in_vocab": summary["coverage"]["gene_not_in_vocab"],
        "unscorable": summary["coverage"]["unscorable"],
        "target_mrr": target,
        "gap": None if in_vocab is None else abs(in_vocab - target),
    }


# --- Gate table -----------------------------------------------------------------------------------

G2 = {
    "a": ("literature panel MAE (primary rows)", "lower"),
    "b": ("R1-dev mean per-gene rho", "higher"),
    "c": ("W1 terms/case vs R1-train", "lower"),
    "d": ("C2ST AUC vs R1-train", "lower"),
    "e": ("|E0 MRR - 0.512|", "lower"),
}


def g2_values(report: dict) -> dict[str, float | None]:
    return {
        "a": report["g2a_panel"]["primary"]["mae"],
        "b": report["g2b_dev_rho"]["mean_rho"],
        "c": report["g2c_terms_per_case"]["present"]["w1_vs_r1_train"],
        "d": report["g2d_c2st"]["auc"] if report.get("g2d_c2st") else None,
        "e": report["g2e_e0"]["gap"] if report.get("g2e_e0") else None,
    }


def gate(baselines: dict[str, dict], candidates: dict[str, dict]) -> dict:
    """Pass/fail per G2 criterion for each candidate against every baseline (ADR-0012)."""
    base_values = {label: g2_values(r) for label, r in baselines.items()}
    table = {"baselines": base_values, "candidates": {}}
    for label, report in candidates.items():
        values = g2_values(report)
        verdict = {}
        for k, (_, direction) in G2.items():
            v = values[k]
            others = [b[k] for b in base_values.values()]
            if v is None or any(o is None for o in others):
                verdict[k] = None
                continue
            ok = all(v < o for o in others) if direction == "lower" else all(v > o for o in others)
            if k == "d":
                ok = ok and v <= C2ST_MAX_AUC
            if k == "e":
                ok = ok and v <= E0_MAX_GAP
            verdict[k] = ok
        table["candidates"][label] = {"values": values, "pass": verdict, "all_pass": all(verdict.values())}
    return table


def gate_markdown(table: dict) -> str:
    def fmt(v):
        return "n/a" if v is None else f"{v:.3f}"

    head = (
        "| Dataset | Role | " + " | ".join(f"G2{k}: {name} ({d})" for k, (name, d) in G2.items()) + " | All |"
    )
    lines = [head, "|" + "---|" * (len(G2) + 3)]
    for label, values in table["baselines"].items():
        lines.append(f"| {label} | baseline | " + " | ".join(fmt(values[k]) for k in G2) + " | — |")
    for label, row in table["candidates"].items():
        cells = []
        for k in G2:
            ok = row["pass"][k]
            cells.append(f"{fmt(row['values'][k])} {'pass' if ok else ('fail' if ok is False else 'n/a')}")
        lines.append(
            f"| {label} | candidate | " + " | ".join(cells) + f" | {'PASS' if row['all_pass'] else 'FAIL'} |"
        )
    notes = [
        "",
        f"G2d also requires AUC <= {C2ST_MAX_AUC}; G2e also requires a gap <= {E0_MAX_GAP} (ADR-0012).",
    ]
    return "\n".join(lines + notes) + "\n"
