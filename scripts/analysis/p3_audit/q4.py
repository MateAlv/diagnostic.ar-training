"""Q4: E0 + training-free similarity fusion. Similarity scorer and fusion weights chosen on p2-v1 train
(MRR over all train patients); every configuration's dev result is logged; dev reported by slice.
"""

import json

import numpy as np
import torch

from common import DATA, Boot, load

genes, meta = load()
N = len(meta)
dev = torch.device("cuda")
kb = json.load(open(DATA / "kb_meta.json"))["kb_genes"]
union = sorted(set(genes) | set(kb))
uidx = {g: i for i, g in enumerate(union)}
U = len(union)
e0_cols = torch.tensor([uidx[g] for g in genes], device=dev)
kb_cols = torch.tensor([uidx[g] for g in kb], device=dev)
truth = torch.tensor([uidx.get(m["gene"], -1) for m in meta], device=dev)
is_dev = np.array([m["part"] == "dev" for m in meta])
cited = np.array([m["cited"] for m in meta])
inv = np.array([m["in_vocab"] for m in meta])
scorable = np.array([m["scorable"] for m in meta])
NEG = -1e30

logp = torch.from_numpy(np.load(DATA / "e0_logp.npy")).to(dev)
E = torch.full((N, U), NEG, device=dev)
E[:, e0_cols] = logp
E[~torch.from_numpy(scorable).to(dev)] = NEG


def ranks_of(S):
    """1-based rank of the true gene (ties midpoint) over genes with a score; None when unranked."""
    t = truth.clamp(min=0)
    st = S.gather(1, t[:, None])
    r = 1 + (S > st).sum(1) + 0.5 * ((S == st).sum(1) - 1)
    ok = (truth >= 0) & (st[:, 0] > NEG / 2)
    return [float(x) if o else None for x, o in zip(r.cpu().numpy(), ok.cpu().numpy())]


def full_rank(S):
    """Competition ranks (1 = best, ties share the best rank) of every gene; unscored genes get +inf."""
    neg = (-S).contiguous()
    asc, _ = neg.sort(1)
    rk = torch.searchsorted(asc, neg, right=False).float() + 1
    return torch.where(S > NEG / 2, rk, torch.tensor(float("inf"), device=dev))


def mrr(ranks, sel):
    return float(np.mean([0 if r is None else 1 / r for r, s in zip(ranks, sel) if s]))


e0_ranks = ranks_of(E)
print("E0 MRR check", mrr(e0_ranks, np.ones(N, bool)), "vs cached", np.mean([0 if m["e0_rank"] is None else 1 / m["e0_rank"] for m in meta]))

SIMS = ["gene_resnik_pg", "gene_resnik_sym", "disease_resnik_pg", "disease_resnik_sym", "gene_heur_prop"]
simS = {}
sel_train = ~is_dev
log = {"sim_train_mrr": {}, "configs": []}
for s in SIMS:
    S = torch.full((N, U), NEG, device=dev)
    S[:, kb_cols] = torch.from_numpy(np.load(DATA / f"sim_{s}.npy")).to(dev)
    S[S < NEG / 2] = NEG
    simS[s] = S
    log["sim_train_mrr"][s] = mrr(ranks_of(S), sel_train)
best_sim = max(log["sim_train_mrr"], key=log["sim_train_mrr"].get)
print("sim train MRR", log["sim_train_mrr"], "-> best", best_sim)
S = simS[best_sim]
rE, rS = full_rank(E), full_rank(S)


def zscore(X):
    m = X > NEG / 2
    cnt = m.sum(1, keepdim=True).clamp(min=1)
    mu = torch.where(m, X, 0).sum(1, keepdim=True) / cnt
    sd = (torch.where(m, (X - mu) ** 2, 0).sum(1, keepdim=True) / cnt).sqrt().clamp(min=1e-9)
    Z = (X - mu) / sd
    zmin = torch.where(m, Z, torch.tensor(float("inf"), device=dev)).amin(1, keepdim=True)
    return torch.where(m, Z, zmin)


zE, zS = zscore(E), zscore(S)
configs = []
for k in (10, 60):
    for lam in (0.25, 0.5, 1.0):
        configs.append((f"rrf_k{k}_lam{lam}", lambda k=k, lam=lam: 1 / (k + rE) + lam / (k + rS)))
