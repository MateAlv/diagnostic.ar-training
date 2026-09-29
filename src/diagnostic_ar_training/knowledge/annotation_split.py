"""A frozen split of HPOA positive annotations into known (A) and held-out (B) halves.

S3 generates test patients from A and B together while every system under test
only sees A (EVAL_PROTOCOL §8), so no knowledge a system uses was read off the
very annotations that produced the test patients' phenotypes.
"""

import csv
import hashlib
from pathlib import Path


def _held_out(salt: str, disease_id: str, hpo_id: str, fraction: float) -> bool:
    digest = hashlib.sha256(f"{salt}:{disease_id}|{hpo_id}".encode()).hexdigest()
    return int(digest, 16) % 10_000 < round(fraction * 10_000)


def split(hpoa: Path, fraction: float, salt: str) -> list[tuple[str, str]]:
    """Held-out (disease_id, hpo_id) pairs among positive phenotype annotations."""
    pairs = set()
    with Path(hpoa).open(encoding="utf-8", newline="") as handle:
        rows = csv.DictReader((line for line in handle if not line.startswith("#")), delimiter="\t")
        for row in rows:
            if (
                row["aspect"] == "P"
                and row["qualifier"] != "NOT"
                and row["frequency"].strip() != "HP:0040285"
            ):
                pairs.add((row["database_id"], row["hpo_id"]))
    return sorted(p for p in pairs if _held_out(salt, *p, fraction))


def write(pairs: list[tuple[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("disease_id\thpo_id\n" + "".join(f"{d}\t{t}\n" for d, t in pairs))


def read(path: Path) -> set[tuple[str, str]]:
    lines = Path(path).read_text().splitlines()
    if lines[0] != "disease_id\thpo_id":
        raise ValueError(f"{path}: unexpected header")
    return {tuple(line.split("\t")) for line in lines[1:] if line}
