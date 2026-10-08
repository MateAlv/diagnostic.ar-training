"""Runs in CI without raw data: committed split files must match their content hash."""

import json

import pytest

from diagnostic_ar_training import SPLITS_DIR, splits
from diagnostic_ar_training.lineage import registry
from diagnostic_ar_training.lineage.hashing import sha256_json

FROZEN = sorted(p.stem for p in SPLITS_DIR.glob("*.json"))
ALL_PARTS = {p.value for p in splits.Part}
PARTS = {"r1-v1": ALL_PARTS, "p2-v1": ALL_PARTS, "p2-fresh-v1": {"vault"}}


def expected_parts(split_id):
    return {"dev", "test"} if split_id.startswith("s3-") else PARTS[split_id]


@pytest.mark.parametrize("split_id", FROZEN)
def test_committed_split_is_untouched(split_id):
    body = json.loads((SPLITS_DIR / f"{split_id}.json").read_text())
    content = {k: v for k, v in body.items() if k != "content_sha256"}
    assert sha256_json(content) == body["content_sha256"], "edited by hand"
    assert set(body["case_ids"]) == expected_parts(split_id)
    ids = [i for part in body["case_ids"].values() for i in part]
    assert len(ids) == len(set(ids)), "a case appears in two parts"


def test_r1_v1_is_the_split_the_protocol_names():
    assert splits.load_frozen("r1-v1")["content_sha256"].startswith("b007aa17")


def test_p2_v1_is_the_split_phase_2_names():
    assert splits.load_frozen("p2-v1")["content_sha256"].startswith("b1ccdada")


def test_p2_fresh_v1_is_the_split_phase_2_names():
    assert splits.load_frozen("p2-fresh-v1")["content_sha256"].startswith("2a9438d0")


def test_p2_v1_is_derived_from_r1_v1():
    r1, p2 = splits.load_frozen("r1-v1"), splits.load_frozen("p2-v1")
    assert p2["inputs"][0] == {"id": "split:r1-v1", "sha256": r1["content_sha256"]}
    for part in ("train", "dev"):
        assert p2["case_ids"][part] == r1["case_ids"][part]
    sealed = sorted(r1["case_ids"]["test"] + r1["case_ids"]["vault"])
    assert sorted(p2["case_ids"]["test"] + p2["case_ids"]["vault"]) == sealed
    assert p2["stats"]["test"]["post_e0_publications"] == 0
    assert p2["stats"]["vault"]["post_e0_publications"] == p2["stats"]["vault"]["publications"]


@pytest.mark.skipif(
    not registry.verify(registry.load_sources()["phenopacket_store"]), reason="needs the raw cohort"
)
def test_p2_v1_masks_the_same_pmids_as_r1_v1():
    committed = set((SPLITS_DIR / "r1-v1.heldout-pmids.txt").read_text().split())
    assert splits.heldout_pmids("p2-v1") == splits.heldout_pmids("r1-v1") == committed
