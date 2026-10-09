"""ft-v1.1 in production: GenPhenAI v3.0's (E0's) gene scores plus a residual that can only lower a gene.

Self-contained: numpy and the standard library only. It ships with `ft-v1.1-prod-bundle.json.gz`
(format `ft-v1.1-prod-bundle/1`), exported by diagnostic.ar-training (`dxt ft prod-package`), and reproduces
that repo's `FtV1` scoring to within 1e-9 (docs/HANDOFF-ft-v1.1-prod.md there).

    model = FtProd(load("ft-v1.1-prod-bundle.json.gz", sha256="..."))
    probs = model.apply(e0_logits, {"sex": "female", "age_years": 7.0, "onset_years": 2.0,
                                    "excluded": ["HP:0001250"]})

For each gene g of E0's vocabulary (`bundle["genes"]`, E0's output order):

    probs = softmax(z + r),   r_g = -Σ_k θ_k f_k(case, g),   θ_k ≥ 0, f_k ≥ 0

- `z` is E0's logits. log(E0's probabilities) works as well: softmax is invariant to adding a constant to
  every gene, and log p = z - logsumexp(z). `apply_probs` takes the probabilities themselves.
- The features `f_k`, each 0 when its input is unknown:
  - `sex_mismatch`: the gene is limited to the other sex;
  - `onset_strict_late`: 1 when the gene's strict earliest onset is later than the reference age;
  - `onset_strict_gap`: log1p of the years by which it is later (0 when it is not);
  - `xlr_female`: a female patient and a gene whose diseases are all X-linked recessive (HP:0001419) only;
  - `neg_obligate`: every annotated disease of the gene has an obligate phenotype that an excluded term
    covers (the excluded term is the phenotype or one of its ancestors).

  The reference age is the onset when known, else the current age; a negative value counts as 0, and a
  non-finite one as unknown. The features are rounded to float32, as in the evaluated code.
- No new input (unknown sex, no age, no onset, no excluded term) gives r = 0: `apply` then returns
  softmax(z) in float64, and `apply_probs` returns its input array itself.

Case inputs: {"sex": "male" | "female" | anything else for unknown, "age_years": float | None,
"onset_years": float | None, "excluded": [HPO ids of the 2026-02-16 release]}. Other keys are ignored. An
excluded id the bundle does not know changes nothing.
"""

import gzip
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np

FORMAT = "ft-v1.1-prod-bundle/1"
FEATURES = ("sex_mismatch", "onset_strict_late", "onset_strict_gap", "xlr_female", "neg_obligate")


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


def _sex(value) -> str | None:
    text = str(value).lower() if value is not None else ""
    return text if text in ("male", "female") else None


def _years(value) -> float | None:
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def reference_age(case_inputs: Mapping) -> float | None:
    ref = _years(case_inputs.get("onset_years"))
    ref = _years(case_inputs.get("age_years")) if ref is None else ref
    return None if ref is None else max(ref, 0.0)


class FtProd:
    """A loaded bundle as arrays over E0's gene vocabulary; each case costs a few numpy operations."""

    def __init__(self, bundle: Mapping) -> None:
        if bundle.get("format") != FORMAT:
            raise ValueError(f"not a {FORMAT} bundle")
        if tuple(bundle["features"]) != FEATURES:
            raise ValueError(f"bundle features {bundle['features']}; this module computes {FEATURES}")
        self.bundle = bundle
        self.genes = tuple(bundle["genes"])
        n = len(self.genes)
        self.theta = np.asarray(bundle["theta"], dtype=np.float64)
        if self.theta.shape != (len(FEATURES),) or not np.all(self.theta >= 0):
            raise ValueError("theta must have one non-negative weight per feature")
        arrays = bundle["arrays"]
        self.male = np.asarray(arrays["male_limited"], dtype=bool)
        self.female = np.asarray(arrays["female_limited"], dtype=bool)
        self.xlr = np.asarray(arrays["xlr_only"], dtype=bool)
        self.strict = np.array(
            [-np.inf if v is None else float(v) for v in arrays["strict_onset_years"]], dtype=np.float64
        )
        if any(len(a) != n for a in (self.male, self.female, self.xlr, self.strict)):
            raise ValueError("every per-gene array must follow the gene vocabulary")
        index = {g: i for i, g in enumerate(self.genes)}
        self.negatable = [
            (index[g], [frozenset(terms) for terms in diseases.values()])
            for g, diseases in sorted(bundle["obligate"].items())
        ]
        covers: dict[str, set[str]] = {}
        for term, ancestors in bundle["ancestors_or_self"].items():
            for a in ancestors:
                covers.setdefault(a, set()).add(term)
        self._covers = covers

    def contradicted(self, excluded: Sequence[str]) -> np.ndarray:
        out = np.zeros(len(self.genes), dtype=bool)
        covered = set().union(*(self._covers.get(e, ()) for e in set(excluded or ())))
        if covered:
            for i, diseases in self.negatable:
                if all(terms & covered for terms in diseases):
                    out[i] = True
        return out

    def features(self, case_inputs: Mapping) -> np.ndarray:
        """[len(FEATURES), genes] float32."""
        f = np.zeros((len(FEATURES), len(self.genes)), dtype=np.float32)
        sex = _sex(case_inputs.get("sex"))
        if sex:
            f[0] = self.female if sex == "male" else self.male
            f[3] = self.xlr if sex == "female" else 0
        ref = reference_age(case_inputs)
        if ref is not None:
            gap = np.clip(self.strict - ref, 0.0, None)
            f[1] = gap > 0
            f[2] = np.log1p(gap)
        excluded = list(case_inputs.get("excluded") or ())
        if excluded:
            f[4] = self.contradicted(excluded)
        return f

    def residual(self, case_inputs: Mapping) -> np.ndarray:
        """r [genes] float64, every entry ≤ 0."""
        return -(self.theta @ self.features(case_inputs).astype(np.float64))

    def apply(self, logits: np.ndarray, case_inputs: Mapping) -> np.ndarray:
        """Probabilities over `genes` from E0's logits (or log-probabilities) in the same order."""
        logits = np.asarray(logits).reshape(-1)
        if logits.size != len(self.genes):
            raise ValueError(f"{logits.size} scores for {len(self.genes)} genes")
        r = self.residual(case_inputs)
        if not r.any():
            return softmax64(logits)
        return softmax64(logits.astype(np.float64) + r)

    def apply_probs(self, probs: np.ndarray, case_inputs: Mapping) -> np.ndarray:
        """The same distribution from E0's probabilities; `probs` itself when no gene changes."""
        if np.asarray(probs).size != len(self.genes):
            raise ValueError(f"{np.asarray(probs).size} probabilities for {len(self.genes)} genes")
        r = self.residual(case_inputs)
        if not r.any():
            return probs
        out = np.asarray(probs, dtype=np.float64).reshape(-1) * np.exp(r - r.max())
        return out / out.sum()


def apply(logits: np.ndarray, case_inputs: Mapping, bundle: Mapping) -> np.ndarray:
    """One-off form of `FtProd(bundle).apply`; keep an FtProd instance to score many cases."""
    return FtProd(bundle).apply(logits, case_inputs)
