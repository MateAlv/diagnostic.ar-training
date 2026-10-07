"""Phase 2 splits (ADR-0017): p2-v1 derived from r1-v1, and the p2-fresh-v1 builder. Synthetic data only."""

from collections import defaultdict

import pytest

from diagnostic_ar_training import splits
from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.lineage import ledger, registry
from diagnostic_ar_training.lineage.registry import LineageError, Purpose, Role, Source
from diagnostic_ar_training.splits import Part

SALT = splits.SPECS["r1-v1"].salt


def case(cid, pmids):
    return Case(case_id=cid, cohort="t", gene=f"G{cid}", present=("HP:1",), pmids=tuple(pmids))


def _sealed(key):
    return splits._part_of(splits._bucket(SALT, key)) in splits.SEALED


# E0 saw PMID:0..29 in phenopacket-store 0.1.25 and PMID:30..59 cited in HPO 2025-11-24; PMID:60..99 are new.
E0_RELEASE = {f"PMID:{i}" for i in range(30)}
E0_CITED = {f"PMID:{i}" for i in range(30, 60)}
# A post-E0 publication linked by one patient to a publication E0 saw; the pair lands in a sealed r1-v1 part.
SEEN, NEW = next((k, m) for k in range(30) for m in range(60, 100) if _sealed(min(f"PMID:{k}", f"PMID:{m}")))
CASES = (
    [case(f"c{i}", [f"PMID:{i // 3}"]) for i in range(300)]
    + [case("link", [f"PMID:{SEEN}", f"PMID:{NEW}"])]
    + [case(f"np{i}", []) for i in range(40)]
)


def fake_source(name, role=Role.KNOWLEDGE):
    return Source(name, role, "v", "f", "https://x", "0" * 64)


SOURCES = {
    "phenopacket_store": fake_source("phenopacket_store", Role.COHORT),
    "phenopacket_store_0_1_25": fake_source("phenopacket_store_0_1_25"),
    "hpo_annotations_2025_11_24": fake_source("hpo_annotations_2025_11_24"),
    "hpo_annotations": fake_source("hpo_annotations"),
    "snap": fake_source("snap", Role.COHORT),
}


@pytest.fixture
def cohort(tmp_path, monkeypatch, docs):
    monkeypatch.setattr(splits, "SPLITS_DIR", tmp_path)
    monkeypatch.setattr(splits, "_all_cases", lambda spec: (list(CASES), {}))
    monkeypatch.setattr(splits, "_e0_seen", lambda: (set(E0_RELEASE), set(E0_CITED)))
    monkeypatch.setattr(splits, "load_sources", lambda: dict(SOURCES))
    monkeypatch.setattr(registry, "load_sources", lambda: dict(SOURCES))
    splits.freeze("r1-v1")
    return tmp_path


def parts_of(body):
    return {cid: Part(p) for p, ids in body["case_ids"].items() for cid in ids}


def expected_status(cid):
    groups = splits._components(CASES)
    pmids = splits.group_pmids(CASES, groups)[groups[cid]]
    return splits.group_status(pmids, E0_RELEASE, E0_CITED)


def test_group_status_is_post_e0_only_when_e0_saw_none_of_its_pmids():
    assert splits.group_status({"PMID:70", "PMID:71"}, E0_RELEASE, E0_CITED) == splits.POST_E0
    assert splits.group_status({"PMID:70", "PMID:3"}, E0_RELEASE, E0_CITED) == splits.IN_E0_RELEASE
    assert splits.group_status({"PMID:70", "PMID:40"}, E0_RELEASE, E0_CITED) == splits.CITED_E0
    assert splits.group_status({"PMID:3", "PMID:40"}, E0_RELEASE, E0_CITED) == splits.IN_E0_RELEASE
    assert splits.group_status(set(), E0_RELEASE, E0_CITED) == splits.NO_PMID


def test_status_is_decided_for_the_whole_publication_group():
    other_new = next(m for m in range(60, 100) if m != NEW)
    assert expected_status(f"c{3 * other_new}") == splits.POST_E0
    assert expected_status(f"c{3 * NEW}") == splits.IN_E0_RELEASE  # linked to PMID:SEEN by one patient
    assert expected_status("np0") == splits.NO_PMID


