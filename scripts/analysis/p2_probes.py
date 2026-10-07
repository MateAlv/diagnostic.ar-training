"""P2-PROBES-v1: sizing Phase 2 candidates on R1 train + dev (free parts), before ADR-0017.

Every configuration tried on 2026-10-07 is here, winners and losers alike (EVAL_PROTOCOL §5):
knowledge-only constraints (sex, age, onset, obligate negation), soft variants, an X-linked prior,
per-gene priors learned from R1-train (scored on R1-dev only), and E0 by publication era.
Sealed parts are never loaded; for test and vault only case ids and PMIDs are counted.

Usage: python scripts/analysis/p2_probes.py <out_dir> [new_since_0.1.27.txt]
"""

import csv
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from diagnostic_ar_training import splits
from diagnostic_ar_training.lineage.registry import Purpose, open_source
from diagnostic_ar_training.splits import Part
from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

csv.field_size_limit(10**9)
OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
NEW_LIST = Path(sys.argv[2]) if len(sys.argv) > 2 else None

cases = splits.load_part("r1-v1", Part.TRAIN, Purpose.EVAL) + splits.load_part(
    "r1-v1", Part.DEV, Purpose.EVAL
)
train_ids = set(splits.load_frozen("r1-v1")["case_ids"]["train"])
groups = splits.publication_groups("r1-v1")
masked = {p.replace("PMID:", "") for p in splits.mask_pmids("r1-v1", "all")}

e0 = GenPheniaV3()
genes = list(e0.genes)
gidx = {g: i for i, g in enumerate(genes)}
P = np.zeros((len(cases), len(genes)))
for i, c in enumerate(cases):
    s = e0.score(c)
    if s.probs is not None:
        P[i] = s.probs

# Knowledge: HPO 2026-02-16 with every R1 publication masked, Orphanet ages 2026-06, HGNC.
g2d = defaultdict(set)
with open(open_source("hpo_genes_to_disease", Purpose.KB)) as f:
    for r in csv.DictReader(f, delimiter="\t"):
        if r["association_type"] != "POLYGENIC":
            g2d[r["gene_symbol"]].add(r["disease_id"])

name, inher, onset_terms, pheno = {}, defaultdict(set), defaultdict(set), defaultdict(list)
with open(open_source("hpo_annotations", Purpose.KB)) as f:
    for r in csv.DictReader((x for x in f if not x.startswith("#")), delimiter="\t"):
        name.setdefault(r["database_id"], r["disease_name"])
        if {x.strip().replace("PMID:", "") for x in r["reference"].split(";")} & masked:
            continue
        d = r["database_id"]
        if r["aspect"] == "I":
            inher[d].add(r["hpo_id"])
        elif r["aspect"] == "C":
            onset_terms[d].add(r["hpo_id"])
        elif r["aspect"] == "P" and r["qualifier"] != "NOT":
            pheno[d].append((r["hpo_id"], r["frequency"]))

# Lower bound, in years, of each onset class.
HPO_ONSET = {
    "HP:0030674": -1,
    "HP:0011460": -1,
    "HP:0011461": -1,
    "HP:0034199": -1,
    "HP:0034198": -1,
    "HP:0034197": -1,
    "HP:0003577": 0,
    "HP:0003623": 0,
    "HP:0410280": 0,
    "HP:0003593": 28 / 365,
    "HP:0011463": 1,
    "HP:0003621": 5,
    "HP:0011462": 16,
    "HP:0025708": 16,
    "HP:0025709": 19,
    "HP:0025710": 25,
    "HP:0003581": 16,
    "HP:0003596": 40,
    "HP:0003584": 60,
}
ORPHA_ONSET = {
    "Antenatal": -1,
    "Neonatal": 0,
    "Infancy": 28 / 365,
    "Childhood": 1,
    "Adolescent": 10,
    "Adult": 16,
    "Elderly": 60,
    "All ages": 0,
}
orpha_onset = defaultdict(set)
for _, el in ET.iterparse(open_source("orphanet_ages_2026_06", Purpose.KB)):
    if el.tag == "Disorder":
        code = el.findtext("OrphaCode")
        for a in el.iter("AverageAgeOfOnset"):
            if a.findtext("Name") in ORPHA_ONSET:
                orpha_onset[f"ORPHA:{code}"].add(ORPHA_ONSET[a.findtext("Name")])
        el.clear()


