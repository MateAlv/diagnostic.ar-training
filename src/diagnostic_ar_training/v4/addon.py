"""The re-rank add-on of the claimed v4 (ADR-0019 amendment 2026-10-15, PHASE3 §2f): ft-v1.1's residual on the
network's gene logits.

scores = logits_base + r, r_g = Σ_k w_k · c_k(patient, g), w = −max(θ, 0): `ft/`'s features, residual, recipe
and bundle format (`ft-v1-bundle/2`, ADR-0018), unchanged. It has no per-gene parameter and can only lower a
gene's score. It reads sex, age, onset and excluded terms (`patients.load_addon`); the network never does
(`network_view`).

- **Knowledge** (`build_kb`, `ft-kb/2`): `ft.knowledge.build` on E0's knowledge only, unmasked (Phase 3 reads
  the "uncited by E0's knowledge" stratum instead of masking):
  - HPOA 2025-03-03: phenotypes, onset, inheritance, obligate phenotypes, disease names. Zero-frequency rows
    are dropped from the profiles and NOT rows are never read (ADR-0019 §4);
  - E0's gene list and gene -> disease links (`e0_genes_to_phenotype`, GraPhens@7aef83d);
  - the 2025-03-03 ontology, for the ancestors of the obligate phenotypes;
  - `neg_embed` reads E0's own frozen term embeddings.

  Orphanet onsets, HGNC locations and Phase 2's curation overrides are not read.
- **Fitting** (`fit`): ft-v1.1's recipe (`c1-lin-all`, seeds 0-2, the mean of their residuals), optionally
  on a subset of the features; early stopping on the held-out publication groups of the fitting patients
  (`ft.configs.inner_split`).
- **Scoring** (`Addon`): base logits + the bundle's residual; with θ = 0 or no patient input it returns the
  base logits exactly. Ranks are pessimistic (ties count against the true gene) on the network's logits as
  `v4.evaluate`, and on the softmax for E0 as `eval.harness`.
"""

import csv
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path

import numpy as np

from diagnostic_ar_training import INTERIM_DIR
from diagnostic_ar_training.ft import configs
from diagnostic_ar_training.ft import knowledge as ft_knowledge
from diagnostic_ar_training.ft.bundle import (
    COVARIATES,
    FEATURE_GROUPS,
    FEATURES,
    FORMAT,
    FtResidual,
    Knowledge,
    covariates,
    softmax64,
)
from diagnostic_ar_training.ft.system import case_inputs
from diagnostic_ar_training.lineage.registry import LineageError, Purpose, open_source
from diagnostic_ar_training.safe import knowledge as safe_knowledge
from diagnostic_ar_training.v4 import patients, report
from diagnostic_ar_training.v4.knowledge import is_negation

KB_SOURCES = {
    "annotations": "hpo_annotations_2025_03_03",
    "ontology": "hpo_ontology_2025_03_03",
    "genes": "e0_genes_to_phenotype",
}
CONFIG = "c1-lin-all"
SEEDS = configs.SEEDS
FEATURE_SETS = {
    "sex-age-onset": tuple(f for f in FEATURES if f in FEATURE_GROUPS["sex"] + FEATURE_GROUPS["age"]),
    "all": FEATURES,
}
STRATA = ("uncited", "uncited_in_vocab", "cited")
ADDON_DIR = INTERIM_DIR / "p3-addon"
KB_FILE = "ft-kb.json.gz"
BUNDLE_FILE = "ft-v1-bundle.json"
KB_KIND, BUNDLE_KIND = "addon-kb", "addon-bundle"


def genes_to_disease(path: Path) -> dict[str, set[str]]:
    """Gene -> its disease ids in E0's `genes_to_phenotype.txt` (rows without a disease id are skipped)."""
    out: dict[str, set[str]] = {}
    with Path(path).open(encoding="utf-8", newline="") as handle:
        for r in csv.DictReader(handle, delimiter="\t"):
            if r["disease_id"]:
                out.setdefault(r["gene_symbol"], set()).add(r["disease_id"])
    return out


def annotations(path: Path) -> safe_knowledge.Annotations:
    """`phenotype.hpoa` unmasked, without NOT rows (as `safe.knowledge`) and without zero-frequency rows."""
    ann = safe_knowledge.read_annotations(path, ())
    for disease, rows in ann.phenotypes.items():
        kept = [(t, f) for t, f in rows if not is_negation("", f)]
        ann.stats["rows_dropped_zero_frequency"] += len(rows) - len(kept)
        ann.phenotypes[disease] = kept
    return ann


