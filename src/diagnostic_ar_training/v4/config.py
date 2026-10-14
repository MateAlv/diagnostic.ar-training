"""A v4 run's configuration, loaded from YAML and hashed into its run id.

The id is `<label>-<hash10>`: the hash covers every field except the label, plus the sha256 of the simulator
parameters file when there is one, so two runs share an id only when they would train the same model from
the same data stream. Fields added after the first runs (`HASH_NEUTRAL`) are left out of the hash at their
default, so existing run ids do not change. Unknown YAML keys are errors.
"""

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any

import yaml

from diagnostic_ar_training import REPO_ROOT

EDGES = ("up", "both")
POOLINGS = ("attention", "attention_mean")
INITS = ("e0", "scratch")
RUN_INIT = re.compile(r"run:([A-Za-z0-9][A-Za-z0-9._-]*?)(?:@(best|last))?")
SCHEDULES = ("cosine", "plateau", "constant")
GENE_DRAWS = ("uniform",)
REAL_DRAWS = ("patient", "gene")
FIT_FOLDS = (0, 1, 2)
REAL_FOLDS = (0, 1, 2, 3)
CONFIRM_FOLD = 4
E0_SHAPE = {"hidden": 512, "layers": 3}
DEFAULT_FACTORY = "diagnostic_ar_training.v4.samplers:sim4"


@dataclass(frozen=True)
class SimConfig:
    preset: str = "e0"
    """A `sim4.PRESETS` key."""
    params: str | None = None
    """Fitted simulator parameters (repo-relative path); its sha256 enters the run id."""
    factory: str = DEFAULT_FACTORY
    """`module:callable`, called as callable(preset, params_path) -> Sampler."""
    gene_draw: str = "uniform"
    real_ratio: float = 0.0
    """Probability that a training item is a real patient (of `real_folds`) instead of a simulated case."""
    real_draw: str = "patient"
    """'patient': the real item is a patient of `real_folds` drawn uniformly. 'gene': the gene is drawn as the
    simulator draws it; when it has real patients, with probability `real_ratio` the item is one of them
    (publication uniform among the gene's, then patient uniform within it), so the label marginal stays the
    simulator's."""
    real_folds: tuple[int, ...] = FIT_FOLDS
    """`p3-v1` train folds the real patients come from, stored sorted: FIT (0-2) by default, any of 0-3. With
    SELECT (3) among them, the best checkpoint is chosen on a fold seen in training, so read `last`. The
    CONFIRM fold (4) is refused."""

    def __post_init__(self) -> None:
        if not isinstance(self.real_folds, list | tuple) or any(type(f) is not int for f in self.real_folds):
            raise ValueError("real_folds must be a list of fold numbers")
        folds = tuple(self.real_folds)
        if not folds or len(set(folds)) != len(folds):
            raise ValueError("real_folds must be non-empty, without repeats")
        if CONFIRM_FOLD in folds:
            raise ValueError(f"real_folds: fold {CONFIRM_FOLD} is CONFIRM, never a training fold")
        if not set(folds) <= set(REAL_FOLDS):
            raise ValueError(f"real_folds must be among {REAL_FOLDS}")
        object.__setattr__(self, "real_folds", tuple(sorted(folds)))
        if self.gene_draw not in GENE_DRAWS:
            raise ValueError(f"gene_draw must be one of {GENE_DRAWS}")
        if self.real_draw not in REAL_DRAWS:
            raise ValueError(f"real_draw must be one of {REAL_DRAWS}")
        if not 0 <= self.real_ratio < 1:
            raise ValueError("real_ratio must be in [0, 1)")


@dataclass(frozen=True)
class EncodingConfig:
    observed_flag: bool = False
    ic_feature: bool = False
    edges: str = "up"
    drop_dash: bool = False
    covariates: bool = False

    def __post_init__(self) -> None:
        if self.edges not in EDGES:
            raise ValueError(f"edges must be one of {EDGES}")


@dataclass(frozen=True)
class ArchConfig:
    hidden: int = 512
    layers: int = 3
    dropout: float = 0.3
    pooling: str = "attention"
    init: str = "scratch"
    """'e0', 'scratch', or 'run:<run_id>[@best|@last]' (default last): weights of one of our v4 runs."""

    def __post_init__(self) -> None:
        if self.pooling not in POOLINGS:
            raise ValueError(f"pooling must be one of {POOLINGS}")
        if self.init not in INITS and not RUN_INIT.fullmatch(self.init):
            raise ValueError(f"init must be one of {INITS} or 'run:<run_id>[@best|@last]'")
        if self.init == "e0" and (self.hidden, self.layers) != (E0_SHAPE["hidden"], E0_SHAPE["layers"]):
            raise ValueError(f"a warm start from E0 needs E0's shape {E0_SHAPE}")
        if self.layers < 1 or self.hidden < 2:
            raise ValueError("at least one layer and two hidden channels")

    @property
    def init_run(self) -> tuple[str, str] | None:
        """(run id, 'best' or 'last') of a warm start from one of our runs, else None."""
        match = RUN_INIT.fullmatch(self.init)
        return (match.group(1), match.group(2) or "last") if match else None