def disease_onset(d):
    vals = [HPO_ONSET[t] for t in onset_terms.get(d, ()) if t in HPO_ONSET] + list(orpha_onset.get(d, ()))
    return min(vals) if vals else None


# lenient: earliest known onset among the gene's diseases.
# strict: the same, but only when every OMIM disease of the gene has onset data.
earliest_lenient, earliest_strict = {}, {}
for g in genes:
    ds = g2d.get(g, set())
    known = [o for o in (disease_onset(d) for d in ds) if o is not None]
    if known:
        earliest_lenient[g] = min(known)
        if all(disease_onset(d) is not None for d in ds if d.startswith("OMIM:")):
            earliest_strict[g] = min(known)

hgnc_loc = {}
with open(open_source("hgnc", Purpose.KB)) as f:
    for r in csv.DictReader(f, delimiter="\t"):
        for sym in [r["symbol"]] + [x for x in (r["prev_symbol"] + "|" + r["alias_symbol"]).split("|") if x]:
            hgnc_loc.setdefault(sym.strip('"'), r["location"])

MALE = re.compile(
    r"sperm|zoospermia|acrosom|flagell|sertoli|anorchia|cryptorchidism|hypospadias|"
    r"male infertility|persistent mullerian duct|testicular regression|micropenis",
    re.I,
)
FEMALE = re.compile(
    r"ovarian (failure|insufficiency|dysgenesis|hyperstimulation)|premature ovarian|oocyte|"
    r"female infertility|hydatidiform mole|preimplantation embryonic lethality|embryonic arrest|"
    r"zygot|empty follicle|mullerian aplasia|mayer-rokitansky|polycystic ovary|"
    r"recurrent pregnancy loss|pre-?eclampsia",
    re.I,
)
SEXREV = re.compile(
    r"sex reversal|gonadal dysgenesis|disorder of sex development|swyer|androgen insensitivity|"
    r"46,? ?x[xy]",
    re.I,
)


def all_names_match(g, pat):
    names = [name[d] for d in g2d.get(g, ()) if d in name]
    return bool(names) and all(pat.search(n) for n in names) and not any(SEXREV.search(n) for n in names)


male_lim, female_lim = set(), set()
for g in genes:
    ds = g2d.get(g, set())
    names = [name.get(d, "") for d in ds]
    sexrev = any(SEXREV.search(n) for n in names)
    loc = hgnc_loc.get(g, "")
    y_only = (
        bool(ds) and any(d in inher for d in ds) and all(inher[d] == {"HP:0001450"} for d in ds if d in inher)
    )
    if (
        (loc.startswith("Y") and "X" not in loc and not sexrev)
        or all_names_match(g, MALE)
        or (y_only and not sexrev)
    ):
        male_lim.add(g)
    if all_names_match(g, FEMALE):
        female_lim.add(g)

parents = defaultdict(set)
for e in json.load(open(open_source("hpo_ontology", Purpose.KB)))["graphs"][0]["edges"]:
    if e["pred"] == "is_a":
        parents[e["sub"].rsplit("/", 1)[-1].replace("_", ":")].add(
            e["obj"].rsplit("/", 1)[-1].replace("_", ":")
        )
_anc = {}


def ancestors(t):
    if t not in _anc:
        out, stack = {t}, [t]
        while stack:
            for p in parents.get(stack.pop(), ()):
                if p not in out:
                    out.add(p)
                    stack.append(p)
        _anc[t] = out
    return _anc[t]


def obligate(freq):
    m = re.fullmatch(r"(\d+)/(\d+)", freq)
    return freq in ("HP:0040280", "100%") or (bool(m) and m.group(1) == m.group(2) and int(m.group(2)) >= 5)


oblig = {d: [ancestors(t) for t, fr in v if obligate(fr)] for d, v in pheno.items()}


def neg_contradicted(g, excluded):
    ds = [d for d in g2d.get(g, ()) if d in pheno]
    return bool(ds) and all(any(a & excluded for a in oblig.get(d, ())) for d in ds)


