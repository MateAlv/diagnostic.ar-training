"""v4 add-on (PHASE3 §2f): excluded terms reach only the add-on; CONFIRM is refused or gated; E0's knowledge
only; θ = 0 is the base exactly; θ ≥ 0 only lowers. No data needed; the fitting test skips without torch."""

import importlib.util
import json
from collections import Counter
from types import SimpleNamespace

import numpy as np
import pytest

from diagnostic_ar_training import REPO_ROOT, splits
from diagnostic_ar_training.cohorts.schema import Case, Sex
from diagnostic_ar_training.ft.bundle import FEATURES, Knowledge
from diagnostic_ar_training.ft.system import case_inputs
from diagnostic_ar_training.lineage import ledger
from diagnostic_ar_training.lineage.gitinfo import CodeState
from diagnostic_ar_training.lineage.registry import LineageError, Purpose
from diagnostic_ar_training.sim4 import folds
from diagnostic_ar_training.v4 import addon, patients, report

GENES = ("-", "G1", "G2", "G3")
HPOA = """#description: fake
#date: 2025-03-03
database_id\tdisease_name\tqualifier\thpo_id\treference\tevidence\tonset\tfrequency\tsex\tmodifier\taspect\tbiocuration
OMIM:1\tSpermatogenic failure 1\t\tHP:3\tPMID:1\tPCS\t\t5/5\t\t\tP\tx
OMIM:1\tSpermatogenic failure 1\t\tHP:9\tPMID:1\tPCS\t\t0/4\t\t\tP\tx
OMIM:1\tSpermatogenic failure 1\tNOT\tHP:7\tPMID:1\tPCS\t\t\t\t\tP\tx
OMIM:2\tAdult-onset ataxia 2\t\tHP:1\tPMID:2\tPCS\t\tHP:0040280\t\t\tP\tx
OMIM:2\tAdult-onset ataxia 2\t\tHP:0003581\tPMID:2\tPCS\t\t\t\t\tC\tx
"""
G2P = """ncbi_gene_id\tgene_symbol\thpo_id\thpo_name\tfrequency\tdisease_id
1\tG1\tHP:3\tx\t-\tOMIM:1
2\tG2\tHP:1\tx\t-\tOMIM:2
3\tG3\tHP:1\tx\t-\t
"""
EDGES = (("HP_3", "HP_2"), ("HP_2", "HP_1"))


def ontology_json() -> str:
    obo = "http://purl.obolibrary.org/obo/"
    nodes = [{"id": f"{obo}HP_{i}", "lbl": f"t{i}"} for i in (1, 2, 3, 7, 9)]
    edges = [{"sub": f"{obo}{a}", "pred": "is_a", "obj": f"{obo}{b}"} for a, b in EDGES]
    return json.dumps({"graphs": [{"nodes": nodes, "edges": edges}]})


@pytest.fixture
def sources(tmp_path, monkeypatch):
    files = {
        "hpo_annotations_2025_03_03": ("phenotype.hpoa", HPOA),
        "hpo_ontology_2025_03_03": ("hp.json", ontology_json()),
        "e0_genes_to_phenotype": ("genes_to_phenotype.txt", G2P),
    }
    opened = []

    def open_source(name, purpose):
        opened.append(name)
        if name not in files:
            raise AssertionError(f"the add-on's knowledge read {name}")
        path = tmp_path / files[name][0]
        path.write_text(files[name][1])
        return path

    monkeypatch.setattr(addon, "open_source", open_source)
    return opened


@pytest.fixture
def kb(sources):
    built, _, _ = addon.kb_from_sources(GENES)
    return built


def case(i: int, **kw) -> Case:
    fields = {"present": ("HP:1",), "excluded": ("HP:2",), "sex": Sex.FEMALE, "age_years": 3.0, "gene": "G1"}
    return Case(case_id=f"c{i}", cohort="t", pmids=(f"PMID:{i}",), **{**fields, **kw})


def test_kb_reads_only_e0s_knowledge(sources, kb):
    assert sorted(sources) == sorted(addon.KB_SOURCES.values())
    assert set(sources) == {"hpo_annotations_2025_03_03", "hpo_ontology_2025_03_03", "e0_genes_to_phenotype"}
    genes, safe = kb["genes"], kb["safe"]["genes"]
    assert genes["G1"]["profile"] == ["HP:3"]
    assert genes["G2"]["profile"] == ["HP:1"] and genes["G3"]["profile"] == []
    assert safe["G1"]["sex"]["limit"] == "male" and safe["G1"]["obligate"] == {"OMIM:1": ["HP:3"]}
    assert safe["G2"]["onset"]["earliest_years"] == 16
    assert kb["safe"]["ancestors_or_self"]["HP:3"] == ["HP:1", "HP:2", "HP:3"]
    assert kb["safe"]["overrides"] == [] and kb["overrides_skipped"] == []


