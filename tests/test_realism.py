import gzip
import json
from collections import Counter

import numpy as np
import pytest

from diagnostic_ar_training.cli_sim import check_budget
from diagnostic_ar_training.eval import realism as RZ
from diagnostic_ar_training.lineage.registry import LineageError
from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.systems import Scored

OBO = "http://purl.obolibrary.org/obo/HP_"
HP = {
    "0000001": [],
    "0000118": ["0000001"],
    "0000707": ["0000118"],
    "0001250": ["0000707"],
    "0002069": ["0001250"],
    "0000478": ["0000118"],
    "0000505": ["0000478"],
}


@pytest.fixture
def onto(tmp_path):
    nodes = [{"id": OBO + c, "lbl": c} for c in HP]
    edges = [{"sub": OBO + c, "pred": "is_a", "obj": OBO + p} for c, ps in HP.items() for p in ps]
    (tmp_path / "hp.json").write_text(json.dumps({"graphs": [{"nodes": nodes, "edges": edges}]}))
    return Ontology.from_json(tmp_path / "hp.json")


def test_loaders(tmp_path):
    with gzip.open(tmp_path / "x.jsonl.gz", "wt") as handle:
        handle.write(
            json.dumps({"case_id": "a", "gene": "G", "present": ["HP:1"], "excluded": [], "sex": "male"})
        )
    assert RZ.load_export(tmp_path / "x.jsonl.gz") == [RZ.SimCase("a", "G", ("HP:1",), (), "male")]
    (tmp_path / "up.json").write_text(json.dumps({"G": [["HP:2", "HP:1"], []], "-": [["HP:1"]]}))
    assert RZ.load_graphens(tmp_path / "up.json") == [RZ.SimCase("up:G:0", "G", ("HP:1", "HP:2"), None)]


def test_per_gene_rho_needs_enough_dev_patients_and_reports_missing_genes():
    real = [{"A", "B"}, {"A"}, {"A", "C"}] * 4  # 12 patients: A 1.0, B 0.33, C 0.33
    sim_good = [{"A", "B", "C"}, {"A"}, {"A"}]
    dev = {"G": real, "H": real, "SMALL": real[:3]}
    out = RZ.per_gene_rho(dev, {"G": sim_good}, lambda g: {"A", "B", "C", "D"})
    assert out["genes_eligible"] == 2 and out["genes_scored"] == 1
    assert out["genes_missing_from_dataset"] == ["H"]
    assert out["per_gene"]["G"]["rho"] > 0.9


def test_frequency_calibration_bins_by_hpoa_frequency():
    dev = {"G": [{"A"}, {"A"}, {"B"}, {"A"}, {"A"}]}
    sim = {"G": [{"A", "B"}, {"B"}]}
    out = RZ.frequency_calibration(dev, sim, lambda g: {"A": 0.9, "B": None})
    bins = {b["hpoa_frequency"]: b for b in out["bins"]}
    assert bins["0.8-1.0"]["real_rate"] == pytest.approx(0.8) and bins["0.8-1.0"]["sim_rate"] == 0.5
    assert bins["unknown"]["real_rate"] == pytest.approx(0.2) and bins["unknown"]["sim_rate"] == 1.0


def test_wasserstein_of_shifted_counts():
    assert RZ.wasserstein([1, 2, 3], [2, 3, 4]) == pytest.approx(1.0)


def write_panel(path, with_kind):
    head = "gene\tfeature_label\thpo_id\tliterature_prevalence\tsex" + ("\tsource_kind" if with_kind else "")
    rows = [
        "G\tseizure\tHP:0001250\t0.9\t" + ("\tgenereviews" if with_kind else ""),
        "G\teye\tHP:0000505\t0.5\tmale" + ("\torphanet" if with_kind else ""),
    ]
    path.write_text("\n".join([head, *rows]) + "\n")


def test_panel_primary_error_leaves_out_orphanet_rows_and_filters_sex(tmp_path, onto, capsys):
    sim = {
        "G": [
            RZ.SimCase("1", "G", ("HP:0002069",), (), "male"),  # a descendant counts as the feature
            RZ.SimCase("2", "G", ("HP:0000505",), (), "female"),
        ]
    }
    write_panel(tmp_path / "v2.tsv", with_kind=True)
    rows, has_kind = RZ.read_panel(tmp_path / "v2.tsv")
    out = RZ.panel_errors(rows, sim, RZ.Closure(onto), has_kind)
    per_row = {r["hpo_id"]: r for r in out["per_row"]}
    assert per_row["HP:0001250"]["emission"] == 0.5 and per_row["HP:0001250"]["abs_error"] == pytest.approx(
        0.4
    )
    assert per_row["HP:0000505"]["sim_cases"] == 1 and per_row["HP:0000505"]["emission"] == 0.0
    assert out["primary"]["mae"] == pytest.approx(0.4) and out["all_rows"]["mae"] == pytest.approx(0.45)

    write_panel(tmp_path / "v1.tsv", with_kind=False)
    rows, has_kind = RZ.read_panel(tmp_path / "v1.tsv")
    out = RZ.panel_errors(rows, sim, RZ.Closure(onto), has_kind)
    assert not has_kind and out["primary"]["mae"] == out["all_rows"]["mae"]
    assert "no source_kind column" in capsys.readouterr().err


