"""Resolve append-only doc merge conflicts by keeping both sides (main's entries first).

Usage: merge_bitacora.py [file ...]   (default: docs/BITACORA.md)
Exits non-zero if any conflict marker is left, so callers can stop instead of committing markers.
"""

import sys


def resolve(path: str) -> None:
    res, state, ours, theirs = [], None, [], []
    for line in open(path).read().split("\n"):
        if line.startswith("<<<<<<<"):
            state, ours, theirs = "ours", [], []
        elif line == "=======" and state == "ours":
            state = "theirs"
        elif line.startswith(">>>>>>>") and state == "theirs":
            res += theirs + [""] + ours
            state = None
        else:
            (ours if state == "ours" else theirs if state == "theirs" else res).append(line)
    open(path, "w").write("\n".join(res))


left = []
for path in sys.argv[1:] or ["docs/BITACORA.md"]:
    resolve(path)
    text = open(path).read().split("\n")
    if any(line.startswith(("<<<<<<<", ">>>>>>>")) or line == "=======" for line in text):
        left.append(path)
if left:
    sys.exit(f"conflict markers left in: {', '.join(left)}")
