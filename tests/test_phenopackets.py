from collections import Counter

import pytest

from diagnostic_ar_training.cohorts.phenopackets import iso_duration_years, parse_packet
from diagnostic_ar_training.cohorts.schema import Sex


def packet(genes=("ESAM",), features=(("HP:1", False),), **extra):
    return {
        "id": "p1",
        "subject": extra.get("subject", {"sex": "FEMALE"}),
        "phenotypicFeatures": [
            {"type": {"id": t}, **({"excluded": True} if ex else {})} for t, ex in features
        ],
        "interpretations": [
            {
                "diagnosis": {
                    "disease": {"id": "OMIM:1"},
                    "genomicInterpretations": [
                        {
                            "interpretationStatus": "CAUSATIVE",
                            "variantInterpretation": {"variationDescriptor": {"geneContext": {"symbol": g}}},
                        }
                        for g in genes
                    ],
                }
            }
        ],
        "diseases": extra.get("diseases", []),
        "metaData": {"externalReferences": [{"id": "PMID:9"}, {"id": "DOI:x"}]},
    }


@pytest.mark.parametrize(
    "value,years",
    [("P3Y", 3.0), ("P1Y6M", 1.5), ("P6M", 0.5), ("P2W", 14 / 365.25), ("", None), ("P", None)],
)
def test_iso_durations(value, years):
    assert iso_duration_years(value) == (pytest.approx(years) if years is not None else None)


def test_present_excluded_sex_age_onset_and_pmids():
    case = parse_packet(
        packet(
            features=(("HP:1", False), ("HP:2", True)),
            subject={"sex": "MALE", "timeAtLastEncounter": {"age": {"iso8601duration": "P4Y"}}},
            diseases=[{"term": {"id": "OMIM:1"}, "onset": {"ontologyClass": {"id": "HP:0003577"}}}],
        ),
        Counter(),
    )
    assert case.gene == "ESAM"
    assert case.present == ("HP:1",) and case.excluded == ("HP:2",)
    assert case.sex is Sex.MALE and case.age_years == 4.0
    assert case.onset_term == "HP:0003577" and case.onset_years is None
    assert case.pmids == ("PMID:9",)


def test_unknown_sex_is_not_guessed():
    case = parse_packet(packet(subject={"sex": "UNKNOWN_SEX"}), Counter())
    assert case.sex is Sex.UNKNOWN and case.age_years is None


def test_multi_gene_and_empty_cases_are_dropped_and_counted():
    drops = Counter()
    assert parse_packet(packet(genes=("A", "B")), drops) is None
    assert parse_packet(packet(features=(("HP:1", True),)), drops) is None
    assert drops == {"not_single_gene": 1, "no_present_terms": 1}


def test_a_term_both_present_and_excluded_is_removed_from_both():
    drops = Counter()
    case = parse_packet(packet(features=(("HP:1", False), ("HP:2", False), ("HP:2", True))), drops)
    assert case.present == ("HP:1",) and case.excluded == ()
    assert drops["terms_both_present_and_excluded"] == 1
