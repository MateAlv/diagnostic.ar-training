"""Re-slice Phase 1 Front A / Track 4 R1-dev ranks by cited vs uncited (descriptive, dev only)."""
import glob, json, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).parent))
from common import Boot, load

genes, meta = load()
dev = [m for m in meta if m["part"] == "dev"]
ids = [m["case_id"] for m in dev]
e0 = [m["e0_rank"] for m in dev]
groups = [m["group"] for m in dev]
cited = np.array([m["cited"] for m in dev])
inv = np.array([m["in_vocab"] for m in dev])
b = Boot(groups)
root = Path(sys.argv[1])
files = sorted(glob.glob(str(root / "results/EXP-A-00*/*/r1-v1-dev*present.ranks.jsonl"))) + sorted(glob.glob(str(root / "results/EXP-P-007/**/*dev*ranks.jsonl"), recursive=True))
for f in files:
    rk = {}
    for line in open(f):
        r = json.loads(line); rk[r["case_id"]] = r.get("rank")
    if not all(i in rk for i in ids):
        print("skip (case mismatch)", f, len(rk)); continue
    a = [rk[i] for i in ids]
    out = []
    for name, sel in [("all", np.ones(len(ids), bool)), ("cited", cited), ("uncited", ~cited), ("uncited&inV", ~cited & inv)]:
        c = b.compare(e0, a, sel)
        out.append(f"{name}: {c['b_mrr']:.3f} vs {c['a_mrr']:.3f} d={c['delta']:+.4f} [{c['ci'][0]:+.4f},{c['ci'][1]:+.4f}]")
    print(f.split("results/")[1]); print("   " + " | ".join(out))
