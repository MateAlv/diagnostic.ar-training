"""P4-SEX step 1: the sex knowledge `sex-kb/2` (`v4.sexrule.build`) with a manifest, and its audit against an
earlier sex list: the add-on's (`p3-addon-kb-v1`, safe-v1's rules; the default) or an earlier `sex-kb`.

Writes data/interim/p4-sex/<id>/sex-kb.json.gz, data/p4-sex/<id>.stats.json and data/p4-sex/<id>.audit.json
(committed: every gene added or removed vs the earlier list with its reasons and diseases, then every limited
gene) and data/manifests/<id>.json. Needs a clean, committed tree. In `sex-kb-v2`'s files the two lists are
"v1" (p3-addon-kb-v1) and "v2"; from `sex-kb-v3` on they are "before" and "after".
Usage: kb.py <id> [<earlier list>]   (sex-kb-v2;  sex-kb-v3 sex-kb-v2)
"""

import json
import sys

from diagnostic_ar_training import DATA_DIR
from diagnostic_ar_training.lineage.manifest import build_manifest, ensure_new, write_manifest
from diagnostic_ar_training.lineage.registry import load_sources
from diagnostic_ar_training.systems.genphenia_v3 import SOURCE as E0_SOURCE
from diagnostic_ar_training.systems.genphenia_v3 import V3Inputs, unpack_bundle
from diagnostic_ar_training.v4 import addon, sexrule

ADDON_KB = "p3-addon-kb-v1"

kb_id = sys.argv[1]
before_id = sys.argv[2] if len(sys.argv) > 2 else ADDON_KB
ensure_new(kb_id)
genes = V3Inputs(unpack_bundle()).genes
kb, stats, read = sexrule.kb_from_sources(genes)
if before_id == ADDON_KB:
    before_kb, before_sha = addon.load_kb(before_id)
    before_records = {g: r["sex"] for g, r in before_kb["safe"]["genes"].items() if "sex" in r}
    before_names = before_kb["safe"]["disease_names"]
    labels = ("v1", "v2")
else:
    before_kb, before_sha = sexrule.load_kb(before_id)
    before_records = before_kb["genes"]
    before_names = before_kb["disease_names"]
    labels = ("before", "after")
v1, v2 = sexrule.limits(before_kb), sexrule.limits(kb)
names = {**before_names, **kb["disease_names"]}


def diseases(g: str) -> list[dict]:
    rec = kb["genes"].get(g) or kb["excluded"].get(g)
    if rec is None:
        return [{"id": d, "name": names.get(d, "")} for d in before_records[g]["diseases"]]
    return [{"id": d, "name": names.get(d, ""), "evidence": e} for d, e in rec["diseases"].items()]


added = [
    {"gene": g, "limit": v2[g], "reasons": kb["genes"][g]["reasons"], "location": kb["genes"][g]["location"]}
    | {labels[0]: v1.get(g), "diseases": diseases(g)}
    for g in sorted(v2)
    if v1.get(g) != v2[g]
]
removed = [
    {"gene": g, f"{labels[0]}_limit": v1[g], f"{labels[0]}_reasons": before_records[g]["reasons"]}
    | {labels[1]: v2.get(g)}
    | {"why": (kb["excluded"].get(g) or {}).get("why") or "no evidence", "diseases": diseases(g)}
    for g in sorted(v1)
    if v2.get(g) != v1[g]
]
audit = {
    "kb": kb_id,
    "compared_with": before_id,
    "counts": {
        labels[0]: {s: sum(v == s for v in v1.values()) for s in sexrule.SEXES},
        labels[1]: {s: sum(v == s for v in v2.values()) for s in sexrule.SEXES},
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
stats = {**stats, f"vs_{before_id}" if before_id != ADDON_KB else "vs_v1": audit["counts"]}
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
    "audit_only": f"{before_id} (the earlier sex list), compared in the audit; not read by the rules",
}
inputs = [sources[n].as_input() for n in (*read, E0_SOURCE)]
inputs.append({"id": f"artifact:{before_id}", "sha256": before_sha})
write_manifest(build_manifest(kb_id, sexrule.KB_KIND, inputs, params, [kb_path, stats_path, audit_path]))
print(json.dumps(stats, indent=1))
for row in added:
    print("added", row["gene"], row["limit"], row["reasons"], [d["name"] for d in row["diseases"]])
for row in removed:
    print("removed", row["gene"], row[f"{labels[0]}_limit"], row["why"], [d["name"] for d in row["diseases"]])
