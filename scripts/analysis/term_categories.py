"""ANALYSIS-002 (R1-train only; the dataset argument is a simulated export). Where do present terms sit relative to the gene's KB annotations? R1-train vs simulated candidate."""
import gzip, json, math, random, sys
from collections import Counter
from diagnostic_ar_training import splits
from diagnostic_ar_training.lineage.manifest import fetch_outputs, load_manifest
from diagnostic_ar_training.lineage.registry import Purpose, open_source
from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.rerank import kb
from diagnostic_ar_training.rerank.features import GeneKnowledge

onto = Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
K = kb.read(fetch_outputs(load_manifest("kb-v4"))[0])
know = GeneKnowledge(K, onto)
dis = K["diseases"]
cnt = Counter()
for d in dis.values():
    closure = set()
    for t in d["phenotypes"]:
        closure.add(t); closure |= onto.ancestors(t)
    cnt.update(closure)
N = len(dis)
ic = lambda t: -math.log(max(cnt.get(t, 0), 1) / N)
annot_cache = {}
def annotated(gene):
    if gene not in annot_cache:
        s = set()
        for d in know.diseases(gene):
            s |= set(dis[d]["phenotypes"])
        annot_cache[gene] = s
    return annot_cache[gene]
def classify(gene, t):
    t = onto.resolve(t) or t
    if know.term_probability(gene, t) > 0:
        return "explained", None
    A = annotated(gene)
    anc = onto.ancestors(t)
    if anc & A:
        return "descendant_of_annotated", None
    best = 0.0
    tset = anc | {t}
    for a in A:
        common = tset & (onto.ancestors(a) | {a})
        if common:
            best = max(best, max(ic(c) for c in common))
    return "unexplained", best
def summarize(label, records):
    cat = Counter(); lca = []
    n = 0
    for gene, terms in records:
        if not know.diseases(gene):
            continue
        for t in terms:
            c, b = classify(gene, t); cat[c] += 1; n += 1
            if b is not None: lca.append(b)
    lca.sort()
    q = lambda p: round(lca[int(p * (len(lca) - 1))], 2) if lca else None
    bins = Counter("ic>=4" if b >= 4 else "2<=ic<4" if b >= 2 else "ic<2" for b in lca)
    print(json.dumps({"set": label, "terms": n, **{k: round(v / n, 3) for k, v in cat.items()},
                      "unexplained_best_lca_ic_quartiles": [q(.25), q(.5), q(.75)],
                      "unexplained_lca_bins_share_of_all_terms": {k: round(v / n, 3) for k, v in bins.items()}}))
train = splits.load_part("r1-v1", splits.Part.TRAIN, Purpose.TRAIN)
summarize("R1-train", [(c.gene, c.present) for c in train])
random.seed(7)
rows = []
with gzip.open(sys.argv[1], "rt") as f:
    for line in f:
        if random.random() < 0.01:
            r = json.loads(line); rows.append((r["gene"], r["present"]))
summarize("cand1 (1% sample)", rows)