def test_excluded_terms_reach_only_the_addon_path(monkeypatch):
    groups = {f"c{i}": f"PMID:{i}" for i in range(40)}
    status = dict.fromkeys(groups.values(), patients.UNCITED)
    cases = [case(i) for i in range(40)]
    full = patients.annotate(cases, groups, status, folds.fold_of, keep_excluded=True)
    assert all(p.case.excluded == ("HP:2",) and p.case.sex == Sex.FEMALE for p in full)
    assert all(p.case.excluded == () for p in patients.annotate(cases, groups, status, folds.fold_of))
    assert all(p.case.excluded == () for p in patients.annotate(cases, groups, status, folds.fold_of, True))
    seen = {}

    def load_train(keep_covariates=False, keep_excluded=False):
        seen["keep_excluded"] = keep_excluded
        return full if keep_excluded else patients.annotate(cases, groups, status, folds.fold_of)

    monkeypatch.setattr(patients, "load_train", load_train)
    monkeypatch.setattr(patients, "_folds", lambda: folds)
    assert all(p.case.excluded == () for p in patients.load_folds((0, 1, 2, 3)))
    assert seen == {"keep_excluded": False}
    kept = patients.load_addon((0, 1, 2, 3))
    assert seen == {"keep_excluded": True} and kept and all(p.case.excluded == ("HP:2",) for p in kept)
    plain = addon.network_view(kept)
    assert all(
        p.case.excluded == () and p.case.sex == Sex.UNKNOWN and p.case.age_years is None for p in plain
    )
    assert [p.case.present for p in plain] == [p.case.present for p in kept]
    with pytest.raises(LineageError, match="CONFIRM"):
        patients.load_addon((3, 4))


def test_untrained_addon_returns_the_base_scores_exactly(kb):
    knowledge = Knowledge(kb, GENES, None, "kb")
    model = addon.Addon(addon.untrained("kb"), knowledge)
    logits = np.array([0.5, 3.0, 2.0, -1.0], dtype=np.float32)
    inputs = case_inputs(case(0))
    assert knowledge.features(inputs).any()
    for feats in (None, knowledge.features(inputs)):
        out = model.scores(logits, inputs, feats)
        assert out.dtype == np.float64 and np.array_equal(out, logits.astype(np.float64))
    assert addon.rank(model.scores(logits, inputs), 1) == addon.rank(logits, 1) == 1.0


def test_fitted_theta_is_nonnegative_and_only_lowers(kb):
    torch = pytest.importorskip("torch")
    torch.manual_seed(0)
    rng = np.random.default_rng(0)
    n, g = 300, len(GENES)
    target = rng.integers(1, g, n)
    logits = rng.normal(size=(n, g)).astype(np.float32)
    wrong = (target % (g - 1)) + 1
    logits[np.arange(n), wrong] += 2.0
    feats = np.zeros((n, len(FEATURES), g), dtype=np.float32)
    feats[np.arange(n), 0, target] = 1.0
    feats[np.arange(n), 1, wrong] = 1.0
    ids = [f"c{i}" for i in range(n)]
    members, info = addon.fit(
        ids, [f"PMID:{i}" for i in range(n)], logits, feats, np.zeros((n, 8), np.float32), target, seeds=(0,)
    )
    theta = np.array(members[0]["theta"])
    assert (theta >= 0).all() and theta[0] == 0 and theta[1] > 0
    assert addon.mean_theta(members)["onset_strict_late"] == pytest.approx(theta[1])
    model = addon.Addon(addon.bundle("kb", members, ["m"]), Knowledge(kb, GENES, None, "kb"))
    for i in range(20):
        out = model.scores(logits[i], case_inputs(case(i)), feats[i])
        assert (out <= logits[i].astype(np.float64)).all() and (out < logits[i]).any()
    assert info[0]["best_epoch"] > 0


def addon_bundle():
    theta = [0.0] * len(FEATURES)
    theta[FEATURES.index("sex_mismatch")] = 2.0
    theta[FEATURES.index("neg_obligate")] = 3.0
    member = {"active_features": list(FEATURES), "active_covariates": [], "theta": theta, "mlp": None}
    return addon.bundle("kb", [member], ["m"])


