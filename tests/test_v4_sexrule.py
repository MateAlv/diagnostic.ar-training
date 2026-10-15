"""P4-SEX hard sex rule (`v4.sexrule`): it only lowers impossible genes, unknown sex is a no-op; the knowledge
drops ambiguous, DSD and compound-name genes, never blocks X-linked recessive, and reads only its declared
sources. No data needed."""

import json

import numpy as np
import pytest

from diagnostic_ar_training.cohorts.schema import Sex
from diagnostic_ar_training.v4 import sexrule

HEADER = (
    "#description: fake\n"
    "database_id\tdisease_name\tqualifier\thpo_id\treference\tevidence\tonset\tfrequency\tsex\tmodifier\taspect"
    "\tbiocuration\n"
)
DISEASES = {
    "OMIM:1": ("Spermatogenic failure 1", [("P", "HP:0000027")]),
    "OMIM:2": ("Premature ovarian failure 2", [("P", "HP:0000137")]),
    "OMIM:3": (
        "Leukoencephalopathy with vanishing white matter 3, with or without ovarian failure",
        [("P", "HP:0001250"), ("P", "HP:0000137")],
    ),
    "OMIM:4": ("Muscular dystrophy, X-linked", [("I", "HP:0001419"), ("P", "HP:0001250")]),
    "OMIM:5": ("46,XY sex reversal 5", [("P", "HP:0000062")]),
    "OMIM:6": ("Azoospermia 6", [("P", "HP:0000027"), ("P", "HP:0000137")]),
    "OMIM:7": ("Some syndrome 7", [("P", "HP:0000027"), ("P", "HP:0000078")]),
    "OMIM:8": ("Deafness, Y-linked 8", [("I", "HP:0001450"), ("P", "HP:0001250")]),
    "OMIM:9": ("Some syndrome 9", [("P", "HP:0000062"), ("P", "HP:0001250")]),
}
GENES = {
    "MALE1": ["OMIM:1"],
    "FEMALE1": ["OMIM:2"],
    "VWM": ["OMIM:3"],
    "XLR": ["OMIM:4"],
    "DSD": ["OMIM:1", "OMIM:5"],
    "DSDPHEN": ["OMIM:1", "OMIM:9"],
    "AMB": ["OMIM:1", "OMIM:2"],
    "CONTRA": ["OMIM:6"],
    "PHEN": ["OMIM:7"],
    "YINH": ["OMIM:8"],
    "PART": ["OMIM:1", "OMIM:4"],
    "YGENE": [],
    "PAR": ["OMIM:4"],
}
LOCATIONS = {"YGENE": "Yq11.223", "PAR": "Xp22.33 and Yp11.32", "YINH": "Yp11.2", "XLR": "Xp21.2"}
EDGES = (
    ("HP_0000078", "HP_0000001"),
    ("HP_0010461", "HP_0000078"),
    ("HP_0000027", "HP_0010461"),
    ("HP_0010460", "HP_0000078"),
    ("HP_0000137", "HP_0010460"),
    ("HP_0000062", "HP_0000078"),
    ("HP_0001250", "HP_0000001"),
)


def hpoa() -> str:
    rows = [
        f"{d}\t{name}\t\t{term}\tPMID:1\tPCS\t\t\t\t\t{aspect}\tx"
        for d, (name, terms) in DISEASES.items()
        for aspect, term in terms
    ]
    return HEADER + "\n".join(rows) + "\n"


def g2p() -> str:
    rows = [f"{i}\t{g}\tHP:0000001\tx\t-\t{d}" for i, (g, ds) in enumerate(GENES.items()) for d in ds]
    rows.append("99\tYGENE\tHP:0000001\tx\t-\t")
    return "ncbi_gene_id\tgene_symbol\thpo_id\thpo_name\tfrequency\tdisease_id\n" + "\n".join(rows) + "\n"


