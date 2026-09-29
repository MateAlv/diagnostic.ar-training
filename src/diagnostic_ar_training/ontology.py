"""HPO ontology from hp.json: is_a structure, labels and id resolution."""

import json
from functools import lru_cache
from pathlib import Path

_OBO = "http://purl.obolibrary.org/obo/"
_ALT_ID = "http://www.geneontology.org/formats/oboInOwl#hasAlternativeId"
_REPLACED_BY = "http://purl.obolibrary.org/obo/IAO_0100001"

ROOT = "HP:0000001"
PHENOTYPIC_ABNORMALITY = "HP:0000118"
ONSET = "HP:0003674"
MODE_OF_INHERITANCE = "HP:0000005"


def _curie(value: str) -> str:
    if value.startswith(_OBO):
        value = value[len(_OBO) :]
    return value.replace("_", ":", 1) if value.startswith("HP_") else value


class Ontology:
    def __init__(
        self,
        parents: dict[str, tuple[str, ...]],
        labels: dict[str, str],
        alt_ids: dict[str, str],
        replaced_by: dict[str, str],
        obsolete: frozenset[str],
    ) -> None:
        self._parents = parents
        self.labels = labels
        self._alt_ids = alt_ids
        self._replaced_by = replaced_by
        self.obsolete = obsolete
        children: dict[str, list[str]] = {}
        for child, ps in parents.items():
            for p in ps:
                children.setdefault(p, []).append(child)
        self._children = {k: tuple(sorted(v)) for k, v in children.items()}

    @classmethod
    def from_json(cls, path: Path) -> "Ontology":
        graph = json.loads(Path(path).read_text())["graphs"][0]
        parents: dict[str, set[str]] = {}
        labels, alt_ids, replaced_by, obsolete = {}, {}, {}, set()
        for node in graph["nodes"]:
            term = _curie(node["id"])
            if not term.startswith("HP:"):
                continue
            parents.setdefault(term, set())
            if node.get("lbl"):
                labels[term] = node["lbl"]
            meta = node.get("meta", {})
            if meta.get("deprecated"):
                obsolete.add(term)
            for prop in meta.get("basicPropertyValues", []):
                if prop["pred"] == _ALT_ID:
                    alt_ids[_curie(prop["val"])] = term
                elif prop["pred"] == _REPLACED_BY:
                    replaced_by[term] = _curie(prop["val"])
        for edge in graph["edges"]:
            if edge["pred"] != "is_a":
                continue
            child, parent = _curie(edge["sub"]), _curie(edge["obj"])
            if child.startswith("HP:") and parent.startswith("HP:"):
                parents.setdefault(child, set()).add(parent)
        return cls(
            {k: tuple(sorted(v)) for k, v in parents.items()},
            labels,
            alt_ids,
            replaced_by,
            frozenset(obsolete),
        )

    def __contains__(self, term: str) -> bool:
        return term in self._parents

    def resolve(self, term: str) -> str | None:
        """Current, non-obsolete id for a term, alternative id or replaced term; else None."""
        seen = set()
        while term not in seen:
            seen.add(term)
            if term in self._alt_ids:
                term = self._alt_ids[term]
            elif term in self.obsolete:
                if term not in self._replaced_by:
                    return None
                term = self._replaced_by[term]
            else:
                return term if term in self._parents else None
        return None

    def parents(self, term: str) -> tuple[str, ...]:
        return self._parents.get(term, ())

    @lru_cache(maxsize=65536)  # noqa: B019 -- one Ontology per process, cache lives with it
    def ancestors(self, term: str) -> frozenset[str]:
        """Strict ancestors (the term itself excluded)."""
        out: set[str] = set()
        for p in self.parents(term):
            out.add(p)
            out |= self.ancestors(p)
        return frozenset(out)

    @lru_cache(maxsize=65536)  # noqa: B019
    def descendants(self, term: str) -> frozenset[str]:
        out: set[str] = set()
        for c in self._children.get(term, ()):
            out.add(c)
            out |= self.descendants(c)
        return frozenset(out)

    def is_a(self, term: str, ancestor: str) -> bool:
        return term == ancestor or ancestor in self.ancestors(term)
