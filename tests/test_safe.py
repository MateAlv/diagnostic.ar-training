import io
import json
import math
import tarfile

import numpy as np
import pytest
from typer.testing import CliRunner

from diagnostic_ar_training import REPO_ROOT, cli_safe, splits
from diagnostic_ar_training.cli import app
from diagnostic_ar_training.cohorts.schema import Case, Sex
from diagnostic_ar_training.eval import harness, metrics, safe_eval
from diagnostic_ar_training.lineage import gitinfo, ledger, manifest
from diagnostic_ar_training.lineage.registry import LineageError
from diagnostic_ar_training.safe import bundle, knowledge, overrides, queue
from diagnostic_ar_training.safe.system import SafeV1, case_inputs, variant_name
from diagnostic_ar_training.systems import Scored

# Toy knowledge. Parent links: HP:3 is_a HP:2 is_a HP:1.
PARENTS = {"HP:3": {"HP:2"}, "HP:2": {"HP:1"}, "HP:1": set(), "HP:9": set()}


def ancestors(term):
    out, stack = set(), [term]
    while stack:
        for p in PARENTS.get(stack.pop(), ()):
            if p not in out:
                out.add(p)
                stack.append(p)
    return out


def annotations():
    ann = knowledge.Annotations()
    ann.names.update(
        {
            "OMIM:1": "Spermatogenic failure 1",
            "OMIM:2": "Premature ovarian failure 2",
            "OMIM:3": "46,XY sex reversal 3",
            "OMIM:4": "Adult-onset ataxia",
            "OMIM:5": "Childhood epilepsy",
            "OMIM:6": "Some syndrome",
            "OMIM:7": "Another syndrome",
            "OMIM:8": "Y-linked deafness",
            "OMIM:9": "Spermatogenic failure and oocyte maturation defect",
        }
    )
    ann.inheritance["OMIM:8"] = {knowledge.Y_LINKED}
    ann.onset_terms.update(
        {"OMIM:4": {"HP:0003581"}, "OMIM:5": {"HP:0011463"}, "OMIM:6": {"HP:0003593"}, "OMIM:7": {"HP:9"}}
    )
    ann.phenotypes.update(
        {
            "OMIM:4": [("HP:3", "HP:0040280"), ("HP:9", "1/2")],
            "OMIM:5": [("HP:3", "5/5")],
            "OMIM:6": [("HP:9", "4/4")],
            "OMIM:7": [("HP:2", "100%")],
        }
    )
    return ann


G2D = {
    "MALE1": {"OMIM:1"},
    "FEMALE1": {"OMIM:2"},
    "SRY": {"OMIM:3"},
    "YGENE": {"OMIM:6"},
    "YINH": {"OMIM:8"},
    "BOTH": {"OMIM:9"},
    "ADULT": {"OMIM:4"},
    "CHILD": {"OMIM:4", "OMIM:5"},
    "INFANT": {"OMIM:6"},
    "PARTIAL": {"OMIM:4", "OMIM:7"},
    "ORPHA": {"ORPHA:10"},
    "NEG2": {"OMIM:5", "OMIM:7"},
}
LOCATIONS = {"SRY": "Yp11.2", "YGENE": "Yq11.223", "MALE1": "1p36"}
ORPHANET = {"ORPHA:10": {"Adult"}}
VOCAB = (*G2D, "NOTHING")


@pytest.fixture(scope="module")
def built():
    return knowledge.build(VOCAB, G2D, annotations(), ORPHANET, LOCATIONS, ancestors)


def test_sex_limitation_reasons_and_blocks(built):
    kb, stats = built
    g = kb["genes"]
    assert g["MALE1"]["sex"] == {"limit": "male", "reasons": ["names"]}
    assert g["FEMALE1"]["sex"] == {"limit": "female", "reasons": ["names"]}
    assert "sex" not in g["SRY"]  # a sex-reversal disease blocks the rule, even on the Y chromosome
    assert g["YGENE"]["sex"] == {"limit": "male", "reasons": ["y_chromosome"]}
    assert g["YINH"]["sex"] == {"limit": "male", "reasons": ["y_linked_inheritance"]}
    assert "sex" not in g["BOTH"] and stats["genes_sex_ambiguous_dropped"] == 1