def test_matched_pairs_use_same_gene_first_then_any_unused_case():
    real = [("r1", "A"), ("r2", "A"), ("r3", "B")]
    pairs = RZ.matched_pairs(real, {"A": [0], "C": [1, 2]}, 3, seed=1)
    partner = dict(pairs)
    assert len(pairs) == 3 and len(set(partner.values())) == 3
    matched = [i for i, j in pairs if j == 0]
    assert len(matched) == 1 and real[matched[0]][1] == "A"


def test_c2st_separates_different_distributions_and_not_identical_ones():
    rng = np.random.default_rng(0)
    n = 600
    groups = [f"p{i // 3}" for i in range(n)]
    pairs = [(i, i) for i in range(n)]
    same = RZ.c2st(rng.normal(size=(n, 2)), rng.normal(size=(n, 2)), groups, pairs, n_scalar=2, n_boot=50)
    shifted = RZ.c2st(
        rng.normal(size=(n, 2)), rng.normal(size=(n, 2)) + 2, groups, pairs, n_scalar=2, n_boot=50
    )
    assert same["auc"] < 0.6 and shifted["auc"] > 0.9
    assert shifted["ci95"][0] <= shifted["auc"] <= shifted["ci95"][1]


def test_case_features(onto):
    class Knowledge:
        kb = {"diseases": {"OMIM:1": {"phenotypes": {"HP:0001250": {}}}}}

        def diseases(self, gene):
            return {"OMIM:1": 1.0}

        def term_probability(self, gene, term):
            return 0.5 if term in ("HP:0001250", "HP:0000707", "HP:0000118") else 0.0

    features = RZ.CaseFeatures(onto, Counter({"HP:0001250": 1}), 3, Knowledge())
    names = features.names()
    row = dict(zip(names, features("G", ["HP:0001250", "HP:0002069"]), strict=True))
    assert row["term_count"] == 2 and row["annotated_share"] == 0.5 and row["noise_share"] == 0.5
    assert row["system:HP:0000707"] == 1.0 and row["system:HP:0000478"] == 0.0
    assert row["mean_depth"] == pytest.approx(3.5)


def test_e0_difficulty_reports_the_gap_to_the_target():
    class Fake:
        name, genes = "fake", ("G", "H")

        def score(self, case):
            return Scored(np.array([0.9, 0.1]) if case.gene == "G" else np.array([0.9, 0.1]))

    cases = [RZ.SimCase("1", "G", ("HP:1",), None), RZ.SimCase("2", "H", ("HP:1",), None)]
    out = RZ.e0_difficulty(Fake(), cases, target=0.5)
    assert out["mrr_in_vocab"] == pytest.approx(0.75) and out["gap"] == pytest.approx(0.25)


def report(a, b, c, d, e):
    return {
        "g2a_panel": {"primary": {"mae": a}},
        "g2b_dev_rho": {"mean_rho": b},
        "g2c_terms_per_case": {"present": {"w1_vs_r1_train": c}},
        "g2d_c2st": {"auc": d},
        "g2e_e0": {"gap": e},
    }


def test_gate_requires_beating_every_baseline_and_the_absolute_caps():
    baselines = {"up": report(0.3, 0.4, 3.0, 0.95, 0.30), "v03": report(0.4, 0.1, 5.0, 0.99, 0.34)}
    table = RZ.gate(
        baselines,
        {"good": report(0.2, 0.5, 2.0, 0.70, 0.05), "near": report(0.2, 0.3, 2.0, 0.80, 0.20)},
    )
    assert table["candidates"]["good"]["all_pass"]
    near = table["candidates"]["near"]["pass"]
    assert near == {"a": True, "b": False, "c": True, "d": False, "e": False}
    assert "FAIL" in RZ.gate_markdown(table) and "baseline" in RZ.gate_markdown(table)


def test_r1_dev_budget_allows_three_candidate_versions():
    rows = [{"role": "candidate", "version": v} for v in ("0.4.0", "0.4.1", "0.5.0")]
    rows.append({"role": "baseline", "version": "—"})
    check_budget("0.4.1", False, rows)  # a version already counted may be re-read
    check_budget(None, True, rows)  # baselines are free
    with pytest.raises(LineageError):
        check_budget("0.6.0", False, rows)
