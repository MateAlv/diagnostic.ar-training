"""ft-v1 as a self-contained residual on top of E0's logits: numpy and the standard library only.

diagnostic.ar-model can ship this module unchanged next to the model, as with `safe/bundle.py` (which it uses
for the obligate-negation rule). `FtV1` (ft/system.py) scores through this same code, so what was evaluated is
what ships.

logits' = logits_E0 + r, r_g = Σ_k w_k(patient) · c_k(patient, g), and w_k(patient) ≤ 0 for every k:
- c_k (`FEATURES`), gene-agnostic compatibility features, each ≥ 0 and 0 when its patient input is unknown:
  - `sex_mismatch`: the gene is limited to the other sex (safe-v1's curated sex rule);
  - `onset_strict_late`: the gene's strict earliest onset is later than the reference age (safe-v1's onset
    rule);
  - `onset_strict_gap`, `onset_lenient_gap`: log1p of the years by which the strict / lenient earliest onset
    is later than the reference age (0 when it is not later);
  - `xlr_female`, `xld_male`: a female patient and an X-linked-recessive-only gene; a male patient and an
    X-linked-dominant-only gene;
  - `neg_obligate`: safe-v1's negation rule (the excluded terms cover an obligate phenotype of every annotated
    disease of the gene);
  - `neg_embed`: the mean, over the excluded terms, of the highest cosine similarity between the excluded term
    and a term of the gene's annotated profile, in v3.0's own (frozen) term embeddings; negative values count
    as 0.

  The reference age is the onset when known, else the current age; negative values count as 0.
- w(patient) = −max(θ, 0) ⊙ softplus(m(z)) / ln 2, where z are the patient covariates (`COVARIATES`) and m is
  a small MLP whose last layer starts at 0 (or absent: w = −max(θ, 0)). θ starts at 0, so the untrained
  residual is exactly 0, and absent findings and incompatibilities can only lower a gene's score.
- No parameter is per gene: the only per-gene inputs are knowledge (`ft-kb/1`), never learned from patients.

Weights bundle (`format: ft-v1-bundle/1`), one JSON object:
- `kb_id`; `features`, `covariates`: the names above, in order;
- `members`: a list; the residual is the mean of the members' residuals (an ensemble of seeds). Each member
  has `active_features` and `active_covariates` (the rest are held at 0), `theta` [K], and `mlp`, null or
  {"w1": [H][C], "b1": [H], "w2": [K][H], "b2": [K]}; optionally `classifier_delta`, the file name of an npz
  with `weight` [genes, 512] and `bias` [genes] added to v3.0's classifier (needs v3.0's pooled vector).

`FtResidual(bundle, Knowledge(kb, genes, embeddings)).apply(logits, case_inputs)` takes E0's logits over
`genes` and {"sex": "male" | "female" | anything else for unknown, "age_years": float | None, "onset_years":
float | None, "present": [HPO ids], "excluded": [HPO ids]}, and returns the probabilities. When the residual
is 0 everywhere, they are softmax(logits) in float64, bit for bit E0's.
"""

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np

from diagnostic_ar_training.safe.bundle import SafeRules
from diagnostic_ar_training.safe.bundle import export as safe_export

FORMAT = "ft-v1-bundle/1"
FEATURES = (
    "sex_mismatch",
    "onset_strict_late",
    "onset_strict_gap",
    "onset_lenient_gap",
    "xlr_female",
    "xld_male",
    "neg_obligate",
    "neg_embed",
)
COVARIATES = (
    "male",
    "female",
    "log1p_age",
    "age_known",
    "log1p_onset",
    "onset_known",
    "log1p_n_present",
    "log1p_n_excluded",
)
# The anteproyecto's inputs, grouped: the ablation drops "sex" and "age" (age and onset).
FEATURE_GROUPS = {
    "sex": ("sex_mismatch", "xlr_female", "xld_male"),
    "age": ("onset_strict_late", "onset_strict_gap", "onset_lenient_gap"),
    "negation": ("neg_obligate", "neg_embed"),
}
COVARIATE_GROUPS = {
    "sex": ("male", "female"),
    "age": ("log1p_age", "age_known", "log1p_onset", "onset_known"),
    "counts": ("log1p_n_present", "log1p_n_excluded"),
}
LN2 = math.log(2.0)


def _sex(value) -> str | None:
    text = str(value).lower() if value is not None else ""
    return text if text in ("male", "female") else None


def reference_age(case_inputs: Mapping) -> float | None:
    ref = case_inputs.get("onset_years")
    ref = case_inputs.get("age_years") if ref is None else ref
    return None if ref is None else max(float(ref), 0.0)


