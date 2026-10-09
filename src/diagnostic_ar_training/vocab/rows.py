"""New-row training: trainable classifier rows on v3.0's frozen pooled vectors, every other row frozen.

- `RowHead`: logits over an extended vocabulary. v3.0's rows are buffers (never trained); `replace` names
  vocabulary indices whose rows are deleted and relearned, `add` appends new genes after the last index. The
  trainable rows start from a seeded uniform(±1/√hidden) draw, as `nn.Linear`, never from v3.0's rows.
- Pools: upstream-style pseudo-patients (`ft/replay.py`: uniform subsets of 1-12 of a gene's masked profile
  terms; the graph adds their ancestors), as v3.0's pooled vectors and their targets in the extended
  vocabulary.
- `fit`: Adam on the trainable rows only. Each step draws a batch of the new genes' pseudo-patients and one of
  the other genes' (replay), and weights the two cross-entropies by their share of genes, so every gene counts
  once, as in a uniform-prior simulator. Early stopping on held-out pseudo-patients (no patient is used).
"""

import copy
import math
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn

NEW_SEED = 20261009
NEW_VAL_SEED = 20261010
REPLAY_VAL_SEED = 20261011
VAL_NEW_PER_GENE = 16
VAL_REPLAY_PER_GENE = 2


@dataclass(frozen=True)
class RowConfig:
    new_per_gene: int = 128
    replay_per_gene: int = 8
    lr: float = 0.05
    weight_decay: float = 0.0
    batch_new: int = 256
    batch_replay: int = 1024
    max_epochs: int = 300
    patience: int = 10
    min_delta: float = 1e-4
    seed: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


class RowHead(nn.Module):
    def __init__(
        self,
        weight: torch.Tensor,
        bias: torch.Tensor,
        replace: Sequence[int] = (),
        add: int = 0,
        seed: int = 0,
    ) -> None:
        super().__init__()
        n_genes, hidden = weight.shape
        replace = [int(i) for i in replace]
        if len(set(replace)) != len(replace) or any(not 0 <= i < n_genes for i in replace):
            raise ValueError("replace must name distinct vocabulary indices")
        if add < 0 or not replace and not add:
            raise ValueError("nothing to train: replace or add at least one row")
        self.n_genes, self.n_replace, self.n_add = n_genes, len(replace), add
        self.register_buffer("weight", weight.detach().clone())
        self.register_buffer("bias", bias.detach().clone())
        self.register_buffer("replace_idx", torch.tensor(replace, dtype=torch.int64, device=weight.device))
        k, bound = len(replace) + add, 1.0 / math.sqrt(hidden)
        gen = torch.Generator(device="cpu").manual_seed(seed)
        new_weight = (torch.rand(k, hidden, generator=gen, dtype=torch.float64) * 2 - 1) * bound
        new_bias = (torch.rand(k, generator=gen, dtype=torch.float64) * 2 - 1) * bound
        self.new_weight = nn.Parameter(new_weight.to(weight.dtype).to(weight.device))
        self.new_bias = nn.Parameter(new_bias.to(weight.dtype).to(weight.device))

    @property
    def n_out(self) -> int:
        return self.n_genes + self.n_add

    def slots(self) -> list[int]:
        """Output index of each trainable row: the replaced indices, then the appended ones."""
        return self.replace_idx.tolist() + list(range(self.n_genes, self.n_genes + self.n_add))

    def forward(self, pooled: torch.Tensor) -> torch.Tensor:
        """Logits [B, n_genes + add]."""
        base = pooled @ self.weight.T + self.bias
        new = pooled @ self.new_weight.T + self.new_bias
        if self.n_replace:
            base = base.index_copy(1, self.replace_idx, new[:, : self.n_replace])
        if self.n_add:
            base = torch.cat([base, new[:, self.n_replace :]], dim=1)
        return base

    @torch.no_grad()
    def matrix(self) -> tuple[torch.Tensor, torch.Tensor]:
        """The extended classifier (weight [n_out, hidden], bias [n_out]) these logits equal."""
        weight = torch.cat([self.weight, self.new_weight[self.n_replace :]])
        bias = torch.cat([self.bias, self.new_bias[self.n_replace :]])
        if self.n_replace:
            weight[self.replace_idx] = self.new_weight[: self.n_replace]
            bias[self.replace_idx] = self.new_bias[: self.n_replace]
        return weight, bias


@dataclass
class Pool:
    """Pseudo-patients as v3.0 pooled vectors [n, hidden] and targets in the extended vocabulary [n]."""

    pooled: torch.Tensor
    target: torch.Tensor

    def __len__(self) -> int:
        return int(self.target.numel())


def pseudo_pools(
    kb: dict,
    vocabulary: Sequence[str],
    known: set[str],
    exclude: set[tuple[str, frozenset[str]]],
    relearn: Sequence[str],
    slots: Sequence[int],
    new_per_gene: int,
    replay_per_gene: int,
    val: bool = False,
) -> tuple[list[tuple[int, tuple[str, ...]]], list[tuple[int, tuple[str, ...]]], dict]:
    """(new, replay, stats): [(output index, present terms)] for the relearned genes and for every other gene.

    `relearn[j]` is trained in output `slots[j]`. Replay covers the vocabulary genes outside `relearn`, with
    EXP-P-003's replay seed; `val` draws the held-out early-stopping pools with their own seeds instead.
    """
    from diagnostic_ar_training.ft import replay as ft_replay

    if len(relearn) != len(slots):
        raise ValueError("one slot per relearned gene")
    new_seed, replay_seed = (NEW_VAL_SEED, REPLAY_VAL_SEED) if val else (NEW_SEED, ft_replay.SEED)
    raw_new, new_stats = ft_replay.pseudo_patients(
        kb, list(relearn), known, exclude, per_gene=new_per_gene, seed=new_seed
    )
    raw_replay, replay_stats = ft_replay.pseudo_patients(
        kb, list(vocabulary), known, exclude, per_gene=replay_per_gene, seed=replay_seed
    )
    relearned = {g.upper() for g in relearn}
    new = [(slots[j], terms) for j, terms in raw_new]
    replay = [(i, terms) for i, terms in raw_replay if vocabulary[i].upper() not in relearned]
    stats = {
        "new": new_stats,
        "replay": {**replay_stats, "cases_after_removing_relearned": len(replay)},
        "new_genes": len({j for j, _ in raw_new}),
        "replay_genes": len({i for i, _ in replay}),
    }
    return new, replay, stats


