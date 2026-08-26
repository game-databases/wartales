#!/usr/bin/env python3
"""cdb_verify.py — INDEPENDENT verification of the draft datasets + relink
seeds against res.pak:/data.cdb and the census counts in docs/cdb-census.mdx.

Deliberately shares no code with cdb_emit.py: it re-derives every expectation
from the raw CastleDB with an assertion-style traversal (compare-as-it-walks,
not construct-then-compare) and hard-codes the census row counts as a second,
doc-side copy so emit↔census reconciliation is bidirectional.

Verified per dataset (exhaustive, every row / every cell):
  _meta contract (buildId, rowCount, tool, column schemas == CDB schema);
  row count == census count == source-sheet line count;
  id sequence (native `"0"` column, or the documented synthetic rule);
  cell fidelity: localizable cells are EXACT textKey refs (no prose leaks),
  `6:` cells preserved verbatim, lists recurse, everything else deep-equals
  the raw payload; no dropped raw keys (schema ⊇ payload proven per row);
  no invented keys beyond the documented synthetic `id`.

Verified per relink file:
  edge multiset == independently recounted populated `6:` cells;
  per-edge `valid` recomputed (True strict membership / False dangling /
  None datafile-backed-or-hidden target); dangling must be 0 pack-wide.

Usage: python cdb_verify.py <data.cdb> [--datadir DIR] [--reldir DIR]
                           [--buildid ID]   (default 20318128, spec §3.6)
"""
import json
import sys
import os
import collections
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wave_kinds  # membership metadata only (spec §3.3/§3.4 rule 1) — the
                   # census transcription and all derivation stay independent

BUILD_ID = "20318128"

# docs/cdb-census.mdx full-sheet table — top-level inline-row sheets only
# (independent transcription; reconciliation is doc ↔ emit, both directions)
CENSUS = {
    "icon": 801, "tutorial": 81, "notify": 482, "groupType": 97,
    "frescos": 9, "region": 13, "kingdom": 9, "env": 87, "activity": 24,
    "itemType": 96, "item": 2125, "craft": 667, "loot": 382, "mission": 22,
    "confessions": 87, "startChoice": 29, "trait": 214, "unitClass": 281,
    "unitPattern": 70, "attribute": 27, "skill": 1373, "status": 330,
    "battle": 133, "effect": 66, "bonus": 495, "counter": 622,
    "constant": 1266, "condition": 18, "sound": 848, "amb": 11,
    "fiefPlace": 19, "fiefGoal": 55, "fiefCondition": 20,
    "fiefAlignment": 5, "fiefAdministration": 15, "fiefPopulation": 11,
    "fiefEvent": 377, "fiefMission": 12, "fiefLaw": 43, "input": 84,
    "credits": 67,
}

# dig-log recorded wave-1 relink totals (docs/data-dig-log.mdx, dig 1)
DIG1_EDGES = {
    "class__attribute": 1672, "item__itemType": 2095, "class__item": 914,
    "class__skill": 874, "item__attribute": 728, "class__itemType": 221,
    "class__groupType": 122, "class__region": 10,
}

problems = []
_MISSING = object()  # sentinel: key absent


def fail(msg):
    problems.append(msg)


def code_of(ts):
    return str(ts).partition(":")[0]


def param_of(ts):
    return str(ts).partition(":")[2] or None


def synth_id(kind, i, raw, idcol):
    """Mirror of the documented _meta.keyRule rules."""
    if idcol is not None:
        return raw[idcol]
    if kind == "frescos":
        return raw["place"]
    return f"{kind}-{i:04d}"