# Evaluation -------------------------------------------------------------------------------------------------
n = len(cases)
truth = np.array([gidx.get(c.gene, -1) for c in cases])
scored = P.sum(1) > 0
is_train = np.array([c.case_id in train_ids for c in cases])
case_group = np.array([groups.get(c.case_id, c.case_id) for c in cases])
uniq, ginv = np.unique(case_group, return_inverse=True)
BOOT = np.random.default_rng(0).integers(0, len(uniq), size=(2000, len(uniq)))


def recip_rank(i, fac=None, hard=None):
    """1/rank of the true gene. `fac` scales probabilities; `hard` genes go below all others, order kept."""
    if truth[i] < 0 or not scored[i]:
        return 0.0
    p = P[i] if fac is None else P[i] * fac
    t, pt = truth[i], (P[i] if fac is None else P[i] * fac)[truth[i]]
    if hard is None or not hard.any():
        return 1.0 / (1 + (p > pt).sum() + 0.5 * ((p == pt).sum() - 1))
    keep = ~hard
    if hard[t]:
        return 1.0 / (keep.sum() + 1 + ((p > pt) & hard).sum() + 0.5 * (((p == pt) & hard).sum() - 1))
    return 1.0 / (1 + ((p > pt) & keep).sum() + 0.5 * (((p == pt) & keep).sum() - 1))


base = np.array([recip_rank(i) for i in range(n)])


def soft(mask, f):
    return None if mask is None else (np.where(mask, f, 1.0), None)


def hard(mask):
    return None if mask is None else (None, mask)


def evaluate(fac_fn, sel=None):
    sel = np.ones(n, bool) if sel is None else sel
    new = base.copy()
    for i in np.where(sel)[0]:
        if truth[i] >= 0 and scored[i]:
            change = fac_fn(cases[i])
            if change is not None:
                new[i] = recip_rank(i, *change)
    delta = np.where(sel, new - base, 0.0)
    gsum = np.bincount(ginv, weights=delta, minlength=len(uniq))
    gcnt = np.bincount(ginv, weights=sel.astype(float), minlength=len(uniq))
    est = gsum[BOOT].sum(1) / np.maximum(gcnt[BOOT].sum(1), 1)
    d = delta[sel]
    rank_new, rank_base = 1 / np.maximum(new[sel], 1e-300), 1 / np.maximum(base[sel], 1e-300)
    return {
        "n": int(sel.sum()),
        "helped": int((d > 0).sum()),
        "harmed": int((d < 0).sum()),
        "helped_publications": int(len(set(case_group[sel][d > 0]))),
        "delta_mrr": float(d.mean()),
        "ci95": [float(x) for x in np.percentile(est, [2.5, 97.5])],
        "top10_entered": int(((rank_new <= 10) & (rank_base > 10)).sum()),
        "top10_left": int(((rank_new > 10) & (rank_base <= 10)).sum()),
    }


def sex_of(c):
    s = str(c.sex).upper()
    return "F" if s.endswith("FEMALE") else "M" if s.endswith("MALE") else None


male_mask = np.array([g in male_lim for g in genes])
female_mask = np.array([g in female_lim for g in genes])
el_l = np.array([earliest_lenient.get(g, -np.inf) for g in genes])
el_s = np.array([earliest_strict.get(g, -np.inf) for g in genes])


def sex_rule(c):
    return {"F": male_mask, "M": female_mask}.get(sex_of(c))


def age_rule(earliest, margin, field):
    return lambda c: None if getattr(c, field) is None else earliest > getattr(c, field) + margin


def neg_rule(c):
    return None if not c.excluded else np.array([neg_contradicted(g, set(c.excluded)) for g in genes])


def combined(c):
    mask, used = np.zeros(len(genes), bool), False
    if sex_rule(c) is not None:
        mask |= sex_rule(c)
        used = True
    age = c.onset_years if c.onset_years is not None else c.age_years
    if age is not None:
        mask |= el_s > age
        used = True
    return (None, mask) if used else None


