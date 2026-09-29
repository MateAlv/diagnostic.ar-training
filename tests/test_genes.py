import gzip
import json
import math

import pytest

from diagnostic_ar_training.knowledge import genes as G
from diagnostic_ar_training.ontology import Ontology

OBO = "http://purl.obolibrary.org/obo/HP_"
HP = {
    "0000001": [],
    "0000118": ["0000001"],
    "0001250": ["0000118"],
    "0000005": ["0000001"],
    "0000006": ["0000005"],
}

HGNC = "\n".join(
    [
        "hgnc_id\tsymbol\tname\tlocus_type\tstatus\tlocation\talias_symbol\tprev_symbol\tomim_id",
        "HGNC:1\tGENEA\tgene a\tgene with protein product\tApproved\t17q11.2\tALIASA\tOLDA\t100",
        "HGNC:2\tGENEX\tgene x\tgene with protein product\tApproved\tXp22.1\tSHARED\t\t200",
        "HGNC:3\tGENEY\tgene y\tgene with protein product\tApproved\t1p36\tSHARED\t\t",
        "HGNC:4\tGONE\tgone\tgene with protein product\tEntry Withdrawn\t2p1\t\t\t",
    ]
)
HPOA_COLUMNS = [
    "database_id", "disease_name", "qualifier", "hpo_id", "reference", "evidence",
    "onset", "frequency", "sex", "modifier", "aspect", "biocuration",
]  # fmt: skip


def hpoa(disease, term, aspect="P", ref="PMID:1", qualifier=""):
    return "\t".join([disease, "d", qualifier, term, ref, "PCS", "", "", "", "", aspect, "x"])


