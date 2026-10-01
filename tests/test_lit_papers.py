from diagnostic_ar_training.knowledge import lit_papers as lp


def rec(title, abstract="", pub_types=("research-article", "Journal Article"), pmid="1"):
    return {
        "pmid": pmid,
        "title": title,
        "abstractText": abstract,
        "pubTypeList": {"pubType": list(pub_types)},
    }


def test_unit_terms_split_units_and_groups():
    units, groups = lp.unit_terms(
        "Natural history of GACI",
        "Generalized arterial calcification of infancy (GACI) is rare. "
        "Fatty acid oxidation disorders (FAODs) and cerebral small vessel diseases (CSVD) are groups.",
        ["ENPP1"],
    )
    assert units == {"ENPP1", "GACI"}
    assert groups == {"FAODs", "CSVD"}


def test_per_unit_count_patterns():
    gene = lp.per_unit_counts(
        "Phenotype of ENPP1 deficiency", "We studied 84 ENPP1-deficient individuals.", ["ENPP1"]
    )
    assert gene == [(84, "count_unit_noun")]
    with_unit = lp.per_unit_counts(
        "Natural history",
        "Alpha disease (ALD) is rare. In all, 65 records for patients with ALD were reviewed.",
        ["GENEA"],
    )
    assert with_unit == [(65, "count_noun_with_unit")]
    disease_noun = lp.per_unit_counts(
        "Outcomes", "We followed 40 children with Stargardt disease.", ["ABCA4"]
    )
    assert disease_noun == [(40, "count_noun_with_unit")]
    cohort = lp.per_unit_counts("Outcomes", "In the ENPP1 data set (n = 84) rickets was frequent.", ["ENPP1"])
    assert cohort == [(84, "unit_cohort_of_n")]
    bare = lp.per_unit_counts(
        "Newborn screening for MCAD deficiency", "Data were evaluated in 45 patients.", []
    )
    assert bare == [(45, "bare_count_single_unit_title")]
    assert lp.per_unit_counts("Outcomes", "Data were evaluated in 45 patients.", []) == []
    group = lp.per_unit_counts(
        "Follow-up",
        "Fatty acid oxidation disorders (FAODs) are many. We diagnosed 30 patients with FAODs.",
        [],
    )
    assert group == []
    assert lp.per_unit_counts("Outcomes", "We studied 12 patients with Stargardt disease.", ["ABCA4"]) == []
    assert (
        lp.per_unit_counts("Outcomes", "We studied 40 patients with suspected Stargardt disease.", []) == []
    )
    assert lp.per_unit_counts("Outcomes", "Since 1999 patients with Alpha syndrome were seen.", []) == []


def test_rescreen_reasons():
    ok = "Generalized arterial calcification of infancy (GACI) is rare. We reviewed 247 patients with GACI."
    assert lp.rescreen(rec("Natural history of ENPP1 deficiency", ok), ["ENPP1"]) == (
        "pass",
        "count_noun_with_unit",
        247,
    )
    cases = [
        (rec("Alpha", ok, ("Case Reports",)), "pub_type:case_report"),
        (rec("Alpha", ok, ("Clinical Trial", "Journal Article")), "pub_type:trial"),
        (rec("Role of molecular testing in ichthyosis", ok), "title:screening_method"),
        (rec("Exome sequencing in a cohort of epilepsy", ok), "title:screening_method"),
        (rec("Structure of the ABCD1 variant database", ok), "title:database"),
        (rec("Penetrance of HCM in sarcomere mutation carriers", ok), "title:carriers"),
        (rec("Novel ABCC6 variants in PXE", ok), "title:variant_level"),
        (rec("Burosumab in X-linked hypophosphatemia", ok), "title:treatment"),
        (rec("Fatty acid oxidation disorders in the screening era", ok), "title:screening_method"),
        (
            rec("Mitochondrial fatty acid oxidation disorders: a single centre experience", ok),
            "title:disease_group",
        ),
        (rec("Clinical spectrum of 14 cases with G6PC3 variants", ok), "title:n_lt_20"),
        (
            rec("Alpha", ok + " We found 93 unrelated individuals who tested negative for ENG."),
            "abstract:diagnostic_yield",
        ),
        (rec("Alpha", ok + " Multivariate analysis gave an odds ratio of 8.4."), "abstract:association"),
        (rec("Alpha", ok + " Incomplete penetrance was observed."), "abstract:penetrance"),
        (
            rec("Alpha", ok + " Nine patients (5.7%) carried pathogenic heterozygous variants."),
            "abstract:few_positives",
        ),
        (rec("Alpha", "We studied many patients."), "no_per_unit_n_ge_20"),
    ]
    for record, reason in cases:
        assert lp.rescreen(record, ["ENPP1"])[:2] == ("fail", reason), (record["title"], reason)
    many = ok + " Pathogenic variants were found in 25 patients (40%) and carried by others."
    assert lp.rescreen(rec("Natural history of ENPP1 deficiency", many), ["ENPP1"])[0] == "pass"
    newborn = "We evaluated MCADD patients detected by newborn screening, in 45 patients."
    assert lp.rescreen(rec("Newborn screening for MCAD deficiency", newborn), ["ACADM"])[0] == "pass"


def test_rescreen_rows_and_confusion():
    good = "We reviewed 247 patients with ENPP1 deficiency."
    papers = [
        {
            "pmid": p,
            "pmcid": "",
            "licence": "cc by",
            "n_stated": "",
            "genes": "ENPP1",
            "weak_genes": "",
            "title": t,
        }
        for p, t in [
            ("1", "Natural history of ENPP1 deficiency"),
            ("2", "ENPP1 variant database"),
            ("3", "Alpha"),
        ]
    ]
    records = {
        "1": rec(papers[0]["title"], good),
        "2": rec(papers[1]["title"], good),
        "3": rec("Natural history of ENPP1 deficiency", good),
    }
    rows = lp.rescreen_rows(papers, records, {"1": ("P001", "extracted"), "2": ("P001", "not_cohort")})
    assert [r["status"] for r in rows] == ["pass", "fail", "pass"]
    assert [r["in_subset"] for r in rows] == [False, False, True]
    c = lp.confusion(rows)
    assert (
        c["papers"],
        c["qualified_pass"],
        c["dead_end_fail"],
        c["qualified_fail"],
        c["dead_end_pass"],
    ) == (
        2,
        1,
        1,
        0,
        0,
    )
    assert c["per_paper"]["PMID:2"] == "not_cohort -> fail (title:database)"
