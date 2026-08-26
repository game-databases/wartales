#!/usr/bin/env python3
"""dig15_logic_edges.py — Data dig 15 (bar 1): ordered-pair relink matrix
upgrade, evidence layer.

For EVERY direction currently `partial` or `missing` in
extracted/relinks/matrix.json this tool either

  (a) derives edges with mechanism `logic` | `inferred` (method recorded per
      edge family) from skill-script bodies, CDB payload id references and
      schema facts — emitted as
      extracted/relinks/_logic/<kindA>__<kindB>.jsonl
      ({fromId,toId,mechanism,method,evidence} rows, `_meta` first line) —
or (b) ledgers the direction with a CONCRETE unblock in
      extracted/relinks/_logic/_ledger.jsonl (never "unknown").

This is the EVIDENCE layer only: canonical promotion stays a later spec
re-freeze. Canonical bytes under extracted/relinks/*.jsonl and
extracted/data/*.jsonl are read-only here.

Deterministic: sorted iteration, fixed ordering, no wall clock.

  python pipeline/tools/dig15_logic_edges.py            # full pass
  python pipeline/tools/dig15_logic_edges.py --dry-run  # no writes
"""
import argparse
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wave_kinds  # noqa: E402  (SHEET_TO_KIND: census sheet -> spec kind)

PACK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(PACK, "extracted", "data", "_draft")
RELDIR = os.path.join(PACK, "extracted", "relinks")
LOGIC = os.path.join(RELDIR, "_logic")
MATRIX = os.path.join(RELDIR, "matrix.json")
SCRATCH = os.path.join(PACK, "output", "_dig-relink-matrix")

BUILDID = "20318128"
DIG = "15"

# ---------------------------------------------------------------- loading --


def read_jsonl(path):
    with open(path, "r", encoding="utf-8") as f:
        head = json.loads(f.readline())
        return head.get("_meta", {}), [json.loads(l) for l in f]


def load_all():
    kinds = {}
    metas = {}
    for fn in sorted(os.listdir(DATA)):
        if fn.endswith(".jsonl"):
            k = fn[:-6]
            metas[k], kinds[k] = read_jsonl(os.path.join(DATA, fn))
    return kinds, metas


# ---------------------------------------------------------------- walking --


