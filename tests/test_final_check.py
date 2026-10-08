"""`dxt final-check`: refusals before any load, one load per vault, every system on the same cases.

Mocked end to end: toy knowledge (from test_ft), a stand-in for E0, and the real `splits.load_part` and
ledger on fake frozen vaults.
"""

import json
from collections import Counter

import numpy as np
import pytest
from test_ft import EMB_INDEX, G2D, GENES, VECTORS, ancestors, annotations, bundle_of, member, override
from typer.testing import CliRunner

from diagnostic_ar_training import cli_final, cli_ft, cli_safe, splits
from diagnostic_ar_training.cli import app
from diagnostic_ar_training.cohorts.schema import Case, Sex
from diagnostic_ar_training.eval import final_check, harness, safe_eval
from diagnostic_ar_training.ft import knowledge as ft_knowledge
from diagnostic_ar_training.ft.system import E0Logits, E0System
from diagnostic_ar_training.lineage import gitinfo, ledger, manifest
from diagnostic_ar_training.lineage.registry import LineageError
from diagnostic_ar_training.rerank import kb as kb_io
from diagnostic_ar_training.safe import bundle as safe_bundle
from diagnostic_ar_training.safe.bundle import SafeRules
from diagnostic_ar_training.systems import genphenia_v3

EXP = "EXP-P-099"
ARGS = [
    "final-check",
    "--exp",
    EXP,
    "--safe-kb",
    "safe-kb-x",
    "--ft-bundle",
    "ft-x-ens",
    "--ft-kb",
    "ft-kb-x",
]
REASON = ["--reason", "pre-registered final check"]
CLEAN = gitinfo.CodeState(repo="r", sha="a" * 40, dirty=False)
DIRTY = gitinfo.CodeState(repo="r", sha="a" * 40, dirty=True)
SYSTEMS = [
    "safe-v1",
    "safe-v1[sex+onset]",
    "safe-v1[sex]",
    "safe-v1[onset]",
    "safe-v1[negation]",
    "ft-x-ens",
]
TERMS = ("HP:3", "HP:9", "HP:7", "HP:1", "HP:2")


class Base:
    """E0 stand-in: logits from the present terms; counts how often the network runs."""

    name = "E0"
    genes = GENES
    calls = 0

    class inputs:  # noqa: N801
        emb_index = EMB_INDEX
        vectors = VECTORS
        root = None

        @staticmethod
        def known_present(case):
            known = [t for t in case.present if t.startswith("HP:")]
            return known, {"n_present": len(case.present)}

    def logits(self, known):
        type(self).calls += 1
        seed = sum(ord(ch) for term in known for ch in term) + 7 * len(known)
        return np.random.default_rng(seed).normal(size=len(GENES)).astype(np.float32), tuple(known)

    def lineage_inputs(self):
        return [{"id": "e0", "sha256": "0" * 64}]


def make_cases(n=40):
    cases = []
    for i in range(n):
        kw = {}
        if i % 3 == 0:
            kw["sex"] = Sex.FEMALE if i % 2 else Sex.MALE
        if i % 4 == 0:
            kw["age_years"] = 2.0
        if i % 5 == 0:
            kw["onset_years"] = 1.0
        if i % 2 == 0:
            kw["excluded"] = ("HP:3",)
        present = tuple(TERMS[j % len(TERMS)] for j in range(i % 3 + 1)) + (f"HP:{100 + i}",)
        cases.append(Case(case_id=f"c{i}", cohort="t", gene=GENES[i % len(GENES)], present=present, **kw))
    return cases


CASES = make_cases()
VAULTS = {"p2-v1": [c.case_id for c in CASES[:24]], "p2-fresh-v1": [c.case_id for c in CASES[24:]]}
GROUPS = {c.case_id: f"g{i // 4}" for i, c in enumerate(CASES)}