class Verifier:
    def __init__(self, db):
        self.sheets = {s["name"]: s for s in db["sheets"]}
        self.extra_preserved = 0
        self.id_sets = {}
        for n, s in self.sheets.items():
            idc = next((c["name"] for c in s.get("columns", [])
                        if code_of(c.get("typeStr", "")) == "0"), None)
            if idc is not None and s.get("lines"):
                self.id_sets[n] = {l[idc] for l in s["lines"]}

    def schema(self, sn):
        return self.sheets.get(sn, {}).get("columns", [])

    def check(self, sn, raw, em, kind, top_id, path, edges):
        """Assert emitted row/sub-row faithfully renders raw against schema."""
        cols = self.schema(sn)
        names = [c["name"] for c in cols]
        # payload keys OUTSIDE the declared schema must be preserved verbatim
        # (doctrine principle zero); verify presence + value equality
        extra_raw = [k for k in raw if k not in names]
        for k in extra_raw:
            self.extra_preserved += 1
            if raw[k] is not None and em.get(k, _MISSING) != raw[k]:
                fail(f"{kind}:{top_id} {path}{k}: undeclared key not preserved "
                     f"({json.dumps(raw[k])[:80]!r} -> "
                     f"{json.dumps(em.get(k))[:80]!r})")
            if raw[k] is None and k in em:
                fail(f"{kind}:{top_id} {path}{k}: null undeclared key emitted")
        allowed = set(names) | set(extra_raw) | ({"id"} if path == "" else set())
        stray = [k for k in em if k not in allowed]
        if stray:
            fail(f"{kind}:{top_id} {sn}: invented emitted keys {stray}")
        for c in cols:
            nm, ts = c["name"], str(c.get("typeStr"))
            rv = raw.get(nm)
            if rv is None:
                if nm in em:
                    fail(f"{kind}:{top_id} {path}{nm}: null raw present in emit")
                continue
            if nm not in em:
                fail(f"{kind}:{top_id} {path}{nm}: populated raw missing in emit")
                continue
            ev = em[nm]
            cd = code_of(ts)
            if cd == "1" and c.get("kind") == "localizable":
                want = {"textKey": {
                    "bridge": "lang/export_<locale>.xml",
                    "sheet": sn.split("@")[0],
                    "column": nm,
                    "row": top_id,
                }}
                if "@" in sn:
                    want["textKey"]["subSheet"] = sn
                if ev != want:
                    fail(f"{kind}:{top_id} {path}{nm}: textKey mismatch "
                         f"{json.dumps(ev)[:120]}")
                if not isinstance(rv, str):
                    fail(f"{kind}:{top_id} {path}{nm}: localizable raw not text")
            elif cd == "6":
                if ev != rv:
                    fail(f"{kind}:{top_id} {path}{nm}: ref altered {rv!r}->{ev!r}")
                edges.append((kind, param_of(ts).split("@")[0].split(".")[0],
                              path + nm, top_id, rv))
            elif cd == "8":
                sub = f"{sn}@{nm}"
                if not (isinstance(rv, list) and isinstance(ev, list)
                        and len(rv) == len(ev)):
                    fail(f"{kind}:{top_id} {path}{nm}: list shape broken")
                    continue
                for sr, se in zip(rv, ev):
                    self.check(sub, sr, se, kind, top_id, f"{path}{nm}[].",
                               edges)
            else:
                if ev != rv:
                    fail(f"{kind}:{top_id} {path}{nm}: value altered")