def test_p2_keeps_r1_train_and_dev_and_splits_sealed_groups_by_post_e0(cohort):
    r1 = parts_of(splits.load_frozen("r1-v1"))
    p2 = parts_of(splits.freeze("p2-v1"))
    assert set(p2) == set(r1)
    for cid, part in r1.items():
        if part in (Part.TRAIN, Part.DEV):
            assert p2[cid] is part
        else:
            assert p2[cid] is (Part.VAULT if expected_status(cid) == splits.POST_E0 else Part.TEST)
    assert p2["link"] is p2[f"c{3 * NEW}"] is Part.TEST
    assert {p2[f"np{i}"] for i in range(40)} <= {Part.TRAIN, Part.DEV, Part.TEST}
    assert {Part.TEST, Part.VAULT} <= set(p2.values())


def test_a_group_never_straddles_parts(cohort):
    p2 = parts_of(splits.freeze("p2-v1"))
    by_group = defaultdict(set)
    for cid, group in splits.publication_groups("p2-v1").items():
        by_group[group].add(p2[cid])
    assert all(len(parts) == 1 for parts in by_group.values())


def test_p2_records_inputs_rule_and_post_e0_counts(cohort):
    r1 = splits.load_frozen("r1-v1")
    body = splits.freeze("p2-v1")
    assert body["inputs"][0] == {"id": "split:r1-v1", "sha256": r1["content_sha256"]}
    assert [i["id"] for i in body["inputs"][1:]] == [
        "source:phenopacket_store_0_1_25@v",
        "source:hpo_annotations_2025_11_24@v",
    ]
    assert body["sealed_parts"] == ["test", "vault"]
    status = body["group_status_by_parent_part"]
    for part in Part:
        assert sum(status[part.value].values()) == r1["stats"][part.value]["publications"]
    stats = body["stats"]
    assert stats["vault"]["post_e0_publications"] == stats["vault"]["publications"] > 0
    assert stats["test"]["post_e0_publications"] == 0
    assert stats["vault"]["publications"] == status["test"]["post_e0"] + status["vault"]["post_e0"]
    assert stats["train"] == {**r1["stats"]["train"], "post_e0_publications": status["train"]["post_e0"]}


def test_p2_refreeze_reproduces_and_detects_drift(cohort, monkeypatch):
    first = splits.freeze("p2-v1")
    text = (cohort / "p2-v1.json").read_text()
    assert splits.freeze("p2-v1")["content_sha256"] == first["content_sha256"]
    assert (cohort / "p2-v1.json").read_text() == text
    monkeypatch.setattr(splits, "_e0_seen", lambda: (set(E0_RELEASE), set()))
    with pytest.raises(LineageError):
        splits.freeze("p2-v1")


def test_p2_refuses_a_source_that_drifted_from_r1(cohort, monkeypatch):
    monkeypatch.setattr(splits, "_all_cases", lambda spec: (CASES[:-1], {}))
    with pytest.raises(LineageError, match="no longer gives"):
        splits.freeze("p2-v1")


def test_p2_masks_and_groups_equal_r1(cohort):
    splits.freeze("p2-v1")
    assert splits.heldout_pmids("p2-v1") == splits.heldout_pmids("r1-v1")
    assert splits.mask_pmids("p2-v1", "all") == splits.mask_pmids("r1-v1", "all")
    assert splits.publication_groups("p2-v1") == splits.publication_groups("r1-v1")
    assert splits.presentation_keys("p2-v1") == splits.presentation_keys("r1-v1")


def test_p2_dev_cannot_feed_training(cohort):
    splits.freeze("p2-v1")
    with pytest.raises(LineageError):
        splits.load_part("p2-v1", Part.DEV, Purpose.TRAIN)
    assert splits.load_part("p2-v1", Part.TRAIN, Purpose.TRAIN)


@pytest.mark.parametrize("part", [Part.TEST, Part.VAULT])
def test_p2_sealed_read_needs_the_exp_id_and_the_env_variable(cohort, clean_tree, monkeypatch, part):
    splits.freeze("p2-v1")
    (cohort / "experiments" / "EXP-P-001.md").write_text("# pre-registered")
    with pytest.raises(LineageError, match="sealed"):
        splits.load_part("p2-v1", part, Purpose.EVAL)
    with pytest.raises(LineageError, match="DXT_SEALED_READ=EXP-P-001"):
        splits.load_part("p2-v1", part, Purpose.EVAL, exp_id="EXP-P-001", reason="gate")
    assert not (cohort / "TEST_LEDGER.md").exists()
    monkeypatch.setenv("DXT_SEALED_READ", "EXP-P-001")
    assert splits.load_part("p2-v1", part, Purpose.EVAL, exp_id="EXP-P-001", reason="gate")
    assert f"| p2-v1/{part.value} | EXP-P-001 |" in (cohort / "TEST_LEDGER.md").read_text()


