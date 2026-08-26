#!/usr/bin/env python3
"""dig17_deferred_carriers.py — Data dig 17 (rider R6): outbound carrier
families for the DEFERRED kinds element/group/place/levelProps.

Emits extracted/relinks/_logic/<src>__<tgt>.jsonl family files ({fromId,
toId,mechanism,method,evidence} rows, `_meta` first line — dig-15 family
convention) for the outbound carrier mass the dig-15 fix round counted and
queued: 73 populated typed paths / 13,429 resolving refs toward managed
kinds, PLUS same-rule carriers toward sibling deferred kinds and
`constant`, PLUS the code-side hscript enum-reference families carried by
`element.script`.

Admission rule (dig-17 extension of the dig-15 family-admission rule —
deferred sources were clause-(4)-excluded there and are this dig's scope):
a payload path P on deferred kind X is admitted as an edge family onto
kind Y iff
  (1) data.cdb declares P — hidden sub-sheet chain recorded in X's
      `_meta.hiddenSubSheets` (shipped with dig 7) — with reference type
      `6:<sheet of Y>`; OR P is `X.script` text and the reference is
      `<Prefix>.<Name>` where <Prefix> is a runtime-registered CDB-enum
      namespace (script.Script f#12343 -> makeCdbEnum f#12329 over
      `Data.<sheet>.all[].id`);
  (2) >=1 populated value resolves exactly into Y's emitted id set
      (non-resolving values are recorded as `unresolvedRefs`, never
      dropped);
  (3) the carrier is positive — polarity-inverted conditions
      (`noHasTrait`, `noPersonalities`) are excluded with reasons;
  (4) Y has an emitted dataset (managed kinds, sibling deferred kinds
      element/group/place, or `constant`). Compound sub-sheet targets
      (`6:element@dialog`) are NOT admitted as kind-id edges — they are
      ledgered in `_ledger_deferred.jsonl` (intra-element dialog-block
      graph), never silently dropped.

Everything below the bar is written to
extracted/relinks/_logic/_ledger_deferred.jsonl with a concrete unblock.
Canonical bytes under extracted/relinks/*.jsonl and extracted/data/*.jsonl
stay read-only (evidence layer, pre-canonical promotion).

Deterministic: sorted iteration, fixed ordering, no wall clock.

  python pipeline/tools/dig17_deferred_carriers.py            # full pass
  python pipeline/tools/dig17_deferred_carriers.py --dry-run  # no writes
"""
import argparse
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wave_kinds  # noqa: E402

PACK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DRAFT = os.path.join(PACK, "extracted", "data", "_draft")
CONST = os.path.join(PACK, "extracted", "logic", "constants.jsonl")
LOGIC = os.path.join(PACK, "extracted", "relinks", "_logic")

BUILDID = "20318128"
DIG = "17"

SOURCES = ("element", "group", "place", "levelProps")
MANAGED = frozenset(wave_kinds.MANAGED_KINDS)
SHEET_KIND_EXTRA = {
    "element": "element", "group": "group", "place": "place",
    "constant": "constant",
}

