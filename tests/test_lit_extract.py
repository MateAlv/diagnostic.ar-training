from diagnostic_ar_training.knowledge import lit_extract as le
from diagnostic_ar_training.ontology import Ontology

NXML = b"""<book-part-wrapper><book-part><book-part-meta>
<title-group><title>Alpha Syndrome</title></title-group>
<abstract><sec><title>Clinical characteristics.</title><p>Alpha is rare.</p></sec></abstract>
</book-part-meta><body>
<sec><title>Clinical Characteristics</title>
<sec><title>Clinical Description</title>
<p>Seizures occur in 12/20 individuals<sup>1</sup>. Onset is at age 3 years
[<xref>Smith et al 2010</xref>].</p>
<table-wrap><label>Table 2. </label><caption><p>Alpha: Frequency of Select Features</p></caption>
<table><thead><tr><th>Feature</th><th>%</th></tr></thead>
<tbody><tr><td>Seizures</td><td>60%</td></tr><tr><td>Ataxia</td><td>&gt;99%</td></tr></tbody></table>
<table-wrap-foot><fn><p>Based on two cohorts</p></fn></table-wrap-foot></table-wrap>
<list><list-item><p>Feature one</p></list-item></list>
</sec>
<sec><title>Prevalence</title><p>Unknown.</p></sec>
</sec>
<sec><title>References</title><ref-list><ref><pub-id pub-id-type="pmid">111</pub-id></ref></ref-list></sec>
</body></book-part></book-part-wrapper>"""


def ontology():
    parents = {
        "HP:0000001": (),
        "HP:0000118": ("HP:0000001",),
        "HP:0001250": ("HP:0000118",),
        "HP:0001251": ("HP:0000118",),
        "HP:0000006": ("HP:0000001",),
    }
    labels = {"HP:0001250": "Seizure", "HP:0001251": "Ataxia", "HP:0000006": "AD"}
    return Ontology(parents, labels, {"HP:9999999": "HP:0001250"}, {}, frozenset())


def test_render_sections_and_quotes():
    text = le.render_jats(NXML)
    assert text.startswith("# Alpha Syndrome\n")
    assert "Seizures occur in 12/20 individuals^1. Onset is at age 3 years [Smith et al 2010]." in text
    assert "[Table 2] Alpha: Frequency of Select Features\nFeature | %\nSeizures | 60%\nAtaxia | >99%" in text
    assert "[Table 2 note] Based on two cohorts\n[/Table 2]" in text
    assert "- Feature one" in text and "111" not in text and "References" not in text
    keys = le.sections(text)
    assert {"abstract", "clinical description", "table 2", "prevalence"} <= set(keys)
    assert "table 2 note" not in keys
    table = le.passage(text, "Table 2")
    assert table.splitlines()[0].startswith("[Table 2]") and table.endswith("[/Table 2]")
    desc = le.passage(text, "Clinical Description")
    assert "Seizures | 60%" in desc and "Unknown." not in desc
    assert le.passage(text, "Clinical characteristics.") is not None
    assert le.passage(text, "Nope") is None
    assert le.quote_found("Seizures   occur in 12/20", desc)
    assert le.quote_found("Feature | % ... Ataxia | >99%", table)
    assert not le.quote_found("Ataxia | >99% ... Feature | %", table)
    assert le.quote_words("a b ... c") == 3


