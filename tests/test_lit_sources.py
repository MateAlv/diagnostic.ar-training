import io
import tarfile

from diagnostic_ar_training.knowledge import lit_sources as L

INDEX = {
    "GRshortname_NBKid_genesymbol_dzname.txt": "\n".join(
        [
            "#header",
            "alpha|NBK10|GENEA|Alpha syndrome",
            "alpha|NBK10|GENEB|Alpha syndrome",
            "beta|NBK20|EVALG|Beta disease",
            "gamma|NBK30|GENEC|Gamma disease",
            "delta|NBK40|GENED|Delta disease",
            "eps|NBK50|Not applicable|Overview",
        ]
    ),
    "NBKid_shortname_OMIM.txt": "#x\nNBK10\talpha\t100\nNBK40\tdelta\t999\n",
    "GRtitle_shortname_NBKid.txt": "#x\nalpha\tAlpha Syndrome\tNBK10\n",
}

NXML = b"""<book-part><body>
<sec><title>Clinical Description</title>
<p>Seizures occur in 12/20 individuals. Onset at age 3 years.</p></sec>
<table-wrap><caption><p>Frequency of Select Features</p></caption><table>
<tr><th>Feature</th><th>%</th></tr><tr><td>Seizures</td><td>60%</td></tr></table></table-wrap>
<table-wrap><caption><p>Treatment of Manifestations</p></caption><table>
<tr><td>x</td><td>10%</td></tr></table></table-wrap>
</body><back><ref-list>
<ref><pub-id pub-id-type="pmid">111</pub-id></ref><ref><pub-id pub-id-type="pmid">222</pub-id></ref>
</ref-list></back></book-part>"""


def gene(name, role="construction", weakness="ok_counts", shares=False, ids=("OMIM:1",)):
    return L.GeneInfo(name, name, frozenset({name}), role, True, frozenset(ids), shares, weakness)


def test_parse_index_and_snapshot(tmp_path):
    path = tmp_path / "gr.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        members = {f"{L.INDEX_DIR}/{k}": v.encode() for k, v in INDEX.items()}
        members[f"{L.NXML_DIR}/alpha.nxml"] = NXML
        members[f"{L.NXML_DIR}/alpha.pdf"] = b"%PDF"
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    chapters, nxml = L.read_snapshot(path)
    assert set(nxml) == {"alpha"}
    assert chapters["alpha"].genes == {"GENEA", "GENEB"}
    assert chapters["alpha"].omim == {"OMIM:100"}
    assert chapters["alpha"].title == "Alpha Syndrome"
    assert chapters["eps"].genes == set()


def test_screen_chapter_counts_feature_tables_and_pmids():
    s = L.screen_chapter(NXML)
    assert s.pmids == {"111", "222"}
    assert (s.feature_tables, s.feature_table_numeric_rows) == (1, 1)
    assert s.clinical_numeric_sentences == 1
    assert s.age_numeric_sentences == 1


def test_chapter_rows_apply_exclusions_and_priority():
    chapters = L.parse_index(INDEX)
    screen = L.screen_chapter(NXML)
    no_table = L.ChapterScreen({"5"}, 0, 0, 0, 0)
    screens = {
        "alpha": screen,
        "beta": no_table,
        "gamma": L.ChapterScreen({"666"}, 0, 0, 0, 0),
        "eps": no_table,
    }
    genes = [
        gene("GENEA", weakness="W1_mostly_no_frequency"),
        gene("GENEB", shares=True),
        gene("EVALG", role="evaluation"),
        gene("GENEC"),
        gene("GENED"),
    ]
    rows = {
        r["shortname"]: r for r in L.chapter_rows(chapters, screens, genes, {"EVALG"}, {"OMIM:999"}, {"666"})
    }
    assert rows["alpha"]["status"] == "usable"
    assert rows["alpha"]["construction_genes"] == "GENEA"
    assert rows["alpha"]["genes_blocked_eval_disease"] == "GENEB"
    assert rows["alpha"]["priority_class"] == "P1"
    assert rows["alpha"]["priority_rank"] == 1
    assert rows["beta"]["status"] == "dropped_eval_unit"
    assert rows["gamma"]["status"] == "dropped_heldout_pmid"
    assert rows["delta"]["status"] == "dropped_eval_unit"  # OMIM:999 is an evaluation disease
    assert rows["eps"]["status"] == "dropped_no_construction_gene"


def test_weakness_tiers():
    assert L.weakness({}, False) == "W0_no_profile"
    assert L.weakness({"t": [True, True, 8]}, False) == "ok_counts"
    assert L.weakness({"t": [True, True, 3]}, False) == "W4_counts_from_small_series_only"
    assert L.weakness({"t": [True, False, 0]}, True) == "W2_orphanet_bins_only"
    assert L.weakness({"t": [False, False, 0], "u": [True, False, 0]}, False) == "W1_mostly_no_frequency"
    assert L.weakness({"t": [True, False, 0]}, False) == "W3_no_counts_other"


