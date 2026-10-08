"""ltr-v1 as a self-contained bundle: gene-agnostic features, a LightGBM text model, a pure-numpy `apply`.

This module imports only numpy, the standard library and `safe/bundle.py` (itself numpy-only), so
diagnostic.ar-model can ship the three files of a bundle with it unchanged. `LtrV1` (ltr/system.py) scores
through this same code, so what was evaluated is what ships.

A bundle is a directory:
- `spec.json` (`ltr-v1-spec/1`): the feature names in model order, the monotone constraints, the family, the
  shrink factor, the number of re-ranked candidates (`top_k`) and the knowledge it was fitted with (`kb_id`,
  `kb_sha256`);
- `model.txt`: the LightGBM text model, evaluated here without LightGBM (`TreeEnsemble`);
- the knowledge (`ltr-kb/1`, gzipped JSON, `Knowledge`), shipped next to them.

`apply(probs, genes, case_inputs)` takes E0's distribution over `genes` and the case inputs
{"present": [HPO ids], "excluded": [HPO ids], "sex": "male" | "female" | anything else for unknown,
"onset_years": float | None, "age_years": float | None}:
1. The candidates are E0's top `top_k` genes. Each gets the features below and a model score; the residual
   families add `shrink` times the score to E0's log-probability.
2. The candidates are re-ordered by score (ties keep E0's order). They keep E0's total probability, spread by
   a softmax of the score, strictly decreasing in the new order.
3. Every other gene keeps E0's order below the candidates (safe/bundle.py `rescale_factors`).
A `residual_new` model with no new-input feature set on any candidate returns `probs` itself, bit for bit:
its score is then increasing in E0's log-probability, so the order could not change anyway.
"""

import gzip
import json
import math
from collections.abc import Mapping, Sequence
from functools import cache
from pathlib import Path

import numpy as np

from diagnostic_ar_training.safe.bundle import SafeRules, rescale_factors

KB_FORMAT = "ltr-kb/1"
SPEC_FORMAT = "ltr-v1-spec/1"
TOP_K = 100
EPSILON = 0.01
UNKNOWN_FREQUENCY = 0.3
XLR, XLD, XL = "HP:0001419", "HP:0001423", "HP:0001417"

# (name, group, monotone constraint). "new" is what the anteproyecto adds: sex, age, onset and excluded terms;
# every one of them is a conflict or an incompatibility, so it may only lower a gene's score (PHASE2.md).
FEATURES: tuple[tuple[str, str, int], ...] = (
    ("e0_logp", "e0", 1),
    ("e0_logrank", "e0", -1),
    ("e0_gap_top1", "e0", 1),
    ("present_llr_sum", "present", 0),
    ("present_llr_mean", "present", 0),
    ("present_explained", "present", 0),
    ("present_resnik_bma", "present", 0),
    ("richness_terms", "richness", 0),
    ("richness_diseases", "richness", 0),
    ("sex_mismatch", "new", -1),
    ("xlr_female", "new", -1),
    ("xld_male", "new", -1),
    ("onset_late", "new", -1),
    ("onset_gap_strict", "new", -1),
    ("onset_gap_lenient", "new", -1),
    ("negation_contradicted", "new", -1),
    ("excl_obligate", "new", -1),
    ("excl_very_frequent", "new", -1),
    ("excl_frequent", "new", -1),
    ("excl_occasional", "new", -1),
    ("excl_unknown_frequency", "new", -1),
)
NAMES = tuple(f[0] for f in FEATURES)
GROUP = {f[0]: f[1] for f in FEATURES}
MONOTONE = {f[0]: f[2] for f in FEATURES}
NEW = tuple(n for n in NAMES if GROUP[n] == "new")
# Highest annotated frequency band of an excluded term (or a descendant) in the gene, on ADR-0007 estimates.
BANDS = ("excl_occasional", "excl_frequent", "excl_very_frequent", "excl_obligate")
BAND_FLOORS = (0.0, 0.30, 0.80, 0.99)

# Families: which features the model sees and whether E0's log-probability is its starting score.
FAMILIES: dict[str, dict] = {
    "free": {"init": False, "groups": ("e0", "present", "richness", "new")},
    "residual": {"init": True, "groups": ("e0", "present", "richness", "new")},
    "residual_new": {"init": True, "groups": ("e0", "new")},
}


def family_features(family: str, ablation: bool = False) -> tuple[str, ...]:
    groups = FAMILIES[family]["groups"]
    return tuple(n for n in NAMES if GROUP[n] in groups and not (ablation and GROUP[n] == "new"))