report = {
    "code_commit": subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip(),
    "cases": n,
    "publication_groups": int(len(uniq)),
    "e0_mrr": float(base.mean()),
    "male_limited_genes": len(male_lim),
    "female_limited_genes": len(female_lim),
    "genes_with_strict_onset": int(np.isfinite(el_s).sum()),
    "strict_onset_at_least_years": {str(t): int((el_s >= t).sum()) for t in (1, 5, 10, 16, 40)},
    "configs": {},
}
C = report["configs"]
C["sex_hard"] = evaluate(lambda c: hard(sex_rule(c)))
for kind, arr in (("lenient", el_l), ("strict", el_s)):
    for m in (0, 2, 5):
        C[f"age_{kind}_m{m}"] = evaluate(lambda c, a=arr, m=m: hard(age_rule(a, m, "age_years")(c)))
        C[f"onset_{kind}_m{m}"] = evaluate(lambda c, a=arr, m=m: hard(age_rule(a, m, "onset_years")(c)))
C["neg_obligate_hard"] = evaluate(lambda c: hard(neg_rule(c)))
for f in (0.3, 0.1, 0.01):
    C[f"neg_obligate_x{f}"] = evaluate(lambda c, f=f: soft(neg_rule(c), f))
for f in (0.3, 0.1):
    C[f"age_lenient_m0_x{f}"] = evaluate(lambda c, f=f: soft(age_rule(el_l, 0, "age_years")(c), f))
    C[f"onset_lenient_m0_x{f}"] = evaluate(lambda c, f=f: soft(age_rule(el_l, 0, "onset_years")(c), f))

inheritance = {g: set().union(*[inher.get(d, set()) for d in g2d.get(g, ())]) for g in genes}
xlr_only = np.array([bool(inheritance[g]) and inheritance[g] <= {"HP:0001419", "HP:0001417"} for g in genes])
xld_only = np.array([bool(inheritance[g]) and inheritance[g] <= {"HP:0001423"} for g in genes])
for a, b in ((0.5, 1.0), (0.3, 1.0), (0.1, 1.0), (1.0, 0.5), (0.3, 0.5)):
    C[f"xlinked_f{a}_m{b}"] = evaluate(
        lambda c, a=a, b=b: {"F": soft(xlr_only, a), "M": soft(xld_only, b)}.get(sex_of(c))
    )

# Per-gene priors learned from R1-train patients, scored on R1-dev only.
BANDS = [-np.inf, 1, 5, 12, 18, 40, np.inf]


def band(x):
    return None if x is None else int(np.searchsorted(BANDS, x, side="right") - 1)


def learned_prior(keyfn, w, shrink=5.0):
    counts, total = defaultdict(Counter), Counter()
    for i in np.where(is_train)[0]:
        k = keyfn(cases[i])
        if k is not None:
            counts[cases[i].gene][k] += 1
            total[k] += 1
    prior = {k: v / sum(total.values()) for k, v in total.items()}
    cache = {}

    def fac(c):
        k = keyfn(c)
        if k not in prior:
            return None
        if k not in cache:
            arr = np.ones(len(genes))
            for g, cc in counts.items():
                if g in gidx:
                    arr[gidx[g]] = ((cc[k] + shrink * prior[k]) / (sum(cc.values()) + shrink) / prior[k]) ** w
            cache[k] = (arr, None)
        return cache[k]

    return fac


for w in (0.5, 1.0):
    C[f"learned_sex_w{w}_dev"] = evaluate(learned_prior(sex_of, w), ~is_train)
    C[f"learned_ageband_w{w}_dev"] = evaluate(learned_prior(lambda c: band(c.age_years), w), ~is_train)
    C[f"learned_onsetband_w{w}_dev"] = evaluate(learned_prior(lambda c: band(c.onset_years), w), ~is_train)
C["sex_hard_plus_age_onset_strict"] = evaluate(combined)

top10 = np.argsort(-P, axis=1)[:, :10]
tops = Counter()
for i, c in enumerate(cases):
    if not scored[i]:
        continue
    if sex_rule(c) is not None:
        tops["sex_known"] += 1
        tops["sex_impossible_in_top10"] += int(sex_rule(c)[top10[i]].any())
    age = c.onset_years if c.onset_years is not None else c.age_years
    if age is not None:
        tops["age_known"] += 1
        tops["age_impossible_in_top10"] += int((el_s[top10[i]] > age).any())
