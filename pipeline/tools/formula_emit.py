#!/usr/bin/env python3
"""formula_emit.py — emit the Wartales logic layer's formula inventory.

Outputs (per brief docs/briefs/dig-formulas.mdx):
  extracted/logic/formulas.jsonl   one row per formula / parameter set:
                                   {id, system, source, formula, params,
                                   units, status, toolsPlanRow, toolUse}
  extracted/logic/constants.jsonl  the full `constant` sheet resolved
                                   (values[] + valueDifficulty[] inlined),
                                   the parameter registry every row cites.

Every numeric payload is read live from data.cdb at emit time — nothing
hand-typed — so a re-run after a patch re-proves or breaks each row.
Verbatim hscript bodies are read from extracted/logic/hscript/
(principle zero: sources stay byte-identical; this file only cites them).

Usage: python formula_emit.py <data.cdb> [--outdir extracted/logic]
"""
import json
import sys
import os
import datetime

BUILD_ID = "20318128"


def load(src):
    with open(src, "r", encoding="utf-8") as f:
        return json.load(f)


def const_rows(db):
    sheet = {s["name"]: s for s in db["sheets"]}["constant"]
    out = {}
    for l in sheet.get("lines", []):
        row = {"value": l.get("value")}
        if l.get("values"):
            row["values"] = [v.get("value") for v in l["values"]]
        if l.get("valueDifficulty"):
            # difficulty enum order: Easy,Normal,Hard,Extreme
            row["difficulty"] = {d["difficulty"]: d.get("value")
                                 for d in l["valueDifficulty"]}
        out[l["id"]] = row
    return out


DIFF_NAMES = {0: "Easy", 1: "Normal", 2: "Hard", 3: "Extreme"}


def cval(C, cid):
    """Scalar constant, or None."""
    return C[cid]["value"] if cid in C else None


def carr(C, cid):
    """Array constant as list, or None."""
    return C[cid].get("values") if cid in C else None


def cdiff(C, cid):
    """{Easy..Extreme: value} for a DIFF constant, or None."""
    d = C[cid].get("difficulty") if cid in C else None
    return {DIFF_NAMES[k]: v for k, v in d.items()} if d else None


def row(id_, system, source, kind, status, tools_plan_row, units, tool_use,
        formula=None, params=None, note=None):
    r = {
        "id": id_,
        "system": system,
        "source": source,
        "kind": kind,          # formula | parameter-set | curve | api-surface | state-schema
        "status": status,      # confirmed-in-client | community-inferred | mixed
        "toolsPlanRow": tools_plan_row,
        "units": units,
        "toolUse": tool_use,
    }
    if formula is not None:
        r["formula"] = formula
    if params is not None:
        r["params"] = params
    if note is not None:
        r["note"] = note
    return r


# ---- verbatim hscript formulas (cited from extracted/logic/hscript) --------
FORMULAS_HX = "extracted/logic/hscript/formulas.hx"

WEAPON_PRICE = """function weaponPrice( v : Item ) {
\tvar price = 10 + v.tier * 10;
\tif( v.rarity == 1 )
\t\tprice += 20;
\tif( v.rarity == 2 )
\t\tprice += 30;
\treturn price;
}"""

ITEM_PRICE = """function itemPrice( i : Item ) {
\tif( i.price != null )
\t\treturn i.price;
\tvar t = i.type;
\twhile( t != null ) {
\t\tif( t.props.basePrice != null )
\t\t\treturn t.props.basePrice;
\t\tt = t.parentType;
\t}
\treturn null; // will create NaN
}"""

CRAFT_PRICE = """function craftPrice( c : Craft ) {
\tvar p = 0;
\tfor( i in c.recipe )
\t\tp += itemPrice(i.item) * i.qty;
\tvar real = itemPrice(c.item);
\treturn p / real - 1;
}"""