# ------------------------------------------------------------------ table --
# Declarative carrier table: (source, dottedPayloadPath, targetKind, decl).
# `decl` is the declaring data.cdb hidden-sub-sheet column chain (as shipped
# in the source kind's _meta.hiddenSubSheets since dig 7). Trailing comments
# give this dig's census (resolving refs / populated), reproducible via
# output/_dig-deferred-carriers/census_typed_paths.py.
TYPED_CARRIERS = [
    # --- element ---------------------------------------------------------
    ("element", "props.activity", "activity",
     "data.cdb element@props@activity:6:activity"),                     # 48/48
    ("element", "dialog[].choices[].gains.attributePoint[].bonus",
     "attribute",
     "data.cdb element@dialog@choices@gains@attributePoint@bonus"
     ":6:attribute"),                                                   # 7/7
    ("element", "dialog[].choices[].gains.bonus[].inf", "bonus",
     "data.cdb element@dialog@choices@gains@bonus@inf:6:bonus"),      # 128/128
    ("element", "npc.unit", "class",
     "data.cdb element@npc@unit:6:unitClass"),                       # 1199/1199
    ("element", "dialog[].choices[].props.unit", "class",
     "data.cdb element@dialog@choices@props@unit:6:unitClass"),        # 16/16
    ("element", "dialog[].props.dlc", "constant",
     "data.cdb element@dialog@props@dlc:6:constant"),                   # 6/6
    ("element", "props.goals[].props.feature", "constant",
     "data.cdb element@props@goals@props@feature:6:constant"),          # 1/1
    ("element", "dialog[].props.gainsCounter[].counter", "counter",
     "data.cdb element@dialog@props@gainsCounter@counter:6:counter"),   # 7/7
    ("element", "dialog[].choices[].gains.fiefEvent[].event", "fiefEvent",
     "data.cdb element@dialog@choices@gains@fiefEvent@event"
     ":6:fiefEvent"),                                                 # 124/124
    ("element", "npc.type", "groupType",
     "data.cdb element@npc@type:6:groupType"),                        # 437/437
    ("element", "dialog[].choices[].verb", "icon",
     "data.cdb element@dialog@choices@verb:6:icon"),         # 3225/3226 (+1 unr.)
    ("element", "props.goals[].props.path", "icon",
     "data.cdb element@props@goals@props@path:6:icon"),                 # 4/4
    ("element", "items.content[].item", "item",
     "data.cdb element@items@content@item:6:item"),                  # 1770/1770
    ("element", "dialog[].props.gains[].item", "item",
     "data.cdb element@dialog@props@gains@item:6:item"),              # 620/620
    ("element", "dialog[].choices[].props.itemCost.item", "item",
     "data.cdb element@dialog@choices@props@itemCost@item:6:item"),   # 476/476
    ("element", "npc.equipment[].item", "item",
     "data.cdb element@npc@equipment@item:6:item"),                   # 463/463
    ("element", "dialog[].choices[].gains.item[].inf", "item",
     "data.cdb element@dialog@choices@gains@item@inf:6:item"),        # 264/264
    ("element", "items.unlockWith", "item",
     "data.cdb element@items@unlockWith:6:item"),                     # 104/104
    ("element", "dialog[].choices[].props.itemCostList[].item", "item",
     "data.cdb element@dialog@choices@props@itemCostList@item"
     ":6:item"),                                                       # 41/41
    ("element", "items.currency", "item",
     "data.cdb element@items@currency:6:item"),                         # 19/19
    ("element", "npc.leftHand", "item",
     "data.cdb element@npc@leftHand:6:item"),                           # 10/10
    ("element", "npc.recruitCost[].item", "item",
     "data.cdb element@npc@recruitCost@item:6:item"),                    # 3/3
    ("element", "dialog[].props.gainsBattle[].item", "item",
     "data.cdb element@dialog@props@gainsBattle@item:6:item"),           # 1/1
    ("element", "items.content[].loot", "loot",
     "data.cdb element@items@content@loot:6:loot"),                   # 369/369
    ("element", "dialog[].props.gainsLoot", "loot",
     "data.cdb element@dialog@props@gainsLoot:6:loot"),               # 300/300
    ("element", "props.fief.forcedPlace", "place",
     "data.cdb element@props@fief@forcedPlace:6:place"),                 # 4/4
    ("element", "props.refCity", "place",
     "data.cdb element@props@refCity:6:place"),                          # 1/1
    ("element", "npc.region", "region",
     "data.cdb element@npc@region:6:region"),                         # 516/516
    ("element", "npc.recruitRegions[].region", "region",
     "data.cdb element@npc@recruitRegions@region:6:region"),             # 58/58
    ("element", "npc.skills[].skill", "skill",
     "data.cdb element@npc@skills@skill:6:skill"),                    # 317/317
    ("element", "dialog[].choices[].gains.skill", "skill",
     "data.cdb element@dialog@choices@gains@skill:6:skill"),             # 13/13
    ("element", "dialog[].props.playSound", "sound",
     "data.cdb element@dialog@props@playSound:6:sound"),                 # 56/56
    ("element", "dialog[].choices[].props.sfx", "sound",
     "data.cdb element@dialog@choices@props@sfx:6:sound"),               # 20/20
    ("element", "dialog[].choices[].gains.status[].inf", "status",
     "data.cdb element@dialog@choices@gains@status@inf:6:status"),       # 72/72
    ("element", "dialog[].choices[].gains.injury[].inf", "status",
     "data.cdb element@dialog@choices@gains@injury@inf:6:status"),        # 7/7
    ("element", "npc.status[].status", "status",
     "data.cdb element@npc@status@status:6:status"),                      # 2/2
    ("element", "dialog[].props.personality", "trait",
     "data.cdb element@dialog@props@personality:6:trait"),             # 236/236
    ("element", "dialog[].choices[].props.personality", "trait",
     "data.cdb element@dialog@choices@props@personality:6:trait"),     # 214/214
    ("element", "dialog[].choices[].gains.trait[].inf", "trait",
     "data.cdb element@dialog@choices@gains@trait@inf:6:trait"),         # 27/27
    ("element", "npc.trait", "trait",
     "data.cdb element@npc@trait:6:trait"),                              # 10/10
    ("element", "props.traitRequire.trait", "trait",
     "data.cdb element@props@traitRequire@trait:6:trait"),                # 5/5
    ("element", "npc.traits[].trait", "trait",
     "data.cdb element@npc@traits@trait:6:trait"),                        # 2/2
    ("element", "npc.pattern", "unitPattern",
     "data.cdb element@npc@pattern:6:unitPattern"),                      # 24/24
    # element -> element (sibling/self deferred-kind targets, same rule)
    ("element", "npc.reference", "element",
     "data.cdb element@npc@reference:6:element"),                     # 816/816
    ("element", "dialog[].props.who", "element",
     "data.cdb element@dialog@props@who:6:element"),                  # 718/718
    ("element", "dialog[].props.voiceWho[].element", "element",
     "data.cdb element@dialog@props@voiceWho@element:6:element"),        # 64/64
    ("element", "props.copyScriptFrom", "element",
     "data.cdb element@props@copyScriptFrom:6:element"),                 # 43/43
    ("element", "props.copyDialogFrom", "element",
     "data.cdb element@props@copyDialogFrom:6:element"),                 # 34/34
    ("element", "props.second", "element",
     "data.cdb element@props@second:6:element"),                         # 17/17
    ("element", "npc.genTalkOverride", "element",
     "data.cdb element@npc@genTalkOverride:6:element"),                  # 12/12
    # --- group -----------------------------------------------------------
    ("group", "battleRules.battle", "battle",
     "data.cdb group@battleRules@battle:6:battle"),                      # 41/41
    ("group", "units.classes[].c", "class",
     "data.cdb group@units@classes@c:6:unitClass"),                      # 43/43
    ("group", "props.seaLord.stats[].counter", "counter",
     "data.cdb group@props@seaLord@stats@counter:6:counter"),            # 40/40
    ("group", "props.type", "groupType",
     "data.cdb group@props@type:6:groupType"),                        # 791/791
    ("group", "props.extraLoot[].item", "item",
     "data.cdb group@props@extraLoot@item:6:item"),                      # 66/66
    ("group", "props.seaLord.treasureMap", "item",
     "data.cdb group@props@seaLord@treasureMap:6:item"),                 # 10/10
    ("group", "props.dialogGroup", "group",
     "data.cdb group@props@dialogGroup:6:group"),                       # 100/100
    ("group", "props.seaLord.fakeFor", "group",
     "data.cdb group@props@seaLord@fakeFor:6:group"),                     # 1/1
    ("group", "props.cancelCost.items", "loot",
     "data.cdb group@props@cancelCost@items:6:loot"),                   # 120/120
    ("group", "props.hideout", "place",
     "data.cdb group@props@hideout:6:place"),                            # 30/30
    ("group", "props.linkedPlace", "place",
     "data.cdb group@props@linkedPlace:6:place"),                         # 7/7
    ("group", "props.timeBehaviour[].goToPlace", "place",
     "data.cdb group@props@timeBehaviour@goToPlace:6:place"),             # 1/1
    ("group", "props.regions[].region", "region",
     "data.cdb group@props@regions@region:6:region"),                    # 46/46
    ("group", "props.weeklyBounties.region", "region",
     "data.cdb group@props@weeklyBounties@region:6:region"),             # 19/19
    ("group", "props.dialogMood", "sound",
     "data.cdb group@props@dialogMood:6:sound"),                         # 15/15
    ("group", "props.soundWorld", "sound",
     "data.cdb group@props@soundWorld:6:sound"),                          # 5/5
    ("group", "battleRules.renforts[].unitPattern", "unitPattern",
     "data.cdb group@battleRules@renforts@unitPattern:6:unitPattern"),   # 14/14
    ("group", "units.pattern", "unitPattern",
     "data.cdb group@units@pattern:6:unitPattern"),                      # 13/13
    ("group", "battleRules.neutrals.unitPattern", "unitPattern",
     "data.cdb group@battleRules@neutrals@unitPattern:6:unitPattern"),    # 1/1
    # --- place -----------------------------------------------------------
    ("place", "props.warEffort.rewards[].bonus", "bonus",
     "data.cdb place@props@warEffort@rewards@bonus:6:bonus"),            # 46/46
    ("place", "props.fiefData", "fiefPlace",
     "data.cdb place@props@fiefData:6:fiefPlace"),                       # 19/19
    ("place", "world.kind", "icon",
     "data.cdb place@world@kind:6:icon"),                              # 443/443
    ("place", "world.cityKind", "icon",
     "data.cdb place@world@cityKind:6:icon"),                            # 39/39
    ("place", "world.codices[].codex", "item",
     "data.cdb place@world@codices@codex:6:item"),                       # 27/27
    ("place", "props.produces[].item", "item",
     "data.cdb place@props@produces@item:6:item"),                       # 24/24
    ("place", "props.rivalTavern.drinkRecipe", "item",
     "data.cdb place@props@rivalTavern@drinkRecipe:6:item"),             # 10/10
    ("place", "props.rivalTavern.foodRecipe", "item",
     "data.cdb place@props@rivalTavern@foodRecipe:6:item"),              # 10/10
    ("place", "props.highSellValueItems", "itemType",
     "data.cdb place@props@highSellValueItems:6:itemType"),               # 1/1
    ("place", "props.samePosAs", "place",
     "data.cdb place@props@samePosAs:6:place"),                           # 4/4
    ("place", "props.enterInPlace", "place",
     "data.cdb place@props@enterInPlace:6:place"),                        # 2/2
    ("place", "props.arena.rules[].kind", "skill",
     "data.cdb place@props@arena@rules@kind:6:skill"),                   # 36/36
    ("place", "props.warEffort.rewardSkill", "skill",
     "data.cdb place@props@warEffort@rewardSkill:6:skill"),               # 7/7
    ("place", "world.soundWorld", "sound",
     "data.cdb place@world@soundWorld:6:sound"),                         # 46/46
    ("place", "world.mood", "sound",
     "data.cdb place@world@mood:6:sound"),                               # 13/13
    # --- levelProps ------------------------------------------------------
    ("levelProps", "props.spawnData.spawnKind", "class",
     "data.cdb levelProps@props@spawnData@spawnKind:6:unitClass"),       # 19/19
    ("levelProps", "props.roamings[].variants[].ref", "group",
     "data.cdb levelProps@props@roamings@variants@ref:6:group"),        # 147/147
    ("levelProps", "props.action", "icon",
     "data.cdb levelProps@props@action:6:icon"),                          # 2/2
    ("levelProps", "props.refItem", "item",
     "data.cdb levelProps@props@refItem:6:item"),                        # 13/13
    ("levelProps", "props.linkedPlaces[].kind", "place",
     "data.cdb levelProps@props@linkedPlaces@kind:6:place"),             # 94/94
    ("levelProps", "props.skill", "skill",
     "data.cdb levelProps@props@skill:6:skill"),                        # 203/203
]