@pytest.fixture
def confirm_fold(tmp_path, monkeypatch):
    groups = {f"c{i}": f"PMID:{i}" for i in range(60)}
    cases = [case(i, gene=GENES[1 + i % 3]) for i in range(60)]
    loaded = []

    def load_part(split, part, purpose, *a, **k):
        loaded.append((split, part))
        return cases

    monkeypatch.setattr(folds, "CONFIRM_LEDGER", tmp_path / "CONFIRM_LEDGER.md")
    monkeypatch.setattr(folds, "train_groups", lambda: groups)
    monkeypatch.setattr(splits, "load_part", load_part)
    monkeypatch.setattr(
        splits,
        "load_frozen",
        lambda split: {"group_status": dict.fromkeys(groups.values(), patients.UNCITED)},
    )
    monkeypatch.delenv(folds.CONFIRM_ENV, raising=False)
    return loaded


def fake_scores(calls):
    def score(members):
        calls.append(len(members))
        assert all(p.case.excluded == () and p.case.sex == Sex.UNKNOWN for p in members)
        return {p.case_id: np.array([0.0, 1.0, 2.0, 3.0], np.float32) for p in members}

    return score


def test_confirm_read_needs_the_flag_and_writes_the_ledger(kb, confirm_fold, monkeypatch):
    knowledge = Knowledge(kb, GENES, None, "kb")
    calls = []
    args = ({"b": addon_bundle()}, knowledge, fake_scores(calls), fake_scores(calls))
    with pytest.raises(LineageError, match=folds.CONFIRM_ENV):
        addon.confirm_read("why", *args)
    assert not confirm_fold and not calls and not folds.CONFIRM_LEDGER.exists()
    monkeypatch.setenv(folds.CONFIRM_ENV, "1")
    with pytest.raises(LineageError, match="reason"):
        addon.confirm_read(" ", *args)
    summary, recs = addon.confirm_read("protocol written", *args)
    assert "protocol written" in folds.CONFIRM_LEDGER.read_text() and calls
    fold4 = recs["E0"]
    assert fold4 and all(r["fold"] == folds.CONFIRM_FOLD for r in fold4)
    assert summary["n"] == len(fold4) == sum(folds.fold_of(f"PMID:{i}") == 4 for i in range(60))
    lowered = {r["case_id"]: r["rank"] for r in recs["b"]}
    for r in recs["network"]:
        assert lowered[r["case_id"]] == r["rank"] + (r["gene"] == "G1")
    assert set(summary["b"]) == {"vs_e0", "vs_network"}


def test_confirm_script_is_gated_and_writes_its_outputs(kb, confirm_fold, monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location(
        "p3_addon_confirm", REPO_ROOT / "scripts" / "analysis" / "p3_addon" / "confirm.py"
    )
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    calls = []
    monkeypatch.setattr(script, "code_dirty", lambda: False)
    monkeypatch.setattr(script, "network_scorer", lambda run: fake_scores(calls))
    monkeypatch.setattr(script, "knowledge_of", lambda kb, kb_id: Knowledge(kb, GENES, None, kb_id))
    monkeypatch.setattr(addon, "load_kb", lambda kb_id: (kb, "sha"))
    monkeypatch.setattr(addon, "load_bundle", lambda bundle_id, kb_id: (addon_bundle(), "sha"))
    monkeypatch.setattr(addon, "e0_logits", fake_scores(calls))
    monkeypatch.setattr(script, "training_genes", lambda: {GENES[1]})
    monkeypatch.setattr(script, "parent_mapper", lambda: lambda term: "HP:0000118")
    out, ranks = tmp_path / "confirm.json", tmp_path / "ranks"
    with pytest.raises(LineageError):
        script.run("why", out=out, ranks=ranks)
    assert not calls and not out.exists() and not confirm_fold
    monkeypatch.setattr(script, "code_dirty", lambda: True)
    monkeypatch.setenv(folds.CONFIRM_ENV, "1")
    with pytest.raises(LineageError, match="clean"):
        script.run("why", out=out, ranks=ranks)
    assert not folds.CONFIRM_LEDGER.exists()
    monkeypatch.setattr(script, "code_dirty", lambda: False)
    summary = script.run("why", out=out, ranks=ranks)
    assert json.loads(out.read_text())["network_run"] == script.NETWORK == summary["network_run"]
    controls = ("E0_swap", "network_swap", "E0_parent", "network_parent")
    assert {p.name for p in ranks.iterdir()} == {
        f"{n}.ranks.jsonl" for n in ("E0", "network", *script.BUNDLES, *controls)
    }
    assert set(summary["controls"]) == {"swap", "parent"} and not summary["dry_run_fold_3"]
    raw = summary["controls"]["swap"]["raw_rank"]
    assert raw["gene_with_training_patients"]["n"] + raw["gene_without"]["n"] > 0


def load_script(name: str):
    path = REPO_ROOT / "scripts" / "analysis" / "p3_addon" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"p3_addon_{name}", path)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    return script


