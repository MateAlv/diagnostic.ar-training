# ruff: noqa: E501
"""Scripted analysis of the pre-registered S3-v2-test session (EXP-Q-001 P1/S1/S2, EXP-B-004 descriptive and H3).

Usage: python scripts/sealed_analysis.py
Reads the interview outputs of the session from results/EXP-B-004/sealed/ and writes
results/EXP-Q-001/sealed-analysis.{md,json} and results/EXP-B-004/sealed-analysis.{md,json}.
It never reads the sealed split: it only reads per-case ranks already produced by the ledgered runs, plus
analysis-only case metadata (entity, age) for the H3 subsets.
Every CI is a paired bootstrap over genes (cluster resampling), 2000 resamples, seed 0 (eval.metrics.paired_bootstrap defaults).
"""

import json
import sys

from diagnostic_ar_training import RESULTS_DIR
from diagnostic_ar_training.cohorts import s3
from diagnostic_ar_training.eval import dev_run, dev_search, harness, question_run
from diagnostic_ar_training.knowledge import annotation_split
from diagnostic_ar_training.lineage.manifest import fetch_outputs, load_manifest
from diagnostic_ar_training.rerank import kb

SEALED_DIR = RESULTS_DIR / "EXP-B-004" / "sealed"
BOOTSTRAP = {"resamples": 2000, "seed": 0, "unit": "gene"}
HARM_CAP = 0.05

F = "8ecd5b320f33"
Q_RUNS = {
    "Q2b": ("Q2b-lam0.6", F, 0),
    "Q0": ("Q0", F, 0),
    "Q1": ("Q1", F, 0),
    "Q2b-noise": ("Q2b-lam0.6", F, 0.05),
    "Q0-noise": ("Q0", F, 0.05),
}
B_SYSTEMS = {
    "F": F,
    "rr-v1 formula on kb-v6": "2b6a00674f4c",
    "F on kb-v7": "af6da5cdbf19",
    "F + onset 0.5": "458768f1bca4",
    "F + sex 0.5": "96e69f9e62fa",
    "F + age_mean 0.5": "5b30ab00d1a0",
    "frontier <=7.5% (propagated k0.8 w0.75)": "c34cb31bd53f",
    "frontier <=10% (capped C2 w2)": "84296576dc8e",
}
H3_SYSTEMS = ("F + onset 0.5", "F + age_mean 0.5", "F + sex 0.5")


def load(strategy: str, cfg: str, noise: float) -> list[dict]:
    path = SEALED_DIR / f"s3-v2-test__{strategy}__cfg-{cfg}__noise{noise:g}.interviews.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def recs(rows: list[dict], key: str) -> list[dict]:
    return question_run.records(rows, key)


def cmp(a_rows, a_key, b_rows, b_key, mask=None) -> dict:
    return dev_search.compare(recs(a_rows, a_key), recs(b_rows, b_key), mask)


def cell(d: dict) -> str:
    if not d["n"]:
        return "n/a (n=0)"
    return f"{d['delta']:+.4f} [{d['ci95'][0]:+.4f}, {d['ci95'][1]:+.4f}]"


def check_same_cases(*runs: list[dict]) -> None:
    ids = [r["case_id"] for r in runs[0]]
    for run in runs[1:]:
        if [r["case_id"] for r in run] != ids:
            raise SystemExit("runs cover different cases or orders")


def q_section() -> tuple[dict, list[str]]:
    runs = {name: load(*spec) for name, spec in Q_RUNS.items()}
    check_same_cases(*runs.values())
    out: dict = {"bootstrap": BOOTSTRAP, "n": len(runs["Q0"])}
    lines = ["| strategy | noise | primary Δ vs E0-initial [95% CI] | harmed | helped | questioner effect [CI] | "
             "re-ranker effect [CI] | re-ranker harmed |", "|" + "---|" * 8]  # fmt: skip
    for name, rows in runs.items():
        strategy, _, noise = Q_RUNS[name]
        prim = cmp(rows, "rank_initial", rows, "rank_final")
        qeff = cmp(rows, "rank_initial", rows, "rank_answers")
        reff = cmp(rows, "rank_answers", rows, "rank_final")
        out[name] = {"primary": prim, "questioner_effect": qeff, "reranker_effect": reff}
        lines.append(
            f"| {strategy} | {noise:g} | {cell(prim)} | {prim['harmed']:.4f} | {prim['helped']:.4f} | "
            f"{cell(qeff)} | {cell(reff)} | {reff['harmed']:.4f} |"
        )
    p1 = cmp(runs["Q0"], "rank_final", runs["Q2b"], "rank_final")
    rr_harmed = out["Q2b"]["reranker_effect"]["harmed"]
    passed = p1["ci95"][0] > 0 and rr_harmed <= HARM_CAP
    s1 = cmp(runs["Q1"], "rank_final", runs["Q2b"], "rank_final")
    s2 = cmp(runs["Q0-noise"], "rank_final", runs["Q2b-noise"], "rank_final")
    out.update(
        P1={"paired_Q2b_minus_Q0": p1, "reranker_effect_harmed_Q2b": rr_harmed, "harm_cap": HARM_CAP, "pass": passed},
        S1={"paired_Q2b_minus_Q1": s1},
        S2={"paired_Q2b_minus_Q0_noise0.05": s2},
    )  # fmt: skip
    lines += [
        "",
        f"P1, Q2b − Q0 (final MRR, same cases): {cell(p1)}, harmed {p1['harmed']:.4f}, helped {p1['helped']:.4f}, n={p1['n']}",
        f"- re-ranker-effect harmed share under Q2b: {rr_harmed:.4f} (cap {HARM_CAP})",
        f"- CI lower bound > 0: {p1['ci95'][0] > 0}; harmed <= cap: {rr_harmed <= HARM_CAP}; **P1 {'PASSES' if passed else 'FAILS'}**",
        f"S1, Q2b − Q1: {cell(s1)}, harmed {s1['harmed']:.4f}, helped {s1['helped']:.4f}",
        f"S2, 5% noise, Q2b − Q0: {cell(s2)}",
    ]
    return out, lines