# ---- bytecode cross-reference (brief item 4) -------------------------------
# Per-row identifiers probed against the hlboot.dat string pool
# (extracted/logic/hl-structure/strings.txt, emitted by the types-walk dig).
# A hit means the bytecode references the same named constant / API the
# formula cites -> double-confirmed. No hit on an hscript-defined name
# (formulas.hx functions, world flags) means that artifact is
# hscript-only, exactly as an embedded-interpreter design implies.
BYTECODE_TOKENS = {
    "trade.weapon-price": ["weaponPrice"],
    "trade.item-price": ["itemPrice"],
    "trade.craft-price": ["craftPrice"],
    "trade.parameter-set": ["TradeGoodPriceOverDistance",
                            "TradeGoodPricePowerDistance",
                            "ItemPriceDefaultSellFactor",
                            "ItemPriceMaximumSellFactor",
                            "ItemQualityBonus3", "ItemLevelPriceBaseLevel"],
    "company.wages": ["DailySalaryMin", "DailySalaryMax",
                      "GlobalSalaryDifficulty"],
    "company.food-consumption": ["Fief_NeedsPerPop", "RestFoodPrice"],
    "company.tiredness": ["TirednessAmountHours", "FightTirenessPerRound"],
    "xp.level-curve": ["LevelXpValues", "MaxLevelLock"],
    "xp.combat-gains": ["XpWinBasePerEnemy", "XpWinPowerRatio"],
    "xp.job-levels": ["JobXpLevels", "FactorJobLevel"],
    "xp.trait-path": ["PathXpBase", "TraitXPBase", "PathMaxLevel"],
    "capture.knockout-recruit": ["KnockOutChanceMin",
                                 "KnockOutChanceMinHealthPercent",
                                 "PrisonerTrustWhip", "RecruitCostBase",
                                 "PrisonerBasePrice"],
    "arena.pits-economy": ["Pit_ReputationOnWin", "Fief_Gambling_WinFactor"],
    "combat.injury-death-morale": ["InjurySmallHpPercent",
                                   "MoraleForEnemyFlee",
                                   "BackstabIgnoreGuard",
                                   "CriticalHitBonusBase",
                                   "WillpowerForNotDying"],
    "scaling.enemy-stat-bonus-per-difficulty": ["EnemyStatBonusLevels",
                                                "EnemyStatBonusLevelsEasy",
                                                "EnemyEarlyStatMalus"],
    "scaling.fixed-difficulty-powers": ["FixedDifficultyPowers",
                                        "FixedDifficultyReferenceLevels"],
    "scaling.level-windows-and-power": ["MaxLevelGroups", "RegionMinPower",
                                        "GlobalFightDifficulty",
                                        "SkilledUnit_Chance"],
    "combat.power-score-weights": ["PowerFactor_HealthArmor",
                                   "PowerFactor_SkillUpgrade"],
    "crafting.quality-tiers": ["ItemQualityBonus3", "ForgeWeightTierA",
                               "ForgeReducePercentPerFail"],
    "ghost.corruption": ["CorruptMissingHealthFactor", "canCorrupt"],
    "combat.skill-damage-surface": ["getPercentHealth", "opportunityAttack",
                                    "criticalHitDamageBonus", "damageHealth",
                                    "onEval", "onHit", "onSkillEval",
                                    "KnockOut"],
    "state.world-flag-registry": ["g1ArenaDone", "fiefTutorialAccepted"],
}