@dataclass(frozen=True)
class TrainConfig:
    lr: float = 5e-4
    lr_new: float | None = None
    """Learning rate of the options' zero-initialised parameters; None = `lr`."""
    weight_decay: float = 5e-4
    batch_size: int = 128
    schedule: str = "cosine"
    warmup_steps: int = 500
    min_lr_ratio: float = 0.05
    plateau_factor: float = 0.5
    plateau_patience: int = 3
    """Evaluations without improvement before the plateau schedule cuts the learning rate."""
    clip_norm: float = 1.0
    amp: bool = True
    max_minutes: float = 60.0
    max_samples: int | None = None
    eval_every_steps: int = 2000
    patience_evals: int | None = None
    """Stop after this many evaluations without improvement; None runs the whole budget."""
    min_delta: float = 1e-4
    num_workers: int = 12

    def __post_init__(self) -> None:
        if self.schedule not in SCHEDULES:
            raise ValueError(f"schedule must be one of {SCHEDULES}")
        if self.max_minutes <= 0 and self.max_samples is None:
            raise ValueError("set a time budget (max_minutes > 0) or a sample budget (max_samples)")
        if self.batch_size < 2 or self.eval_every_steps < 1:
            raise ValueError("batch_size >= 2 and eval_every_steps >= 1")


@dataclass(frozen=True)
class RunConfig:
    label: str = "v4"
    seed: int = 0
    sim: SimConfig = field(default_factory=SimConfig)
    encoding: EncodingConfig = field(default_factory=EncodingConfig)
    arch: ArchConfig = field(default_factory=ArchConfig)
    train: TrainConfig = field(default_factory=TrainConfig)

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", self.label):
            raise ValueError(f"label {self.label!r}: letters, digits, '.', '_' and '-' only")

    def as_dict(self) -> dict:
        return asdict(self)

    def hashed_body(self) -> dict:
        body = {k: v for k, v in self.as_dict().items() if k != "label"}
        for section, defaults in HASH_NEUTRAL.items():
            for name, default in defaults.items():
                if body[section][name] == default:
                    del body[section][name]
        body["sim_params_sha256"] = params_sha256(self.sim.params)
        return body

    @property
    def config_hash(self) -> str:
        text = json.dumps(self.hashed_body(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode()).hexdigest()

    @property
    def run_id(self) -> str:
        return f"{self.label}-{self.config_hash[:10]}"


SECTIONS = {"sim": SimConfig, "encoding": EncodingConfig, "arch": ArchConfig, "train": TrainConfig}
HASH_NEUTRAL = {"sim": {"real_draw": "patient", "real_folds": FIT_FOLDS}}


def resolve(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else REPO_ROOT / p


def params_sha256(params: str | None) -> str | None:
    if params is None:
        return None
    path = resolve(params)
    if not path.is_file():
        raise FileNotFoundError(f"simulator parameters file {params} not found")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check_keys(cls, data: dict, where: str) -> None:
    unknown = set(data) - {f.name for f in fields(cls)}
    if unknown:
        raise ValueError(f"{where}: unknown keys {sorted(unknown)}")


def from_dict(data: dict) -> RunConfig:
    data = dict(data or {})
    _check_keys(RunConfig, data, "config")
    kwargs: dict[str, Any] = {}
    for name, cls in SECTIONS.items():
        section = data.pop(name, None) or {}
        _check_keys(cls, section, name)
        kwargs[name] = cls(**section)
    return RunConfig(**data, **kwargs)


def load(path: str | Path) -> RunConfig:
    return from_dict(yaml.safe_load(resolve(path).read_text()))


def dump(cfg: RunConfig) -> str:
    return yaml.safe_dump(cfg.as_dict(), sort_keys=False)


def override(cfg: RunConfig, dotted: dict[str, Any]) -> RunConfig:
    """`{"arch.hidden": 768, "seed": 1}` applied to `cfg`; every key must name an existing field."""
    data = cfg.as_dict()
    for key, value in dotted.items():
        target, *rest = key.split(".")
        if not rest:
            if target not in data or target in SECTIONS:
                raise ValueError(f"unknown override {key!r}")
            data[target] = value
            continue
        if target not in SECTIONS or len(rest) != 1 or rest[0] not in data[target]:
            raise ValueError(f"unknown override {key!r}")
        data[target][rest[0]] = value
    return from_dict(data)


def with_seed(cfg: RunConfig, seed: int) -> RunConfig:
    return replace(cfg, seed=seed)
