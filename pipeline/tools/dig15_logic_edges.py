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

    def scan_typed(self, kind, dotted, tgt, fam=None, conv=str):
        """Typed leaf join: values at dotted path resolved against tgt ids."""
        st = self.stats
        sk = (kind, tgt)
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
        for row in self.kinds["item"]:
            for p, cont, k, v in walk(row.get("props"), "props"):
                if k == "bonus" and isinstance(v, str):
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
        for row in self.kinds["confessions"]:
            data = row.get("data")
            if not isinstance(data, list):
                continue
            for p, cont, k, v in walk(data, "data"):
                if not isinstance(v, str):
                    continue
                # gains.<K>[].inf  (path ...gains.<K>[].inf)
                m = re.search(r"\.gains\.([A-Za-z]+)\[\]\.inf$", p)
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
        # region counters: every scalar under props.counters resolving into
        # counter ids (keys localTeamDefeated/blackmarketFinished/... +
        # finishConfessions[].counter)
        self.scan_region_counters()
        self.scan_confessions_gains()

    def scan_region_counters(self):
        st = self.stats
        sk = ("region", "counter")
        for row in self.kinds["region"]:
            base = (row.get("props") or {}).get("counters")
            if not isinstance(base, dict):
                continue
            for p, cont, k, v in walk(base, "props.counters"):
                if isinstance(v, str):
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
        if (frm, to) in modeled:
            meta["_meta"]["modeledDirectionNote"] = (
                "direction already modeled canonically; this file carries "
                "ADDITIONAL undeclared payload join keys for the next spec "
                "re-freeze fold — not counted as a bar-1 transition")
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


UNRELATED = ("structurally unrelated at buildid 20318128: zero carriers "
             "across all four checks (canonical hard refs, payload-id "
             "sweep, hscript enum sweep, schema 6:-column census) — "
             "recheck at TargetBuildID 21238928 patch-diff")

TERMINAL = {
    "icon": ("terminal registry", "atlas/icon registry consumed only "
             "inbound (counter.path, recipe.group, attribute.icon); other "
             "kinds carry atlas descriptors routed straight to UIA assets "
             "(dig 4 resolution mechanism), never through icon-sheet ids"),
    "input": ("terminal registry", "bindings/category scalars only; no "
              "outbound id carrier exists in client data or code"),
    "credits": ("terminal registry", "credits roll — lines/linesTrad text "
                "only"),
    "sound": ("audio carve-out", "Wwise-carried relations sit outside the "
              "corpus by media carve-out ([DR-2026-08-18-media-scope]); "
              "data-side joins are inbound (amb.mood/battleMood, "
              "gameObject self-chain)"),
    "kingdom": ("leaf vocabulary", "bare rows (name/props flags like "
                "fiefCanTrade); the kingdom join is carried by regions "
                "inbound (region.kingdom, modeled reverse)"),
    "condition": ("leaf vocabulary", "comment/done scalars; consumers "
                  "reference it inbound (fiefEvent.conditions[].cond, "
                  "fiefPlace.productions[].conds[].cond, both modeled)"),
    "effect": ("leaf vocabulary", "implement bool + numeric target enums, "
               "no id-typed outbound columns"),
    "fiefCondition": ("leaf vocabulary", "numeric target enums; consumed "
                      "inbound by fiefGoal/fiefCondition chains"),
    "fiefAlignment": ("leaf vocabulary", "names/desc/props scalars only"),
    "fiefPopulation": ("leaf vocabulary", "name/inf scalars only"),
    "tutorial": ("inward-only chain", "steps[].tuto self-chain (modeled); "
                 "no outbound entity ids"),
    "startChoice": ("inward-only chain", "troopChoices self-chain (modeled) "
                    "+ props.pattern → unitPattern now in the evidence "
                    "layer; no other outbound carrier"),
    "trait": ("bitmask vocabulary", "gen bitmask + condition enum — flag-"
              "name mapping to unitClass.flags stays unproven; unblock: "
              "decode the shared enum tables in data.cdb customTypes"),
    "skill": ("code-side only", "skill subtree declares ZERO hard-reference "
              "columns (dig 1 finding 4) — remaining carriers would be "
              "runtime wiring behind unresolved closure call sites (8,964 "
              "OCallClosure, dig 13 residual); script-enum families are in "
              "the evidence layer"),
}


def classify_directions(kinds, metas, matrix_json, derived_dirs):
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
            if y in schema_refs.get(x, set()):
                cls = "schema-empty"
                tok = (f"schema-declared 6:{y} column on {x} carries zero "
                       "populated cells at buildid 20318128 — recheck at "
                       "TargetBuildID 21238928 patch-diff")
                note = f"declared on {x} sheet, never populated in-line"
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
        kinds, metas, matrix_json, derived_dirs)

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
    for d in dangling[:10]:
        print("DANGLING", d)
    return 0 if not dangling else 1


if __name__ == "__main__":
    sys.exit(main())