def walk(obj, path=""):
    """Yield (path, container, key, value) for every scalar."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else k
            if isinstance(v, (dict, list)):
                yield from walk(v, p)
            else:
                yield p, obj, k, v
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, f"{path}[]")
    return


def get_path(row, dotted):
    """Navigate 'a.b[].c' — returns list of scalars found."""
    out = []

    def rec(o, parts):
        if not parts:
            if isinstance(o, (str, int, float, bool)):
                out.append(o)
            return
        head, rest = parts[0], parts[1:]
        if head.endswith("[]"):
            key = head[:-2]
            if isinstance(o, dict) and key in o and isinstance(o[key], list):
                for v in o[key]:
                    rec(v, rest)
        else:
            if isinstance(o, dict) and head in o:
                rec(o[head], rest)

    rec(row, dotted.split("."))
    return out


# ------------------------------------------------------------ derivations --


def _strip_props(dotted):
    """'props.a.b' -> 'a.b' (canonical join keys are written without the
    payload prefix; dataset columns sit at the row root)."""
    parts = dotted.split(".")
    if parts and parts[0] == "props":
        return ".".join(parts[1:])
    return dotted


def _norm_path(path):
    return _strip_props(re.sub(r"\[\d+\]", "[]", path))


def _walk_strings(obj, path=""):
    """Yield (path, value) for every string scalar; textKey routing objects
    are locale plumbing, not entity references."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "textKey":
                continue
            yield from _walk_strings(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_strings(v, f"{path}[]")
    elif isinstance(obj, str):
        yield path, obj

SCRIPT_ENUMS = [
    # (enum prefix in hscript, target managed kind)
    ("Skill", "skill"),
    ("Status", "status"),
    ("UnitClass", "class"),
    ("Trait", "trait"),
    ("Attribute", "attribute"),
    ("Item", "item"),
]
SCRIPT_RE = re.compile(
    r"\b(Skill|Status|UnitClass|Trait|Attribute|Item)\.([A-Za-z_][A-Za-z0-9_]*)"
)


# --- dig15 fix round (verify-dig15-b M1/M2) ---------------------------------
# Declarative admission table: every data.cdb-typed payload carrier admitted
# under the family-admission rule stated in docs/data-dig-log.mdx (Dig 15):
#   admit iff (1) data.cdb declares the path (top-level sheet or hidden
#   sub-sheet A@b@c chain) with reference type 6:<target sheet>;
#   (2) >=1 populated value resolves exactly into the target kind's draft id
#       set (unresolved values recorded as unresolvedRefs, never dropped);
#   (3) the carrier is positive (negated conditions noHasTrait /
#       noPersonalities / noTargetsHasTrait carry inverted polarity and stay
#       out -- excluded with reasons, same evidence bar); (4) both ends are
#       managed scaffold kinds (deferred element/group/place/levelProps stay
#       outside, queued).
# tag 'm1'    -> new evidence family on a direction ledgered
#                unadjudicated-name-hits (data.cdb itself adjudicates it);
# tag 'merge' -> additional join key inside an already-emitted family;
# tag 'fold'  -> carrier on an already-modeled direction (fold-note file);
# tag 'self'  -> self-pair carrier family.
# Each line comments its resolution count (resolved/populated) and the
# declaring data.cdb column chain. Census proof:
# output/_dig15-fix/p1_census.json (+ p3_family_probe.py re-derivation).
FIX_ROUND_CARRIERS = [
        ('battle', 'props.globalSkills[].skill', 'skill', 'fold', 'data.cdb battle@props@globalSkills@skill:6:skill'),  # 53/53
        ('confessions', 'data[].choices[].cost.traitCost[].trait', 'trait', 'fold', 'data.cdb confessions@data@choices@cost@traitCost@trait:6:trait'),  # 5/5
        ('counter', 'props.displayIcon', 'icon', 'fold', 'data.cdb counter@props@displayIcon:6:icon'),  # 8/8
        ('fiefPlace', 'props.conds[].cond', 'condition', 'fold', 'data.cdb fiefPlace@props@conds@cond:6:condition'),  # 12/12
        ('fiefPlace', 'props.serviceCosts[].counter', 'counter', 'fold', 'data.cdb fiefPlace@props@serviceCosts@counter:6:counter'),  # 2/2
        ('fiefPlace', 'props.serviceCosts[].item', 'item', 'fold', 'data.cdb fiefPlace@props@serviceCosts@item:6:item'),  # 2/2
        ('item', 'props.displayType', 'itemType', 'fold', 'data.cdb item@props@displayType:6:itemType'),  # 1/1
        ('item', 'tool.requiredWeapon[].weapon', 'itemType', 'fold', 'data.cdb item@tool@requiredWeapon@weapon:6:itemType'),  # 2/2
        ('item', 'tool.tavern.refCustomization', 'itemType', 'fold', 'data.cdb item@tool@tavern@refCustomization:6:itemType'),  # 8/8
        ('region', 'props.sameDifficultyAs', 'region', 'fold', 'data.cdb region@props@sameDifficultyAs:6:region'),  # 4/4
        ('status', 'props.attributePercent', 'attribute', 'fold', 'data.cdb status@props@attributePercent:6:attribute'),  # 5/5
        ('status', 'props.attributeValue', 'attribute', 'fold', 'data.cdb status@props@attributeValue:6:attribute'),  # 3/3
        ('activity', 'props.onFailStatus', 'status', 'm1', 'data.cdb activity@props@onFailStatus:6:status'),  # 1/1
        ('activity', 'props.tutorial', 'tutorial', 'm1', 'data.cdb activity@props@tutorial:6:tutorial'),  # 9/9
        ('bonus', 'props.icon', 'icon', 'm1', 'data.cdb bonus@props@icon:6:icon'),  # 43/43
        ('bonus', 'props.loot', 'loot', 'm1', 'data.cdb bonus@props@loot:6:loot'),  # 5/5
        ('bonus', 'props.unitCondition.skills[].skill', 'skill', 'm1', 'data.cdb bonus@props@unitCondition@skills@skill:6:skill'),  # 4/4
        ('bonus', 'props.unitCondition.status', 'status', 'm1', 'data.cdb bonus@props@unitCondition@status:6:status'),  # 3/3
        ('confessions', 'data[].choices[].gains.attributePoint[].bonus', 'attribute', 'm1', 'data.cdb confessions@data@choices@gains@attributePoint@bonus:6:attribute'),  # 6/6
        ('confessions', 'data[].choices[].gains.dailyBonuses[].bonus', 'bonus', 'm1', 'data.cdb confessions@data@choices@gains@dailyBonuses@bonus:6:bonus'),  # 2/2
        ('counter', 'props.unit', 'item', 'm1', 'data.cdb counter@props@unit:6:item'),  # 9/9
        ('counter', 'props.loot', 'loot', 'm1', 'data.cdb counter@props@loot:6:loot'),  # 7/7
        ('env', 'camp.contextualTool', 'item', 'm1', 'data.cdb env@camp@contextualTool:6:item'),  # 18/18
        ('fiefAlignment', 'props.counter', 'counter', 'm1', 'data.cdb fiefAlignment@props@counter:6:counter'),  # 4/4
        ('fiefAlignment', 'props.populations[].pop', 'fiefPopulation', 'm1', 'data.cdb fiefAlignment@props@populations@pop:6:fiefPopulation'),  # 5/5
        ('fiefAlignment', 'props.displayIcon', 'icon', 'm1', 'data.cdb fiefAlignment@props@displayIcon:6:icon'),  # 5/5
        ('fiefEvent', 'consequences.alignment[].alignment', 'fiefAlignment', 'm1', 'data.cdb fiefEvent@consequences@alignment@alignment:6:fiefAlignment'),  # 92/92
        ('fiefEvent', 'consequences.fx.visuals[].place', 'fiefPlace', 'm1', 'data.cdb fiefEvent@consequences@fx@visuals@place:6:fiefPlace'),  # 1/1
        ('fiefEvent', 'consequences.populationType[].population', 'fiefPopulation', 'm1', 'data.cdb fiefEvent@consequences@populationType@population:6:fiefPopulation'),  # 51/51
        ('fiefEvent', 'params[].filter.populationTypes[].type', 'fiefPopulation', 'm1', 'data.cdb fiefEvent@params@filter@populationTypes@type:6:fiefPopulation'),  # 20/20
        ('fiefEvent', 'consequences.decodeCodex', 'item', 'm1', 'data.cdb fiefEvent@consequences@decodeCodex:6:item'),  # 1/1
        ('fiefEvent', 'consequences.items[].inf', 'item', 'm1', 'data.cdb fiefEvent@consequences@items@inf:6:item'),  # 3/3
        ('fiefEvent', 'consequences.gainAlly', 'kingdom', 'm1', 'data.cdb fiefEvent@consequences@gainAlly:6:kingdom'),  # 4/4
        ('fiefEvent', 'consequences.relationLevel[].kingdom', 'kingdom', 'm1', 'data.cdb fiefEvent@consequences@relationLevel@kingdom:6:kingdom'),  # 19/19
        ('fiefEvent', 'consequences.fx.mood', 'sound', 'm1', 'data.cdb fiefEvent@consequences@fx@mood:6:sound'),  # 7/7
        ('fiefEvent', 'consequences.traits[].trait', 'trait', 'm1', 'data.cdb fiefEvent@consequences@traits@trait:6:trait'),  # 3/3
        ('fiefEvent', 'params[].props.unitTrait', 'trait', 'm1', 'data.cdb fiefEvent@params@props@unitTrait:6:trait'),  # 1/1
        ('fiefMission', 'props.conds[].cond', 'condition', 'm1', 'data.cdb fiefMission@props@conds@cond:6:condition'),  # 10/10
        ('fiefMission', 'props.reward[].counter', 'counter', 'm1', 'data.cdb fiefMission@props@reward@counter:6:counter'),  # 12/12
        ('fiefMission', 'props.onCancel', 'fiefEvent', 'm1', 'data.cdb fiefMission@props@onCancel:6:fiefEvent'),  # 1/1
        ('fiefMission', 'props.region', 'region', 'm1', 'data.cdb fiefMission@props@region:6:region'),  # 5/5
        ('fiefPlace', 'props.effects[].ref', 'effect', 'm1', 'data.cdb fiefPlace@props@effects@ref:6:effect'),  # 38/38
        ('fiefPlace', 'props.alignments[].alignment', 'fiefAlignment', 'm1', 'data.cdb fiefPlace@props@alignments@alignment:6:fiefAlignment'),  # 18/18
        ('fiefPlace', 'props.populationType[].pop', 'fiefPopulation', 'm1', 'data.cdb fiefPlace@props@populationType@pop:6:fiefPopulation'),  # 16/16
        ('fiefPopulation', 'inf.effects[].ref', 'effect', 'm1', 'data.cdb fiefPopulation@inf@effects@ref:6:effect'),  # 16/16
        ('groupType', 'props.tavern.bonusRequired.bonus', 'bonus', 'm1', 'data.cdb groupType@props@tavern@bonusRequired@bonus:6:bonus'),  # 3/3
        ('groupType', 'props.tavern.firstDayBonus[].bonus', 'bonus', 'm1', 'data.cdb groupType@props@tavern@firstDayBonus@bonus:6:bonus'),  # 1/1
        ('groupType', 'props.tavern.song', 'counter', 'm1', 'data.cdb groupType@props@tavern@song:6:counter'),  # 15/15
        ('groupType', 'props.sail', 'item', 'm1', 'data.cdb groupType@props@sail:6:item'),  # 4/4
        ('groupType', 'props.tavern.itemRequired', 'item', 'm1', 'data.cdb groupType@props@tavern@itemRequired:6:item'),  # 3/3
        ('groupType', 'props.tavern.menuItemRequired.item[].item', 'item', 'm1', 'data.cdb groupType@props@tavern@menuItemRequired@item@item:6:item'),  # 2/2
        ('groupType', 'props.tavern.menuItemRequired.itemType[].type', 'itemType', 'm1', 'data.cdb groupType@props@tavern@menuItemRequired@itemType@type:6:itemType'),  # 2/2
        ('groupType', 'props.tavern.jobRequired', 'trait', 'm1', 'data.cdb groupType@props@tavern@jobRequired:6:trait'),  # 1/1
        ('item', 'props.faction', 'groupType', 'm1', 'data.cdb item@props@faction:6:groupType'),  # 227/227
        ('item', 'props.tavern.attractedFactions[].faction', 'groupType', 'm1', 'data.cdb item@props@tavern@attractedFactions@faction:6:groupType'),  # 237/237
        ('item', 'tool.tavern.factions[].faction', 'groupType', 'm1', 'data.cdb item@tool@tavern@factions@faction:6:groupType'),  # 62/62
        ('item', 'props.converts.action', 'icon', 'm1', 'data.cdb item@props@converts@action:6:icon'),  # 9/9
        ('item', 'props.refIcons[].icon', 'icon', 'm1', 'data.cdb item@props@refIcons@icon:6:icon'),  # 3/3
        ('item', 'props.sfx.onCampAction', 'sound', 'm1', 'data.cdb item@props@sfx@onCampAction:6:sound'),  # 1/1
        ('item', 'props.sfx.onUse', 'sound', 'm1', 'data.cdb item@props@sfx@onUse:6:sound'),  # 1/1
        ('item', 'props.specialStatus[].inf', 'status', 'm1', 'data.cdb item@props@specialStatus@inf:6:status'),  # 2/2
        ('item', 'tool.statusOnRest', 'status', 'm1', 'data.cdb item@tool@statusOnRest:6:status'),  # 1/1
        ('item', 'tool.statusRestAdjacent', 'status', 'm1', 'data.cdb item@tool@statusRestAdjacent:6:status'),  # 5/5
        ('item', 'tool.requiredJob', 'trait', 'm1', 'data.cdb item@tool@requiredJob:6:trait'),  # 27/27
        ('skill', 'props.bonuses[].bonus', 'bonus', 'm1', 'data.cdb skill@props@bonuses@bonus:6:bonus'),  # 16/16
        ('skill', 'props.cursor', 'icon', 'm1', 'data.cdb skill@props@cursor:6:icon'),  # 6/6
        ('skill', 'props.tooltipText[].icon', 'icon', 'm1', 'data.cdb skill@props@tooltipText@icon:6:icon'),  # 15/15
        ('startChoice', 'props.bonuses[].bonus', 'bonus', 'm1', 'data.cdb startChoice@props@bonuses@bonus:6:bonus'),  # 19/19
        ('startChoice', 'props.pathCounter', 'counter', 'm1', 'data.cdb startChoice@props@pathCounter:6:counter'),  # 10/10
        ('startChoice', 'props.items[].item', 'item', 'm1', 'data.cdb startChoice@props@items@item:6:item'),  # 20/20
        ('status', 'props.bonuses[].bonus', 'bonus', 'm1', 'data.cdb status@props@bonuses@bonus:6:bonus'),  # 1/1
        ('trait', 'props.tavern.unitCategories[].category', 'class', 'm1', 'data.cdb trait@props@tavern@unitCategories@category:6:unitClass'),  # 17/17
        ('trait', 'props.tavern.specialities[].unlock[].counter', 'counter', 'm1', 'data.cdb trait@props@tavern@specialities@unlock@counter:6:counter'),  # 12/12
        ('trait', 'props.requireFood', 'itemType', 'm1', 'data.cdb trait@props@requireFood:6:itemType'),  # 3/3
        ('trait', 'props.kingdomCondition', 'kingdom', 'm1', 'data.cdb trait@props@kingdomCondition:6:kingdom'),  # 4/4
        ('trait', 'props.skill', 'skill', 'm1', 'data.cdb trait@props@skill:6:skill'),  # 5/5
        ('trait', 'props.fromStatus', 'status', 'm1', 'data.cdb trait@props@fromStatus:6:status'),  # 1/1
        ('tutorial', 'props.reward.counters[].counter', 'counter', 'm1', 'data.cdb tutorial@props@reward@counters@counter:6:counter'),  # 2/2
        ('bonus', 'props.unitCondition.globalBonus', 'bonus', 'merge', 'data.cdb bonus@props@unitCondition@globalBonus:6:bonus'),  # 1/1
        ('confessions', 'data[].choices[].gains.injury[].inf', 'status', 'merge', 'data.cdb confessions@data@choices@gains@injury@inf:6:status'),  # 3/3
        ('groupType', 'props.tavern.menuItemRequired.region', 'region', 'merge', 'data.cdb groupType@props@tavern@menuItemRequired@region:6:region'),  # 1/1
        ('groupType', 'props.tavern.region', 'region', 'merge', 'data.cdb groupType@props@tavern@region:6:region'),  # 14/14
        ('item', 'props.buyRequireBonus', 'bonus', 'merge', 'data.cdb item@props@buyRequireBonus:6:bonus'),  # 1/1
        ('item', 'props.refBonus', 'bonus', 'merge', 'data.cdb item@props@refBonus:6:bonus'),  # 5/5
        ('item', 'tool.bonusesIfAssigned[].bonus', 'bonus', 'merge', 'data.cdb item@tool@bonusesIfAssigned@bonus:6:bonus'),  # 34/34
        ('item', 'tool.personalBonuses[].bonus', 'bonus', 'merge', 'data.cdb item@tool@personalBonuses@bonus:6:bonus'),  # 8/8
        ('item', 'tool.tavern.bonuses[].bonus', 'bonus', 'merge', 'data.cdb item@tool@tavern@bonuses@bonus:6:bonus'),  # 132/132
        ('item', 'props.buyRequireCounter', 'counter', 'merge', 'data.cdb item@props@buyRequireCounter:6:counter'),  # 6/6
        ('item', 'props.refCounter', 'counter', 'merge', 'data.cdb item@props@refCounter:6:counter'),  # 11/11
        ('item', 'props.song', 'counter', 'merge', 'data.cdb item@props@song:6:counter'),  # 2/2
        ('item', 'props.passiveSkill', 'skill', 'merge', 'data.cdb item@props@passiveSkill:6:skill'),  # 283/283
        ('mission', 'props.replace', 'mission', 'merge', 'data.cdb mission@props@replace:6:mission'),  # 2/2
        ('skill', 'levels[].props.attributes[].kind', 'attribute', 'merge', 'data.cdb skill@levels@props@attributes@kind:6:attribute'),  # 4/4
        ('skill', 'props.attributes[].kind', 'attribute', 'merge', 'data.cdb skill@props@attributes@kind:6:attribute'),  # 21/21
        ('skill', 'props.objectUnit', 'class', 'merge', 'data.cdb skill@props@objectUnit:6:unitClass'),  # 4/4
        ('skill', 'props.unlockClass', 'class', 'merge', 'data.cdb skill@props@unlockClass:6:unitClass'),  # 8/8
        ('skill', 'props.fireSkills[].ammo', 'item', 'merge', 'data.cdb skill@props@fireSkills@ammo:6:item'),  # 2/2
        ('skill', 'props.itemCost.item', 'item', 'merge', 'data.cdb skill@props@itemCost@item:6:item'),  # 55/56
        ('skill', 'props.weapon', 'item', 'merge', 'data.cdb skill@props@weapon:6:item'),  # 7/7
        ('skill', 'props.copyDesc', 'skill', 'merge', 'data.cdb skill@props@copyDesc:6:skill'),  # 7/7
        ('skill', 'props.copyScript', 'skill', 'merge', 'data.cdb skill@props@copyScript:6:skill'),  # 3/3
        ('skill', 'props.fireSkills[].skill', 'skill', 'merge', 'data.cdb skill@props@fireSkills@skill:6:skill'),  # 3/3
        ('skill', 'props.replaceSkill', 'skill', 'merge', 'data.cdb skill@props@replaceSkill:6:skill'),  # 8/8
        ('skill', 'props.switchData.switchSkills[].skill', 'skill', 'merge', 'data.cdb skill@props@switchData@switchSkills@skill:6:skill'),  # 12/12
        ('skill', 'levels[].props.tooltipStatus[].st', 'status', 'merge', 'data.cdb skill@levels@props@tooltipStatus@st:6:status'),  # 33/33
        ('skill', 'props.destructiveStatus[].status', 'status', 'merge', 'data.cdb skill@props@destructiveStatus@status:6:status'),  # 1/1
        ('skill', 'props.tooltipStatus[].st', 'status', 'merge', 'data.cdb skill@props@tooltipStatus@st:6:status'),  # 772/772
        ('skill', 'props.learnTrait', 'trait', 'merge', 'data.cdb skill@props@learnTrait:6:trait'),  # 1/1
        ('status', 'props.descSkill', 'skill', 'merge', 'data.cdb status@props@descSkill:6:skill'),  # 1/1
        ('trait', 'props.contentBonuses[].mainStat', 'attribute', 'merge', 'data.cdb trait@props@contentBonuses@mainStat:6:attribute'),  # 6/6
        ('trait', 'props.tavern.attributes[].attribute', 'attribute', 'merge', 'data.cdb trait@props@tavern@attributes@attribute:6:attribute'),  # 20/20
        ('trait', 'props.levels[].bonus', 'bonus', 'merge', 'data.cdb trait@props@levels@bonus:6:bonus'),  # 49/49
        ('trait', 'props.tavern.levels[].bonuses[].bonus', 'bonus', 'merge', 'data.cdb trait@props@tavern@levels@bonuses@bonus:6:bonus'),  # 59/59
        ('trait', 'props.tavern.spyingReward[].bonus', 'bonus', 'merge', 'data.cdb trait@props@tavern@spyingReward@bonus:6:bonus'),  # 10/10
        ('fiefEvent', 'consequences.planEvents[].event', 'fiefEvent', 'self', 'data.cdb fiefEvent@consequences@planEvents@event:6:fiefEvent'),  # 18/18
        ('fiefGoal', 'props.nextGoal', 'fiefGoal', 'self', 'data.cdb fiefGoal@props@nextGoal:6:fiefGoal'),  # 8/8
        ('groupType', 'props.aggroTargets[].type', 'groupType', 'self', 'data.cdb groupType@props@aggroTargets@type:6:groupType'),  # 41/41
        ('groupType', 'props.parentCategory', 'groupType', 'self', 'data.cdb groupType@props@parentCategory:6:groupType'),  # 57/57
        ('item', 'props.converts.item', 'item', 'self', 'data.cdb item@props@converts@item:6:item'),  # 9/9
        ('item', 'props.refItem', 'item', 'self', 'data.cdb item@props@refItem:6:item'),  # 326/326
        ('item', 'props.refItemLoca', 'item', 'self', 'data.cdb item@props@refItemLoca:6:item'),  # 49/49
        ('item', 'props.refItems[].item', 'item', 'self', 'data.cdb item@props@refItems@item:6:item'),  # 96/96
        ('status', 'props.copyDesc', 'status', 'self', 'data.cdb status@props@copyDesc:6:status'),  # 8/8
        ('status', 'props.similarStatus', 'status', 'self', 'data.cdb status@props@similarStatus:6:status'),  # 2/2
        ('trait', 'props.cantBeWith[].kind', 'trait', 'self', 'data.cdb trait@props@cantBeWith@kind:6:trait'),  # 47/47
        ('trait', 'props.jobRequire', 'trait', 'self', 'data.cdb trait@props@jobRequire:6:trait'),  # 2/2
        ('trait', 'props.tavern.attributes[].trait', 'trait', 'self', 'data.cdb trait@props@tavern@attributes@trait:6:trait'),  # 20/20
        ('trait', 'props.tavern.scaleWithJobs[].job', 'trait', 'self', 'data.cdb trait@props@tavern@scaleWithJobs@job:6:trait'),  # 6/6
        ('trait', 'props.tavern.specialities[].trait', 'trait', 'self', 'data.cdb trait@props@tavern@specialities@trait:6:trait'),  # 30/30
]


NEGATED_CARRIER_PATHS = (
    # proven typed carriers excluded by rule (3): polarity-inverted conditions
    # (confessions->trait, 41 resolving refs) -- documented exclusion, not an
    # oversight; see p1_census.json decisions.
    "data[].choices[].props.noHasTrait",
    "data[].choices[].props.noPersonalities[].trait",
    "data[].extraConditions.noHasTrait",
    "data[].extraConditions.noTargetsHasTrait",
)


class Deriver:
    def __init__(self, kinds, metas):
        self.kinds = kinds
        self.metas = metas
        self.ids = {
            k: {(r["id"] if "id" in r else r["_id"]) for r in rows}
            for k, rows in kinds.items()}
        # direction -> list of edge dicts
        self.found = collections.defaultdict(list)
        # family bookkeeping: (from,to,family) -> counters
        self.stats = collections.defaultdict(
            lambda: {"refsSeen": 0, "emitted": 0,
                     "unresolved": [], "ambiguous": []})
        # src kind -> set of dotted paths whose value namespace is TYPED to
        # some target (derived this dig or canonically modeled join keys);
        # the residual sweep excludes these when judging other directions
        self.pinned = collections.defaultdict(set)
        # (src,dst) -> {"total": n, "top": [(path, count)...], "examples":[..]}
        self.residual = {}
        # (src,dst) -> [data.cdb declaring column chains] (fix-round table)
        self.carrier_decls = collections.defaultdict(list)
        # (src,dst) -> set of admission tags from FIX_ROUND_CARRIERS
        self.carrier_tags = collections.defaultdict(set)
        self.hl_corroboration = {
            "skill__status":
                "extracted/decompiled/hl-src/src/battle/Unit.hx.hx "
                "battle.Unit.getCaptureChance f#7774 pcs 43-55 consumes the "
                "'Fierce' status count and pcs 221-263 reads globalSkills "
                "'HuntBonusEasyCapture' (disasm-formula-findings §3.1)",
            "skill__skill":
                "extracted/decompiled/hl-src/src/ui/win/UnitInfo.hx.hx and "
                "script runtime resolve Skill.<id> globals; skill.jsonl "
                "OpportunityAttack.onEval compares castOrigin == "
                "Skill.Disengage",
            # --- fix-round additions (consumer greps in
            # output/_dig15-fix/p3_family_probe.json, contexts hand-read) ---
            "startChoice__counter":
                "extracted/decompiled/hl-src/src/ui/win/Paths.hx.hx:543/700 "
                "reads troopChoice.props.pathCounter and compares it against "
                "counter ids (p0.id) — the start-choice path progress "
                "consumer",
            "status__attribute":
                "extracted/decompiled/hl-src/src/st/Status.hx.hx:371/381/389 "
                "reads props.attributePercent and :248/:257 attributeValue "
                "for status stat rows",
            "item__skill":
                "item.props.passiveSkill consumed at "
                "src/ui/dev/TeamManagement.hx.hx:1466/8371 and "
                "src/st/player/Simulation.hx.hx:4622 (joins the modeled "
                "props.skill family this dig already emitted)",
            "battle__skill":
                "battle.props.globalSkills consumed at "
                "src/battle/Unit.hx.hx:2887/2938/16614 (globalSkill ids "
                "resolved as Skill.<id>; fold onto the canonically modeled "
                "direction)",
            "groupType__groupType":
                "src/st/Group.hx.hx:30 reads groupType.parentCategory "
                "(category tree self-chain)",
            "region__region":
                "src/st/Region.hx.hx:1711 reads sameDifficultyAs "
                "(difficulty-twin regions; fold onto the canonical "
                "next[].region self-pair)",
        }

    # -- family helpers -----------------------------------------------------
    def add(self, fam, frm, to, mech, meth, ev):
        lst = self.found[fam]
        for e in lst:
            if e["fromId"] == frm and e["toId"] == to:
                if len(e["_paths"]) < 3 and ev not in e["_paths"]:
                    e["_paths"].append(ev)
                return False
        lst.append({"fromId": frm, "toId": to, "mechanism": mech,
                    "method": meth, "evidence": ev, "_paths": [ev]})
        return True

    def scan_script_enums(self):
        st = self.stats
        for row in self.kinds["skill"]:
            s = row.get("script") or ""
            if not s:
                continue
            for m in SCRIPT_RE.finditer(s):
                prefix, name = m.group(1), m.group(2)
                tgt = dict(SCRIPT_ENUMS)[prefix]
                sk = ("skill", tgt)
                st[sk + ("hscript",)]["refsSeen"] += 1
                if name in self.ids[tgt]:
                    ev = (f"extracted/data/_draft/skill.jsonl#{row['id']}"
                          f".script@{m.start()} '{prefix}.{name}'")
                    if self.add(sk, row["id"], name, "logic",
                                f"hscript-enum-ref:{prefix}", ev):
                        st[sk + ("hscript",)]["emitted"] += 1
                else:
                    u = st[sk + ("hscript",)]["unresolved"]
                    if name not in u:
                        u.append(name)

    def scan_typed(self, kind, dotted, tgt, fam=None, conv=str,
                   decl=None, tag=None):
        """Typed leaf join: values at dotted path resolved against tgt ids."""
        st = self.stats
        sk = (kind, tgt)
        if decl:
            self.carrier_decls[sk].append(decl)
        if tag:
            self.carrier_tags[sk].add(tag)
        self.pinned[kind].add(dotted)
        self.pinned[kind].add(_strip_props(dotted))
        for row in self.kinds[kind]:
            for v in get_path(row, dotted):
                val = conv(v)
                st[sk + ("payload",)]["refsSeen"] += 1
                if val in self.ids[tgt]:
                    ev = (f"extracted/data/_draft/{kind}.jsonl#{row['id']}"
                          f":{dotted}='{val}'")
                    if self.add(sk, row["id"], val, "inferred",
                                "cdb-payload-id-join", ev):
                        st[sk + ("payload",)]["emitted"] += 1
                else:
                    u = st[sk + ("payload",)]["unresolved"]
                    if val not in u:
                        u.append(val)

    def scan_item_bonus_dicts(self):
        """Any dict under an item row keyed exactly 'bonus' (string value)
        resolves against bonus ids — covers props.bonuses and
        tool.bonusesIfAssigned without enumerating every nesting."""
        st = self.stats
        sk = ("item", "bonus")
        self.pinned["item"].add("props.bonuses[].bonus")
        self.pinned["item"].add("props.tool.bonusesIfAssigned[].bonus")
        for row in self.kinds["item"]:
            for p, cont, k, v in walk(row.get("props"), "props"):
                if k == "bonus" and isinstance(v, str):
                    self.pinned["item"].add(_norm_path(p))
                    st[sk + ("payload",)]["refsSeen"] += 1
                    if v in self.ids["bonus"]:
                        ev = (f"extracted/data/_draft/item.jsonl#{row['id']}"
                              f":{p}='{v}'")
                        if self.add(sk, row["id"], v, "inferred",
                                    "cdb-payload-id-join", ev):
                            st[sk + ("payload",)]["emitted"] += 1
                    else:
                        u = st[sk + ("payload",)]["unresolved"]
                        if v not in u:
                            u.append(v)

    def scan_confessions_gains(self):
        """confessions@data gains trees: gains.<K>[].inf typed by the parent
        key K ∈ {item,status,trait}; cost.itemCost[].item typed by 'item'.
        Direct 'trait' conditions ride the already-modeled personality
        family and stay out of the evidence layer."""
        st = self.stats
        typed_targets = ("item", "status", "trait")
        for tgt in typed_targets:
            self.pinned["confessions"].add(f"data[].choices[].gains.{tgt}[].inf")
        self.pinned["confessions"].add("data[].choices[].cost.itemCost[].item")
        self.pinned["confessions"].add("data[].personality")
        for row in self.kinds["confessions"]:
            data = row.get("data")
            if not isinstance(data, list):
                continue
            for p, cont, k, v in walk(data, "data"):
                if not isinstance(v, str):
                    continue
                # gains.<K>[].inf  (path ...gains.<K>[].inf)
                m = re.search(r"\.gains\.([A-Za-z]+)\[\]\.inf$", p)
                if m:
                    self.pinned["confessions"].add(_norm_path(p))
                if m and m.group(1) in typed_targets:
                    tgt = m.group(1)
                    sk = ("confessions", tgt)
                    st[sk + ("payload",)]["refsSeen"] += 1
                    if v in self.ids[tgt]:
                        ev = (f"extracted/data/_draft/confessions.jsonl#"
                              f"{row['id']}:{p}='{v}'")
                        if self.add(sk, row["id"], v, "inferred",
                                    "cdb-payload-id-join", ev):
                            st[sk + ("payload",)]["emitted"] += 1
                    else:
                        u = st[sk + ("payload",)]["unresolved"]
                        if v not in u:
                            u.append(v)
                    continue
                # cost.itemCost[].item
                if p.endswith(".itemCost[].item"):
                    sk = ("confessions", "item")
                    st[sk + ("payload",)]["refsSeen"] += 1
                    if v in self.ids["item"]:
                        ev = (f"extracted/data/_draft/confessions.jsonl#"
                              f"{row['id']}:{p}='{v}'")
                        if self.add(sk, row["id"], v, "inferred",
                                    "cdb-payload-id-join", ev):
                            st[sk + ("payload",)]["emitted"] += 1
                    else:
                        u = st[sk + ("payload",)]["unresolved"]
                        if v not in u:
                            u.append(v)

    def run(self):
        self.scan_script_enums()
        self.scan_typed("counter", "props.confession", "confessions")
        self.scan_typed("counter", "props.trait", "trait")
        self.scan_typed("bonus", "props.items[].item", "item")
        self.scan_typed("bonus", "props.attribute", "attribute")
        self.scan_typed("bonus", "props.bonuses[].bonus", "bonus")
        self.scan_typed("bonus", "props.similarAs", "bonus")
        self.scan_item_bonus_dicts()
        self.scan_typed("notify", "props.loot", "loot")
        self.scan_typed("mission", "props.region", "region")
        self.scan_typed("mission", "props.parentMission", "mission")
        self.scan_typed("groupType", "props.pattern", "unitPattern")
        self.scan_typed("startChoice", "props.pattern", "unitPattern")
        self.scan_typed("status", "props.skills[].skill", "skill")
        self.scan_typed("region", "props.peddlerItems", "loot")
        # --- dig 15 r2 additions (probe-verified carrier families) ---
        self.scan_typed("item", "props.skill", "skill")            # 381/381
        self.scan_typed("battle", "props.recruitClasses[].unitClass",
                        "class")                                    # 40/40
        self.scan_typed("battle", "props.rewards[].item", "item")   # 50/50
        # polymorphic target refs: resolving half -> counters, rest stay
        # recorded as unresolvedRefs (fiefPlace/fiefCondition targets)
        self.scan_typed("fiefEvent", "consequences.effects[].target[]",
                        "counter")
        self.scan_typed("item", "props.fief.effects[].target[]", "counter")
        self.scan_typed("fiefEvent", "consequences.effects[].ref",
                        "effect")                                   # 245/245
        self.scan_typed("item", "props.fief.effects[].ref",
                        "effect")                                   # 360/360
        self.scan_typed("class", "props.status[].kind",
                        "status")                                   # 43/43
        self.scan_typed("trait", "props.attributes[].kind",
                        "attribute")                                # 150/150
        self.scan_typed("trait", "props.contentBonuses[].bonus",
                        "bonus")                                    # 62/62
        self.scan_typed("itemType", "props.dismantleLoot",
                        "loot")                                     # 28/28
        self.scan_typed("item", "props.region", "region")          # 113/113
        self.scan_typed("groupType", "props.loot[].t", "loot")      # 93/93
        # --- dig 15 r3 additions (probe-verified 100% carriers) ---
        self.scan_typed("class", "props.trait", "trait")            # 22/22
        self.scan_typed("fiefEvent", "consequences.goal",
                        "fiefGoal")                                 # 25/25
        self.scan_typed("itemType", "props.baseBonusDefault",
                        "item")                                     # 20/20
        self.scan_typed("groupType", "props.regions[].region",
                        "region")                                   # 15/15
        self.scan_typed("item", "props.activity",
                        "activity")                                 # 21/21
        # region counters: every scalar under props.counters resolving into
        # counter ids (keys localTeamDefeated/blackmarketFinished/... +
        # finishConfessions[].counter)
        self.scan_region_counters()
        self.scan_confessions_gains()
        # --- dig15 fix round: data.cdb hidden-sub-sheet typed carriers ------
        # (verify-dig15-b M1/M2; admission rule + census proof in the table
        # comment above). Deterministic order: table is sorted by tag/dir/path.
        for kind, dotted, tgt, tag, decl in FIX_ROUND_CARRIERS:
            self.scan_typed(kind, dotted, tgt, decl=decl, tag=tag)

    def pin_canonical(self, matrix_json):
        """Record canonically modeled join keys as typed paths per source."""
        for p in matrix_json["pairs"]:
            for side, (x, y) in (("forward", (p["a"], p["b"])),
                                 ("reverse", (p["b"], p["a"]))):
                if p[side]["status"] == "modeled":
                    for k in p[side].get("joinKeys") or []:
                        self.pinned[x].add(k)

    def residual_sweep(self):
        """Global exact-name sweep over ALL string scalars of every managed
        kind, EXCLUDING paths pinned (typed) for that source kind. Anything
        left is an unadjudicated name match for its direction — never an
        edge, but it must appear in the ledger instead of a zero-carrier
        claim."""
        hits = collections.defaultdict(lambda: collections.Counter())
        examples = collections.defaultdict(list)
        for x, rows in sorted(self.kinds.items()):
            skip = self.pinned.get(x, set())
            for row in rows:
                rid = row.get("id") or row.get("_id")
                for path, v in _walk_strings(row):
                    if _norm_path(path) in skip:
                        continue
                    for y in sorted(self.ids.keys()):
                        if y == x or v not in self.ids[y]:
                            continue
                        fam = re.sub(r"\[\d+\]", "[]", path)
                        hits[(x, y)][_norm_path(fam)] += 1
                        if len(examples[(x, y, fam)]) < 2:
                            examples[(x, y, fam)].append(f"{rid}:{path}={v!r}")
        self.residual = {}
        for key, fams in hits.items():
            top = fams.most_common(3)
            ex = []
            for p, _c in top:
                ex.extend(examples[(key[0], key[1], p)][:1])
            # verify-dig15-b m2: hits resting ONLY on the row's own `id`
            # field are namespace coincidences of the identifier itself,
            # not payload values — flagged so the ledger says so.
            self.residual[key] = {
                "total": sum(fams.values()),
                "top": top,
                "examples": ex[:3],
                "ownIdOnly": set(fams.keys()) == {"id"},
                "pathCount": len(fams),
            }

    def scan_region_counters(self):
        st = self.stats
        sk = ("region", "counter")
        for row in self.kinds["region"]:
            base = (row.get("props") or {}).get("counters")
            if not isinstance(base, dict):
                continue
            for p, cont, k, v in walk(base, "props.counters"):
                if isinstance(v, str):
                    self.pinned["region"].add(_norm_path(p))
                    st[sk + ("payload",)]["refsSeen"] += 1
                    if v in self.ids["counter"]:
                        ev = (f"extracted/data/_draft/region.jsonl#"
                              f"{row['id']}:{p}='{v}'")
                        if self.add(sk, row["id"], v, "inferred",
                                    "cdb-payload-id-join", ev):
                            st[sk + ("payload",)]["emitted"] += 1
                    else:
                        u = st[sk + ("payload",)]["unresolved"]
                        if v not in u:
                            u.append(v)


# ------------------------------------------------------------- schema side --


def schema_ref_targets(metas):
    """kind -> set of target KINDS named by declared 6:<sheet> columns."""
    out = collections.defaultdict(set)
    for kind, meta in metas.items():
        for c in meta.get("columns", []):
            ts = c.get("typeStr", "")
            if ts.startswith("6:"):
                sheet = ts[2:]
                tgt = wave_kinds.SHEET_TO_KIND.get(sheet)
                if tgt is not None and tgt in wave_kinds.MANAGED_KINDS:
                    out[kind].add(tgt)
    return out


# ----------------------------------------------------------------- output --


def emit_logic_files(deriver, dry=False):
    written = []
    os.makedirs(LOGIC, exist_ok=True)
    # canonical modeled directions (matrix.json) — evidence files landing on
    # one of these stay out of bar-1 accounting and carry an explicit fold
    # note instead.
    with open(MATRIX, encoding="utf-8") as f:
        m = json.load(f)
    modeled = set()
    for p in m["pairs"]:
        if p["forward"]["status"] == "modeled":
            modeled.add((p["a"], p["b"]))
        if p["reverse"]["status"] == "modeled":
            modeled.add((p["b"], p["a"]))
    # canonical self-pairs are modeled directions too — fix-round carriers
    # landing on one (region.props.sameDifficultyAs) carry the fold note.
    for sp in m.get("selfPairs", []):
        modeled.add((sp["kind"], sp["kind"]))
    dirs = sorted(deriver.found.keys())
    for (frm, to) in dirs:
        edges = sorted(deriver.found[(frm, to)],
                       key=lambda e: (e["fromId"], e["toId"]))
        fam_stats = []
        for tag in ("hscript", "payload"):
            s = deriver.stats.get((frm, to, tag))
            if s:
                fam_stats.append({
                    "family": ("hscript-enum-ref" if tag == "hscript"
                               else "cdb-payload-id-join"),
                    **{k: v for k, v in s.items() if k != "unresolved"},
                    "unresolvedRefs": sorted(s["unresolved"])[:24],
                    "unresolvedRefCount": len(s["unresolved"]),
                })
        methods = sorted({e["method"].split(":")[0] for e in edges})
        promotes = ("hard"
                    if methods == ["cdb-payload-id-join"]
                    else "mixed (code-side families promote as logic)")
        meta = {
            "_meta": {
                "dig": DIG,
                "buildId": BUILDID,
                "layer": "evidence (pre-canonical)",
                "fromKind": frm,
                "toKind": to,
                "rowCount": len(edges),
                "methods": methods,
                "promotionExpectation": promotes,
                "families": fam_stats,
                "hlCorroboration": deriver.hl_corroboration.get(
                    f"{frm}__{to}"),
                "recheck": (
                    "re-run pipeline/tools/dig15_logic_edges.py over the same "
                    "draft bytes; every edge re-derives from its evidence "
                    "path"),
            }
        }
        decls = sorted(set(deriver.carrier_decls.get((frm, to), [])))
        if decls:
            meta["_meta"]["cdbDeclarations"] = decls
            meta["_meta"]["admission"] = (
                "family-admission rule (dig-15 fix round): data.cdb-declared "
                "6:<target> reference columns, >=1 populated value resolving "
                "into the target id set, positive polarity, managed scaffold "
                "kinds only")
            tags = deriver.carrier_tags.get((frm, to))
            if tags:
                meta["_meta"]["admissionTags"] = sorted(tags)
        if (frm, to) in modeled:
            meta["_meta"]["modeledDirectionNote"] = (
                "direction already modeled canonically; this file carries "
                "ADDITIONAL join keys beyond the canonical join keys for "
                "the next spec re-freeze fold (data.cdb-schema-typed where "
                "_meta.admissionTags is present) — not counted as a bar-1 "
                "transition")
        path = os.path.join(LOGIC, f"{frm}__{to}.jsonl")
        lines = [json.dumps(meta, ensure_ascii=False)]
        for e in edges:
            lines.append(json.dumps(
                {"fromId": e["fromId"], "toId": e["toId"],
                 "mechanism": e["mechanism"], "method": e["method"],
                 "evidence": e["evidence"]},
                ensure_ascii=False))
        if not dry:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(lines) + "\n")
        written.append((frm, to, len(edges)))
    return written


