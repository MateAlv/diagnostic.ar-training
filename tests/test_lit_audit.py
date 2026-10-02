import json
import sys

import pytest
from typer.testing import CliRunner

from diagnostic_ar_training import cli_lit_extract as cli
from diagnostic_ar_training.knowledge import lit_audit as la
from diagnostic_ar_training.knowledge.lit_extract import ROW_COLUMNS

SOURCES = {f"C{n:03d}": [f"NBK{n}{k}" for k in range(1, 11)] for n in (1, 2, 36)} | {
    "Q001": [f"PMID:{k}" for k in range(1, 13)]
}


# --- sample -------------------------------------------------------------------------


def test_sample_is_deterministic_and_every_shard_contributes():
    first = la.sample(SOURCES, 0.05, 20261002)
    assert first == la.sample(SOURCES, 0.05, 20261002)
    assert {shard for shard, _ in first} == set(SOURCES)
    assert first != la.sample(SOURCES, 0.05, 1)
    assert all(source in SOURCES[shard] for shard, source in first)


def test_sample_takes_at_least_two_sources_from_c036_and_one_elsewhere():
    picks = la.sample(SOURCES, 0.05, 20261002)
    counts = {s: sum(shard == s for shard, _ in picks) for s in SOURCES}
    assert counts == {"C001": 1, "C002": 1, "C036": 2, "Q001": 1}


def test_a_shards_draw_does_not_move_when_other_shards_change():
    before = [p for p in la.sample(SOURCES, 0.5, 7) if p[0] == "C001"]
    after = [p for p in la.sample(SOURCES | {"C099": ["NBK9"]}, 0.5, 7) if p[0] == "C001"]
    assert before == after


def test_the_fraction_raises_the_draw_above_the_floor():
    picks = la.sample(SOURCES, 0.5, 7)
    assert sum(shard == "C001" for shard, _ in picks) == 5
    assert sum(shard == "C036" for shard, _ in picks) == 5


def test_a_single_source_shard_gives_its_only_source_even_with_a_floor_of_two():
    assert la.sample({"C036": ["NBK1"]}, 0.05, 1) == [("C036", "NBK1")]


# --- source cut ---------------------------------------------------------------------

TEXT = "\n".join(
    [
        "# Title",
        "## Clinical Description",
        *[f"description line {i} " + "x" * 40 for i in range(200)],
        "## Management",
        "management line",
        "[Table 2] Features",
        "Feature | % of Persons",
        "Seizures | 40%",
        "[/Table 2]",
    ]
)


def test_cut_source_keeps_the_cited_section_and_the_tables_within_the_cap():
    cut = la.cut_source(TEXT, ["Clinical Description"], cap=3000)
    assert "Seizures | 40%" in cut and "description line 0 " in cut
    assert "management line" not in cut
    assert len(cut) <= 3000 + len(la.TRUNCATED) + 40
    assert cut.rstrip().endswith(la.TRUNCATED)


def test_cut_source_without_citations_starts_with_the_tables():
    cut = la.cut_source(TEXT, [], cap=3000)
    assert cut.startswith("[Table 2] Features") and "Seizures | 40%" in cut


def test_cut_source_marks_gaps_and_does_not_repeat_a_table_inside_a_cited_section():
    text = "# A\nalpha\n# B\nbeta\n[Table 1] t\nrow | 1\n[/Table 1]\n# C\ngamma"
    cut = la.cut_source(text, ["A", "Table 1"], cap=1000)
    assert cut == "# A\nalpha\n[...]\n[Table 1] t\nrow | 1\n[/Table 1]\n"
    assert la.TRUNCATED not in cut


def test_cut_source_falls_back_to_the_beginning_when_nothing_matches():
    cut = la.cut_source("# A\nalpha\nbeta", ["Missing"], cap=1000)
    assert cut == "# A\nalpha\nbeta\n"


# --- answers ------------------------------------------------------------------------

ANSWER = {
    "ok": False,
    "wrong_unit": [{"row": 3, "reason": "figure is for type 2"}, {"row": 99, "reason": "unknown"}],
    "missed": [{"feature": "Ptosis", "stated_number": "30%", "quote": "Ptosis | 30%"}],
    "bad_row": [{"row": 2, "reason": "conditional share"}],
}


def row(**kw):
    base = {c: "" for c in ROW_COLUMNS}
    return (
        base | {"gene": "G1", "disease_id": "OMIM:1", "feature_label": "Seizures", "evidence_quote": "q"} | kw
    )


def test_parse_answer_checks_the_schema_shape():
    assert la.parse_answer(ANSWER)["missed"][0]["stated_number"] == "30%"
    for bad in ({}, {"ok": True, "wrong_unit": [], "missed": [{"feature": "x"}], "bad_row": []}, [], None):
        with pytest.raises(ValueError):
            la.parse_answer(bad)


def test_the_schema_requires_every_field():
    schema = json.loads(la.schema_json())
    assert schema["required"] == ["ok", "wrong_unit", "missed", "bad_row"]
    assert schema["additionalProperties"] is False


