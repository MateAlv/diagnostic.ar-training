"""Blind re-extractor for `dxt lit crosscheck run --command`, using a minimal Claude CLI call.

Usage (as a --command template):
  python scripts/tools/claude_reextract.py --model haiku {schema} {answer} {prompt}
The source passage arrives on stdin; the answer JSON is written to {answer}. Token usage is appended to
<answer dir>/claude_usage.json so the cost of the run can be summed.
"""

import argparse
import os
import json
import re
import subprocess
import sys
from pathlib import Path

SYSTEM = (
    "You read a passage from a medical source and report one stated fact, exactly as the passage states it. "
    "Never infer or compute a number the passage does not state. Prevalence fields are proportions between 0 and 1: write 35% as 0.35 and 100% as 1. For a range, give prevalence_low, prevalence_high and their midpoint as prevalence. Reply with only one JSON object matching "
    "this JSON schema, with no prose and no code fences:\n"
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("schema")
    ap.add_argument("answer")
    ap.add_argument("prompt")
    args = ap.parse_args()
    schema = json.loads(Path(args.schema).read_text())
    passage = sys.stdin.read()
    message = f"{args.prompt}\n\n<passage>\n{passage}\n</passage>"
    proc = subprocess.run(
        ["claude", "-p", "--model", args.model, "--tools", "", "--no-session-persistence",
         "--system-prompt", SYSTEM + json.dumps(schema), "--output-format", "json"],
        input=message, capture_output=True, text=True, timeout=300,
        env={**os.environ, "MAX_THINKING_TOKENS": "0"},
    )
    if proc.returncode != 0:
        print(proc.stderr[-2000:], file=sys.stderr)
        return 1
    envelope = json.loads(proc.stdout)
    text = envelope.get("result", "")
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        print(f"no JSON in reply: {text[:500]}", file=sys.stderr)
        return 1
    answer = json.loads(match.group(0))
    missing = [k for k in schema.get("required", []) if k not in answer]
    if missing:
        print(f"reply misses keys {missing}", file=sys.stderr)
        return 1
    out = Path(args.answer)
    out.write_text(json.dumps(answer) + "\n")
    (out.parent / "claude_usage.json").write_text(
        json.dumps({"model": args.model, "usage": envelope.get("usage"), "cost_usd": envelope.get("total_cost_usd")})
        + "\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
