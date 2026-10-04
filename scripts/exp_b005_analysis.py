# ruff: noqa: E501
"""Scripted analysis of EXP-B-005 (symptom-onset age in the re-ranker, S3 v3b, Q2b interview).

Usage:
    python scripts/exp_b005_analysis.py dev    # dev selection of w: writes results/EXP-B-005/dev-search.tsv
    python scripts/exp_b005_analysis.py test   # the P1 verdict from the one sealed session

It never opens a split: it reads the per-case ranks that `dxt s3 onset-session` wrote under
results/EXP-B-005/<dev|sealed>/, plus analysis-only metadata of those cases (entity, literature-onset flag).
Primary population: cases whose onset age came from the literature (`literature-onset-cases.txt` of
s3-data-v3b). Every CI is a paired bootstrap over genes, 2000 resamples, seed 0 (`eval.metrics.paired_bootstrap`).
The first arm of the session (F) is the reference; every other arm is a candidate F + onset w.

Selection rule (ADR-0015, fixed): maximise the paired Δ (candidate − F) on the literature-onset dev cases subject to
harmed(candidate vs E0+answers) <= 5% and the R1-dev no-harm check; a tie (equal at six decimals) goes to the smaller w.
P1 (sealed): paired Δ CI lower bound > 0 and harmed <= 5%.
"""

import csv
import gzip
import json
import sys

from diagnostic_ar_training import RESULTS_DIR
from diagnostic_ar_training.cohorts import s3
from diagnostic_ar_training.eval import dev_search, onset_run
from diagnostic_ar_training.lineage.manifest import fetch_outputs, load_manifest
from diagnostic_ar_training.rerank import kb

EXP = "EXP-B-005"
SPLIT = "s3-v3b"
HARM_CAP = 0.05
BOOTSTRAP = {"resamples": 2000, "seed": 0, "unit": "gene"}
SOURCES = ("hpoa", "orphanet", "orphanet_exact_alignment", None)

TSV_COLUMNS = (
    "arm_id", "config_hash", "w", "n_lit", "delta_vs_F", "ci_lo", "ci_hi", "harmed_vs_e0", "helped_vs_e0",
    "delta_vs_e0", "r1dev_delta", "r1dev_ci_lo", "r1dev_ci_hi", "r1dev_pass", "feasible", "selected",
    "all_delta_vs_F", "all_ci_lo", "all_ci_hi", "all_harmed", "known_delta_vs_F", "known_ci_lo",
    "known_ci_hi", "known_harmed", "code_sha",
)  # fmt: skip


def read_ranks(path) -> tuple[list[str], list[dict]]:
    with gzip.open(path, "rt") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        arm_ids = list(reader.fieldnames)[4:]
        rows = list(reader)
    return arm_ids, rows


def cell(d: dict) -> str:
    if not d["n"]:
        return "n/a (n=0)"
    return f"{d['delta']:+.4f} [{d['ci95'][0]:+.4f}, {d['ci95'][1]:+.4f}]"


def masks_for(rows: list[dict], interviews: list[dict]) -> dict[str, list[bool]]:
    data = next(p for p in fetch_outputs(load_manifest("s3-data-v3b")) if p.name.endswith(".jsonl.gz"))
    lit_path = next(
        p for p in fetch_outputs(load_manifest("s3-data-v3b")) if p.name == "literature-onset-cases.txt"
    )
    lit_ids = {f"{SPLIT}:{x}" for x in lit_path.read_text().split()}
    ids = [r["case_id"] for r in rows]
    if ids != [i["case_id"] for i in interviews]:
        raise SystemExit("ranks and interviews cover different cases")
    entities = s3.read_entities(data, SPLIT, set(ids))
    kb_data = kb.read(fetch_outputs(load_manifest("kb-v6"))[0])
    source_of = {d: v["onset_source"] for d, v in kb_data["diseases"].items()}
    lit = [c in lit_ids for c in ids]
    known = [i["case"].onset_years is not None for i in interviews]
    out = {
        "lit": lit,
        "all": [True] * len(ids),
        "known": known,
        "lit_known": [a and b for a, b in zip(lit, known, strict=True)],
        "lit_unknown": [a and not b for a, b in zip(lit, known, strict=True)],
    }
    for source in SOURCES:
        label = "none" if source is None else source
        flags = [a and source_of.get(entities[c]) == source for a, c in zip(lit, ids, strict=True)]
        out[f"lit_src_{label}"] = flags
        out[f"lit_known_src_{label}"] = [a and b for a, b in zip(flags, known, strict=True)]
    return out


