import json
from collections import Counter

import pytest

from diagnostic_ar_training.knowledge import literature_panel as lp
from diagnostic_ar_training.ontology import Ontology

ONTOLOGY = Ontology(
    parents={
        "HP:0000001": (),
        "HP:0000118": ("HP:0000001",),
        "HP:0000707": ("HP:0000118",),  # nervous system
        "HP:0001250": ("HP:0000707",),
        "HP:0001251": ("HP:0000707",),
        "HP:0001626": ("HP:0000118",),  # cardiovascular
        "HP:0001631": ("HP:0001626",),
        "HP:0000005": ("HP:0000001",),
        "HP:0000006": ("HP:0000005",),
        "HP:0000007": ("HP:0000005",),
        "HP:0001417": ("HP:0000005",),
        "HP:0001419": ("HP:0001417",),
    },
    labels={"HP:0000707": "Abnormality of the nervous system", "HP:0001250": "Seizure"},
    alt_ids={"HP:9999999": "HP:0001250"},
    replaced_by={},
    obsolete=frozenset(),
)


def unit(gene, organ="HP:0000707", inh="AD", train=0, dev=0, disease=None):
    return lp.Unit(
        gene=gene,
        symbol=gene,
        disease_id=disease or f"OMIM:{abs(hash(gene)) % 10**6}",
        disease_ids=(disease or f"OMIM:{abs(hash(gene)) % 10**6}",),
        disease_name="d",
        organ_system=organ,
        organ_system_label=organ,
        inheritance=inh,
        r1_train_patients=train,
        r1_dev_patients=dev,
        orphanet_prevalence=None,
        sim_weight=1.0,
    )


def test_inheritance_class():
    assert lp.inheritance_class(["HP:0000006"], ONTOLOGY) == "AD"
    assert lp.inheritance_class(["HP:0001419"], ONTOLOGY) == "XL"
    assert lp.inheritance_class(["HP:0000006", "HP:0000007"], ONTOLOGY) == "other"
    assert lp.inheritance_class([], ONTOLOGY) == "other"


def test_organ_system_is_the_modal_top_level_branch():
    assert lp.organ_system({"HP:0001250", "HP:0001251", "HP:0001631"}, ONTOLOGY) == "HP:0000707"
    assert lp.organ_system(set(), ONTOLOGY) == "none"
    # ties go to the smaller id
    assert lp.organ_system({"HP:0001250", "HP:0001631"}, ONTOLOGY) == "HP:0000707"


def test_train_bins():
    assert [unit("A", train=n).train_bin for n in (0, 1, 9, 10)] == ["0", "1-9", "1-9", ">=10"]


def test_units_pick_the_heaviest_simulable_entity_and_count_both_spellings():
    built = {
        "vocabulary": {"OLD": "NEW", "NOPE": None},
        "genes": {
            "NEW": {
                "entities": [
                    {"entity": "OMIM:1", "ids": ["OMIM:1"], "profile_ids": ["OMIM:1"], "simulable": True,
                     "sim_weight": 0.3, "inheritance": ["HP:0000007"], "prevalence": None},
                    {"entity": "OMIM:2", "ids": ["OMIM:2", "ORPHA:2"], "profile_ids": ["OMIM:2"],
                     "simulable": True, "sim_weight": 0.7, "inheritance": ["HP:0000006"], "prevalence": 5e-5},
                    {"entity": "OMIM:3", "ids": ["OMIM:3"], "profile_ids": [], "simulable": False,
                     "sim_weight": 0.0, "inheritance": [], "prevalence": None},
                ]
            }
        },
    }  # fmt: skip
    out = lp.units(
        built,
        ONTOLOGY,
        {"OMIM:2": {"HP:0001631"}},
        {"ORPHA:2": "Two"},
        Counter({"OLD": 3, "NEW": 4}),
        Counter({"NEW": 12}),
    )
    assert len(out) == 1
    u = out[0]
    assert (u.gene, u.symbol, u.disease_id, u.inheritance) == ("OLD", "NEW", "OMIM:2", "AD")
    assert u.organ_system == "HP:0001626" and u.disease_name == "Two"
    assert (u.r1_train_patients, u.r1_dev_patients) == (7, 12)


def _pool():
    pool = []
    organs = ["HP:0000707", "HP:0001626", "HP:0000478"]
    for i in range(120):
        pool.append(
            unit(
                f"G{i:03d}",
                organ=organs[i % 3],
                inh=("AD", "AR", "XL", "other")[i % 4],
                train=(0, 3, 20)[i % 5 % 3],
                dev=15 if i % 7 == 0 else 0,
            )
        )
    return pool


