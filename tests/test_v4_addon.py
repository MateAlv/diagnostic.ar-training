"""v4 add-on (PHASE3 §2f): excluded terms reach only the add-on; CONFIRM is refused or gated; E0's knowledge
only; θ = 0 is the base exactly; θ ≥ 0 only lowers. No data needed; the fitting test skips without torch."""

import importlib.util
import json

import numpy as np
import pytest

from diagnostic_ar_training import REPO_ROOT, splits
from diagnostic_ar_training.cohorts.schema import Case, Sex
from diagnostic_ar_training.ft.bundle import FEATURES, Knowledge
from diagnostic_ar_training.ft.system import case_inputs
from diagnostic_ar_training.lineage.registry import LineageError
from diagnostic_ar_training.sim4 import folds
from diagnostic_ar_training.v4 import addon, patients

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
    assert {p.name for p in ranks.iterdir()} == {
        f"{n}.ranks.jsonl" for n in ("E0", "network", *script.BUNDLES)
    }
