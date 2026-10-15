"""P4-AGE hard age rule (`v4.agerule`): it only lowers genes, unknown age and onset are a no-op, a gene with
any disease lacking an onset class is never blocked, and the knowledge reads only its declared sources. No
data needed."""

import json

import numpy as np
import pytest

from diagnostic_ar_training.v4 import agerule

HEADER = (
    "#description: fake\n"
    "database_id\tdisease_name\tqualifier\thpo_id\treference\tevidence\tonset\tfrequency\tsex\tmodifier\taspect"
    "\tbiocuration\n"
)
ADULT, MIDDLE, LATE, CHILD, CONGENITAL = "HP:0003581", "HP:0003596", "HP:0003584", "HP:0011463", "HP:0003577"
PERIMENOPAUSAL, PROGRESSIVE = "HP:6000314", "HP:0003676"
# disease -> rows of (aspect, term, qualifier, onset column, frequency)
DISEASES = {
    "OMIM:1": [("C", LATE, "", "", ""), ("P", "HP:0001250", "", "", "")],
    "OMIM:2": [("C", MIDDLE, "", "", ""), ("C", PROGRESSIVE, "", "", "")],
    "OMIM:3": [("C", ADULT, "", "", ""), ("P", "HP:0001250", "", CHILD, "")],
    "OMIM:4": [
        ("C", ADULT, "", "", ""),
        ("P", "HP:0001250", "NOT", CONGENITAL, ""),
        ("P", "HP:0001251", "", CHILD, "0/5"),
    ],
    "OMIM:5": [("C", PROGRESSIVE, "", "", ""), ("P", "HP:0001250", "", MIDDLE, "")],
    "OMIM:6": [("C", PERIMENOPAUSAL, "", "", "")],
    "ORPHA:7": [("C", LATE, "", "", "")],
    "ORPHA:8": [("P", "HP:0001250", "", "", "")],
}
GENES = {
    "LATE1": ["OMIM:1", "ORPHA:7"],
    "MID": ["OMIM:1", "OMIM:2"],
    "ROWS": ["OMIM:3"],
    "NOTROWS": ["OMIM:4"],
    "COURSE": ["OMIM:5"],
    "UNKNOWN": ["OMIM:6"],
    "PARTIAL": ["OMIM:1", "ORPHA:8"],
}
ONSET_EDGES = [(t, "HP:0003674") for t in ("HP:0003581", "HP:0410280", "HP:0003577", PERIMENOPAUSAL)] + [
    (MIDDLE, ADULT),
    (LATE, ADULT),
    (CHILD, "HP:0410280"),
    ("HP:0003674", "HP:0000001"),
]
EDGES = [*ONSET_EDGES, *((t, "HP:0000001") for t in (PROGRESSIVE, "HP:0001250", "HP:0001251"))]


def hpoa() -> str:
    rows = [
        f"{d}\tDisease {d}\t{q}\t{term}\tPMID:1\tPCS\t{onset}\t{freq}\t\t\t{aspect}\tx"
        for d, terms in DISEASES.items()
        for aspect, term, q, onset, freq in terms
    ]
    return HEADER + "\n".join(rows) + "\n"


def g2p() -> str:
    rows = [f"{i}\t{g}\tHP:0000001\tx\t-\t{d}" for i, (g, ds) in enumerate(GENES.items()) for d in ds]
    rows.append("99\tNODISEASE\tHP:0000001\tx\t-\t")
    return "ncbi_gene_id\tgene_symbol\thpo_id\thpo_name\tfrequency\tdisease_id\n" + "\n".join(rows) + "\n"


def ontology_json() -> str:
    obo = "http://purl.obolibrary.org/obo/"
    terms = {t.replace(":", "_") for edge in EDGES for t in edge}
    nodes = [{"id": f"{obo}{t}", "lbl": t} for t in sorted(terms)]
    edges = [
        {"sub": f"{obo}{a.replace(':', '_')}", "pred": "is_a", "obj": f"{obo}{b.replace(':', '_')}"}
        for a, b in EDGES
    ]
    return json.dumps({"graphs": [{"nodes": nodes, "edges": edges}]})


@pytest.fixture
def opened(tmp_path, monkeypatch):
    files = {
        "hpo_annotations_2025_03_03": ("phenotype.hpoa", hpoa()),
        "hpo_ontology_2025_03_03": ("hp.json", ontology_json()),
        "e0_genes_to_phenotype": ("genes_to_phenotype.txt", g2p()),
    }
    seen = []

    def open_source(name, purpose):
        seen.append(name)
        if name not in files:
            raise AssertionError(f"the age knowledge read {name}")
        path = tmp_path / files[name][0]
        path.write_text(files[name][1])
        return path

    monkeypatch.setattr(agerule, "open_source", open_source)
    return seen


@pytest.fixture
def built(opened):
    return agerule.kb_from_sources([*GENES, "NODISEASE"])


def test_kb_reads_only_the_declared_sources(opened, built):
    _, _, read = built
    assert sorted(opened) == sorted(agerule.KB_SOURCES.values()) == sorted(read)
    assert not {"orphanet_ages", "orphanet_ages_2026_06", "hgnc", "hpo_annotations"} & set(opened)