def test_strict_onset_needs_every_omim_disease_and_infantile_is_zero(built):
    g = built[0]["genes"]
    assert g["ADULT"]["onset"]["earliest_years"] == 16
    assert g["CHILD"]["onset"]["earliest_years"] == 1
    assert g["INFANT"]["onset"]["earliest_years"] == 0
    assert "onset" not in g["PARTIAL"]  # OMIM:7's only onset term has no lower bound
    assert g["ORPHA"]["onset"]["earliest_years"] == 16
    assert g["CHILD"]["onset"]["diseases"]["OMIM:5"] == {
        "lower_years": 1,
        "hpo_terms": ["HP:0011463"],
        "orphanet": [],
    }
    assert knowledge.HPO_ONSET_LOWER["HP:0003593"] == 0 and knowledge.ORPHANET_ONSET_LOWER["Infancy"] == 0


def test_obligate_phenotypes_and_negatable_genes(built):
    kb = built[0]
    g = kb["genes"]
    assert g["ADULT"]["obligate"] == {"OMIM:4": ["HP:3"]}
    assert g["INFANT"]["obligate"] == {"OMIM:6": []}  # 4/4 is below n = 5
    assert knowledge.negatable(g["NEG2"]) and not knowledge.negatable(g["INFANT"])
    assert "obligate" not in g["NOTHING"]
    assert kb["ancestors_or_self"]["HP:3"] == ["HP:1", "HP:2", "HP:3"]
    assert [knowledge.is_obligate(f) for f in ("HP:0040280", "100%", "5/5", "4/4", "5/6", "HP:0040281")] == [
        True,
        True,
        True,
        False,
        False,
        False,
    ]


def test_annotation_masking_keeps_names(tmp_path):
    header = "database_id\tdisease_name\tqualifier\thpo_id\treference\tevidence\tonset\tfrequency\tsex"
    rows = [
        "OMIM:1\tD one\t\tHP:3\tPMID:1\tPCS\t\t5/5\t\t\tP\tx",
        "OMIM:1\tD one\t\tHP:2\tPMID:2;OMIM:1\tPCS\t\t5/5\t\t\tP\tx",
        "OMIM:2\tD two\t\tHP:0003581\tPMID:2\tPCS\t\t\t\t\tC\tx",
        "OMIM:1\tD one\tNOT\tHP:9\tPMID:1\tPCS\t\t\t\t\tP\tx",
    ]
    path = tmp_path / "phenotype.hpoa"
    path.write_text("#c\n" + header + "\tmodifier\taspect\tbiocuration\n" + "\n".join(rows) + "\n")
    ann = knowledge.read_annotations(path, ["PMID:2"])
    assert ann.phenotypes == {"OMIM:1": [("HP:3", "5/5")]}
    assert dict(ann.onset_terms) == {} and ann.names == {"OMIM:1": "D one", "OMIM:2": "D two"}
    assert ann.stats["rows_masked_heldout_pmid"] == 2


def test_hgnc_approved_symbol_wins_over_another_genes_alias(tmp_path):
    path = tmp_path / "hgnc.tsv"
    path.write_text(
        "symbol\tlocation\talias_symbol\tprev_symbol\n"
        "OTHER\tYq11\tFOO\t\n"
        "FOO\t3p21\t\t\n"
        'BAR\t5q1\t\t"OLD1|OLD2"\n'
    )
    loc = knowledge.read_hgnc_locations(path)
    assert loc["FOO"] == "3p21" and loc["OLD2"] == "5q1"


# Rules and the block


