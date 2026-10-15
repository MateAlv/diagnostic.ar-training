"""PHASE3 §2f step 2: the add-on's knowledge from E0's knowledge only (`v4.addon.build_kb`), with a manifest.

Writes data/interim/p3-addon/<id>/ft-kb.json.gz, data/p3-addon/<id>.stats.json (committed) and
data/manifests/<id>.json. Needs a clean, committed tree.
Usage: kb.py <id>   (p3-addon-kb-v1)
"""

import json
import sys

from diagnostic_ar_training import DATA_DIR
from diagnostic_ar_training.lineage.manifest import build_manifest, ensure_new, write_manifest
from diagnostic_ar_training.lineage.registry import load_sources
from diagnostic_ar_training.rerank import kb as kb_io
from diagnostic_ar_training.systems.genphenia_v3 import SOURCE as E0_SOURCE
from diagnostic_ar_training.systems.genphenia_v3 import V3Inputs, unpack_bundle
from diagnostic_ar_training.v4 import addon

kb_id = sys.argv[1]
ensure_new(kb_id)
genes = V3Inputs(unpack_bundle()).genes
kb, stats, read = addon.kb_from_sources(genes)
kb_path = addon.ADDON_DIR / kb_id / addon.KB_FILE
kb_io.write(kb, kb_path)
stats_path = DATA_DIR / "p3-addon" / f"{kb_id}.stats.json"
stats_path.parent.mkdir(parents=True, exist_ok=True)
stats_path.write_text(json.dumps(stats, indent=1) + "\n")
sources = load_sources()
params = {
    "schema": kb["schema"],
    "builder": "v4.addon.build_kb (ft.knowledge.build)",
    "vocabulary": "E0 (genphenia_v3) genes",
    "gene_to_disease": "e0_genes_to_phenotype rows with a disease id",
    "annotations": "hpo_annotations_2025_03_03, unmasked; NOT rows never read, zero-frequency rows dropped",
    "ancestors": "hpo_ontology_2025_03_03",
    "orphanet": None,
    "hgnc": None,
    "overrides": None,
    "embeddings_at_use": "E0's frozen term embeddings (genphenia_v3), for neg_embed",
}
inputs = [sources[n].as_input() for n in (*read, E0_SOURCE)]
write_manifest(build_manifest(kb_id, addon.KB_KIND, inputs, params, [kb_path, stats_path]))
print(json.dumps({k: v for k, v in stats.items() if not k.startswith("hpoa_")}, indent=1))