HPOA = [
    hpoa("OMIM:1", "HP:0001250"),
    hpoa("OMIM:1", "HP:0000006", aspect="I"),
    hpoa("OMIM:2", "HP:0001250"),
    hpoa("ORPHA:20", "HP:0001250"),
    hpoa("OMIM:3", "HP:0001250", ref="PMID:666"),  # only row of OMIM:3 is masked
    hpoa("OMIM:4", "HP:0001250"),
]
G2D = [
    "ncbi_gene_id\tgene_symbol\tassociation_type\tdisease_id\tsource",
    "N:1\tOLDA\tMENDELIAN\tOMIM:1\tx",  # previous symbol resolves to GENEA
    "N:1\tGENEA\tMENDELIAN\tOMIM:2\tx",
    "N:1\tGENEA\tPOLYGENIC\tOMIM:4\tx",
    "N:1\tGENEA\tMENDELIAN\tOMIM:3\tx",
    "N:2\tGENEX\tUNKNOWN\tORPHA:20\tx",
]
G2P = ["ncbi_gene_id\tgene_symbol\thpo_id\thpo_name\tfrequency\tdisease_id"]
P6 = """<?xml version="1.0"?><JDBOR><DisorderList>
<Disorder><OrphaCode>10</OrphaCode><DisorderGeneAssociationList>
<DisorderGeneAssociation><Gene><Symbol>GENEA</Symbol></Gene>
<DisorderGeneAssociationType><Name>Candidate gene tested in</Name></DisorderGeneAssociationType>
<DisorderGeneAssociationStatus><Name>Assessed</Name></DisorderGeneAssociationStatus></DisorderGeneAssociation>
</DisorderGeneAssociationList></Disorder>
<Disorder><OrphaCode>20</OrphaCode><DisorderGeneAssociationList>
<DisorderGeneAssociation><Gene><Symbol>GENEX</Symbol></Gene>
<DisorderGeneAssociationType><Name>Disease-causing somatic mutation(s) in</Name></DisorderGeneAssociationType>
<DisorderGeneAssociationStatus><Name>Assessed</Name></DisorderGeneAssociationStatus></DisorderGeneAssociation>
</DisorderGeneAssociationList></Disorder></DisorderList></JDBOR>"""
P1 = """<?xml version="1.0"?><JDBOR><DisorderList>
<Disorder><OrphaCode>10</OrphaCode><ExternalReferenceList>
<ExternalReference><Source>OMIM</Source><Reference>2</Reference>
<DisorderMappingRelation><Name>E (Exact mapping: the two concepts are equivalent)</Name></DisorderMappingRelation>
<DisorderMappingValidationStatus><Name>Validated</Name></DisorderMappingValidationStatus></ExternalReference>
<ExternalReference><Source>OMIM</Source><Reference>4</Reference>
<DisorderMappingRelation><Name>BTNT (ORPHAcode is broader)</Name></DisorderMappingRelation>
<DisorderMappingValidationStatus><Name>Validated</Name></DisorderMappingValidationStatus></ExternalReference>
</ExternalReferenceList></Disorder></DisorderList></JDBOR>"""  # noqa: E501
PREV = """<?xml version="1.0"?><JDBOR><DisorderList><Disorder><OrphaCode>10</OrphaCode><PrevalenceList>
<Prevalence><PrevalenceType><Name>Point prevalence</Name></PrevalenceType>
<PrevalenceClass><Name>1-9 / 100 000</Name></PrevalenceClass><PrevalenceGeographic><Name>Europe</Name></PrevalenceGeographic></Prevalence>
<Prevalence><PrevalenceType><Name>Point prevalence</Name></PrevalenceType>
<PrevalenceClass><Name>1-9 / 1 000 000</Name></PrevalenceClass><PrevalenceGeographic><Name>Worldwide</Name></PrevalenceGeographic></Prevalence>
</PrevalenceList></Disorder></DisorderList></JDBOR>"""  # noqa: E501
CLINGEN = "\n".join(
    [
        '"CLINGEN GENE DISEASE VALIDITY CURATIONS"',
        '"GENE SYMBOL","GENE ID (HGNC)","DISEASE LABEL","DISEASE ID (MONDO)","MOI","SOP","CLASSIFICATION"',
        '"+++","+++","+++","+++","+++","+++","+++"',
        '"GENEA","HGNC:1","d1","MONDO:1","AR","SOP10","Limited"',
        '"GENEA","HGNC:1","dz","MONDO:9","AD","SOP10","Definitive"',
    ]
)
MONDO = """[Term]
id: MONDO:1
xref: OMIM:1 {source="MONDO:equivalentTo"}
xref: DOID:5 {source="MONDO:equivalentTo"}

[Term]
id: MONDO:2
is_obsolete: true
xref: OMIM:4 {source="MONDO:equivalentTo"}
"""
CLINVAR_HEADER = "#AlleleID\tGeneSymbol\tClinSigSimple\tPhenotypeIDS\tOriginSimple\tAssembly"
CLINVAR = [
    "1\tGENEA\t1\tMONDO:MONDO:1,OMIM:1\tgermline\tGRCh38",
    "2\tGENEA\t1\tOMIM:1|Orphanet:ORPHA10\tgermline\tGRCh38",
    "2\tGENEA\t1\tOMIM:1\tgermline\tGRCh37",  # other assembly: not counted twice
    "3\tGENEA\t0\tOMIM:2\tgermline\tGRCh38",  # not P/LP
    "4\tGENEA;GENEX\t1\tOMIM:2\tgermline\tGRCh38",  # multi-gene
    "5\tGENEA\t1\tOrphanet:10\tsomatic\tGRCh38",  # somatic
    "6\tGENEA\t1\tOMIM:2\tgermline\tGRCh38",
]


