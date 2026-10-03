import pytest

from diagnostic_ar_training import splits
from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.lineage import registry
from diagnostic_ar_training.lineage.registry import LineageError, Purpose, Role, Source
from diagnostic_ar_training.splits import Part


def case(i, pmids, gene="G"):
    return Case(case_id=f"c{i}", cohort="t", gene=gene, present=(f"HP:{i}",), pmids=tuple(pmids))


CASES = [case(i, [f"PMID:{i // 3}"]) for i in range(300)] + [
    case(900, ["PMID:1", "PMID:50"]),  # links publications 1 and 50 into one component
]


@pytest.fixture
def cohort(tmp_path, monkeypatch, docs):
    monkeypatch.setattr(splits, "SPLITS_DIR", tmp_path)
    monkeypatch.setattr(splits, "_all_cases", lambda spec: (list(CASES), {}))
    fake = Source("phenopacket_store", Role.COHORT, "t", "f", "https://x", "0" * 64)
    monkeypatch.setattr(splits, "load_sources", lambda: {"phenopacket_store": fake})
    monkeypatch.setattr(registry, "load_sources", lambda: {"phenopacket_store": fake})
    return tmp_path


def test_publication_linked_cases_share_a_part(cohort):
    body = splits.freeze("r1-v1")
    part_of = {cid: p for p, ids in body["case_ids"].items() for cid in ids}
    assert part_of["c3"] == part_of["c900"] == part_of["c150"]  # PMID:1 and PMID:50
    assert part_of["c0"] == part_of["c1"] == part_of["c2"]
    assert sum(len(v) for v in body["case_ids"].values()) == len(CASES)


def test_freeze_is_deterministic_and_detects_drift(cohort, monkeypatch):
    first = splits.freeze("r1-v1")
    assert splits.freeze("r1-v1")["content_sha256"] == first["content_sha256"]
    monkeypatch.setattr(splits, "_all_cases", lambda spec: (CASES[:-5], {}))
    with pytest.raises(LineageError):
        splits.freeze("r1-v1")


def test_hand_edited_split_is_rejected(cohort):
    splits.freeze("r1-v1")
    path = cohort / "r1-v1.json"
    path.write_text(path.read_text().replace('"c1"', '"c1x"', 1))
    with pytest.raises(LineageError):
        splits.load_frozen("r1-v1")


def test_dev_cannot_feed_training(cohort):
    splits.freeze("r1-v1")
    with pytest.raises(LineageError):
        splits.load_part("r1-v1", Part.DEV, Purpose.TRAIN)
    assert splits.load_part("r1-v1", Part.TRAIN, Purpose.TRAIN)


def test_sealed_parts_need_a_preregistered_experiment(cohort, clean_tree, monkeypatch):
    monkeypatch.setenv("DXT_SEALED_READ", "EXP-B-001")
    splits.freeze("r1-v1")
    with pytest.raises(LineageError):
        splits.load_part("r1-v1", Part.TEST, Purpose.EVAL)
    with pytest.raises(LineageError):
        splits.load_part("r1-v1", Part.TEST, Purpose.EVAL, exp_id="EXP-B-001", reason="gate")
    (cohort / "experiments" / "EXP-B-001.md").write_text("# pre-registered")
    assert splits.load_part("r1-v1", Part.TEST, Purpose.EVAL, exp_id="EXP-B-001", reason="gate")
    assert "r1-v1/test | EXP-B-001" in (cohort / "TEST_LEDGER.md").read_text()


def test_sealed_parts_refuse_an_uncommitted_registration(cohort, clean_tree, monkeypatch):
    monkeypatch.setenv("DXT_SEALED_READ", "EXP-B-001")
    splits.freeze("r1-v1")
    (cohort / "experiments" / "EXP-B-001.md").write_text("draft")
    with pytest.raises(LineageError):
        splits.load_part("r1-v1", Part.TEST, Purpose.EVAL, exp_id="EXP-B-001", reason="gate")


def test_sealed_parts_refuse_uncommitted_code(cohort, dirty_tree, monkeypatch):
    monkeypatch.setenv("DXT_SEALED_READ", "EXP-B-001")
    splits.freeze("r1-v1")
    (cohort / "experiments" / "EXP-B-001.md").write_text("# pre-registered")
    with pytest.raises(LineageError):
        splits.load_part("r1-v1", Part.TEST, Purpose.EVAL, exp_id="EXP-B-001", reason="gate")


def test_vault_opens_once(cohort, clean_tree, monkeypatch):
    monkeypatch.setenv("DXT_SEALED_READ", "EXP-A-009")
    splits.freeze("r1-v1")
    (cohort / "experiments" / "EXP-A-009.md").write_text("# final")
    splits.load_part("r1-v1", Part.VAULT, Purpose.EVAL, exp_id="EXP-A-009", reason="final")
    with pytest.raises(LineageError):
        splits.load_part("r1-v1", Part.VAULT, Purpose.EVAL, exp_id="EXP-A-009", reason="again")


def test_heldout_pmids_never_include_train_publications(cohort):
    body = splits.freeze("r1-v1")
    train_ids = set(body["case_ids"]["train"])
    train_pmids = {p for c in CASES if c.case_id in train_ids for p in c.pmids}
    assert not train_pmids & splits.heldout_pmids("r1-v1")


def test_all_scope_masks_train_publications_too(cohort):
    body = splits.freeze("r1-v1")
    train_ids = set(body["case_ids"]["train"])
    train_pmids = {p for c in CASES if c.case_id in train_ids for p in c.pmids}
    held, every = splits.mask_pmids("r1-v1", "heldout"), splits.mask_pmids("r1-v1", "all")
    assert every == held | train_pmids and not held & train_pmids


@pytest.fixture
def recorded(monkeypatch):
    calls = []
    monkeypatch.setattr(splits.ledger, "record_access", lambda *a: calls.append(a))
    return calls


@pytest.mark.parametrize("part", [Part.TEST, Part.VAULT])
def test_sealed_read_is_refused_without_the_env_variable(cohort, recorded, part):
    splits.freeze("r1-v1")
    with pytest.raises(LineageError, match="DXT_SEALED_READ=EXP-B-001"):
        splits.load_part("r1-v1", part, Purpose.EVAL, exp_id="EXP-B-001", reason="gate")
    assert recorded == []


def test_sealed_read_is_refused_with_the_wrong_env_value(cohort, recorded, monkeypatch):
    splits.freeze("r1-v1")
    monkeypatch.setenv("DXT_SEALED_READ", "EXP-B-002")
    with pytest.raises(LineageError, match="DXT_SEALED_READ"):
        splits.load_part("r1-v1", Part.TEST, Purpose.EVAL, exp_id="EXP-B-001", reason="gate")
    assert recorded == []


def test_sealed_read_is_allowed_with_the_matching_env_value(cohort, recorded, monkeypatch):
    splits.freeze("r1-v1")
    monkeypatch.setenv("DXT_SEALED_READ", "EXP-B-001")
    assert splits.load_part("r1-v1", Part.TEST, Purpose.EVAL, exp_id="EXP-B-001", reason="gate")
    assert recorded == [("r1-v1", Part.TEST, "EXP-B-001", "gate")]


def test_unsealed_parts_do_not_need_the_env_variable(cohort, recorded):
    splits.freeze("r1-v1")
    assert splits.load_part("r1-v1", Part.DEV, Purpose.EVAL)
    assert recorded == []
