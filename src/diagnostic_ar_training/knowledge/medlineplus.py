"""MedlinePlus Genetics (NLM): condition-gene links, inheritance and the page sections.

The `medlineplus_genetics` snapshot (scripts/sources/snapshot_medlineplus.py) is a
tar.gz holding the bulk compendium `ghr-summaries.xml` and each condition's web page
`condition/<slug>.html`. The compendium gives genes, inheritance codes, database
keys (OMIM, GTR, MeSH…) and the description; the page adds the Frequency (disease
prevalence, as prose), Causes and Inheritance sections. Section text is kept as
plain prose: nothing is extracted from it here.
"""

import html
import re
import tarfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

NS = "{https://medlineplus.gov/download/ghr-summaries-20250602.xsd}"
COMPENDIUM = "ghr-summaries.xml"
PAGE_SECTIONS = ("description", "frequency", "causes", "inheritance")
INHERITANCE_HPO = {
    "ad": "HP:0000006",
    "ar": "HP:0000007",
    "x": "HP:0001417",
    "xr": "HP:0001419",
    "xd": "HP:0001423",
    "y": "HP:0001450",
    "m": "HP:0001427",
    "ac": "HP:0012274",
}
_BOOKMARK = re.compile(r'<div class="mp-exp exp-full" data-bookmark="([a-z-]+)">')
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Condition:
    slug: str
    name: str
    page: str
    genes: tuple[str, ...]
    inheritance: tuple[str, ...]
    """MedlinePlus inheritance codes (ad, ar, xl, xlr, xld, mito, ac, n, u, …)."""
    db_keys: tuple[tuple[str, str], ...]
    synonyms: tuple[str, ...]
    reviewed: str
    sections: dict[str, str] = field(default_factory=dict, hash=False, compare=False)

    @property
    def omim_ids(self) -> tuple[str, ...]:
        return tuple(f"OMIM:{key}" for db, key in self.db_keys if db == "OMIM")

    @property
    def inheritance_hpo(self) -> tuple[str, ...]:
        return tuple(INHERITANCE_HPO[c] for c in self.inheritance if c in INHERITANCE_HPO)


def _text(fragment: str) -> str:
    return _SPACE.sub(" ", html.unescape(_TAG.sub(" ", fragment))).strip()


def _slug(page: str) -> str:
    return page.rstrip("/").rsplit("/", 1)[-1]


def parse_compendium(xml: bytes) -> list[Condition]:
    """Every health-condition summary, with the description as plain text."""
    out = []
    for c in ET.fromstring(xml):
        if c.tag != f"{NS}health-condition-summary":
            continue
        page = c.findtext(f"{NS}ghr-page") or ""
        sections = {}
        for text in c.iter(f"{NS}text"):
            role = text.findtext(f"{NS}text-role")
            body = text.find(f"{NS}html")
            if role and body is not None:
                sections[role] = _SPACE.sub(" ", "".join(body.itertext())).strip()
        out.append(
            Condition(
                slug=_slug(page),
                name=c.findtext(f"{NS}name") or "",
                page=page,
                genes=tuple(sorted({g.text for g in c.iter(f"{NS}gene-symbol") if g.text})),
                inheritance=tuple(p.findtext(f"{NS}code") or "" for p in c.iter(f"{NS}inheritance-pattern")),
                db_keys=tuple(
                    (k.findtext(f"{NS}db") or "", k.findtext(f"{NS}key") or "") for k in c.iter(f"{NS}db-key")
                ),
                synonyms=tuple(s.text for s in c.iter(f"{NS}synonym") if s.text),
                reviewed=c.findtext(f"{NS}reviewed") or "",
                sections=sections,
            )
        )
    return out


def parse_page(page_html: str) -> dict[str, str]:
    """A condition page's bookmarked sections (description, frequency, causes, …) as text."""
    parts = _BOOKMARK.split(page_html)
    out = {}
    for name, body in zip(parts[1::2], parts[2::2], strict=True):
        heading_end = body.find("</h2>")
        out[name] = _text(body[heading_end + 5 :] if heading_end >= 0 else body)
    return out


def load(path: Path) -> list[Condition]:
    """The snapshot's conditions, with page sections overriding the compendium's."""
    with tarfile.open(path, "r:gz") as tar:
        conditions = parse_compendium(tar.extractfile(COMPENDIUM).read())
        pages = {
            m.name.removeprefix("condition/").removesuffix(".html"): m
            for m in tar.getmembers()
            if m.name.startswith("condition/")
        }
        for c in conditions:
            if c.slug in pages:
                sections = parse_page(tar.extractfile(pages[c.slug]).read().decode("utf-8"))
                c.sections.update({k: v for k, v in sections.items() if k in PAGE_SECTIONS and v})
    return conditions