def test_construction_entities_and_shards():
    def ent(name, w, ids=None, sim=True):
        return {
            "entity": name,
            "ids": ids or [name],
            "profile_ids": [name],
            "sim_weight": w,
            "simulable": sim,
        }

    built = {
        "vocabulary": {"GA": "GA", "GB": "GB", "EV": "EV", "GC": "GC"},
        "genes": {
            "GA": {
                "entities": [
                    ent("OMIM:1", 0.9),
                    ent("OMIM:2", 0.1),
                    ent("OMIM:3", 0.2, ["OMIM:3", "ORPHA:9"]),
                ]
            },
            "GB": {"entities": [ent("OMIM:9", 0.9)]},
            "EV": {"entities": [ent("OMIM:5", 0.9)]},
            "GC": {"entities": [ent("OMIM:7", 0.9, sim=False)]},
        },
    }
    entities = le.construction_entities(built, {"EV"}, {"ORPHA:9", "OMIM:9"})
    assert [e.disease_id for e in entities["GA"]] == ["OMIM:1", "OMIM:2"]
    assert "GB" not in entities and "EV" not in entities and "GC" not in entities
    assert [e.disease_id for e in le.chapter_units(["GA"], {"OMIM:2"}, entities)] == ["OMIM:2"]
    assert [e.disease_id for e in le.chapter_units(["GA"], {"OMIM:77"}, entities)] == ["OMIM:1"]
    chapters = [
        {"status": "usable", "priority_class": c, "priority_rank": str(r), "nbk": f"NBK{r}",
         "shortname": f"s{r}", "title": "t", "construction_genes": "GA", "omim_ids": "OMIM:2"}
        for r, c in [(3, "P2"), (1, "P1"), (2, "P1")] + [(i, "P3") for i in range(4, 15)]
    ] + [{"status": "dropped_eval_unit", "priority_class": "", "priority_rank": ""}]  # fmt: skip
    papers = [
        {"status": "selected", "pmid": str(i), "pmcid": f"PMC{i}", "licence": "cc by", "weak_genes": "",
         "title": "p", "genes": "GA"}
        for i in range(13)
    ] + [{"status": "excluded"}]  # fmt: skip
    rows = le.assign_shards(chapters, papers, entities)
    chap = [r for r in rows if r["kind"] == "chapters"]
    assert [r["source_id"] for r in chap[:3]] == ["NBK1", "NBK2", "NBK3"]
    assert [r["shard"] for r in chap].count("C001") == 10 and chap[-1]["shard"] == "C002"
    pap = [r for r in rows if r["kind"] == "papers"]
    assert pap[0]["source_id"] == "PMID:0" and pap[12]["shard"] == "P002" and pap[11]["position"] == 12
    assert pap[0]["units"] == "GA|OMIM:1;GA|OMIM:2"
    assert le.parse_units(chap[0]["units"]) == {("GA", "OMIM:2")}


def base_row(**kw):
    row = dict.fromkeys(le.ROW_COLUMNS, "")
    row.update(
        source_id="NBK10",
        gene="GA",
        disease_id="OMIM:1",
        construction_unit="GA|OMIM:1",
        feature_label="Seizure",
        hpo_id="HP:0001250",
        prevalence="0.6",
        n_affected="12",
        n_assessed="20",
        population="all affected",
        source_kind="genereviews",
        citation="GeneReviews NBK10 (Alpha Syndrome)",
        section="Clinical Description",
        evidence_quote="Seizures occur in 12/20 individuals",
        access_path="genereviews-snapshot",
        licence=le.GENEREVIEWS_LICENCE,
    )
    row.update(kw)
    return row


def check(rows, **boundary):
    text = le.render_jats(NXML)
    sources = {
        "NBK10": le.ShardSource(
            "NBK10", "chapters", "genereviews", le.GENEREVIEWS_LICENCE, {("GA", "OMIM:1")}
        ),
        "PMID:5": le.ShardSource("PMID:5", "papers", "cohort_paper", "cc by", {("GA", "OMIM:1")}),
    }
    texts = {
        "NBK10": le.SourceText(text, "genereviews-snapshot"),
        "PMID:5": le.SourceText(text, "europepmc-fulltext"),
    }
    b = le.Boundary(
        ontology(), boundary.get("eval_genes", set()), {"OMIM:66"}, {"5"} if boundary.get("held") else set()
    )
    return le.check_rows(rows, sources, texts, b)


