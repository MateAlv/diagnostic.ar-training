"""The second CONFIRM read (scripts/analysis/p4_confirm/confirm2.py): every refusal comes before any patient
is loaded or the ledger touched, fold 4 opens once, the gate fields and outputs are right; the dry run reads
fold 3 without the gate. Fakes only; the network-training refusals skip without torch."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from test_v4_addon import (  # noqa: F401
    DIRTY,
    GENES,
    addon_bundle,
    case,
    confirm_fold,
    fake_scores,
    kb,
    sources,
    untrained_on_0_3,
)

from diagnostic_ar_training import REPO_ROOT, splits
from diagnostic_ar_training.ft.bundle import Knowledge
from diagnostic_ar_training.lineage.registry import LineageError
from diagnostic_ar_training.sim4 import folds
from diagnostic_ar_training.v4 import addon, patients, report, sexrule

FIRST_READ = "| 2026-10-15T16:45:42+00:00 | d663d26 | P3-CONFIRM |\n"
SEX_KB = {"schema": sexrule.SCHEMA, "genes": {"G3": {"limit": "male"}}}
SYSTEMS = ("E0", "F3", "F1", "F2")


def load_script():
    path = REPO_ROOT / "scripts" / "analysis" / "p4_confirm" / "confirm2.py"
    spec = importlib.util.spec_from_file_location("p4_confirm2", path)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    return script


@pytest.fixture
def c2(kb, confirm_fold, docs, clean_tree, monkeypatch, tmp_path):  # noqa: F811
    """confirm2.py on 60 fake train patients (fold 4 through the real `folds.cases_in`), every gate open."""
    script = load_script()
    folds.CONFIRM_LEDGER.write_text(folds.LEDGER_HEADER + FIRST_READ)
    protocol = tmp_path / "P4-CONFIRM.md"
    protocol.write_text("protocol")
    monkeypatch.setattr(script, "PROTOCOL", protocol)
    monkeypatch.setenv(folds.CONFIRM_ENV, "1")
    calls, written = [], []
    real_scorer, real_write = script.network_scorer, report.write_ranks
    monkeypatch.setattr(script, "code_state", lambda: clean_tree)
    monkeypatch.setattr(script, "network_scorer", lambda run: fake_scores(calls))
    monkeypatch.setattr(script, "checkpoint_sha", lambda run: script.FROZEN_SHA256[run])
    monkeypatch.setattr(addon, "load_kb", lambda kb_id: (kb, script.FROZEN_SHA256[kb_id]))
    monkeypatch.setattr(addon, "load_bundle", lambda b, kb_id: (addon_bundle(), script.FROZEN_SHA256[b]))
    monkeypatch.setattr(sexrule, "load_kb", lambda kb_id: (SEX_KB, script.FROZEN_SHA256[kb_id]))
    monkeypatch.setattr(script, "knowledge_of", lambda kb, kb_id: Knowledge(kb, GENES, None, kb_id))
    monkeypatch.setattr(script, "e0_scorer", lambda: fake_scores(calls))
    monkeypatch.setattr(
        report, "write_ranks", lambda path, r: (written.append(Path(path).name), real_write(path, r))
    )
    return SimpleNamespace(
        script=script,
        calls=calls,
        written=written,
        loaded=confirm_fold,
        protocol=protocol,
        real_scorer=real_scorer,
        out=tmp_path / "out" / "confirm2.json",
        ranks=tmp_path / "out" / "ranks",
    )


def wrong_hash(module, name):
    def breaks(v, mp):
        load = getattr(module, name)
        mp.setattr(module, name, lambda *a: (load(*a)[0], "0" * 64))

    return breaks


def unverified_sex_kb(v, mp):
    def load_kb(kb_id):
        raise LineageError(f"{kb_id}: not a verified sex-kb")

    mp.setattr(sexrule, "load_kb", load_kb)


def ledger_with(*rows):
    return lambda v, mp: folds.CONFIRM_LEDGER.write_text(folds.LEDGER_HEADER + "".join(rows))


REFUSALS = {
    "empty reason": (lambda v, mp: " ", "reason"),
    "no DXT_P3_CONFIRM": (lambda v, mp: mp.delenv(folds.CONFIRM_ENV), folds.CONFIRM_ENV),
    "no protocol": (lambda v, mp: v.protocol.unlink(), "committed"),
    "uncommitted protocol": (lambda v, mp: v.protocol.write_text("draft"), "committed"),
    "dirty tree": (lambda v, mp: mp.setattr(v.script, "code_state", lambda: DIRTY), "SHA"),
    "no ledger": (lambda v, mp: folds.CONFIRM_LEDGER.unlink(), "exactly 1"),
    "ledger without the first read": (ledger_with(), "exactly 1"),
    "second read already done": (ledger_with(FIRST_READ, FIRST_READ), "exactly 1"),
    "output exists": (lambda v, mp: (v.out.parent.mkdir(), v.out.write_text("{}")), "never overwritten"),
    "ranks exist": (lambda v, mp: v.ranks.mkdir(parents=True), "never overwritten"),
    "network trained on folds 0-2": (lambda v, mp: untrained_on_0_3(v, mp), "folds 0-3"),
    "network without last.pt": (lambda v, mp: untrained_on_0_3(v, mp, (0, 1, 2, 3), False), "folds 0-3"),
    "checkpoint hash": (lambda v, mp: mp.setattr(v.script, "checkpoint_sha", lambda run: "0"), "frozen"),
    "add-on knowledge hash": (wrong_hash(addon, "load_kb"), "frozen"),
    "add-on bundle hash": (wrong_hash(addon, "load_bundle"), "frozen"),
    "sex knowledge hash": (wrong_hash(sexrule, "load_kb"), "frozen"),
    "unverified sex knowledge": (unverified_sex_kb, "verified"),
}


def ledger_text():
    return folds.CONFIRM_LEDGER.read_text() if folds.CONFIRM_LEDGER.exists() else None


@pytest.mark.parametrize("refusal", REFUSALS)
def test_confirm2_refusals_come_before_any_load(c2, monkeypatch, refusal):
    breaks, message = REFUSALS[refusal]
    reason = breaks(c2, monkeypatch)
    before = ledger_text()
    out_before = c2.out.read_text() if c2.out.exists() else None
    ranks_before = c2.ranks.exists()
    with pytest.raises(LineageError, match=message):
        c2.script.run(reason if isinstance(reason, str) else "go", c2.out, c2.ranks)
    assert not c2.loaded and not c2.calls and not c2.written
    assert ledger_text() == before
    assert (c2.out.read_text() if c2.out.exists() else None) == out_before
    assert c2.ranks.exists() == ranks_before and not (ranks_before and any(c2.ranks.iterdir()))


def test_confirm2_opens_fold_4_once_and_writes_its_outputs(c2, tmp_path):
    script = c2.script
    summary = script.run("Mateo's go", c2.out, c2.ranks)
    assert c2.loaded == [("p3-v1", splits.Part.TRAIN)]
    rows = script.confirm_rows()
    assert len(rows) == 2 and rows[0] == FIRST_READ.strip() and "Mateo's go" in rows[1]
    assert json.loads(c2.out.read_text()) == json.loads(json.dumps(summary, default=str))
    assert c2.written == [f"{n}.ranks.jsonl" for n in SYSTEMS]
    ranks = {n: {r["case_id"]: r for r in report.read_ranks(c2.ranks / f"{n}.ranks.jsonl")} for n in SYSTEMS}
    fold4 = [f"c{i}" for i in range(60) if folds.fold_of(f"PMID:{i}") == folds.CONFIRM_FOLD]
    assert sorted(ranks["E0"]) == sorted(fold4) and {r["fold"] for r in ranks["E0"].values()} == {4}
    rank = {n: {c: r["rank"] for c, r in x.items()} for n, x in ranks.items()}
    by_gene = {g: [c for c, r in ranks["E0"].items() if r["gene"] == g] for g in GENES[1:]}
    assert by_gene["G1"] and by_gene["G3"]

    g = summary["gate"]
    harmed = sorted(c for c in fold4 if rank["F3"][c] > rank["F1"][c])
    assert g["sex_rule_harmed"] == len(harmed) and harmed == sorted(by_gene["G3"])
    f1, f2 = (np.array([rank[n][c] for c in fold4]) for n in ("F1", "F2"))
    assert g["addon_helped_minus_harmed"] == np.sum(f1 < f2) - np.sum(f1 > f2) == -len(by_gene["G1"])
    x = summary["readings"]["F3_vs_E0"]["uncited"]
    assert g["pass_primary"] == (x["delta_mrr_cap_ci95"][0] > 0)
    assert g["F3_vs_E0"]["delta"] == x["delta"]["mrr_cap"] and g["F3_vs_E0"]["n"] == len(fold4)
    assert set(summary["readings"]) == set(script.PAIRS)
    for reading in summary["readings"].values():
        assert {"uncited", "uncited_in_vocab", "all"} <= set(reading)
        metrics = {"mrr", "mrr_cap", "top1", "top10", "delta_mrr_ci95", "delta_mrr_cap_ci95"}
        assert metrics <= set(reading["all"])
    impossible = summary["sex_rule"]["true_gene_impossible"]
    assert sorted(r["case_id"] for r in impossible) == sorted(by_gene["G3"])
    view = summary["sex_rule"]["doctor_view"]
    assert all(view[n]["shown"][k]["patients"] == len(fold4) for n in ("F2", "F1") for k in sexrule.TOP_K)
    assert view["F3"]["shown"][1] == {"patients": 0, "genes": 0}
    assert view["F3"]["shown"][5] == {"patients": len(fold4), "genes": len(fold4)}
    sex_kb = summary["frozen_system"]["sex_kb"]
    assert sex_kb == {"id": "sex-kb-v3", "sha256": script.FROZEN_SHA256["sex-kb-v3"]}
    assert not summary["dry_run_fold_3"]

    with pytest.raises(LineageError, match="exactly 1"):
        script.run("again", tmp_path / "again.json", tmp_path / "again")
    assert len(c2.loaded) == 1 and len(script.confirm_rows()) == 2


def test_confirm2_dry_run_reads_fold_3_without_the_gate(c2, monkeypatch, tmp_path):
    monkeypatch.delenv(folds.CONFIRM_ENV)
    monkeypatch.setattr(c2.script, "code_state", lambda: DIRTY)
    c2.protocol.unlink()
    folds.CONFIRM_LEDGER.unlink()
    cases = [case(i, gene=GENES[1 + i % 3]) for i in range(30)]
    groups = {c.case_id: f"PMID:{c.case_id[1:]}" for c in cases}
    status = dict.fromkeys(groups.values(), patients.UNCITED)
    fold3 = patients.annotate(cases, groups, status, lambda g: 3, keep_excluded=True)
    monkeypatch.setattr(patients, "load_addon", lambda folds_: fold3 if folds_ == (3,) else [])
    summary = c2.script.run("dry run", c2.out, c2.ranks, dry_run=True)
    assert summary["dry_run_fold_3"] and summary["size"]["n"] == 30
    assert not c2.loaded and not folds.CONFIRM_LEDGER.exists() and c2.out.exists()
    assert c2.written == [f"{n}.ranks.jsonl" for n in SYSTEMS]
    with pytest.raises(LineageError, match="reason"):
        c2.script.run("", tmp_path / "x.json", tmp_path / "x", dry_run=True)
