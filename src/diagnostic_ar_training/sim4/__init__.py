"""sim4: a minimal, pristine patient simulator for GenPhenAI v4.0 (ADR-0019, docs/analyses/SIM4-v1.md).

Knowledge is E0's own (HPO 2025-03-03 and E0's genes_to_phenotype) without literature negations; the only
statistics taken from patients are global and low-dimensional (`fit`).
"""

from diagnostic_ar_training.sim4 import folds
from diagnostic_ar_training.sim4.config import PRESETS, SimConfig
from diagnostic_ar_training.sim4.fit import FittedParams, fit
from diagnostic_ar_training.sim4.knowledge import Knowledge, load_knowledge
from diagnostic_ar_training.sim4.sampler import Sampler, SimulatedCase

__all__ = [
    "PRESETS",
    "FittedParams",
    "Knowledge",
    "Sampler",
    "SimConfig",
    "SimulatedCase",
    "fit",
    "folds",
    "load_knowledge",
]