def band(freq: float | None) -> int:
    """Index into BANDS, or -1 for an annotation of unknown frequency."""
    if freq is None:
        return -1
    return max(i for i, floor in enumerate(BAND_FLOORS) if freq >= floor)


class Knowledge:
    """Per-gene knowledge (`ltr-kb/1`) and the features of a case's candidates.

    Format, one JSON object:
    - `genes`: {symbol: {"diseases": {disease id: weight}, "lenient_onset_years": float, "xlr_only": bool,
      "xld_only": bool}}; optional keys are present only when they apply;
    - `diseases`: {disease id: [[HPO id, frequency or null], ...]}, ADR-0007 frequency estimates;
    - `parents`: {HPO id: [parent ids]}; `resolve`: {old or alternative id: current id};
    - `ic`: {HPO id: information content over the diseases};
    - `background`: {HPO id: mean P(term | gene) over the vocabulary};
    - `safe`: a `safe-v1-bundle/1` (sex limitation, strict earliest onset, obligate phenotypes).
    """

    def __init__(self, kb: Mapping) -> None:
        if kb.get("format") != KB_FORMAT:
            raise ValueError(f"not a {KB_FORMAT} knowledge")
        self.kb = kb
        self.genes = kb["genes"]
        self.diseases = kb["diseases"]
        self.parents = kb["parents"]
        self.resolve = kb["resolve"]
        self.ic = kb["ic"]
        self.background = kb["background"]
        self.epsilon = float(kb.get("epsilon", EPSILON))
        self.unknown_frequency = float(kb.get("unknown_frequency", UNKNOWN_FREQUENCY))
        self.safe = SafeRules(kb["safe"])
        self._by_ic: dict[str, tuple[tuple[float, str], ...]] = {}

    @classmethod
    def load(cls, path: Path) -> "Knowledge":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return cls(json.load(handle))

    def term(self, hpo_id: str) -> str | None:
        t = self.resolve.get(hpo_id, hpo_id)
        return t if t in self.parents else None

    @cache  # noqa: B019 -- one Knowledge per process
    def ancestors_or_self(self, term: str) -> frozenset[str]:
        out = {term}
        for p in self.parents.get(term, ()):
            out |= self.ancestors_or_self(p)
        return frozenset(out)

    def _by_information(self, term: str) -> tuple[tuple[float, str], ...]:
        """The term's ancestors-or-self with an IC, most informative first."""
        if term not in self._by_ic:
            self._by_ic[term] = tuple(
                sorted(((self.ic[a], a) for a in self.ancestors_or_self(term) if a in self.ic), reverse=True)
            )
        return self._by_ic[term]

    @cache  # noqa: B019
    def disease_profile(self, disease: str) -> tuple[dict[str, float], dict[str, int]]:
        """(P(term | disease) for each term annotated itself or through a descendant, best band per term)."""
        absent: dict[str, float] = {}
        best: dict[str, int] = {}
        for term, freq in self.diseases.get(disease, ()):
            f = self.unknown_frequency if freq is None else freq
            b = band(freq)
            for t in self.ancestors_or_self(term):
                absent[t] = absent.get(t, 1.0) * (1.0 - f)
                best[t] = max(best.get(t, -1), b)
        return {t: 1.0 - a for t, a in absent.items()}, best

    @cache  # noqa: B019
    def gene_profile(self, gene: str) -> tuple[dict[str, float], dict[str, int], int, int]:
        """(P(term | gene), best band per term, distinct annotated terms, annotated diseases)."""
        probs: dict[str, float] = {}
        best: dict[str, int] = {}
        terms: set[str] = set()
        annotated = 0
        for d, w in self.genes.get(gene, {}).get("diseases", {}).items():
            p, b = self.disease_profile(d)
            for t, v in p.items():
                probs[t] = probs.get(t, 0.0) + w * v
            for t, v in b.items():
                best[t] = max(best.get(t, -1), v)
            rows = self.diseases.get(d, ())
            terms.update(t for t, _ in rows)
            annotated += bool(rows)
        return probs, best, len(terms), annotated

    def features(
        self, vocabulary: Sequence[str], top: np.ndarray, case_inputs: Mapping, logp: np.ndarray
    ) -> np.ndarray:
        """[len(top), len(NAMES)] for one case's candidates `top` (indices into `vocabulary`, in E0's order;
        `logp` is their E0 log-probability)."""
        n = len(top)
        x = np.zeros((n, len(NAMES)))
        col = {name: i for i, name in enumerate(NAMES)}
        x[:, col["e0_logp"]] = logp
        x[:, col["e0_logrank"]] = np.log(np.arange(1, n + 1))
        x[:, col["e0_gap_top1"]] = logp - logp[0] if n else logp
        if not n:
            return x
        vocabulary = tuple(vocabulary)
        x[:, col["sex_mismatch"]] = self.safe.masks(vocabulary, case_inputs, ("sex",))[1][top]
        x[:, col["onset_late"]] = self.safe.masks(vocabulary, case_inputs, ("onset",))[1][top]
        x[:, col["negation_contradicted"]] = self.safe.masks(vocabulary, case_inputs, ("negation",))[0][top]

        present = [t for t in (self.term(h) for h in case_inputs.get("present") or ()) if t]
        excluded = [t for t in (self.term(h) for h in case_inputs.get("excluded") or ()) if t]
        bg = [self.background.get(t, 0.0) for t in present]
        sex = str(case_inputs.get("sex") or "").lower()
        ref = case_inputs.get("onset_years")
        ref = case_inputs.get("age_years") if ref is None else ref
        ref = None if ref is None else max(float(ref), 0.0)
        safe_genes = self.safe.bundle["genes"]
        for i, g in enumerate(vocabulary[j] for j in top):
            probs, best, n_terms, n_diseases = self.gene_profile(g)
            if present:
                p = [probs.get(t, 0.0) for t in present]
                llr = sum(
                    math.log((a + self.epsilon) / (b + self.epsilon)) for a, b in zip(p, bg, strict=True)
                )
                x[i, col["present_llr_sum"]] = llr
                x[i, col["present_llr_mean"]] = llr / len(present)
                x[i, col["present_explained"]] = sum(v > 0 for v in p) / len(present)
                x[i, col["present_resnik_bma"]] = sum(
                    next((ic for ic, a in self._by_information(t) if a in probs), 0.0) for t in present
                ) / len(present)
            x[i, col["richness_terms"]] = math.log1p(n_terms)
            x[i, col["richness_diseases"]] = n_diseases
            info = self.genes.get(g, {})
            if sex == "female" and info.get("xlr_only"):
                x[i, col["xlr_female"]] = 1.0
            if sex == "male" and info.get("xld_only"):
                x[i, col["xld_male"]] = 1.0
            if ref is not None:
                if "lenient_onset_years" in info:
                    x[i, col["onset_gap_lenient"]] = max(info["lenient_onset_years"] - ref, 0.0)
                strict = safe_genes.get(g, {}).get("earliest_onset_years")
                if strict is not None:
                    x[i, col["onset_gap_strict"]] = max(strict - ref, 0.0)
            for t in excluded:
                if t in best:
                    b = best[t]
                    x[i, col[BANDS[b]] if b >= 0 else col["excl_unknown_frequency"]] += 1.0
        return x


