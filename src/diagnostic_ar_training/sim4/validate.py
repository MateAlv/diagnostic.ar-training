"""Realism of sim4 presets on a held-out fold: simulated cases with the evaluation patients' gene mix.

Reuses eval/realism.py (C2ST, CaseFeatures, per-gene rho). The fold given here is never used to fit.
"""

import math
from collections import Counter
from dataclasses import dataclass

import numpy as np

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.eval import realism as RZ
from diagnostic_ar_training.sim4.config import CATEGORIES, SimConfig
from diagnostic_ar_training.sim4.fit import UNCITED, FittedParams, Profiler
from diagnostic_ar_training.sim4.knowledge import Knowledge
from diagnostic_ar_training.sim4.sampler import Sampler

EXPLAINED_BINS = ((0.0, 0.25, "<25%"), (0.25, 0.5, "25-50%"), (0.5, 0.75, "50-75%"), (0.75, 1.01, ">=75%"))
PLACES = (*CATEGORIES, "off")
N_SCALAR_FEATURES = 6


def explained_bin(share: float) -> int:
    return next(i for i, (lo, hi, _) in enumerate(EXPLAINED_BINS) if lo <= share < hi)


class FeatureKnowledge:
    """The knowledge interface CaseFeatures expects, over sim4's entities."""

    def __init__(self, kb: Knowledge, profiler: Profiler) -> None:
        self.kb = {"diseases": {e.id: {"phenotypes": e.terms} for ents in kb.entities.values() for e in ents}}
        self._genes = {g: [e.id for e in ents] for g, ents in kb.entities.items()}
        self.profiler = profiler

    def diseases(self, gene: str) -> list[str]:
        return self._genes.get(gene, [])

    def term_probability(self, gene: str, term: str) -> float:
        return 0.0 if self.profiler.place(gene, term)[0] == "off" else 1.0


@dataclass
class Described:
    k: list[int]
    explained: list[float]
    places: Counter


def describe(profiler: Profiler, cases: list[tuple[str, tuple[str, ...]]]) -> Described:
    places: Counter = Counter()
    for gene, terms in cases:
        places.update(profiler.place(gene, t)[0] for t in terms)
    return Described([len(t) for _, t in cases], [profiler.explained_share(g, t) for g, t in cases], places)


def _bins(values: list[float]) -> list[float]:
    counts = Counter(explained_bin(v) for v in values)
    return [counts[i] / len(values) for i in range(len(EXPLAINED_BINS))]


def _bin_w1(a: list[float], b: list[float]) -> float:
    width = 0.25
    return float(sum(abs(x - y) for x, y in zip(np.cumsum(a), np.cumsum(b), strict=True)) * width)


def _shares(places: Counter) -> dict[str, float]:
    total = sum(places.values())
    return {p: places[p] / total for p in PLACES}


def _summary(real: Described, sim: Described) -> dict:
    rs, ss = _shares(real.places), _shares(sim.places)
    rb, sb = _bins(real.explained), _bins(sim.explained)
    return {
        "terms_per_case": {"real_mean": float(np.mean(real.k)), "sim_mean": float(np.mean(sim.k))},
        "w1_terms_per_case": RZ.wasserstein(real.k, sim.k),
        "explained_bins": {"labels": [b[2] for b in EXPLAINED_BINS], "real": rb, "sim": sb},
        "w1_explained_bins": _bin_w1(rb, sb),
        "category_shares": {"real": rs, "sim": ss},
        "category_tv": 0.5 * sum(abs(rs[p] - ss[p]) for p in PLACES),
    }


def _mrr_by_bin(records: list[dict], explained: list[float]) -> dict:
    rr = [0.0 if math.isinf(r["rank"]) else 1.0 / r["rank"] for r in records]
    out = {"all": {"n": len(rr), "mrr": float(np.mean(rr))}}
    for i, (_, _, label) in enumerate(EXPLAINED_BINS):
        sel = [x for x, e in zip(rr, explained, strict=True) if explained_bin(e) == i]
        out[label] = {"n": len(sel), "mrr": float(np.mean(sel)) if sel else None}
    return out


