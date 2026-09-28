"""Runs in CI without raw data: committed split files must match their content hash."""

import pytest

from diagnostic_ar_training import SPLITS_DIR, splits

FROZEN = sorted(p.stem for p in SPLITS_DIR.glob("*.json"))


@pytest.mark.parametrize("split_id", FROZEN)
def test_committed_split_is_untouched(split_id):
    body = splits.load_frozen(split_id)
    assert set(body["case_ids"]) == {p.value for p in splits.Part}
    ids = [i for part in body["case_ids"].values() for i in part]
    assert len(ids) == len(set(ids)), "a case appears in two parts"


def test_r1_v1_is_the_split_the_protocol_names():
    assert splits.load_frozen("r1-v1")["content_sha256"].startswith("b007aa17")
