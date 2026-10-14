"""Curator (`metaData.createdBy`) of every fold 0-3 patient, for K3's curation-style check (PHASE3 §2e).

Only zip entries whose file name is a fold 0-3 case ID are opened, so no vault or CONFIRM phenopacket is read.
Writes `$P3_B1_DATA/curators.json` ({case_id: curator}).
"""

import collections
import json
import os
import zipfile

from diagnostic_ar_training.lineage.registry import Purpose, open_source
from diagnostic_ar_training.v4 import patients as P

DATA = os.environ.get("P3_B1_DATA", "data/interim/p3-b1") + "/"

ids = {p.case.case_id for p in P.load("fit") + P.load("select")}
out = {}
with zipfile.ZipFile(open_source("phenopacket_store", Purpose.TRAIN)) as z:
    for name in z.namelist():
        case_id = name.rsplit("/", 1)[-1].removesuffix(".json")
        if case_id in ids:
            out[case_id] = json.loads(z.read(name))["metaData"].get("createdBy", "")
json.dump(out, open(DATA + "curators.json", "w"), indent=0, sort_keys=True)
print(len(out), "of", len(ids), "patients;", collections.Counter(out.values()).most_common(8))
