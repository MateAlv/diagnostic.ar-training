"""v4 runs: `data/interim/v4/<run_id>/` and the results row `results/P3/runs/<run_id>.json`.

Run directory: `config.yaml` / `config.json`, `history.jsonl` (one SELECT evaluation per line), `best.pt`,
`last.pt`, ranks and `summary.json` (every stratum, Δ vs E0).
The results row is small: configuration, code state, training totals, step-0 and best SELECT metrics, and the
SELECT / FIT summaries vs E0. R0 (E0 as released, production ONNX) has the run id `R0`.

Readings (`section`), each in the summary and the results row, with its ranks:
- best checkpoint (chosen on SELECT): top-level `select` / `fit`, `ranks/{select,fit}.ranks.jsonl`;
- final checkpoint (`last.pt`): `final`, `ranks/last/`;
- phenotype-swap control (`patients.phenotype_swap`) of either: `swap` / `final_swap`, `ranks/swap/` /
  `ranks/last/swap/`. Δ is vs E0 on the same swapped inputs (cached under R0's `ranks/swap/`).

Real patients mixed into training come from `sim.real_folds` (FIT by default; the row's `real_folds`). The
readings stay on SELECT and FIT whatever those folds, so a fold left out of them is read from the ranks by
case id.
"""

import json
import time
import traceback
from collections.abc import Callable
from pathlib import Path

from diagnostic_ar_training import INTERIM_DIR, RESULTS_DIR
from diagnostic_ar_training.lineage.registry import LineageError
from diagnostic_ar_training.v4 import config as v4config
from diagnostic_ar_training.v4 import report
from diagnostic_ar_training.v4.config import RunConfig

V4_DIR = INTERIM_DIR / "v4"
P3_RESULTS = RESULTS_DIR / "P3"
E0_RUN = "R0"
FOLD_SETS = ("select", "fit")
CHECKPOINTS = ("best", "last")
COMPLETE, RUNNING, FAILED = "complete", "running", "failed"
ROW_STRATA = ("all", "uncited", "cited", "no_pmid", "in_vocab", "oov", "uncited_in_vocab", "cited_in_vocab")


def runs_results_dir() -> Path:
    return P3_RESULTS / "runs"


def run_dir(run_id: str) -> Path:
    return V4_DIR / run_id


def row_path(run_id: str) -> Path:
    return runs_results_dir() / f"{run_id}.json"


def read_row(run_id: str) -> dict | None:
    path = row_path(run_id)
    return json.loads(path.read_text()) if path.is_file() else None


def write_json(path: Path, obj) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True, default=str) + "\n")
    tmp.replace(path)
    return path


def is_complete(run_id: str) -> bool:
    row = read_row(run_id)
    return row is not None and row.get("status") == COMPLETE


def code_state(require_clean: bool) -> dict:
    from diagnostic_ar_training.lineage.gitinfo import code_state as state

    s = state()
    if require_clean and s.dirty:
        raise LineageError("commit your code first (or pass --allow-dirty for a scratch run)")
    return s.as_dict()


def section(checkpoint: str = "best", swap: bool = False) -> str | None:
    """Summary / results-row key of a reading; None for the best checkpoint's (top-level `select` / `fit`)."""
    if checkpoint not in CHECKPOINTS:
        raise ValueError(f"checkpoint must be one of {CHECKPOINTS}")
    name = "final" if checkpoint == "last" else None
    if swap:
        return "swap" if name is None else f"{name}_swap"
    return name


def ranks_dir(run_id: str, checkpoint: str = "best", swap: bool = False) -> Path:
    d = run_dir(run_id) / "ranks"
    if checkpoint == "last":
        d = d / "last"
    return d / "swap" if swap else d


def compact(summary: dict, strata=ROW_STRATA) -> dict:
    return {
        "primary": summary["primary"],
        "strata": {k: v for k, v in summary["strata"].items() if k in strata},
    }


