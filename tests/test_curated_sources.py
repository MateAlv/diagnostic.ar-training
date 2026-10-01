# ruff: noqa: E501  (inline XML/HTML fixtures)
import gzip
import io
import json
import tarfile

from diagnostic_ar_training.knowledge import gene2phenotype, medlineplus, panelapp

NS = "https://medlineplus.gov/download/ghr-summaries-20250602.xsd"
COMPENDIUM = f"""<?xml version="1.0" encoding="utf-8"?>
<summaries xmlns="{NS}" xmlns:html="http://www.w3.org/1999/xhtml">
<health-condition-summary id="1">
<name>Marfan syndrome</name>
<ghr-page>https://medlineplus.gov/genetics/condition/marfan-syndrome</ghr-page>
<text-list><text><text-role>description</text-role><html><html:p>Affects <html:i>connective</html:i> tissue.</html:p></html></text></text-list>
<inheritance-pattern-list><inheritance-pattern><code>ad</code><memo>Autosomal dominant</memo></inheritance-pattern></inheritance-pattern-list>
<related-gene-list><related-gene><gene-symbol>FBN1</gene-symbol></related-gene></related-gene-list>
<synonym-list><synonym>MFS</synonym></synonym-list>
<db-key-list><db-key><db>OMIM</db><key>154700</key></db-key><db-key><db>MeSH</db><key>D008382</key></db-key></db-key-list>
<reviewed>2021-06</reviewed>
</health-condition-summary>
<gene-summary id="2"><gene-symbol>FBN1</gene-symbol><name>fibrillin 1</name></gene-summary>
</summaries>"""
PAGE = """<html><div class="main">
<div class="mp-exp exp-full" data-bookmark="description"><h2>Description</h2>
<section><div class="mp-content"><p>Marfan syndrome affects the <a href="x">connective tissue<img src="y"/></a>.</p></div></section></div>
<div class="mp-exp exp-full" data-bookmark="frequency"><h2>Frequency</h2>
<section><div class="mp-content"><p>The incidence is approximately 1 in 5,000 worldwide.</p></div></section></div>
<div class="mp-exp exp-full" data-bookmark="causes"><h2>Causes</h2><section><p>Mutations in <i>FBN1</i> &amp; others.</p></section></div>
<div class="mp-exp exp-full" data-bookmark="synonyms"><h2>Other Names</h2><section><li>MFS</li></section></div>
</div></html>"""


def _tar(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_medlineplus_compendium():
    [c] = medlineplus.parse_compendium(COMPENDIUM.encode())
    assert c.slug == "marfan-syndrome"
    assert c.genes == ("FBN1",)
    assert c.omim_ids == ("OMIM:154700",)
    assert c.inheritance == ("ad",) and c.inheritance_hpo == ("HP:0000006",)
    assert c.synonyms == ("MFS",)
    assert c.sections["description"] == "Affects connective tissue."


def test_medlineplus_page_sections():
    sections = medlineplus.parse_page(PAGE)
    assert sections["frequency"] == "The incidence is approximately 1 in 5,000 worldwide."
    assert sections["description"] == "Marfan syndrome affects the connective tissue ."
    assert sections["causes"] == "Mutations in FBN1 & others."


def test_medlineplus_load_merges_page(tmp_path):
    path = tmp_path / "mlp.tar.gz"
    path.write_bytes(
        _tar({"ghr-summaries.xml": COMPENDIUM.encode(), "condition/marfan-syndrome.html": PAGE.encode()})
    )
    [c] = medlineplus.load(path)
    assert c.sections["frequency"].startswith("The incidence")
    assert "synonyms" not in c.sections
    assert c.sections["description"].startswith("Marfan syndrome affects")


G2P_HEADER = (
    "g2p id,gene symbol,gene mim,hgnc id,previous gene symbols,disease name,disease mim,disease MONDO,"
    "allelic requirement,cross cutting modifier,confidence,variant consequence,variant types,"
    "molecular mechanism,molecular mechanism support,molecular mechanism categorisation,"
    "molecular mechanism evidence,phenotypes,publications,additional mined publications,panel,comments,"
    "date of last review,review"
)
G2P_ROWS = [
    "G2P1,BRIP1,605882,20473,BACH1; FANCJ,BRIP1-related Fanconi anemia,609054,MONDO:0012187,"
    "biallelic_autosomal,,definitive,absent gene product,,loss of function,inferred,,,"
    "HP:0000007; HP:0001263,16116424,999; 888,DD; Cancer,,2025-01-28,",
    "G2P2,ALG9,606941,15672,,ALG9-CDG,,,monoallelic_autosomal,typically de novo; restricted mutation set,"
    "Limited,,,,,,,,,,Eye,,2025-01-21,",
]


def test_gene2phenotype(tmp_path):
    path = tmp_path / "g2p.csv"
    path.write_text("\n".join([G2P_HEADER, *G2P_ROWS]) + "\n", encoding="utf-8")
    a, b = gene2phenotype.parse(path)
    assert a.gene == "BRIP1" and a.hgnc_id == "HGNC:20473"
    assert a.previous_symbols == ("BACH1", "FANCJ")
    assert a.disease_ids == ("OMIM:609054", "MONDO:0012187")
    assert a.hpo_ids == ("HP:0000007", "HP:0001263")
    assert a.pmids == ("PMID:16116424",)  # ML-mined publications are not curated
    assert a.panels == ("DD", "Cancer")
    assert a.variant_consequences == ("absent gene product",)
    assert a.confidence_rank == 5
    assert b.disease_ids == () and b.hpo_ids == () and b.pmids == ()
    assert b.confidence == "limited" and b.confidence_rank == 2
    assert b.cross_cutting_modifiers == ("typically de novo", "restricted mutation set")


def test_panelapp(tmp_path):
    panel = {"id": 7, "name": "Cerebral folate deficiency", "version": "1.4", "disease_group": "Metabolic",
             "relevant_disorders": ["R1"]}  # fmt: skip
    doc = {
        "panels": [panel],
        "genes": [
            {
                "entity_type": "gene",
                "entity_name": "SLC46A1",
                "gene_data": {"hgnc_symbol": "SLC46A1", "hgnc_id": "HGNC:30521"},
                "confidence_level": "3",
                "phenotypes": ["Folate malabsorption, hereditary, OMIM:229050", "Seizures HP:0001250", ""],
                "mode_of_inheritance": "BIALLELIC, autosomal or pseudoautosomal",
                "publications": ["21333572", "not a pmid"],
                "panel": panel,
            },
            {
                "entity_type": "gene",
                "entity_name": "GENEB",
                "gene_data": {"gene_symbol": "GENEB"},
                "confidence_level": "0",
                "phenotypes": ["Bardet-Biedl syndrome 1, 209900", "MONDO:0012345"],
                "panel": panel,
            },
            {"entity_type": "str", "entity_name": "STR1", "panel": panel},
        ],
    }
    path = tmp_path / "panelapp.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as h:
        json.dump(doc, h)
    a, b = panelapp.parse(path)
    assert a.gene == "SLC46A1" and a.evidence == "green" and a.panel_name == "Cerebral folate deficiency"
    assert a.omim_ids == ("OMIM:229050",)
    assert a.hpo_ids == ("HP:0001250",)
    assert a.pmids == ("PMID:21333572",)
    assert len(a.phenotypes) == 2
    assert b.evidence == "red" and b.omim_ids == ("OMIM:209900",) and b.hpo_ids == ()
