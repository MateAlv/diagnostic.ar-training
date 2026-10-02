"""Resolve a docs/BITACORA.md merge conflict by keeping both sides (main's entries first)."""

p = "docs/BITACORA.md"
res, state, ours, theirs = [], None, [], []
for line in open(p).read().split("\n"):
    if line.startswith("<<<<<<<"):
        state, ours, theirs = "ours", [], []
    elif line.startswith("=======") and state == "ours":
        state = "theirs"
    elif line.startswith(">>>>>>>") and state == "theirs":
        res += theirs + [""] + ours
        state = None
    else:
        (ours if state == "ours" else theirs if state == "theirs" else res).append(line)
open(p, "w").write("\n".join(res))
