import dataclasses

import numpy as np
import pytest
from test_rerank import KB, ONTO, K, disease

from diagnostic_ar_training.cohorts.schema import Case, Sex
from diagnostic_ar_training.eval import interactive
from diagnostic_ar_training.knowledge import annotation_split


def test_public_case_cannot_carry_the_answer():
    fields = {f.name for f in dataclasses.fields(interactive.PublicCase)}
    assert fields == {"case_id", "present", "sex", "age_years", "onset_years"}
    case = Case(
        case_id="c", cohort="s3", gene="XLR", present=("HP:0001263",), sex=Sex.MALE, disease_ids=("OMIM:1",)
    )
    public = interactive.PublicCase.of(case)
    assert not hasattr(public, "gene") and not hasattr(public, "disease_ids")


def test_questions_target_what_separates_the_candidates_and_skip_what_was_reported():
    genes = ("XLR", "ADULT", "NOONSET")
    public = interactive.PublicCase("c", ("HP:0001263",))
    qs = interactive.choose_questions(public, np.array([0.5, 0.3, 0.2]), genes, K, ONTO, n_questions=3)
    assert qs and "HP:0001263" not in qs
    assert "HP:0002373" in qs or "HP:0000028" in qs  # XLR's features split XLR from the others
    again = interactive.choose_questions(public, np.array([0.5, 0.3, 0.2]), genes, K, ONTO, n_questions=3)
    assert qs == again


def test_answers_come_from_the_truth_including_through_descendants():
    truth = frozenset({"HP:0002373"})  # febrile seizure
    assert interactive.answer("HP:0001250", truth, ONTO)  # seizure: yes, via the child
    assert not interactive.answer("HP:0000028", truth, ONTO)
    case = Case(case_id="c", cohort="s3", gene="XLR", present=("HP:0001263",))
    after = interactive.interview(case, truth, ["HP:0001250", "HP:0000028"], ONTO)
    assert after.present == ("HP:0001250", "HP:0001263") and after.excluded == ("HP:0000028",)


def test_annotation_split_is_deterministic_positive_only_and_about_the_right_size(tmp_path):
    header = "\t".join(
        "database_id disease_name qualifier hpo_id reference evidence onset frequency sex modifier aspect "
        "biocuration".split()
    )
    rows = [f"OMIM:{d}\tn\t\tHP:{t:07d}\tPMID:1\tPCS\t\t\t\t\tP\tx" for d in range(40) for t in range(50)]
    rows += [
        "OMIM:1\tn\tNOT\tHP:9999999\tPMID:1\tPCS\t\t\t\t\tP\tx",
        "OMIM:1\tn\t\tHP:0001417\tx\tx\t\t\t\t\tI\tx",
    ]
    path = tmp_path / "phenotype.hpoa"
    path.write_text("#version: t\n" + header + "\n" + "\n".join(rows) + "\n")
    a = annotation_split.split(path, 0.3, "s")
    assert a == annotation_split.split(path, 0.3, "s") != annotation_split.split(path, 0.3, "other salt")
    assert 0.25 < len(a) / 2000 < 0.35
    assert ("OMIM:1", "HP:9999999") not in a and ("OMIM:1", "HP:0001417") not in a
    annotation_split.write(a, tmp_path / "h.tsv")
    assert annotation_split.read(tmp_path / "h.tsv") == set(a)


def test_kb_built_without_half_b_never_contains_a_held_out_annotation(tmp_path):
    from test_kb import _args, _write_fixtures

    from diagnostic_ar_training.ontology import Ontology
    from diagnostic_ar_training.rerank import kb

    onto = Ontology.from_json(_write_fixtures(tmp_path))
    held = {("OMIM:1", "HP:0000028")}
    built, stats = kb.build(onto, *_args(tmp_path), masked_pmids=set(), drop_annotations=held)
    assert "HP:0000028" not in built["diseases"]["OMIM:1"]["phenotypes"]
    assert stats["rows_dropped_heldout_annotation"] == 1
    assert KB and disease  # shared fixtures imported for the questioner tests


def test_interview_is_the_only_path_from_truth_to_system_inputs():
    import inspect

    src = inspect.getsource(interactive.choose_questions)
    assert "true_present" not in src and ".gene" not in src.replace("genes", "")


def _write_dataset(path, n=40):
    import gzip as gz
    import json as js

    with gz.open(path, "wt") as f:
        for i in range(n):
            f.write(js.dumps({"case_id": f"c{i}", "gene": "XLR", "present": ["HP:0001263"],
                              "true_present": ["HP:0001263", "HP:0002373"], "excluded": ["HP:0000028"],
                              "sex": "male", "age_years": 3.0, "onset_years": None}) + "\n")  # fmt: skip


def test_s3_cases_carry_no_truth_and_drop_the_simulators_own_negatives(tmp_path):
    from diagnostic_ar_training.cohorts import s3

    _write_dataset(tmp_path / "d.jsonl.gz")
    case, truth = s3.read_dataset(tmp_path / "d.jsonl.gz", "s3-t")[0]
    assert case.excluded == () and case.present == ("HP:0001263",)
    assert truth == {"HP:0001263", "HP:0002373"} and "HP:0002373" not in case.present
    assert case.case_id == "s3-t:c0"


def test_s3_split_is_frozen_hash_checked_and_its_test_part_sealed(tmp_path, monkeypatch, docs, clean_tree):
    from diagnostic_ar_training.cohorts import s3
    from diagnostic_ar_training.lineage.registry import LineageError

    monkeypatch.setattr(s3, "SPLITS_DIR", tmp_path)
    data = tmp_path / "d.jsonl.gz"
    _write_dataset(data)
    body = s3.freeze("s3-t", data, "0" * 64)
    assert sum(body["counts"].values()) == 40 and min(body["counts"].values()) > 5
    assert s3.freeze("s3-t", data, "0" * 64)["content_sha256"] == body["content_sha256"]
    assert len(s3.load_part("s3-t", "dev", data)) == body["counts"]["dev"]
    with pytest.raises(LineageError):
        s3.load_part("s3-t", "test", data)
    (docs / "experiments" / "EXP-S3-001.md").write_text("# pre-registered")
    assert (
        len(s3.load_part("s3-t", "test", data, exp_id="EXP-S3-001", reason="gate")) == body["counts"]["test"]
    )
    _write_dataset(data, n=41)
    with pytest.raises(LineageError):
        s3.load_part("s3-t", "dev", data)


def test_interviewed_cases_round_trip_without_truth(tmp_path):
    import gzip
    import json

    from diagnostic_ar_training.eval import s3_run
    from diagnostic_ar_training.systems import Scored

    class E0:
        genes = ("XLR", "ADULT", "NOONSET")

        def score(self, case):
            return Scored(np.array([0.5, 0.3, 0.2]), {})

    case = Case(case_id="s3-v1:c", cohort="s3-v1", gene="XLR", present=("HP:0001263",), sex=Sex.MALE)
    truth = frozenset({"HP:0002373"})
    [interview] = s3_run.interview_cases([(case, truth)], E0(), K, ONTO, n_candidates=3, n_questions=3)
    expected = interactive.interview(case, truth, interview.questions, ONTO)
    assert interview.questions and interview.after == expected
    assert interview.yes == len(set(expected.present) - set(case.present))
    path = tmp_path / "interviews.jsonl.gz"
    s3_run.write_interviews(path, [interview])
    assert s3_run.read_interviews(path) == [expected]
    with gzip.open(path, "rt") as handle:
        assert set(json.loads(handle.readline())) == {"questions", "case"}