UNRELATED = (
    "structurally unrelated at buildid 20318128 under the dig-15 global "
    "sweep: zero exact-name payload matches outside typed join keys, zero "
    "hscript enum hits, and no data.cdb-declared 6-column (top level or "
    "hidden sub-sheet, dig-15 fix-round census) carries a value resolving "
    "into this target kind — recheck at TargetBuildID 21238928 patch-diff")

NAME_HITS = (
    "exact-name payload matches exist but none adjudicates as a relation "
    "at this dig: the dig-15 fix-round hidden-sub-sheet census leaves "
    "these paths with NO data.cdb-declared reference type whose values "
    "resolve into this target kind's ids, and no code consumer pins them; "
    "values equally resolve into other kinds' id namespaces (cross-kind "
    "name collisions). Unblock: prove a code consumer or a schema retype "
    "at TargetBuildID 21238928 patch-diff, then promote via "
    "cdb-payload-id-join")

TERMINAL = {
    "icon": ("terminal registry", "atlas/icon registry consumed only "
             "inbound (canonical: counter.path, recipe.group, "
             "attribute.icon; evidence layer since the dig-15 fix round: "
             "bonus.icon, skill.cursor/tooltipText[].icon, "
             "item.converts.action/refIcons[], counter.displayIcon, "
             "fiefAlignment.displayIcon); other kinds carry atlas "
             "descriptors routed straight to UIA assets (dig 4 resolution "
             "mechanism), never through icon-sheet ids"),
    "input": ("terminal registry", "bindings/category scalars only; no "
              "outbound id carrier exists in client data or code"),
    "credits": ("terminal registry", "credits roll — lines/linesTrad text "
                "only"),
    "sound": ("audio carve-out", "Wwise-carried relations sit outside the "
              "corpus by media carve-out ([DR-2026-08-18-media-scope]); "
              "data-side joins are inbound (canonical amb.mood/battleMood + "
              "gameObject self-chain; evidence layer since the dig-15 fix "
              "round: fiefEvent.consequences.fx.mood, item.props.sfx)"),
    "kingdom": ("leaf vocabulary", "bare rows (name/props flags like "
                "fiefCanTrade); kingdom joins are inbound (canonical "
                "region.kingdom modeled reverse; evidence layer since the "
                "dig-15 fix round: fiefEvent.relationLevel[].kingdom/"
                "gainAlly, trait.kingdomCondition)"),
    "condition": ("leaf vocabulary", "comment/done scalars; consumers "
                  "reference it inbound (canonical fiefEvent.conditions[]"
                  ".cond, fiefPlace.productions[].conds[].cond; evidence "
                  "layer since the dig-15 fix round: "
                  "fiefMission.props.conds[].cond)"),
    "effect": ("leaf vocabulary", "implement bool + numeric target enums, "
               "no id-typed outbound columns"),
    "fiefCondition": ("leaf vocabulary", "numeric target enums; consumed "
                      "inbound by fiefGoal/fiefCondition chains"),
    "fiefAlignment": ("leaf vocabulary", "names/desc/props scalars only"),
    "fiefPopulation": ("leaf vocabulary", "name/inf scalars only"),
    "tutorial": ("inward-only chain", "steps[].tuto self-chain (modeled); "
                 "no outbound entity ids"),
    "startChoice": ("inward-only chain", "troopChoices self-chain (modeled);"
                    " outbound carriers live in the evidence layer since "
                    "dig 15 (props.pattern→unitPattern; fix round added "
                    "pathCounter/items[]/bonuses[]) — nothing unmodeled "
                    "remains at this build"),
    "trait": ("bitmask vocabulary", "gen bitmask + condition enum — flag-"
              "name mapping to unitClass.flags stays unproven; unblock: "
              "decode the shared enum tables in data.cdb customTypes"),
    "skill": ("code-side only", "skill subtree declares ZERO hard-reference "
              "columns (dig 1 finding 4) — remaining carriers would be "
              "runtime wiring behind unresolved closure call sites (8,964 "
              "OCallClosure, dig 13 residual); script-enum families are in "
              "the evidence layer"),
}


