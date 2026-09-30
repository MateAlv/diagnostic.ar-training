import json

import pytest

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.knowledge import recount as RC
from diagnostic_ar_training.ontology import Ontology

OBO = "http://purl.obolibrary.org/obo/HP_"
HP = {
    "0000001": [],
    "0000118": ["0000001"],
    "0000707": ["0000118"],  # nervous system
    "0001250": ["0000707"],  # seizure
    "0002069": ["0001250"],  # a kind of seizure
    "0000478": ["0000118"],  # eye
    "0000505": ["0000478"],  # visual impairment
}


@pytest.fixture
def onto(tmp_path):
    nodes = [{"id": OBO + c, "lbl": c} for c in HP]
    edges = [{"sub": OBO + c, "pred": "is_a", "obj": OBO + p} for c, ps in HP.items() for p in ps]
    (tmp_path / "hp.json").write_text(json.dumps({"graphs": [{"nodes": nodes, "edges": edges}]}))
    return Ontology.from_json(tmp_path / "hp.json")


def row(disease, term, ref="PMID:1", aspect="P", freq="", qualifier="", sex="", onset=""):
    values = [disease, "d", qualifier, term, ref, "PCS", onset, freq, sex, "", aspect, "cur"]
    return dict(zip(RC.COLUMNS, values, strict=True))


def case(i, present=(), excluded=(), disease="OMIM:1", onsets=()):
    return Case(
        case_id=f"c{i}",
        cohort="t",
        gene="G",
        present=tuple(present) or ("HP:0000505",),
        excluded=tuple(excluded),
        disease_ids=(disease,),
        feature_onsets=tuple(onsets),
    )


def test_counts_descendants_as_present_and_ancestor_exclusions_as_excluded(onto):
    patients = RC.patients_by_disease(
        [
            case(1, ["HP:0002069"]),  # descendant present
            case(2, ["HP:0001250"]),  # term present
            case(3, excluded=["HP:0000707"]),  # ancestor excluded: the term is excluded too
            case(4, excluded=["HP:0002069"]),  # descendant excluded says nothing about the term
            case(5),  # not mentioned
        ],
        onto,
        [],
    )
    assert RC.count("HP:0001250", patients["OMIM:1"], onto) == (2, 3)


def test_rows_citing_heldout_pmids_are_recounted_once_and_others_kept(onto):
    patients = RC.patients_by_disease(
        [case(i, ["HP:0001250"]) for i in range(3)] + [case(9, excluded=["HP:0001250"])], onto, []
    )
    rows = [
        row("OMIM:1", "HP:0001250", "PMID:9;PMID:1", freq="91/182"),  # one held-out PMID of two
        row("OMIM:1", "HP:0001250", "PMID:9", freq="HP:0040281"),  # same pair, held out too
        row("OMIM:1", "HP:0000505", "PMID:1", freq="1/1"),  # untouched
        row("OMIM:1", "HP:0000006", "PMID:9", aspect="I"),  # other aspect citing held-out: dropped
    ]
    out, stats = RC.recount(rows, {"PMID:9"}, patients, onto)
    assert [r["hpo_id"] for r in out] == ["HP:0001250", "HP:0000505"]
    new = out[0]
    assert new["frequency"] == "3/4" and new["reference"] == "R1-TRAIN:r1-v1" and new["evidence"] == "PCS"
    assert new["qualifier"] == "" and out[1] is rows[2]
    assert stats["per_disease"]["OMIM:1"] == {"kept": 1, "recounted": 2, "recount_rows": 1, "dropped": 1}
    assert stats["totals"]["rows_recounted"] == 2 and stats["totals"]["rows_dropped_other_aspect"] == 1


def test_too_few_patients_drops_the_row(onto):
    patients = RC.patients_by_disease([case(1, ["HP:0001250"]), case(2)], onto, [])
    out, stats = RC.recount([row("OMIM:1", "HP:0001250", "PMID:9")], {"PMID:9"}, patients, onto)
    assert out == [] and stats["totals"]["rows_dropped_too_few_patients"] == 1


def test_orpha_rows_take_patients_of_exactly_aligned_omim_ids(onto):
    patients = RC.patients_by_disease(
        [case(i, ["HP:0001250"]) for i in range(3)], onto, [("ORPHA:10", "OMIM:1")]
    )
    out, _ = RC.recount([row("ORPHA:10", "HP:0001250", "PMID:9")], {"PMID:9"}, patients, onto)
    assert out[0]["frequency"] == "3/3" and out[0]["database_id"] == "ORPHA:10"


def test_negated_rows_are_recounted_as_counts(onto):
    patients = RC.patients_by_disease([case(i, excluded=["HP:0001250"]) for i in range(3)], onto, [])
    out, _ = RC.recount([row("OMIM:1", "HP:0001250", "PMID:9", qualifier="NOT")], {"PMID:9"}, patients, onto)
    assert out[0]["frequency"] == "0/3" and out[0]["qualifier"] == ""


def test_recount_onset_is_the_class_of_the_median_feature_onset(onto):
    cases = [case(i, ["HP:0002069"], onsets=[("HP:0002069", age, None)]) for i, age in enumerate((2, 3, 30))]
    patients = RC.patients_by_disease(cases, onto, [])
    out, _ = RC.recount([row("OMIM:1", "HP:0001250", "PMID:9")], {"PMID:9"}, patients, onto)
    assert out[0]["onset"] == "HP:0011463"  # childhood: median 3 years
    onsets = RC.feature_onsets(out, patients, onto)
    assert onsets[0][:3] == ("OMIM:1", "HP:0001250", 3) and onsets[0][4] == 3


def test_onset_classes():
    assert [RC.onset_class(y) for y in (-0.2, 0.0, 0.01, 0.5, 3, 10, 20, 50, 70)] == [
        "HP:0030674", "HP:0003577", "HP:0003623", "HP:0003593", "HP:0011463",
        "HP:0003621", "HP:0011462", "HP:0003596", "HP:0003584",
    ]  # fmt: skip


def test_hpoa_round_trip_keeps_comments_and_header(tmp_path):
    path = tmp_path / "p.hpoa"
    rows = [row("OMIM:1", "HP:0001250")]
    RC.write_hpoa(path, ["#version: x\n"], rows)
    comments, back = RC.read_hpoa(path)
    assert comments == ["#version: x\n"] and back == rows


def test_count_frequencies_pool_count_rows_only(onto):
    rows = [
        row("OMIM:1", "HP:0001250", freq="1/4"),
        row("OMIM:1", "HP:0001250", freq="3/4"),  # pooled with the row above: 4/8
        row("OMIM:1", "HP:0000505", freq="HP:0040281"),  # a category, not a count
        row("OMIM:2", "HP:0000505", freq="9/10", qualifier="NOT"),
        row("OMIM:2", "HP:0001250", freq="1/1"),
    ]
    assert sorted(RC.count_frequencies(rows, onto)) == [0.5, 1.0]