def analyse(directory, report_name: str) -> dict:
    session = json.loads((directory / "session.json").read_text())
    arm_ids, rows = read_ranks(directory / "ranks.tsv.gz")
    interviews = onset_run.read_rows(directory / "interviews.jsonl.gz")
    masks = masks_for(rows, interviews)
    ids = [r["case_id"] for r in rows]
    genes = [r["gene"] for r in rows]

    def recs(column):
        return dev_search.records(ids, genes, [float(r[column]) for r in rows])

    base, ref = recs("e0_answers"), recs(arm_ids[0])
    out: dict = {
        "exp": EXP,
        "part": report_name,
        "bootstrap": BOOTSTRAP,
        "cases": len(rows),
        "mask_sizes": {k: sum(v) for k, v in masks.items()},
        "driver_rank_parity": session["driver_rank_parity"],
        "code_sha_session": session["code_sha"],
        "reference": {
            "arm_id": arm_ids[0],
            "vs_e0": {k: dev_search.compare(base, ref, m) for k, m in masks.items()},
        },
        "arms": {},
    }
    configs = {a["arm_id"]: a for a in session["arms"]}
    for arm_id in arm_ids[1:]:
        new = recs(arm_id)
        out["arms"][arm_id] = {
            "config_hash": configs[arm_id]["config_hash"],
            "w": configs[arm_id]["config"]["weights"]["onset"],
            "vs_F": {k: dev_search.compare(ref, new, m) for k, m in masks.items()},
            "vs_e0": {k: dev_search.compare(base, new, m) for k, m in masks.items()},
        }
    return out


def fmt_tables(out: dict) -> list[str]:
    lines = [
        f"cases={out['cases']}; masks: " + ", ".join(f"{k}={v}" for k, v in out["mask_sizes"].items()),
        "",
    ]
    lines += [
        "| arm | w | subset | n | Δ vs F [95% CI over genes] | harmed vs E0+answers | helped | Δ vs E0+answers [CI] |",
        "|" + "---|" * 8,
    ]
    for arm_id, a in out["arms"].items():
        for k in a["vs_F"]:
            f, e = a["vs_F"][k], a["vs_e0"][k]
            lines.append(
                f"| {arm_id} | {a['w']:g} | {k} | {f['n']} | {cell(f)} | {e['harmed']:.4f} | {e['helped']:.4f} | {cell(e)} |"
            )
    ref = out["reference"]["vs_e0"]
    lines += [
        "",
        f"F ({out['reference']['arm_id']}) vs E0+answers: "
        + "; ".join(
            f"{k} {cell(v)} harmed {v['harmed']:.4f}" for k, v in ref.items() if k in ("lit", "all", "known")
        ),
    ]
    return lines


