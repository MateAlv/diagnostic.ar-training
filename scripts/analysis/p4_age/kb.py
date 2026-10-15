"""P4-AGE step 1: the age knowledge `age-kb/1` (`v4.agerule.build`) with a manifest, compared with the
add-on's strict earliest onsets (`p3-addon-kb-v1`, safe-v1's rule: every OMIM disease annotated, ORPHA ones
not needed).

Writes data/interim/p4-age/<id>/age-kb.json.gz, data/p4-age/<id>.stats.json (committed: counts, the bound
distribution and the comparison) and data/manifests/<id>.json. Needs a clean, committed tree.
Usage: kb.py <id>   (age-kb-v1)
"""

import json
import sys
from collections import Counter

from diagnostic_ar_training import DATA_DIR
from diagnostic_ar_training.lineage.manifest import build_manifest, ensure_new, write_manifest
from diagnostic_ar_training.lineage.registry import load_sources
from diagnostic_ar_training.systems.genphenia_v3 import SOURCE as E0_SOURCE
from diagnostic_ar_training.systems.genphenia_v3 import V3Inputs, unpack_bundle
from diagnostic_ar_training.v4 import addon, agerule

V1 = "p3-addon-kb-v1"

kb_id = sys.argv[1]
ensure_new(kb_id)
genes = V3Inputs(unpack_bundle()).genes
kb, stats, read = agerule.kb_from_sources(genes)
v1_kb, v1_sha = addon.load_kb(V1)
v1 = {g: r["onset"]["earliest_years"] for g, r in v1_kb["safe"]["genes"].items() if "onset" in r}
v2, by_class = agerule.bounds(kb), agerule.bounds(kb, rows=False)
both = set(v1) & set(v2)
comparison = {
    "v1_genes_with_bound": len(v1),
    "v2_genes_with_bound": len(v2),
    "both": len(both),
    "v1_only": len(set(v1) - set(v2)),
    "v2_only": len(set(v2) - set(v1)),
    "both_v2_lower": sum(v2[g] < v1[g] for g in both),
    "both_v2_higher": sum(v2[g] > v1[g] for g in both),
    "lowered_by_row_onsets": sum(v2[g] < by_class[g] for g in v2),
}
stats = {
    **stats,
    "bound_distribution": {f"{k:g}": v for k, v in sorted(Counter(v2.values()).items())},
    "vs_v1": comparison,
}
out_dir = DATA_DIR / "p4-age"
out_dir.mkdir(parents=True, exist_ok=True)
stats_path = out_dir / f"{kb_id}.stats.json"
stats_path.write_text(json.dumps(stats, indent=1) + "\n")
kb_path = agerule.write_kb(kb, kb_id)
sources = load_sources()
params = {
    "schema": kb["schema"],
    "builder": "v4.agerule.build",
    "vocabulary": "E0 (genphenia_v3) genes",
    "gene_to_disease": "e0_genes_to_phenotype rows with a disease id",
    "annotations": "hpo_annotations_2025_03_03, unmasked: aspect C onset classes and the onset column of "
    "phenotype rows (NOT and zero-frequency rows skipped)",
    "ontology": "hpo_ontology_2025_03_03 (onset subtree, HP:0003674)",
    "rules": kb["rules"],
    "certainty": "a gene has a bound only when every one of its diseases has an onset class",
    "audit_only": f"{V1} (the add-on's strict onsets), compared in the stats; not read by the rules",
}
inputs = [sources[n].as_input() for n in (*read, E0_SOURCE)] + [{"id": f"artifact:{V1}", "sha256": v1_sha}]
write_manifest(build_manifest(kb_id, agerule.KB_KIND, inputs, params, [kb_path, stats_path]))
print(json.dumps(stats, indent=1))
