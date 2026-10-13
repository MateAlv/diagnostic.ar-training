"""Simulator configurations: one frozen dataclass per ablation rung (PHASE3.md §2), hashed and recorded."""

from dataclasses import asdict, dataclass

from diagnostic_ar_training.lineage.hashing import sha256_json

# E0's empirical inputs (GraPhens@7aef83d data/simulation/phenotype_counts.csv and phenotype_distances.csv),
# regenerated bit for bit from SIM/demo.py: np.random.seed(42), then poisson(5, 1000) clipped at >= 1, and
# choice(4, 5000, p=[0.6, 0.25, 0.1, 0.05]).
E0_COUNT_HISTOGRAM = {
    1: 46,
    2: 84,
    3: 142,
    4: 168,
    5: 177,
    6: 140,
    7: 106,
    8: 69,
    9: 34,
    10: 22,
    11: 11,
    12: 1,
}
E0_DISTANCE_HISTOGRAM = {0: 2999, 1: 1271, 2: 474, 3: 256}

MAX_DISTANCE = 4
CATEGORIES = (
    "exact",
    *(f"anc{d}" for d in range(1, MAX_DISTANCE + 1)),
    *(f"desc{d}" for d in range(1, MAX_DISTANCE + 1)),
)
"""How a reported term relates to the gene's annotated profile: the term itself, an ancestor at shortest
distance d, or a descendant at depth d (d = 4 means 4 or more). Off-profile terms are none of these."""

RECIPES = ("e0", "disease")
FREQUENCY = ("uniform", "proportional", "fitted")
COUNTS = ("e0", "fitted")
CATEGORY_MODES = ("e0", "fitted")
OFF_PROFILE = ("none", "pooled", "neighbourhood", "mix")


def e0_category_shares() -> dict[str, float]:
    total = sum(E0_DISTANCE_HISTOGRAM.values())
    shares = dict.fromkeys(CATEGORIES, 0.0)
    shares["exact"] = E0_DISTANCE_HISTOGRAM[0] / total
    for d in range(1, 4):
        shares[f"anc{d}"] = E0_DISTANCE_HISTOGRAM[d] / total
    return shares


@dataclass(frozen=True)
class SimConfig:
    name: str
    recipe: str = "disease"
    """e0: E0's gene-level recipe; disease: pick one disease of the gene, then its findings."""
    frequency: str = "fitted"
    """uniform (gamma 0), proportional (gamma 1) or the fitted gamma and default frequency."""
    counts: str = "fitted"
    count_slope: bool = True
    """Scale the fitted term count with the gene's profile size (the fitted log-log slope)."""
    categories: str = "fitted"
    off_profile: str = "none"
    off_mix: float = 0.5
    """Share of off-profile terms drawn from the pooled vocabulary when off_profile is mix."""
    group_weight: float = 0.2
    """Weight of an ORPHA group or the no-disease pool when the gene has a specific disease."""
    covariates: bool = False
    max_tries: int = 20

    def __post_init__(self) -> None:
        for value, allowed in (
            (self.recipe, RECIPES),
            (self.frequency, FREQUENCY),
            (self.counts, COUNTS),
            (self.categories, CATEGORY_MODES),
            (self.off_profile, OFF_PROFILE),
        ):
            if value not in allowed:
                raise ValueError(f"{value!r} not in {allowed}")

    def as_dict(self) -> dict:
        return asdict(self)

    def config_hash(self) -> str:
        return sha256_json(self.as_dict())


PRESETS: dict[str, SimConfig] = {
    "e0": SimConfig("e0", recipe="e0", frequency="uniform", counts="e0", count_slope=False, categories="e0"),
    "freq": SimConfig("freq", frequency="fitted", counts="e0", count_slope=False, categories="e0"),
    "real": SimConfig("real"),
    "real_noise": SimConfig("real_noise", off_profile="pooled"),
}

VARIANTS: dict[str, SimConfig] = {
    "real_noise_nbhd": SimConfig("real_noise_nbhd", off_profile="neighbourhood"),
    "real_noise_mix": SimConfig("real_noise_mix", off_profile="mix"),
    "real_noslope": SimConfig("real_noslope", count_slope=False),
}
"""Options of a rung, validated next to the presets so every configuration tried is on record."""
