"""Write the EXP-B-005 arms: F, and F + onset w for the given weights.

Usage: python scripts/exp_b005_arms.py OUT.json W [W ...]
The first arm is F (config hash 8ecd5b320f33, EXP-B-004's reference); it drives the interview.
"""

import json
import sys
from pathlib import Path

from diagnostic_ar_training.eval.dev_search import Arm
from diagnostic_ar_training.rerank.config import RerankConfig

F_HASH = "8ecd5b320f33"
F_CONFIG = Path("results/EXP-B-004/sealed-configs/F.json")


def main(out: Path, weights: list[float]) -> None:
    f = RerankConfig.from_dict(json.loads(F_CONFIG.read_text()))
    if f.config_hash != F_HASH:
        raise SystemExit(f"F hash is {f.config_hash}, expected {F_HASH}")
    arms = [Arm("F", "B5", f, "reference re-ranker; drives the interview")]
    for w in weights:
        config = RerankConfig.from_dict({**f.to_dict(), "weights": {**f.weights, "onset": w}})
        arms.append(Arm(f"F+onset{w:g}", "B5", config, f"F with onset weight {w:g}"))
    out.write_text(json.dumps([a.to_dict() for a in arms], indent=1, sort_keys=True) + "\n")
    for a in arms:
        print(a.arm_id, a.config.config_hash)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]), [float(x) for x in sys.argv[2:]])
