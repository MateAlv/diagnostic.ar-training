import numpy as np

from diagnostic_ar_training.eval.metrics import paired_bootstrap


def test_level_ci_is_wider_and_uses_the_same_draws():
    rng = np.random.default_rng(1)
    base = rng.integers(1, 50, size=300).astype(float)
    new = np.maximum(base - rng.integers(0, 3, size=300), 1)
    groups = [f"g{i // 3}" for i in range(300)]
    plain = paired_bootstrap(base, new, groups=groups)
    wide = paired_bootstrap(base, new, groups=groups, level=1 - 0.05 / 3)
    assert wide["ci95"] == plain["ci95"] and "ci" not in plain
    assert wide["ci"][0] <= plain["ci95"][0] and wide["ci"][1] >= plain["ci95"][1]