NEGATED_CARRIER_PATHS = (
    # rule (3) exclusions — polarity-inverted conditions on element dialogs;
    # same evidence bar, inverted reading, documented not dropped.
    # (path, targetKind, resolvingRefs, reason)
    ("dialog[].props.noHasTrait", "trait", 24,
     "negated condition: block shows only when the speaker LACKS the trait"),
    ("dialog[].choices[].props.noHasTrait", "trait", 3,
     "negated condition: choice visible only when the player LACKS the "
     "trait"),
    ("dialog[].choices[].props.noPersonalities[].id", "trait", 6,
     "negated condition: choice hidden for holders of the trait (mirrors "
     "the confessions noPersonalities carrier excluded at dig 15)"),
)

# Code-side carriers: runtime-registered CDB-enum namespaces consumed by
# element scripts (scripts exist on element rows only). Mechanism proven at
# extracted/decompiled/hl-src/src/script/Script.hx.hx f#12343
# (src/script/Script.hx:59): GLOBALS[<name>] = makeCdbEnum(ids of
# Data.<sheet>.all) (makeCdbEnum f#12329 :173). Comments are stripped before
# scanning (measured effect: schema prose like
# 'Group.props.seaLords.treasureMap' inside a B1SeaLord01Leader comment is
# NOT a reference and stays out).
SCRIPT_ENUM_PREFIX = {
    "Activity": "activity", "Attribute": "attribute", "Bonus": "bonus",
    "Constant": "constant", "Counter": "counter", "Element": "element",
    "FiefEvent": "fiefEvent", "FiefGoal": "fiefGoal",
    "GroupType": "groupType", "Icon": "icon", "Item": "item",
    "ItemType": "itemType", "Kingdom": "kingdom", "Notify": "notify",
    "Place": "place", "Region": "region", "Skill": "skill",
    "Sound": "sound", "Status": "status", "Trait": "trait",
    "Tutorial": "tutorial", "UnitClass": "class",
}
SCRIPT_RE = re.compile(
    r"\b(" + "|".join(sorted(SCRIPT_ENUM_PREFIX)) + r")\.([A-Za-z_][A-Za-z0-9_]*)")
COMMENT_RE = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)


def read_jsonl(path):
    with open(path, "r", encoding="utf-8") as f:
        head = json.loads(f.readline())
        return head.get("_meta", {}), [json.loads(l) for l in f]


def load_universe():
    kinds, metas = {}, {}
    for fn in sorted(os.listdir(DRAFT)):
        if fn.endswith(".jsonl"):
            k = fn[:-6]
            metas[k], kinds[k] = read_jsonl(os.path.join(DRAFT, fn))
    metas["constant"], kinds["constant"] = read_jsonl(CONST)
    return kinds, metas