def test_issues_flag_row_numbers_that_are_not_the_items_rows():
    item = {"item": "0001", "shard": "C001", "source_id": "NBK1"}
    found = la.issues(item, la.parse_answer(ANSWER), {2: row(), 3: row(gene="G2", disease_id="OMIM:2")})
    by = {(i["kind"], i.get("row", ""), i["valid"]) for i in found}
    assert by == {
        ("wrong_unit", 3, "true"),
        ("wrong_unit", 99, "false"),
        ("missed", "", "true"),
        ("bad_row", 2, "true"),
    }
    assert next(i for i in found if i.get("row") == 3)["gene"] == "G2"


def test_summary_counts_per_shard_and_ignores_unanswered_items():
    items = [
        {"item": "0001", "shard": "C001", "source_id": "NBK1"},
        {"item": "0002", "shard": "C001", "source_id": "NBK2"},
        {"item": "0003", "shard": "C002", "source_id": "NBK3"},
    ]
    clean = la.parse_answer({"ok": True, "wrong_unit": [], "missed": [], "bad_row": []})
    dirty = la.parse_answer(ANSWER)
    results = [
        {"item": "0001", "answer": clean, "issues": []},
        {"item": "0002", "answer": dirty, "issues": la.issues(items[1], dirty, {2: row(), 3: row()})},
    ]
    summary = la.summarise(results, items, {"0001": 4, "0002": 5, "0003": 1})
    c1, c2 = summary["by_shard"]["C001"], summary["by_shard"]["C002"]
    assert (c1["sources"], c1["answered"], c1["sources_with_issue"], c1["share_sources_with_issue"]) == (
        2,
        2,
        1,
        0.5,
    )
    assert (c1["wrong_unit_rows"], c1["missed_facts"], c1["bad_rows"], c1["invalid_row_numbers"]) == (
        1,
        1,
        1,
        1,
    )
    assert c1["rows_audited"] == 9
    assert c2["answered"] == 0 and c2["share_sources_with_issue"] is None
    assert summary["total"]["sources"] == 3 and summary["total"]["sources_with_issue"] == 1


def test_ok_false_with_no_entries_still_counts_as_an_issue():
    answer = la.parse_answer({"ok": False, "wrong_unit": [], "missed": [], "bad_row": []})
    assert la.has_issue(answer)
    summary = la.summarise(
        [{"item": "1", "answer": answer, "issues": []}], [{"item": "1", "shard": "C001"}], {"1": 0}
    )
    assert summary["total"]["ok_false_without_entries"] == 1


def test_prompt_spells_out_the_guides_skip_rules():
    for needle in (
        "inferred",
        "complement",
        "conditional",
        "bundle",
        "at least 20",
        "evaluation units",
        "newborn",
        "has not been reported",
    ):
        assert needle in la.PROMPT


def test_rows_table_uses_shard_file_lines_and_flat_cells():
    r = row(hpo_id="HP:1", prevalence="0.5", evidence_quote="a\tb", construction_unit="G1|OMIM:1")
    lines = la.rows_table([(7, r)], {"HP:1": "Seizure"}).splitlines()
    assert lines[0].split("\t")[:4] == ["row", "feature", "hpo_id", "hpo_label"]
    cells = lines[1].split("\t")
    assert cells[0] == "7" and cells[3] == "Seizure" and cells[-1] == "a b"
    assert len(cells) == len(la.ROWS_COLUMNS)


# --- run and score ------------------------------------------------------------------


@pytest.fixture
def audit_env(tmp_path, monkeypatch):
    work, audit, rows_dir = tmp_path / "work", tmp_path / "audit", tmp_path / "rows"
    for d in (work, audit, rows_dir):
        d.mkdir()
    for attr, value in (
        ("WORK_DIR", work),
        ("AUDIT_DIR", audit),
        ("ROWS_DIR", rows_dir),
        ("REPO_ROOT", tmp_path),
    ):
        monkeypatch.setattr(cli, attr, value)
    lines = ["\t".join(ROW_COLUMNS)]
    for source in ("NBK1", "NBK1", "NBK2"):
        r = row(source_id=source)
        lines.append("\t".join(r[c] for c in ROW_COLUMNS))
    (rows_dir / "C001.tsv").write_text("\n".join(lines) + "\n")
    items = ["item\tshard\tsource_id\tsource_kind\toutcome\trows\tsource_chars"]
    items += [
        "0001\tC001\tNBK1\tgenereviews\textracted\t2\t10",
        "0002\tC001\tNBK2\tgenereviews\textracted\t1\t10",
    ]
    (audit / "t.items.tsv").write_text("\n".join(items) + "\n")
    folders = work / "audit" / "t" / "items"
    for item in ("0001", "0002"):
        (folders / item).mkdir(parents=True)
        for f in ("prompt.txt", "source.txt", "units.txt", "rows.tsv"):
            (folders / item / f).write_text(f"{f} of {item}\n")
    (work / "audit" / "t" / "schema.json").write_text(la.schema_json())
    return tmp_path