def test_check_rows_passes_and_fails():
    age = base_row(
        feature_label="AGE_ONSET", hpo_id="", prevalence="", n_affected="", n_assessed="",
        age_onset_low_years="3", age_onset_high_years="3", evidence_quote="Onset is at age 3 years",
    )  # fmt: skip
    table = base_row(
        hpo_id="HP:0001251", feature_label="Ataxia", prevalence="0.99", prevalence_high="1", n_affected="",
        n_assessed="", section="Table 2", evidence_quote="Ataxia | >99%",
    )  # fmt: skip
    assert check([base_row(), age, table]) == []
    cases = {
        "not a current HPO id": base_row(hpo_id="HP:9999999"),
        "not under Phenotypic abnormality": base_row(hpo_id="HP:0000006"),
        "n_affected 30 > n_assessed 20": base_row(n_affected="30", prevalence="1"),
        "is not 12/20": base_row(prevalence="0.5"),
        "not verbatim in that section": base_row(evidence_quote="Seizures occur in 13/20 individuals"),
        "fix `section`": base_row(section="Prevalence"),
        "not a heading or table": base_row(section="Results"),
        "not a unit this source may feed": base_row(disease_id="OMIM:2", construction_unit="GA|OMIM:2"),
        "evaluation disease": base_row(disease_id="OMIM:66", construction_unit="GA|OMIM:66"),
        "construction_unit must be": base_row(construction_unit="GA OMIM:1"),
        "small_n exactly when": base_row(n_affected="2", n_assessed="4", prevalence="0.5"),
        "words (max 25)": base_row(evidence_quote=" ".join(["Seizures"] * 26)),
        "licence must be": base_row(licence="cc by"),
        "an age row has no prevalence": base_row(
            feature_label="AGE_PRESENTATION", hpo_id="", age_presentation_low_years="1"
        ),  # fmt: skip
        "must leave": base_row(**{**age, "age_presentation_low_years": "2"}),
        "age_onset_low_years > age_onset_high_years": base_row(**{**age, "age_onset_low_years": "4"}),
        "duplicate": None,
    }
    for message, row in cases.items():
        rows = [base_row(), base_row()] if row is None else [row]
        problems = check(rows)
        assert any(message in p for p in problems), (message, problems)
    assert any("evaluation gene" in p for p in check([base_row()], eval_genes={"GA"}))
    paper = base_row(source_id="PMID:5", citation="PMID:5 (PMC5)", source_kind="cohort_paper",
                     licence="cc by", access_path="europepmc-fulltext")  # fmt: skip
    assert check([paper]) == []
    assert any("held-out" in p for p in check([paper], held=True))
    assert check([base_row(n_affected="2", n_assessed="4", prevalence="0.5", flags="small_n",
                           evidence_quote="Seizures occur in")]) == []  # fmt: skip


def test_notes():
    rows = [base_row()]
    good = [
        {"source_id": "NBK10", "outcome": "extracted", "rows": "1", "note": ""},
        {"source_id": "NBK11", "outcome": "no_numbers", "rows": "0", "note": "vague quantifiers only"},
    ]
    assert le.check_notes(good, ["NBK10", "NBK11"], rows) == []
    assert le.check_notes(good[:1], ["NBK10", "NBK11"], rows)
    bad = [dict(good[0], rows="2"), dict(good[1], note="")]
    assert len(le.check_notes(bad, ["NBK10", "NBK11"], rows)) == 2


def test_sample_prompt_and_agreement():
    rows = {"C001": [base_row() for _ in range(25)], "C002": [base_row() for _ in range(3)]}
    picks = le.sample(rows, 0.1, 1, 0)
    assert [s for s, _ in picks].count("C001") == 3 and [s for s, _ in picks].count("C002") == 1
    assert picks == le.sample(rows, 0.1, 1, 0)
    assert len(le.sample({"C001": rows["C001"]}, 0.1, 1, 30)) == 25
    prompt = le.crosscheck_prompt(base_row(), "Seizure")
    assert "0.6" not in prompt and "12/20" not in prompt and "Seizures occur" not in prompt
    assert "Seizure (HP:0001250 Seizure)" in prompt and "all affected" in prompt
    age = base_row(feature_label="AGE_ONSET", age_onset_low_years="2", age_onset_high_years="4")
    assert "Age at onset" in le.crosscheck_prompt(age)

    def answer(**kw):
        d = dict.fromkeys(le.ANSWER_SCHEMA["required"])
        d.update({"found": True, "quote": "q", **kw})
        return le.parse_answer(d)

    assert le.agrees(base_row(), answer(prevalence=0.65))
    assert le.agrees(base_row(), answer(n_affected=12, n_assessed=20))
    assert not le.agrees(base_row(), answer(prevalence=0.4))
    assert not le.agrees(base_row(), answer(found=False, prevalence=0.6))
    assert le.agrees(age, answer(age_low_years=3, age_high_years=10))
    assert le.agrees(age, answer(age_low_years=None, age_high_years=5))
    assert not le.agrees(age, answer(age_low_years=10, age_high_years=12))
    assert answer(age_low_years=1, age_high_years=3)["point"] == "2.0"
