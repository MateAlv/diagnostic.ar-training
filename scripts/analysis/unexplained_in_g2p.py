"""ANALYSIS-004: are real uncited patients' kb-v3-unexplained terms annotated to the gene in the unmasked g2p file?

R1-train only. Prints the share and E0 MRR on each subset.
"""

import csv
import json
import re
from collections import defaultdict

from diagnostic_ar_training import splits
from diagnostic_ar_training.eval import harness
from diagnostic_ar_training.lineage.manifest import fetch_outputs, load_manifest
from diagnostic_ar_training.lineage.registry import Purpose, open_source
from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.rerank import kb
from diagnostic_ar_training.rerank.features import GeneKnowledge
from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

onto = Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
know = GeneKnowledge(kb.read(fetch_outputs(load_manifest("kb-v3"))[0]), onto)
g2p = defaultdict(set)
with open_source("hpo_genes_to_phenotype", Purpose.EVAL).open(encoding="utf-8") as h:
    for r in csv.DictReader(h, delimiter="\t"):
        t = onto.resolve(r["hpo_id"])
        if t:
            g2p[r["gene_symbol"].upper()] |= {t} | onto.ancestors(t)
cited = set()
with open(open_source("hpo_annotations", Purpose.KB)) as f:
    for line in f:
        if not line.startswith("#"):
            cited.update(re.findall(r"PMID:(\d+)", line))
inside, outside, n_in, n_out = [], [], 0, 0
for c in splits.load_part("r1-v1", splits.Part.TRAIN, Purpose.EVAL):
    if {p.replace("PMID:", "") for p in c.pmids} & cited or not know.diseases(c.gene):
        continue
    unexpl = [onto.resolve(t) or t for t in c.present if know.term_probability(c.gene, onto.resolve(t) or t) == 0]
    a = tuple(t for t in unexpl if t in g2p.get(c.gene.upper(), ()))
    b = tuple(t for t in unexpl if t not in g2p.get(c.gene.upper(), ()))
    n_in += len(a)
    n_out += len(b)
    if a:
        inside.append(c.model_copy(update={"present": a}))
    if b:
        outside.append(c.model_copy(update={"present": b}))
e0 = GenPheniaV3()
out = {"unexplained_terms": n_in + n_out, "share_annotated_to_gene_in_unmasked_g2p": round(n_in / (n_in + n_out), 3)}
for name, cs in (("in_g2p", inside), ("not_in_g2p", outside)):
    s = harness.summarize(harness.run(e0, cs, view="present"))
    out[name] = {"patients": len(cs), "mrr_in_vocab": round(s.get("gene_in_vocab", s["all"])["mrr"], 4)}
print(json.dumps(out, indent=1))
