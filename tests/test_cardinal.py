import json

import pytest

from diagnostic_ar_training.knowledge import cardinal as CA
from diagnostic_ar_training.knowledge.recount import COLUMNS
from diagnostic_ar_training.ontology import Ontology

OBO = "http://purl.obolibrary.org/obo/HP_"
HP = {"0000001": [], "0000118": ["0000001"], "0001250": ["0000118"], "0000505": ["0000118"]}
P4 = """<?xml version="1.0"?><JDBOR><HPODisorderSetStatusList>
<HPODisorderSetStatus><Disorder><OrphaCode>10</OrphaCode><HPODisorderAssociationList>
<HPODisorderAssociation><HPO><HPOId>HP:0001250</HPOId></HPO>
<DiagnosticCriteria><Name>Diagnostic criterion</Name></DiagnosticCriteria></HPODisorderAssociation>
<HPODisorderAssociation><HPO><HPOId>HP:0000505</HPOId></HPO><DiagnosticCriteria/></HPODisorderAssociation>
</HPODisorderAssociationList></Disorder><Source>123[PMID]_ORPHA</Source></HPODisorderSetStatus>
<HPODisorderSetStatus><Disorder><OrphaCode>20</OrphaCode><HPODisorderAssociationList>
<HPODisorderAssociation><HPO><HPOId>HP:0000505</HPOId></HPO>
<DiagnosticCriteria><Name>Pathognomonic sign</Name></DiagnosticCriteria></HPODisorderAssociation>
</HPODisorderAssociationList></Disorder><Source>999[PMID]</Source></HPODisorderSetStatus>
</HPODisorderSetStatusList></JDBOR>"""


@pytest.fixture
def onto(tmp_path):
    nodes = [{"id": OBO + c, "lbl": c} for c in HP]
    edges = [{"sub": OBO + c, "pred": "is_a", "obj": OBO + p} for c, ps in HP.items() for p in ps]
    (tmp_path / "hp.json").write_text(json.dumps({"graphs": [{"nodes": nodes, "edges": edges}]}))
    return Ontology.from_json(tmp_path / "hp.json")


def hrow(disease, term, freq, ref="PMID:1", qualifier=""):
    values = [disease, "d", qualifier, term, ref, "PCS", "", freq, "", "", "P", "x"]
    return dict(zip(COLUMNS, values, strict=True))


def test_product4_flags_are_parsed_with_their_disorder_pmids(tmp_path):
    (tmp_path / "p4.xml").write_text(P4)
    assert CA.parse_product4(tmp_path / "p4.xml") == [
        ("ORPHA:10", "HP:0001250", "diagnostic_criterion", ["PMID:123"]),
        ("ORPHA:20", "HP:0000505", "pathognomonic", ["PMID:999"]),
    ]


def test_build_maps_to_omim_drops_heldout_disorders_and_adds_count_proxies(tmp_path, onto):
    (tmp_path / "p4.xml").write_text(P4)
    hpoa = [
        hrow("OMIM:5", "HP:0001250", "8/10"),  # 0.8 over 10: proxy
        hrow("OMIM:5", "HP:0000505", "9/9"),  # m < 10
        hrow("OMIM:6", "HP:0000505", "5/6", ref="R1-TRAIN:r1-v1"),
        hrow("OMIM:6", "HP:0000505", "4/4", ref="PMID:2"),  # pooled 9/10: proxy
        hrow("OMIM:7", "HP:0001250", "HP:0040281"),  # a category is not a count
        hrow("OMIM:8", "HP:0001250", "10/10", qualifier="NOT"),
    ]
    rows, stats = CA.build(
        CA.parse_product4(tmp_path / "p4.xml"),
        hpoa,
        onto,
        [("ORPHA:10", "OMIM:1")],
        {"PMID:999"},
        "p4@x",
        "rc",
    )
    assert rows == [
        ("OMIM:1", "HP:0001250", "diagnostic_criterion", "p4@x;ORPHA:10;PMID:123"),
        ("OMIM:5", "HP:0001250", "cardinal_proxy", "rc;PMID:1"),
        ("OMIM:6", "HP:0000505", "cardinal_proxy", "rc;PMID:2;R1-TRAIN:r1-v1"),
        ("ORPHA:10", "HP:0001250", "diagnostic_criterion", "p4@x;ORPHA:10;PMID:123"),
    ]
    assert stats["product4_dropped_cites_heldout_pmid"] == 1 and stats["rows_cardinal_proxy"] == 2
    assert CA.references(rows[2][3]) == {"PMID:2", "R1-TRAIN:r1-v1"}


def test_tsv_round_trip(tmp_path):
    rows = [("OMIM:1", "HP:0001250", "pathognomonic", "p4;ORPHA:1")]
    CA.write(tmp_path / "c.tsv", rows)
    assert CA.read(tmp_path / "c.tsv") == [dict(zip(CA.HEADER, rows[0], strict=True))]