for lam in (0.1, 0.25, 0.5, 1.0):
    configs.append((f"z_lam{lam}", lambda lam=lam: zE + lam * zS))
# round 2 (after round 1 picked the grid edge z_lam0.1): smaller weights, and blending only when E0 is unsure
for lam in (0.01, 0.02, 0.05):
    configs.append((f"z_lam{lam}", lambda lam=lam: zE + lam * zS))
e0_top = logp.amax(1, keepdim=True).exp()
for tau, lam in ((0.5, 0.1), (0.5, 0.25)):
    configs.append((f"z_gate{tau}_lam{lam}", lambda tau=tau, lam=lam: zE + lam * zS * (e0_top < tau).float()))

groups = [m["group"] for m in meta]
B = Boot(groups)
results = {}
for name, fn in configs:
    F = fn()
    F = torch.where((E > NEG / 2) | (S > NEG / 2), F, torch.tensor(NEG, device=dev))
    r = ranks_of(F)
    results[name] = r
    row = {"config": name, "train_mrr": mrr(r, sel_train), "dev_mrr": mrr(r, is_dev),
           "train_uncited_mrr": mrr(r, sel_train & ~cited),
           "dev_uncited_delta": B.compare(e0_ranks, r, is_dev & ~cited)["delta"],
           "dev_delta": B.compare(e0_ranks, r, is_dev)["delta"]}
    log["configs"].append(row)
    print(row)
log["e0_train_mrr"], log["e0_dev_mrr"] = mrr(e0_ranks, sel_train), mrr(e0_ranks, is_dev)
chosen = max(log["configs"], key=lambda x: x["train_mrr"])["config"]
log["chosen"] = chosen
chosen_unc = max(log["configs"], key=lambda x: x["train_uncited_mrr"])["config"]
log["chosen_on_train_uncited"] = chosen_unc
print("chosen on train uncited:", chosen_unc)
log["dev_median_delta_all_configs"] = float(np.median([c["dev_delta"] for c in log["configs"]]))
print("chosen on train:", chosen)

slices = {"dev all": is_dev, "dev cited": is_dev & cited, "dev uncited": is_dev & ~cited,
          "dev cited & inV": is_dev & cited & inv, "dev uncited & inV": is_dev & ~cited & inv,
          "dev uncited & OOV": is_dev & ~cited & ~inv,
          "dev post/uncited": is_dev & ~cited & ~np.array([m["in_0125"] for m in meta]),
          "train all": sel_train, "train uncited": sel_train & ~cited, "train cited": sel_train & cited}
rep = {}
for cname in dict.fromkeys((chosen, chosen_unc, "z_lam0.1", "rrf_k60_lam1.0")):
    rk = results[cname]
    for sname, sel in slices.items():
        c = B.compare(e0_ranks, rk, sel)
        rt = np.array([np.inf if x is None else x for x in rk])
        re = np.array([np.inf if x is None else x for x in e0_ranks])
        c["top1_e0"], c["top1_b"] = float((re[sel] <= 1).mean()), float((rt[sel] <= 1).mean())
        c["top10_e0"], c["top10_b"] = float((re[sel] <= 10).mean()), float((rt[sel] <= 10).mean())
        rep[f"{cname} | {sname}"] = c
        print(f"{cname:16s} {sname:20s} n={c['n']} pubs={c['pubs']} E0 {c['a_mrr']:.3f} -> {c['b_mrr']:.3f} "
              f"d={c['delta']:+.4f} [{c['ci'][0]:+.4f},{c['ci'][1]:+.4f}] harmed={c['harmed']:.3f} helped={c['helped']:.3f} "
              f"top1 {c['top1_e0']:.3f}->{c['top1_b']:.3f} top10 {c['top10_e0']:.3f}->{c['top10_b']:.3f}")
log["report"] = rep
json.dump(log, open(DATA / "q4.json", "w"), indent=1)
json.dump({k: v for k, v in results.items() if k in (chosen, chosen_unc, "z_lam0.1", "rrf_k60_lam1.0")}, open(DATA / "q4_ranks.json", "w"))
