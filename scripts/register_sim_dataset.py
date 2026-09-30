"""Register a simulated training export as an artifact, with its contamination check and exclusion list.

Writes two manifests, the way `ds-sim0.3.1-A-n100-s1001` and its `-excl-v1` were registered:
- `<id>`: the export, its dataset card and `contamination.json`, with every input's sha256;
- `<id>-excl-v1`: the case ids whose (gene upper-cased, present set) equals an R1 patient's (all parts, keys
  only, `splits.presentation_keys`) or an S3 case's (`s3-data-v1`, all cases), and a residual overlap of 0.

Inputs are given as `artifact:<id>=<path>` (the file must be one of the artifact's manifest outputs),
`source:<name>` (a pinned source, sha-verified) or `file:<label>=<path>`.

Usage:
  PYTHONPATH=src .venv/bin/python scripts/register_sim_dataset.py --artifact ds-sim0.4.0-A-n100-s1001 \
    --export <sim>/ds.jsonl.gz --card <sim>/ds.card.json --profiles <sim>/profiles-A.jsonl \
    --profiles-summary <sim>/profiles-A.summary.json --run-summary <sim>/run.summary.json \
    --input artifact:genes-v2=<path> ... --param key=value ... [--publish]
"""

import argparse
import gzip
import json
import shutil
from pathlib import Path

from diagnostic_ar_training import INTERIM_DIR, SPLITS_DIR, splits
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
from diagnostic_ar_training.lineage.registry import LineageError, load_sources, verify

S3_ARTIFACT = "s3-data-v1"


def input_ref(spec: str) -> dict:
    kind, rest = spec.split(":", 1)
    if kind == "source":
        source = load_sources()[rest]
        if not verify(source):
            raise LineageError(f"source {rest} is missing or modified")
        return source.as_input()
    name, path = rest.split("=", 1)
    sha = sha256_file(Path(path))
    if kind == "artifact":
        if sha not in {o.sha256 for o in load_manifest(name).outputs}:
            raise LineageError(f"{path} is not an output of {name}")
        return {"id": f"artifact:{name}", "sha256": sha}
    if kind == "file":
        return {"id": f"file:{name}", "sha256": sha}
    raise ValueError(f"unknown input kind in {spec!r}")