def test_p2_vault_opens_once_and_apart_from_r1_vault(cohort, clean_tree, monkeypatch):
    splits.freeze("p2-v1")
    for exp in ("EXP-V-001", "EXP-P-009"):
        (cohort / "experiments" / f"{exp}.md").write_text("# final")
    monkeypatch.setenv("DXT_SEALED_READ", "EXP-V-001")
    splits.load_part("r1-v1", Part.VAULT, Purpose.EVAL, exp_id="EXP-V-001", reason="phase 1 final")
    monkeypatch.setenv("DXT_SEALED_READ", "EXP-P-009")
    vault = splits.load_part("p2-v1", Part.VAULT, Purpose.EVAL, exp_id="EXP-P-009", reason="final check")
    assert {c.case_id for c in vault} == set(splits.load_frozen("p2-v1")["case_ids"]["vault"])
    with pytest.raises(LineageError, match="already opened"):
        splits.load_part("p2-v1", Part.VAULT, Purpose.EVAL, exp_id="EXP-P-009", reason="again")


def test_ledger_accepts_phase_2_experiment_ids():
    assert ledger.EXP_ID.match("EXP-P-001")
    assert ledger.EXP_ID.match("EXP-P-123")
    assert not ledger.EXP_ID.match("EXP-P-01")
    assert not ledger.EXP_ID.match("EXP-P-0001")
    assert not ledger.EXP_ID.match("EXP-Q-001")


# --- p2-fresh-v1 -------------------------------------------------------------------------------------------


def packet(pid, pmids, gene="GENE1"):
    out = {
        "id": pid,
        "subject": {"sex": "FEMALE"},
        "phenotypicFeatures": [{"type": {"id": "HP:0001250"}}],
        "metaData": {"externalReferences": [{"id": p} for p in pmids]},
    }
    if gene:
        variant = {"variationDescriptor": {"geneContext": {"symbol": gene}}}
        out["interpretations"] = [
            {"diagnosis": {"genomicInterpretations": [{"variantInterpretation": variant}]}}
        ]
    return out


RELEASE_027 = {"old1": {"PMID:800"}, "old2": {"PMID:5"}}
NOW_CITED = {"PMID:950"}
PACKETS = [
    packet("keep1", ["PMID:900"]),
    packet("keep2", ["PMID:900"]),
    packet("keep3", ["PMID:910", "PMID:911"]),
    packet("keep1", ["PMID:900"]),  # duplicate id
    packet("old1", ["PMID:999"]),  # id in 0.1.27
    packet("nogene", ["PMID:920"], gene=None),  # parser: no causal gene
    packet("pm027", ["PMID:800"]),  # publication in 0.1.27
    packet("linked_a", ["PMID:930", "PMID:800"]),  # links PMID:930 to a 0.1.27 publication
    packet("linked_b", ["PMID:930"]),
    packet("nopmid", []),
    packet("seen025", ["PMID:3"]),  # in 0.1.25 (dropped from 0.1.27)
    packet("cited_e0", ["PMID:40"]),
    packet("cited_now", ["PMID:950"]),
]


def test_select_fresh_keeps_only_new_uncited_post_e0_groups():
    sel = splits.select_fresh(PACKETS, RELEASE_027, E0_RELEASE, E0_CITED, NOW_CITED)
    assert sorted(c.case_id for c in sel.cases) == ["keep1", "keep2", "keep3"]
    assert sel.excluded_patients == {
        "duplicate_id": 1,
        "id_in_0_1_27": 1,
        "parser": 1,
        "pmid_in_0_1_27": 3,
        "no_pmid": 1,
        "in_0_1_25": 1,
        "cited_hpo_2025_11_24": 1,
        "cited_hpo_2026_02_16": 1,
    }
    assert sel.excluded_groups == {
        "pmid_in_0_1_27": 1,
        "no_pmid": 1,
        "in_0_1_25": 1,
        "cited_hpo_2025_11_24": 1,
        "cited_hpo_2026_02_16": 1,
    }
    assert sel.parse_drops == {"not_single_gene": 1}
    assert sel.groups["keep1"] == sel.groups["keep2"] != sel.groups["keep3"]