report["top10_lists"] = dict(tops)


# Publication eras: metadata only (phenopacket ids and PMIDs).
def ids_and_pmids(zip_path):
    out = {}
    with zipfile.ZipFile(zip_path) as z:
        for member in z.namelist():
            if member.endswith(".json"):
                try:
                    doc = json.loads(z.read(member))
                except ValueError:
                    continue
                if isinstance(doc, dict) and "id" in doc:
                    refs = doc.get("metaData", {}).get("externalReferences") or []
                    out[doc["id"]] = {r["id"][5:] for r in refs if str(r.get("id", "")).startswith("PMID:")}
    return out


def cited_pmids(hpoa_path):
    out = set()
    with open(hpoa_path) as f:
        for line in f:
            if not line.startswith(("#", "database_id")):
                cols = line.rstrip("\n").split("\t")
                out |= {x.strip()[5:] for x in cols[4].split(";") if x.strip().startswith("PMID:")}
    return out


pm25 = set().union(*ids_and_pmids(open_source("phenopacket_store_0_1_25", Purpose.KB)).values())
by_id27 = ids_and_pmids(open_source("phenopacket_store", Purpose.EVAL))
pm27 = set().union(*by_id27.values())
e0_cited = cited_pmids(open_source("hpo_annotations_2025_11_24", Purpose.KB))
now_cited = cited_pmids(open_source("hpo_annotations", Purpose.KB))


def era_label(pm):
    return ("post-0.1.25" if not (pm & pm25) else "<=0.1.25") + (
        "/E0-cited" if pm & e0_cited else "/not-cited"
    )


part_of = {cid: part for part, ids in splits.load_frozen("r1-v1")["case_ids"].items() for cid in ids}
era_counts = Counter((part, era_label(by_id27.get(cid, set()))) for cid, part in part_of.items())
report["era_counts_by_part"] = {f"{p}|{e}": v for (p, e), v in sorted(era_counts.items())}
labels = np.array([era_label(by_id27.get(c.case_id, set())) for c in cases])
inv = truth >= 0
report["e0_by_era_train_dev"] = {
    lab: {
        "n": int((labels == lab).sum()),
        "in_vocab": float(inv[labels == lab].mean()),
        "mrr": float(base[labels == lab].mean()),
        "mrr_in_vocab": float(base[(labels == lab) & inv].mean()),
    }
    for lab in sorted(set(labels))
}
post_e0 = labels == "post-0.1.25/not-cited"
report["post_e0_train_dev"] = {
    "sex_hard_plus_age_onset_strict": evaluate(combined, post_e0),
    "neg_obligate_x0.1": evaluate(lambda c: soft(neg_rule(c), 0.1), post_e0),
}

if NEW_LIST:
    fresh = Counter()
    for line in NEW_LIST.read_text().split():
        m = re.match(r"PMID_(\d+)", Path(line).stem)
        pm = {m.group(1)} if m else set()
        fresh[
            ("pub-in-0.1.27" if pm & pm27 else "new-pub")
            + ("/E0-cited" if pm & e0_cited else "/not-E0-cited")
            + ("/cited-2026-02-16" if pm & now_cited else "")
        ] += 1
    report["new_since_0_1_27"] = dict(fresh)

(OUT / "report.json").write_text(json.dumps(report, indent=1) + "\n")
(OUT / "sex_limited_genes.json").write_text(
    json.dumps({"male": sorted(male_lim), "female": sorted(female_lim)}, indent=0)
)
for k, v in C.items():
    print(
        f"{k:34s} n={v['n']:5d} +{v['helped']:4d} -{v['harmed']:3d} dMRR={v['delta_mrr']:+.5f} "
        f"[{v['ci95'][0]:+.5f}, {v['ci95'][1]:+.5f}] top10 +{v['top10_entered']}/-{v['top10_left']}"
    )
print(
    json.dumps({k: report[k] for k in ("top10_lists", "e0_by_era_train_dev", "post_e0_train_dev")}, indent=1)
)
print(json.dumps(report.get("new_since_0_1_27"), indent=1))
