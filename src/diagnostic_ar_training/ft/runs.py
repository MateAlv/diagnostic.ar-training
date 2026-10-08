"""What `dxt ft grid` and `dxt ft ensemble` share: the per-process setup, one run, and their outputs.

The setup is computed once per process: E0's logits (production ONNX) for every train and dev patient, the
features, E0's records, the subsets, and for the classifier configuration v3.0's pooled vectors and the
pseudo-patients. Only free parts are loaded: `r1-v1` train (fitting) and dev (selection).
"""

import json
import math
import time
from pathlib import Path

import numpy as np

from diagnostic_ar_training import RESULTS_DIR, SPLITS_DIR
from diagnostic_ar_training.eval import harness
from diagnostic_ar_training.eval.safe_eval import contrast
from diagnostic_ar_training.ft import configs
from diagnostic_ar_training.ft import evaluate as ft_eval
from diagnostic_ar_training.ft.bundle import COVARIATES, FEATURES, FORMAT
from diagnostic_ar_training.ft.system import E0Logits, E0System, case_inputs

SPLIT = "r1-v1"
E0_REFERENCE = RESULTS_DIR / "EXP-P-001"


class Setup:
    def __init__(self, kb: dict, kb_id: str, kb_sha: str, device: str, pooled: bool) -> None:
        import torch

        from diagnostic_ar_training import splits
        from diagnostic_ar_training.ft import train as ft_train
        from diagnostic_ar_training.ft.bundle import Knowledge
        from diagnostic_ar_training.lineage.hashing import sha256_file
        from diagnostic_ar_training.lineage.registry import Purpose
        from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

        self.kb, self.kb_id, self.kb_sha = kb, kb_id, kb_sha
        self.device = torch.device(device)
        self.base = GenPheniaV3()
        self.e0 = E0Logits(self.base)
        self.e0_system = E0System(self.e0)
        inputs = self.base.inputs
        self.knowledge = Knowledge(kb, self.base.genes, (inputs.emb_index, inputs.vectors), kb_id)
        self.train_cases = splits.load_part(SPLIT, "train", Purpose.TRAIN)
        self.dev_cases = splits.load_part(SPLIT, "dev", Purpose.EVAL)
        self.groups = splits.publication_groups(SPLIT)
        self.arrays = ft_train.arrays(self.train_cases, self.e0, self.knowledge)
        self.inner = configs.inner_split(self.groups, [c.case_id for c in self.train_cases])
        train_ids = {c.case_id for c in self.train_cases}
        train_genes = {c.gene.upper() for c in self.train_cases}
        self.train_subsets = {"inner_val": self.inner, "fit": train_ids - self.inner}
        self.dev_subsets = {
            "post_e0": self._post_e0(self.dev_cases, self.groups),
            "gene_in_train": {c.case_id for c in self.dev_cases if c.gene.upper() in train_genes},
            "gene_not_in_train": {c.case_id for c in self.dev_cases if c.gene.upper() not in train_genes},
        }
        self.e0_dev = harness.run(self.e0_system, self.dev_cases, "all", self.groups)
        self.e0_train = harness.run(self.e0_system, self.train_cases, "all", self.groups)
        self.e0_check = {
            "dev_ranks_differ_from_exp_p001": self._differ(self.e0_dev, "r1-v1-dev__E0__all.ranks.jsonl"),
            "train_ranks_differ_from_exp_p001": self._differ(
                self.e0_train, "r1-v1-train__E0__all.ranks.jsonl"
            ),
        }
        self.split_sha = sha256_file(SPLITS_DIR / f"{SPLIT}.json")
        self.mask_sha = sha256_file(SPLITS_DIR / f"{SPLIT}.all-pmids.txt")
        self.replay = self.pooled_train = self.replay_stats = self.pooled_check = self.v3_cpu = None
        if pooled:
            self._pooled()

    @staticmethod
    def _post_e0(cases, groups: dict[str, str]) -> set[str]:
        from diagnostic_ar_training import splits

        release, cited = splits._e0_seen()
        pmids = splits.group_pmids(cases, groups)
        status = {g: splits.group_status(p, release, cited) for g, p in pmids.items()}
        return {c.case_id for c in cases if status[groups[c.case_id]] == splits.POST_E0}

    @staticmethod
    def _differ(records: list[dict], name: str) -> int | None:
        path = E0_REFERENCE / name
        if not path.is_file():
            return None
        ref = {r["case_id"]: r["rank"] for r in harness.read(path)}
        return sum(ref.get(r["case_id"]) != r["rank"] for r in records)

    def _pooled(self) -> None:
        import torch

        from diagnostic_ar_training import splits
        from diagnostic_ar_training.ft import replay as ft_replay
        from diagnostic_ar_training.ft import train as ft_train
        from diagnostic_ar_training.gnn.model import load_v3

        inputs = self.base.inputs
        v3 = load_v3(inputs.root, map_location=self.device)
        by_id = {c.case_id: c for c in self.train_cases}
        self.pooled_train = ft_replay.pooled_vectors(
            v3, inputs, [by_id[i].present for i in self.arrays["case_ids"]], self.device
        )
        weight, bias = v3.classifier.weight.detach(), v3.classifier.bias.detach()
        recon = (torch.from_numpy(self.pooled_train).to(self.device) @ weight.T + bias).cpu().numpy()
        self.pooled_check = {"max_abs_logit_diff_vs_onnx": float(np.abs(recon - self.arrays["logits"]).max())}
        pseudo, self.replay_stats = ft_replay.pseudo_patients(
            self.kb, inputs.genes, set(inputs.dag.index), splits.presentation_keys(SPLIT)
        )
        pooled = ft_replay.pooled_vectors(v3, inputs, [p for _, p in pseudo], self.device)
        self.replay = ft_train.Replay(
            torch.from_numpy(pooled).to(self.device),
            torch.tensor([g for g, _ in pseudo], dtype=torch.int64, device=self.device),
            weight,
            bias,
        )
        self.v3_cpu = load_v3(inputs.root, map_location="cpu")

    def pooler(self, case) -> np.ndarray:
        from diagnostic_ar_training.ft import replay as ft_replay

        return ft_replay.pooled_vectors(self.v3_cpu, self.base.inputs, [case.present], "cpu")[0]

    def lineage(self) -> list[dict]:
        return [
            *self.base.lineage_inputs(),
            {"id": f"artifact:{self.kb_id}", "sha256": self.kb_sha},
            {"id": f"split:{SPLIT}", "sha256": self.split_sha},
            {"id": f"all-pmids:{SPLIT}", "sha256": self.mask_sha},
        ]

    def evaluate(self, system) -> tuple[dict, dict[str, list[dict]]]:
        """(report, records): dev and train vs E0, the dev present-only view, and its bit-for-bit check."""
        dev = harness.run(system, self.dev_cases, "all", self.groups)
        train = harness.run(system, self.train_cases, "all", self.groups)
        present = harness.run(system, self.dev_cases, "present", self.groups)
        report = {
            "dev": ft_eval.report(self.e0_dev, dev, self.dev_cases, self.dev_subsets),
            "train": ft_eval.report(self.e0_train, train, self.train_cases, self.train_subsets),
            "dev_present_view": contrast(self.e0_dev, present),
            "dev_present_identity": ft_eval.present_identity(system, self.e0_system, self.dev_cases),
        }
        return report, {"dev": dev, "train": train}

    def counts(self) -> dict:
        a = self.arrays
        return {
            "train_cases": len(self.train_cases),
            "usable": len(a["case_ids"]),
            "skipped": a["skipped"],
            "held_out_groups_usable": len(set(a["case_ids"]) & self.inner),
            "dev_cases": len(self.dev_cases),
            "dev_subsets": {k: len(v) for k, v in self.dev_subsets.items()},
        }