def test_select_is_deterministic_and_respects_quotas():
    pool = _pool()
    anchors = ("G000", "G001")
    a = lp.select(pool, anchors=anchors, size=20, reserves=5, seed=1)
    b = lp.select(list(reversed(pool)), anchors=anchors, size=20, reserves=5, seed=1)
    assert [u.gene for u, _ in a] == [u.gene for u, _ in b]
    roles = Counter(r for _, r in a)
    assert roles == {"anchor": 2, "sampled": 18, "reserve": 5}
    assert [u.gene for u, r in a if r == "anchor"] == list(anchors)
    assert len({u.gene for u, _ in a}) == 25
    sampled = [u for u, r in a if r == "sampled"]
    assert sum(u.r1_dev_patients >= 10 for u in sampled) == 9
    assert {u.inheritance for u in sampled} == {"AD", "AR", "XL", "other"}
    c = lp.select(pool, anchors=anchors, size=20, reserves=5, seed=2)
    assert [u.gene for u, _ in a] != [u.gene for u, _ in c]


def test_select_rejects_missing_anchor():
    with pytest.raises(ValueError, match="anchor"):
        lp.select(_pool(), anchors=("NOPE",), size=5, reserves=0)


def test_split_rows_roundtrip(tmp_path):
    rows = lp.split_rows(lp.select(_pool(), anchors=("G000",), size=4, reserves=1, seed=3))
    path = tmp_path / "split.tsv"
    lp.write_tsv(rows, lp.SPLIT_COLUMNS, path)
    back = lp.read_tsv(path)
    assert [r["gene"] for r in back] == [r["gene"] for r in rows]
    assert back[0]["role"] == "anchor" and back[-1]["role"] == "reserve"
    summary = lp.split_summary(back, _pool())
    assert summary["panel_units"] == 4 and summary["reserve_units"] == 1


SPLIT = [{"gene": "NF1", "disease_ids": "OMIM:162200;ORPHA:636"}]


def curated(**overrides):
    row = {
        "gene": "NF1",
        "disease_id": "OMIM:162200",
        "disease_name": "NF1",
        "feature_label": "Seizure",
        "hpo_id": "HP:0001250",
        "prevalence": "0.06",
        "prevalence_low": "0.04",
        "prevalence_high": "0.08",
        "n_affected": "",
        "n_assessed": "",
        "sex_restriction": "",
        "age_note": "",
        "population": "all NF1",
        "source_kind": "cohort_paper",
        "citation": "Smith 2020, PMID:111",
        "section": "Table 2",
        "evidence_quote": "Seizures occurred in 6% of patients.",
        "access_path": "europepmc",
    }
    row.update(overrides)
    return row


def test_validate_rows_accepts_and_annotates():
    rows, problems = lp.validate_rows([curated()], SPLIT, ONTOLOGY, set(), {})
    assert problems == []
    assert rows[0]["independent"] == "true" and rows[0]["source_pmids"] == "111"
    assert rows[0]["hpo_label"] == "Seizure" and rows[0]["source_r1_part"] == "none"


def test_validate_rows_flags_dependence_on_construction():
    rows, _ = lp.validate_rows([curated()], SPLIT, ONTOLOGY, {"111"}, {})
    assert rows[0]["source_in_hpoa"] == "true" and rows[0]["independent"] == "false"
    rows, _ = lp.validate_rows([curated()], SPLIT, ONTOLOGY, set(), {"111": "train"})
    assert rows[0]["source_r1_part"] == "train" and rows[0]["independent"] == "false"
    rows, _ = lp.validate_rows([curated()], SPLIT, ONTOLOGY, set(), {"111": "heldout"})
    assert rows[0]["independent"] == "true"
    rows, _ = lp.validate_rows(
        [curated(source_kind="orphanet", citation="ORPHA:636")], SPLIT, ONTOLOGY, set(), {}
    )
    assert rows[0]["independent"] == "false"


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"gene": "FBN1"}, "not an evaluation unit"),
        ({"disease_id": "OMIM:1"}, "not the unit's disease"),
        ({"hpo_id": "HP:9999999"}, "not a current HPO id"),
        ({"prevalence": "1.4", "prevalence_high": ""}, "in [0, 1]"),
        ({"prevalence": "0.2"}, "outside its range"),
        ({"source_kind": "omim"}, "source_kind"),
        ({"evidence_quote": " ".join(["word"] * 26)}, "longer than 25"),
        ({"citation": ""}, "required"),
    ],
)
def test_validate_rows_problems(override, message):
    _, problems = lp.validate_rows([curated(**override)], SPLIT, ONTOLOGY, set(), {})
    assert any(message in p for p in problems), problems


