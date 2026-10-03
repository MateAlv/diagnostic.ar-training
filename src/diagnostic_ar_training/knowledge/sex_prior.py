"""Male share of real patients per simulator sex-prior class, measured on R1-train.

The class of a gene's entity follows rare-disease-simulator 0.5.4
(`simulation/simulator.py`: `entity_sex_prior_key`, `_sex_key`;
`profiles/inheritance.py`: `derive_sex_bias`; commit cfc20da), copied here with the
constants it uses so that the measurement and the generator share one definition.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence

from diagnostic_ar_training.cohorts.schema import Case, Sex
from diagnostic_ar_training.ontology import Ontology

CLASSES = (
    "male_limited",
    "female_limited",
    "male_biased",
    "female_biased",
    "x_linked_dominant",
    "unbiased",
)
SIMULATOR_DEFAULTS = {
    "male_limited": 1.0,
    "female_limited": 0.0,
    "male_biased": 0.9,
    "female_biased": 0.1,
    "x_linked_dominant": 0.33,
    "unbiased": 0.5,
}
FIXED_BY_DEFINITION = ("male_limited", "female_limited")
MIN_PATIENTS = 20

MENDELIAN_INHERITANCE = "HP:0034345"
AUTOSOMAL_MODES = ("HP:0000006", "HP:0000007", "HP:0032113")
MALE_ONLY_MODES = ("HP:0001419", "HP:0001450")
MALE_LIMITED = "HP:0001475"
FEMALE_LIMITED = "HP:0034344"
Y_LINKED = "HP:0001450"
X_LINKED_DOMINANT = "HP:0001423"
SEX_LIMITED_EXPRESSION = (MALE_LIMITED, FEMALE_LIMITED)


def derive_sex_bias(inheritance: Sequence[str], ontology: Ontology) -> str | None:
    male_limited = [t for t in inheritance if ontology.is_a(t, MALE_LIMITED)]
    female_limited = [t for t in inheritance if ontology.is_a(t, FEMALE_LIMITED)]
    modes = [t for t in inheritance if ontology.is_a(t, MENDELIAN_INHERITANCE)]
    if male_limited and not female_limited:
        return "male"
    if female_limited and not male_limited:
        return "female"
    if male_limited or female_limited:
        return None
    if modes and all(any(ontology.is_a(t, a) for a in MALE_ONLY_MODES) for t in modes):
        return "male"
    if modes and all(any(ontology.is_a(t, a) for a in AUTOSOMAL_MODES) for t in modes):
        return "none"
    return None


def sex_key(inheritance: set[str], bias: str) -> str:
    male_limited = MALE_LIMITED in inheritance or Y_LINKED in inheritance
    female_limited = FEMALE_LIMITED in inheritance
    if male_limited and not female_limited:
        return "male_limited"
    if female_limited and not male_limited:
        return "female_limited"
    if bias == "male":
        return "male_biased"
    if bias == "female":
        return "female_biased"
    if bias == "unknown" and X_LINKED_DOMINANT in inheritance:
        return "x_linked_dominant"
    return "unbiased"


def entity_sex_key(
    entity_inheritance: Sequence[str], profile_inheritance: set[str], ontology: Ontology
) -> str:
    """Sex prior class of a gene-first case: the entity's inheritance, else the profile's."""
    ids = set(entity_inheritance) | (profile_inheritance & set(SEX_LIMITED_EXPRESSION))
    if not entity_inheritance:
        ids = set(profile_inheritance)
    bias = derive_sex_bias(sorted(ids), ontology)
    return sex_key(ids, bias or "unknown")


def jeffreys_male_share(male: float, n: float) -> float:
    return (male + 0.5) / (n + 1.0)


def patient_entities(case: Case, entities: Sequence[dict]) -> list[tuple[dict, float]]:
    """The gene's entities a patient stands for, with weights summing to 1.

    The entities whose ids include one of the patient's diagnoses, else every simulable
    entity weighted by `sim_weight`, as the gene-first simulator draws them.
    """
    diagnosed = set(case.disease_ids)
    matched = [e for e in entities if diagnosed & set(e["ids"])]
    if matched:
        return [(e, 1.0 / len(matched)) for e in matched]
    simulable = [e for e in entities if e.get("simulable") and e["sim_weight"] > 0]
    total = sum(e["sim_weight"] for e in simulable)
    return [(e, e["sim_weight"] / total) for e in simulable] if total else []


def measure(
    cases: Iterable[Case],
    genes: Mapping[str, dict],
    profile_inheritance: Mapping[str, set[str]],
    ontology: Ontology,
) -> dict:
    """Male and female patient mass per class among patients with known sex."""
    by_symbol = {}
    for symbol, gene in genes.items():
        by_symbol[symbol.upper()] = gene
        if gene.get("v3_symbol"):
            by_symbol.setdefault(gene["v3_symbol"].upper(), gene)
    mass = {k: {"male": 0.0, "female": 0.0} for k in CLASSES}
    stats: dict[str, int] = defaultdict(int)
    for case in cases:
        stats["patients"] += 1
        if case.sex == Sex.UNKNOWN:
            stats["sex_unknown"] += 1
            continue
        gene = by_symbol.get(case.gene.upper())
        if gene is None:
            stats["gene_not_in_genes_table"] += 1
            continue
        picked = patient_entities(case, gene["entities"])
        if not picked:
            stats["gene_without_simulable_entity"] += 1
            continue
        diagnosed = bool(set(case.disease_ids) & {i for e, _ in picked for i in e["ids"]})
        stats["entity_by_diagnosis" if diagnosed else "entity_by_sim_weight"] += 1
        for entity, weight in picked:
            profile = set().union(*(profile_inheritance.get(i, set()) for i in entity["profile_ids"]))
            mass[entity_sex_key(entity["inheritance"], profile, ontology)][case.sex.value] += weight
    return {"mass": mass, "patients": dict(stats)}
