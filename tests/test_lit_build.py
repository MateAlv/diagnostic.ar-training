import json

import pytest

from diagnostic_ar_training.knowledge import lit_build as LB
from diagnostic_ar_training.knowledge.lit_extract import ROW_COLUMNS
from diagnostic_ar_training.knowledge.recount import COLUMNS as HPOA_COLUMNS
from diagnostic_ar_training.ontology import Ontology

OBO = "http://purl.obolibrary.org/obo/HP_"
ALT = "http://www.geneontology.org/formats/oboInOwl#hasAlternativeId"
HP = {"0000001": [], "0000118": ["0000001"], "0001250": ["0000118"], "0000505": ["0000118"]}
SEIZURE, VISION = "HP:0001250", "HP:0000505"
CHAPTERS = {"NBK10": ("grshort", "20301999")}


@pytest.fixture
def onto(tmp_path):
    nodes = [{"id": OBO + c, "lbl": c} for c in HP]
    nodes[2]["meta"] = {"basicPropertyValues": [{"pred": ALT, "val": "HP:0009999"}]}
    edges = [{"sub": OBO + c, "pred": "is_a", "obj": OBO + p} for c, ps in HP.items() for p in ps]
    (tmp_path / "hp.json").write_text(json.dumps({"graphs": [{"nodes": nodes, "edges": edges}]}))
    return Ontology.from_json(tmp_path / "hp.json")


def lit(source="PMID:1", disease="OMIM:1", term=SEIZURE, p="0.5", n="", m="", flags="", units="", **kw):
    row = {c: "" for c in ROW_COLUMNS}
    row |= {
        "source_id": source,
        "gene": "G1",
        "disease_id": disease,
        "construction_unit": units or f"G1|{disease}",
        "disease_name": "dis",
        "feature_label": "feature",
        "hpo_id": term,
        "prevalence": p,
        "n_affected": n,
        "n_assessed": m,
        "flags": flags,
        "population": "all affected",
        "source_kind": "genereviews" if source.startswith("NBK") else "cohort_paper",
    }
    return row | kw


def age(source="NBK10", disease="OMIM:1", low="", high="", m="", feature="AGE_PRESENTATION", **kw):
    cols = "presentation" if feature == "AGE_PRESENTATION" else "onset"
    row = lit(source, disease, term="", p="", m=m, feature_label=feature, **kw)
    return row | {f"age_{cols}_low_years": low, f"age_{cols}_high_years": high}


def hpoa(disease="OMIM:1", term=SEIZURE, ref="PMID:7", freq="", qualifier=""):
    values = [disease, "HPOA name", qualifier, term, ref, "PCS", "", freq, "", "", "P", "HPO:x"]
    return dict(zip(HPOA_COLUMNS, values, strict=True))


def run(rows, onto, hpoa_rows=()):
    return LB.build(list(rows), list(hpoa_rows), onto, CHAPTERS)


def by_key(result):
    return {(r["database_id"], r["hpo_id"], r["qualifier"]): r for r in result["lit_rows"]}


# --- Rule 1 -----------------------------------------------------------------------


def test_counts_become_count_notation_and_prevalence_only_a_percentage(onto):
    out = by_key(run([lit(n="3", m="10", p="0.3"), lit(term=VISION, p="0.6667")], onto))
    count, pct = out[("OMIM:1", SEIZURE, "")], out[("OMIM:1", VISION, "")]
    assert count["frequency"] == "3/10" and pct["frequency"] == "66.67%"
    assert count["reference"] == "PMID:1" and count["evidence"] == "PCS" and count["aspect"] == "P"
    assert count["biocuration"] == "diagnostic.ar-training:lit-extract"


def test_a_stated_denominator_alone_stays_a_percentage(onto):
    (row,) = run([lit(p="0.3", m="40")], onto)["lit_rows"]
    assert row["frequency"] == "30%"


def test_zero_with_counts_is_0_over_m_and_zero_without_counts_is_not(onto):
    out = by_key(run([lit(p="0", n="0", m="23"), lit(term=VISION, p="0")], onto))
    assert out[("OMIM:1", SEIZURE, "")]["frequency"] == "0/23"
    neg = out[("OMIM:1", VISION, "NOT")]
    assert neg["frequency"] == "" and neg["reference"] == "PMID:1"


# --- Rules 2 and 3 ----------------------------------------------------------------


GROUP = "G1|OMIM:1;G2|OMIM:2;G3|OMIM:3;G4|OMIM:3"


def test_pooled_group_is_a_percentage_on_every_listed_disease_never_counts(onto):
    result = run([lit(source="NBK10", p="0.4", n="4", m="10", flags="pooled_group", units=GROUP)], onto)
    rows = result["lit_rows"]
    assert [(r["database_id"], r["frequency"]) for r in rows] == [
        ("OMIM:1", "40%"),
        ("OMIM:2", "40%"),
        ("OMIM:3", "40%"),
    ]
    assert result["report"]["placements"]["pooled_group_placements"] == 3


