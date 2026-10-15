"""P4-SEX step 1: the sex knowledge `sex-kb/2` (`v4.sexrule.build`) with a manifest, and its audit against the
add-on's sex list (`p3-addon-kb-v1`, safe-v1's rules).

Writes data/interim/p4-sex/<id>/sex-kb.json.gz, data/p4-sex/<id>.stats.json and data/p4-sex/<id>.audit.json
(committed: every gene added or removed vs p3-addon-kb-v1 with its reasons and diseases, then every limited
gene) and data/manifests/<id>.json. Needs a clean, committed tree.
Usage: kb.py <id>   (sex-kb-v2)
"""

import json
import sys

from diagnostic_ar_training import DATA_DIR
from diagnostic_ar_training.lineage.manifest import build_manifest, ensure_new, write_manifest
from diagnostic_ar_training.lineage.registry import load_sources
from diagnostic_ar_training.systems.genphenia_v3 import SOURCE as E0_SOURCE
from diagnostic_ar_training.systems.genphenia_v3 import V3Inputs, unpack_bundle
from diagnostic_ar_training.v4 import addon, sexrule

V1 = "p3-addon-kb-v1"

kb_id = sys.argv[1]
ensure_new(kb_id)
genes = V3Inputs(unpack_bundle()).genes
kb, stats, read = sexrule.kb_from_sources(genes)
v1_kb, v1_sha = addon.load_kb(V1)
v1_records = {g: r["sex"] for g, r in v1_kb["safe"]["genes"].items() if "sex" in r}
v1, v2 = sexrule.limits(v1_kb), sexrule.limits(kb)
names = {**v1_kb["safe"]["disease_names"], **kb["disease_names"]}


def diseases(g: str) -> list[dict]:
    rec = kb["genes"].get(g) or kb["excluded"].get(g)
    if rec is None:
        return [{"id": d, "name": names.get(d, "")} for d in v1_kb["safe"]["genes"][g]["diseases"]]
    return [{"id": d, "name": names.get(d, ""), "evidence": e} for d, e in rec["diseases"].items()]


added = [
    {"gene": g, "limit": v2[g], "reasons": kb["genes"][g]["reasons"], "location": kb["genes"][g]["location"]}
    | {"v1": v1.get(g), "diseases": diseases(g)}
    for g in sorted(v2)
    if v1.get(g) != v2[g]
]
removed = [
    {"gene": g, "v1_limit": v1[g], "v1_reasons": v1_records[g]["reasons"], "v2": v2.get(g)}
    | {"why": (kb["excluded"].get(g) or {}).get("why") or "no evidence", "diseases": diseases(g)}
    for g in sorted(v1)
    if v2.get(g) != v1[g]
]
audit = {
    "kb": kb_id,
    "compared_with": V1,
    "counts": {
        "v1": {s: sum(v == s for v in v1.values()) for s in sexrule.SEXES},
        "v2": {s: sum(v == s for v in v2.values()) for s in sexrule.SEXES},
        "kept": sum(v1.get(g) == v for g, v in v2.items()),
        "added": len(added),
        "removed": len(removed),
    },
    "added": added,
    "removed": removed,
    "limited": {
        g: {"limit": r["limit"], "reasons": r["reasons"], "location": r["location"], "diseases": diseases(g)}
        for g, r in kb["genes"].items()
    },
}
stats = {**stats, "vs_v1": audit["counts"]}
out_dir = DATA_DIR / "p4-sex"
out_dir.mkdir(parents=True, exist_ok=True)
stats_path = out_dir / f"{kb_id}.stats.json"
stats_path.write_text(json.dumps(stats, indent=1) + "\n")
audit_path = out_dir / f"{kb_id}.audit.json"
audit_path.write_text(json.dumps(audit, indent=1, ensure_ascii=False) + "\n")
kb_path = sexrule.write_kb(kb, kb_id)
sources = load_sources()
params = {
    "schema": kb["schema"],
    "builder": "v4.sexrule.build",
    "vocabulary": "E0 (genphenia_v3) genes",
    "gene_to_disease": "e0_genes_to_phenotype rows with a disease id",
    "annotations": "hpo_annotations_2025_03_03, unmasked; NOT rows never read, zero-frequency rows dropped",
    "ontology": "hpo_ontology_2025_03_03 (sex, genital and DSD subtrees)",
    "hgnc": "hgnc chromosome locations (declared extra source): Y outside the pseudoautosomal regions",
    "rules": kb["rules"],
    "audit_only": f"{V1} (the add-on's sex list), compared in the audit; not read by the rules",
}
inputs = [sources[n].as_input() for n in (*read, E0_SOURCE)] + [{"id": f"artifact:{V1}", "sha256": v1_sha}]
write_manifest(build_manifest(kb_id, sexrule.KB_KIND, inputs, params, [kb_path, stats_path, audit_path]))
print(json.dumps(stats, indent=1))
for row in added:
    print("added", row["gene"], row["limit"], row["reasons"], [d["name"] for d in row["diseases"]])
for row in removed:
    print("removed", row["gene"], row["v1_limit"], row["why"], [d["name"] for d in row["diseases"]])
