"""Interviewed simulated training cases (ADR-0010 §2): selection, deterministic file, contamination keys."""

import random

import pytest

pytest.importorskip("torch")

from diagnostic_ar_training.gnn import data, interviewed  # noqa: E402


def rows():
    genes, splits = ("G0", "G1"), ("train", "val", "test")
    return [(split, gene, f"{gene}-{split}-{k}") for gene in genes for split in splits for k in range(30)]


def test_selection_keeps_the_smallest_salted_keys_per_gene_whatever_the_input_order():
    per_gene = {"train": 20, "val": 5}
    chosen = interviewed.select(rows(), per_gene, "salt")
    shuffled = rows()
    random.Random(1).shuffle(shuffled)
    assert interviewed.select(shuffled, per_gene, "salt") == chosen
    assert set(chosen) == {"train", "val"}
    for split, k in per_gene.items():
        for gene in ("G0", "G1"):
            mine = [i for i in chosen[split] if i.startswith(f"{gene}-")]
            candidates = sorted((interviewed.selection_key("salt", i), i) for s, g, i in rows()
                                if s == split and g == gene)  # fmt: skip
            assert sorted(mine) == sorted(i for _, i in candidates[:k])
    assert interviewed.select(rows(), per_gene, "other salt") != chosen


def test_genes_with_fewer_cases_than_asked_keep_them_all():
    few = [("val", "G0", "a"), ("val", "G0", "b")]
    assert interviewed.select(few, {"val": 5}, "salt") == {"val": ["a", "b"]}


def test_the_initial_presentation_drops_the_simulators_own_negatives():
    record = {"case_id": "c", "gene": "G0", "present": ["B", "A", "A"], "excluded": ["X"], "sex": "male",
              "age_years": 3.0, "onset_years": 1.0}  # fmt: skip
    case = interviewed.initial_case(record)
    assert case.present == ("A", "B") and case.excluded == ()
    assert (case.sex, case.age_years, case.onset_years) == ("male", 3.0, 1.0)


def example_rows():
    return [
        {
            "case_id": f"c{i}",
            "gene": "G0",
            "gene_index": 0,
            "split": "train" if i else "val",
            "present": ["A", "B"][: i + 1],
            "excluded": ["X"],
            "sex": "unknown",
            "age_years": None,
            "onset_years": None,
            "questions": ["X"],
            "yes": 0,
            "no": 1,
        }
        for i in range(2)
    ]


def test_the_file_is_byte_deterministic_and_reads_like_a_simulator_export(tmp_path):
    a, b = tmp_path / "a.jsonl.gz", tmp_path / "b.jsonl.gz"
    interviewed.write_rows(a, example_rows())
    interviewed.write_rows(b, example_rows())
    assert a.read_bytes() == b.read_bytes()
    splits, counts = data.read_export(a, splits=("train", "val"))
    assert counts["kept"] == {"train": 1, "val": 1}
    assert splits["train"][0].present == ("A", "B") and splits["train"][0].excluded == ("X",)


def test_contamination_matches_gene_case_insensitively_and_the_whole_present_set():
    keys = {data.overlap_key("g0", ["A"])}
    assert interviewed.contamination(example_rows(), {"cohort": keys}) == {"cohort": ["c0"]}