def test_bounds_need_every_disease_and_rows_only_lower(built):
    kb, stats, _ = built
    assert agerule.bounds(kb) == {"LATE1": 60, "MID": 40, "ROWS": 1, "NOTROWS": 16}
    assert agerule.bounds(kb, rows=False) == {"LATE1": 60, "MID": 40, "ROWS": 16, "NOTROWS": 16}
    genes = kb["genes"]
    assert genes["COURSE"]["why"] == "no_onset_class"
    assert genes["UNKNOWN"]["why"] == "unknown_onset_term"
    assert genes["PARTIAL"]["earliest_years"] is None and genes["PARTIAL"]["why"] == "no_onset_class"
    assert genes["MID"]["diseases"]["OMIM:2"]["classes"] == [MIDDLE]
    assert "NODISEASE" not in genes
    assert stats["genes_with_bound"] == 4 and stats["genes_without_diseases"] == 1
    assert stats["genes_bound_lowered_by_rows"] == 1


def test_a_gene_with_an_unannotated_disease_is_never_blocked(built):
    kb, _, _ = built
    genes = list(GENES)
    rule = agerule.AgeRule(agerule.bounds(kb), genes, margin_years=0, min_earliest_years=0)
    blocked = rule.blocked(0.0)
    assert dict(zip(genes, blocked.tolist(), strict=True)) == {
        "LATE1": True,
        "MID": True,
        "ROWS": True,
        "NOTROWS": True,
        "COURSE": False,
        "UNKNOWN": False,
        "PARTIAL": False,
    }


@pytest.mark.parametrize(
    ("kwargs", "latest"),
    [
        ({}, None),
        ({"onset_years": 30.0}, 30.0),
        ({"onset_years": 30.0, "age_years": 12.0}, 12.0),
        ({"onset_term": CHILD, "age_years": 40.0}, 5.0),
        ({"onset_term": ADULT, "age_years": 40.0}, 40.0),
        ({"onset_term": ADULT}, None),
        ({"onset_term": "HP:0000001"}, None),
        ({"onset_years": -0.2}, 0.0),
        ({"age_years": 50.0, "feature_onsets": (("HP:1", 33.0, None), ("HP:2", None, MIDDLE))}, 33.0),
        ({"age_years": 50.0, "feature_onsets": (("HP:2", None, CONGENITAL),)}, 0.0),
    ],
)
def test_latest_onset(kwargs, latest):
    assert agerule.latest_onset(**kwargs) == latest


def test_latest_onset_without_classes_reads_years_only():
    assert agerule.latest_onset(onset_term=CHILD, age_years=40.0, classes=False) == 40.0
    assert agerule.latest_onset(feature_onsets=(("HP:1", None, CONGENITAL),), classes=False) is None


def scores_and_rule(**kw):
    genes = ("A", "LATE", "B", "MID", "YOUNG", "C")
    bounds = {"LATE": 60.0, "MID": 40.0, "YOUNG": 16.0}
    return np.array([3.0, 5.0, 1.0, 4.0, 2.0, 1.0], dtype=np.float32), agerule.AgeRule(bounds, genes, **kw)


def test_rule_only_lowers_genes_that_cannot_have_started():
    scores, rule = scores_and_rule(margin_years=10, min_earliest_years=0)
    blocked = rule.blocked(25.0)
    assert blocked.tolist() == [False, True, False, True, False, False]
    out = rule.apply(scores, 25.0)
    np.testing.assert_array_equal(out[~blocked], scores[~blocked])
    assert out[blocked].max() < out[~blocked].min()
    assert out[1] > out[3]
    assert out.dtype == np.float64
    before = [int(np.sum(scores >= scores[i])) for i in np.flatnonzero(~blocked)]
    after = [int(np.sum(out >= out[i])) for i in np.flatnonzero(~blocked)]
    assert all(a <= b for a, b in zip(after, before, strict=True))
    assert not rule.blocked(30.0)[3] and rule.blocked(29.9)[3]


def test_min_earliest_limits_the_blockable_genes():
    _, rule = scores_and_rule(margin_years=0, min_earliest_years=40)
    assert rule.blocked(0.0).tolist() == [False, True, False, True, False, False]
    _, rule = scores_and_rule(margin_years=0, min_earliest_years=60)
    assert rule.blocked(0.0).tolist() == [False, True, False, False, False, False]


@pytest.mark.parametrize("latest", [None, float("nan"), float("inf")])
def test_unknown_age_is_a_no_op(latest):
    scores, rule = scores_and_rule()
    assert not rule.blocked(latest).any()
    np.testing.assert_array_equal(rule.apply(scores, latest), scores)


def test_case_latest_onset_reads_every_case_field():
    from diagnostic_ar_training.cohorts.schema import Case

    case = Case(
        case_id="x",
        cohort="c",
        gene="G",
        present=("HP:1",),
        age_years=20.0,
        onset_term=ADULT,
        feature_onsets=(("HP:1", None, CHILD),),
    )
    assert agerule.case_latest_onset(case) == 5.0
    assert agerule.case_latest_onset(case, classes=False) == 20.0
    unknown = case.model_copy(update={"age_years": None, "feature_onsets": ()})
    assert agerule.case_latest_onset(unknown) is None


def test_the_chosen_variant_blocks_late_onset_genes_before_thirty_only():
    _, rule = scores_and_rule()
    assert (rule.margin_years, rule.min_earliest_years) == (30.0, 60.0)
    assert rule.blocked(29.9).tolist() == [False, True, False, False, False, False]
    assert not rule.blocked(30.0).any()
