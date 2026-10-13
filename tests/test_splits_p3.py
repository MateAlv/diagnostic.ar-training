"""Phase 3 union split (ADR-0019): p3-v1 from p2-v1 and p2-fresh-v1. Synthetic data only."""

import pytest

from diagnostic_ar_training import splits
from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.lineage import registry
from diagnostic_ar_training.lineage.hashing import sha256_json
from diagnostic_ar_training.lineage.registry import LineageError, Purpose, Role, Source
from diagnostic_ar_training.splits import Part


def case(cid, pmids):
    return Case(case_id=cid, cohort="t", gene=f"G{cid}", present=("HP:1",), pmids=tuple(pmids))


COHORT = [case(f"c{i}", [f"PMID:{i // 3}"]) for i in range(300)] + [case(f"np{i}", []) for i in range(20)]
FRESH = [case(f"f{i}", [f"PMID:{500 + i // 2}"]) for i in range(30)]
# E0's knowledge cites PMID:0..49 and one fresh publication.
E0_KNOWLEDGE_CITED = {f"PMID:{i}" for i in range(50)} | {"PMID:500"}


def fake_source(name, role=Role.KNOWLEDGE):
    return Source(name, role, "v", "f", "https://x", "0" * 64)


SOURCES = {
    "phenopacket_store": fake_source("phenopacket_store", Role.COHORT),
    "phenopacket_store_0_1_25": fake_source("phenopacket_store_0_1_25"),
    "hpo_annotations_2025_11_24": fake_source("hpo_annotations_2025_11_24"),
    "hpo_annotations_2025_03_03": fake_source("hpo_annotations_2025_03_03"),
    "hpo_annotations": fake_source("hpo_annotations"),
}


def write_fresh(tmp_path, ids):
    body = {"split_id": "p2-fresh-v1", "case_ids": {"vault": sorted(ids)}, "cohort_source": "snap"}
    body["content_sha256"] = sha256_json(body)
    (tmp_path / "p2-fresh-v1.json").write_text(__import__("json").dumps(body))


@pytest.fixture
def cohort(tmp_path, monkeypatch, docs):
    fresh = list(FRESH)

    def all_cases(spec):
        if spec.members:
            return splits._union_cases(spec)
        return (list(fresh), {}) if spec.fresh else (list(COHORT), {})

    monkeypatch.setattr(splits, "SPLITS_DIR", tmp_path)
    monkeypatch.setattr(splits, "_all_cases", all_cases)
    monkeypatch.setattr(splits, "_e0_seen", lambda: ({"PMID:0"}, {"PMID:1"}))
    monkeypatch.setattr(splits, "_e0_knowledge_cited", lambda: set(E0_KNOWLEDGE_CITED))
    monkeypatch.setattr(splits, "load_sources", lambda: dict(SOURCES))
    monkeypatch.setattr(registry, "load_sources", lambda: dict(SOURCES))
    splits.freeze("r1-v1")
    splits.freeze("p2-v1")
    write_fresh(tmp_path, [c.case_id for c in FRESH])
    return tmp_path, fresh


def parts_of(body):
    return {cid: Part(p) for p, ids in body["case_ids"].items() for cid in ids}


def test_p3_trains_on_p2_development_and_seals_everything_else(cohort):
    p2 = parts_of(splits.load_frozen("p2-v1"))
    p3 = parts_of(splits.freeze("p3-v1"))
    for cid, part in p2.items():
        assert p3[cid] == (Part.TRAIN if part in (Part.TRAIN, Part.DEV) else Part.VAULT)
    assert all(p3[c.case_id] == Part.VAULT for c in FRESH)
    assert set(p3) == set(p2) | {c.case_id for c in FRESH}


def test_p3_records_e0_knowledge_status_per_group(cohort):
    body = splits.freeze("p3-v1")
    status = body["group_status"]
    assert status["PMID:0"] == splits.CITED_BY_E0_KNOWLEDGE
    assert status["PMID:60"] == splits.UNCITED_BY_E0_KNOWLEDGE
    assert status["PMID:500"] == splits.CITED_BY_E0_KNOWLEDGE
    assert status["PMID:501"] == splits.UNCITED_BY_E0_KNOWLEDGE
    assert status["case:np0"] == splits.NO_PMID
    counted = sum(v["cases"] for part in body["stats"].values() for v in part["by_e0_knowledge"].values())
    assert counted == len(COHORT) + len(FRESH)
    assert body["stats"]["vault"]["from_member_part"]["p2-fresh-v1/vault"] == len(FRESH)
    assert body["sealed_parts"] == ["vault"]


def test_p3_refreeze_reproduces_and_detects_drift(cohort, monkeypatch):
    first = splits.freeze("p3-v1")
    assert splits.freeze("p3-v1")["content_sha256"] == first["content_sha256"]
    monkeypatch.setattr(splits, "_e0_knowledge_cited", lambda: set())
    with pytest.raises(LineageError, match="frozen"):
        splits.freeze("p3-v1")


def test_p3_refuses_a_group_that_straddles_parts(cohort):
    _, fresh = cohort
    train_pmid = next(
        c.pmids[0]
        for c in COHORT
        if c.case_id in splits.load_frozen("p2-v1")["case_ids"]["train"] and c.pmids
    )
    fresh.append(case("link", [train_pmid]))
    write_fresh(cohort[0], [c.case_id for c in fresh])
    with pytest.raises(LineageError, match="straddles"):
        splits.freeze("p3-v1")


def test_p3_train_feeds_training_and_the_vault_does_not(cohort):
    splits.freeze("p3-v1")
    assert splits.load_part("p3-v1", Part.TRAIN, Purpose.TRAIN)
    with pytest.raises(LineageError):
        splits.load_part("p3-v1", Part.VAULT, Purpose.TRAIN)


def test_p3_vault_needs_a_preregistered_read_and_opens_once(cohort, clean_tree, monkeypatch):
    tmp_path, _ = cohort
    splits.freeze("p3-v1")
    (tmp_path / "experiments" / "EXP-P-010.md").write_text("# pre-registered")
    with pytest.raises(LineageError, match="sealed"):
        splits.load_part("p3-v1", Part.VAULT, Purpose.EVAL)
    with pytest.raises(LineageError, match="DXT_SEALED_READ=EXP-P-010"):
        splits.load_part("p3-v1", Part.VAULT, Purpose.EVAL, exp_id="EXP-P-010", reason="v4.0 claim")
    monkeypatch.setenv("DXT_SEALED_READ", "EXP-P-010")
    vault = splits.load_part("p3-v1", Part.VAULT, Purpose.EVAL, exp_id="EXP-P-010", reason="v4.0 claim")
    assert {c.case_id for c in vault} == set(splits.load_frozen("p3-v1")["case_ids"]["vault"])
    with pytest.raises(LineageError, match="already opened"):
        splits.load_part("p3-v1", Part.VAULT, Purpose.EVAL, exp_id="EXP-P-010", reason="again")


def test_p3_masks_every_sealed_publication(cohort):
    splits.freeze("p3-v1")
    vault = set(splits.load_frozen("p3-v1")["case_ids"]["vault"])
    expected = {p for c in COHORT + FRESH if c.case_id in vault for p in c.pmids}
    assert splits.heldout_pmids("p3-v1") == expected
