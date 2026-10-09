"""What `dxt vocab select` and `dxt vocab final` share: the setup, the pools, a fit, an evaluation.

Only free parts are loaded: `r1-v1` train always, `r1-v1` dev only when the final command asks for it. No
patient enters a fit: the rows learn from pseudo-patients only, and patients are scored afterwards.
"""

import time
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import torch

from diagnostic_ar_training import RESULTS_DIR, SPLITS_DIR
from diagnostic_ar_training.eval import harness
from diagnostic_ar_training.ft import configs as ft_configs
from diagnostic_ar_training.ft.system import E0Logits, E0System
from diagnostic_ar_training.vocab import rows, standards

SPLIT = "r1-v1"
E0_REFERENCE = RESULTS_DIR / "EXP-P-001"


class Setup:
    def __init__(self, kb: dict, kb_id: str, kb_sha: str, device: str, parts: Sequence[str]) -> None:
        from diagnostic_ar_training import splits
        from diagnostic_ar_training.ft import replay as ft_replay
        from diagnostic_ar_training.gnn.model import load_v3
        from diagnostic_ar_training.lineage.hashing import sha256_file
        from diagnostic_ar_training.lineage.registry import Purpose
        from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

        if not set(parts) <= {"train", "dev"}:
            raise ValueError("only the free parts train and dev")
        self.kb, self.kb_id, self.kb_sha = kb, kb_id, kb_sha
        self.device = torch.device(device)
        self.base = GenPheniaV3()
        self.inputs = self.base.inputs
        self.vocabulary = list(self.base.genes)
        self.e0 = E0Logits(self.base)
        self.e0_system = E0System(self.e0)
        self.v3 = load_v3(self.inputs.root, map_location=self.device)
        self.weight = self.v3.classifier.weight.detach()
        self.bias = self.v3.classifier.bias.detach()
        self.known = set(self.inputs.dag.index)
        self.exclude = splits.presentation_keys(SPLIT)
        self.groups = splits.publication_groups(SPLIT)
        purposes = {"train": Purpose.TRAIN, "dev": Purpose.EVAL}
        self.cases = {p: splits.load_part(SPLIT, p, purposes[p]) for p in parts}
        train_ids = [c.case_id for c in self.cases["train"]]
        self.inner = ft_configs.inner_split(self.groups, train_ids)
        self.e0_records = {
            p: harness.run(self.e0_system, cs, "all", self.groups) for p, cs in self.cases.items()
        }
        self.e0_check = {
            p: self._differ(r, f"{SPLIT}-{p}__E0__all.ranks.jsonl") for p, r in self.e0_records.items()
        }
        start = time.perf_counter()
        self.pooled: dict[str, np.ndarray] = {}
        for cs in self.cases.values():
            scorable = [(c.case_id, known) for c in cs if (known := self.inputs.known_present(c)[0])]
            vectors = ft_replay.pooled_vectors(self.v3, self.inputs, [k for _, k in scorable], self.device)
            self.pooled.update({cid: vectors[i] for i, (cid, _) in enumerate(scorable)})
        self.case_pool_seconds = time.perf_counter() - start
        self.split_sha = sha256_file(SPLITS_DIR / f"{SPLIT}.json")
        self.mask_sha = sha256_file(SPLITS_DIR / f"{SPLIT}.all-pmids.txt")
        self._pool_key = self._pools = None
        self._val_key = self._val = None

    @staticmethod
    def _differ(records: list[dict], name: str) -> int | None:
        path = E0_REFERENCE / name
        if not path.is_file():
            return None
        ref = {r["case_id"]: r["rank"] for r in harness.read(path)}
        return sum(ref.get(r["case_id"]) != r["rank"] for r in records)

    def has_profile(self, gene: str) -> bool:
        return any(t in self.known for t in self.kb["genes"].get(gene, {}).get("profile", ()))

    def index(self, genes: Sequence[str]) -> list[int]:
        lookup = {g.upper(): i for i, g in enumerate(self.vocabulary)}
        return [lookup[g.upper()] for g in genes]

    def pools(self, relearn: Sequence[str], cfg: rows.RowConfig) -> dict:
        """Training and held-out pools of the relearned genes and of the replay genes, on the device."""
        slots = self.index(relearn)
        key = (tuple(relearn), cfg.new_per_gene, cfg.replay_per_gene)
        start = time.perf_counter()
        if key != self._pool_key:
            self._pools = None
            if self.device.type == "cuda":
                torch.cuda.empty_cache()
            new, replay, stats = rows.pseudo_pools(
                self.kb, self.vocabulary, self.known, self.exclude, relearn, slots,
                cfg.new_per_gene, cfg.replay_per_gene,
            )  # fmt: skip
            self._pools = {
                "new": rows.to_pool(self.v3, self.inputs, new, self.device),
                "replay": rows.to_pool(self.v3, self.inputs, replay, self.device),
                "stats": stats,
            }
            self._pool_key = key
        if tuple(relearn) != self._val_key:
            vn, vr, vstats = rows.pseudo_pools(
                self.kb, self.vocabulary, self.known, self.exclude, relearn, slots,
                rows.VAL_NEW_PER_GENE, rows.VAL_REPLAY_PER_GENE, val=True,
            )  # fmt: skip
            self._val = {
                "val_new": rows.to_pool(self.v3, self.inputs, vn, self.device),
                "val_replay": rows.to_pool(self.v3, self.inputs, vr, self.device),
                "val_stats": vstats,
            }
            self._val_key = tuple(relearn)
        out = {**self._pools, **self._val}
        out["w_new"] = rows.prior_weight(out["stats"]["new_genes"], out["stats"]["replay_genes"])
        out["seconds"] = time.perf_counter() - start
        return out

    def fit(self, relearn: Sequence[str], cfg: rows.RowConfig, log=print) -> tuple[rows.RowFit, dict]:
        pools = self.pools(relearn, cfg)
        head = rows.RowHead(self.weight, self.bias, replace=self.index(relearn), seed=cfg.seed).to(
            self.device
        )
        init = head.new_weight.detach().clone()
        if self.device.type == "cuda":
            torch.cuda.reset_peak_memory_stats(self.device)
        result = rows.fit(
            cfg,
            head,
            pools["new"],
            pools["replay"],
            pools["val_new"],
            pools["val_replay"],
            pools["w_new"],
            log,
        )
        e0_rows = self.weight[head.replace_idx]
        checks = {
            "frozen_weight_unchanged": bool(torch.equal(head.weight, self.weight)),
            "frozen_bias_unchanged": bool(torch.equal(head.bias, self.bias)),
            "v3_classifier_unchanged": bool(
                torch.equal(self.v3.classifier.weight, self.weight)
                and torch.equal(self.v3.classifier.bias, self.bias)
            ),
            "init_max_abs": float(init.abs().max()),
            "init_max_cosine_to_e0_rows": float(
                torch.nn.functional.cosine_similarity(init, e0_rows, dim=1).abs().max()
            ),
            "final_mean_cosine_to_e0_rows": float(
                torch.nn.functional.cosine_similarity(head.new_weight.detach(), e0_rows, dim=1).mean()
            ),
            "final_mean_row_norm": float(head.new_weight.detach().norm(dim=1).mean()),
            "e0_mean_row_norm": float(e0_rows.norm(dim=1).mean()),
        }
        info = {
            "pool_stats": pools["stats"],
            "val_pool_stats": pools["val_stats"],
            "w_new": pools["w_new"],
            "pool_seconds": pools["seconds"],
            "max_gpu_memory_gb": torch.cuda.max_memory_allocated(self.device) / 1e9
            if self.device.type == "cuda"
            else None,
            "checks": checks,
        }
        return result, info

    def system(self, relearn: Sequence[str], weight: np.ndarray, bias: np.ndarray, name: str):
        return standards.Relearned(self.e0, self.index(relearn), weight, bias, self.pooled, name)

    def run(self, system, part: str) -> list[dict]:
        return harness.run(system, self.cases[part], "all", self.groups)

    def untouched_logits_differ(self, system, part: str, n: int = 300) -> int:
        """Cases (of the first n scorable) where a non-relearned gene's logit is not E0's, bit for bit."""
        keep = np.ones(len(self.vocabulary), dtype=bool)
        keep[system.index] = False
        differ = 0
        for case in self.cases[part][:n]:
            a, _ = self.e0(case)
            b, _ = system.logits(case)
            if a is None:
                continue
            differ += not np.array_equal(np.asarray(a, dtype=np.float64)[keep], b[keep])
        return differ

    def e0_rows_rank_differences(self, relearn: Sequence[str], part: str) -> int:
        """E0's own rows through the torch pooled vectors: cases whose rank differs from E0's."""
        idx = self.index(relearn)
        w = self.weight[idx].double().cpu().numpy()
        b = self.bias[idx].double().cpu().numpy()
        recs = self.run(self.system(relearn, w, b, "e0-rows"), part)
        return sum(x["rank"] != y["rank"] for x, y in zip(recs, self.e0_records[part], strict=True))

    def lineage(self) -> list[dict]:
        return [
            *self.base.lineage_inputs(),
            {"id": f"artifact:{self.kb_id}", "sha256": self.kb_sha},
            {"id": f"split:{SPLIT}", "sha256": self.split_sha},
            {"id": f"all-pmids:{SPLIT}", "sha256": self.mask_sha},
        ]


def save_rows(path: Path, genes: Sequence[str], index: Sequence[int], weight, bias, meta: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "genes": list(genes),
            "index": list(index),
            "weight": torch.as_tensor(np.asarray(weight, dtype=np.float32)),
            "bias": torch.as_tensor(np.asarray(bias, dtype=np.float32)),
            "meta": meta,
        },
        path,
    )
    return path


def load_rows(path: Path) -> dict:
    return torch.load(path, map_location="cpu", weights_only=True)