@pytest.fixture
def artifacts(tmp_path):
    rows = [override("FEMALE1")]
    kb, _ = ft_knowledge.build(GENES, G2D, annotations(), {}, {}, ancestors, rows)
    kb_path = tmp_path / "ft-kb.json.gz"
    kb_io.write(kb, kb_path)
    safe_path = tmp_path / "safe-v1-bundle.json"
    safe_path.write_text(json.dumps(safe_bundle.export(kb["safe"], "safe-kb-x", onset_factor=0.01)))
    ft_path = tmp_path / "ft-v1-bundle.json"
    ft = bundle_of(member([1.0, 2.0, 0.5, 0.5, 1.0, 1.0, 3.0, 0.0]))
    ft_path.write_text(json.dumps(ft))
    return {"kb": kb, "kb_path": kb_path, "safe_path": safe_path, "ft": ft, "ft_path": ft_path}


@pytest.fixture
def world(tmp_path, monkeypatch, docs, clean_tree, artifacts):
    """Every check passes; the real load_part and ledger run on fake frozen vaults."""
    (docs / "experiments" / f"{EXP}.md").write_text("registered")
    monkeypatch.setenv(ledger.SEALED_READ_ENV, EXP)
    monkeypatch.setattr(safe_eval, "code_state", lambda: CLEAN)
    monkeypatch.setattr(manifest, "MANIFESTS_DIR", tmp_path / "manifests")
    monkeypatch.setattr(cli_final, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(harness, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(cli_final, "SPLITS_DIR", tmp_path)
    for split_id in VAULTS:
        (tmp_path / f"{split_id}.json").write_text("{}")
    monkeypatch.setattr(splits, "load_frozen", lambda s: {"case_ids": {"train": ["x"], "vault": VAULTS[s]}})
    monkeypatch.setattr(splits, "_all_cases", lambda spec: (list(CASES), Counter()))
    monkeypatch.setattr(splits, "publication_groups", lambda s: GROUPS)
    loads = Counter()
    load_part = splits.load_part

    def counted(split_id, part, *a, **k):
        loads[(split_id, part)] += 1
        return load_part(split_id, part, *a, **k)

    monkeypatch.setattr(splits, "load_part", counted)
    monkeypatch.setattr(cli_safe, "_kb_output", lambda kb_id, name: (artifacts["safe_path"], "5" * 64))
    monkeypatch.setattr(cli_ft, "_kb_output", lambda kb_id: (artifacts["kb_path"], "6" * 64))
    monkeypatch.setattr(
        cli_ft, "verified_bundle", lambda b, k: (artifacts["ft"], artifacts["ft_path"], "EXP-P-003")
    )
    monkeypatch.setattr(genphenia_v3, "GenPheniaV3", Base)
    Base.calls = 0
    return {
        "loads": loads,
        "out": tmp_path / "results" / EXP / "final-check",
        "manifests": tmp_path / "manifests",
    }


def run(args):
    return CliRunner().invoke(app, args, env={"COLUMNS": "400"})


class Touched(Exception):
    pass


def refused(result, text):
    return result.exit_code != 0 and not isinstance(result.exception, Touched) and text in result.output


@pytest.fixture
def tripwires(monkeypatch):
    """Anything that loads data, builds a system, fetches an artifact or touches the ledger fails the test."""

    def boom(*a, **k):
        raise Touched

    for module, name in (
        (splits, "load_part"),
        (splits, "publication_groups"),
        (splits, "_all_cases"),
        (ledger, "record_access"),
        (genphenia_v3, "GenPheniaV3"),
    ):
        monkeypatch.setattr(module, name, boom)


def test_end_to_end_one_load_per_vault_and_identical_cases(world):
    result = run(ARGS + REASON)
    assert result.exit_code == 0, result.output
    assert world["loads"] == {("p2-v1", "vault"): 1, ("p2-fresh-v1", "vault"): 1}
    assert Base.calls == len(CASES)  # E0's network ran once per case, for all seven systems
    rows = ledger.LEDGER.read_text().splitlines()
    assert [r.split(" | ")[1] for r in rows] == ["p2-v1/vault", "p2-fresh-v1/vault"]

    out = world["out"]
    report = json.loads((out / "report.json").read_text())
    assert report["systems_order"] == SYSTEMS and set(report["systems"]) == set(SYSTEMS)
    assert report["cases"] == len(CASES) and report["frozen_vault_sizes"] == {"p2-v1": 24, "p2-fresh-v1": 16}
    assert report["publications"] == 10 and report["components"]["p2-v1"]["publications"] == 6
    assert set(report["components"]) == {"p2-v1", "p2-fresh-v1"}
    assert report["components"]["p2-fresh-v1"]["cases"] == 16
    assert report["identity"]["present_view_vs_e0_mismatches"] == dict.fromkeys(SYSTEMS, 0)
    for name in SYSTEMS:
        for scope in (report, *report["components"].values()):
            d = scope["systems"][name]["vs_e0"]
            assert d["n"] == scope["cases"] and d["resample_unit"] == "group"
            assert {"ci95", "harmed_n", "helped_n", "top1_entered", "top10_left"} <= set(d)
            assert set(scope["systems"][name]["subsets"]) == {"gene_in_vocab", *safe_eval.known_subsets([])}
            assert scope["systems"][name]["rank_changes_where_it_changed_none"] == 0
    assert any(report["systems"][n]["vs_e0"]["delta"] != 0 for n in SYSTEMS)

    case_lists = {}
    for name in ["E0", *SYSTEMS]:
        recs = harness.read(out / f"{final_check.COHORT}__{name}__all.ranks.jsonl")
        case_lists[name] = [r["case_id"] for r in recs]
    assert all(ids == [c.case_id for c in CASES] for ids in case_lists.values())

    m = manifest.load_manifest(final_check.run_id(EXP))
    paths = [o.path for o in m.outputs]
    assert len(paths) == len(set(paths)) == 2 * 7 + 1
    assert m.kind == "final-check" and m.params["systems"] == ["E0", *SYSTEMS]


def test_a_second_run_is_refused_by_the_ledger_before_anything(world):
    assert run(ARGS + REASON).exit_code == 0
    loads, calls = dict(world["loads"]), Base.calls
    result = run(ARGS + REASON)
    assert result.exit_code != 0 and "already opened" in result.output
    assert dict(world["loads"]) == loads and Base.calls == calls
    assert len(ledger.LEDGER.read_text().splitlines()) == 2


def test_tripwires_are_live_once_every_check_passes(world, tripwires):
    assert isinstance(run(ARGS + REASON).exception, Touched)


def test_preflight_refusals_come_in_order_and_before_any_load(world, tripwires, monkeypatch):
    monkeypatch.delenv(ledger.SEALED_READ_ENV)
    monkeypatch.setattr(ledger, "is_preregistered", lambda path: False)
    monkeypatch.setattr(safe_eval, "code_state", lambda: DIRTY)
    assert refused(run(ARGS), f"DXT_SEALED_READ={EXP}")
    monkeypatch.setenv(ledger.SEALED_READ_ENV, "EXP-P-001")
    assert refused(run(ARGS), f"DXT_SEALED_READ={EXP}")
    monkeypatch.setenv(ledger.SEALED_READ_ENV, EXP)
    assert refused(run(ARGS), "committed")
    monkeypatch.setattr(ledger, "is_preregistered", lambda path: True)
    assert refused(run(ARGS), "uncommitted")
    monkeypatch.setattr(safe_eval, "code_state", lambda: CLEAN)
    assert refused(run(ARGS), "reason is required")
    ledger.LEDGER.write_text("| 2026-10-20T00:00:00+00:00 | p2-fresh-v1/vault | EXP-P-001 | abc | r |\n")
    assert refused(run(ARGS + REASON), "already opened")
    ledger.LEDGER.write_text("")
    assert refused(run([*ARGS[:2], "EXP-X-001", *ARGS[3:], *REASON]), "experiment id")


def test_artifact_and_split_refusals_come_before_any_load(world, tripwires, monkeypatch, artifacts):
    manifests = world["manifests"]
    manifests.mkdir(parents=True)
    (manifests / f"{final_check.run_id(EXP)}.json").write_text("{}")
    assert refused(run(ARGS + REASON), "already exists")
    (manifests / f"{final_check.run_id(EXP)}.json").unlink()
    world["out"].mkdir(parents=True)
    assert refused(run(ARGS + REASON), "never overwritten")
    world["out"].rmdir()

    def not_frozen(split_id):
        if split_id == "p2-fresh-v1":
            raise LineageError(f"{split_id} is not frozen")
        return {"case_ids": {"vault": VAULTS[split_id]}}

    monkeypatch.setattr(splits, "load_frozen", not_frozen)
    assert refused(run(ARGS + REASON), "p2-fresh-v1 is not frozen")
    monkeypatch.setattr(splits, "load_frozen", lambda s: {"case_ids": {"test": ["c1"]}})
    assert refused(run(ARGS + REASON), "no vault part")
    monkeypatch.setattr(splits, "load_frozen", lambda s: {"case_ids": {"vault": ["c1", s]}})
    assert refused(run(ARGS + REASON), "in both")
    monkeypatch.setattr(splits, "load_frozen", lambda s: {"case_ids": {"vault": VAULTS[s]}})

    def wrong_kind(*a):
        raise LineageError("safe-kb-x is not verified")

    monkeypatch.setattr(cli_safe, "_kb_output", wrong_kind)
    assert refused(run(ARGS + REASON), "not verified")
    monkeypatch.setattr(cli_safe, "_kb_output", lambda kb_id, name: (artifacts["safe_path"], "5" * 64))

    def other_kb(b, k):
        raise LineageError(f"{b} was trained on ft-kb-y, not {k}")

    monkeypatch.setattr(cli_ft, "verified_bundle", other_kb)
    assert refused(run(ARGS + REASON), "trained on ft-kb-y")
    assert not ledger.LEDGER.exists() or not ledger.LEDGER.read_text()


def test_system_names_never_collide():
    final_check.check_names(SYSTEMS)
    for bad in (["safe-v1", "safe-v1"], ["E0"], ["a/b"], ["a__b"], [""]):
        with pytest.raises(ValueError):
            final_check.check_names(bad)


def test_evaluate_refuses_colliding_systems_and_shares_e0(artifacts):
    base = Base()
    e0 = E0Logits(base)
    memo = safe_eval.Memo(E0System(e0))
    rules = SafeRules(json.loads(artifacts["safe_path"].read_text()))
    systems = final_check.safe_systems(memo, rules)
    assert [s.name for s in systems] == SYSTEMS[:5]
    by_split = {
        s: ([c for c in CASES if c.case_id in ids], {i: f"{s}:{GROUPS[i]}" for i in ids})
        for s, ids in VAULTS.items()
    }
    with pytest.raises(ValueError, match="collide"):
        final_check.evaluate(memo, [*systems, systems[0]], by_split)
    Base.calls = 0
    report, records = final_check.evaluate(memo, systems, by_split)
    assert Base.calls == len(CASES)
    assert list(records) == ["E0", *SYSTEMS[:5]]
    full = safe_eval.evaluate(
        safe_eval.Memo(E0System(E0Logits(Base()))),
        rules,
        CASES,
        {k: v for _, g in by_split.values() for k, v in g.items()},
    )[0]
    for label, v in full["variants"].items():
        assert report["systems"][v["system"]]["vs_e0"] == v["vs_e0"], label
    assert final_check.table(report)