def build_kb(
    genes: Iterable[str],
    hpoa: Path,
    e0_genes_to_phenotype: Path,
    ancestors: Callable[[str], Iterable[str]],
) -> tuple[dict, dict]:
    """(kb, stats): an `ft-kb/2` document from E0's knowledge only (no Orphanet, HGNC or overrides)."""
    return ft_knowledge.build(
        genes, genes_to_disease(e0_genes_to_phenotype), annotations(hpoa), {}, {}, ancestors, ()
    )


def kb_from_sources(genes: Iterable[str]) -> tuple[dict, dict, list[str]]:
    """(kb, stats, the source names read), opening only `KB_SOURCES` through the registry."""
    from diagnostic_ar_training.ontology import Ontology

    paths = {k: open_source(name, Purpose.KB) for k, name in KB_SOURCES.items()}
    ontology = Ontology.from_json(paths["ontology"])
    kb, stats = build_kb(genes, paths["annotations"], paths["genes"], ontology.ancestors)
    return kb, stats, list(KB_SOURCES.values())


def _verified_output(artifact_id: str, kind: str, name: str) -> tuple[Path, str]:
    from diagnostic_ar_training.lineage import manifest

    m = manifest.load_manifest(artifact_id)
    problems = manifest.verify_outputs(m)
    if m.kind != kind or problems:
        raise LineageError(f"{artifact_id}: not a verified {kind} (kind {m.kind!r}; {problems})")
    out = next((o for o in m.outputs if o.path.endswith(name)), None)
    if out is None:
        raise LineageError(f"{artifact_id} has no output named {name}")
    return manifest.output_path(out), out.sha256


def load_kb(kb_id: str) -> tuple[dict, str]:
    """(kb, sha256) of a verified add-on knowledge artifact."""
    from diagnostic_ar_training.rerank import kb as kb_io

    path, sha = _verified_output(kb_id, KB_KIND, KB_FILE)
    return kb_io.read(path), sha


def load_bundle(bundle_id: str, kb_id: str) -> tuple[dict, str]:
    """(bundle, sha256) of a verified add-on bundle fitted on `kb_id`."""
    from diagnostic_ar_training.ft.bundle import load

    path, sha = _verified_output(bundle_id, BUNDLE_KIND, BUNDLE_FILE)
    out = load(path)
    if out["kb_id"] != kb_id:
        raise LineageError(f"{bundle_id} was fitted on {out['kb_id']}, not {kb_id}")
    return out, sha


def network_view(members: Sequence[patients.Patient]) -> list[patients.Patient]:
    """What the network reads: present terms only."""
    return [patients.Patient(patients.present_only(p.case), p.group, p.status, p.fold) for p in members]


def load_network(run_id: str, ctx, checkpoint: str = "last"):
    """A v4 run's network in eval mode; refused if it reads covariates (it must see present terms only)."""
    from diagnostic_ar_training.v4 import model, train
    from diagnostic_ar_training.v4.runs import load_config, run_dir

    cfg = load_config(run_id)
    if cfg.encoding.covariates:
        raise LineageError(f"{run_id} reads covariates: the add-on's network must see present terms only")
    net = model.GinV4(ctx.inputs.dim, len(ctx.genes), cfg.arch, cfg.encoding).to(ctx.device).eval()
    train.load_weights(net, run_dir(run_id) / f"{checkpoint}.pt", ctx.device)
    return net, cfg


def network_logits(net, pset, tables, encoding, batch_size: int = 512) -> dict[str, np.ndarray]:
    """case id -> float32 logits of every scorable patient of a PatientSet.

    The in-vocabulary rows are batched exactly as `v4.evaluate.model_ranks`, so the ranks are its own; the
    out-of-vocabulary rows (rank inf anyway) follow.
    """
    import torch

    from diagnostic_ar_training.v4 import data

    rows = [i for i, (g, t) in enumerate(zip(pset.graphs, pset.targets, strict=True)) if g is not None]
    in_vocab = [i for i in rows if pset.targets[i] is not None]
    oov = [i for i in rows if pset.targets[i] is None]
    out = {}
    with torch.no_grad():
        for group in (in_vocab, oov):
            for start in range(0, len(group), batch_size):
                chunk = group[start : start + batch_size]
                items = [
                    data.Item(pset.graphs[i], pset.targets[i] or 0, pset.covariates[i], True) for i in chunk
                ]
                inputs = data.to_device(data.collate(items), tables, encoding)
                logits = net(**data.model_inputs(inputs)).float().cpu().numpy()
                out.update({pset.patients[i].case_id: logits[j] for j, i in enumerate(chunk)})
    return out