@pytest.fixture
def built(tmp_path):
    nodes = [{"id": OBO + c, "lbl": c} for c in HP]
    edges = [{"sub": OBO + c, "pred": "is_a", "obj": OBO + p} for c, ps in HP.items() for p in ps]
    (tmp_path / "hp.json").write_text(json.dumps({"graphs": [{"nodes": nodes, "edges": edges}]}))
    files = {
        "hgnc": HGNC,
        "hpoa": "#version: t\n" + "\t".join(HPOA_COLUMNS) + "\n" + "\n".join(HPOA),
        "g2d": "\n".join(G2D),
        "g2p": "\n".join(G2P),
        "p6": P6,
        "p1": P1,
        "prev": PREV,
        "clingen": CLINGEN,
        "mondo": MONDO,
    }
    for name, text in files.items():
        (tmp_path / name).write_text(text + "\n")
    with gzip.open(tmp_path / "clinvar.gz", "wt") as handle:
        handle.write(CLINVAR_HEADER + "\n" + "\n".join(CLINVAR) + "\n")
    p = lambda n: tmp_path / n  # noqa: E731
    return G.build(
        Ontology.from_json(tmp_path / "hp.json"),
        p("hgnc"), p("hpoa"), p("g2d"), p("g2p"), p("p6"), p("p1"), p("prev"), p("clingen"), p("mondo"),
        p("clinvar.gz"), {"PMID:666"}, ["-", "GENEA", "OLDA", "NOPE"],
    )  # fmt: skip


def entity(out, symbol, primary):
    return next(e for e in out["genes"][symbol]["entities"] if e["entity"] == primary)


def test_chromosome_parsing():
    assert [G.chromosome(x) for x in ("17q11.2", "Xp22.1", "Yq11", "mitochondria", "X and Y", "?")] == [
        "17", "X", "Y", "MT", "XY", "unknown",
    ]  # fmt: skip


def test_symbols_resolve_through_previous_symbols_but_not_ambiguous_aliases(built):
    out, stats = built
    assert out["vocabulary"] == {"GENEA": "GENEA", "OLDA": "GENEA", "NOPE": None}
    assert out["genes"]["GENEA"]["hgnc_id"] == "HGNC:1" and out["genes"]["GENEX"]["chromosome"] == "X"


def test_exact_alignments_merge_entities_and_broader_ones_do_not(built):
    out, _ = built
    e = entity(out, "GENEA", "OMIM:2")
    assert e["ids"] == ["OMIM:2", "ORPHA:10"]
    assert all("OMIM:4" not in x["ids"] or x["ids"] == ["OMIM:4"] for x in out["genes"]["GENEA"]["entities"])


def test_validity_prefers_clingen_then_orphanet_then_hpo(built):
    out, _ = built
    assert entity(out, "GENEA", "OMIM:1")["validity"] == pytest.approx(0.3)  # ClinGen Limited via MONDO:1
    assert entity(out, "GENEA", "OMIM:1")["inheritance"] == ["HP:0000007"]  # ClinGen AR beats HPOA AD
    assert entity(out, "GENEA", "OMIM:2")["validity"] == pytest.approx(0.1)  # Orphanet candidate gene
    assert entity(out, "GENEX", "ORPHA:20")["validity"] == 0.0  # somatic only


def test_clinvar_counts_distinct_germline_grch38_single_gene_alleles(built):
    out, _ = built
    assert entity(out, "GENEA", "OMIM:1")["clinvar_plp_alleles"] == 2
    assert entity(out, "GENEA", "OMIM:2")["clinvar_plp_alleles"] == 2  # allele 2 via ORPHA:10, allele 6


def test_weights_normalise_over_simulable_entities_only(built):
    out, stats = built
    a = {e["entity"]: e for e in out["genes"]["GENEA"]["entities"]}
    assert "OMIM:4" not in a  # polygenic link excluded
    assert a["OMIM:3"]["profile_ids"] == [] and a["OMIM:3"]["sim_weight"] == 0.0  # masked away
    w1, w2 = 0.3 * math.sqrt(3), 0.1 * math.sqrt(3)
    assert a["OMIM:1"]["sim_weight"] == pytest.approx(w1 / (w1 + w2), abs=1e-6)
    assert sum(e["sim_weight"] for e in a.values()) == pytest.approx(1.0, abs=1e-5)
    assert out["genes"]["GENEX"]["simulable_entities"] == 0


def test_prevalence_prefers_worldwide_point_prevalence(built):
    out, _ = built
    assert entity(out, "GENEA", "OMIM:2")["prevalence"] == 5e-6


def test_obsolete_mondo_terms_are_ignored(tmp_path):
    (tmp_path / "m").write_text(MONDO)
    assert G.parse_mondo(tmp_path / "m") == {"MONDO:1": {"OMIM:1"}}