@pytest.fixture(scope="module")
def rules(built):
    return bundle.SafeRules(bundle.export(built[0], "safe-kb-test"))


def test_export_has_only_applicable_rules(built):
    b = bundle.export(built[0], "safe-kb-test")
    assert b["format"] == bundle.FORMAT and b["negation_factor"] == 0.1
    assert b["genes"]["MALE1"] == {"sex": "male"}
    assert b["genes"]["CHILD"] == {"earliest_onset_years": 1}
    assert "NOTHING" not in b["genes"]
    assert set(b["obligate"]) == {"ADULT", "CHILD", "NEG2", "PARTIAL"}
    assert set(b["ancestors_or_self"]) == {"HP:2", "HP:3"}


def ranks(p):
    return np.array([metrics.rank_of(g, range(len(p)), p) for g in range(len(p))])


def test_block_goes_below_every_kept_gene_keeping_both_orders():
    rng = np.random.default_rng(0)
    for trial in range(200):
        n = 50
        p = rng.dirichlet(np.full(n, 0.3 if trial % 2 else 3.0))
        blocked = rng.random(n) < 0.3
        blocked[0] = True
        blocked[1] = False
        out = bundle.rescale(p, np.zeros(n, bool), blocked, 0.1)
        assert math.isclose(out.sum(), 1.0, rel_tol=1e-12)
        assert out[blocked].max() < out[~blocked].min()
        kept, block = np.where(~blocked)[0], np.where(blocked)[0]
        expected = np.empty(n)
        expected[kept[np.argsort(-p[kept], kind="stable")]] = np.arange(1, kept.size + 1)
        expected[block[np.argsort(-p[block], kind="stable")]] = np.arange(kept.size + 1, n + 1)
        assert np.array_equal(ranks(out), expected)


def test_block_is_exact_with_extreme_probabilities():
    blocked = np.array([False, True, True, False])
    for tiny in (1e-300, 1e-310):
        p = np.array([tiny, 0.6, 0.4, 2 * tiny])
        out = bundle.rescale(p, np.zeros(4, bool), blocked, 0.1)
        assert out[blocked].max() < out[~blocked].min()
        assert list(ranks(out)) == [2.0, 3.0, 4.0, 1.0]
    p = np.array([0.0, 0.6, 0.3, 0.1])  # nothing fits below a zero: the block ties with it, never above
    out = bundle.rescale(p, np.zeros(4, bool), blocked, 0.1)
    assert out[blocked].max() == 0.0 and list(ranks(out)) == [4.0, 4.0, 4.0, 1.0]
    p = np.array([0.0, 0.6, 0.4, 0.0])
    out = bundle.rescale(p, np.zeros(4, bool), blocked, 0.1)
    assert out.sum() == pytest.approx(1.0) and all(ranks(out) == 4.0)


def test_identity_returns_the_same_array():
    p = np.array([0.5, 0.3, 0.2])
    none = np.zeros(3, bool)
    assert bundle.rescale(p, none, none, 0.1) is p
    assert bundle.rescale(p, none, np.array([False, False, True]), 0.1) is p  # already below
    assert bundle.rescale(p, none, np.ones(3, bool), 0.1) is p