VAULT_STATUS = {f"PMID:{i}": patients.CITED if i % 3 == 0 else patients.UNCITED for i in range(60)}


@pytest.fixture
def vault(kb, docs, clean_tree, monkeypatch, tmp_path):
    """The vault script on 60 fake vault patients, every gate open; `splits.load_part` is the real one."""
    script = load_script("vault")
    cases = [case(i, gene=GENES[1 + i % 3]) for i in range(60)]
    frozen = {
        "case_ids": {"train": [], "vault": [c.case_id for c in cases]},
        "group_status": VAULT_STATUS,
        "content_sha256": "split",
    }
    calls, loaded = [], []
    real_load_part = splits.load_part

    def load_part(split, part, purpose, exp_id=None, reason=""):
        loaded.append((split, part, purpose, exp_id, reason))
        return real_load_part(split, part, purpose, exp_id, reason)

    monkeypatch.setattr(splits, "load_part", load_part)
    monkeypatch.setattr(splits, "load_frozen", lambda split: frozen)
    monkeypatch.setattr(splits, "_all_cases", lambda spec: (cases, Counter()))
    (ledger.EXPERIMENTS_DIR / f"{script.EXP}.md").write_text("pre-registered")
    monkeypatch.setenv(ledger.SEALED_READ_ENV, script.EXP)
    real_scorer = script.network_scorer
    monkeypatch.setattr(script, "code_state", lambda: clean_tree)
    monkeypatch.setattr(script, "network_scorer", lambda run: fake_scores(calls))
    monkeypatch.setattr(script, "checkpoint_sha", lambda run: script.FROZEN_SHA256[run])
    monkeypatch.setattr(addon, "load_kb", lambda kb_id: (kb, script.FROZEN_SHA256[kb_id]))
    monkeypatch.setattr(addon, "load_bundle", lambda b, kb_id: (addon_bundle(), script.FROZEN_SHA256[b]))
    monkeypatch.setattr(script, "knowledge_of", lambda kb, kb_id: Knowledge(kb, GENES, None, kb_id))
    monkeypatch.setattr(script, "e0_scorer", lambda: fake_scores(calls))
    monkeypatch.setattr(script, "training_genes", lambda: {GENES[1]})
    monkeypatch.setattr(script, "parent_mapper", lambda: lambda term: "HP:0000118")
    return SimpleNamespace(
        script=script,
        calls=calls,
        loaded=loaded,
        cases=cases,
        real_scorer=real_scorer,
        out=tmp_path / "out" / "vault.json",
        ranks=tmp_path / "ranks",
    )


def untrained_on_0_3(v, monkeypatch, folds_used=(0, 1, 2), last=True):
    from diagnostic_ar_training.v4 import runs

    run = v.out.parent.parent / "run"
    run.mkdir()
    if last:
        (run / "last.pt").write_bytes(b"x")
    cfg = SimpleNamespace(sim=SimpleNamespace(real_folds=list(folds_used)))
    monkeypatch.setattr(runs, "load_config", lambda run_id: cfg)
    monkeypatch.setattr(runs, "run_dir", lambda run_id: run)
    monkeypatch.setattr(v.script, "network_scorer", v.real_scorer)


def bad_bundle(v, monkeypatch):
    monkeypatch.setattr(addon, "load_bundle", lambda b, kb_id: (addon_bundle(), "0" * 64))


def unverified_kb(v, monkeypatch):
    def load_kb(kb_id):
        raise LineageError(f"{kb_id}: not a verified addon-kb")

    monkeypatch.setattr(addon, "load_kb", load_kb)


def registration(v):
    return ledger.EXPERIMENTS_DIR / f"{v.script.EXP}.md"