class Context:
    """Per-process inputs, built once: E0's bundle, the graph builder, node tables, patients, E0's ranks."""

    def __init__(self, device: str = "cuda") -> None:
        import torch

        from diagnostic_ar_training.systems.genphenia_v3 import V3Inputs, unpack_bundle
        from diagnostic_ar_training.v4.graphs import GraphBuilder

        self.device = torch.device(device if device != "cuda" or torch.cuda.is_available() else "cpu")
        self.inputs = V3Inputs(unpack_bundle())
        self.genes = self.inputs.genes
        self.builder = GraphBuilder(self.inputs.dag)
        self._tables: dict[bool, object] = {}
        self._sets: dict[tuple[str, bool, bool], object] = {}
        self._e0: dict[tuple[str, bool], list[dict]] = {}

    def tables(self, ic: bool):
        from diagnostic_ar_training.v4 import data, graphs, knowledge

        if ic not in self._tables:
            table = knowledge.ic_table(self.inputs.dag) if ic else None
            self._tables[ic] = data.NodeTables(graphs.node_tables(self.inputs, table), self.device)
        return self._tables[ic]

    def e0_weights(self):
        from diagnostic_ar_training.gnn.model import load_v3

        return load_v3(self.inputs.root, map_location="cpu")

    def patient_set(self, fold_set: str | tuple[int, ...], keep_covariates: bool = False, swap: bool = False):
        """A named fold set ('fit', 'select') or explicit fold numbers (`sim.real_folds`); cached by folds."""
        from diagnostic_ar_training.v4 import patients
        from diagnostic_ar_training.v4.evaluate import PatientSet

        folds = patients.fold_numbers(fold_set) if isinstance(fold_set, str) else tuple(sorted(fold_set))
        key = (folds, keep_covariates, swap)
        if key not in self._sets:
            members, swap_from = patients.load_folds(folds, keep_covariates), None
            if swap:
                members, swap_from = patients.phenotype_swap(members)
            self._sets[key] = PatientSet.build(members, self.builder, self.genes, swap_from)
        return self._sets[key]

    def e0_records(self, fold_set: str, log: Callable[[str], None] = print, swap: bool = False) -> list[dict]:
        """E0 as released on a fold set (phenotype-swapped with `swap`); cached under R0's ranks."""
        from diagnostic_ar_training.v4 import evaluate

        key = (fold_set, swap)
        if key not in self._e0:
            pset = self.patient_set(fold_set, swap=swap)
            sources = pset.swap_from or [None] * len(pset.patients)
            want = [(p.case_id, s) for p, s in zip(pset.patients, sources, strict=True)]
            path = ranks_dir(E0_RUN, swap=swap) / f"{fold_set}.ranks.jsonl"
            cached = report.read_ranks(path) if path.is_file() else None
            if cached is None or [(r["case_id"], r.get("swap_from")) for r in cached] != want:
                label = f"{fold_set} (phenotype swapped)" if swap else fold_set
                log(f"scoring E0 (production ONNX) on {label}: {len(want)} patients")
                cached = evaluate.tag_swap(evaluate.e0_records(pset.patients), pset.swap_from)
                report.write_ranks(path, cached)
            self._e0[key] = cached
        return self._e0[key]


