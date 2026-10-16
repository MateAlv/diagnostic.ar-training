"""How far each system's top-1 probability can be read as a chance of being right, folds 0-3 out of fold
(the cross-fitted networks of P3-BATCH1-DIAG §11, a proxy for R5x-f4; E0 on the same patients). Uncapped, per
patient. Writes results/P3/addon/calibration.json.
Run under a memory cap: `systemd-run --user --scope -p MemoryMax=8G -p MemorySwapMax=0`."""

import json

import numpy as np

from diagnostic_ar_training import REPO_ROOT
from diagnostic_ar_training.v4 import addon, patients

EDGES = (0.0, 0.5, 0.8, 0.95, 0.99, 1.0)
OUT = REPO_ROOT / "results" / "P3" / "addon" / "calibration.json"


def softmax(logits: np.ndarray) -> np.ndarray:
    z = logits.astype(np.float64)
    z -= z.max(axis=1, keepdims=True)
    p = np.exp(z)
    return p / p.sum(axis=1, keepdims=True)


def summary(conf: np.ndarray, hit: np.ndarray) -> dict:
    bins, ece = [], 0.0
    for lo, hi in zip(EDGES[:-1], EDGES[1:], strict=True):
        s = (conf >= lo) & ((conf < hi) if hi < 1 else (conf <= hi))
        if not s.any():
            continue
        gap = abs(conf[s].mean() - hit[s].mean())
        ece += gap * s.sum() / len(conf)
        mean_conf, acc = float(conf[s].mean()), float(hit[s].mean())
        bins.append({"from": lo, "to": hi, "n": int(s.sum()), "mean_conf": mean_conf, "acc": acc})
    acc = float(hit.mean())
    return {"n": len(conf), "mean_conf": float(conf.mean()), "top1_acc": acc, "ece": ece, "bins": bins}


members = {p.case_id: p for p in patients.load_addon((0, 1, 2, 3))}
rows = {"network": ([], [], []), "E0": ([], [], [])}
for k in range(4):
    with np.load(addon.ADDON_DIR / f"logits-f{k}.npz") as z:
        genes, ids, ok = list(z["genes"]), z["case_id"], z["net_ok"] & z["e0_ok"]
        index = {g: i for i, g in enumerate(genes)}
        keep = [i for i, c in enumerate(ids) if ok[i] and members[str(c)].case.gene in index]
        truth = np.array([index[members[str(ids[i])].case.gene] for i in keep])
        uncited = [members[str(ids[i])].status.startswith("uncited") for i in keep]
        for name, key in (("network", "net"), ("E0", "e0")):
            p = softmax(z[key][keep])
            rows[name][0].extend(p.max(axis=1))
            rows[name][1].extend(p.argmax(axis=1) == truth)
            rows[name][2].extend(uncited)
            del p

result = {}
for name, (conf, hit, uncited) in rows.items():
    conf, hit, uncited = np.array(conf), np.array(hit), np.array(uncited)
    result[name] = {"all": summary(conf, hit), "uncited": summary(conf[uncited], hit[uncited])}
    for stratum, s in result[name].items():
        print(
            f"{name} {stratum}: n={s['n']}",
            f"top-1 prob {s['mean_conf']:.3f} acc {s['top1_acc']:.3f} ECE {s['ece']:.3f}",
        )
        for b in s["bins"]:
            print(
                f"  [{b['from']:.2f}, {b['to']:.2f}]: n={b['n']:5d}",
                f"prob {b['mean_conf']:.3f}",
                f"acc {b['acc']:.3f}",
            )
OUT.write_text(json.dumps(result, indent=2) + "\n")
print("wrote", OUT.relative_to(REPO_ROOT))