def test_rules_mask_the_right_genes(rules):
    genes = VOCAB
    i = {g: k for k, g in enumerate(genes)}

    def masks(**inputs):
        neg, block = rules.masks(genes, inputs)
        return {g for g in genes if neg[i[g]]}, {g for g in genes if block[i[g]]}

    assert masks() == (set(), set())
    assert masks(sex="female")[1] == {"MALE1", "YGENE", "YINH"}
    assert masks(sex="male")[1] == {"FEMALE1"}
    assert masks(sex="unknown") == (set(), set())
    assert masks(age_years=0.5)[1] == {"ADULT", "CHILD", "ORPHA"}
    assert masks(age_years=-0.4)[1] == {"ADULT", "CHILD", "ORPHA"}  # negative ages count as 0
    assert masks(age_years=0.5, onset_years=20)[1] == set()  # onset wins over age
    assert masks(onset_years=1)[1] == {"ADULT", "ORPHA"}  # later, not equal
    # HP:2 is an ancestor of HP:3, obligate in OMIM:4 and OMIM:5; HP:2 itself is obligate in OMIM:7.
    assert masks(excluded=["HP:3"])[0] == {"ADULT", "CHILD"}  # OMIM:7 (NEG2, PARTIAL) is not covered
    assert masks(excluded=["HP:2"])[0] == {"ADULT", "CHILD", "NEG2", "PARTIAL"}
    assert masks(excluded=["HP:9"])[0] == set()  # 1/2 and 4/4 are not obligate
    assert masks(excluded=["HP:1"])[0] == {"ADULT", "CHILD", "NEG2", "PARTIAL"}
    neg, block = rules.masks(genes, {"sex": "female", "excluded": ["HP:1"]}, rules=("sex",))
    assert not neg.any() and block.sum() == 3
    with pytest.raises(ValueError):
        rules.masks(genes, {}, rules=("age",))


def test_negation_multiplies_by_the_factor(rules):
    genes = VOCAB
    p = np.full(len(genes), 1 / len(genes))
    out = rules.apply(p, genes, {"excluded": ["HP:3"]})
    i = genes.index("ADULT")
    assert math.isclose(out[i] / out[0], 0.1)
    assert out.sum() == pytest.approx(1.0)


def test_module_apply_matches_the_rules(rules, built):
    p = np.random.default_rng(1).dirichlet(np.ones(len(VOCAB)))
    inputs = {"sex": "female", "age_years": 3, "excluded": ["HP:1"]}
    b = bundle.export(built[0], "safe-kb-test")
    assert np.array_equal(bundle.apply(p, VOCAB, inputs, b), rules.apply(p, VOCAB, inputs))


# The system


class FakeBase:
    name = "fake-e0"
    genes = VOCAB

    def lineage_inputs(self):
        return [{"id": "fake", "sha256": "0" * 64}]

    def score(self, case):
        assert case.excluded == ()  # E0 sees present terms only
        if not case.present:
            return Scored(None, {"n_present": 0})
        rng = np.random.default_rng(len(case.case_id) + sum(map(ord, case.case_id)))
        return Scored(rng.dirichlet(np.ones(len(self.genes))), {"n_present": len(case.present)})


def case(i, gene, **kw):
    return Case(case_id=f"c{i}", cohort="t", gene=gene, present=("HP:0001263",), **kw)


def test_safe_v1_is_e0_bit_for_bit_without_inputs(rules):
    base = FakeBase()
    system = SafeV1(base, rules)
    for c in (case(1, "ADULT"), case(2, "MALE1", sex=Sex.UNKNOWN), case(3, "FEMALE1", excluded=("HP:9",))):
        assert np.array_equal(system.score(c).probs, base.score(c.model_copy(update={"excluded": ()})).probs)


def test_safe_v1_ranks_blocked_true_gene_below_every_kept_gene(rules):
    base = FakeBase()
    c = case(4, "ADULT", age_years=2.0, sex=Sex.FEMALE)
    scored = SafeV1(base, rules).score(c)
    n_blocked = scored.info["safe_blocked"]
    rank = metrics.rank_of("ADULT", VOCAB, scored.probs)
    assert n_blocked == 5  # MALE1, YGENE, YINH, ADULT, ORPHA; CHILD starts at 1 year
    assert len(VOCAB) - n_blocked < rank <= len(VOCAB)


def test_variant_names_and_case_inputs():
    assert variant_name(bundle.RULES) == "safe-v1"
    assert variant_name(("onset", "sex")) == "safe-v1[sex+onset]"
    c = case(5, "ADULT", sex=Sex.MALE, age_years=3.0, excluded=("HP:1",))
    assert case_inputs(c) == {"sex": "male", "onset_years": None, "age_years": 3.0, "excluded": ["HP:1"]}