def write_config(cfg: RunConfig) -> Path:
    d = run_dir(cfg.run_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.yaml").write_text(v4config.dump(cfg))
    write_json(
        d / "config.json",
        {"run_id": cfg.run_id, "config_hash": cfg.config_hash, **cfg.hashed_body(), "label": cfg.label},
    )
    return d


def load_config(run_id: str) -> RunConfig:
    path = run_dir(run_id) / "config.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"no run {run_id} under {V4_DIR}")
    cfg = v4config.load(path)
    if cfg.run_id != run_id:
        raise LineageError(f"{path} hashes to {cfg.run_id}, not {run_id}")
    return cfg


def eval_e0(ctx: Context, log: Callable[[str], None] = print, swap: bool = False) -> dict:
    row = read_row(E0_RUN) or {}
    row.update(
        run_id=E0_RUN,
        status=COMPLETE,
        system="E0 as released (genphenia-v3.0 production ONNX)",
        inputs="present terms only",
        code=code_state(False),
    )
    readings = {fs: compact(report.summarize(ctx.e0_records(fs, log, swap))) for fs in FOLD_SETS}
    if swap:
        row["swap"] = readings
    else:
        row.update(readings)
    write_json(row_path(E0_RUN), row)
    return row


def run_weights(arch) -> tuple[dict, dict] | tuple[None, None]:
    """A warm start from one of our runs (`arch.init` 'run:<id>[@best|@last]'): its model state, and where it
    came from (run id, checkpoint, step)."""
    import torch

    if arch.init_run is None:
        return None, None
    source, checkpoint = arch.init_run
    path = run_dir(source) / f"{checkpoint}.pt"
    if not path.is_file():
        raise FileNotFoundError(f"init {arch.init!r}: no {path}")
    saved = torch.load(path, map_location="cpu", weights_only=False)
    if saved.get("run_id") != source:
        raise LineageError(f"{path} belongs to run {saved.get('run_id')}, not {source}")
    return saved["model"], {"run_id": source, "checkpoint": checkpoint, "step": saved["state"]["step"]}


def evaluate_run(
    run_id: str,
    ctx: Context,
    log: Callable[[str], None] = print,
    checkpoint: str = "best",
    swap: bool = False,
    fresh: bool = False,
) -> dict:
    """One reading (`section`) of a run on SELECT and FIT vs E0: ranks, summary, results row. FIT is a train
    check when the real patients are FIT's (`sim.real_folds`); SELECT is held out unless it is among them.

    Other readings already in the summary and the row are kept, unless `fresh` (a new summary).
    """
    from diagnostic_ar_training.v4 import evaluate, model, train

    cfg = load_config(run_id)
    d = run_dir(run_id)
    key = section(checkpoint, swap)
    net = model.GinV4(ctx.inputs.dim, len(ctx.genes), cfg.arch, cfg.encoding).to(ctx.device)
    state = train.load_weights(net, d / f"{checkpoint}.pt", ctx.device)
    tables = ctx.tables(cfg.encoding.ic_feature)
    reading = {}
    for fold_set in FOLD_SETS:
        pset = ctx.patient_set(fold_set, cfg.encoding.covariates, swap)
        records = evaluate.model_records(net, pset, tables, cfg.encoding)
        report.write_ranks(ranks_dir(run_id, checkpoint, swap) / f"{fold_set}.ranks.jsonl", records)
        reading[fold_set] = report.summarize(records, ctx.e0_records(fold_set, log, swap))
    path = d / "summary.json"
    summary = json.loads(path.read_text()) if path.is_file() and not fresh else {}
    summary["run_id"] = run_id
    if key is None:
        summary.update(best_step=state["step"], **reading)
    else:
        summary[key] = {"checkpoint": checkpoint, "swap": swap, "step": state["step"], **reading}
    write_json(path, summary)
    row = read_row(run_id) or {"run_id": run_id, "config": cfg.as_dict(), "config_hash": cfg.config_hash}
    readings = {
        "select": compact(reading["select"]),
        "fit": compact(reading["fit"], ("all", "uncited", "cited")),
    }
    if key is None:
        row.update(status=COMPLETE, best_step=state["step"], step0_select=train.step0(d), **readings)
    else:
        row[key] = {"step": state["step"], **readings}
    write_json(row_path(run_id), row)
    p = reading["select"]["primary"]
    log(
        f"{run_id} {key or 'best'} (step {state['step']}): SELECT uncited Δ capped MRR vs E0 "
        f"{p['delta']:+.4f} [{p['ci95'][0]:+.4f}, {p['ci95'][1]:+.4f}]"
    )
    return row


def train_run(
    cfg: RunConfig,
    ctx: Context,
    force: bool = False,
    require_clean: bool = True,
    log: Callable[[str], None] = print,
) -> dict:
    """Train (or resume) one configuration, then read its best and final checkpoints, and their phenotype-swap
    controls when real patients (of `sim.real_folds`) are mixed in. Complete runs are skipped."""
    from diagnostic_ar_training.v4 import data, model, samplers, train

    if is_complete(cfg.run_id) and not force:
        log(f"{cfg.run_id}: already complete")
        return read_row(cfg.run_id)
    code = code_state(require_clean)
    d = write_config(cfg)
    row = {
        "run_id": cfg.run_id,
        "config_hash": cfg.config_hash,
        "config": cfg.as_dict(),
        "sim_params_sha256": cfg.hashed_body()["sim_params_sha256"],
        "code": code,
        "status": RUNNING,
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    write_json(row_path(cfg.run_id), row)
    try:
        sampler = samplers.build(cfg.sim)
        samplers.check_genes(sampler, ctx.genes)
        real = None
        if cfg.sim.real_ratio > 0:
            real = ctx.patient_set(cfg.sim.real_folds, cfg.encoding.covariates).items()
            row["real_folds"] = list(cfg.sim.real_folds)
        stream = data.TrainStream(
            sampler,
            ctx.builder,
            samplers.gene_pool(sampler, cfg.encoding.drop_dash),
            cfg.train.batch_size,
            cfg.seed,
            real=real,
            real_ratio=cfg.sim.real_ratio,
            with_covariates=cfg.encoding.covariates,
            real_draw=cfg.sim.real_draw,
        )
        if cfg.sim.real_draw == "gene" and real:
            row["real_by_gene"] = {
                "genes": len(stream.real_by_gene),
                "publications": sum(len(p) for p in stream.real_by_gene.values()),
                "patients": sum(len(x) for p in stream.real_by_gene.values() for x in p),
            }
        e0 = ctx.e0_weights() if cfg.arch.init == "e0" else None
        weights, source = run_weights(cfg.arch)
        if source is not None:
            row["init"] = source
        import torch

        torch.manual_seed(cfg.seed)
        net = model.build(cfg.arch, cfg.encoding, e0, len(ctx.genes), ctx.inputs.dim, weights).to(ctx.device)
        del weights
        select = ctx.patient_set("select", cfg.encoding.covariates)
        tables = ctx.tables(cfg.encoding.ic_feature)
        ctx.e0_records("select", log)
        row["training"] = train.train(cfg, net, stream, tables, select, d, ctx.device, log)
        row["n_real_fit_items"] = len(real) if real else 0
        write_json(row_path(cfg.run_id), row)
    except BaseException as error:
        row.update(
            status=FAILED, error=f"{type(error).__name__}: {error}", traceback=traceback.format_exc()[-2000:]
        )
        write_json(row_path(cfg.run_id), row)
        raise
    out = evaluate_run(cfg.run_id, ctx, log, fresh=True)
    evaluate_run(cfg.run_id, ctx, log, "last")
    if cfg.sim.real_ratio > 0:
        for checkpoint in CHECKPOINTS:
            evaluate_run(cfg.run_id, ctx, log, checkpoint, swap=True)
    return read_row(cfg.run_id) or out