OPENED = "| t | p3-v1/vault | EXP-V-001 | s | r |\n"
DIRTY = CodeState("t", "b" * 40, True)
REFUSALS = {
    "empty reason": (lambda v, mp: " ", "reason"),
    "dirty tree": (lambda v, mp: mp.setattr(v.script, "code_state", lambda: DIRTY), "SHA"),
    "no pre-registration": (lambda v, mp: registration(v).unlink(), "committed"),
    "uncommitted pre-registration": (lambda v, mp: registration(v).write_text("draft"), "committed"),
    "no DXT_SEALED_READ": (lambda v, mp: mp.delenv(ledger.SEALED_READ_ENV), "DXT_SEALED_READ"),
    "wrong DXT_SEALED_READ": (lambda v, mp: mp.setenv(ledger.SEALED_READ_ENV, "EXP-V-1"), "DXT_SEALED_READ"),
    "vault already opened": (lambda v, mp: ledger.LEDGER.write_text(OPENED), "already opened"),
    "output exists": (lambda v, mp: (v.out.parent.mkdir(), v.out.write_text("{}")), "never overwritten"),
    "network trained on folds 0-2": (lambda v, mp: untrained_on_0_3(v, mp), "folds 0-3"),
    "network trained on folds 0-4": (lambda v, mp: untrained_on_0_3(v, mp, (0, 1, 2, 3, 4)), "folds 0-3"),
    "network without last.pt": (lambda v, mp: untrained_on_0_3(v, mp, (0, 1, 2, 3), False), "folds 0-3"),
    "checkpoint hash": (lambda v, mp: mp.setattr(v.script, "checkpoint_sha", lambda run: "0"), "frozen"),
    "bundle hash": (bad_bundle, "frozen"),
    "unverified knowledge": (unverified_kb, "verified"),
}


@pytest.mark.parametrize("refusal", REFUSALS)
def test_vault_refusals_come_before_any_load(vault, monkeypatch, refusal):
    breaks, message = REFUSALS[refusal]
    reason = breaks(vault, monkeypatch)
    before = ledger.LEDGER.read_text() if ledger.LEDGER.exists() else None
    out_before = vault.out.read_text() if vault.out.exists() else None
    with pytest.raises(LineageError, match=message):
        vault.script.run(reason if isinstance(reason, str) else "go", vault.out, vault.ranks)
    assert not vault.loaded and not vault.calls and not vault.ranks.exists()
    assert (ledger.LEDGER.read_text() if ledger.LEDGER.exists() else None) == before
    assert (vault.out.read_text() if vault.out.exists() else None) == out_before


def test_vault_read_opens_once_and_writes_its_outputs(vault):
    script = vault.script
    summary = script.run("Mateo's go", vault.out, vault.ranks)
    assert vault.loaded == [("p3-v1", splits.Part.VAULT, Purpose.EVAL, "EXP-V-002", "Mateo's go")]
    rows = ledger.entries("p3-v1", "vault")
    assert len(rows) == 1 and "EXP-V-002" in rows[0] and "Mateo's go" in rows[0]
    assert json.loads(vault.out.read_text()) == json.loads(json.dumps(summary, default=str))
    controls = ("E0_swap", "network_swap", "E0_parent", "network_parent")
    assert {p.name for p in vault.ranks.iterdir()} == {
        f"{n}.ranks.jsonl" for n in ("E0", "network", *script.BUNDLES, *controls)
    }
    e0 = report.read_ranks(vault.ranks / "E0.ranks.jsonl")
    assert len(e0) == 60 and {r["fold"] for r in e0} == {script.VAULT_FOLD}
    assert {r["group"] for r in e0} == set(VAULT_STATUS) and not summary["dry_run_fold_3"]
    assert {r["status"] for r in e0 if r["group"] == "PMID:0"} == {patients.CITED}
    assert set(summary["readings"]) == set(script.PAIRS)
    assert set(summary["readings"]["F1_vs_E0"]) == set(script.STRATA)
    f1, f2 = (summary["readings"][k]["uncited"] for k in ("F1_vs_E0", "F2_vs_E0"))
    g = summary["gate"]
    assert g["h1_pass"] == (f1["delta_mrr_cap_ci95"][0] > 0) and g["F1"]["delta"] == f1["delta"]["mrr_cap"]
    assert g["F2"]["ci95"] == f2["delta_mrr_cap_ci95"] and g["h2_tested"] == g["h1_pass"]
    assert summary["agreement"]["ranks_differing_from_F1"] == 0
    assert summary["size"]["n"] == 60 and summary["size"]["by_stratum"]["uncited"]["n"] == 40
    assert summary["size"]["largest_uncited_group"]["share"] == pytest.approx(1 / 40)
    assert set(summary["publication_mean"]["F1_vs_E0"]) == set(script.STRATA)
    assert summary["frozen_system"]["bundles"] == {b: script.FROZEN_SHA256[b] for b in script.BUNDLES}
    vault.out.unlink()
    with pytest.raises(LineageError, match="already opened"):
        script.run("again", vault.out, vault.ranks)
    assert len(vault.loaded) == 1 and len(ledger.entries("p3-v1", "vault")) == 1