def e0_logits(members: Sequence[patients.Patient], e0=None) -> dict[str, np.ndarray]:
    """case id -> E0's float32 logits (production ONNX, present terms) of every patient E0 can score."""
    from diagnostic_ar_training.ft.system import E0Logits

    if e0 is None:
        from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

        e0 = E0Logits(GenPheniaV3())
    out = {}
    for p in network_view(members):
        logits, _ = e0(p.case)
        if logits is not None:
            out[p.case_id] = np.asarray(logits, dtype=np.float32)
    return out


def features(members: Sequence[patients.Patient], knowledge: Knowledge) -> tuple[np.ndarray, np.ndarray]:
    """(c [n, K, genes] float32, z [n, C] float32) of the add-on's inputs."""
    feats = np.zeros((len(members), len(FEATURES), len(knowledge.genes)), dtype=np.float32)
    z = np.zeros((len(members), len(COVARIATES)), dtype=np.float32)
    for i, p in enumerate(members):
        inputs = case_inputs(p.case)
        feats[i] = knowledge.features(inputs)
        z[i] = covariates(inputs)
    return feats, z


def fit_config(features: Sequence[str], seed: int):
    from diagnostic_ar_training.ft.train import FitConfig

    return FitConfig(seed=seed, **{**configs.config(CONFIG), "features": tuple(features)})


def fit(
    case_ids: Sequence[str],
    groups: Sequence[str],
    logits: np.ndarray,
    feats: np.ndarray,
    z: np.ndarray,
    target: np.ndarray,
    features: Sequence[str] = FEATURES,
    seeds: Sequence[int] = SEEDS,
    device: str = "cpu",
    log: Callable[[str], None] = print,
) -> tuple[list[dict], list[dict]]:
    """(members, per-seed fit info) of ft-v1.1's recipe on these rows (in-vocabulary, scorable patients).

    Early stopping reads the held-out publication groups of `ft.configs.inner_split` among these rows.
    """
    from diagnostic_ar_training.ft import train as ft_train

    case_ids = list(case_ids)
    held = configs.inner_split(dict(zip(case_ids, groups, strict=True)), case_ids)
    part = ft_train.to_part(case_ids, logits, feats, z, target, device)
    trn, val = part.rows(set(case_ids) - held), part.rows(held)
    members, info = [], []
    for seed in seeds:
        result = ft_train.fit(fit_config(features, seed), trn, val, log=log)
        member = result.model.member()
        members.append(member)
        info.append(
            {
                "seed": seed,
                "best_epoch": result.best_epoch,
                "epochs_run": result.epochs_run,
                "stopped_early": result.stopped_early,
                "theta": dict(zip(FEATURES, member["theta"], strict=True)),
                "val_mrr_epoch0": result.history[0]["val"]["mrr"],
                "val_mrr_best": max(h["val"]["mrr"] for h in result.history),
            }
        )
    return members, info


def bundle(kb_id: str, members: list[dict], model_ids: list[str], **extra) -> dict:
    """An `ft-v1-bundle/2` (ft/bundle.py), with provenance fields that format ignores."""
    return {
        "format": FORMAT,
        "kb_id": kb_id,
        "features": list(FEATURES),
        "covariates": list(COVARIATES),
        "members": members,
        "model_ids": model_ids,
        **extra,
    }


def untrained(kb_id: str, features: Sequence[str] = FEATURES) -> dict:
    """A one-member bundle with θ = 0: the add-on before any fitting."""
    member = {
        "active_features": list(features),
        "active_covariates": list(COVARIATES),
        "theta": [0.0] * len(FEATURES),
        "mlp": None,
    }
    return bundle(kb_id, [member], ["untrained"])


def mean_theta(members: Sequence[Mapping]) -> dict[str, float]:
    """The ensemble's effective θ per feature (linear members: the mean of max(θ, 0) on active features)."""
    rows = []
    for m in members:
        active = set(m["active_features"])
        rows.append([max(t, 0.0) if f in active else 0.0 for f, t in zip(FEATURES, m["theta"], strict=True)])
    return dict(zip(FEATURES, np.mean(rows, axis=0).tolist(), strict=True))


class Addon:
    """A bundle on its knowledge: base logits in, add-on scores out (float64)."""

    def __init__(self, bundle: Mapping, knowledge: Knowledge) -> None:
        if any(m.get("classifier_delta") for m in bundle["members"]):
            raise ValueError("the add-on has no per-gene parameter: classifier deltas are refused")
        self.bundle, self.knowledge = bundle, knowledge
        self.residual = FtResidual(bundle, knowledge)

    def residual_of(self, inputs: Mapping, feats: np.ndarray | None = None) -> np.ndarray:
        """r [genes] float64; `feats` are this patient's precomputed `Knowledge.features`, if at hand."""
        if feats is None:
            return self.residual.residual(inputs)
        w = self.residual.weights(inputs)
        if not w.any():
            return np.zeros(len(self.knowledge.genes), dtype=np.float64)
        return (w @ np.asarray(feats, dtype=np.float64)).mean(axis=0)

    def scores(self, logits: np.ndarray, inputs: Mapping, feats: np.ndarray | None = None) -> np.ndarray:
        base = np.asarray(logits, dtype=np.float64).reshape(-1)
        r = self.residual_of(inputs, feats)
        return base + r if r.any() else base


