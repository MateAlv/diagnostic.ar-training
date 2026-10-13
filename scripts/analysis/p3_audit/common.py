import json
import os
import pickle
from pathlib import Path

import numpy as np

DATA = Path(os.environ.get("P3_AUDIT_DATA", "data/interim/p3-audit"))


def load():
    d = pickle.load(open(DATA / "cases.pkl", "rb"))
    meta = d["meta"]
    sim = {r["case_id"]: r for r in json.load(open(DATA / "sim_ranks.json"))}
    for m in meta:
        m["sim"] = sim[m["case_id"]]
    return d["genes"], meta


def rr(ranks):
    r = np.array([np.nan if x is None else x for x in ranks], dtype=float)
    return np.where(np.isnan(r), 0.0, 1.0 / np.where(np.isnan(r), 1.0, r)), r


def summary(ranks, sel):
    rec, r = rr(ranks)
    r = np.where(np.isnan(r), np.inf, r)
    return {
        "mrr": float(rec[sel].mean()) if sel.any() else float("nan"),
        "top1": float((r[sel] <= 1).mean()) if sel.any() else float("nan"),
        "top10": float((r[sel] <= 10).mean()) if sel.any() else float("nan"),
    }


class Boot:
    def __init__(self, groups, n=2000, seed=0):
        self.uniq, self.inv = np.unique(np.asarray(groups), return_inverse=True)
        self.idx = np.random.default_rng(seed).integers(0, len(self.uniq), size=(n, len(self.uniq)))

    def ci_mean(self, x, sel):
        g = len(self.uniq)
        s = np.bincount(self.inv, weights=np.where(sel, x, 0.0), minlength=g)
        c = np.bincount(self.inv, weights=sel.astype(float), minlength=g)
        est = s[self.idx].sum(1) / np.maximum(c[self.idx].sum(1), 1)
        return [float(v) for v in np.percentile(est, [2.5, 97.5])]

    def compare(self, a_ranks, b_ranks, sel):
        """Delta of b vs a (b - a)."""
        ra, _ = rr(a_ranks)
        rb, _ = rr(b_ranks)
        d = rb - ra
        return {
            "n": int(sel.sum()),
            "pubs": int(len(set(self.inv[sel]))),
            "a_mrr": float(ra[sel].mean()),
            "b_mrr": float(rb[sel].mean()),
            "delta": float(d[sel].mean()),
            "ci": self.ci_mean(d, sel),
            "helped": float((d[sel] > 1e-12).mean()),
            "harmed": float((d[sel] < -1e-12).mean()),
        }


def fmt(x, p=3):
    return f"{x:.{p}f}"
