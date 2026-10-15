"""v4's post-processing layer in production: the add-on `p3-addon-v1-all` and the hard sex rule `sex-kb-v3`
on the 5,229 gene logits of the v4 network (`genphenia-v4.0`'s model.onnx).

Self-contained: numpy and the standard library only. It ships with `v4-layer-bundle.json.gz` (format
`v4-layer-bundle/1`), exported by diagnostic.ar-training (`dxt v4 release-layer`), and reproduces that repo's
F3 scoring (`v4.addon.Addon`, then `v4.sexrule.SexRule`) exactly (docs/HANDOFF-v4-prod.md there).

    layer = V4Layer(load("v4-layer-bundle.json.gz", sha256="..."))
    probs = layer.apply(network_logits, {"sex": "female", "age_years": 7.0, "onset_years": 2.0})

For each gene g of the network's vocabulary (`bundle["genes"]`, E0's output order):

    s = z + r,   r_g = mean over members m of (-Σ_k θ_mk f_k(case, g)),   θ_mk ≥ 0, f_k ≥ 0
    s_g -= max(s) - min(s) + 1   for every gene g the patient's sex cannot have (hard sex rule)
    probs = softmax(s)

- `z` is the network's logits. log-probabilities work as well: softmax and the rule's shift are invariant to
  adding one constant to every gene.
- The add-on's features `f_k`, each 0 when its input is unknown:
  - `sex_mismatch`: the gene is limited to the other sex (the add-on's knowledge, `p3-addon-kb-v1`);
  - `onset_strict_late`: 1 when the gene's strict earliest onset is later than the reference age;
  - `onset_strict_gap`, `onset_lenient_gap`: log1p of the years by which the strict / lenient earliest onset
    is later than the reference age (0 when it is not);
  - `xlr_female`: a female patient and a gene whose diseases are all X-linked recessive only.

  The reference age is the onset when known, else the current age; a negative value counts as 0, and a
  non-finite one as unknown. The features are rounded to float32, as in the evaluated code. The add-on's two
  negation features have θ = 0 in every member and are not shipped: excluded terms change nothing.
- The hard sex rule (`sex-kb-v3`) moves the genes a patient of the recorded sex cannot have below every other
  gene, keeping their order among themselves. Unknown sex changes nothing.
- No new input (unknown sex, no age, no onset) gives r = 0 and no blocked gene: `scores` then returns the
  logits as float64 and `apply` returns softmax(logits) in float64, bit for bit.

Case inputs: {"sex": "male" | "female" | anything else for unknown, "age_years": float | None,
"onset_years": float | None}. Other keys ("present", "excluded", ...) are ignored.
"""

import gzip
import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path

import numpy as np

FORMAT = "v4-layer-bundle/1"
FEATURES = ("sex_mismatch", "onset_strict_late", "onset_strict_gap", "onset_lenient_gap", "xlr_female")
SEXES = ("male", "female")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path, sha256: str | None = None) -> dict:
    """The bundle at `path` (.json or .json.gz); with `sha256`, refuse a file whose hash differs."""
    path = Path(path)
    if sha256 is not None and sha256_file(path) != sha256:
        raise ValueError(f"{path}: sha256 {sha256_file(path)}, expected {sha256}")
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        bundle = json.load(handle)
    if bundle.get("format") != FORMAT:
        raise ValueError(f"{path}: not a {FORMAT} bundle")
    return bundle


def softmax64(logits: np.ndarray) -> np.ndarray:
    logits = np.asarray(logits, dtype=np.float64).reshape(-1)
    exp = np.exp(logits - logits.max())
    return exp / exp.sum()


def sex_of(value) -> str | None:
    text = str(value).lower() if value is not None else ""
    return text if text in SEXES else None


def _years(value) -> float | None:
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def reference_age(case_inputs: Mapping) -> float | None:
    ref = _years(case_inputs.get("onset_years"))
    ref = _years(case_inputs.get("age_years")) if ref is None else ref
    return None if ref is None else max(ref, 0.0)


def _onsets(values) -> np.ndarray:
    return np.array([-np.inf if v is None else float(v) for v in values], dtype=np.float64)