def test_validate_rows_rejects_duplicates():
    _, problems = lp.validate_rows([curated(), curated()], SPLIT, ONTOLOGY, set(), {})
    assert any("duplicate" in p for p in problems)


def test_hpoa_helpers(tmp_path):
    path = tmp_path / "phenotype.hpoa"
    header = "\t".join(
        ["database_id", "disease_name", "qualifier", "hpo_id", "reference", "evidence", "onset"]
        + ["frequency", "sex", "modifier", "aspect", "biocuration"]
    )
    lines = [
        "#description: x",
        header,
        "OMIM:1\tOne\t\tHP:0001250\tPMID:5;OMIM:1\tPCS\t\t\t\t\tP\tx",
        "OMIM:1\tOne\t\tHP:0001631\tPMID:6\tPCS\t\t\t\t\tP\tx",
        "OMIM:1\tOne\tNOT\tHP:0001251\tPMID:7\tPCS\t\t\t\t\tP\tx",
        "OMIM:1\tOne\t\tHP:0000006\tOMIM:1\tIEA\t\t\t\t\tI\tx",
    ]
    path.write_text("\n".join(lines) + "\n")
    terms, names = lp.hpoa_phenotypes(path, ONTOLOGY, {"PMID:6"})
    assert terms == {"OMIM:1": {"HP:0001250"}} and names == {"OMIM:1": "One"}
    assert lp.hpoa_cited_pmids(path) == {"5", "6", "7"}


def test_crosscheck_sample_is_seeded():
    rows = [{}] * 95
    a = lp.crosscheck_sample(rows, seed=7)
    assert len(a) == 10 and a == lp.crosscheck_sample(rows, seed=7)
    assert a != lp.crosscheck_sample(rows, seed=8)


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (
            {"prevalence": "0.5", "prevalence_low": "0.4", "prevalence_high": "0.6"},
            {"prevalence": "0.62"},
            False,
        ),
        (
            {"prevalence": "0.3", "prevalence_low": "0.2", "prevalence_high": "0.45"},
            {"prevalence": "0.7", "prevalence_low": "0.45", "prevalence_high": "0.9"},
            True,
        ),
        ({"prevalence": "0.5"}, {"prevalence": "0.6"}, True),
        ({"prevalence": "0.5"}, {"prevalence": "0.65"}, False),
        (
            {"prevalence": "0.9", "prevalence_low": "0.8", "prevalence_high": "1"},
            {"prevalence": "0.3"},
            False,
        ),
        ({"prevalence": "0.5"}, {"prevalence": ""}, False),
    ],
)
def test_agrees(a, b, expected):
    assert lp.agrees(a, b) is expected


def test_r1_pmid_parts():
    parts = lp.r1_pmid_parts({"PMID:1", "PMID:2"}, {"PMID:2"})
    assert parts == {"1": "train", "2": "heldout"}


def test_crosscheck_prompt_never_leaks_our_values():
    row = curated(prevalence="0.4321", prevalence_low="0.1234", prevalence_high="0.9876")
    prompt = lp.crosscheck_prompt(row, "/tmp/source.txt")
    assert all(s in prompt for s in ("NF1", "Seizure", "PMID:111", "Table 2", "/tmp/source.txt"))
    assert not any(v in prompt for v in ("0.4321", "0.1234", "0.9876", "6% of patients"))


def test_parse_answer():
    last = '{"found": true, "prevalence": 0.5, "prevalence_low": null, "prevalence_high": 0.6, "quote": "q"}'
    assert lp.parse_answer("Reasoning...\n" + last) == {
        "found": True,
        "prevalence": "0.5",
        "prevalence_low": "",
        "prevalence_high": "0.6",
        "quote": "q",
    }
    with pytest.raises(ValueError):
        lp.parse_answer("no json here")


