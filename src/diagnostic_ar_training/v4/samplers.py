"""The simulator v4 trains on, as an interface: `sim4.Sampler` or anything with the same surface.

A configuration names its sampler by `sim.factory` (`module:callable`), called as
`callable(preset, params_path)`. The default, `sim4`, is the only place that knows how sim4 builds a
Sampler; tests and scratch runs pass their own factory.
"""

import importlib
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

from diagnostic_ar_training.v4.config import SimConfig, resolve


@runtime_checkable
class Sampler(Protocol):
    genes: tuple[str, ...] | list[str]
    """E0's gene symbols, in E0's order."""
    simulable_gene_indices: np.ndarray | list[int] | tuple[int, ...]

    def sample(self, gene_index: int, rng: np.random.Generator) -> list[str]:
        """Present HPO ids of one simulated patient of that gene."""
        ...


def sample_covariates(
    sampler, gene_index: int, rng: np.random.Generator
) -> tuple[str, float | None, float | None]:
    """(sex, age_years, onset_years) when the sampler simulates them, else unknown."""
    fn = getattr(sampler, "sample_covariates", None)
    if fn is None:
        return "unknown", None, None
    return fn(gene_index, rng)


def sim4(preset: str, params: Path | None) -> Sampler:
    from diagnostic_ar_training.sim4 import PRESETS, FittedParams, Sampler, load_knowledge

    if preset not in PRESETS:
        raise ValueError(f"unknown sim4 preset {preset!r}; one of {sorted(PRESETS)}")
    fitted = FittedParams.load(params) if params is not None else None
    return Sampler(load_knowledge(), fitted, PRESETS[preset])


def build(sim: SimConfig) -> Sampler:
    module_name, _, attr = sim.factory.partition(":")
    if not attr:
        raise ValueError(f"sim.factory {sim.factory!r} must be 'module:callable'")
    factory = getattr(importlib.import_module(module_name), attr)
    sampler = factory(sim.preset, resolve(sim.params) if sim.params else None)
    if not isinstance(sampler, Sampler):
        raise TypeError(f"{sim.factory} returned {type(sampler).__name__}, not a Sampler")
    return sampler


def check_genes(sampler: Sampler, genes: tuple[str, ...]) -> None:
    if tuple(sampler.genes) != tuple(genes):
        raise ValueError("the sampler's genes are not E0's genes in E0's order")


def gene_pool(sampler: Sampler, drop_dash: bool) -> np.ndarray:
    pool = np.unique(np.asarray(sampler.simulable_gene_indices, dtype=np.int64))
    if drop_dash:
        pool = pool[pool != 0]
    if pool.size == 0:
        raise ValueError("the sampler has no simulable gene")
    return pool
