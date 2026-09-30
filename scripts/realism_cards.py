"""ADR-0012 G3: disease cards for human-style review of a simulated dataset.

Thirty cards: the ten ANALYSIS-001 genes, plus twenty literature-panel-v2
diseases picked by a salted hash, round-robin over organ systems. Each card
shows, for the disease's simulated cases:
- the literature prevalence next to the simulated true and reported rates;
- the most reported simulated terms;
- R1-train's reporting rates for the gene;
- sex and age;
- example records.

It reads R1-train only.

Usage:
  PYTHONPATH=src .venv/bin/python scripts/realism_cards.py \
      --dataset <export.jsonl.gz> --label v0.4-cand2 --out results/realism/cards/v0.4-cand2
"""

import argparse
import csv
import gzip
import hashlib
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from diagnostic_ar_training import splits
from diagnostic_ar_training.lineage.registry import Purpose, open_source
from diagnostic_ar_training.ontology import Ontology

ANALYSIS_001 = ["NF1", "LMNA", "FBN1", "PTPN11", "KMT2D", "TBX5", "UMOD", "FBXL4", "SPTAN1", "ITPR1"]
PANEL = Path("data/realism/literature-panel-v2.tsv")
SPLIT = Path("data/realism/litpanel-split-v3.tsv")
SALT = "g3-cards-v1"
N_EXTRA = 20
TOP_TERMS = 12
EXAMPLES = 3


def pick_units(panel_units: dict, split_rows: list[dict]) -> list[tuple[str, str]]:
    organ = {(r["gene"], r["disease_id"]): r["organ_system_label"] for r in split_rows}
    chosen = []
    for gene in ANALYSIS_001:
        unit = next((u for u in panel_units if u[0] == gene), None)
        if unit is None:
            unit = next(((r["gene"], r["disease_id"]) for r in split_rows if r["gene"] == gene), (gene, ""))
        chosen.append(unit)
    rest = [u for u in panel_units if u[0] not in ANALYSIS_001]
    by_system = defaultdict(list)
    for u in sorted(rest, key=lambda u: hashlib.sha256(f"{SALT}:{u[0]}:{u[1]}".encode()).hexdigest()):
        by_system[organ.get(u, "other")].append(u)
    systems = sorted(by_system)
    while len(chosen) < len(ANALYSIS_001) + N_EXTRA and any(by_system.values()):
        for s in systems:
            if by_system[s] and len(chosen) < len(ANALYSIS_001) + N_EXTRA:
                chosen.append(by_system[s].pop(0))
    return chosen


def closure(terms, onto: Ontology) -> set[str]:
    out = set()
    for t in terms:
        t = onto.resolve(t) or t
        out.add(t)
        out |= onto.ancestors(t)
    return out


def rate(sets: list[set[str]], term: str) -> float | None:
    return sum(term in s for s in sets) / len(sets) if sets else None


def male_share(sexes) -> float | None:
    known = [x for x in sexes if x in ("male", "female")]
    return sum(x == "male" for x in known) / len(known) if known else None