def classify_directions(kinds, metas, matrix_json, derived_dirs, residual):
    """Produce ledger + transition records for all ordered directions."""
    schema_refs = schema_ref_targets(metas)
    inbound = collections.defaultdict(set)
    for p in matrix_json["pairs"]:
        for side, (x, y) in (("forward", (p["a"], p["b"])),
                             ("reverse", (p["b"], p["a"]))):
            if p[side]["status"] == "modeled":
                inbound[y].add(x)
    for sp in matrix_json["selfPairs"]:
        inbound[sp["kind"]].add(sp["kind"])
    for dt in matrix_json["deferredTargetPairs"]:
        inbound[dt["target"]].add(dt["fromKind"])

    ledger = []
    transitions = []
    for p in matrix_json["pairs"]:
        for side, (x, y) in (("forward", (p["a"], p["b"])),
                             ("reverse", (p["b"], p["a"]))):
            before = p[side]["status"]
            if before == "modeled":
                transitions.append({"pair": f"{p['a']}–{p['b']}",
                                    "dir": f"{x}→{y}",
                                    "before": before, "after": "modeled",
                                    "edges": p[side]["edges"]})
                continue
            if (x, y) in derived_dirs:
                transitions.append({
                    "pair": f"{p['a']}–{p['b']}", "dir": f"{x}→{y}",
                    "before": before, "after": "derived-evidence",
                    "edges": derived_dirs[(x, y)],
                    "file": f"extracted/relinks/_logic/{x}__{y}.jsonl"})
                continue
            # ---- ledger with a concrete unblock ----
            res = residual.get((x, y))
            if y in schema_refs.get(x, set()):
                cls = "schema-empty"
                tok = (f"schema-declared 6:{y} column on {x} carries zero "
                       "populated cells at buildid 20318128 — recheck at "
                       "TargetBuildID 21238928 patch-diff")
                note = f"declared on {x} sheet, never populated in-line"
            elif res is not None:
                cls = "unadjudicated-name-hits"
                paths = "; ".join(f"{pth}×{c}" for pth, c in res["top"])
                tok = (f"{NAME_HITS}. dig-15 sweep: "
                       f"{res['total']} matches; top paths: {paths}; e.g. "
                       + (res["examples"][0] if res["examples"] else "n/a"))
                if res.get("ownIdOnly"):
                    note = ("own-id namespace coincidence only (verify-dig15b "
                            "m2): every hit is the row's own `id` value "
                            "colliding with a " + y + " id — not a payload "
                            "value; never edges")
                else:
                    note = ("exact-name sweep hits, unadjudicated "
                            "(never edges)")
            elif x in TERMINAL:
                cls, text = TERMINAL[x]
                tok = text
                note = f"inbound consumers of {x}: " + (
                    ", ".join(sorted(inbound.get(x, []))) or "none")
            else:
                cls = "no-carrier"
                tok = UNRELATED
                note = ""
            ledger.append({"a": p["a"], "b": p["b"], "dir": f"{x}→{y}",
                           "statusBefore": before, "action": "ledgered",
                           "unblockClass": cls, "unblock": tok,
                           "note": note})
            transitions.append({"pair": f"{p['a']}–{p['b']}",
                                "dir": f"{x}→{y}", "before": before,
                                "after": "ledgered:" + cls})
    return ledger, transitions


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8")
    kinds, metas = load_all()
    with open(MATRIX, encoding="utf-8") as f:
        matrix_json = json.load(f)

    deriver = Deriver(kinds, metas)
    deriver.run()
    deriver.pin_canonical(matrix_json)
    deriver.residual_sweep()

    written = emit_logic_files(deriver, dry=args.dry_run)
    derived_dirs = {(frm, to): n for frm, to, n in written}

    # dangling check — every from/to id exists in the draft datasets
    dangling = []
    total_edges = 0
    for (frm, to) in sorted(deriver.found.keys()):
        for e in deriver.found[(frm, to)]:
            total_edges += 1
            if e["fromId"] not in deriver.ids[frm]:
                dangling.append((frm, to, e["fromId"], "fromId"))
            if e["toId"] not in deriver.ids[to]:
                dangling.append((frm, to, e["toId"], "toId"))

    ledger, transitions = classify_directions(
        kinds, metas, matrix_json, derived_dirs, deriver.residual)

    os.makedirs(SCRATCH, exist_ok=True)
    if not args.dry_run:
        with open(os.path.join(LOGIC, "_ledger.jsonl"), "w",
                  encoding="utf-8", newline="\n") as f:
            for r in sorted(ledger, key=lambda r: (r["a"], r["b"], r["dir"])):
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        with open(os.path.join(SCRATCH, "transition_table.json"), "w",
                  encoding="utf-8", newline="\n") as f:
            json.dump({"dig": DIG, "buildId": BUILDID,
                       "totalsBefore": matrix_json["totals"],
                       "directions": sorted(
                           transitions,
                           key=lambda t: (t["pair"], t["dir"]))},
                      f, ensure_ascii=False, indent=1)

    # ---- report ----
    after_ct = collections.Counter(t["after"] for t in transitions)
    before_ct = collections.Counter(t["before"] for t in transitions)
    print(f"derived files: {len(written)}  edges: {total_edges}  "
          f"dangling: {len(dangling)}")
    for frm, to, n in sorted(written):
        print(f"  _logic/{frm}__{to}.jsonl  {n}")
    print(f"ledgered directions: {len(ledger)}")
    print("before:", dict(before_ct))
    print("after: ", dict(after_ct))
    # verify-dig15-a note (b): unpinned exact-name hits INSIDE derived
    # directions — by design neither edges nor ledger rows; reported so the
    # residue is counted, not silent.
    leftover = {d: r for d, r in deriver.residual.items()
                if d in derived_dirs}
    leftover_total = sum(r["total"] for r in leftover.values())
    top_left = sorted(leftover.items(), key=lambda kv: -kv[1]["total"])[:6]
    print(f"unpinned residual matches inside DERIVED directions: "
          f"{leftover_total} across {len(leftover)} dirs (cross-kind name "
          f"coincidences; never edges)")
    for d, r in top_left:
        print(f"  {d[0]}→{d[1]}  {r['total']}  "
              f"{[(p, c) for p, c in r['top'][:2]]}")
    own_id = [r["dir"] for r in ledger
              if r["unblockClass"] == "unadjudicated-name-hits"
              and r["note"].startswith("own-id")]
    print(f"name-hit directions resting ONLY on own-id collisions (m2): "
          f"{len(own_id)}")
    for d in dangling[:10]:
        print("DANGLING", d)
    return 0 if not dangling else 1


if __name__ == "__main__":
    sys.exit(main())
