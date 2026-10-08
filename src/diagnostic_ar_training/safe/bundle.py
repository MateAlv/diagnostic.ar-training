"""safe-v1 as a self-contained bundle: one JSON file and the pure-numpy `apply` below.

This module imports only numpy and the standard library, so diagnostic.ar-model can ship it next to the model
unchanged. `SafeV1` (safe/system.py) scores through this same code, so what was evaluated is what ships.

Bundle format (`format: safe-v1-bundle/1`), one JSON object:
- `kb_id`: the knowledge artifact it was exported from; `negation_factor`: 0.1.
- `onset_factor` (optional): when present, onset-incompatible genes are multiplied by it instead of being
  blocked (step 2 then covers only the sex rule).
- `genes`: {symbol: {"sex": "male" | "female", "earliest_onset_years": float}}; each key is present only when
  the rule applies to the gene. `sex` names the only sex the gene's diseases affect.
- `obligate`: {symbol: {disease id: [HPO ids]}}, only for genes whose every annotated disease has at least one
  obligate phenotype (any other gene can never be contradicted).
- `ancestors_or_self`: {obligate HPO id: [the id and all its is_a ancestors]}.

`apply(probs, genes, case_inputs, bundle)` takes E0's distribution over `genes` and the case inputs
{"sex": "male" | "female" | anything else for unknown, "onset_years": float | None,
"age_years": float | None, "excluded": [HPO ids]}:
1. Negation: genes the excluded terms contradict are multiplied by `negation_factor`, then renormalised.
   A gene is contradicted when every annotated disease of it has an obligate phenotype whose
   ancestors-or-self include an excluded term.
2. Hard block: genes limited to the other sex (sex known) and genes whose earliest onset is later than the
   reference age (onset if known, else current age; negative values count as 0) go below every other gene,
   keeping their order: the block is scaled by a power of two until its largest probability is at most
   half the smallest kept one, then everything is renormalised.
When no gene is changed, the input array is returned as is, bit for bit.
"""

import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

import numpy as np

FORMAT = "safe-v1-bundle/1"
RULES = ("sex", "onset", "negation")
NEGATION_FACTOR = 0.1


def export(
    kb: dict, kb_id: str, negation_factor: float = NEGATION_FACTOR, onset_factor: float | None = None
) -> dict:
    """The bundle of a safe knowledge artifact (`safe-kb/1`)."""
    genes, obligate = {}, {}
    for symbol, record in sorted(kb["genes"].items()):
        entry = {}
        if "sex" in record:
            entry["sex"] = record["sex"]["limit"]
        if "onset" in record:
            entry["earliest_onset_years"] = record["onset"]["earliest_years"]
        if entry:
            genes[symbol] = entry
        ob = record.get("obligate", {})
        if ob and all(ob.values()):
            obligate[symbol] = ob
    used = {t for ob in obligate.values() for terms in ob.values() for t in terms}
    return {
        "format": FORMAT,
        "kb_id": kb_id,
        "negation_factor": negation_factor,
        **({} if onset_factor is None else {"onset_factor": onset_factor}),
        "genes": genes,
        "obligate": obligate,
        "ancestors_or_self": {t: a for t, a in sorted(kb["ancestors_or_self"].items()) if t in used},
    }


def load(path: Path) -> dict:
    bundle = json.loads(Path(path).read_text())
    if bundle.get("format") != FORMAT:
        raise ValueError(f"{path}: not a {FORMAT} bundle")
    return bundle


def _sex(value) -> str | None:
    text = str(value).lower() if value is not None else ""
    return text if text in ("male", "female") else None