def block(scores: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """float64 scores with the masked genes moved below every other gene, their own order kept."""
    out = np.asarray(scores, dtype=np.float64).reshape(-1).copy()
    mask = np.asarray(mask, dtype=bool)
    if mask.any() and not mask.all():
        out[mask] -= out.max() - out.min() + 1.0
    return out


class V4Layer:
    """A loaded bundle as arrays over the network's gene vocabulary; a case costs a few numpy operations."""

    def __init__(self, bundle: Mapping) -> None:
        if bundle.get("format") != FORMAT:
            raise ValueError(f"not a {FORMAT} bundle")
        addon = bundle["addon"]
        if tuple(addon["features"]) != FEATURES:
            raise ValueError(f"bundle features {addon['features']}; this module computes {FEATURES}")
        self.bundle = bundle
        self.genes = tuple(bundle["genes"])
        n = len(self.genes)
        self.theta = np.asarray(addon["theta"], dtype=np.float64)
        if self.theta.ndim != 2 or self.theta.shape[1] != len(FEATURES) or not np.all(self.theta >= 0):
            raise ValueError("theta must be [members, features], every weight non-negative")
        arrays = addon["arrays"]
        self.male = np.asarray(arrays["male_limited"], dtype=bool)
        self.female = np.asarray(arrays["female_limited"], dtype=bool)
        self.xlr = np.asarray(arrays["xlr_only"], dtype=bool)
        self.strict = _onsets(arrays["strict_onset_years"])
        self.lenient = _onsets(arrays["lenient_onset_years"])
        index = {g: i for i, g in enumerate(self.genes)}
        self.only = {s: np.zeros(n, dtype=bool) for s in SEXES}
        for sex in SEXES:
            self.only[sex][[index[g] for g in bundle["sex_rule"][f"{sex}_only"]]] = True
        arrays = (self.male, self.female, self.xlr, self.strict, self.lenient)
        if any(len(a) != n for a in arrays):
            raise ValueError("every per-gene array must follow the gene vocabulary")

    def features(self, case_inputs: Mapping) -> np.ndarray:
        """[len(FEATURES), genes] float32."""
        f = np.zeros((len(FEATURES), len(self.genes)), dtype=np.float32)
        sex = sex_of(case_inputs.get("sex"))
        if sex:
            f[0] = self.female if sex == "male" else self.male
            f[4] = self.xlr if sex == "female" else 0
        ref = reference_age(case_inputs)
        if ref is not None:
            strict_gap = np.clip(self.strict - ref, 0.0, None)
            f[1] = strict_gap > 0
            f[2] = np.log1p(strict_gap)
            f[3] = np.log1p(np.clip(self.lenient - ref, 0.0, None))
        return f

    def residual(self, case_inputs: Mapping) -> np.ndarray:
        """r [genes] float64, every entry ≤ 0."""
        return ((-self.theta) @ self.features(case_inputs).astype(np.float64)).mean(axis=0)

    def blocked(self, sex) -> np.ndarray:
        """Genes impossible for this sex (those limited to the other one); none when the sex is unknown."""
        sex = sex_of(sex)
        if sex is None:
            return np.zeros(len(self.genes), dtype=bool)
        return self.only["female" if sex == "male" else "male"]

    def scores(self, logits: np.ndarray, case_inputs: Mapping) -> np.ndarray:
        """F3's float64 scores from the network's logits (or log-probabilities) in `genes` order."""
        base = np.asarray(logits, dtype=np.float64).reshape(-1)
        if base.size != len(self.genes):
            raise ValueError(f"{base.size} scores for {len(self.genes)} genes")
        r = self.residual(case_inputs)
        s = base + r if r.any() else base
        mask = self.blocked(case_inputs.get("sex"))
        return block(s, mask) if mask.any() else s

    def apply(self, logits: np.ndarray, case_inputs: Mapping) -> np.ndarray:
        """Probabilities over `genes`: softmax of `scores`."""
        return softmax64(self.scores(logits, case_inputs))


def apply(logits: np.ndarray, case_inputs: Mapping, bundle: Mapping) -> np.ndarray:
    """One-off form of `V4Layer(bundle).apply`; keep a V4Layer instance to score many cases."""
    return V4Layer(bundle).apply(logits, case_inputs)
