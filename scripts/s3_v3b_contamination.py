"""Contamination check of `s3-data-v3b` and its exclusion list `s3-data-v3b-excl-v1` (ADR-0015 phase 1).

A case is excluded when its (gene upper-cased, present set, excluded set) signature equals one in S3 v1-v3
or in any registered simulated training dataset, or when its (gene, present set) key equals an R1 patient's
(all parts, keys only: R1 is not read as cases). The key-level overlap with S3 v1-v3 and the training sets
is reported too, but does not exclude. Only keys and signatures are compared; no case content is printed.

Usage: PYTHONPATH=src .venv/bin/python scripts/s3_v3b_contamination.py
"""

import gzip
import json
from pathlib import Path

from diagnostic_ar_training import INTERIM_DIR, MANIFESTS_DIR, SPLITS_DIR, splits
from diagnostic_ar_training.gnn.data import overlap_key
from diagnostic_ar_training.lineage.gitinfo import code_state
from diagnostic_ar_training.lineage.hashing import sha256_file
from diagnostic_ar_training.lineage.manifest import (
    build_manifest,
    ensure_new,
    fetch_outputs,
    load_manifest,
    publish,
    write_manifest,
)
from diagnostic_ar_training.lineage.registry import LineageError

ARTIFACT = "s3-data-v3b"
EXCLUSION = "s3-data-v3b-excl-v1"


def rows(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            yield json.loads(line)


def signature(r: dict) -> tuple:
    return r["gene"].upper(), frozenset(r["present"]), frozenset(r.get("excluded") or ())


def main() -> None:
    ensure_new(EXCLUSION)
    state = code_state()
    if state.dirty:
        raise LineageError("commit before producing artifacts")
    data_manifest = load_manifest(ARTIFACT)
    data = next(p for p in fetch_outputs(data_manifest) if p.name.endswith(".jsonl.gz"))
    cases = [(f"s3-v3b:{r['case_id']}", r) for r in rows(data)]
    keys = {cid: overlap_key(r["gene"], r["present"]) for cid, r in cases}
    sigs = {cid: signature(r) for cid, r in cases}

    r1_keys = splits.presentation_keys("r1-v1")
    hits_r1 = {cid for cid, k in keys.items() if k in r1_keys}

    sources = {}
    s3v1 = next(p for p in fetch_outputs(load_manifest("s3-data-v1")) if p.name.endswith(".jsonl.gz"))
    sources["s3-data-v1"] = s3v1
    for earlier in ("s3-data-v2", "s3-data-v3"):
        sources[earlier] = next(
            p for p in fetch_outputs(load_manifest(earlier)) if p.name.endswith(".jsonl.gz")
        )
    for path in sorted(MANIFESTS_DIR.glob("ds-sim*.json")):
        manifest = load_manifest(path.stem)
        if manifest.kind == "simulated-training-dataset":
            sources[path.stem] = next(p for p in fetch_outputs(manifest) if p.name.endswith(".jsonl.gz"))

    by_source, sig_hits, key_hits = {}, set(), set()
    inputs = []
    sig_index = {}
    for cid, s in sigs.items():
        sig_index.setdefault(s, []).append(cid)
    key_index = {}
    for cid, k in keys.items():
        key_index.setdefault(k, []).append(cid)
    for name, path in sources.items():
        sig_found, key_found, total = set(), set(), 0
        for r in rows(path):
            total += 1
            for cid in sig_index.get(signature(r), ()):
                sig_found.add(cid)
            for cid in key_index.get(overlap_key(r["gene"], r["present"]), ()):
                key_found.add(cid)
        by_source[name] = {
            "cases": total,
            "signature_overlap": len(sig_found),
            "present_set_overlap": len(key_found),
        }
        sig_hits |= sig_found
        key_hits |= key_found
        inputs.append({"id": f"artifact:{name}", "sha256": sha256_file(path)})

    excluded = sorted(hits_r1 | sig_hits)
    dropped = set(excluded)
    residual_r1 = sum(1 for cid, k in keys.items() if cid not in dropped and k in r1_keys)
    residual_sig = sum(1 for cid in sigs if cid not in dropped and cid in sig_hits)
    if residual_r1 or residual_sig:
        raise LineageError(f"residual overlap after exclusion: {residual_r1}, {residual_sig}")
    report = {
        "s3_v3b_cases": len(cases),
        "key": "(gene upper-cased, present set)",
        "signature": "(gene upper-cased, present set, excluded set)",
        "vs_r1_all_parts": {"keys": len(r1_keys), "present_set_overlap": len(hits_r1)},
        "vs_s3_v1_v2_v3_and_training": by_source,
        "signature_overlap_total": len(sig_hits),
        "present_set_overlap_total_not_excluded": len(key_hits),
        "excluded": len(excluded),
        "residual_overlap": residual_r1 + residual_sig,
    }
    out_dir = INTERIM_DIR / "datasets" / EXCLUSION
    out_dir.mkdir(parents=True, exist_ok=True)
    exclude_path = out_dir / "exclude.txt"
    exclude_path.write_text("".join(f"{i}\n" for i in excluded))
    report_path = out_dir / "contamination.json"
    report_path.write_text(json.dumps(report, indent=1) + "\n")
    inputs += [
        {"id": f"artifact:{ARTIFACT}", "sha256": sha256_file(data)},
        {"id": "split:r1-v1 (all parts, keys only)", "sha256": sha256_file(SPLITS_DIR / "r1-v1.json")},
        {"id": "split:s3-v3b", "sha256": sha256_file(SPLITS_DIR / "s3-v3b.json")},
    ]
    params = {
        "rule": "drop cases with an R1 (gene, present) key or a signature of S3 v1, S3 v2, S3 v3 or a "
        "registered simulated training dataset",
        "excluded": len(excluded),
        "residual_overlap": 0,
        "ids": "split case ids, prefixed s3-v3b:",
    }
    manifest = build_manifest(
        EXCLUSION, "eval-exclusion-list", inputs, params, [exclude_path, report_path], state=state
    )
    manifest = publish(manifest, EXCLUSION)
    write_manifest(manifest)
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