class TreeEnsemble:
    """A LightGBM text model (numerical splits only), evaluated with numpy."""

    def __init__(self, text: str) -> None:
        self.feature_names: list[str] = []
        self.trees: list[dict] = []
        tree: dict | None = None
        for line in text.splitlines():
            if line.startswith("feature_names=") and tree is None:
                self.feature_names = line.split("=", 1)[1].split()
            elif line.startswith("Tree="):
                tree = {}
                self.trees.append(tree)
            elif line.startswith("end of trees"):
                break
            elif tree is not None and "=" in line:
                key, value = line.split("=", 1)
                tree[key] = value
        self._arrays = [self._parse(t) for t in self.trees]

    @staticmethod
    def _parse(tree: dict) -> dict:
        leaves = np.array(tree["leaf_value"].split(), dtype=np.float64)
        if int(tree["num_leaves"]) == 1:
            return {"leaf": leaves}
        decision = np.array(tree["decision_type"].split(), dtype=np.int64)
        if (decision & 1).any():
            raise ValueError("categorical splits are not supported")
        return {
            "leaf": leaves,
            "feature": np.array(tree["split_feature"].split(), dtype=np.int64),
            "threshold": np.array(tree["threshold"].split(), dtype=np.float64),
            "default_left": (decision & 2) > 0,
            "missing": (decision >> 2) & 3,
            "left": np.array(tree["left_child"].split(), dtype=np.int64),
            "right": np.array(tree["right_child"].split(), dtype=np.int64),
        }

    def predict(self, x: np.ndarray) -> np.ndarray:
        """Raw scores (the sum of leaf values), as LightGBM's `predict(raw_score=True)`."""
        x = np.asarray(x, dtype=np.float64)
        out = np.zeros(x.shape[0])
        rows = np.arange(x.shape[0])
        for t in self._arrays:
            if "feature" not in t:
                out += t["leaf"][0]
                continue
            node = np.zeros(x.shape[0], dtype=np.int64)
            active = node >= 0
            while active.any():
                idx = node[active]
                v = x[rows[active], t["feature"][idx]]
                missing = t["missing"][idx]
                nan = np.isnan(v)
                v = np.where(nan & (missing != 2), 0.0, v)
                use_default = ((missing == 1) & (np.abs(v) <= 1e-35)) | ((missing == 2) & nan)
                go_left = np.where(use_default, t["default_left"][idx], v <= t["threshold"][idx])
                node[active] = np.where(go_left, t["left"][idx], t["right"][idx])
                active = node >= 0
            out += t["leaf"][~node]
        return out