# Overrides


def row(**kw):
    base = {
        "gene": "ADULT",
        "rule": "onset",
        "action": "lower_onset",
        "value_years": "5",
        "evidence_quote": "onset from age 5",
        "source_file": "x.nxml",
        "curator": "agent-1",
    }
    return overrides.parse_row({**base, **kw})


def test_overrides_may_only_relax(built):
    kb = built[0]
    curated = overrides.apply(kb, [row(), row(gene="MALE1", rule="sex", action="remove", value_years="")])
    assert curated["genes"]["ADULT"]["onset"]["earliest_years"] == 5.0
    assert curated["genes"]["ADULT"]["curated"]["onset"] == {"uncurated_earliest_years": 16}
    assert "sex" not in curated["genes"]["MALE1"] and len(curated["overrides"]) == 2
    assert kb["genes"]["ADULT"]["onset"]["earliest_years"] == 16  # the input is not modified
    for stricter in (
        [row(value_years="20")],  # a higher bound
        [row(value_years="16")],  # not lower
        [row(gene="NOTHING")],  # adding an onset bound
        [row(gene="ADULT", rule="sex", action="remove", value_years="")],  # ADULT is not sex-limited
        [row(gene="UNKNOWN")],
        [row(), row(value_years="2")],  # two overrides of one rule
    ):
        with pytest.raises(overrides.OverrideError):
            overrides.apply(kb, stricter)


def test_override_rows_are_validated():
    for bad in (
        {"rule": "age"},
        {"action": "add"},
        {"rule": "sex", "action": "lower_onset"},
        {"value_years": "soon"},
        {"value_years": "inf"},
        {"action": "remove"},  # remove takes no value
        {"evidence_quote": ""},
        {"curator": " "},
        {"source_file": ""},
    ):
        with pytest.raises(overrides.OverrideError):
            row(**bad)


def test_committed_overrides_file_is_header_only_and_valid(tmp_path):
    path = REPO_ROOT / "data" / "curation" / "safe-v1-overrides.csv"
    assert path.read_text().strip() == ",".join(overrides.COLUMNS)
    assert overrides.read(path) == []
    bad = tmp_path / "bad.csv"
    bad.write_text("gene,rule\n")
    with pytest.raises(overrides.OverrideError):
        overrides.read(bad)


# Evaluation

GENES_CYCLE = ("ADULT", "MALE1", "NEG2", "CHILD", "NOT_IN_VOCAB")


def make_cases():
    cases = []
    for i in range(30):
        kw = {}
        if i % 3 == 0:
            kw["sex"] = Sex.FEMALE
        if i % 4 == 0:
            kw["age_years"] = 0.5
        if i % 5 == 0:
            kw["onset_years"] = 30.0
        if i % 2 == 0:
            kw["excluded"] = ("HP:1",)
        cases.append(case(i, GENES_CYCLE[i % len(GENES_CYCLE)], **kw))
    return cases


GROUPS = {f"c{i}": f"g{i // 3}" for i in range(30)}


def test_evaluate_reports_each_rule_and_subset(rules):
    cases = make_cases()
    report, records = safe_eval.evaluate(FakeBase(), rules, cases, GROUPS)
    assert set(records) == {"E0", "safe-v1", "safe-v1[sex]", "safe-v1[onset]", "safe-v1[negation]"}
    assert set(report["variants"]) == {"sex", "onset", "negation", "all"}
    assert report["identity"] == {"present_view_all_rules_vs_e0_mismatches": 0}
    assert report["subset_sizes"]["gene_in_vocab"] == 24
    assert report["subset_sizes"]["onset_known"] == 6
    for v in report["variants"].values():
        d = v["vs_e0"]
        assert d["n"] == 30 and d["resample_unit"] == "group"
        assert {"helped_n", "harmed_n", "top1_entered", "top1_left", "top10_entered", "top10_left"} <= set(d)
        assert v["rank_changes_where_no_rule_fired"] == 0
        assert set(v["subsets"]) == {"gene_in_vocab", *safe_eval.known_subsets([])}
    sex = report["variants"]["sex"]
    assert sex["subsets"]["sex_known"]["n"] == 10
    expected = harness.compare(records["E0"], records["safe-v1"])
    assert report["variants"]["all"]["vs_e0"]["delta"] == expected["delta"]
    assert safe_eval.table(report)