def test_pooled_group_skips_a_disease_with_a_unit_specific_row_from_the_same_source(onto):
    rows = [
        lit(source="NBK10", p="0.4", flags="pooled_group", units=GROUP),
        lit(source="NBK10", disease="OMIM:2", p="0.9", gene="G2", units="G2|OMIM:2"),
        lit(source="PMID:5", disease="OMIM:3", p="0.1", m="50", gene="G3", units="G3|OMIM:3"),
    ]
    result = run(rows, onto)
    out = {r["database_id"]: (r["frequency"], r["reference"]) for r in result["lit_rows"]}
    assert out["OMIM:2"] == ("90%", "NBK10")
    assert out["OMIM:3"] == ("10%", "PMID:5")  # another source's row does not block the group figure...
    assert result["report"]["placements"]["by_outcome"][LB.DROP_GROUP_SKIP] == 1
    assert result["report"]["placements"]["by_outcome"][LB.DROP_PERCENT] == 1  # ...rule 6 decides


def test_pooled_row_stays_on_its_own_disease(onto):
    rows = run([lit(p="0.7", flags="pooled", units="G1|OMIM:1")], onto)["lit_rows"]
    assert [(r["database_id"], r["frequency"]) for r in rows] == [("OMIM:1", "70%")]


def test_pooled_group_zero_is_not_on_every_listed_disease(onto):
    rows = run([lit(p="0", flags="pooled_group", units="G1|OMIM:1;G2|OMIM:2")], onto)["lit_rows"]
    assert [(r["database_id"], r["qualifier"]) for r in rows] == [("OMIM:1", "NOT"), ("OMIM:2", "NOT")]


# --- Rule 4 -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("flags", "p", "lo", "hi", "n", "m", "freq"),
    [
        ("small_n", "0.5", "", "", "2", "4", "2/4"),
        ("binned", "0.875", "0.75", "1", "", "", "87.5%"),
        ("lower_bound", "0.95", "0.95", "1", "", "", "95%"),
    ],
)
def test_small_n_binned_and_lower_bound_are_kept_with_their_point_estimate(
    onto, flags, p, lo, hi, n, m, freq
):
    row = lit(p=p, n=n, m=m, flags=flags, prevalence_low=lo, prevalence_high=hi)
    assert [r["frequency"] for r in run([row], onto)["lit_rows"]] == [freq]


# --- Rule 5 -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "ref"),
    [
        ("PMID:7", "PMID:7;OMIM:1"),
        ("NBK10", "https://www.ncbi.nlm.nih.gov/books/NBK10/"),
        ("NBK10", "PMID:20301999"),
        ("NBK10", "ISBN-13:1;http://www.ncbi.nlm.nih.gov/bookshelf/br.fcgi?book=gene&part=grshort"),
    ],
)
def test_a_source_hpoa_already_cites_for_the_disease_and_term_is_dropped(onto, source, ref):
    result = run([lit(source=source, n="1", m="2")], onto, [hpoa(ref=ref, freq="5/9")])
    assert result["lit_rows"] == []
    assert result["report"]["feature_rows_by_outcome"] == {LB.DROP_HPOA: 1}


def test_double_count_is_per_disease_and_term_and_resolves_alt_ids(onto):
    rows = [lit(source="PMID:7", n="1", m="2"), lit(source="PMID:7", term=VISION, n="1", m="2")]
    result = run(
        rows, onto, [hpoa(term="HP:0009999", ref="PMID:7"), hpoa(disease="OMIM:9", term=VISION, ref="PMID:7")]
    )
    assert [r["hpo_id"] for r in result["lit_rows"]] == [VISION]


# --- Rule 6 -----------------------------------------------------------------------


def test_counts_pool_across_distinct_sources_and_one_row_per_source(onto):
    rows = [
        lit(source="PMID:1", n="3", m="10", p="0.3"),
        lit(source="PMID:1", n="10", m="20", p="0.5", population="adults"),
        lit(source="PMID:2", n="1", m="5", p="0.2"),
    ]
    result = run(rows, onto)
    (row,) = result["lit_rows"]
    assert row["frequency"] == "11/25" and row["reference"] == "PMID:1;PMID:2"
    assert result["report"]["placements"]["by_outcome"][LB.DROP_SAME_SOURCE_COUNT] == 1


def test_one_percentage_per_disease_and_term_with_the_largest_population(onto):
    rows = [
        lit(source="PMID:1", p="0.3", m="40"),
        lit(source="PMID:2", p="0.6", m="120"),
        lit(source="NBK10", p="0.9"),
        lit(source="PMID:3", p="0.1", n="1", m="10"),
    ]
    result = run(rows, onto)
    counts, percent = result["lit_rows"]
    assert counts["frequency"] == "1/10"
    assert (percent["frequency"], percent["reference"]) == ("60%", "PMID:2")
    assert result["report"]["placements"]["by_outcome"][LB.DROP_PERCENT] == 2
    assert result["report"]["hpoa_lit"]["by_notation"]["percent_rows_beside_lit_counts"] == 1


def test_with_no_stated_population_both_sexes_beat_one(onto):
    rows = [lit(p="0.8", sex_restriction="male", population="males"), lit(p="0.5")]
    result = run(rows, onto)
    assert [(r["frequency"], r["sex"]) for r in result["lit_rows"]] == [("50%", "")]
    assert result["report"]["hpoa_lit"]["by_notation"]["percent_choice_by_both_sexes_over_one"] == 1


