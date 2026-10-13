"""v4 runs: `data/interim/v4/<run_id>/` and the results row `results/P3/runs/<run_id>.json`.

Run directory: `config.yaml` / `config.json`, `history.jsonl` (one SELECT evaluation per line), `best.pt`,
`last.pt`, `ranks/{select,fit}.ranks.jsonl` and `summary.json` (every stratum, Δ vs E0).
The results row is small: configuration, code state, training totals, step-0 and best SELECT metrics, and the
SELECT / FIT summaries vs E0. R0 (E0 as released, production ONNX) has the run id `R0`.
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
        self._sets: dict[tuple[str, bool], object] = {}
        self._e0: dict[str, list[dict]] = {}

    def tables(self, ic: bool):
        from diagnostic_ar_training.v4 import data, graphs, knowledge

        if ic not in self._tables:
            table = knowledge.ic_table(self.inputs.dag) if ic else None
            self._tables[ic] = data.NodeTables(graphs.node_tables(self.inputs, table), self.device)
        return self._tables[ic]

    def e0_weights(self):
        from diagnostic_ar_training.gnn.model import load_v3

        return load_v3(self.inputs.root, map_location="cpu")

    def patient_set(self, fold_set: str, keep_covariates: bool = False):
        from diagnostic_ar_training.v4 import patients
        from diagnostic_ar_training.v4.evaluate import PatientSet

        key = (fold_set, keep_covariates)
        if key not in self._sets:
            self._sets[key] = PatientSet.build(
                patients.load(fold_set, keep_covariates), self.builder, self.genes
            )
        return self._sets[key]

    def e0_records(self, fold_set: str, log: Callable[[str], None] = print) -> list[dict]:
        """E0 as released on a fold set; cached in `data/interim/v4/R0/ranks/`."""
        from diagnostic_ar_training.v4 import evaluate

        if fold_set not in self._e0:
            ids = [p.case_id for p in self.patient_set(fold_set).patients]
            path = run_dir(E0_RUN) / "ranks" / f"{fold_set}.ranks.jsonl"
            cached = report.read_ranks(path) if path.is_file() else None
            if cached is None or [r["case_id"] for r in cached] != ids:
                log(f"scoring E0 (production ONNX) on {fold_set}: {len(ids)} patients")
                cached = evaluate.e0_records(self.patient_set(fold_set).patients)
                report.write_ranks(path, cached)
            self._e0[fold_set] = cached
        return self._e0[fold_set]


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


def eval_e0(ctx: Context, log: Callable[[str], None] = print) -> dict:
    row = {
        "run_id": E0_RUN,
        "status": COMPLETE,
        "system": "E0 as released (genphenia-v3.0 production ONNX)",
        "inputs": "present terms only",
        "code": code_state(False),
    }
    for fold_set in FOLD_SETS:
        row[fold_set] = compact(report.summarize(ctx.e0_records(fold_set, log)))
    write_json(row_path(E0_RUN), row)
    return row


def evaluate_run(run_id: str, ctx: Context, log: Callable[[str], None] = print) -> dict:
    """Best checkpoint on SELECT and FIT (train check) vs E0: ranks files, summary, results row."""
    from diagnostic_ar_training.v4 import evaluate, model, train

    cfg = load_config(run_id)
    d = run_dir(run_id)
    net = model.GinV4(ctx.inputs.dim, len(ctx.genes), cfg.arch, cfg.encoding).to(ctx.device)
    best_state = train.load_weights(net, d / "best.pt", ctx.device)
    tables = ctx.tables(cfg.encoding.ic_feature)
    summary = {"run_id": run_id, "best_step": best_state["step"]}
    for fold_set in FOLD_SETS:
        pset = ctx.patient_set(fold_set, cfg.encoding.covariates)
        records = evaluate.model_records(net, pset, tables, cfg.encoding)
        report.write_ranks(d / "ranks" / f"{fold_set}.ranks.jsonl", records)
        summary[fold_set] = report.summarize(records, ctx.e0_records(fold_set, log))
    write_json(d / "summary.json", summary)
    row = read_row(run_id) or {"run_id": run_id, "config": cfg.as_dict(), "config_hash": cfg.config_hash}
    row.update(
        status=COMPLETE,
        best_step=best_state["step"],
        step0_select=train.step0(d),
        select=compact(summary["select"]),
        fit=compact(summary["fit"], ("all", "uncited", "cited")),
    )
    write_json(row_path(run_id), row)
    p = summary["select"]["primary"]
    log(f"{run_id}: SELECT uncited Δ MRR vs E0 {p['delta']:+.4f} [{p['ci95'][0]:+.4f}, {p['ci95'][1]:+.4f}]")
    return row


def train_run(
    cfg: RunConfig,
    ctx: Context,
    force: bool = False,
    require_clean: bool = True,
    log: Callable[[str], None] = print,
) -> dict:
    """Train (or resume) one configuration, then evaluate its best checkpoint. Complete runs are skipped."""
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
        real = ctx.patient_set("fit", cfg.encoding.covariates).items() if cfg.sim.real_ratio > 0 else None
        stream = data.TrainStream(
            sampler,
            ctx.builder,
            samplers.gene_pool(sampler, cfg.encoding.drop_dash),
            cfg.train.batch_size,
            cfg.seed,
            real=real,
            real_ratio=cfg.sim.real_ratio,
            with_covariates=cfg.encoding.covariates,
        )
        e0 = ctx.e0_weights() if cfg.arch.init == "e0" else None
        import torch

        torch.manual_seed(cfg.seed)
        net = model.build(cfg.arch, cfg.encoding, e0, len(ctx.genes), ctx.inputs.dim).to(ctx.device)
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
    return evaluate_run(cfg.run_id, ctx, log)