def test_top_moves_count_entries_and_exits():
    base = [{"rank": r} for r in (1, 5, 11, math.inf)]
    new = [{"rank": r} for r in (2, 12, 3, 1)]
    assert safe_eval.top_moves(base, new) == {
        "top1_entered": 1,
        "top1_left": 1,
        "top10_entered": 2,
        "top10_left": 1,
    }


# Curation queue


def make_tar(path, files):
    with tarfile.open(path, "w:gz") as tar:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def test_queue_lists_sex_and_onset_genes_with_their_evidence(built, tmp_path):
    gr = tmp_path / "gr.tar.gz"
    make_tar(
        gr,
        {
            "gene_NBK1116/ataxia.nxml": "<p>ADULT and CHILD-related variants; MALE12</p>",
            "gene_NBK1116/TOC.nxml": "ADULT MALE1",
        },
    )
    mp = tmp_path / "mp.tar.gz"
    make_tar(mp, {"condition/x.html": "MALE1 is a gene", "ghr-summaries.xml": "ADULT"})
    symbols = ["ADULT", "CHILD", "MALE1"]
    genereviews = queue.mentions(gr, symbols, queue.genereviews_chapter)
    medlineplus = queue.mentions(mp, symbols, queue.medlineplus_page)
    assert genereviews == {"ADULT": ["ataxia.nxml"], "CHILD": ["ataxia.nxml"]}
    assert medlineplus == {"MALE1": ["x.html"]}
    table = queue.rows(built[0], genereviews, medlineplus)
    by = {(r["gene"], r["rule"]): r for r in table}
    assert ("INFANT", "onset") not in by  # bound 0 < 1 year
    assert by[("ADULT", "onset")]["current"] == "16"
    assert by[("CHILD", "onset")]["genereviews_files"] == "ataxia.nxml"
    assert by[("CHILD", "onset")]["disease_onset_lower_years"] == "OMIM:4: 16; OMIM:5: 1"
    assert by[("MALE1", "sex")]["diseases"] == "OMIM:1 | Spermatogenic failure 1"
    assert by[("MALE1", "sex")]["medlineplus_files"] == "x.html"
    assert {r for _, r in by} == {"sex", "onset"}
    out = tmp_path / "q.csv"
    queue.write(out, table)
    assert out.read_text().splitlines()[0] == ",".join(queue.COLUMNS)


# The sealed read

ARGS = ["safe", "confirm", "--exp", "EXP-P-001", "--split", "p2-v1", "--part", "test", "--kb", "safe-kb-x"]
REASON = ["--reason", "pre-registered confirmation"]
CLEAN = gitinfo.CodeState(repo="r", sha="a" * 40, dirty=False)
DIRTY = gitinfo.CodeState(repo="r", sha="a" * 40, dirty=True)


class Touched(Exception):
    pass


@pytest.fixture
def tripwires(monkeypatch):
    """Anything that loads data, fetches an artifact or touches the ledger fails the test."""

    def boom(*a, **k):
        raise Touched

    monkeypatch.setattr(splits, "load_part", boom)
    monkeypatch.setattr(splits, "publication_groups", boom)
    monkeypatch.setattr(manifest, "load_manifest", boom)
    monkeypatch.setattr(manifest, "fetch_outputs", boom)
    monkeypatch.setattr(manifest, "ensure_new", boom)
    monkeypatch.setattr(ledger, "record_access", boom)


