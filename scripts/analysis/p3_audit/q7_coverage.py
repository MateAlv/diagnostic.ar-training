"""Free-part coverage checks: patient terms without a v3.0 embedding; genes annotated in HPO but outside v3.0's vocabulary."""
import csv, pickle, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import DATA  # noqa: E402
from diagnostic_ar_training.systems.genphenia_v3 import V3Inputs, unpack_bundle  # noqa: E402

inp = V3Inputs(unpack_bundle())
d = pickle.load(open(DATA / "cases.pkl", "rb"))
meta = d["meta"]
tot = miss = pat_any = 0
for m in meta:
    terms = list(dict.fromkeys(m["present"]))
    k = sum(1 for t in terms if t not in inp.emb_index)
    tot += len(terms); miss += k; pat_any += k > 0
print(f"present terms: {tot}, without embedding: {miss} ({miss/tot:.2%}); patients with >=1: {pat_any}/{len(meta)}")
voc = set(inp.genes)
for name in ["hpo_genes_to_phenotype"]:
    p = next(Path("data/raw", name).glob("*.txt"))
    genes = set()
    with open(p) as f:
        r = csv.DictReader(f, delimiter="\t")
        for row in r:
            genes.add(row["gene_symbol"])
    print(f"{name}: {len(genes)} annotated genes; outside v3.0 vocab: {len(genes - voc)}; vocab genes not annotated: {len(voc - genes)}")