def test_vault_dry_run_reads_fold_3_without_the_gate(vault, monkeypatch):
    monkeypatch.delenv(ledger.SEALED_READ_ENV)
    monkeypatch.setattr(vault.script, "code_state", lambda: DIRTY)
    registration(vault).unlink()
    groups = {c.case_id: f"PMID:{c.case_id[1:]}" for c in vault.cases}
    fold3 = patients.annotate(vault.cases[:30], groups, VAULT_STATUS, lambda g: 3, keep_excluded=True)
    monkeypatch.setattr(patients, "load_addon", lambda folds_: fold3 if folds_ == (3,) else [])
    summary = vault.script.run("dry run", vault.out, vault.ranks, dry_run=True)
    assert summary["dry_run_fold_3"] and summary["size"]["n"] == 30
    assert not vault.loaded and not ledger.LEDGER.exists() and vault.out.exists()
    with pytest.raises(LineageError, match="reason"):
        vault.script.run("", vault.out, vault.ranks, dry_run=True)
    wrong = {**VAULT_STATUS, "PMID:1": patients.CITED}
    mislabelled = patients.annotate(vault.cases[:30], groups, wrong, lambda g: 3, keep_excluded=True)
    monkeypatch.setattr(patients, "load_addon", lambda folds_: mislabelled)
    with pytest.raises(LineageError, match="disagrees"):
        vault.script.run("dry run", vault.out, vault.ranks, dry_run=True)


def reading(lower: float) -> dict:
    return {
        "uncited": {
            "n": 5,
            "n_groups": 2,
            "mrr_cap": 0.3,
            "e0": {"mrr_cap": 0.2},
            "delta": {"mrr_cap": 0.1},
            "delta_mrr_cap_ci95": [lower, 0.2],
        }
    }


def test_vault_gate_is_hierarchical():
    gate = load_script("vault").gate
    assert gate(reading(0.01), reading(-0.01)) | {"F1": None, "F2": None} == {
        "stratum": "uncited",
        "metric": "mrr_cap",
        "F1": None,
        "F2": None,
        "h1_pass": True,
        "h2_tested": True,
        "h2_pass": False,
    }
    assert gate(reading(0.01), reading(0.02))["h2_pass"] is True
    failed = gate(reading(0.0), reading(0.05))
    assert failed["h1_pass"] is False and failed["h2_tested"] is False and failed["h2_pass"] is None
    assert gate(reading(0.01), reading(0.0))["F1"] == {
        "n": 5,
        "n_groups": 2,
        "e0": 0.2,
        "value": 0.3,
        "delta": pytest.approx(0.1),
        "ci95": [0.01, 0.2],
    }


def test_publication_mean_weighs_each_publication_once():
    publication_mean = load_script("vault").publication_mean

    def recs(ranks, groups):
        return [
            {"case_id": f"c{i}", "group": g, "rank": r, "strata": ["all", "uncited"]}
            for i, (r, g) in enumerate(zip(ranks, groups, strict=True))
        ]

    groups = ["a", "a", "a", "b"]
    out = publication_mean(recs([1, 1, 1, 4], groups), recs([2, 2, 2, float("inf")], groups), ("uncited",))
    x = out["uncited"]
    assert x["mrr_pub"] == pytest.approx((1 + 0.25) / 2) and x["e0_mrr_pub"] == pytest.approx(0.25)
    assert x["delta"] == pytest.approx(0.375) and x["n_groups"] == 2 and x["n"] == 4
    rng = np.random.default_rng(0)
    groups = [f"g{i // 3}" for i in range(60)]
    new, base = rng.integers(1, 20, 60).astype(float), rng.integers(1, 20, 60).astype(float)
    even = publication_mean(recs(new, groups), recs(base, groups), ("all",))["all"]
    assert even["ci95"] == pytest.approx(report.capped_bootstrap(base, new, groups))