def row(report: dict) -> dict:
    """The numbers the configuration table aggregates."""
    d = report["dev"]["vs_e0"]
    return {
        "dev": {
            "delta": d["delta"],
            "ci_low": d["ci95"][0],
            "ci_high": d["ci95"][1],
            "harmed": d["harmed"],
            "helped": d["helped"],
        },
        "present_delta": report["dev_present_view"]["delta"],
        "train_delta": report["train"]["vs_e0"]["delta"],
        "inner_delta": report["train"]["subsets"]["inner_val"]["delta"],
        "post_e0_delta": report["dev"]["subsets"]["post_e0"].get("delta"),
    }


def write_compact_ranks(path: Path, records: list[dict]) -> Path:
    """(case_id, rank, group) per case, as `gnn.experiment.write_compact_ranks`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        for r in records:
            rank = "inf" if math.isinf(r["rank"]) else r["rank"]
            handle.write(
                json.dumps({"case_id": r["case_id"], "rank": rank, "group": r.get("group")}, sort_keys=True)
            )
            handle.write("\n")
    return path


def write_records(out_dir: Path, records: dict[str, list[dict]]) -> list[Path]:
    return [
        write_compact_ranks(out_dir / f"r1-v1-{part}.ranks.jsonl", recs) for part, recs in records.items()
    ]


def bundle(kb_id: str, members: list[dict], model_ids: list[str]) -> dict:
    return {
        "format": FORMAT,
        "kb_id": kb_id,
        "features": list(FEATURES),
        "covariates": list(COVARIATES),
        "members": members,
        "model_ids": model_ids,
    }


def residual_agreement(model, residual, part, cases_by_id: dict, n: int = 256) -> float:
    """Max |r_torch − r_numpy| over the first `n` rows of a part: the trained model vs what ships."""
    import torch

    rows = slice(0, min(n, len(part)))
    pooled = None if part.pooled is None else part.pooled[rows]
    with torch.no_grad():
        torch_r = model(part.feats[rows], part.z[rows], pooled).double().cpu().numpy()
    numpy_r = np.stack(
        [
            residual.residual(
                case_inputs(cases_by_id[cid]), None if pooled is None else pooled[k].cpu().numpy()
            )
            for k, cid in enumerate(part.case_ids[rows])
        ]
    )
    return float(np.abs(numpy_r - torch_r).max()) if len(numpy_r) else 0.0


def write_json(path: Path, obj) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, default=str) + "\n")
    return path


def elapsed(start: float) -> float:
    return time.perf_counter() - start