@pytest.fixture
def good(monkeypatch):
    monkeypatch.setenv("DXT_SEALED_READ", "EXP-P-001")
    monkeypatch.setattr(ledger, "is_preregistered", lambda path: True)
    monkeypatch.setattr(safe_eval, "code_state", lambda: CLEAN)


def run(args):
    return CliRunner().invoke(app, args, env={"COLUMNS": "400"})


def refused(result, text):
    return result.exit_code != 0 and not isinstance(result.exception, Touched) and text in result.output


def test_tripwires_are_live_once_every_check_passes(tripwires, good):
    assert isinstance(run(ARGS + REASON).exception, Touched)


def test_refusals_come_in_order_and_before_any_load(tripwires, good, monkeypatch):
    monkeypatch.delenv("DXT_SEALED_READ")
    monkeypatch.setattr(ledger, "is_preregistered", lambda path: False)
    monkeypatch.setattr(safe_eval, "code_state", lambda: DIRTY)
    assert refused(run(ARGS), "DXT_SEALED_READ=EXP-P-001")
    monkeypatch.setenv("DXT_SEALED_READ", "EXP-B-006")
    assert refused(run(ARGS), "DXT_SEALED_READ=EXP-P-001")
    monkeypatch.setenv("DXT_SEALED_READ", "EXP-P-001")
    assert refused(run(ARGS), "committed")
    monkeypatch.setattr(ledger, "is_preregistered", lambda path: True)
    assert refused(run(ARGS), "uncommitted")
    monkeypatch.setattr(safe_eval, "code_state", lambda: CLEAN)
    assert refused(run(ARGS), "reason is required")
    assert refused(run(ARGS + ["--reason", "  "]), "reason is required")


def test_malformed_requests_are_refused_before_any_load(tripwires, good):
    base = ["safe", "confirm", "--exp", "EXP-P-001", "--kb", "k", *REASON]
    for args in (
        [*base, "--split", "p2-v1", "--part", "dev"],
        [*base, "--split", "r1-v1", "--part", "test"],
        [*base, "--split", "p2-v1", "--split", "p2-fresh-v1", "--part", "test"],
        [*base, "--split", "p2-v1", "--part", "vault"],
        [*base, "--split", "p2-v1", "--split", "p2-v1", "--part", "test"],
        ["safe", "confirm", "--exp", "EXP-X-001", "--kb", "k", "--split", "p2-v1", "--part", "test", *REASON],
    ):
        result = run(args)
        assert result.exit_code != 0 and not isinstance(result.exception, Touched)


def test_final_check_reads_both_vaults_once(tripwires, good):
    args = [
        "safe",
        "confirm",
        "--exp",
        "EXP-P-001",
        "--split",
        "p2-v1",
        "--split",
        "p2-fresh-v1",
        "--part",
        "vault",
        "--kb",
        "k",
        *REASON,
    ]
    assert isinstance(run(args).exception, Touched)
    ledger.LEDGER.write_text("| 2026-10-20T00:00:00+00:00 | p2-fresh-v1/vault | EXP-P-001 | abc | r |\n")
    assert refused(run(args), "already opened")
    safe_eval.check_request("EXP-P-001", ["p2-fresh-v1", "p2-v1"], "vault")


def test_preflight_order_in_the_module(good, monkeypatch):
    monkeypatch.delenv("DXT_SEALED_READ")
    with pytest.raises(LineageError, match="DXT_SEALED_READ"):
        safe_eval.preflight("EXP-P-001", ["p2-v1"], "test", "")
    monkeypatch.setenv("DXT_SEALED_READ", "EXP-P-001")
    with pytest.raises(LineageError, match="reason"):
        safe_eval.preflight("EXP-P-001", ["p2-v1"], "test", "")
    safe_eval.preflight("EXP-P-001", ["p2-v1"], "test", "r")


