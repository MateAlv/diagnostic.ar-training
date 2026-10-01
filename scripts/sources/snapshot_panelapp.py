"""Snapshot Genomics England PanelApp (public API v1) into one gzipped JSON.

Pages through /api/v1/panels/ and /api/v1/genes/ (every gene entry of every
public panel, with its panel, confidence level, phenotypes and publications)
and writes {"retrieved_utc", "api", "panels": [...], "genes": [...]}, sorted by
panel and entity. The output is pinned in
data/sources.yaml as a release asset (ADR-0005).

Usage: python scripts/sources/snapshot_panelapp.py OUT.json.gz
"""

import gzip
import json
import sys
import time
import urllib.request
from datetime import UTC, datetime

API = "https://panelapp.genomicsengland.co.uk/api/v1"
PAUSE_S = 0.5


def fetch(url: str) -> dict:
    for attempt in range(5):
        try:
            headers = {"Accept": "application/json", "User-Agent": "diagnostic.ar-training research snapshot"}
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=120) as h:
                return json.load(h)
        except OSError:
            if attempt == 4:
                raise
            time.sleep(10 * (attempt + 1))
    raise RuntimeError(url)


def pages(endpoint: str) -> list[dict]:
    url, out = f"{API}/{endpoint}/", []
    while url:
        page = fetch(url)
        out.extend(page["results"])
        url = page["next"]
        time.sleep(PAUSE_S)
    return out


def main() -> None:
    out = sys.argv[1]
    retrieved = datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ")
    panels = sorted(pages("panels"), key=lambda p: p["id"])
    genes = sorted(pages("genes"), key=lambda g: (g["panel"]["id"], g["entity_name"]))
    doc = {"retrieved_utc": retrieved, "api": API, "panels": panels, "genes": genes}
    with gzip.GzipFile(out, "wb", mtime=0) as h:
        h.write(json.dumps(doc, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    print(f"{len(panels)} panels, {len(genes)} gene entries -> {out}")


if __name__ == "__main__":
    main()
