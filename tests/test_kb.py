import json

import pytest

from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.rerank import kb

OBO = "http://purl.obolibrary.org/obo/HP_"
TERMS = {
    "0000001": ("All", []),
    "0000118": ("Phenotypic abnormality", ["0000001"]),
    "0000707": ("Nervous system", ["0000118"]),
    "0001250": ("Seizure", ["0000707"]),
    "0002373": ("Febrile seizure", ["0001250"]),
    "0000028": ("Cryptorchidism", ["0000118"]),
    "0003674": ("Onset", ["0000001"]),
    "0003577": ("Congenital onset", ["0003674"]),
    "0011463": ("Childhood onset", ["0003674"]),
    "0003581": ("Adult onset", ["0003674"]),
    "0000005": ("Mode of inheritance", ["0000001"]),
    "0001417": ("X-linked", ["0000005"]),
    "0001419": ("X-linked recessive", ["0001417"]),
    "0009999": ("Obsolete seizure", []),
}


def hp_json():
    nodes = []
    for code, (label, _) in TERMS.items():
        node = {"id": OBO + code, "lbl": label, "meta": {"basicPropertyValues": []}}
        if code == "0001250":
            node["meta"]["basicPropertyValues"].append(
                {"pred": "http://www.geneontology.org/formats/oboInOwl#hasAlternativeId", "val": "HP:0007000"}
            )
        if code == "0009999":
            node["meta"]["deprecated"] = True
            node["meta"]["basicPropertyValues"].append(
                {"pred": "http://purl.obolibrary.org/obo/IAO_0100001", "val": "HP:0001250"}
            )
        nodes.append(node)
    edges = [{"sub": OBO + c, "pred": "is_a", "obj": OBO + p} for c, (_, ps) in TERMS.items() for p in ps]
    return {"graphs": [{"nodes": nodes, "edges": edges}]}


HPOA_COLUMNS = [
    "database_id", "disease_name", "qualifier", "hpo_id", "reference", "evidence",
    "onset", "frequency", "sex", "modifier", "aspect", "biocuration",
]  # fmt: skip
HEADER = "\t".join(HPOA_COLUMNS)


def hpoa_row(disease, term, ref="PMID:1", qualifier="", onset="", freq="", sex="", aspect="P"):
    return "\t".join(
        [disease, f"name {disease}", qualifier, term, ref, "PCS", onset, freq, sex, "", aspect, "x"]
    )


ROWS = [
    hpoa_row("OMIM:1", "HP:0001250", freq="HP:0040281", onset="HP:0011463"),
    hpoa_row("OMIM:1", "HP:0001250", ref="PMID:2", freq="1/2"),  # merged with the row above
    hpoa_row("OMIM:1", "HP:0007000"),  # alternative id of HP:0001250
    hpoa_row("OMIM:1", "HP:0002373", qualifier="NOT"),
    hpoa_row("OMIM:1", "HP:0000028", sex="MALE", freq="HP:0040283"),
    hpoa_row("OMIM:1", "HP:0003577", aspect="C"),
    hpoa_row("OMIM:1", "HP:0001419", aspect="I"),
    hpoa_row("OMIM:2", "HP:0001250", ref="PMID:666;OMIM:2"),  # cites a held-out PMID
    hpoa_row("OMIM:2", "HP:0000028"),
    hpoa_row("ORPHA:3", "HP:0009999", freq="HP:0040285"),  # obsolete -> replaced; Excluded -> negated
    hpoa_row("ORPHA:3", "HP:0000028", freq=""),
    hpoa_row("OMIM:4", "HP:0001250"),
    hpoa_row("OMIM:4", "HP:0001250", qualifier="NOT", ref="PMID:9"),  # contradicts a positive
]
G2D = [
    "ncbi_gene_id\tgene_symbol\tassociation_type\tdisease_id\tsource",
    "NCBIGene:1\tGENEA\tMENDELIAN\tOMIM:1\tx",
    "NCBIGene:2\tGENEB\tPOLYGENIC\tOMIM:2\tx",
    "NCBIGene:3\tGENEC\tUNKNOWN\tORPHA:3\tx",
    "NCBIGene:4\t-\tMENDELIAN\tOMIM:4\tx",
]
G2P = [
    "ncbi_gene_id\tgene_symbol\thpo_id\thpo_name\tfrequency\tdisease_id",
    "NCBIGene:2\tGENEB\tHP:0000028\tx\t\tOMIM:2",
    "NCBIGene:5\tGENED\tHP:0001250\tx\t\tOMIM:4",
]
ORPHANET = """<?xml version="1.0"?><JDBOR><DisorderList count="2">
<Disorder id="1"><OrphaCode>3</OrphaCode><AverageAgeOfOnsetList>
<AverageAgeOfOnset><Name lang="en">Adult</Name></AverageAgeOfOnset>
<AverageAgeOfOnset><Name lang="en">All ages</Name></AverageAgeOfOnset></AverageAgeOfOnsetList></Disorder>
<Disorder id="2"><OrphaCode>1</OrphaCode><AverageAgeOfOnsetList>
<AverageAgeOfOnset><Name lang="en">Infancy</Name></AverageAgeOfOnset></AverageAgeOfOnsetList></Disorder>
</DisorderList></JDBOR>"""