class SafeRules:
    """A loaded bundle, with per-vocabulary arrays cached so each case costs a few numpy operations."""

    def __init__(self, bundle: Mapping) -> None:
        if bundle.get("format") != FORMAT:
            raise ValueError(f"not a {FORMAT} bundle")
        self.bundle = bundle
        self.negation_factor = float(bundle["negation_factor"])
        onset_factor = bundle.get("onset_factor")
        self.onset_factor = None if onset_factor is None else float(onset_factor)
        covers: dict[str, set[str]] = {}
        for term, ancestors in bundle["ancestors_or_self"].items():
            for a in ancestors:
                covers.setdefault(a, set()).add(term)
        self._covers = covers
        self._vocab: dict[tuple[str, ...], dict] = {}

    def _arrays(self, genes: Sequence[str]) -> dict:
        key = tuple(genes)
        if key not in self._vocab:
            info = self.bundle["genes"]
            self._vocab[key] = {
                "male": np.array([info.get(g, {}).get("sex") == "male" for g in key]),
                "female": np.array([info.get(g, {}).get("sex") == "female" for g in key]),
                "onset": np.array(
                    [info.get(g, {}).get("earliest_onset_years", -np.inf) for g in key], dtype=np.float64
                ),
                "negatable": [
                    (i, [set(terms) for terms in self.bundle["obligate"][g].values()])
                    for i, g in enumerate(key)
                    if g in self.bundle["obligate"]
                ],
            }
        return self._vocab[key]

    def masks(
        self, genes: Sequence[str], case_inputs: Mapping, rules: Iterable[str] = RULES
    ) -> tuple[np.ndarray, np.ndarray]:
        """(contradicted, blocked) boolean masks over `genes`; onset-incompatible genes count as blocked."""
        contradicted, blocked, late = self._masks(genes, case_inputs, rules)
        return contradicted, blocked | late

    def _masks(
        self, genes: Sequence[str], case_inputs: Mapping, rules: Iterable[str] = RULES
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(contradicted, sex-blocked, onset-incompatible) boolean masks over `genes`."""
        rules = set(rules)
        if unknown := rules - set(RULES):
            raise ValueError(f"unknown rules {sorted(unknown)}")
        arr = self._arrays(genes)
        n = len(arr["onset"])
        contradicted, blocked, late = (
            np.zeros(n, dtype=bool),
            np.zeros(n, dtype=bool),
            np.zeros(n, dtype=bool),
        )
        excluded = set(case_inputs.get("excluded") or ())
        if "negation" in rules and excluded:
            covered = set().union(*(self._covers.get(e, ()) for e in excluded))
            if covered:
                for i, diseases in arr["negatable"]:
                    if all(terms & covered for terms in diseases):
                        contradicted[i] = True
        sex = _sex(case_inputs.get("sex"))
        if "sex" in rules and sex:
            blocked |= arr["male"] if sex == "female" else arr["female"]
        if "onset" in rules:
            ref = case_inputs.get("onset_years")
            ref = case_inputs.get("age_years") if ref is None else ref
            if ref is not None:
                late = arr["onset"] > max(float(ref), 0.0)
        return contradicted, blocked, late

    def changes(
        self, genes: Sequence[str], case_inputs: Mapping, rules: Iterable[str] = RULES
    ) -> tuple[np.ndarray | None, np.ndarray]:
        """(per-gene factors, or None when no gene is scaled; hard-blocked mask)."""
        contradicted, blocked, late = self._masks(genes, case_inputs, rules)
        if self.onset_factor is None:
            blocked, late = blocked | late, np.zeros_like(late)
        if not (contradicted.any() or late.any()):
            return None, blocked
        factors = np.where(contradicted, self.negation_factor, 1.0) * np.where(
            late, self.onset_factor or 1.0, 1.0
        )
        return factors, blocked

    def apply(
        self, probs: np.ndarray, genes: Sequence[str], case_inputs: Mapping, rules: Iterable[str] = RULES
    ) -> np.ndarray:
        factors, blocked = self.changes(genes, case_inputs, rules)
        return rescale_factors(probs, factors, blocked)


def rescale(probs: np.ndarray, contradicted: np.ndarray, blocked: np.ndarray, factor: float) -> np.ndarray:
    """Apply the negation factor and the hard block; return `probs` itself when nothing changes."""
    factors = np.where(contradicted, factor, 1.0) if contradicted.any() else None
    return rescale_factors(probs, factors, blocked)


def rescale_factors(probs: np.ndarray, factors: np.ndarray | None, blocked: np.ndarray) -> np.ndarray:
    """Multiply by per-gene `factors`, then apply the hard block; `probs` itself if nothing changes."""
    out = None
    if factors is not None:
        out = np.asarray(probs, dtype=np.float64) * factors
        out /= out.sum()
    if blocked.any() and not blocked.all():
        p = np.asarray(probs, dtype=np.float64) if out is None else out
        kept_min, block_max = p[~blocked].min(), p[blocked].max()
        if block_max >= kept_min:
            p = p.copy() if out is None else p
            if kept_min > 0:
                k = max(int(np.ceil(np.log2(block_max) - np.log2(kept_min))) + 1, 1)
                while block_max * 2.0**-k > kept_min / 2:
                    k += 1
                p[blocked] *= 2.0**-k
            else:
                # Nothing fits below a zero: the block ties with the zero genes, which ranks it after them.
                p[blocked] = 0.0
            total = p.sum()
            out = p / total if total > 0 else np.full(p.size, 1.0 / p.size)
    return probs if out is None else out


def apply(probs: np.ndarray, genes: Sequence[str], case_inputs: Mapping, bundle: Mapping) -> np.ndarray:
    """One-off form of `SafeRules(bundle).apply`; keep a SafeRules instance to score many cases."""
    return SafeRules(bundle).apply(probs, genes, case_inputs)