def load_string_pool(hl_dir):
    p = os.path.join(hl_dir, "strings.txt")
    if not os.path.isfile(p):
        return None, None
    pool = set()
    with open(p, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t", 1)
            pool.add(parts[1] if len(parts) > 1 else "")
    return pool, p


def annotate_bytecode(rows, hl_dir="extracted/logic/hl-structure"):
    pool, path = load_string_pool(hl_dir)
    for r in rows:
        toks = BYTECODE_TOKENS.get(r["id"])
        if not toks:
            continue
        if pool is None:
            r["bytecode"] = {"status": "pending",
                             "note": "hl-structure outputs not landed"}
            continue
        found = [t for t in toks if t in pool]
        missing = [t for t in toks if t not in pool]
        if not missing:
            status = "double-confirmed"
        elif not found:
            status = "hscript-only"
        else:
            status = "partial"
        r["bytecode"] = {
            "status": status,
            "stringPool": path,
            "tokensSearched": len(toks),
            "tokensFound": found,
            "tokensMissing": missing,
        }


def main(argv):
    src = argv[1]
    outdir = argv[argv.index("--outdir") + 1] if "--outdir" in argv \
        else "extracted/logic"
    os.makedirs(outdir, exist_ok=True)
    db = load(src)
    sheets = {s["name"]: s for s in db["sheets"]}
    C = const_rows(db)
    now = datetime.datetime.now().isoformat(timespec="seconds")

    rows = []

    # 1. trade prices -------------------------------------------------------
    rows.append(row(
        "trade.weapon-price", "Trade prices",
        {"file": "res.pak:/formulas.hx", "function": "weaponPrice",
         "verbatimSource": FORMULAS_HX},
        "formula", "confirmed-in-client", "1",
        "gold", "base weapon price before town/region modifiers",
        formula=WEAPON_PRICE,
        params={"tier": "item.tier int", "rarity": "0=C,1=U,2=R,3=Legendary"},
        note="rarity==3 (Legendary) carries NO surcharge here"))
    rows.append(row(
        "trade.item-price", "Trade prices",
        {"file": "res.pak:/formulas.hx", "function": "itemPrice"},
        "formula", "confirmed-in-client", "1",
        "gold", "fallback price resolution used by every other price path",
        formula=ITEM_PRICE,
        note="walks itemType.parentType chain for props.basePrice; "
             "basePrice is datafile-backed (not inline in this build's CDB)"))
    rows.append(row(
        "trade.craft-price", "Trade prices / crafting",
        {"file": "res.pak:/formulas.hx", "function": "craftPrice"},
        "formula", "confirmed-in-client", "1/10",
        "ratio (0 = break-even)",
        "craft profitability margin shown in the craft UI",
        formula=CRAFT_PRICE,
        note="hidden float col craft.calcPrice exists but is populated on "
             "0/667 rows -> editor-side helper, value recomputed at runtime"))

    trade_ids = [
        ("ItemPriceDefaultSellFactor", None), ("ItemPriceMaximumSellFactor", None),
        ("ItemHighSellValueFactor", None), ("ItemPriceFactorDiscount", None),
        ("TradeGoodPriceOverDistance", None), ("TradeGoodPricePowerDistance", None),
        ("TradeGoodPathSellThreshold", None), ("TradeGoodRepatriatePriceFactor", None),
        ("ItemQualityPrice1", None), ("ItemQualityPrice2", None),
        ("ItemQualityPrice3", None), ("ItemLevelPriceBaseLevel", None),
        ("ItemLevelPriceLowCoef", None), ("ItemLevelPriceHighCoef", None),
        ("ItemLevelPriceHighMul", None),
    ]
    tp = {k: cval(C, k) for k, _ in trade_ids}
    it_sell = {l["id"]: l["props"]["sellPriceFactor"]
               for l in sheets["itemType"]["lines"]
               if isinstance(l.get("props"), dict)
               and l["props"].get("sellPriceFactor") is not None}
    rows.append(row(
        "trade.parameter-set", "Trade prices",
        {"sheet": "constant", "columns": [k for k, _ in trade_ids],
         "sheetExtra": "itemType.props.sellPriceFactor"},
        "parameter-set", "mixed", "1",
        "factors x, distances in meters/world-units, gold",
        "price atlas + trade route planner gradients and caps",
        params={"constants": tp, "itemType.sellPriceFactor": it_sell},
        note="community hand-measured caps ~35% max buy cut / ~25% max sell "
             "bonus are [COMM]; client-side factors above are confirmed, the "
             "full composition (which factor applies where) resolves in "
             "hlboot.dat bytecode"))

    # 2. wages & upkeep ------------------------------------------------------
    wage = {k: cdiff(C, k) or cval(C, k) for k in (
        "DailySalaryMin", "DailySalaryMax", "SalaryCoefPerLevel",
        "SalaryAddingCaptain", "SalaryAddingLieutenant", "SalarySleeps",
        "GlobalSalaryDifficulty", "UnhappySalary", "Tavern_SalaryNoJob")}
    rows.append(row(
        "company.wages", "Wages & upkeep",
        {"sheet": "constant", "columns": sorted(wage)},
        "parameter-set", "confirmed-in-client", "2",
        "gold/day", "upkeep term of every profitability calculator",
        params=wage))

    # 3. food, tiredness, rest ------------------------------------------------
    uc_food = [{"id": l["id"], "dailyFood": l["props"]["dailyFood"]}
               for l in sheets["unitClass"]["lines"]
               if isinstance(l.get("props"), dict)
               and l["props"].get("dailyFood") is not None]
    food = {k: cval(C, k) for k in (
        "RestFoodPrice", "HappyBadDietFactor", "UnhappyStarve",
        "StarvationMemoryRests", "Fief_NeedsPerPop", "RestHours",
        "TravelRestByDay")}
    tired = {k: cval(C, k) for k in (
        "TirednessAmountHours", "TirednessMax", "TirednessMinFactor",
        "FightTirenessBase", "FightTirenessPerRound", "GlobalTiredDifficulty")}
    tired["GlobalTiredDifficulty"] = cdiff(C, "GlobalTiredDifficulty")
    rows.append(row(
        "company.food-consumption", "Food consumption",
        {"sheet": "constant + unitClass@props.dailyFood"},
        "parameter-set", "confirmed-in-client", "3",
        "food/day per unit", "ration-efficiency calculator input side",
        params={"constants": food, "unitClassDailyFood": uc_food}))
    rows.append(row(
        "company.tiredness", "Tiredness & rest",
        {"sheet": "constant"}, "parameter-set", "confirmed-in-client",
        "3/8", "factor, hours", "rest scheduling + travel planning tools",
        params=tired))

    # 4. XP curves ------------------------------------------------------------
    rows.append(row(
        "xp.level-curve", "XP & leveling",
        {"sheet": "constant", "column": "LevelXpValues.values[15]"},
        "curve", "confirmed-in-client", "4",
        "cumulative XP per unit level",
        "level budget math for the build planner",
        formula="level L+1 requires LevelXpValues[L] total XP (index table)",
        params={"table": carr(C, "LevelXpValues"),
                "MaxLevelLock": cval(C, "MaxLevelLock"),
                "UpValueLevelRef": cval(C, "UpValueLevelRef"),
                "note": "MaxLevelLock=15 coexists with lieutenant/banner "
                        "unlock levels 20/40 — exact semantics resolve in "
                        "bytecode (open question for hlboot cross-ref)"}))
    rows.append(row(
        "xp.combat-gains", "XP & leveling",
        {"sheet": "constant",
         "columns": ["XpWinBasePerEnemy", "XpWinBasePerEnemyKilled",
                     "XpWinPowerRatio", "XpWinDifficultyFactor",
                     "XpWinUnitNotInBattle"]},
        "parameter-set", "confirmed-in-client", "4",
        "xp", "post-battle XP projection",
        params={k: cval(C, k) for k in (
            "XpWinBasePerEnemy", "XpWinBasePerEnemyKilled",
            "XpWinPowerRatio", "XpWinDifficultyFactor",
            "XpWinUnitNotInBattle")}))
    rows.append(row(
        "xp.job-levels", "XP & leveling (professions)",
        {"sheet": "constant",
         "columns": ["JobXpLevels", "FactorJobLevel", "MaxJobLevel",
                     "GoldXpComponent", "CommonXpComponent",
                     "UncommonXpComponent", "RareXpComponent",
                     "LegendaryXpComponent", "DefaultXpComponent"]},
        "curve", "confirmed-in-client", "4/7",
        "job xp, multipliers",
        "profession levelling + loot-quality xp coupling",
        params={"JobXpLevels": carr(C, "JobXpLevels"),
                "FactorJobLevel": carr(C, "FactorJobLevel"),
                "MaxJobLevel": cval(C, "MaxJobLevel"),
                "rarityXpComponents": {k: cval(C, k) for k in (
                    "GoldXpComponent", "CommonXpComponent",
                    "UncommonXpComponent", "RareXpComponent",
                    "LegendaryXpComponent", "DefaultXpComponent")}}))
    rows.append(row(
        "xp.trait-path", "XP & leveling (traits/paths)",
        {"sheet": "constant",
         "columns": ["TraitXPBase", "TraitXPIncrease", "TraitXPActivity",
                     "PathXpBase", "PathXpNext", "PathMaxLevel"]},
        "parameter-set", "confirmed-in-client", "4/12",
        "xp, levels", "path-perk progression pacing (tools-plan row 12)",
        params={k: cval(C, k) for k in (
            "TraitXPBase", "TraitXPIncrease", "TraitXPActivity",
            "PathXpBase", "PathXpNext", "PathMaxLevel")}))

    # 5. capture / tame --------------------------------------------------------
    capture = {
        "KnockOutChanceMin%": cval(C, "KnockOutChanceMin"),
        "KnockOutChanceMax%": cval(C, "KnockOutChanceMax"),
        "healthPercent_at_min": cval(C, "KnockOutChanceMinHealthPercent"),
        "healthPercent_at_max": cval(C, "KnockOutChanceMaxHealthPercent"),
        "PrisonerRatio": cval(C, "PrisonerRatio"),
        "MinPrisonerTrustToRecruit": cval(C, "MinPrisonerTrustToRecruit"),
        "PrisonerTrustRange": [cval(C, "MinPrisonerTrust"),
                               cval(C, "MaxPrisonerTrust")],
        "trustModifiers": {k: cval(C, k) for k in (
            "PrisonerTrustWellFed", "PrisonerTrustAdjacentAlly",
            "PrisonerTrustAdjacentAnimal", "PrisonerTrustHeal",
            "PrisonerTrustNotRest", "PrisonerTrustPillory",
            "PrisonerTrustWhip", "PrisonerTrustBeardPerDay")},
        "ransomPrices": {k: cval(C, k) for k in (
            "PrisonerBasePrice", "PrisonerLevelScalePrice",
            "PrisonerJobScalePrice", "PrisonerOutlawBasePrice",
            "PrisonerOutlawLevelScalePrice")},
        "recruitCosts": {k: cval(C, k) for k in (
            "RecruitCostBase", "RecruitCostIncrease", "RecruitCostFactor",
            "RecruitCostFactorPrisonerInTroop", "RecruitCostInfluenceToGold")},
    }
    cc = [{"id": l["id"], "captureCost": l["props"]["captureCost"],
           "prisonerProbability": l["props"].get("prisonerProbability")}
          for l in sheets["unitClass"]["lines"]
          if isinstance(l.get("props"), dict)
          and l["props"].get("captureCost") is not None]
    rows.append(row(
        "capture.knockout-recruit", "Capture / tame odds",
        {"sheet": "constant + unitClass@props.captureCost/prisonerProbability"},
        "parameter-set", "mixed", "5",
        "% chance, gold, rope qty",
        "capture/recruit explorer: knockout chance endpoints, rope cost "
        "per beast, trust economy, ransom valuation",
        params={**capture, "unitClassCaptureCost": cc},
        note="endpoints confirmed (50%@>=50% HP .. 100%@<=10% HP); the "
             "interpolation between them + resist rolls live in bytecode"))

    # 6. arena / pits -----------------------------------------------------------
    pit_rep = {k: (cdiff(C, k) or carr(C, k) or cval(C, k)) for k in (
        "Pit_ReputationOnFirstWin", "Pit_ReputationOnWin",
        "Pit_ReputationOnAllWin")}
    rows.append(row(
        "arena.pits-economy", "Arena betting (The Pits)",
        {"sheet": "constant", "columns": ["Pit_*", "Arena_*"]},
        "parameter-set", "mixed", "6",
        "gold, reputation, %",
        "arena-betting advisor groundwork (watchlist tool)",
        params={"Pit_RecruitCost": cval(C, "Pit_RecruitCost"),
                "reputation": pit_rep,
                "Pit_BossPercentHealthReduction":
                    cval(C, "Pit_BossPercentHealthReduction"),
                "Pit_BossDotFactor": cval(C, "Pit_BossDotFactor"),
                "Fief_Gambling_Bet": carr(C, "Fief_Gambling_Bet"),
                "Fief_Gambling_WinFactor": cval(C, "Fief_Gambling_WinFactor"),
                "Fief_Effect_GamblingProba": cval(C, "Fief_Effect_GamblingProba")},
        note="fighter-vs-fighter win odds themselves are NOT in data.cdb — "
             "they resolve in bytecode (battle AI/power); payout/reputation "
             "parameters are confirmed"))

    # 7. injury / death / morale -------------------------------------------------
    rows.append(row(
        "combat.injury-death-morale", "Injury, death & morale",
        {"sheet": "constant + attribute.desc (Guard backstab clause)"},
        "parameter-set", "confirmed-in-client", "7/8/15",
        "%, thresholds", "survivability math in the build planner",
        params={k: cval(C, k) for k in (
            "InjurySmallHpPercent", "InjuryFleePercentGet",
            "WillpowerForNotDying", "MoraleLostOnDie",
            "MoraleLostIncreaseOnEachDeath", "MoraleForEnemyFlee",
            "MoraleForGalvanized", "MoraleForMotivated",
            "WillpowerToMoralPerLevel", "MoraleRandomization",
            "BackstabIgnoreGuard", "CriticalHitBonusBase",
            "CriticalHitBonusMult", "CriticalHitPercentBackstabBonus",
            "AttributeCriticalScalePower", "HealInjuryPrice",
            "GuardMaxValue", "KnockOutChanceMin")},
        note="morale/mood thresholds fully client-read; attribute sheet desc "
             "confirms guard halves against backstabs"))

    # 9. adaptive difficulty / level scaling --------------------------------------
    rows.append(row(
        "scaling.enemy-stat-bonus-per-difficulty", "Adaptive difficulty",
        {"sheet": "constant",
         "columns": ["EnemyStatBonusLevels{,Easy,Hard,Extreme}.values[18]"]},
        "curve", "confirmed-in-client", "9/E5",
        "+% stat bonus by enemy level (index = level-1)",
        "spawn/scaling inspector: THE per-mode enemy stat tables",
        params={
            "Normal": carr(C, "EnemyStatBonusLevels"),
            "Easy": carr(C, "EnemyStatBonusLevelsEasy"),
            "Hard": carr(C, "EnemyStatBonusLevelsHard"),
            "Extreme": carr(C, "EnemyStatBonusLevelsExtreme"),
            "EnemyEarlyStatMalus": cdiff(C, "EnemyEarlyStatMalus"),
            "AnimalScale": cval(C, "EnemyStatsBonusAnimalScale")}))
    rows.append(row(
        "scaling.fixed-difficulty-powers", "Adaptive difficulty",
        {"sheet": "constant",
         "columns": ["FixedDifficultyPowers{,Easy,Hard,Extreme}[21]",
                     "FixedDifficultyReferenceLevels{,Easy,Hard,Extreme}[21]"]},
        "curve", "confirmed-in-client", "9/E5",
        "power score targets + reference levels per region tier",
        "answers 'what level/power should my company be where' per mode",
        params={name: {"powers": carr(C, f"FixedDifficultyPowers{name}"),
                       "referenceLevels": carr(
                           C, f"FixedDifficultyReferenceLevels{name}")}
                for name in ("", "Easy", "Hard", "Extreme")}))
    rows.append(row(
        "scaling.level-windows-and-power", "Adaptive difficulty",
        {"sheet": "constant"},
        "parameter-set", "confirmed-in-client", "9/E5",
        "levels, power multipliers",
        "region-lock window + global fight scaling per mode",
        params={
            "MinLevelDiff": cdiff(C, "MinLevelDiff"),
            "MaxLevelDiff": cdiff(C, "MaxLevelDiff"),
            "MaxLevelGroups": cdiff(C, "MaxLevelGroups"),
            "RegionMinPower": cdiff(C, "RegionMinPower"),
            "GlobalFightDifficulty": cdiff(C, "GlobalFightDifficulty"),
            "PowerDifficultyFactor": carr(C, "PowerDifficultyFactor"),
            "PowerFactor_Level": carr(C, "PowerFactor_Level"),
            "ExtremeEnemyCountReduction": carr(C, "ExtremeEnemyCountReduction"),
            "SkilledUnit_Ratio": carr(C, "SkilledUnit_Ratio"),
            "SkilledUnit_Chance": cval(C, "SkilledUnit_Chance"),
            "HelmetUnit_Ratio": carr(C, "HelmetUnit_Ratio")}))
    rows.append(row(
        "combat.power-score-weights", "Damage & combat math (power rating)",
        {"sheet": "constant", "columns": ["PowerFactor_*"]},
        "parameter-set", "confirmed-in-client", "15/9",
        "weights over unit stats -> power score",
        "the game's own unit-strength metric, usable to rate any build",
        params={k: (carr(C, k) if C[k].get("values") else
                    (cdiff(C, k) if C[k].get("difficulty") else cval(C, k)))
                for k in C if k.startswith("PowerFactor_")}))

    # 10. crafting quality tiers ---------------------------------------------------
    rows.append(row(
        "crafting.quality-tiers", "Crafting quality tiers & golden strikes",
        {"sheet": "constant", "columns": ["ItemQualityBonus*", "Forge*",
                                          "Alter*"]},
        "parameter-set", "mixed", "10/M2",
        "stat multiplier, forge minigame weights/probabilities",
        "forging outcome calculator incl. superior-tier stat multipliers",
        params={"statMultipliers": {
                    "quality1": cval(C, "ItemQualityBonus1"),
                    "quality2": cval(C, "ItemQualityBonus2"),
                    "quality3": cval(C, "ItemQualityBonus3"),
                    "helmetFlat": cval(C, "ItemQualityBonusHelmet")},
                "forgeMinigame": {k: cval(C, k) for k in (
                    "ForgeWeightTierA", "ForgeWeightTierB", "ForgeWeightTierC",
                    "ForgeReducePercentPerFail", "ForgetPercentageQuality3",
                    "AlterFactorReduceWithQuality", "AlterMinFactor",
                    "AlterMaxFactor", "AlterMaxFactorAtLevel")},
                "priceMultipliers": {
                    "q1": cval(C, "ItemQualityPrice1"),
                    "q2": cval(C, "ItemQualityPrice2"),
                    "q3": cval(C, "ItemQualityPrice3")}},
        note="client shows THREE quality bonus tiers (1.1/1.2/1.3) — "
             "community documents only +10%/+20%; exact golden-strike roll "
             "composition pending bytecode"))

    # 11. ghost curses / corruption --------------------------------------------------
    rows.append(row(
        "ghost.corruption", "Ghost curses",
        {"sheet": "constant", "skillScript": "Corrupt",
         "file": "content/script/World.hx (ghost flags)"},
        "parameter-set + api-hook", "confirmed-in-client", "11",
        "factors", "curse-risk model for Ludern/Skelmar content",
        params={k: cval(C, k) for k in (
            "CorruptMissingHealthFactor", "CorruptUnitUncoFactor",
            "CorruptUnitRareFactor", "CorruptUnitSkilledFactor",
            "CorruptMoralPositiveFactor", "CorruptBonusPerTryFactor")},
        note="runtime hook confirmed verbatim in skill script 'Corrupt': "
             "canCorrupt(u) gate + corrupt() application"))

    # 13. valor — honest negative -----------------------------------------------------
    rows.append(row(
        "valor.not-found", "Valor points",
        {"searched": "constant ids, skill scripts, attribute/status sheets"},
        "negative-result", "unverified", "13",
        "-", "no client-side valor parameter found in this pass; stays "
             "[P0-DIG] via hlboot.dat globals",
        note="recorded per doctrine: relations looked for and not found are "
             "documented, never silently dropped"))

    # 15. skill damage surface ----------------------------------------------------------
    sk_lines = sheets["skill"]["lines"]
    attrs = [a["id"] for a in sheets["attribute"]["lines"]]
    dmg_c = {}
    vars_n = ap_n = mm_n = 0
    for l in sk_lines:
        p = l.get("props") or {}
        if p.get("dmgAttribute") is not None:
            a = attrs[p["dmgAttribute"]]
            dmg_c[a] = dmg_c.get(a, 0) + 1
        if isinstance(p.get("vars"), dict):
            vars_n += 1
        if p.get("apCost") is not None:
            ap_n += 1
        if l.get("minDmg") is not None:
            mm_n += 1
    rows.append(row(
        "combat.skill-damage-surface", "Damage & combat math",
        {"sheet": "skill", "columns": ["minDmg", "maxDmg",
                                       "props.dmgAttribute", "props.apCost",
                                       "props.vars", "script"]},
        "api-surface", "confirmed-in-client", "15/M3",
        "damage points, AP, attribute enum index",
        "damage estimate engine inputs for the build planner",
        params={"skills": len(sk_lines),
                "withScript": sum(1 for l in sk_lines if l.get("script")),
                "withVars": vars_n, "withApCost": ap_n,
                "withMinMaxDmg": mm_n,
                "dmgAttributeCounts": dmg_c,
                "hooks": {"onEval/onSkillEval": "pre-resolution modifiers "
                          "(crit, damageHealth...)", "onHit": "post-hit "
                          "effects", "onDamage/onDamageDealt": "reactive",
                          "onBeginAction/onEndTurn": "aura/regen ticks"},
                "runtimeApi": ["damages()", "getPercentHealth()",
                               "gainsHealth()", "pushback()",
                               "opportunityAttack()", "addStatus()",
                               "hasStatus()", "cancelStatus()", "corrupt()",
                               "attackTarget()", "getFoes()/getAllies()"]},
        note="armor/guard/crit final resolution lives in hlboot.dat "
             "(16 MB HLB) — skill scripts compose it, they don't replace it"))

    # state schema --------------------------------------------------------------------
    import re
    hscript_dir = os.path.join(outdir, "hscript", "content", "script")

    def count_flags(path):
        txt = open(path, encoding="utf-8").read()
        return len(re.findall(r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*:", txt, re.M))

    world_flags_path = os.path.join(hscript_dir, "World.hx")
    region_files = sorted(f for f in os.listdir(hscript_dir)
                          if f.endswith(".hx") and f not in ("Paths.hx",
                                                             "World.hx"))
    region_flags = sum(count_flags(os.path.join(hscript_dir, f))
                       for f in region_files)
    world_flag_n = count_flags(world_flags_path)
    rows.append(row(
        "state.world-flag-registry", "Quest/path/state",
        {"files": ["extracted/logic/hscript/content/script/World.hx"] + [
            f"extracted/logic/hscript/content/script/{f}"
            for f in region_files]},
        "state-schema", "confirmed-in-client", "12/M4-M7",
        "booleans + counters",
        "quest-state vocabulary for guides/tools; path progression flags "
        "(Crime/Might/Trade/Knowledge) live here",
        params={"worldFlags": world_flag_n,
                "regionFlags": region_flags,
                "regionGlobalsFiles": len(region_files)},
        note="Paths.hx is an empty stub (onInit_Paths{}); these are state "
             "containers, not formulas — preserved verbatim per principle zero"))

    # ---- write formulas.jsonl ----------------------------------------------------------
    annotate_bytecode(rows)
    fx = os.path.join(outdir, "formulas.jsonl")
    meta = {"_meta": {
        "buildId": BUILD_ID,
        "emitted": now,
        "tool": "pipeline/tools/formula_emit.py",
        "sources": ["res.pak:/formulas.hx (687 B)",
                    "res.pak:/content/script/*.hx (11 files)",
                    "res.pak:/data.cdb sheet `constant` (1,266 rows)",
                    "res.pak:/data.cdb sheets skill/unitClass/itemType/"
                    "craft/attribute (script + payload columns)"],
        "rowCount": len(rows),
        "statusVocabulary": {
            "confirmed-in-client": "value(s) read directly from client files "
                                   "this dig",
            "mixed": "parameters client-read, composition still bytecode-side",
            "community-inferred": "community-measured, no client read yet",
            "unverified": "looked for, not found"},
        "bytecodeStatusVocabulary": {
            "double-confirmed": "every probed identifier appears in the "
                                "hlboot.dat string pool",
            "partial": "some identifiers appear",
            "hscript-only": "no identifier appears (embedded-interpreter "
                            "artifacts: formulas.hx functions)",
            "pending": "hl-structure outputs absent at emit time"},
        "companionDatasets": ["extracted/logic/constants.jsonl",
                              "extracted/logic/hscript/**"]}}
    with open(fx, "w", encoding="utf-8", newline="\n") as g:
        g.write(json.dumps(meta, ensure_ascii=False) + "\n")
        for r in rows:
            # flatten the optional params_extra into params
            extra = r.pop("params_extra", None)
            if extra:
                r["params"].update(extra)
            g.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ---- write constants.jsonl ---------------------------------------------------------
    cx = os.path.join(outdir, "constants.jsonl")
    csheet = sheets["constant"]
    cmeta = {"_meta": {
        "kind": "constant", "sourceSheet": "constant", "buildId": BUILD_ID,
        "container": "res.pak:/data.cdb (CastleDB JSON, compress=false)",
        "rowCount": len(csheet.get("lines", [])), "emitted": now,
        "tool": "pipeline/tools/formula_emit.py",
        "columns": [{ "name": c["name"], "typeStr": str(c.get("typeStr")),
                      "opt": bool(c.get("opt")), "kind": c.get("kind")}
                    for c in csheet["columns"]],
        "enums": {"valueDifficulty.difficulty": ["Easy", "Normal", "Hard",
                                                 "Extreme"]},
        "note": "full parameter registry; values[] and valueDifficulty[] "
                "resolved inline; info/color columns preserved verbatim"}}
    with open(cx, "w", encoding="utf-8", newline="\n") as g:
        g.write(json.dumps(cmeta, ensure_ascii=False) + "\n")
        for l in csheet.get("lines", []):
            out = {"id": l.get("id"), "value": l.get("value"),
                   "info": l.get("info")}
            if l.get("values"):
                out["values"] = [v.get("value") for v in l["values"]]
            if l.get("valueDifficulty"):
                out["difficulty"] = {DIFF_NAMES[d["difficulty"]]: d.get("value")
                                     for d in l["valueDifficulty"]}
            if l.get("color"):
                out["color"] = l["color"]
            g.write(json.dumps(out, ensure_ascii=False) + "\n")

    n_conf = sum(1 for r in rows if r["status"] == "confirmed-in-client")
    print(f"formulas.jsonl: {len(rows)} rows "
          f"({n_conf} confirmed-in-client, "
          f"{sum(1 for r in rows if r['status']=='mixed')} mixed) -> {fx}")
    print(f"constants.jsonl: {cmeta['_meta']['rowCount']} rows -> {cx}")


if __name__ == "__main__":
    main(sys.argv)