def write(name: str, out: dict, lines: list[str]) -> None:
    directory = RESULTS_DIR / EXP
    (directory / f"{name}.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    (directory / f"{name}.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


def dev() -> None:
    directory = RESULTS_DIR / EXP / "dev"
    out = analyse(directory, "dev")
    r1 = json.loads((directory / "r1dev.json").read_text())
    session = json.loads((directory / "session.json").read_text())
    table = []
    for arm_id, a in out["arms"].items():
        prim, r = a["vs_F"]["lit"], r1["arms"][arm_id]
        harmed = a["vs_e0"]["lit"]["harmed"]
        r1_pass = dev_search.r1_no_harm(r["delta"], r["ci95"][1])
        a["r1dev"] = r | {"pass": r1_pass}
        a["feasible"] = bool(harmed <= HARM_CAP and r1_pass)
        table.append((arm_id, a, prim, harmed, r1_pass))
    feasible = [t for t in table if t[1]["feasible"]]
    selected = None
    if feasible:
        best = max(round(t[2]["delta"], 6) for t in feasible)
        selected = min((t for t in feasible if round(t[2]["delta"], 6) == best), key=lambda t: t[1]["w"])[0]
    out["selected"] = selected
    rows = []
    for arm_id, a, prim, harmed, r1_pass in table:
        al, kn, r = a["vs_F"]["all"], a["vs_F"]["known"], a["r1dev"]
        rows.append({
            "arm_id": arm_id, "config_hash": a["config_hash"], "w": a["w"], "n_lit": prim["n"],
            "delta_vs_F": round(prim["delta"], 6), "ci_lo": round(prim["ci95"][0], 6), "ci_hi": round(prim["ci95"][1], 6),
            "harmed_vs_e0": round(harmed, 5), "helped_vs_e0": round(a["vs_e0"]["lit"]["helped"], 5),
            "delta_vs_e0": round(a["vs_e0"]["lit"]["delta"], 6),
            "r1dev_delta": round(r["delta"], 6), "r1dev_ci_lo": round(r["ci95"][0], 6), "r1dev_ci_hi": round(r["ci95"][1], 6),
            "r1dev_pass": int(r1_pass), "feasible": int(a["feasible"]), "selected": int(arm_id == selected),
            "all_delta_vs_F": round(al["delta"], 6), "all_ci_lo": round(al["ci95"][0], 6), "all_ci_hi": round(al["ci95"][1], 6),
            "all_harmed": round(a["vs_e0"]["all"]["harmed"], 5),
            "known_delta_vs_F": round(kn["delta"], 6), "known_ci_lo": round(kn["ci95"][0], 6), "known_ci_hi": round(kn["ci95"][1], 6),
            "known_harmed": round(a["vs_e0"]["known"]["harmed"], 5), "code_sha": session["code_sha"],
        })  # fmt: skip
    with (RESULTS_DIR / EXP / "dev-search.tsv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, TSV_COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    lines = fmt_tables(out)
    lines += [
        "",
        "R1-dev no-harm: "
        + "; ".join(
            f"{t[0]} {t[1]['r1dev']['delta']:+.4f} [{t[1]['r1dev']['ci95'][0]:+.4f}, {t[1]['r1dev']['ci95'][1]:+.4f}] pass={t[4]}"
            for t in table
        ),
    ]
    lines += ["", f"feasible: {[t[0] for t in feasible]}", f"SELECTED: {selected}"]
    write("dev-analysis", out, lines)


def test() -> None:
    out = analyse(RESULTS_DIR / EXP / "sealed", "test")
    verdicts = {}
    for arm_id, a in out["arms"].items():
        p1 = a["vs_F"]["lit"]
        harmed = a["vs_e0"]["lit"]["harmed"]
        verdicts[arm_id] = {
            "delta": p1["delta"], "ci95": p1["ci95"], "harmed": harmed, "n": p1["n"],
            "ci_lower_gt_0": p1["ci95"][0] > 0, "harmed_le_cap": harmed <= HARM_CAP,
            "pass": bool(p1["ci95"][0] > 0 and harmed <= HARM_CAP),
        }  # fmt: skip
    out["P1"] = verdicts
    lines = fmt_tables(out)
    for arm_id, v in verdicts.items():
        lines += ["", f"P1 {arm_id}: Δ {v['delta']:+.4f} [{v['ci95'][0]:+.4f}, {v['ci95'][1]:+.4f}], harmed {v['harmed']:.4f}, n={v['n']}; "
                      f"CI lower > 0: {v['ci_lower_gt_0']}; harmed <= {HARM_CAP}: {v['harmed_le_cap']}; **P1 {'PASSES' if v['pass'] else 'FAILS'}**"]  # fmt: skip
    write("sealed-analysis", out, lines)


if __name__ == "__main__":
    if sys.argv[1:] == ["dev"]:
        dev()
    elif sys.argv[1:] == ["test"]:
        test()
    else:
        raise SystemExit(__doc__)
