"""Snapshot MedlinePlus Genetics: the bulk summaries XML plus every condition page.

The bulk compendium (ghr-summaries.xml) holds each condition's description,
genes, inheritance codes and database keys, but not the Frequency, Causes or
Inheritance sections, which exist only on the condition web pages. This script
downloads the compendium, then each condition page it lists, and packs them
unmodified into one tar.gz:
- ghr-summaries.xml
- condition/<slug>.html

Members are sorted with fixed mtime, owner and mode, so the archive depends only
on the downloaded bytes. The output is pinned in data/sources.yaml as a release
asset (ADR-0005).

Usage: python scripts/sources/snapshot_medlineplus.py OUT.tar.gz
"""

import gzip
import io
import sys
import tarfile
import time
import urllib.request
import xml.etree.ElementTree as ET

BULK = "https://medlineplus.gov/download/ghr-summaries.xml"
NS = "{https://medlineplus.gov/download/ghr-summaries-20250602.xsd}"
PAUSE_S = 0.5
UA = {"User-Agent": "diagnostic.ar-training research snapshot"}


def get(url: str) -> bytes:
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as h:
                return h.read()
        except OSError:
            if attempt == 4:
                raise
            time.sleep(10 * (attempt + 1))
    raise RuntimeError(url)


def add(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size, info.mtime, info.mode = len(data), 0, 0o644
    tar.addfile(info, io.BytesIO(data))


def main() -> None:
    out = sys.argv[1]
    bulk = get(BULK)
    root = ET.fromstring(bulk)
    pages = sorted(
        {c.findtext(f"{NS}ghr-page") for c in root if c.tag == f"{NS}health-condition-summary"} - {None}
    )
    files = {"ghr-summaries.xml": bulk}
    for url in pages:
        slug = url.rstrip("/").rsplit("/", 1)[1]
        files[f"condition/{slug}.html"] = get(url + "/")
        time.sleep(PAUSE_S)
    with gzip.GzipFile(out, "wb", mtime=0) as gz, tarfile.open(fileobj=gz, mode="w") as tar:
        for name in sorted(files):
            add(tar, name, files[name])
    print(f"{len(pages)} condition pages + compendium -> {out}")


if __name__ == "__main__":
    main()