def hgnc() -> str:
    rows = [f"{g}\t{LOCATIONS.get(g, '1p36')}\t\t" for g in GENES]
    return "symbol\tlocation\tprev_symbol\talias_symbol\n" + "\n".join(rows) + "\n"


def ontology_json() -> str:
    obo = "http://purl.obolibrary.org/obo/"
    terms = {t for edge in EDGES for t in edge}
    nodes = [{"id": f"{obo}{t}", "lbl": t} for t in sorted(terms)]
    edges = [{"sub": f"{obo}{a}", "pred": "is_a", "obj": f"{obo}{b}"} for a, b in EDGES]
    return json.dumps({"graphs": [{"nodes": nodes, "edges": edges}]})


@pytest.fixture
def opened(tmp_path, monkeypatch):
    files = {
        "hpo_annotations_2025_03_03": ("phenotype.hpoa", hpoa()),
        "hpo_ontology_2025_03_03": ("hp.json", ontology_json()),
        "e0_genes_to_phenotype": ("genes_to_phenotype.txt", g2p()),
        "hgnc": ("hgnc_complete_set.txt", hgnc()),
    }
    seen = []

    def open_source(name, purpose):
        seen.append(name)
        if name not in files:
            raise AssertionError(f"the sex knowledge read {name}")
        path = tmp_path / files[name][0]
        path.write_text(files[name][1])
        return path

    monkeypatch.setattr(sexrule, "open_source", open_source)
    return seen


@pytest.fixture
def built(opened):
    return sexrule.kb_from_sources([*GENES, "NOTHING"])


def test_kb_reads_only_the_declared_sources(opened, built):
    _, _, read = built
    assert sorted(opened) == sorted(sexrule.KB_SOURCES.values()) == sorted(read)
    assert "hgnc" in opened and not {"orphanet_ages", "hpo_annotations", "hpo_ontology"} & set(opened)


def test_limits_reasons_and_exclusions(built):
    kb, stats, _ = built
    genes, excluded = kb["genes"], kb["excluded"]
    assert genes["MALE1"]["limit"] == "male" and genes["MALE1"]["reasons"] == ["names", "phenotypes"]
    assert genes["FEMALE1"]["limit"] == "female" and genes["FEMALE1"]["reasons"] == ["names", "phenotypes"]
    assert genes["PHEN"] == {
        "limit": "male",
        "reasons": ["phenotypes"],
        "location": "1p36",
        "diseases": {"OMIM:7": ["male:phenotypes", "male_terms"]},
    }
    assert genes["YINH"]["reasons"] == ["y_chromosome", "y_linked_inheritance"]
    assert genes["YGENE"]["limit"] == "male" and genes["YGENE"]["reasons"] == ["y_chromosome"]
    assert excluded["AMB"]["why"] == "ambiguous"
    assert excluded["DSD"]["why"] == excluded["DSDPHEN"]["why"] == "dsd"
    assert excluded["CONTRA"]["why"] == "contradicted"
    assert excluded["PART"]["why"] == "partial"
    assert excluded["VWM"]["why"] == "compound_name"
    assert {"XLR", "PAR", "NOTHING"}.isdisjoint(genes) and {"XLR", "PAR", "NOTHING"}.isdisjoint(excluded)
    assert stats["male_limited"] == 4 and stats["female_limited"] == 1 and stats["genes"] == len(GENES) + 1
    assert sexrule.limits(kb) == {"MALE1": "male", "FEMALE1": "female", "PHEN": "male", "YINH": "male"} | {
        "YGENE": "male"
    }