def rid_of(row):
    return row["id"] if "id" in row else row.get("_id")


def payload_only(row):
    return {k: v for k, v in row.items()
            if k not in ("_carrier", "_path", "_variant")}


def leaf_containers(o, dotted):
    """Containers sitting at the parent of the dotted leaf ([] = list
    descent, mirroring CDB list semantics)."""
    parents = dotted.split(".")[:-1]

    def rec(obj, pp):
        if not pp:
            if isinstance(obj, dict):
                yield obj
            return
        h, rr = pp[0], pp[1:]
        if h.endswith("[]"):
            k = h[:-2]
            if isinstance(obj, dict) and isinstance(obj.get(k), list):
                for v in obj[k]:
                    yield from rec(v, rr)
        else:
            if isinstance(obj, dict) and isinstance(obj.get(h), dict):
                yield from rec(obj[h], rr)

    yield from rec(o, parents)


def norm(p):
    return re.sub(r"\[\d+\]", "[]", p)


def walk_strings(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "textKey":
                continue
            yield from walk_strings(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_strings(v, f"{path}[]")
    elif isinstance(obj, str):
        yield norm(path), obj


# ------------------------------------------------------------ hl citations --
HL_CORROBORATION = {
    "element__class":
        "ent/p/Npc.hx.hx:249 reads `unit = npc.unit` (identity gate vs "
        "Npc.getUnit); :4855 npc.equipment; :5058 npc.leftHand; "
        ":2309-2327 itemCost/itemCostList",
    "element__groupType":
        "ent/p/Npc.hx.hx:4475 reads npc.type",
    "element__region":
        "st/Unit.hx.hx:27252 reads npc.region and :27286-27299 "
        "npc.recruitRegions for spawn-region resolution",
    "element__item":
        "ent/CrimeCave.hx.hx:560 + ent/p/ActivityGather.hx.hx:124 consume "
        "items[].content; ent/p/Element.hx.hx:2469-2474 currency; "
        "ent/p/Chest.hx.hx:85/292 unlockWith",
    "element__icon":
        "ent/p/Npc.hx.hx:1365-1431 assigns dialog choice verb icons",
    "element__loot":
        "st/player/Confession.hx.hx:7263 reads dialog gainsLoot",
    "element__sound":
        "ent/p/SignElement.hx.hx:552 reads dialog playSound",
    "element__trait":
        "ent/p/GarnisonManager.hx.hx:1726 reads props.traitRequire; "
        "personality gates consumed by the dialog engine "
        "(ui/win/Dialog.hx.hx)",
    "element__unitPattern":
        "st/Group.hx.hx:3268 reads .pattern; battle/BattleMode.hx.hx:530",
    "element__element":
        "ent/p/Element.hx.hx:3439 copyScriptFrom and :3412 copyDialogFrom "
        "(also ui/win/Dialog.hx.hx:5990); ent/p/Npc.hx.hx:1498 "
        "genTalkOverride; st/player/Confession.hx.hx:7341 voiceWho",
    "element__constant":
        "st/player/Confession.hx.hx:7227 reads dialog dlc gating",
    "element__activity":
        "ent/p/Element.hx.hx:92 reads .activity",
    "element__fiefEvent":
        "dialog gains.fiefEvent events feed the fief event queue "
        "(st/player/fief/FiefEventManager.hx.hx)",
    "element__counter":
        "ent/p/Element.hx.hx:4798 reads gainsCounter; "
        "st/player/Confession.hx.hx:7251 same field on the confession "
        "side of the shared choice-gains machinery",
    "element__attribute":
        "st/player/Confession.hx.hx:381 attributePoint gain machinery "
        "(shared with element dialogs)",
    "element__skill":
        "ent/p/Npc.hx.hx:5017 reads npc.skills",
    "element__status":
        "ent/p/Npc.hx.hx:5067 reads npc.status",
    "element__bonus":
        "ui/win/Dialog.hx.hx:1403 reads gains.bonus; "
        "st/player/tavern/TavernEvent.hx.hx:686 same reader on tavern "
        "events",
    "group__loot":
        "ui/win/Dialog.hx.hx:6608 Dialog.cancelCost + "
        "ent/roaming/GhostPack.hx.hx:1658 and ui/win/GroupFight.hx.hx:88 "
        "read group cancelCost.items",
    "group__counter":
        "st/player/SeaLords.hx.hx reputation counters under seaLord.stats",
    "group__battle":
        "ent/p/Element.hx.hx:3277 reads battleRules (group battle wiring)",
    "place__skill":
        "ent/Arena.hx.hx:532 reads props.arena (rules[].kind inside); "
        "warEffort at st/player/E2Conquest.hx.hx:15-24",
    "levelProps__group":
        "st/player/SystemicDirector.hx.hx:1321/1586 reads roamings + "
        "variants for roaming spawners",
    "levelProps__item":
        "refItem readers: st/item/Tool.hx.hx:2897, "
        "st/player/GlobalInventory.hx.hx:3929, "
        "st/player/SeaFishing.hx.hx:2399",
    "levelProps__icon":
        "ent/ForsakenVillage.hx.hx:1081 reads node .action",
    "group__groupType":
        "st/Group.hx.hx:3274 reads group props.type",
    "group__place":
        "ent/Roaming.hx.hx:8103/8146/8208 read group hideout; "
        "ent/roaming/SystemicRoaming.hx.hx:169 period goToPlace",
    "group__unitPattern":
        "battle/Battle.hx.hx:4370-4414 consumes renforts unit patterns",
    "group__item":
        "st/Group.hx.hx:1840 extraLoot; st/player/SeaLords.hx.hx:1229 "
        "seaLord treasureMap",
    "group__sound":
        "ent/Roaming.hx.hx:1812 reads soundWorld; "
        "world/DialogOutView.hx.hx:1598 dialogMood",
    "group__region":
        "ui/win/MissionBoard.hx.hx:7804 reads weeklyBounties regions",
    "group__class":
        "st/Group.hx.hx:597/2515 iterate units.classes",
    "group__group":
        "st/player/SeaLords.hx.hx:666 reads seaLord fakeFor; dialogGroup "
        "consumed by the roaming dialog engine",
    "place__icon":
        "ent/Place.hx.hx:120 cityKind icon resolution (world.kind same "
        "reader family)",
    "place__sound":
        "ent/Place.hx.hx:373-380 initSound reads world.soundWorld/mood",
    "place__item":
        "ent/Place.hx.hx:1881 produces and :2281 codices; "
        "st/player/tavern/TavernSimulation.hx.hx:4606 rivalTavern recipes",
    "place__itemType":
        "st/Item.hx.hx:3950 reads highSellValueItems (trade pricing)",
    "place__place":
        "ui/win/MiniMap.hx.hx:13352 reads samePosAs; ent/Place.hx.hx:4222 "
        "enterInPlace",
    "place__fiefPlace":
        "ent/p/GarnisonManager.hx.hx:87 reads props.fiefData",
    "place__bonus":
        "st/player/E2Conquest.hx.hx:15-24 reads warEffort (rewards[].bonus "
        "inside)",
    "levelProps__class":
        "battle/Gen.hx.hx:8729 reads spawnData.spawnKind (battle spawner)",
    "levelProps__skill":
        "battle/Battle.hx.hx:4715 iterEnvSkillPolygons consumes EnvSkill "
        "nodes' props.skill",
    "levelProps__place":
        "ent/roaming/Caravan.hx.hx:802 + ent/roaming/Convoy.hx.hx:39 read "
        "props.linkedPlaces[].kind",
    "_script":
        "extracted/decompiled/hl-src/src/script/Script.hx.hx f#12343 "
        "(src/script/Script.hx:59) registers the CDB-enum namespaces "
        "scripts read: GLOBALS[name] = makeCdbEnum(Data.<sheet>.all[].id) "
        "(makeCdbEnum f#12329 :173) for Status/UnitClass/Attribute/Skill/"
        "Item/ItemType/Icon/GroupType/Trait/Counter/Activity/Bonus/Region/"
        "Constant/Sound/Notify/FiefGoal/FiefEvent/FiefPlace/Tutorial/"
        "Kingdom literally; Element./Place. bind through the same runtime "
        "family (scripts run via script.Script.initScriptElement :1696, "
        "PlaceApi/ElementApi). Sampled occurrences read as id arguments: "
        "startActivity(Activity.Archery), "
        "getPlace(Place.A1CryptAdmiralStart), "
        "getPlaceElement(Place.G1TreasureFishery, "
        "Element.G1TreasureFisheryChest), addStatus(Status.Sting), "
        "addTrait(Trait.EnemyBurned), sfx(Sound.Places_A1Ruins_RockGrowl), "
        "hasFeature(Constant.Belerion), counter(Counter.AlazarTruthEye), "
        "deliverPrisoner({types:[GroupType.Outlaws]}), "
        "addEvent(UnitClass.TheBeast, Skill.BeastRoar)",
}


class Emitter:
    def __init__(self, kinds, metas):
        self.kinds = kinds
        self.metas = metas
        self.ids = {}
        self.dup = {}
        for k, rows in kinds.items():
            c = collections.Counter(rid_of(r) for r in rows)
            self.ids[k] = set(c)
            self.dup[k] = {i: n for i, n in c.items() if n > 1}
        self.found = collections.defaultdict(list)   # (src,tgt) -> edges
        # channel-split counters: (src,tgt,"payload"|"hscript")
        self.stats = collections.defaultdict(
            lambda: {"refsSeen": 0, "resolved": 0, "emitted": 0,
                     "paths": [], "unresolved": [], "prefixes": set()})
        self.seen = collections.defaultdict(set)  # ((src,tgt),chan)->pairs
        self.decls = collections.defaultdict(set)
        self.tags = collections.defaultdict(set)
        self.script_refs_in_comments = 0
        # authored-empty ids: scene-local anonymous rows cannot join
        self.anonymous_skipped = collections.Counter()  # kind -> rows
        self.anonymous_refs = collections.Counter()     # kind -> refs

    def add(self, key, frm, to, mech, meth, ev):
        lst = self.found[key]
        for e in lst:
            if e["fromId"] == frm and e["toId"] == to:
                if len(e["_paths"]) < 3 and ev not in e["_paths"]:
                    e["_paths"].append(ev)
                return False
        lst.append({"fromId": frm, "toId": to, "mechanism": mech,
                    "method": meth, "evidence": ev, "_paths": [ev]})
        return True

    def scan_typed(self, src, dotted, tgt, decl):
        st = self.stats[(src, tgt, "payload")]
        st["paths"].append(dotted)
        self.decls[(src, tgt)].add(decl)
        self.tags[(src, tgt)].add("typed-hidden-sub-sheet")
        tids = self.ids[tgt]
        leaf = dotted.split(".")[-1]
        for row in self.kinds[src]:
            rid = rid_of(row)
            if not rid:
                vals0 = [1 for cont in leaf_containers(payload_only(row),
                                                       dotted)
                         if isinstance(cont.get(leaf), str)]
                if vals0:
                    self.anonymous_skipped[src] += 1
                    self.anonymous_refs[src] += len(vals0)
                continue
            vals = []
            for cont in leaf_containers(payload_only(row), dotted):
                v = cont.get(leaf)
                if isinstance(v, str):
                    vals.append(v)
            if not vals:
                continue
            st["refsSeen"] += len(vals)
            st["resolved"] += sum(1 for v in vals if v in tids)
            rid = rid_of(row)
            for v in vals:
                if v in tids:
                    ev = (f"extracted/data/_draft/{src}.jsonl#{rid}:"
                          f"{dotted}='{v}'")
                    if (rid, v) not in self.seen[((src, tgt), "payload")]:
                        self.seen[((src, tgt), "payload")].add((rid, v))
                        st["emitted"] += 1
                    self.add((src, tgt), rid, v, "inferred",
                             "cdb-payload-id-join", ev)
                elif v not in st["unresolved"]:
                    st["unresolved"].append(v)

    def scan_script_enums(self):
        for src in SOURCES:
            colnames = {c["name"] for c in self.metas[src].get("columns", [])}
            if "script" not in colnames:
                continue
            for row in self.kinds[src]:
                s = row.get("script")
                if not isinstance(s, str) or not s:
                    continue
                if not rid_of(row):
                    continue
                # comment spans are computed on the RAW text so evidence
                # offsets stay verifiable against the dataset bytes
                spans = [(m.start(), m.end())
                         for m in COMMENT_RE.finditer(s)]
                in_comment = lambda i: any(a <= i < b for a, b in spans)
                raw_hits = len(SCRIPT_RE.findall(s))
                kept = 0
                rid = rid_of(row)
                for m in SCRIPT_RE.finditer(s):
                    if in_comment(m.start()):
                        continue
                    kept += 1
                    pre, name = m.group(1), m.group(2)
                    tgt = SCRIPT_ENUM_PREFIX[pre]
                    st = self.stats[(src, tgt, "hscript")]
                    st["refsSeen"] += 1
                    st["prefixes"].add(pre)
                    if name in self.ids[tgt]:
                        st["resolved"] += 1
                        ev = (f"extracted/data/_draft/{src}.jsonl#{rid}"
                              f".script@{m.start()} '{pre}.{name}'")
                        if (rid, name) not in self.seen[
                                ((src, tgt), "hscript")]:
                            self.seen[((src, tgt), "hscript")].add((rid, name))
                            st["emitted"] += 1
                        self.add((src, tgt), rid, name, "logic",
                                 f"hscript-enum-ref:{pre}", ev)
                    elif name not in st["unresolved"]:
                        st["unresolved"].append(name)
                self.script_refs_in_comments += raw_hits - kept

    def run(self):
        for src, dotted, tgt, decl in TYPED_CARRIERS:
            assert src in SOURCES, (src, dotted)
            assert tgt in self.ids, (src, dotted, tgt)
            self.scan_typed(src, dotted, tgt, decl)
        self.scan_script_enums()

    # ---------------- unpinned residual sweep (ledger input, never edges) --
    def residual_sweep(self):
        pinned = {s: set() for s in SOURCES}
        for src, dotted, _tgt, _decl in TYPED_CARRIERS:
            pinned[src].add(dotted)
        for p, _t, _n, _r in NEGATED_CARRIER_PATHS:
            pinned["element"].add(p)
        hits = collections.defaultdict(
            lambda: collections.defaultdict(collections.Counter))
        examples = {}
        own_id = collections.defaultdict(
            lambda: collections.defaultdict(int))
        for src in SOURCES:
            for row in self.kinds[src]:
                rid = rid_of(row)
                for p, v in walk_strings(payload_only(row)):
                    if p in pinned[src]:
                        continue
                    for tgt in sorted(self.ids.keys()):
                        if tgt == src or tgt == "levelProps":
                            continue
                        if v in self.ids[tgt]:
                            hits[src][tgt][p] += 1
                            examples.setdefault((src, tgt, p),
                                                f"{rid}:{p}={v!r}")
                            if p == "id":
                                own_id[src][tgt] += 1
        return hits, examples, own_id

    def declared_not_admitted(self):
        """Every declared 6:-typed column on the four sources that the
        emitter did NOT admit, classified (negated / compound-populated /
        compound-empty / schema-empty), each counted."""
        admitted = {(s, d) for s, d, _t, _decl in TYPED_CARRIERS}
        negated = {p for p, _t, _n, _r in NEGATED_CARRIER_PATHS}
        out = []
        for src in SOURCES:
            hs = self.metas[src].get("hiddenSubSheets", {})
            cols_root = {c["name"]: c for c in
                         self.metas[src].get("columns", [])}
            for key in sorted(hs):
                segs = key.split("@")
                parts, cur, prefix = [], cols_root, []
                ok = True
                for seg in segs:
                    col = cur.get(seg) if cur else None
                    if col is None:
                        ok = False
                        break
                    parts.append(seg +
                                 ("[]" if str(col.get("typeStr")) == "8"
                                  else ""))
                    prefix.append(seg)
                    sheet = "@".join(prefix)
                    cur = ({c["name"]: c for c in hs[sheet]}
                           if sheet in hs else None)
                if not ok:
                    continue
                for c in hs[key]:
                    ts = str(c.get("typeStr", ""))
                    if not ts.startswith("6:"):
                        continue
                    name = c["name"]
                    path = ".".join(parts + [name])
                    if (src, path) in admitted:
                        continue
                    tgt_sheet = ts[2:]
                    compound = "@" in tgt_sheet
                    pop = 0
                    leaf = name
                    for row in self.kinds[src]:
                        for cont in leaf_containers(payload_only(row),
                                                    path):
                            if isinstance(cont.get(leaf), str):
                                pop += 1
                    if path in negated:
                        cls = "negated-polarity"
                    elif compound and pop:
                        cls = "compound-populated"
                    elif compound:
                        cls = "compound-empty"
                    else:
                        cls = "schema-empty"
                    out.append({"source": src, "path": path,
                                "declChain": f"data.cdb {key}@{name}",
                                "targetSheet": tgt_sheet,
                                "populated": pop, "class": cls})
        return out


# ----------------------------------------------------------------- output --


def emit_files(em, dry=False):
    written = []
    for key in sorted(em.found.keys()):
        src, tgt = key
        edges = sorted(em.found[key],
                       key=lambda e: (str(e["fromId"]), str(e["toId"])))
        fam_stats = []
        sp = em.stats.get((src, tgt, "payload"))
        sh = em.stats.get((src, tgt, "hscript"))
        if sp and sp["refsSeen"]:
            fam_stats.append({
                "family": "cdb-payload-id-join",
                "carrierPaths": sorted(sp["paths"]),
                "refsSeen": sp["refsSeen"],
                "resolved": sp["resolved"],
                "emittedPairs": sp["emitted"],
                "unresolvedRefs": sorted(sp["unresolved"])[:24],
                "unresolvedRefCount": len(sp["unresolved"]),
                "ambiguous": [],
            })
        if sh and sh["refsSeen"]:
            fam_stats.append({
                "family": "hscript-enum-ref",
                "namespaces": sorted(sh["prefixes"]),
                "refsSeen": sh["refsSeen"],
                "resolved": sh["resolved"],
                "emittedPairs": sh["emitted"],
                "unresolvedRefs": sorted(sh["unresolved"])[:24],
                "unresolvedRefCount": len(sh["unresolved"]),
                "note": ("occurrence refs dedupe to (element,target) "
                         "pairs; emittedPairs counts pairs first "
                         "contributed by this family; evidence cites the "
                         "first script-text offset; comments stripped "
                         "before scanning"),
            })
        methods = sorted({e["method"].split(":")[0] for e in edges})
        promotes = ("hard" if methods == ["cdb-payload-id-join"]
                    else "mixed (code-side families promote as logic)")
        meta = {
            "dig": DIG,
            "buildId": BUILDID,
            "layer": "evidence (pre-canonical)",
            "fromKind": src,
            "toKind": tgt,
            "sourceClass": "deferred-kind (spec-stages-datasets §3.5)",
            "rowCount": len(edges),
            "methods": methods,
            "promotionExpectation": promotes,
            "families": fam_stats,
            "hlCorroboration": (
                HL_CORROBORATION.get(f"{src}__{tgt}")
                or (HL_CORROBORATION["_script"]
                    if sh and sh["refsSeen"] else None)),
            "admission": (
                "family-admission rule (dig-17 extension of the dig-15 "
                "rule whose clause (4) excluded deferred sources): "
                "data.cdb declares the path (hidden sub-sheet chain, "
                "reference type 6:<target>) OR the reference is a "
                "runtime-registered CDB-enum namespace in element.script; "
                ">=1 populated value resolves into the target id set; "
                "positive polarity; target has an emitted dataset "
                "(managed kinds, sibling deferred kinds element/group/"
                "place, constant). Compound sub-sheet targets "
                "(6:element@dialog) and negated-condition carriers are "
                "ledgered in _ledger_deferred.jsonl instead"),
            "admissionTags": sorted(em.tags.get((src, tgt), set())),
            "cdbDeclarations": sorted(em.decls.get((src, tgt), set())),
            "fromIdUniquenessNote": (
                f"duplicate ids in {src}.jsonl (scene-local variants kept "
                f"by dig 7): {len(em.dup.get(src) or {})} ids sit on "
                "multiple rows; pairs dedupe by (fromId,toId)"
                if em.dup.get(src) else None),
            "recheck": (
                "re-run pipeline/tools/dig17_deferred_carriers.py over the "
                "same draft bytes; every edge re-derives from its evidence "
                "path"),
        }
        meta = {"_meta": {k: v for k, v in meta.items() if v is not None}}
        lines = [json.dumps(meta, ensure_ascii=False)]
        for e in edges:
            lines.append(json.dumps(
                {k: e[k] for k in ("fromId", "toId", "mechanism", "method",
                                   "evidence")},
                ensure_ascii=False))
        path = os.path.join(LOGIC, f"{src}__{tgt}.jsonl")
        if not dry:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(lines) + "\n")
        written.append((src, tgt, len(edges)))
    return written


LEDGER_HEADER_NOTE = (
    "dig-17 deferred-kind outbound ledger — everything BELOW the "
    "family-admission bar for the element/group/place/levelProps source "
    "mass, with concrete unblocks. Companion to the dig-15 _ledger.jsonl "
    "(the managed ordered-pair matrix, regenerated by dig15_logic_edges."
    "py); THIS file is regenerated by dig17_deferred_carriers.py. Nothing "
    "below the bar is silent.")


def emit_ledger(em, non_admitted, hits, examples, own_id, dry=False):
    rows = [{"_meta": {"dig": DIG, "buildId": BUILDID,
                       "note": LEDGER_HEADER_NOTE}}]
    # 1. negated-polarity carriers
    neg_total = sum(n for _p, _t, n, _r in NEGATED_CARRIER_PATHS)
    neg_detail = [e for e in non_admitted if e["class"] == "negated-polarity"]
    rows.append({
        "a": "element", "b": "trait", "dir": "element→trait",
        "action": "ledgered", "unblockClass": "negated-polarity",
        "unblock": (
            "; ".join(f"{p} ×{n} ({r})" for p, _t, n, r in
                      NEGATED_CARRIER_PATHS) +
            ". Typed 6:trait carriers excluded by admission clause (3): "
            "inverted polarity — absence conditions, not relations. "
            "Measured populations agree with the census (" +
            "; ".join(f"{e['path']}={e['populated']}" for e in neg_detail) +
            "). Unblock: emit with an inverted flag field when a consumer "
            "renders negative gates; recheck at TargetBuildID 21238928 "
            "patch-diff"),
        "note": f"{neg_total} resolving refs, never edges"})
    # 2. compound dialog-node graph (intra-element block references)
    tgt_cnt = miss = copy_dialog = 0
    for row in em.kinds["element"]:
        d = row.get("dialog")
        if not isinstance(d, list):
            continue
        blocks = {b.get("id") for b in d if isinstance(b, dict)}
        for b in d:
            if not isinstance(b, dict):
                continue
            if isinstance((b.get("props") or {}).get("copyDialog"), str):
                copy_dialog += 1
            for ch in b.get("choices") or []:
                if isinstance(ch, dict) and "target" in ch:
                    tgt_cnt += 1
                    if ch["target"] not in blocks:
                        miss += 1
    comp_pop = [e for e in non_admitted if e["class"] == "compound-populated"]
    comp_empty = [e for e in non_admitted if e["class"] == "compound-empty"]
    rows.append({
        "a": "element", "b": "element(dialog)", "dir": "element→element@dialog",
        "action": "ledgered", "unblockClass": "compound-dialog-node",
        "unblock": (
            "dialog[].choices[].target (declared 6:element@dialog) holds "
            f"{tgt_cnt} references resolving INTO THE OWNING ROW'S dialog "
            f"block ids (measured misses: {miss}) — nodes are "
            "(element, blockId) pairs, not entity ids, so they cannot be "
            "(fromId,toId) kind-id edges; plus dialog[].props.copyDialog "
            f"×{copy_dialog}. Declared compound columns measured: " +
            "; ".join(f"{e['source']}:{e['path']} pop={e['populated']}"
                      for e in comp_pop + comp_empty) +
            ". Unblock: emit a per-element dialog adjacency dataset "
            "(block id, text refs, choices[verb,target]) when the "
            "interrogation DB piece lands — the R6 deadline surface; the "
            "schema already ships in element._meta.hiddenSubSheets"),
        "note": "complete intra-element dialogue graph, honestly shaped"})
    # 3. declared-but-empty typed columns
    man_empty = [e for e in non_admitted if e["class"] == "schema-empty"]
    rows.append({
        "a": "element/group/place/levelProps", "b": "(managed targets)",
        "dir": "deferred→managed", "action": "ledgered",
        "unblockClass": "schema-empty",
        "unblock": (
            f"{len(man_empty)} declared 6:-typed columns (managed OR "
            "deferred targets) carry ZERO populated cells at buildid "
            f"{BUILDID}: " +
            "; ".join(f"{e['source']}:{e['path']} ({e['declChain']})"
                      for e in man_empty) +
            " — recheck at TargetBuildID 21238928 patch-diff"),
        "note": "declared, never populated"})
    # 4. unpinned exact-name residual (prefab-carried untyped strings)
    tot_all = sum(sum(c.values()) for s in hits.values() for c in s.values())
    tot_own = sum(sum(v.values()) for v in own_id.values())
    top_lines = []
    ranked = [(src, tgt, c) for src in hits for tgt, c in hits[src].items()]
    ranked.sort(key=lambda x: -sum(x[2].values()))
    for src, tgt, c in ranked[:8]:
        s = sum(c.values())
        pth, cnt = c.most_common(1)[0]
        top_lines.append(f"{src}→{tgt} {s} (top {pth}×{cnt}; e.g. "
                         f"{examples.get((src, tgt, pth), 'n/a')})")
    rows.append({
        "a": "element/group/place/levelProps", "b": "(any kind)",
        "dir": "deferred→any (unpinned)", "action": "ledgered",
        "unblockClass": "unadjudicated-name-hits",
        "unblock": (
            f"pin-aware global sweep over the four sources finds {tot_all} "
            "exact-name string matches OUTSIDE the admitted carrier paths "
            f"(of which {tot_own} rest ONLY on the row's own `id` "
            "colliding with another kind's id — namespace coincidence, "
            "the dig-15 m2 pattern). Dominant families: dialog BLOCK ids "
            "colliding with icon/input ids (block ids are intra-element "
            "labels, not entities); generic tokens like 'Default' "
            "(levelProps props.refLoot ×13 — an untyped payload key whose "
            "value is simultaneously an amb/battle/loot id); dev-pivot "
            "French names (place.world.name). Top: " +
            " | ".join(top_lines) +
            ". Unblock: per-path code-consumer proof or a schema retype at "
            "TargetBuildID 21238928 patch-diff, then promote via "
            "cdb-payload-id-join. Never edges"),
        "note": "exact-name sweep hits, unadjudicated"})
    # 5. script-side non-resolving residue
    scr_bits = []
    for (src, tgt, chan), s in sorted(em.stats.items()):
        if chan == "hscript" and s["unresolved"]:
            scr_bits.append(f"{src}.script→{tgt} "
                            f"({','.join(sorted(s['prefixes']))}): "
                            f"{s['unresolved']}")
    rows.append({
        "a": "element", "b": "(script enums)", "dir": "element→any",
        "action": "ledgered", "unblockClass": "script-non-resolving",
        "unblock": (
            "script enum references resolving into NO id set of their own "
            "namespace (also kept per-family in _meta.unresolvedRefs): " +
            ("; ".join(scr_bits) if scr_bits else "none") +
            f"; the comment-stripped scan additionally ignores "
            f"{em.script_refs_in_comments} in-comment matches (schema "
            "prose such as 'Group.props.seaLords.treasureMap' in a "
            "B1SeaLord01Leader comment — documentation, not references)"),
        "note": ""})
    # 6. anonymous carrier rows (authored-empty id)
    anon_rows = sum(em.anonymous_skipped.values())
    anon_refs = sum(em.anonymous_refs.values())
    if anon_rows:
        rows.append({
            "a": "element", "b": "(anonymous rows)", "dir": "element→any",
            "action": "ledgered", "unblockClass": "anonymous-carrier-rows",
            "unblock": (
                f"{anon_rows} element rows carry an AUTHORED-EMPTY `id` "
                "(scene-local anonymous NPCs, e.g. training-camp dummies "
                "under prefabs/places/region/*/ / Beast_*.prefab) while "
                f"holding {anon_refs} resolving typed-carrier values; an "
                "edge needs a source identity, so these rows are excluded "
                "from emission (never invented ids). Their payloads stay "
                "in the dataset addressed by `_carrier`+`_path`. Unblock: "
                "address by (carrier,path) locator if a consumer needs "
                "anonymous scene props; recheck at TargetBuildID 21238928 "
                "patch-diff"),
            "note": f"rows={anon_rows} refs={anon_refs}, never edges"})
    if not dry:
        path = os.path.join(LOGIC, "_ledger_deferred.jsonl")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8")
    kinds, metas = load_universe()
    em = Emitter(kinds, metas)
    em.run()

    written = emit_files(em, dry=args.dry_run)
    total_edges = sum(n for _, _, n in written)

    # probe (a): dangling endpoints
    dangling = []
    for key, edges in em.found.items():
        src, tgt = key
        for e in edges:
            if e["fromId"] not in em.ids[src]:
                dangling.append((src, tgt, str(e["fromId"]), "fromId"))
            if e["toId"] not in em.ids[tgt]:
                dangling.append((src, tgt, str(e["toId"]), "toId"))

    non_admitted = em.declared_not_admitted()
    hits, examples, own_id = em.residual_sweep()
    ledger_rows = emit_ledger(em, non_admitted, hits, examples, own_id,
                              dry=args.dry_run)

    print(f"families written: {len(written)}  edges: {total_edges}  "
          f"dangling: {len(dangling)}")
    for src, tgt, n in sorted(written, key=lambda w: (-w[2], w[0], w[1])):
        print(f"  _logic/{src}__{tgt}.jsonl  {n}")
    typed_keys = [key for key in em.stats if key[2] == "payload"]
    script_keys = [key for key in em.stats if key[2] == "hscript"]
    typed_refs = sum(em.stats[k]["resolved"] for k in typed_keys)
    script_refs = sum(em.stats[k]["resolved"] for k in script_keys)
    print(f"typed resolving refs: {typed_refs}  "
          f"script resolving refs: {script_refs}")
    print(f"(script refs skipped inside comments: "
          f"{em.script_refs_in_comments})")
    print(f"ledger rows incl. header: {len(ledger_rows)}")
    for d in dangling[:10]:
        print("DANGLING", d)
    return 0 if not dangling else 1


if __name__ == "__main__":
    sys.exit(main())