@pytest.fixture
def built(tmp_path):
    (tmp_path / "hp.json").write_text(json.dumps(hp_json()))
    (tmp_path / "phenotype.hpoa").write_text("#version: test\n" + HEADER + "\n" + "\n".join(ROWS) + "\n")
    (tmp_path / "g2d.txt").write_text("\n".join(G2D) + "\n")
    (tmp_path / "g2p.txt").write_text("\n".join(G2P) + "\n")
    (tmp_path / "ages.xml").write_text(ORPHANET)
    onto = Ontology.from_json(tmp_path / "hp.json")
    args = [tmp_path / n for n in ("phenotype.hpoa", "g2d.txt", "g2p.txt", "ages.xml")]
    return onto, args, kb.build(onto, *args, masked_pmids={"PMID:666"})


def test_ontology_resolves_alternative_and_obsolete_ids(built):
    onto, _, _ = built
    assert onto.resolve("HP:0007000") == "HP:0001250"
    assert onto.resolve("HP:0009999") == "HP:0001250"
    assert onto.resolve("HP:1234567") is None
    assert onto.ancestors("HP:0002373") >= {"HP:0001250", "HP:0000707", "HP:0000118", "HP:0000001"}
    assert "HP:0002373" in onto.descendants("HP:0000707")


def test_duplicate_rows_merge_and_alternative_ids_fold_in(built):
    _, _, (k, _) = built
    seizure = k["diseases"]["OMIM:1"]["phenotypes"]["HP:0001250"]
    assert seizure["freq"] == pytest.approx(((0.80 + 0.99) / 2 + 0.5) / 2)
    assert seizure["onset"] == ["HP:0011463"] and seizure["sex"] is None


def test_negations_sex_restriction_onset_and_inheritance(built):
    _, _, (k, _) = built
    d = k["diseases"]["OMIM:1"]
    assert d["excluded"] == ["HP:0002373"]
    assert d["phenotypes"]["HP:0000028"]["sex"] == "male"
    assert d["onset_years"] == [[0.0, 0.0]] and d["onset_source"] == "hpoa"
    assert d["inheritance"] == ["HP:0001419"]


def test_heldout_pmid_rows_are_masked(built):
    _, _, (k, stats) = built
    assert "HP:0001250" not in k["diseases"]["OMIM:2"]["phenotypes"]
    assert "HP:0000028" in k["diseases"]["OMIM:2"]["phenotypes"]
    assert stats["rows_masked_heldout_pmid"] == 1


def test_excluded_frequency_is_a_negation_and_orphanet_fills_missing_onset(built):
    _, _, (k, _) = built
    d = k["diseases"]["ORPHA:3"]
    assert d["excluded"] == ["HP:0001250"]
    assert d["phenotypes"]["HP:0000028"]["freq"] is None  # unknown, not "always"
    assert d["onset_years"] == [[18.0, 65.0]] and d["onset_source"] == "orphanet"


def test_a_negation_contradicted_by_a_positive_is_dropped(built):
    _, _, (k, stats) = built
    assert k["diseases"]["OMIM:4"]["excluded"] == []
    assert stats["negations_dropped_conflicting_with_positive"] == 1


def test_gene_links_skip_polygenic_and_unnamed_loci_but_add_genes_to_phenotype_pairs(built):
    _, _, (k, _) = built
    assert k["genes"]["GENEA"] == {"OMIM:1": "MENDELIAN"}
    assert k["genes"]["GENEB"] == {"OMIM:2": "GENES_TO_PHENOTYPE_ONLY"}
    assert k["genes"]["GENED"] == {"OMIM:4": "GENES_TO_PHENOTYPE_ONLY"}
    assert "-" not in k["genes"]


def test_build_and_write_are_byte_deterministic(built, tmp_path):
    onto, args, (k, _) = built
    again, _ = kb.build(onto, *args, masked_pmids={"PMID:666"})
    kb.write(k, tmp_path / "a.json.gz")
    kb.write(again, tmp_path / "b.json.gz")
    assert (tmp_path / "a.json.gz").read_bytes() == (tmp_path / "b.json.gz").read_bytes()
    assert kb.read(tmp_path / "a.json.gz") == k