def fmt(x, digits=2) -> str:
    return "—" if x is None else f"{x:.{digits}f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    onto = Ontology.from_json(open_source("hpo_ontology", Purpose.EVAL))
    label = lambda t: onto.labels.get(t, t)  # noqa: E731
    panel = list(csv.DictReader(PANEL.open(), delimiter="\t"))
    split_rows = list(csv.DictReader(SPLIT.open(), delimiter="\t"))
    units = {}
    for r in panel:
        units.setdefault((r["gene"], r["disease_id"]), []).append(r)
    chosen = pick_units(units, split_rows)
    genes = {g for g, _ in chosen}

    sim = defaultdict(list)
    with gzip.open(args.dataset, "rt") as f:
        for line in f:
            r = json.loads(line)
            if r["gene"] in genes:
                sim[r["gene"]].append(r)
    train = defaultdict(list)
    for c in splits.load_part("r1-v1", splits.Part.TRAIN, Purpose.EVAL):
        if c.gene in genes:
            train[c.gene].append(c)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    index = [
        f"# G3 disease cards: {args.label}\n",
        f"Dataset: `{args.dataset}`\n",
        "| # | Gene | Disease | Sim cases | Panel rows | R1-train n |",
        "|---|---|---|---|---|---|",
    ]
    data = []
    for i, (gene, disease) in enumerate(chosen, 1):
        cases = sim.get(gene, [])
        own = [c for c in cases if disease and disease in (c.get("entity"), c.get("profile_id"))]
        scope = "this disease" if own else "all of the gene's entities (no case carries this disease id)"
        cases_used = own or cases
        real = train.get(gene, [])
        real_sets = [closure(c.present, onto) for c in real]
        rows = units.get((gene, disease), [])
        name = (
            rows[0]["disease_name"]
            if rows
            else next((r["disease_name"] for r in split_rows if r["gene"] == gene), "")
        )

        lit = []
        for r in rows:
            t = onto.resolve(r["hpo_id"]) or r["hpo_id"]
            sex = r["sex_restriction"] or None
            sub = [c for c in cases_used if not sex or c.get("sex") == sex]
            sp = [closure(c["present"], onto) for c in sub]
            st = [closure(c["true_present"], onto) for c in sub]
            lit.append(
                {
                    "hpo_id": t,
                    "feature": r["feature_label"],
                    "prevalence": float(r["prevalence"]),
                    "low": r["prevalence_low"],
                    "high": r["prevalence_high"],
                    "sex": sex,
                    "sim_true": rate(st, t),
                    "sim_reported": rate(sp, t),
                    "r1_train_reported": rate(real_sets, t) if real else None,
                    "independent": r["independent"],
                    "citation": r["citation"],
                }
            )
        direct = Counter(t for c in cases_used for t in set(c["present"]))
        top = [(t, k / len(cases_used)) for t, k in direct.most_common(TOP_TERMS)] if cases_used else []
        ages = [c["age_years"] for c in cases_used if c.get("age_years") is not None]
        real_ages = [c.age_years for c in real if c.age_years is not None]
        card = {
            "n": i,
            "gene": gene,
            "disease_id": disease,
            "disease_name": name,
            "scope": scope,
            "sim_cases": len(cases_used),
            "r1_train_patients": len(real),
            "sim_terms_per_case": (
                statistics.mean(len(c["present"]) for c in cases_used) if cases_used else None
            ),
            "real_terms_per_case": statistics.mean(len(c.present) for c in real) if real else None,
            "sim_male_share": male_share([c.get("sex") for c in cases_used]),
            "real_male_share": male_share([str(getattr(c.sex, "value", c.sex)) for c in real]),
            "sim_age_median": statistics.median(ages) if ages else None,
            "real_age_median": statistics.median(real_ages) if real_ages else None,
            "literature": lit,
            "top_reported": top,
            "examples": [[label(t) for t in c["present"]] for c in cases_used[:EXAMPLES]],
        }
        data.append(card)

        md = [
            f"# Card {i}: {gene} — {name} ({disease or 'no panel disease'})\n",
            f"- Simulated cases ({scope}): {card['sim_cases']}; R1-train patients for {gene}: {len(real)}",
            f"- Terms per case: sim {fmt(card['sim_terms_per_case'], 1)}, "
            f"R1-train {fmt(card['real_terms_per_case'], 1)}",
            f"- Male share: sim {fmt(card['sim_male_share'])}, R1-train {fmt(card['real_male_share'])}",
            f"- Median age (years): sim {fmt(card['sim_age_median'], 1)}, "
            f"R1-train {fmt(card['real_age_median'], 1)}\n",
            "## Literature vs simulation (rates include more specific terms)\n",
            "| Feature | HPO | Literature | Sim true | Sim reported | R1-train reported | Source |",
            "|---|---|---|---|---|---|---|",
        ]
        for f_ in lit:
            ranged = f_["low"] and f_["high"] and f_["low"] != f_["high"]
            rng = f" [{f_['low']}–{f_['high']}]" if ranged else ""
            sx = f" ({f_['sex']} only)" if f_["sex"] else ""
            md.append(
                f"| {f_['feature']}{sx} | {f_['hpo_id']} | {f_['prevalence']:.2f}{rng} | "
                f"{fmt(f_['sim_true'])} | {fmt(f_['sim_reported'])} | "
                f"{fmt(f_['r1_train_reported'])} | {f_['citation']} |"
            )
        if not lit:
            md.append("| (no literature-panel rows for this gene) | | | | | | |")
        md += ["\n## Most reported simulated terms\n", "| Term | Share of cases |", "|---|---|"]
        md += [f"| {label(t)} ({t}) | {k:.2f} |" for t, k in top]
        md += ["\n## Example simulated records\n"]
        md += [f"{j}. " + "; ".join(ex) for j, ex in enumerate(card["examples"], 1)]
        md += ["\n## Review\n", "- Reviewer A verdict: ", "- Reviewer B verdict: "]
        (out / f"card-{i:02d}-{gene}.md").write_text("\n".join(md) + "\n")
        index.append(f"| {i} | {gene} | {name} | {card['sim_cases']} | {len(rows)} | {len(real)} |")
    (out / "INDEX.md").write_text("\n".join(index) + "\n")
    (out / "cards.json").write_text(json.dumps(data, indent=1) + "\n")
    print(f"{len(data)} cards -> {out}")


if __name__ == "__main__":
    main()