def to_pool(model, inputs, cases: list[tuple[int, tuple[str, ...]]], device) -> Pool:
    from diagnostic_ar_training.ft import replay as ft_replay

    pooled = ft_replay.pooled_vectors(model, inputs, [terms for _, terms in cases], device)
    return Pool(
        torch.from_numpy(pooled).to(device),
        torch.tensor([t for t, _ in cases], dtype=torch.int64, device=device),
    )


def prior_weight(n_new_genes: int, n_replay_genes: int) -> float:
    """The new genes' share of the loss: one weight per gene, as a uniform prior over genes."""
    return n_new_genes / (n_new_genes + n_replay_genes)


def loss(head: RowHead, new: Pool, replay: Pool, w_new: float, idx_new=None, idx_replay=None) -> torch.Tensor:
    pn = new.pooled if idx_new is None else new.pooled.index_select(0, idx_new)
    tn = new.target if idx_new is None else new.target.index_select(0, idx_new)
    pr = replay.pooled if idx_replay is None else replay.pooled.index_select(0, idx_replay)
    tr = replay.target if idx_replay is None else replay.target.index_select(0, idx_replay)
    return w_new * F.cross_entropy(head(pn), tn) + (1 - w_new) * F.cross_entropy(head(pr), tr)


@torch.no_grad()
def pool_loss(head: RowHead, pool: Pool, chunk: int = 4096) -> float:
    total = 0.0
    for start in range(0, len(pool), chunk):
        sl = slice(start, start + chunk)
        total += float(F.cross_entropy(head(pool.pooled[sl]), pool.target[sl], reduction="sum"))
    return total / max(len(pool), 1)


@dataclass
class RowFit:
    head: RowHead
    history: list[dict] = field(default_factory=list)
    best_epoch: int = 0
    epochs_run: int = 0
    stopped_early: bool = False
    seconds: float = 0.0


def fit(
    cfg: RowConfig,
    head: RowHead,
    new: Pool,
    replay: Pool,
    val_new: Pool,
    val_replay: Pool,
    w_new: float,
    log=print,
) -> RowFit:
    """Train the head's new rows; keep the state with the lowest held-out pseudo-patient loss."""
    device = head.weight.device
    optimizer = torch.optim.Adam([head.new_weight, head.new_bias], lr=cfg.lr, weight_decay=cfg.weight_decay)
    order = torch.Generator(device="cpu").manual_seed(cfg.seed)
    replay_gen = torch.Generator(device="cpu").manual_seed(cfg.seed + 1)
    start = time.perf_counter()
    result = RowFit(head)

    def val_loss() -> dict:
        a, b = pool_loss(head, val_new), pool_loss(head, val_replay)
        return {"new": a, "replay": b, "loss": w_new * a + (1 - w_new) * b}

    best = val_loss()
    result.history.append({"epoch": 0, "val": best})
    best_state, since = copy.deepcopy(head.state_dict()), 0
    for epoch in range(1, cfg.max_epochs + 1):
        perm = torch.randperm(len(new), generator=order).to(device)
        total, steps = 0.0, 0
        for b in range(0, len(new), cfg.batch_new):
            idx_new = perm[b : b + cfg.batch_new]
            idx_replay = torch.randint(len(replay), (cfg.batch_replay,), generator=replay_gen).to(device)
            step_loss = loss(head, new, replay, w_new, idx_new, idx_replay)
            optimizer.zero_grad(set_to_none=True)
            step_loss.backward()
            optimizer.step()
            total += float(step_loss.detach())
            steps += 1
        row = {"epoch": epoch, "train_loss": total / max(steps, 1), "val": val_loss()}
        result.history.append(row)
        if row["val"]["loss"] < best["loss"] - cfg.min_delta:
            best, best_state, since, result.best_epoch = (
                row["val"],
                copy.deepcopy(head.state_dict()),
                0,
                epoch,
            )
        else:
            since += 1
        result.epochs_run = epoch
        if epoch % 10 == 0 or epoch == 1:
            log(
                f"  epoch {epoch}: train {row['train_loss']:.4f} val {row['val']['loss']:.4f} "
                f"(new {row['val']['new']:.3f}, replay {row['val']['replay']:.3f}; best {best['loss']:.4f} "
                f"@ {result.best_epoch})"
            )
        if since >= cfg.patience:
            result.stopped_early = True
            break
    head.load_state_dict(best_state)
    result.seconds = time.perf_counter() - start
    return result


def mean_rows(heads: Sequence[RowHead]) -> tuple[np.ndarray, np.ndarray]:
    """The seed ensemble: the mean of the trainable rows (logits are linear in them, so this is the mean
    logit)."""
    weight = torch.stack([h.new_weight.detach().double().cpu() for h in heads]).mean(0)
    bias = torch.stack([h.new_bias.detach().double().cpu() for h in heads]).mean(0)
    return weight.numpy(), bias.numpy()