def covariates(case_inputs: Mapping) -> np.ndarray:
    z = np.zeros(len(COVARIATES), dtype=np.float32)
    sex = _sex(case_inputs.get("sex"))
    z[0], z[1] = sex == "male", sex == "female"
    if case_inputs.get("age_years") is not None:
        z[2], z[3] = math.log1p(max(float(case_inputs["age_years"]), 0.0)), 1
    if case_inputs.get("onset_years") is not None:
        z[4], z[5] = math.log1p(max(float(case_inputs["onset_years"]), 0.0)), 1
    z[6] = math.log1p(len(set(case_inputs.get("present") or ())))
    z[7] = math.log1p(len(set(case_inputs.get("excluded") or ())))
    return z


class Knowledge:
    """`ft-kb/1` as arrays over one gene vocabulary.

    `embeddings` is (term -> row, vectors [rows, dim]), v3.0's input embeddings; without it `neg_embed` is 0.
    """

    def __init__(
        self,
        kb: Mapping,
        genes: Sequence[str],
        embeddings: tuple[Mapping[str, int], np.ndarray] | None = None,
        kb_id: str = "",
    ) -> None:
        self.genes = tuple(genes)
        safe = kb["safe"]["genes"]
        extra = kb["genes"]
        self.male = np.array([safe.get(g, {}).get("sex", {}).get("limit") == "male" for g in self.genes])
        self.female = np.array([safe.get(g, {}).get("sex", {}).get("limit") == "female" for g in self.genes])
        self.strict = np.array(
            [safe.get(g, {}).get("onset", {}).get("earliest_years", -np.inf) for g in self.genes],
            dtype=np.float64,
        )
        self.lenient = np.array(
            [extra.get(g, {}).get("lenient_onset_years", -np.inf) for g in self.genes], dtype=np.float64
        )
        self.xlr = np.array([bool(extra.get(g, {}).get("xlr_only")) for g in self.genes])
        self.xld = np.array([bool(extra.get(g, {}).get("xld_only")) for g in self.genes])
        self.rules = SafeRules(safe_export(kb["safe"], kb_id))
        self.embedded = embeddings is not None
        self._profiles(extra, embeddings)

    def _profiles(self, extra: Mapping, embeddings) -> None:
        self.has_profile = np.zeros(len(self.genes), dtype=bool)
        self.starts = np.zeros(0, dtype=np.int64)
        self.cols = np.zeros(0, dtype=np.int64)
        self.unit = np.zeros((0, 0), dtype=np.float32)
        self.index: Mapping[str, int] = {}
        if embeddings is None:
            return
        index, vectors = embeddings
        self.index, self.vectors = index, vectors
        named = {t for g in self.genes for t in extra.get(g, {}).get("profile", ())}
        terms = sorted(t for t in named if self._norm(t) > 0)
        column = {t: i for i, t in enumerate(terms)}
        self.unit = self._unit(terms)
        cols, starts = [], []
        for i, g in enumerate(self.genes):
            mine = [column[t] for t in extra.get(g, {}).get("profile", ()) if t in column]
            if mine:
                self.has_profile[i] = True
                starts.append(len(cols))
                cols.extend(mine)
        self.starts = np.asarray(starts, dtype=np.int64)
        self.cols = np.asarray(cols, dtype=np.int64)

    def _norm(self, term: str) -> float:
        row = self.index.get(term)
        return 0.0 if row is None else float(np.linalg.norm(self.vectors[row]))

    def _unit(self, terms: Sequence[str]) -> np.ndarray:
        if not terms:
            return np.zeros((0, self.vectors.shape[1]), dtype=np.float32)
        x = np.asarray(self.vectors[[self.index[t] for t in terms]], dtype=np.float32)
        return x / np.linalg.norm(x, axis=1, keepdims=True)

    def neg_embed(self, excluded: Sequence[str]) -> np.ndarray:
        out = np.zeros(len(self.genes), dtype=np.float32)
        terms = [t for t in dict.fromkeys(excluded) if self._norm(t) > 0] if self.embedded else []
        if not terms or not self.cols.size:
            return out
        sims = self._unit(terms) @ self.unit.T
        best = np.maximum.reduceat(sims[:, self.cols], self.starts, axis=1)
        out[self.has_profile] = np.clip(best, 0.0, None).mean(axis=0)
        return out

    def features(self, case_inputs: Mapping) -> np.ndarray:
        """[len(FEATURES), genes] float32."""
        f = np.zeros((len(FEATURES), len(self.genes)), dtype=np.float32)
        sex = _sex(case_inputs.get("sex"))
        if sex:
            f[0] = self.female if sex == "male" else self.male
            f[4] = self.xlr if sex == "female" else 0
            f[5] = self.xld if sex == "male" else 0
        ref = reference_age(case_inputs)
        if ref is not None:
            strict_gap = np.clip(self.strict - ref, 0.0, None)
            f[1] = strict_gap > 0
            f[2] = np.log1p(strict_gap)
            f[3] = np.log1p(np.clip(self.lenient - ref, 0.0, None))
        excluded = list(case_inputs.get("excluded") or ())
        if excluded:
            contradicted, _ = self.rules.masks(self.genes, {"excluded": excluded}, ("negation",))
            f[6] = contradicted
            f[7] = self.neg_embed(excluded)
        return f