def fake_auditor(tmp_path, fail_item=""):
    script = tmp_path / "fake.py"
    script.write_text(
        "import json, os, sys\n"
        "stdin = sys.stdin.read()\n"
        f"open({str(tmp_path / 'calls.log')!r}, 'a').write(os.path.basename(os.getcwd()) + chr(10))\n"
        f"if os.path.basename(os.getcwd()) == {fail_item!r}: sys.exit(3)\n"
        "assert 'source.txt of' in stdin and 'units.txt of' in stdin and 'rows.tsv of' in stdin\n"
        "assert stdin.index('source.txt') < stdin.index('units.txt') < stdin.index('rows.tsv')\n"
        "answer = {'ok': True, 'wrong_unit': [], 'missed': [], 'bad_row': []}\n"
        "if os.path.basename(os.getcwd()) == '0002':\n"
        "    answer = {'ok': False, 'wrong_unit': [{'row': 4, 'reason': 'other subtype'}],\n"
        "              'missed': [{'feature': 'Ptosis', 'stated_number': '30%', 'quote': 'Ptosis | 30%'}],\n"
        "              'bad_row': [{'row': 2, 'reason': 'not mine'}]}\n"
        "json.dump(answer, open(sys.argv[1], 'w'))\n"
    )
    return f"{sys.executable} {script} {{answer}}"


def invoke(*args):
    return CliRunner().invoke(cli.extract_app, ["audit", *args])


def test_run_is_resumable_and_retries_failures(audit_env):
    calls = audit_env / "calls.log"
    failing = fake_auditor(audit_env, fail_item="0002")
    result = invoke("run", "--name", "t", "--workers", "1", "--command", failing)
    assert result.exit_code == 1 and "1 items failed" in result.output
    items = audit_env / "work" / "audit" / "t" / "items"
    assert (items / "0001" / "answer.json").is_file() and not (items / "0002" / "answer.json").is_file()
    result = invoke("run", "--name", "t", "--workers", "1", "--command", fake_auditor(audit_env))
    assert result.exit_code == 0 and "1 to ask" in result.output
    assert calls.read_text().split() == ["0001", "0002", "0002"]
    assert invoke("run", "--name", "t", "--command", fake_auditor(audit_env)).output.startswith(
        "2 items, 0 to ask"
    )
    assert calls.read_text().split() == ["0001", "0002", "0002"]


def test_run_limit_caps_the_pending_items(audit_env):
    result = invoke(
        "run", "--name", "t", "--workers", "1", "--limit", "1", "--command", fake_auditor(audit_env)
    )
    assert result.exit_code == 0 and "2 items, 1 to ask" in result.output
    assert (audit_env / "calls.log").read_text().split() == ["0001"]


def test_score_summarises_per_shard_and_keeps_resolutions(audit_env):
    assert invoke("run", "--name", "t", "--workers", "1", "--command", fake_auditor(audit_env)).exit_code == 0
    result = invoke("score", "--name", "t")
    assert result.exit_code == 0, result.output
    summary = json.loads((audit_env / "audit" / "t.summary.json").read_text())
    c = summary["by_shard"]["C001"]
    assert (c["sources"], c["answered"], c["sources_with_issue"]) == (2, 2, 1)
    assert (c["wrong_unit_rows"], c["missed_facts"], c["bad_rows"], c["invalid_row_numbers"]) == (1, 1, 0, 1)
    assert summary["missing"] == [] and summary["issues_unresolved"] == 3
    issues = (audit_env / "audit" / "t.issues.tsv").read_text().splitlines()
    header = issues[0].split("\t")
    assert len(issues) == 4 and "resolution" in header
    edited = [issues[0]] + [i + "fixed" if "Ptosis" in i else i for i in issues[1:]]
    (audit_env / "audit" / "t.issues.tsv").write_text("\n".join(edited) + "\n")
    invoke("score", "--name", "t")
    assert json.loads((audit_env / "audit" / "t.summary.json").read_text())["issues_unresolved"] == 2


def test_score_reports_missing_and_unparseable_answers(audit_env):
    items = audit_env / "work" / "audit" / "t" / "items"
    (items / "0001" / "answer.json").write_text("not json")
    result = invoke("score", "--name", "t")
    assert result.exit_code == 0, result.output
    summary = json.loads((audit_env / "audit" / "t.summary.json").read_text())
    assert summary["unparseable"] == ["0001"] and summary["missing"] == ["0002"] and summary["answered"] == 0


def test_score_refuses_when_the_rows_changed_since_prepare(audit_env):
    path = audit_env / "rows" / "C001.tsv"
    path.write_text("\n".join(path.read_text().splitlines()[:2]) + "\n")
    result = invoke("score", "--name", "t")
    assert result.exit_code != 0 and "rows changed since prepare" in str(result.exception)