def test_sex_column_only_when_every_pooled_row_agrees(onto):
    same = run(
        [lit(n="1", m="2", sex_restriction="male"), lit("PMID:2", n="1", m="3", sex_restriction="male")], onto
    )
    mixed = run([lit(n="1", m="2", sex_restriction="male"), lit("PMID:2", n="1", m="3")], onto)
    assert same["lit_rows"][0]["sex"] == "MALE" and mixed["lit_rows"][0]["sex"] == ""


# --- Rule 7 -----------------------------------------------------------------------


def test_presentation_age_prefers_genereviews_then_the_largest_population(onto):
    rows = [
        age("PMID:1", low="1", high="3", m="500"),
        age("NBK10", low="2", high="9", m="30"),
        age("NBK11", low="4", high="6", m="60"),
        age("NBK10", disease="OMIM:2", low="5", high="7"),
        age("NBK10", disease="OMIM:2", low="0", high="5", feature="AGE_ONSET"),
    ]
    result = run(rows, onto)
    assert result["presentation_ages"] == [
        {"disease_id": "OMIM:1", "age_low_years": "4", "age_high_years": "6", "source": "NBK11"},
        {"disease_id": "OMIM:2", "age_low_years": "5", "age_high_years": "7", "source": "NBK10"},
    ]
    stats = result["report"]["presentation_ages"]
    assert stats["placements_by_outcome"] == {"used": 2, "not_chosen": 2}
    assert result["report"]["age_onset_coverage"]["diseases_also_with_presentation_age"] == 1


@pytest.mark.parametrize(
    ("low", "high", "out"),
    [
        ("30", "30", ("27", "33")),
        ("4.5", "4.5", ("3.5", "5.5")),
        ("0", "0", ("0", "1")),
        ("", "5", ("0", "5")),
    ],
)
def test_single_values_are_widened_and_a_missing_low_end_is_zero(onto, low, high, out):
    (row,) = run([age(low=low, high=high)], onto)["presentation_ages"]
    assert (row["age_low_years"], row["age_high_years"]) == out


def test_an_open_upper_bound_gives_no_range(onto):
    result = run([age(low="40", high="")], onto)
    assert result["presentation_ages"] == []
    assert result["report"]["presentation_ages"]["placements_by_outcome"] == {LB.AGE_OPEN_UPPER: 1}


def test_presentation_file_has_the_simulator_header(onto):
    lines = LB.presentation_lines(run([age(low="1", high="2")], onto)["presentation_ages"])
    assert lines[0] == "disease_id\tage_low_years\tage_high_years\tsource\n"
    assert lines[1] == "OMIM:1\t1\t2\tNBK10\n"


def test_pooled_group_age_applies_where_the_source_has_no_specific_row(onto):
    rows = [
        age("NBK10", low="1", high="2", flags="pooled_group", construction_unit="G1|OMIM:1;G2|OMIM:2"),
        age("NBK10", disease="OMIM:2", low="5", high="6", gene="G2", construction_unit="G2|OMIM:2"),
    ]
    out = {r["disease_id"]: r["age_low_years"] for r in run(rows, onto)["presentation_ages"]}
    assert out == {"OMIM:1": "1", "OMIM:2": "5"}


# --- Report -----------------------------------------------------------------------


def test_report_separates_new_and_existing_terms_and_their_effect(onto):
    rows = [lit(n="1", m="2"), lit(term=VISION, p="0.4"), lit(disease="OMIM:5", p="0")]
    hpoa_rows = [hpoa(ref="PMID:99", freq="HP:0040282"), hpoa(term=VISION, ref="PMID:98", freq="3/9")]
    report = run(rows, onto, hpoa_rows)["report"]["hpoa_lit"]
    assert report["terms"] == {"new": 0, "existing": 2}
    assert report["effects"] == {
        "lit_counts_override_hpoa_category": 1,
        "lit_percent_shadowed_by_hpoa_counts": 1,
    }
    assert report["not_pairs"] == 1 and report["diseases_not_in_hpoa_recount"] == 1
    assert report["units_in"] == 2 and report["units_enriched"] == 2


def test_disease_name_comes_from_hpoa_then_the_row(onto):
    rows = run([lit(), lit(disease="OMIM:5")], onto, [hpoa(term=VISION)])["lit_rows"]
    assert [r["disease_name"] for r in rows] == ["HPOA name", "dis"]


def test_reference_keys_and_chapter_index():
    keys = LB.reference_keys("PMID:1;https://www.ncbi.nlm.nih.gov/books/NBK5/;OMIM:3")
    assert keys == {"PMID:1", "NBK5"}
    text = "#GR_shortname\tGR_Title\tNBK_id\tPMID\naadc\tAADC\tNBK595821\t37824694\n"
    assert LB.chapter_index(text) == {"NBK595821": ("aadc", "37824694")}
    assert LB.source_keys("NBK595821", LB.chapter_index(text)) == {"NBK595821", "GR:aadc", "PMID:37824694"}
