"""HPOA frequency of one (disease, term), with every zero row dropped first (ADR-0019 §4).

Provenance: `HPO_FREQUENCY_MIDPOINTS`, `ParsedFrequencies`, `parse_frequencies`, `jeffreys_mean` and the
precedence of `estimate_frequency` are copied from rare-disease-simulator,
src/rare_disease_simulator/profiles/frequency.py, commit cfc20da78df229a92c14d7f414c3451c91673444 (the
ADR-0007 convention this repo shares). Changes: `is_zero_frequency` and `pooled_frequency` drop 0/n, 0% and
HP:0040285 rows before pooling (that module pooled a 0/n row into the counts); only the point estimate is
kept (no interval or category label).
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

EXCLUDED = "HP:0040285"

HPO_FREQUENCY_MIDPOINTS: dict[str, float] = {
    "HP:0040280": 1.0,
    "HP:0040281": 0.895,
    "HP:0040282": 0.545,
    "HP:0040283": 0.17,
    "HP:0040284": 0.025,
}

_RATIO_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")
_PERCENT_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*%\s*$")


@dataclass(frozen=True)
class ParsedFrequencies:
    """HPOA frequency values of one (disease, term), split by notation."""

    ratios: tuple[tuple[int, int], ...] = ()
    percents: tuple[float, ...] = ()
    categories: tuple[str, ...] = ()
    unparsed: int = 0


def is_zero_frequency(value: str | None) -> bool:
    """A literature negation written as a frequency: 0/n, 0% or HP:0040285 (Excluded)."""
    value = (value or "").strip()
    if value == EXCLUDED:
        return True
    if ratio := _RATIO_RE.match(value):
        return int(ratio.group(1)) == 0
    if percent := _PERCENT_RE.match(value):
        return float(percent.group(1)) == 0.0
    return False


def parse_frequencies(values: Iterable[str | None]) -> ParsedFrequencies:
    """Split raw HPOA frequency values by notation; empty values are skipped."""
    ratios: list[tuple[int, int]] = []
    percents: list[float] = []
    categories: list[str] = []
    unparsed = 0
    for value in values:
        if not value:
            continue
        if value in HPO_FREQUENCY_MIDPOINTS:
            categories.append(value)
            continue
        ratio = _RATIO_RE.match(value)
        if ratio and int(ratio.group(2)) > 0:
            numerator, denominator = int(ratio.group(1)), int(ratio.group(2))
            ratios.append((min(numerator, denominator), denominator))
            continue
        percent = _PERCENT_RE.match(value)
        if percent:
            percents.append(min(float(percent.group(1)) / 100.0, 1.0))
            continue
        unparsed += 1
    return ParsedFrequencies(tuple(ratios), tuple(percents), tuple(categories), unparsed)


def jeffreys_mean(successes: int, trials: int) -> float:
    """Posterior mean of a Binomial proportion under the Jeffreys Beta(1/2, 1/2) prior."""
    return (successes + 0.5) / (trials + 1.0)


def estimate_frequency(parsed: ParsedFrequencies) -> float | None:
    """ADR-0007 precedence: pooled counts (Jeffreys mean), then mean percentage, then mean category
    midpoint; None means unknown, never "always"."""
    if parsed.ratios:
        return jeffreys_mean(sum(n for n, _ in parsed.ratios), sum(m for _, m in parsed.ratios))
    if parsed.percents:
        return sum(parsed.percents) / len(parsed.percents)
    if parsed.categories:
        return sum(HPO_FREQUENCY_MIDPOINTS[t] for t in parsed.categories) / len(parsed.categories)
    return None


def pooled_frequency(values: Iterable[str | None]) -> float | None:
    """The frequency of a (disease, term) from all its rows, zero rows dropped before pooling."""
    return estimate_frequency(parse_frequencies(v for v in values if not is_zero_frequency(v)))
