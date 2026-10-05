"""Write the EXP-B-006 arms: the rr-v1 formula and the same formula plus onset, on one KB.

Usage: python scripts/exp_b006_arms.py OUT.json KB_ID W

The first arm (rr-v1) drives the interview; the second adds the `onset` weight W. rr-v1[neg=0.5] has
config hash 8488e32fc7c2 on kb-v5 and fe58053033fa on kb-v3 (the KB inside rerank-v1.0.0).
"""

import json
import sys
from pathlib import Path

from diagnostic_ar_training.eval.dev_search import Arm
from diagnostic_ar_training.rerank.config import RerankConfig, rr_v1_reference

RR_V1_KB5_HASH = "8488e32fc7c2"
RR_V1_KB3_HASH = "fe58053033fa"


def arms(kb_id: str, w: float) -> list[Arm]:
    reference = rr_v1_reference(kb_id)
    candidate = RerankConfig.from_dict({**reference.to_dict(), "weights": {**reference.weights, "onset": w}})
    return [
        Arm("rr-v1", "B6", reference, "production formula; drives the interview"),
        Arm(f"rr-v1+onset{w:g}", "B6", candidate, f"rr-v1 with onset weight {w:g}"),
    ]


def main(out: Path, kb_id: str, w: float) -> None:
    expected = {"kb-v5": RR_V1_KB5_HASH, "kb-v3": RR_V1_KB3_HASH}
    result = arms(kb_id, w)
    if kb_id in expected and result[0].config.config_hash != expected[kb_id]:
        raise SystemExit(f"rr-v1 hash is {result[0].config.config_hash}, expected {expected[kb_id]}")
    out.write_text(json.dumps([a.to_dict() for a in result], indent=1, sort_keys=True) + "\n")
    for a in result:
        print(a.arm_id, a.config.config_hash)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]), sys.argv[2], float(sys.argv[3]))