def _e0_records(system, gene_terms: list[tuple[str, tuple[str, ...]]], prefix: str) -> list[dict]:
    from diagnostic_ar_training.eval import harness

    cases = [
        Case(case_id=f"{prefix}:{i}", cohort="sim4", gene=g, present=t) for i, (g, t) in enumerate(gene_terms)
    ]
    return harness.run(system, cases, view="present")


def validate(
    kb: Knowledge,
    params: FittedParams,
    configs: dict[str, SimConfig],
    fit_cases: list[Case],
    eval_cases: list[Case],
    groups: dict[str, str],
    group_status: dict[str, str],
    *,
    uncited_only: bool = True,
    reps: int = 5,
    rho_sims: int = 50,
    min_rho_patients: int = 5,
    seed: int = 0,
    e0_system=None,
) -> dict:
    profiler = Profiler(kb)
    simulable = set(kb.simulable_genes)

    def real_of(cases):
        out = []
        for c in cases:
            if uncited_only and group_status[groups[c.case_id]] != UNCITED:
                continue
            terms = profiler.prepare(c.present)
            if c.gene in simulable and terms:
                out.append((c, terms))
        return out

    real = real_of(eval_cases)
    fitted = real_of(fit_cases)
    real_gt = [(c.gene, t) for c, t in real]
    real_desc = describe(profiler, real_gt)
    features = RZ.CaseFeatures(kb.ontology, kb.disease_counts, kb.n_diseases, FeatureKnowledge(kb, profiler))
    X_real = np.asarray([features(g, t) for g, t in real_gt])
    real_groups = [groups[c.case_id] for c, _ in real]
    closure = RZ.Closure(kb.ontology)

    eval_by_gene: dict[str, list[set[str]]] = {}
    fit_by_gene: dict[str, list[set[str]]] = {}
    for c, t in real:
        eval_by_gene.setdefault(c.gene, []).append(closure(t))
    for c, t in fitted:
        fit_by_gene.setdefault(c.gene, []).append(closure(t))
    rho_genes = sorted(
        g
        for g in eval_by_gene
        if len(eval_by_gene[g]) >= min_rho_patients and len(fit_by_gene.get(g, ())) >= min_rho_patients
    )
    sub = np.random.default_rng(seed)
    fit_matched = {
        g: [
            fit_by_gene[g][i]
            for i in sorted(sub.choice(len(fit_by_gene[g]), len(eval_by_gene[g]), replace=False))
        ]
        if len(fit_by_gene[g]) > len(eval_by_gene[g])
        else fit_by_gene[g]
        for g in rho_genes
    }

    report = {
        "eval_patients": len(real),
        "eval_publications": len(set(real_groups)),
        "fit_patients": len(fitted),
        "uncited_only": uncited_only,
        "reps": reps,
        "seed": seed,
        "params_hash": params.params_hash(),
        "rho": {"min_patients": min_rho_patients, "genes": rho_genes, "sims_per_gene": rho_sims},
        "real": {
            "terms_per_case_mean": float(np.mean(real_desc.k)),
            "explained_bins": _bins(real_desc.explained),
            "category_shares": _shares(real_desc.places),
        },
        "configs": {},
    }
    if e0_system is not None:
        report["real"]["e0_mrr"] = _mrr_by_bin(_e0_records(e0_system, real_gt, "real"), real_desc.explained)

    for n, (name, cfg) in enumerate(configs.items()):
        sampler = Sampler(kb, params, cfg)
        rng = np.random.default_rng([seed, n])
        sims = [[sampler.sample(kb.gene_index[c.gene], rng) for _ in range(reps)] for c, _ in real]
        sim_gt = [(c.gene, tuple(s)) for (c, _), reps_ in zip(real, sims, strict=True) for s in reps_]
        first = [(c.gene, tuple(r[0])) for (c, _), r in zip(real, sims, strict=True)]
        row = {
            "config": cfg.as_dict(),
            "config_hash": cfg.config_hash(),
            **_summary(real_desc, describe(profiler, sim_gt)),
        }

        X_sim = np.asarray([features(g, t) for g, t in first])
        sim_by_gene: dict[str, list[int]] = {}
        for j, (g, _) in enumerate(first):
            sim_by_gene.setdefault(g, []).append(j)
        pairs = RZ.matched_pairs([(c.case_id, c.gene) for c, _ in real], sim_by_gene, len(first), seed)
        row["c2st"] = RZ.c2st(X_real, X_sim, real_groups, pairs, N_SCALAR_FEATURES, seed=seed, n_boot=300)

        rho_sim = {
            g: [closure(sampler.sample(kb.gene_index[g], rng)) for _ in range(rho_sims)] for g in rho_genes
        }

        def universe(g):
            return kb.profile(g)

        r_eval = RZ.per_gene_rho({g: eval_by_gene[g] for g in rho_genes}, rho_sim, universe, min_rho_patients)
        r_fit = RZ.per_gene_rho(fit_matched, rho_sim, universe, min_rho_patients)
        row["per_gene_rho"] = {
            "eval_fold": r_eval["mean_rho"],
            "fit_folds_matched_n": r_fit["mean_rho"],
            "genes_scored": r_eval["genes_scored"],
            **_gap(r_fit["per_gene"], r_eval["per_gene"], seed),
        }
        if e0_system is not None:
            first_desc = describe(profiler, first)
            row["e0_mrr"] = _mrr_by_bin(_e0_records(e0_system, first, name), first_desc.explained)
        report["configs"][name] = row
    return report


