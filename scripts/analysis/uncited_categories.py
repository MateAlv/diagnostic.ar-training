"""ANALYSIS-003: term categories of R1-train patients whose paper HPOA does not cite, against a given KB.

R1-train only. Usage: python scripts/analysis/uncited_categories.py <kb artifact id>
"""

import json
import math
import re
import sys
from collections import Counter

from diagnostic_ar_training import splits
from diagnostic_ar_training.lineage.manifest import fetch_outputs, load_manifest
from diagnostic_ar_training.lineage.registry import Purpose, open_source
from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.rerank import kb
from diagnostic_ar_training.rerank.features import GeneKnowledge

onto = Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
K = kb.read(fetch_outputs(load_manifest(sys.argv[1]))[0])
know = GeneKnowledge(K, onto)
cnt = Counter()
for d in K["diseases"].values():
    c = set()
    for t in d["phenotypes"]:
        c.add(t)
        c |= onto.ancestors(t)
    cnt.update(c)
N = len(K["diseases"])
ic = lambda t: -math.log(max(cnt.get(t, 0), 1) / N)  # noqa: E731
cited = set()
with open(open_source("hpo_annotations", Purpose.KB)) as f:
    for line in f:
        if not line.startswith("#"):
            cited.update(re.findall(r"PMID:(\d+)", line))
out = {}
for group in ("uncited", "cited"):
    cat, n, per_case, explained_per_case = Counter(), 0, [], []
    for c in splits.load_part("r1-v1", splits.Part.TRAIN, Purpose.EVAL):
        is_cited = bool({p.replace("PMID:", "") for p in c.pmids} & cited)
        if (group == "cited") != is_cited or not know.diseases(c.gene):
            continue
        annotated = {t for d in know.diseases(c.gene) for t in K["diseases"][d]["phenotypes"]}
        u = e = 0
        for t in c.present:
            t = onto.resolve(t) or t
            n += 1
            if know.term_probability(c.gene, t) > 0:
                cat["explained"] += 1
                e += 1
            elif onto.ancestors(t) & annotated:
                cat["more_specific"] += 1
            else:
                u += 1
                best = 0.0
                ts = onto.ancestors(t) | {t}
                for a in annotated:
                    common = ts & (onto.ancestors(a) | {a})
                    if common:
                        best = max(best, max(ic(x) for x in common))
                cat["related_ic>=2" if best >= 2 else "weak_ic<2"] += 1
        per_case.append(u)
        explained_per_case.append(e)
    out[group] = {"terms": n, **{k: round(v / n, 3) for k, v in sorted(cat.items())},
                  "cases": len(per_case),
                  "terms_per_case_mean": round(n / len(per_case), 4),
                  "explained_per_case_mean": round(sum(explained_per_case) / len(per_case), 4),
                  "unexplained_per_case_mean": round(sum(per_case) / len(per_case), 2)}
print(json.dumps({"kb": sys.argv[1], **out}, indent=1))