def test_stated_n():
    assert L.stated_n("We studied 45 unrelated patients") == 45
    assert L.stated_n("Fifty-eight children were assessed") == 58
    assert L.stated_n("12 of 40 patients had seizures") == 40
    assert L.stated_n("200 healthy controls and 18 patients") == 18
    assert L.stated_n("in 2019 patients were") is None
    assert L.stated_n("40% of patients") is None
    assert L.stated_n("trial NCT04537832 of children") is None
    assert L.stated_n("a cohort (n = 33)") == 33
    assert L.stated_n("a boy with seizures") is None


def record(**kw):
    base = {
        "pmid": "1",
        "pmcid": "PMC1",
        "license": "cc by",
        "title": "Clinical spectrum of GENEA disorder",
        "abstractText": "We describe 30 patients with pathogenic GENEA variants.",
        "pubTypeList": {"pubType": ["Journal Article"]},
        "source": "MED",
    }
    return base | kw


def test_screen_paper_rule_order():
    args = ({"9"}, {"8"}, {"EVALG"})
    assert L.screen_paper(record(), *args) == ("selected", "n>=20", 30)
    assert L.screen_paper(record(pmid="9"), *args)[1] == "heldout_pmid"
    assert L.screen_paper(record(pmid="8"), *args)[1] == "litpanel_source"
    assert L.screen_paper(record(license="cc by-nd"), *args)[1] == "licence:cc by-nd"
    assert L.screen_paper(record(license=None), *args)[1] == "licence:none"
    assert L.screen_paper(record(license="CC BY-NC-ND"), *args)[0] == "selected"
    assert (
        L.screen_paper(record(pubTypeList={"pubType": ["Case Reports"]}), *args)[1] == "pub_type:case_report"
    )
    assert L.screen_paper(record(source="PPR"), *args)[1] == "preprint"
    assert L.screen_paper(record(title="EVALG and GENEA"), *args)[1] == "mentions_eval_gene:EVALG"
    assert L.screen_paper(record(abstractText="30 patients; a review of the literature"), *args)[1] == (
        "literature_review"
    )
    assert L.screen_paper(record(abstractText="A GWAS of 3000 patients"), *args)[1] == "association_study"
    assert L.screen_paper(record(abstractText="EGFR-mutant NSCLC in 80 patients"), *args)[1] == (
        "somatic_or_oncology_treatment"
    )
    assert (
        L.screen_paper(record(abstractText="We describe 30 patients."), *args)[1] == "no_genetic_confirmation"
    )
    assert L.screen_paper(record(abstractText="Pathogenic variants in 12 patients."), *args) == (
        "excluded",
        "n_lt_20",
        12,
    )
    assert L.screen_paper(record(abstractText="Pathogenic variants were found."), *args)[1] == "n_not_stated"
    assert L.screen_paper(record(), *args, frozenset({"GENEA"}))[0] == "selected"
    cd4 = record(abstractText="CD4 counts of 90 pathogenic HIV patients")
    assert L.screen_paper(cd4, *args, frozenset({"CD4"}))[1] == "gene_not_in_variant_context"


def test_in_variant_context():
    assert L.in_variant_context("COCH", "COCH-related hearing loss")
    assert L.in_variant_context("GENEA", "biallelic variants in GENEA cause")
    assert not L.in_variant_context("CD4", "CD4 counts fell in HIV")


def test_paper_row_marks_in_hpoa():
    g = gene("GENEA", ids=("OMIM:1",))
    row = L.paper_row(record(), "selected", "n>=20", 30, [g], "query_gene", [], {"OMIM:1": {"1"}}, "q")
    assert (row["status"], row["reason"], row["in_hpoa"], row["in_hpoa_diseases"]) == (
        "excluded",
        "in_hpoa",
        True,
        "OMIM:1",
    )
    row = L.paper_row(record(), "selected", "n>=20", 30, [g], "query_gene", ["alpha"], {}, "q")
    assert row["status"] == "selected" and row["cited_by_genereviews"] is True


def test_plain_and_word_in():
    assert L.plain("Variants in &lt;i&gt;SCN1A&lt;/i&gt; gene") == "Variants in SCN1A gene"
    assert L.word_in("SCN1A", "SCN1A-related epilepsy")
    assert not L.word_in("SCN1", "SCN1A epilepsy")
    assert not L.word_in("SET", "a set of patients")


def test_queries_are_recorded_strings():
    assert L.epmc_gene_query("ABC1").startswith('TITLE:"ABC1" AND (TITLE:(cohort')
    assert L.epmc_pmid_query(["1", "2"]) == "(EXT_ID:1 OR EXT_ID:2) AND SRC:MED AND OPEN_ACCESS:y"
