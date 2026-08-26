#!/usr/bin/env python3
"""wave_kinds.py — the neutral managed-universe module for run_all stages 4-6.

Membership metadata ONLY (spec-stages-datasets §3.4 rule 1, arbiter F1): the
40 kind<->sheet pairs of cdb_emit.py waves 1+2, carried here so that

  - promote_drafts.py  (stage 4/5 promotion whitelist),
  - relink_catalog.py  (stage 5 catalog universe),
  - validate_all.py    (stage 6 per-kind checks), and
  - cdb_verify.py      (scan scope; it keeps its own census transcription and
                        ALL derivation logic independent)

consume ONE definition. Sharing the kind list does not dilute the emitter/
verifier independence (spec §3.3) — sharing derivation code would, and none
is shared: this file derives nothing.

Kind-vs-sheet naming trap (spec §10 hole 6): `craft` emits as kind `recipe`;
`class` is emitted from sheet `unitClass`; filenames, matrix rows and join
keys use KIND names everywhere.
"""

# Verbatim mirror of cdb_emit.WAVES (kind, sourceSheet) pairs.
WAVES = {
    "wave1": [("item", "item"), ("skill", "skill"), ("class", "unitClass")],
    "wave2": [
        ("icon", "icon"), ("tutorial", "tutorial"), ("notify", "notify"),
        ("groupType", "groupType"), ("frescos", "frescos"),
        ("region", "region"), ("kingdom", "kingdom"), ("env", "env"),
        ("activity", "activity"), ("itemType", "itemType"),
        ("recipe", "craft"), ("loot", "loot"), ("mission", "mission"),
        ("confessions", "confessions"), ("startChoice", "startChoice"),
        ("trait", "trait"), ("unitPattern", "unitPattern"),
        ("attribute", "attribute"), ("status", "status"),
        ("battle", "battle"), ("effect", "effect"), ("bonus", "bonus"),
        ("counter", "counter"), ("condition", "condition"),
        ("sound", "sound"), ("amb", "amb"), ("fiefPlace", "fiefPlace"),
        ("fiefGoal", "fiefGoal"), ("fiefCondition", "fiefCondition"),
        ("fiefAlignment", "fiefAlignment"),
        ("fiefAdministration", "fiefAdministration"),
        ("fiefPopulation", "fiefPopulation"), ("fiefEvent", "fiefEvent"),
        ("fiefMission", "fiefMission"), ("fiefLaw", "fiefLaw"),
        ("input", "input"), ("credits", "credits"),
    ],
}

MANAGED_PAIRS = tuple(WAVES["wave1"]) + tuple(WAVES["wave2"])
MANAGED_KINDS = frozenset(k for k, _ in MANAGED_PAIRS)

KIND_SHEETS = dict(MANAGED_PAIRS)                      # kind -> source sheet
SHEET_TO_KIND = {sheet: kind for kind, sheet in MANAGED_PAIRS}

EXPECTED_PAIR_FILES = 51   # frozen §2 (8 wave-1 + 43 wave-2); wave-3 growth
                           # re-freezes per the EXTRACTION-LOG §5 procedure

# Deferred-kinds honesty list (spec-stages-datasets §3.5, frozen content).
# Embedded verbatim by validate_all.py in validation-report.json.deferred[]
# and rendered by relink_catalog.py in RELATIONS.md.
DEFERRED = (
    {
        "id": "hbson-decoded-kinds",
        "kinds": ["location-place(sheet place)", "enemy group",
                  "npc/dialogue(element)", "poi/battle-scene(levelProps)"],
        "why": "decoded (Dig 7, hbson_emit.py): datasets already sit in "
               "_draft (place 536 / group 791 / element 5180 / levelProps "
               "5982 occurrences, 235 distinct payloads); NOT promoted by "
               "stages 4-6 (non-managed). Origin of the deferral: the four "
               "top-level sheets carry zero inline rows - payloads are the "
               "HBSON prefab corpus; the CDB side ships their schema via "
               "hidden sub-sheets",
        "unblock": "R1",
    },
    {
        "id": "achievement",
        "kinds": ["achievement"],
        "why": "emitted keyless (Dig 10): 235-row dataset sits in _draft "
               "(buildId n/a); not a CDB sheet - Steam GetSchemaForGame "
               "surface; client half ships in counter.jsonl incl. "
               "counter@props.achievements; NOT promoted by stages 4-6 "
               "(non-managed)",
        "unblock": "R2",
    },
    {
        "id": "constant",
        "kinds": ["constant"],
        "why": "already emitted as extracted/logic/constants.jsonl (1266 "
               "rows, dig 2) - deliberately NOT duplicated into data/",
        "unblock": "none - closure counts it",
    },
    {
        "id": "subset-views",
        "kinds": ["potion/food", "trade-good/price", "path/title",
                  "ghost/curse views"],
        "why": "subset views over emitted datasets, not sheets (itemType ids "
               "Food/CookedMeat/TradeGoods/Recipe; traits "
               "RawFood/Trader/Cook/SonOfTrader; constants TradeGood*; "
               "unitClass Ghost* x6 + groupType GhostPack* + status "
               "GhostLeader*) - derivable by joins on shipped files, no "
               "separate emission owed (Dig 3)",
        "unblock": "none - joins",
    },
)


def split_pair_name(filename):
    """`<from>__<to>.jsonl` -> (from, to), else None (hole 1 name rule)."""
    base = filename[:-6] if filename.endswith(".jsonl") else None
    if not base or "__" not in base:
        return None
    a, b = base.split("__", 1)
    if not a or not b:
        return None
    return a, b


def is_pair_name(filename):
    return split_pair_name(filename) is not None


assert len(MANAGED_KINDS) == 40, len(MANAGED_KINDS)
assert len(KIND_SHEETS) == 40 and len(SHEET_TO_KIND) == 40