def _gap(fit: dict, held: dict, seed: int, n_boot: int = 2000) -> dict:
    """Mean per-gene (fit-fold rho - eval-fold rho) over genes scored in both, with a gene-bootstrap CI."""
    diffs = np.asarray(
        [
            fit[g]["rho"] - held[g]["rho"]
            for g in sorted(set(fit) & set(held))
            if not (math.isnan(fit[g]["rho"]) or math.isnan(held[g]["rho"]))
        ]
    )
    if not len(diffs):
        return {"gap_fit_minus_eval": None, "gap_ci95": None}
    rng = np.random.default_rng(seed)
    boots = [float(np.mean(rng.choice(diffs, len(diffs)))) for _ in range(n_boot)]
    return {
        "gap_fit_minus_eval": float(np.mean(diffs)),
        "gap_ci95": [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))],
        "gap_genes": len(diffs),
    }


def _f(v, digits: int = 3) -> str:
    return "n/a" if v is None else f"{v:.{digits}f}"


def _ci(ci) -> str:
    return "" if ci is None else f"[{_f(ci[0])}, {_f(ci[1])}]"


def markdown(report: dict) -> str:
    labels = [b[2] for b in EXPLAINED_BINS]
    real = report["real"]
    lines = [
        "| Preset | Terms/case | W1 terms | Explained bins "
        + "/".join(labels)
        + " | W1 explained | Category TV "
        "| Off share | C2ST AUC [95% CI] | Per-gene rho eval | rho fit (matched n) | Gap [95% CI] |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
        f"| real (eval fold) | {_f(real['terms_per_case_mean'], 2)} | — | "
        + "/".join(_f(x, 2) for x in real["explained_bins"])
        + f" | — | — | {_f(real['category_shares']['off'])} | — | — | — | — |",
    ]
    for name, r in report["configs"].items():
        c2 = r["c2st"]
        rho = r["per_gene_rho"]
        lines.append(
            f"| {name} | {_f(r['terms_per_case']['sim_mean'], 2)} | {_f(r['w1_terms_per_case'], 2)} | "
            + "/".join(_f(x, 2) for x in r["explained_bins"]["sim"])
            + f" | {_f(r['w1_explained_bins'])} | {_f(r['category_tv'])} | "
            f"{_f(r['category_shares']['sim']['off'])} | "
            f"{_f(c2['auc'])} [{_f(c2['ci95'][0])}, {_f(c2['ci95'][1])}] | {_f(rho['eval_fold'])} | "
            f"{_f(rho['fit_folds_matched_n'])} | {_f(rho['gap_fit_minus_eval'])} {_ci(rho['gap_ci95'])} |"
        )
    if "e0_mrr" in real:
        lines += [
            "",
            "| E0 MRR | all | " + " | ".join(labels) + " |",
            "|---|---|" + "---|" * len(labels),
        ]

        def cells(m):
            return " | ".join(f"{_f(m[k]['mrr'])} (n={m[k]['n']})" for k in ("all", *labels))

        lines.append(f"| real (eval fold) | {cells(real['e0_mrr'])} |")
        for name, r in report["configs"].items():
            lines.append(f"| {name} | {cells(r['e0_mrr'])} |")
    return "\n".join(lines) + "\n"