def subset_masks(rows: list[dict]) -> dict[str, list[bool]]:
    ids = {r["case_id"] for r in rows}
    data = next(p for p in fetch_outputs(load_manifest("s3-data-v2")) if p.name.endswith(".jsonl.gz"))
    by_id = {c.case_id: c for c, _ in s3.read_dataset(data, "s3-v2") if c.case_id in ids}
    ordered = [{"case": by_id[r["case_id"]], "case_id": r["case_id"], "gene": r["gene"]} for r in rows]
    entities = s3.read_entities(data, "s3-v2", ids)
    lit = {
        line.split("\t")[0]
        for line in fetch_outputs(load_manifest("onset-ages-v2"))[0].read_text().splitlines()[1:]
    }
    half_b = annotation_split.read(fetch_outputs(load_manifest("annot-split-v2"))[0])
    kb_data = kb.read(fetch_outputs(load_manifest("kb-v6"))[0])
    source_of = {d: v["onset_source"] for d, v in kb_data["diseases"].items()}
    return dev_run.subset_masks(ordered, entities, lit, half_b, source_of)


def b_section() -> tuple[dict, list[str]]:
    runs = {name: load("Q0", cfg, 0) for name, cfg in B_SYSTEMS.items()}
    check_same_cases(*runs.values())
    ref = runs["F"]
    same_answers = all(
        [(r["questions"], r["answers"], r["rank_answers"], r["rank_initial"]) for r in rows]
        == [(r["questions"], r["answers"], r["rank_answers"], r["rank_initial"]) for r in ref]
        for rows in runs.values()
    )
    out: dict = {"bootstrap": BOOTSTRAP, "n": len(ref), "same_interview_in_every_run": same_answers}
    lines = [
        f"Same Q0 interview and E0+answers ranks in every run: {same_answers}",
        "",
        "| system | config | Δ MRR vs E0+answers [95% CI] | harmed | helped | MRR final | Δ vs F [CI] |",
        "|" + "---|" * 7,
    ]
    for name, rows in runs.items():
        d = cmp(rows, "rank_answers", rows, "rank_final")
        vs_f = cmp(ref, "rank_final", rows, "rank_final")
        out[name] = {"config": B_SYSTEMS[name], "vs_E0+answers": d, "vs_F": vs_f, "mrr_final": harness.summarize(
            recs(rows, "rank_final"))["all"]["mrr"]}  # fmt: skip
        lines.append(
            f"| {name} | {B_SYSTEMS[name]} | {cell(d)} | {d['harmed']:.4f} | {d['helped']:.4f} | "
            f"{out[name]['mrr_final']:.4f} | {cell(vs_f)} |"
        )
    masks = subset_masks(ref)
    names = ["lit_onset", "lit_onset_src_hpoa", "lit_onset_src_orphanet", "lit_onset_src_orphanet_exact_alignment",
             "lit_onset_src_none", "lit_onset_age_known", "age_known", "sex_known"]  # fmt: skip
    out["subset_sizes"] = {s: sum(masks[s]) for s in names}
    out["H3"] = {}
    lines += [
        "",
        "H3 and sex on subsets (sizes: " + ", ".join(f"{s}={out['subset_sizes'][s]}" for s in names) + ")",
    ]
    lines += [
        "",
        "| system | subset | n | Δ vs E0+answers [CI] | harmed | Δ vs F [CI] |",
        "|" + "---|" * 6,
    ]
    for name in H3_SYSTEMS:
        rows = runs[name]
        out["H3"][name] = {}
        for s in names:
            d = cmp(rows, "rank_answers", rows, "rank_final", masks[s])
            vs_f = cmp(ref, "rank_final", rows, "rank_final", masks[s])
            out["H3"][name][s] = {"vs_E0+answers": d, "vs_F": vs_f}
            lines.append(f"| {name} | {s} | {d['n']} | {cell(d)} | {d['harmed']:.4f} | {cell(vs_f)} |")
    return out, lines


def write(exp: str, out: dict, lines: list[str]) -> None:
    directory = RESULTS_DIR / exp
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "sealed-analysis.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    (directory / "sealed-analysis.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


def main() -> None:
    q, q_lines = q_section()
    write("EXP-Q-001", q, q_lines)
    b, b_lines = b_section()
    write("EXP-B-004", b, b_lines)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        raise SystemExit(__doc__)
    main()