def _softplus(x: np.ndarray) -> np.ndarray:
    return np.logaddexp(0.0, x)


def member_weights(member: Mapping, z: np.ndarray) -> np.ndarray:
    """w(patient) [K] of one member, float64, every entry ≤ 0."""
    active = np.array([f in set(member["active_features"]) for f in FEATURES], dtype=np.float64)
    theta = np.maximum(np.asarray(member["theta"], dtype=np.float64), 0.0) * active
    mlp = member.get("mlp")
    if not mlp:
        return -theta
    keep = np.array([c in set(member["active_covariates"]) for c in COVARIATES], dtype=np.float64)
    h = np.maximum(np.asarray(mlp["w1"], dtype=np.float64) @ (z * keep) + np.asarray(mlp["b1"]), 0.0)
    m = np.asarray(mlp["w2"], dtype=np.float64) @ h + np.asarray(mlp["b2"], dtype=np.float64)
    return -theta * _softplus(m) / LN2


def softmax64(logits: np.ndarray) -> np.ndarray:
    logits = np.asarray(logits, dtype=np.float64).reshape(-1)
    exp = np.exp(logits - logits.max())
    return exp / exp.sum()


def load(path: Path) -> dict:
    bundle = json.loads(Path(path).read_text())
    if bundle.get("format") != FORMAT:
        raise ValueError(f"{path}: not a {FORMAT} bundle")
    return bundle


def load_deltas(bundle: Mapping, directory: Path) -> list[tuple[np.ndarray, np.ndarray] | None]:
    out = []
    for member in bundle["members"]:
        name = member.get("classifier_delta")
        if name:
            with np.load(Path(directory) / name) as npz:
                out.append((npz["weight"].astype(np.float64), npz["bias"].astype(np.float64)))
        else:
            out.append(None)
    return out


class FtResidual:
    """A loaded weights bundle on one Knowledge; `deltas` holds each member's classifier delta, if any."""

    def __init__(
        self,
        bundle: Mapping,
        knowledge: Knowledge,
        deltas: Sequence[tuple[np.ndarray, np.ndarray] | None] | None = None,
    ) -> None:
        if bundle.get("format") != FORMAT:
            raise ValueError(f"not a {FORMAT} bundle")
        if tuple(bundle["features"]) != FEATURES or tuple(bundle["covariates"]) != COVARIATES:
            raise ValueError("bundle features or covariates differ from this module's")
        if not bundle["members"]:
            raise ValueError("a bundle needs at least one member")
        self.bundle, self.knowledge = bundle, knowledge
        self.members = list(bundle["members"])
        self.deltas = list(deltas) if deltas is not None else [None] * len(self.members)
        if any(m.get("classifier_delta") for m in self.members) and not any(self.deltas):
            raise ValueError("this bundle has classifier deltas: load them with load_deltas")
        uses_embed = any(
            "neg_embed" in m["active_features"] and m["theta"][FEATURES.index("neg_embed")] > 0
            for m in self.members
        )
        if uses_embed and not knowledge.embedded:
            raise ValueError("neg_embed has a weight: the Knowledge needs v3.0's embeddings")

    @property
    def needs_pooled(self) -> bool:
        return any(d is not None for d in self.deltas)

    def weights(self, case_inputs: Mapping) -> np.ndarray:
        """[members, K]."""
        z = covariates(case_inputs).astype(np.float64)
        return np.stack([member_weights(m, z) for m in self.members])

    def residual(self, case_inputs: Mapping, pooled: np.ndarray | None = None) -> np.ndarray:
        """r [genes] float64: the mean over members of w · c, plus the classifier deltas' contribution."""
        w = self.weights(case_inputs)
        r = np.zeros(len(self.knowledge.genes), dtype=np.float64)
        if w.any():
            feats = self.knowledge.features(case_inputs).astype(np.float64)
            r = (w @ feats).mean(axis=0)
        if self.needs_pooled:
            if pooled is None:
                raise ValueError("this bundle has classifier deltas: pass v3.0's pooled vector")
            p = np.asarray(pooled, dtype=np.float64).reshape(-1)
            for d in self.deltas:
                if d is not None:
                    r = r + (d[0] @ p + d[1]) / len(self.members)
        return r

    def apply(self, logits: np.ndarray, case_inputs: Mapping, pooled: np.ndarray | None = None) -> np.ndarray:
        r = self.residual(case_inputs, pooled)
        logits = np.asarray(logits).reshape(-1)
        if not r.any():
            return softmax64(logits)
        return softmax64(logits.astype(np.float64) + r)
