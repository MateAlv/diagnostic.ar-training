#!/usr/bin/env bash
# ADR-0012 G3, reviewer B: Codex reviews each card independently (it never sees reviewer A's verdict).
# Usage: scripts/g3/review_codex.sh <cards dir>
set -euo pipefail
dir="$1"
here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$dir/codex"
for card in "$dir"/card-*.md; do
  name="$(basename "$card" .md)"
  out="$dir/codex/$name.json"
  [[ -s "$out" ]] && continue
  if ! codex exec --skip-git-repo-check --ephemeral -s read-only \
      --output-schema "$here/verdict.schema.json" -o "$out" \
      "$(cat "$here/reviewer_prompt.txt")" < "$card" > "$dir/codex/$name.log" 2>&1; then
    echo "codex failed on $name" >&2
    rm -f "$out"
    exit 1
  fi
  echo "$name: $(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["verdict"])' "$out")"
done