def read_rows(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            yield json.loads(line)


def signature(gene: str, present, excluded) -> tuple:
    return gene.upper(), frozenset(present), frozenset(excluded or ())


def parse_value(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--artifact", required=True)
    ap.add_argument("--export", type=Path, required=True)
    ap.add_argument("--card", type=Path, required=True)
    ap.add_argument("--profiles", type=Path, required=True)
    ap.add_argument("--profiles-summary", type=Path, required=True)
    ap.add_argument("--run-summary", type=Path, required=True)
    ap.add_argument("--input", action="append", default=[], dest="inputs")
    ap.add_argument("--param", action="append", default=[], dest="params")
    ap.add_argument("--publish", action="store_true")
    args = ap.parse_args()

    artifact, exclusion = args.artifact, f"{args.artifact}-excl-v1"
    ensure_new(artifact)
    ensure_new(exclusion)
    state = code_state()
    if state.dirty:
        raise LineageError("working tree has uncommitted changes; commit before producing artifacts")

    profiles_summary = json.loads(args.profiles_summary.read_text())
    if profiles_summary["output"]["sha256"] != sha256_file(args.profiles):
        raise LineageError("the profiles do not match their build summary")
    card = json.loads(args.card.read_text())
    if card["file"]["sha256"] != sha256_file(args.export):
        raise LineageError("the export does not match its dataset card")
    if card["inputs"]["run_summary"]["sha256"] != sha256_file(args.run_summary):
        raise LineageError("the run summary does not match the dataset card")

    out_dir = INTERIM_DIR / "datasets" / artifact
    out_dir.mkdir(parents=True, exist_ok=True)
    export = out_dir / f"{artifact}.jsonl.gz"
    card_out = out_dir / f"{artifact}.card.json"
    shutil.copyfile(args.export, export)
    shutil.copyfile(args.card, card_out)
    if sha256_file(export) != card["file"]["sha256"]:
        raise LineageError("copy of the export differs from the original")

    s3_manifest = load_manifest(S3_ARTIFACT)
    s3_path = next(p for p in fetch_outputs(s3_manifest) if p.name.endswith(".jsonl.gz"))
    s3_rows = list(read_rows(s3_path))
    s3_keys = {overlap_key(r["gene"], r["present"]) for r in s3_rows}
    s3_signatures = {signature(r["gene"], r["present"], r.get("excluded")) for r in s3_rows}
    r1_keys = splits.presentation_keys("r1-v1")

    cases = 0
    hits = {"vs_r1_all_parts": [], "vs_s3": []}
    s3_signature_hits = 0
    for r in read_rows(export):
        cases += 1
        key = overlap_key(r["gene"], r["present"])
        if key in r1_keys:
            hits["vs_r1_all_parts"].append(r["case_id"])
        if key in s3_keys:
            hits["vs_s3"].append(r["case_id"])
        if signature(r["gene"], r["present"], r.get("excluded")) in s3_signatures:
            s3_signature_hits += 1
    excluded = sorted({i for ids in hits.values() for i in ids})
    dropped = set(excluded)
    residual = sum(
        1
        for r in read_rows(export)
        if r["case_id"] not in dropped and overlap_key(r["gene"], r["present"]) in (r1_keys | s3_keys)
    )
    if residual:
        raise LineageError(f"residual overlap after exclusion: {residual}")
    contamination = {
        "train_cases": cases,
        "key": "(gene upper-cased, present set)",
        "vs_r1_all_parts": {
            "keys": len(r1_keys),
            "present_set_overlap": len(hits["vs_r1_all_parts"]),
            "signature_overlap": "not computed: R1 is read as keys only",
        },
        "vs_s3": {
            "cases": len(s3_rows),
            "present_set_overlap": len(hits["vs_s3"]),
            "signature_overlap": s3_signature_hits,
        },
        "excluded": len(excluded),
        "residual_overlap": residual,
    }
    contamination_path = out_dir / "contamination.json"
    contamination_path.write_text(json.dumps(contamination, indent=1) + "\n")

    inputs = [input_ref(s) for s in args.inputs] + [
        {"id": "simulator-profiles:A (build summary)", "sha256": sha256_file(args.profiles_summary)},
        {"id": "simulator-profiles:A", "sha256": sha256_file(args.profiles)},
        {"id": "simulator-run-summary", "sha256": sha256_file(args.run_summary)},
    ]
    params = dict(p.split("=", 1) for p in args.params)
    params = {k: parse_value(v) for k, v in params.items()}
    manifest = build_manifest(
        artifact,
        "simulated-training-dataset",
        inputs,
        params,
        [contamination_path, card_out, export],
        state=state,
    )
    if args.publish:
        manifest = publish(manifest, artifact)
    write_manifest(manifest)

    excl_dir = INTERIM_DIR / "datasets" / exclusion
    excl_dir.mkdir(parents=True, exist_ok=True)
    excl_path = excl_dir / "exclude.txt"
    excl_path.write_text("".join(f"{i}\n" for i in excluded))
    excl_manifest = build_manifest(
        exclusion,
        "training-exclusion-list",
        [
            {"id": f"artifact:{artifact}", "sha256": sha256_file(export)},
            {"id": f"artifact:{S3_ARTIFACT}", "sha256": sha256_file(s3_path)},
            {"id": "split:r1-v1 (all parts, keys only)", "sha256": sha256_file(SPLITS_DIR / "r1-v1.json")},
        ],
        {
            "rule": "drop training cases whose (gene, present set) equals any S3 case or any R1 patient",
            "excluded": len(excluded),
            "residual_overlap": residual,
        },
        [excl_path],
        state=state,
    )
    if args.publish:
        excl_manifest = publish(excl_manifest, exclusion)
    write_manifest(excl_manifest)
    print(json.dumps(contamination, indent=1))


if __name__ == "__main__":
    main()