def read_spec(path: Path) -> dict:
    spec = json.loads(Path(path).read_text())
    if spec.get("format") != SPEC_FORMAT:
        raise ValueError(f"{path}: not a {SPEC_FORMAT} spec")
    return spec


class LtrModel:
    """A fitted re-ranker: knowledge, spec and trees."""

    def __init__(self, knowledge: Knowledge, spec: Mapping, model_text: str) -> None:
        if spec.get("format") != SPEC_FORMAT:
            raise ValueError(f"not a {SPEC_FORMAT} spec")
        self.knowledge = knowledge
        self.spec = spec
        self.features = tuple(spec["features"])
        self.columns = np.array([NAMES.index(f) for f in self.features], dtype=np.int64)
        self.init = bool(spec["init_e0_logp"])
        self.shrink = float(spec.get("shrink", 1.0))
        self.top_k = int(spec["top_k"])
        self.trees = TreeEnsemble(model_text)
        if self.trees.feature_names and self.trees.feature_names != list(self.features):
            raise ValueError("the model's features differ from the spec's")
        self.new_columns = np.array([i for i, f in enumerate(self.features) if GROUP[f] == "new"], dtype=int)
        self.identity_when_no_new = spec["family"] == "residual_new"

    @classmethod
    def load(cls, directory: Path, knowledge: Knowledge, model_file: str = "model.txt") -> "LtrModel":
        directory = Path(directory)
        return cls(knowledge, read_spec(directory / "spec.json"), (directory / model_file).read_text())

    def candidates(self, probs: np.ndarray) -> np.ndarray:
        """E0's top `top_k`, in E0's order (ties by gene index, as a stable sort gives)."""
        return np.argsort(-np.asarray(probs, dtype=np.float64), kind="stable")[: self.top_k]

    def scores(self, x_all: np.ndarray) -> np.ndarray:
        """Final scores of one case's candidates from the full feature matrix."""
        s = self.trees.predict(x_all[:, self.columns])
        return x_all[:, NAMES.index("e0_logp")] + self.shrink * s if self.init else s

    def unchanged(self, x_all: np.ndarray) -> bool:
        return self.identity_when_no_new and not x_all[:, self.columns[self.new_columns]].any()

    def apply(self, probs: np.ndarray, genes: Sequence[str], case_inputs: Mapping) -> np.ndarray:
        top = self.candidates(probs)
        logp = np.log(np.clip(np.asarray(probs, dtype=np.float64)[top], 1e-300, None))
        x = self.knowledge.features(genes, top, case_inputs, logp)
        if self.unchanged(x):
            return probs
        return reorder(probs, top, self.scores(x))


def order(scores: np.ndarray) -> np.ndarray:
    """Positions by decreasing score; ties keep the incoming (E0) order."""
    return np.lexsort((np.arange(scores.size), -scores))


def reorder(probs: np.ndarray, top: np.ndarray, scores: np.ndarray) -> np.ndarray:
    """E0's candidates re-ordered by `scores`, keeping their total mass; every other gene stays below them."""
    p = np.asarray(probs, dtype=np.float64)
    mass = p[top].sum()
    if not mass > 0:
        return probs
    new = order(scores)
    s = scores[new] - scores.max()
    logq = s - math.log(np.exp(s).sum()) + math.log(mass)
    for i in range(1, logq.size):
        logq[i] = min(logq[i], logq[i - 1] - 1e-9)
    out = p.copy()
    out[top[new]] = np.exp(logq)
    rest = np.ones(p.size, dtype=bool)
    rest[top] = False
    return rescale_factors(out / out.sum(), None, rest)