def test_snapshot_reader_takes_phenopackets_only_in_path_order(tmp_path):
    import io
    import json
    import tarfile

    path = tmp_path / "snap.tar.gz"
    files = {
        "ps-abc/notebooks/B/phenopackets/b.json": packet("b", ["PMID:1"]),
        "ps-abc/notebooks/A/phenopackets/a.json": packet("a", ["PMID:2"]),
        "ps-abc/notebooks/A/A_individuals.json": {"id": "not-a-packet"},
        "ps-abc/docs/x.json": {"id": "docs"},
    }
    with tarfile.open(path, "w:gz") as archive:
        for name, doc in files.items():
            data = json.dumps(doc).encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    assert [p["id"] for p in splits.iter_snapshot_packets(path)] == ["a", "b"]


REAL_ALL_CASES = splits._all_cases


@pytest.fixture
def fresh(cohort, monkeypatch):
    """The real fresh-split reader over PACKETS; r1-v1 and p2-v1 keep the synthetic CASES."""
    monkeypatch.setattr(
        splits, "_all_cases", lambda spec: REAL_ALL_CASES(spec) if spec.fresh else (list(CASES), {})
    )
    monkeypatch.setattr(splits, "open_source", lambda name, purpose: name)
    monkeypatch.setattr(splits, "iter_snapshot_packets", lambda path: iter(PACKETS))
    monkeypatch.setattr(splits, "release_index", lambda path: RELEASE_027)
    monkeypatch.setattr(splits, "cited_pmids", lambda path: NOW_CITED)
    return cohort


def test_fresh_split_is_one_sealed_vault_with_its_exclusions(fresh):
    body = splits.freeze_fresh("p2-fresh-v1", "snap")
    assert body["case_ids"] == {"vault": ["keep1", "keep2", "keep3"]}
    assert body["cohort_source"] == "snap" and body["source"]["id"] == "source:snap@v"
    assert body["sealed_parts"] == ["vault"]
    assert body["exclusions"]["patients"]["pmid_in_0_1_27"] == 3
    assert body["stats"]["vault"]["cases"] == 3
    assert body["stats"]["vault"]["publications"] == body["stats"]["vault"]["post_e0_publications"] == 2
    text = (fresh / "p2-fresh-v1.json").read_text()
    assert splits.freeze("p2-fresh-v1")["content_sha256"] == body["content_sha256"]
    assert (fresh / "p2-fresh-v1.json").read_text() == text


def test_fresh_split_needs_a_cohort_snapshot(fresh):
    with pytest.raises(LineageError, match="cohort source"):
        splits.freeze_fresh("p2-fresh-v1", "hpo_annotations")
    with pytest.raises(LineageError, match="freeze-fresh"):
        splits.freeze("p2-fresh-v1")


def test_fresh_refreeze_detects_drift(fresh, monkeypatch):
    splits.freeze_fresh("p2-fresh-v1", "snap")
    monkeypatch.setattr(splits, "cited_pmids", lambda path: NOW_CITED | {"PMID:900"})
    with pytest.raises(LineageError, match="different content"):
        splits.freeze("p2-fresh-v1")


def test_fresh_vault_is_sealed_and_opens_once(fresh, clean_tree, monkeypatch):
    splits.freeze_fresh("p2-fresh-v1", "snap")
    (fresh / "experiments" / "EXP-P-009.md").write_text("# final")
    with pytest.raises(LineageError, match="no train part"):
        splits.load_part("p2-fresh-v1", Part.TRAIN, Purpose.TRAIN)
    with pytest.raises(LineageError, match="DXT_SEALED_READ"):
        splits.load_part("p2-fresh-v1", Part.VAULT, Purpose.EVAL, exp_id="EXP-P-009", reason="final")
    monkeypatch.setenv("DXT_SEALED_READ", "EXP-P-009")
    vault = splits.load_part("p2-fresh-v1", Part.VAULT, Purpose.EVAL, exp_id="EXP-P-009", reason="final")
    assert [c.case_id for c in vault] == ["keep1", "keep2", "keep3"]
    with pytest.raises(LineageError, match="already opened"):
        splits.load_part("p2-fresh-v1", Part.VAULT, Purpose.EVAL, exp_id="EXP-P-009", reason="again")


def test_fresh_masks_and_groups_cover_its_vault_only(fresh):
    splits.freeze_fresh("p2-fresh-v1", "snap")
    assert splits.heldout_pmids("p2-fresh-v1") == {"PMID:900", "PMID:910", "PMID:911"}
    groups = splits.publication_groups("p2-fresh-v1")
    assert set(groups) == {"keep1", "keep2", "keep3"} and len(set(groups.values())) == 2
