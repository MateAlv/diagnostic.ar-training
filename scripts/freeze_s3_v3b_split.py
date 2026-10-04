"""Freeze the `s3-v3b` dev/test split on `s3-data-v3b` (salted hash of the case id; test sealed).

Only case ids are used. Usage: PYTHONPATH=src .venv/bin/python scripts/freeze_s3_v3b_split.py
"""

from diagnostic_ar_training.cohorts import s3
from diagnostic_ar_training.lineage.manifest import fetch_outputs, load_manifest

manifest = load_manifest("s3-data-v3b")
dataset = next(p for p in fetch_outputs(manifest) if p.name.endswith(".jsonl.gz"))
sha = next(o.sha256 for o in manifest.outputs if o.path.endswith(".jsonl.gz"))
body = s3.freeze("s3-v3b", dataset, sha)
print(body["counts"], body["content_sha256"], body["sealed_parts"])