def test_dry_run_refuses_sealed_parts_before_loading(tripwires):
    for part in ("test", "vault"):
        result = run(["safe", "eval", "--kb", "k", "--split", "r1-v1", "--part", part])
        assert result.exit_code != 0 and not isinstance(result.exception, Touched)
        assert "free parts only" in result.output


def test_experiment_id_p_is_accepted_by_the_ledger():
    assert ledger.EXP_ID.match("EXP-P-001")
    assert not ledger.EXP_ID.match("EXP-P-01")


def test_final_check_runs_end_to_end_on_mocked_vaults(good, built, monkeypatch, tmp_path):
    from diagnostic_ar_training.systems import genphenia_v3

    bundle_path = tmp_path / "safe-v1-bundle.json"
    bundle_path.write_text(json.dumps(bundle.export(built[0], "safe-kb-x")))
    cases = make_cases()
    loads = []

    def load_part(split_id, part, purpose, exp_id=None, reason=""):
        loads.append((split_id, part, exp_id, reason))
        return cases[:15] if split_id == "p2-v1" else cases[15:]

    for name in ("p2-v1", "p2-fresh-v1"):
        (tmp_path / f"{name}.json").write_text("{}")
    monkeypatch.setattr(splits, "load_part", load_part)
    monkeypatch.setattr(splits, "publication_groups", lambda split_id: GROUPS)
    monkeypatch.setattr(cli_safe, "_kb_output", lambda kb_id, name: (bundle_path, "f" * 64))
    monkeypatch.setattr(genphenia_v3, "GenPheniaV3", FakeBase)
    monkeypatch.setattr(gitinfo, "code_state", lambda *a, **k: CLEAN)
    monkeypatch.setattr(cli_safe, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(harness, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(cli_safe, "SPLITS_DIR", tmp_path)
    monkeypatch.setattr(manifest, "MANIFESTS_DIR", tmp_path / "manifests")
    args = ["safe", "confirm", "--exp", "EXP-P-001", "--split", "p2-v1", "--split", "p2-fresh-v1"]
    result = run([*args, "--part", "vault", "--kb", "safe-kb-x", *REASON])
    assert result.exit_code == 0, result.output
    assert loads == [(s, "vault", "EXP-P-001", REASON[1]) for s in ("p2-v1", "p2-fresh-v1")]
    out = tmp_path / "results" / "EXP-P-001"
    report = json.loads((out / "p2-v1+p2-fresh-v1-vault__safe-v1__safe-kb-x__report.json").read_text())
    assert report["cases"] == 30 and set(report["components"]) == {"p2-v1", "p2-fresh-v1"}
    assert report["components"]["p2-v1"]["cases"] == 15
    assert report["publications"] == 10  # five groups per vault, prefixed by their split
    assert (
        tmp_path / "manifests" / "results-EXP-P-001-p2-v1+p2-fresh-v1-vault-safe-v1-safe-kb-x.json"
    ).exists()


def test_kb_outputs_are_read_locally_when_they_verify(monkeypatch, tmp_path):
    from diagnostic_ar_training.lineage.hashing import sha256_file

    path = tmp_path / "safe-v1-bundle.json"
    path.write_text("{}")
    ref = manifest.OutputRef(path=str(path), sha256=sha256_file(path), bytes=2)
    m = manifest.Manifest(
        artifact_id="safe-kb-x",
        kind="safe-kb",
        created_at="t",
        code={},
        inputs=[],
        params={},
        params_hash="h",
        outputs=[ref],
    )
    monkeypatch.setattr(manifest, "load_manifest", lambda artifact_id: m)
    assert cli_safe._kb_output("safe-kb-x", "safe-v1-bundle.json") == (path, ref.sha256)
    path.write_text("{ }")
    with pytest.raises(LineageError, match="never published"):
        cli_safe._kb_output("safe-kb-x", "safe-v1-bundle.json")