def test_panel_summary_counts_sources_and_independence():
    unit = {
        "gene": "NF1",
        "rank": "1",
        "role": "anchor",
        "organ_system_label": "N",
        "inheritance": "AD",
        "train_bin": ">=10",
        "r1_dev_patients": "151",
        "disease_ids": "OMIM:162200;ORPHA:636",
    }
    curated_rows = [curated(hpo_id="HP:0001250"), curated(hpo_id="HP:0001251")]
    curated_rows.append(curated(hpo_id="HP:0001631", source_kind="orphanet", citation="ORPHA:636"))
    rows, problems = lp.validate_rows(curated_rows, [unit], ONTOLOGY, set(), {})
    assert problems == []
    s = lp.panel_summary(rows, [unit], [{"gene": "X", "reason": "no numbers"}])
    assert s["rows"] == 3 and s["units"] == 1 and s["rows_independent"] == 2
    assert s["rows_by_source_kind"] == {"cohort_paper": 2, "orphanet": 1}
    assert s["units_with_5_independent_rows"] == 0 and s["dropped"][0]["gene"] == "X"


def test_crosscheck_and_build_commands(tmp_path, monkeypatch, clean_tree):
    from typer.testing import CliRunner

    from diagnostic_ar_training import cli
    from diagnostic_ar_training.lineage import manifest as manifest_mod

    working = tmp_path / "working.tsv"
    rows = [curated(hpo_id=h, source_text_file="/tmp/src.txt") for h in ("HP:0001250", "HP:0001251")]
    lp.write_tsv(rows, (*lp.CURATED_COLUMNS, "source_text_file"), working)
    answers = iter(
        [
            json.dumps({"found": True, "prevalence": 0.06, "prevalence_low": 0.04, "prevalence_high": 0.08}),
            json.dumps({"found": True, "prevalence": 0.5, "prevalence_low": None, "prevalence_high": None}),
        ]
    )
    seen = []

    def fake_run(args, **kwargs):
        seen.append(args)
        return type("R", (), {"stdout": next(answers)})()

    monkeypatch.setattr("subprocess.run", fake_run)
    out = tmp_path / "extraction" / "crosscheck.tsv"
    out.parent.mkdir()
    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        ["litpanel", "crosscheck", "--rows", str(working), "--out", str(out), "--fraction", "1",
         "--log-dir", str(tmp_path / "logs"), "--command", "fake-model --flag"],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert seen[0][:2] == ["fake-model", "--flag"] and "0.06" not in seen[0][-1]
    checked = lp.read_tsv(out)
    assert [r["agree"] for r in checked] == ["true", "false"]

    monkeypatch.setattr(cli, "REALISM_DIR", tmp_path)
    monkeypatch.setattr(manifest_mod, "MANIFESTS_DIR", tmp_path / "manifests")
    split_path = tmp_path / "litpanel-split-test.tsv"
    unit = {"rank": 1, "role": "anchor", "gene": "NF1", "disease_ids": "OMIM:162200", "r1_dev_patients": 151}
    lp.write_tsv([unit], lp.SPLIT_COLUMNS, split_path)
    split_manifest = manifest_mod.build_manifest(
        "litpanel-split-test", "litpanel-split", [], {}, [split_path]
    )
    monkeypatch.setattr(manifest_mod, "load_manifest", lambda _id: split_manifest)
    monkeypatch.setattr(
        "diagnostic_ar_training.lineage.registry.open_source", lambda name, purpose: tmp_path / name
    )
    monkeypatch.setattr(Ontology, "from_json", classmethod(lambda cls, path: ONTOLOGY))
    monkeypatch.setattr(lp, "hpoa_cited_pmids", lambda path: set())
    lp.write_tsv([{k: v for k, v in r.items() if k != "source_text_file"} for r in rows], lp.CURATED_COLUMNS,
                 out.parent / "curated.tsv")  # fmt: skip
    lp.write_tsv([], ("gene", "reason"), out.parent / "dropped.tsv")
    lp.write_tsv([], ("source", "access_path", "status", "note"), out.parent / "access-log.tsv")
    build = ["litpanel", "build", "--id", "literature-panel-test", "--split", "litpanel-split-test",
             "--extraction", str(out.parent)]  # fmt: skip
    result = runner.invoke(cli.app, build)
    assert result.exit_code == 1 and "without a resolution" in str(result.exception)
    fixed = [
        dict(r, resolution="source-supports-ours: re-read") if r["agree"] == "false" else r for r in checked
    ]
    lp.write_tsv(fixed, cli.CROSSCHECK_COLUMNS, out)
    result = runner.invoke(cli.app, build)
    assert result.exit_code == 0, result.output
    panel = lp.read_tsv(tmp_path / "literature-panel-test.tsv")
    assert len(panel) == 2 and panel[0]["independent"] == "true"
    assert (tmp_path / "manifests" / "literature-panel-test.json").exists()
