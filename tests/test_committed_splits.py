"""Runs in CI without raw data: committed split files must match their content hash."""

import json

import pytest

from diagnostic_ar_training import SPLITS_DIR, splits
from diagnostic_ar_training.lineage.hashing import sha256_json

FROZEN = sorted(p.stem for p in SPLITS_DIR.glob("*.json"))
PARTS = {"r1": {p.value for p in splits.Part}, "s3": {"dev", "test"}}


@pytest.mark.parametrize("split_id", FROZEN)
def test_committed_split_is_untouched(split_id):
    body = json.loads((SPLITS_DIR / f"{split_id}.json").read_text())
    content = {k: v for k, v in body.items() if k != "content_sha256"}
    assert sha256_json(content) == body["content_sha256"], "edited by hand"
    assert set(body["case_ids"]) == PARTS[split_id.split("-")[0]]
    ids = [i for part in body["case_ids"].values() for i in part]
    assert len(ids) == len(set(ids)), "a case appears in two parts"


def test_r1_v1_is_the_split_the_protocol_names():
    assert splits.load_frozen("r1-v1")["content_sha256"].startswith("b007aa17")