@pytest.mark.parametrize(
    ("name", "sex"),
    [
        ("Spermatogenic failure, X-linked, 3", "male"),
        ("Male infertility with large-headed, multiflagellar, polyploid spermatozoa", "male"),
        ("Male infertility with azoospermia or oligozoospermia due to single gene mutation", "male"),
        ("Persistent mullerian duct syndrome, types I and II", "male"),
        ("Oocyte/zygote/embryo maturation arrest 14", "female"),
        ("Preeclampsia/eclampsia 4", "female"),
        ("Female infertility due to oocyte meiotic arrest", "female"),
        ("Deafness, autosomal recessive 32, with or without immotile sperm", None),
        ("Heterotaxy, visceral, 9, autosomal, with male infertility", None),
        ("Azoospermia, obstructive, with nephrolithiasis", None),
        ("Muscular dystrophy, congenital hearing loss, and ovarian insufficiency syndrome", None),
        ("X-linked microcephaly-growth retardation-prognathism-cryptorchidism syndrome", None),
        ("Prostate cancer/brain cancer susceptibility", None),
    ],
)
def test_names_limit_only_when_the_whole_name_is_sex_limited(name, sex):
    found = [s for s, pattern in sexrule.NAMES.items() if sexrule.limited_name(name, pattern)]
    assert found == ([sex] if sex else [])


def test_x_linked_recessive_is_not_evidence():
    ann = sexrule.safe_knowledge.Annotations()
    ann.names["OMIM:4"] = "Muscular dystrophy, X-linked"
    ann.inheritance["OMIM:4"] = {"HP:0001419"}
    classify = sexrule.term_classifier(lambda t: ())
    evidence = {"OMIM:4": sexrule.disease_evidence("OMIM:4", ann, classify)}
    assert sexrule.gene_limit(evidence, "Xp21.2") == (None, [], None)


def scores_and_rule():
    genes = ("A", "M1", "B", "F1", "M2", "C")
    rule = sexrule.SexRule({"M1": "male", "M2": "male", "F1": "female"}, genes)
    return np.array([3.0, 5.0, 1.0, 4.0, 2.0, 1.0], dtype=np.float32), rule


def test_rule_only_lowers_genes_impossible_for_the_sex():
    scores, rule = scores_and_rule()
    out = rule.apply(scores, Sex.FEMALE)
    blocked = rule.blocked("female")
    assert blocked.tolist() == [False, True, False, False, True, False]
    np.testing.assert_array_equal(out[~blocked], scores[~blocked])
    assert out[blocked].max() < out[~blocked].min()
    assert out[1] > out[4]
    assert out.dtype == np.float64
    male = rule.apply(scores, "male")
    assert male[3] < male[[0, 1, 2, 4, 5]].min() and np.array_equal(
        male[[0, 1, 2, 4, 5]], scores[[0, 1, 2, 4, 5]]
    )
    for s, new in ((Sex.FEMALE, out), (Sex.MALE, male)):
        kept = ~rule.blocked(s)
        before = [int(np.sum(scores > scores[i]) + np.sum(scores == scores[i])) for i in np.flatnonzero(kept)]
        after = [int(np.sum(new > new[i]) + np.sum(new == new[i])) for i in np.flatnonzero(kept)]
        assert all(a <= b for a, b in zip(after, before, strict=True))


@pytest.mark.parametrize("sex", [Sex.UNKNOWN, None, "unknown", "other", ""])
def test_unknown_sex_is_a_no_op(sex):
    scores, rule = scores_and_rule()
    assert not rule.blocked(sex).any()
    np.testing.assert_array_equal(rule.apply(scores, sex), scores)


def test_block_keeps_scores_when_nothing_or_everything_is_blocked():
    s = np.array([1.0, 2.0, 2.0])
    np.testing.assert_array_equal(sexrule.block(s, np.zeros(3, bool)), s)
    np.testing.assert_array_equal(sexrule.block(s, np.ones(3, bool)), s)
    out = sexrule.block(s, np.array([False, True, False]))
    assert out[1] < out[0] < out[2]


def test_limits_reads_the_addon_knowledge_sex_list():
    kb = {"schema": "ft-kb/2", "safe": {"genes": {"A": {"sex": {"limit": "male"}}, "B": {"onset": {}}}}}
    assert sexrule.limits(kb) == {"A": "male"}