def score_patients(
    base: Mapping[str, np.ndarray], members: Sequence[patients.Patient], addon: Addon
) -> dict[str, np.ndarray]:
    """case id -> add-on scores of every patient whose base logits are given; `members` carry every input."""
    return {
        p.case_id: addon.scores(base[p.case_id], case_inputs(p.case)) for p in members if p.case_id in base
    }


def rank(scores: np.ndarray, target: int, softmax: bool = False) -> float:
    """Pessimistic 1-based rank of `target`; on softmax64(scores) when `softmax` (E0's harness)."""
    s = softmax64(scores) if softmax else np.asarray(scores)
    t = s[target]
    return float(np.sum(s > t) + np.sum(s == t))


def records(
    members: Sequence[patients.Patient],
    scores: Mapping[str, np.ndarray],
    genes: Sequence[str],
    softmax: bool = False,
) -> list[dict]:
    """`v4.report` records: rank inf when the gene is outside the vocabulary or the patient is unscorable."""
    lookup = {g.upper(): i for i, g in enumerate(genes)}
    out = []
    for p in members:
        idx, s = lookup.get(p.case.gene.upper()), scores.get(p.case_id)
        r = math.inf if idx is None or s is None else rank(s, idx, softmax)
        out.append(report.record(p, idx is not None, s is not None, r))
    return out


def compare(new: Sequence[dict], base: Sequence[dict], strata: Sequence[str] = STRATA) -> dict[str, dict]:
    """Per stratum, `v4.report.stratum_summary` of `new` against `base` on the same patients."""
    by_id = {r["case_id"]: r for r in base}
    out = {}
    for name in strata:
        recs = [r for r in new if name in r["strata"]]
        if recs:
            out[name] = report.stratum_summary(recs, [by_id[r["case_id"]] for r in recs])
    return out


def confirm_patients(
    reason: str,
    cases_in: Callable | None = None,
    groups: Mapping[str, str] | None = None,
    status: Mapping[str, str] | None = None,
) -> list[patients.Patient]:
    """The CONFIRM fold's patients with every add-on input. Main session only.

    They come through `sim4.folds.cases_in`, which demands DXT_P3_CONFIRM=1 and a reason, and writes the
    ledger row before any patient is loaded.
    """
    from diagnostic_ar_training.sim4 import folds

    cases = (cases_in or folds.cases_in)((folds.CONFIRM_FOLD,), Purpose.EVAL, reason)
    if groups is None:
        groups = folds.train_groups()
    if status is None:
        from diagnostic_ar_training import splits

        status = splits.load_frozen(patients.SPLIT)["group_status"]
    out = patients.annotate(cases, dict(groups), dict(status), folds.fold_of, keep_excluded=True)
    if {p.fold for p in out} - {folds.CONFIRM_FOLD}:
        raise LineageError("a CONFIRM read got patients of another fold")
    return out


def confirm_read(
    reason: str,
    bundles: Mapping[str, Mapping],
    knowledge: Knowledge,
    network_scores: Callable[[list[patients.Patient]], dict[str, np.ndarray]],
    e0_scores: Callable[[list[patients.Patient]], dict[str, np.ndarray]],
    load: Callable[[str], list[patients.Patient]] = confirm_patients,
) -> tuple[dict, dict[str, list[dict]]]:
    """(summary, records): the network alone and the network + each bundle vs E0 on the CONFIRM fold.

    `load` opens the fold (and its gate) before anything is scored; the network and E0 get the present terms
    only, the add-on every input.
    """
    members = load(reason)
    genes = knowledge.genes
    net = network_scores(network_view(members))
    e0 = e0_scores(network_view(members))
    recs = {"E0": records(members, e0, genes, softmax=True), "network": records(members, net, genes)}
    summary = {"n": len(members), "network": {"vs_e0": compare(recs["network"], recs["E0"])}}
    for bundle_id, b in bundles.items():
        recs[bundle_id] = records(members, score_patients(net, members, Addon(b, knowledge)), genes)
        summary[bundle_id] = {
            "vs_e0": compare(recs[bundle_id], recs["E0"]),
            "vs_network": compare(recs[bundle_id], recs["network"]),
        }
    return summary, recs