def main(argv):
    src = argv[1]

    def opt(a, d=None):
        return argv[argv.index(a) + 1] if a in argv else d

    datadir = opt("--datadir", "extracted/data/_draft")
    reldir = opt("--reldir", "extracted/relinks/_draft")
    buildid = opt("--buildid", BUILD_ID)  # spec §3.6: require equality

    with open(src, "r", encoding="utf-8") as f:
        db = json.load(f)
    V = Verifier(db)

    # ---- datasets ----------------------------------------------------------
    # Scan scope (spec §3.3, arbiter F1): only the 40 managed kinds are
    # verified; anything else is skipped and enumerated, never failed.
    all_files = sorted(fn for fn in os.listdir(datadir) if fn.endswith(".jsonl"))
    files = [fn for fn in all_files
             if fn[:-6] in wave_kinds.MANAGED_KINDS]
    skipped_data = [fn for fn in all_files
                    if fn[:-6] not in wave_kinds.MANAGED_KINDS]
    seen_kinds = {}
    total_rows = 0
    textkey_sheets = collections.Counter()
    for fn in files:
        p = os.path.join(datadir, fn)
        with open(p, "r", encoding="utf-8", errors="strict") as g:
            lines = g.read().splitlines()
        try:
            meta = json.loads(lines[0])
            rows = [json.loads(x) for x in lines[1:]]
        except json.JSONDecodeError as e:
            fail(f"{fn}: JSON parse error {e}")
            continue
        m = meta.get("_meta", {})
        kind, sn = m.get("kind"), m.get("sourceSheet")
        seen_kinds[kind] = sn
        if m.get("buildId") != buildid:
            fail(f"{fn}: buildId {m.get('buildId')}")
        if not str(m.get("tool", "")).endswith("cdb_emit.py"):
            fail(f"{fn}: tool field {m.get('tool')}")
        if sn not in CENSUS:
            fail(f"{fn}: sourceSheet {sn} not in census table")
            continue
        sheet = V.sheets[sn]
        raw_lines = sheet.get("lines", [])
        if m.get("rowCount") != len(raw_lines):
            fail(f"{fn}: _meta.rowCount {m.get('rowCount')} != sheet {len(raw_lines)}")
        if len(rows) != CENSUS[sn]:
            fail(f"{fn}: {len(rows)} rows != census {CENSUS[sn]}")
        if len(rows) != len(raw_lines):
            fail(f"{fn}: {len(rows)} rows != source lines {len(raw_lines)}")
        # column schema block equals CDB declaration
        want_cols = [{"name": c["name"], "typeStr": str(c.get("typeStr")),
                      "opt": bool(c.get("opt")), "kind": c.get("kind")}
                     for c in sheet.get("columns", [])]
        if m.get("columns") != want_cols:
            fail(f"{fn}: _meta.columns diverge from CDB schema")
        idc = next((c["name"] for c in sheet.get("columns", [])
                    if code_of(c.get("typeStr", "")) == "0"), None)
        keyrule = m.get("keyRule")
        if (idc is None) != bool(keyrule):
            fail(f"{fn}: keyRule presence {bool(keyrule)} contradicts "
                 f"native id col {idc}")
        edges = []
        for i, (rl, er) in enumerate(zip(raw_lines, rows)):
            tid = synth_id(kind if keyrule else None, i, rl, idc) \
                if keyrule else rl[idc]
            if keyrule:
                if er.get("id") != tid:
                    fail(f"{fn} row {i}: synthetic id {er.get('id')!r} != "
                         f"rule {tid!r}")
            V.check(sn, rl, er, kind, tid, "", edges)
            # collect textKey sheet coverage
            def scan(o):
                if isinstance(o, dict):
                    tk = o.get("textKey")
                    if isinstance(tk, dict):
                        textkey_sheets[(tk.get("sheet"), bool(tk.get("subSheet")))] += 1
                    for v in o.values():
                        scan(v)
                elif isinstance(o, list):
                    for v in o:
                        scan(v)
            scan(er)
        total_rows += len(rows)

    # ---- relink ------------------------------------------------------------
    expect = collections.Counter()
    edge_param = {}  # edge key -> exact `6:<sheet[@sub]>` target declaration
    edge_valid = {}  # edge key -> recomputed valid flag (True/False/None)
    # recount edges for EVERY emitted kind by walking its RAW sheet directly
    for kind, sn in seen_kinds.items():
        sheet = V.sheets.get(sn, {})
        idc = next((c["name"] for c in sheet.get("columns", [])
                    if code_of(c.get("typeStr", "")) == "0"), None)
        keyrule = idc is None

        def walk_raw(ssn, ro, tid, path):
            for c in V.schema(ssn):
                ts = str(c.get("typeStr"))
                v = ro.get(c["name"])
                if v is None:
                    continue
                if code_of(ts) == "6":
                    yield (ts, (kind, param_of(ts).split("@")[0].split(".")[0],
                                path + c["name"], tid, v))
                elif code_of(ts) == "8":
                    for sr in v:
                        yield from walk_raw(f"{ssn}@{c['name']}", sr, tid,
                                            f"{path}{c['name']}[].")
        for i, l in enumerate(sheet.get("lines", [])):
            tid = l["place"] if (keyrule and kind == "frescos") else (
                f"{kind}-{i:04d}" if keyrule else l[idc])
            for ts, e in walk_raw(sn, l, tid, ""):
                expect[e] += 1
                prev = edge_param.setdefault(e, ts)
                if prev != ts:
                    fail(f"edge {e} declared as both {prev} and {ts}")
                # recomputed validity from the exact declaration
                tgt = V.sheets.get(param_of(ts))
                tlines = tgt.get("lines") if tgt else None
                if not tlines:
                    w = None
                else:
                    idc2 = next((c["name"] for c in tgt.get("columns", [])
                                 if code_of(c.get("typeStr", "")) == "0"), None)
                    w = e[4] in ({r2[idc2] for r2 in tlines} if idc2 else set())
                edge_valid.setdefault(e, w)

    got = collections.Counter()
    dangling = 0
    unverifiable = 0
    # Hole-1 name rule (spec §10): a reldir file is a pair file iff its name
    # matches <kind>__<kind>.jsonl; anything else (locale_availability.jsonl,
    # the non-pair poi_coordinates.jsonl orphan, ...) is skipped + enumerated.
    all_rel = sorted(fn for fn in os.listdir(reldir) if fn.endswith(".jsonl"))
    rel_files = [fn for fn in all_rel if wave_kinds.is_pair_name(fn)]
    skipped_rel = [fn for fn in all_rel if not wave_kinds.is_pair_name(fn)]
    per_file = {}
    for fn in rel_files:
        p = os.path.join(reldir, fn)
        with open(p, "r", encoding="utf-8", errors="strict") as g:
            glines = g.read().splitlines()
        rm = json.loads(glines[0]).get("_meta", {})
        es = [json.loads(x) for x in glines[1:]]
        # R5: §3.6 equality holds on BOTH planes — pair files carry
        # _meta.buildId too, mirrored on the dataset check above.
        if rm.get("buildId") != buildid:
            fail(f"relinks/{fn}: buildId {rm.get('buildId')} != required "
                 f"{buildid}")
        if rm.get("edges") != len(es):
            fail(f"relinks/{fn}: _meta.edges {rm.get('edges')} != {len(es)}")
        pair = fn[:-6]
        per_file[pair] = len(es)
        for e in es:
            key = (rm["fromKind"], rm["toKind"], e["column"], e["fromId"],
                   e["toId"])
            got[key] += 1
            if e.get("valid") is False:
                dangling += 1
            elif e.get("valid") is None:
                unverifiable += 1
            if e.get("mechanism") != "hard":
                fail(f"relinks/{fn}: mechanism {e.get('mechanism')}")

    # F6-tool (§3.3/§4.4 gate): any positive dangling count FAILS the
    # verifier — a source-authoring dangling edge never ships through this
    # gate green.
    if dangling:
        fail(f"pack-wide dangling invariant: {dangling} != 0")

    if got != expect:
        miss = expect - got
        over = got - expect
        for k, n in list(miss.items())[:10]:
            fail(f"relink MISSING edge {k} x{n}")
        for k, n in list(over.items())[:10]:
            fail(f"relink UNEXPECTED edge {k} x{n}")
        if len(miss) > 10 or len(over) > 10:
            fail(f"relink multiset diff: {len(miss)} missing / {len(over)} "
                 "unexpected distinct keys")

    # valid-flag audit — per-edge, against the recomputed declaration table.
    # Multiset equality (got==expect) is asserted below; here every emitted
    # edge's flag must equal the independently recomputed one. To pair them,
    # rescan the files once more keyed the same way.
    bad_valid = 0
    for fn in rel_files:
        with open(os.path.join(reldir, fn), "r", encoding="utf-8") as g:
            glines = g.read().splitlines()
        rm = json.loads(glines[0])["_meta"]
        for x in glines[1:]:
            e = json.loads(x)
            key = (rm["fromKind"], rm["toKind"], e["column"], e["fromId"],
                   e["toId"])
            want = edge_valid.get(key, "??")
            if want != "??" and e.get("valid") != want:
                bad_valid += 1
                fail(f"relinks/{fn}: {e['fromId']}->{e['toId']} valid="
                     f"{e.get('valid')} recomputed {want}")

    # ---- dig-log wave-1 totals cross-check ---------------------------------
    for pair, n in DIG1_EDGES.items():
        if per_file.get(pair) != n:
            fail(f"dig-log reconciliation: {pair}={per_file.get(pair)} "
                 f"!= recorded {n}")

    # ---- bridge coverage ----------------------------------------------------
    bridge = set()
    bp = "extracted/harvest/_lang-bridge/export_en.xml"
    if os.path.exists(bp):
        root = ET.parse(bp).getroot()
        bridge = {c.get("name") for c in root if c.tag == "sheet"}
    covered = sorted({s for (s, _ss) in textkey_sheets if s in bridge})
    absent = sorted({s for (s, _ss) in textkey_sheets if s not in bridge})

    # ---- report -------------------------------------------------------------
    if skipped_data:
        print(f"datasets skipped (outside managed universe): "
              f"{len(skipped_data)} -> {', '.join(skipped_data)}")
    if skipped_rel:
        print(f"relink skipped (not <from>__<to>.jsonl): "
              f"{len(skipped_rel)} -> {', '.join(skipped_rel)}")
    print(f"datasets verified : {len(files)} files, {total_rows} rows "
          f"(census sum over their sheets: "
          f"{sum(CENSUS[s] for s in seen_kinds.values())})")
    print(f"relink files      : {len(rel_files)}, edges {sum(got.values())} "
          f"(expected {sum(expect.values())}), dangling {dangling}, "
          f"unverifiable {unverifiable}, valid-flag mismatches {bad_valid}")
    print(f"textKey sheets in en bridge ({len(bridge)} sheets): covered "
          f"{len(covered)} -> {', '.join(covered) if covered else '-'}")
    print(f"textKey sheets NOT in bridge (drift ledger): {len(absent)} -> "
          f"{', '.join(absent) if absent else '-'}")
    print(f"undeclared payload keys preserved verbatim: "
          f"{V.extra_preserved}")
    if problems:
        print(f"\nFAILURES: {len(problems)}")
        for x in problems[:60]:
            print("  -", x)
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main(sys.argv)
