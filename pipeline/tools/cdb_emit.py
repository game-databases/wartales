#!/usr/bin/env python3
"""cdb_emit.py — emit the Wartales data dig's first canonical datasets +
relink seed edges from res.pak:/data.cdb.

Waves (selected with --wave):
  wave1  item <- `item`, skill <- `skill`, class <- `unitClass`
         (the three clearest kinds by census evidence)
  wave2  every remaining top-level sheet with inline rows — 37 datasets;
         `craft` emits under its spec kind name `recipe`; `constant` is
         NOT re-emitted (already `extracted/logic/constants.jsonl`,
         dig 2); the four datafile-backed sheets (`place`,`group`,
         `element`,`levelProps`) stay deferred pending HBSON decode.

Sheets with no `"0"` id column (`frescos`, `env`, `craft`) get a
synthetic `id`: `frescos` keys on its unique `place` ref; `env`/`craft`
take a zero-padded row ordinal (`<kind>-NNNN`). The rule is recorded in
each `_meta.keyRule`; original columns are never renamed or replaced.

Emission rules (dig brief):
  - one JSONL row per entity, ALL original columns preserved under
    original names, identifiers never stripped;
  - `id` = the sheet's stable identifier column value;
  - localizable text cells become structured references
    `{"textKey": {bridge, sheet, column, row}}` — prose stays in the
    lang bridge (parsed by the next dig);
  - `_meta` first line: source sheet, buildid, row count, timestamp,
    column types, enum/flags case tables;
  - every populated `6:<sheet>` reference cell emits a relink edge
    (fromId, toId, column, mechanism="hard") into
    extracted/relinks/_draft/<kindA>__<kindB>.jsonl, walked recursively
    through list sub-rows; dangling refs counted, never dropped.

Usage: python cdb_emit.py <data.cdb> [--wave wave1|wave2]
                          [--outdir DIR] [--reldir DIR]
                          [--buildid ID]   (default 20318128, spec §3.6)
"""
import json
import sys
import os
import datetime
import collections

BUILD_ID = "20318128"

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

KINDS = WAVES["wave1"]  # kept for backward compatibility

# census typeStr codes (verified in cdb_census.py header)
def code_of(ts):
    return str(ts).partition(":")[0]

def param_of(ts):
    return str(ts).partition(":")[2] or None


class Emitter:
    def __init__(self, db):
        self.db = db
        self.sheets = {s["name"]: s for s in db["sheets"]}
        self.custom_types = {t["name"]: t for t in db["customTypes"]}
        self.edges = collections.defaultdict(list)
        self.edge_dangling = collections.Counter()
        self.extra_keys = collections.Counter()  # undeclared payload keys kept
        self.id_sets = {}  # sheet -> set of ids

        # register ids of every sheet with inline lines (ref validation)
        for name, s in self.sheets.items():
            col0 = None
            for c in s.get("columns", []):
                if code_of(c.get("typeStr", "")) == "0":
                    col0 = c["name"]
                    break
            if col0 is not None:
                self.id_sets[name] = {
                    l[col0] for l in s.get("lines", []) if l.get(col0) is not None
                }

    def schema(self, sheet_name):
        return self.sheets.get(sheet_name, {}).get("columns", [])

    def id_col(self, sheet_name):
        """Name of the sheet's `"0"` (id) column, or None if it has none."""
        for c in self.schema(sheet_name):
            if code_of(c.get("typeStr", "")) == "0":
                return c["name"]
        return None

    def row_ids(self, kind, sheet_name, lines):
        """Stable key per row. Native `"0"` column when the sheet has one;
        otherwise a documented synthetic rule (never replaces a real
        identifier — these sheets simply carry none)."""
        col = self.id_col(sheet_name)
        if col is not None:
            return [(l[col], None) for l in lines], None
        if kind == "frescos":  # unique `place` ref is the native key
            rule = "synthetic: id = row's unique `place` ref (sheet has no id column)"
            return [(l["place"], rule) for l in lines], rule
        rule = (f"synthetic: zero-padded row ordinal — sheet `{sheet_name}` "
                "has no id column")
        return [(f"{kind}-{i:04d}", rule) for i, l in enumerate(lines)], rule

    def resolve_enum(self, ts):
        """Return the ordered case-name list for an enum/flags column."""
        code, param = code_of(ts), param_of(ts)
        if code == "9":
            ct = self.custom_types.get(param)
            if ct:
                return [c["name"] for c in ct.get("cases", [])]
            return None
        if code in ("5", "10"):
            return param.split(",") if param else None
        return None

    def walk(self, sheet_name, row, top_id, top_kind, path):
        """Recursively transform a row against its schema; collect edges."""
        out = {}
        for c in self.schema(sheet_name):
            name = c["name"]
            ts = str(c.get("typeStr"))
            code = code_of(ts)
            if name not in row or row[name] is None:
                continue  # opt/null cells omitted; schema lives in _meta
            v = row[name]
            if code == "1" and c.get("kind") == "localizable":
                out[name] = {"textKey": {
                    "bridge": "lang/export_<locale>.xml",
                    "sheet": sheet_name.split("@")[0],
                    "column": name,
                    "row": top_id,
                    "subSheet": sheet_name if "@" in sheet_name else None,
                }}
                # strip the None subSheet for top-level sheets
                if out[name]["textKey"]["subSheet"] is None:
                    del out[name]["textKey"]["subSheet"]
            elif code == "6":
                tgt_root = param_of(ts).split("@")[0].split(".")[0]
                out[name] = v
                tgt_lines = self.sheets.get(param_of(ts), {}).get("lines")
                if tgt_lines:
                    # inline rows exist — strict membership check
                    ok = v in self.id_sets.get(param_of(ts), set())
                else:
                    # hidden sub-sheet or datafile-backed root (place/group/
                    # element/levelProps): id registry lives outside CDB —
                    # unverifiable inline, never counted dangling
                    ok = None
                self.edges[(top_kind, tgt_root)].append({
                    "fromId": top_id,
                    "toId": v,
                    "column": path + name,
                    "mechanism": "hard",
                    "valid": ok,
                })
            elif code == "8":
                sub = f"{sheet_name}@{name}"
                out[name] = [self.walk(sub, sr, top_id, top_kind,
                                       f"{path}{name}[].")
                             for sr in v]
            else:
                out[name] = v
        # CastleDB rows may carry keys OUTSIDE their sheet's declared schema
        # (authoring flags like `__ignoreLoc__`, leftover sub-data). Schema-
        # driven emission would silently drop them — preserve verbatim.
        known = {c["name"] for c in self.schema(sheet_name)}
        for k, v in row.items():
            if k not in known and k not in out and v is not None:
                out[k] = v
                self.extra_keys[f"{sheet_name}@{k}"] += 1
        return out


def main(argv):
    src = argv[1]

    def opt(a, default=None):
        return argv[argv.index(a) + 1] if a in argv else default

    wave = opt("--wave", "wave1")
    if wave not in WAVES:
        sys.exit(f"unknown wave {wave!r}; known: {', '.join(WAVES)}")
    # spec-stages-datasets §3.6: buildid is a flag (default keeps every
    # recorded output valid); a patch rerun stamps the NEW id, never the old
    buildid = opt("--buildid", BUILD_ID)
    kinds = WAVES[wave]
    outdir = opt("--outdir", "extracted/data/_draft")
    reldir = opt("--reldir", "extracted/relinks/_draft")
    os.makedirs(outdir, exist_ok=True)
    os.makedirs(reldir, exist_ok=True)

    with open(src, "r", encoding="utf-8") as f:
        db = json.load(f)

    em = Emitter(db)
    now = datetime.datetime.now().isoformat(timespec="seconds")
    summary = []

    for kind, sheet_name in kinds:
        sheet = em.sheets[sheet_name]
        lines = sheet.get("lines", [])
        cols = em.schema(sheet_name)
        ids, key_rules = em.row_ids(kind, sheet_name, lines)
        assert len({i for i, _ in ids}) == len(ids), \
            f"{sheet_name}: duplicate stable ids"
        meta = {
            "_meta": {
                "kind": kind,
                "sourceSheet": sheet_name,
                "buildId": buildid,
                "container": "res.pak:/data.cdb (CastleDB JSON, compress=false)",
                "rowCount": len(lines),
                "emitted": now,
                "tool": "pipeline/tools/cdb_emit.py",
                "localeTextRoute": "lang/export_<locale>.xml via textKey refs; "
                                   "leaf addressing pinned by next dig",
                "enums": {},
                "columns": [
                    {"name": c["name"], "typeStr": str(c.get("typeStr")),
                     "opt": bool(c.get("opt")), "kind": c.get("kind")}
                    for c in cols
                ],
            }
        }
        if key_rules:
            # only id-less sheets carry the note (wave-1 shape untouched)
            meta["_meta"]["keyRule"] = key_rules
        for c in cols:
            cases = em.resolve_enum(str(c.get("typeStr")))
            if not cases:
                continue
            en = meta["_meta"]["enums"]
            if c["name"] in en and en[c["name"]] != cases:
                en[f"{sheet_name}@{c['name']}"] = cases  # disambiguate clash
            else:
                en[c["name"]] = cases

        rows = [em.walk(sheet_name, l, i, kind, "")
                for l, (i, _) in zip(lines, ids)]
        if em.id_col(sheet_name) is None:
            # additive stable key on id-less sheets — originals untouched
            for r, (i, _) in zip(rows, ids):
                r_cp = {"id": i}
                r_cp.update(r)
                r.clear()
                r.update(r_cp)

        out_path = os.path.join(outdir, f"{kind}.jsonl")
        with open(out_path, "w", encoding="utf-8", newline="\n") as g:
            g.write(json.dumps(meta, ensure_ascii=False) + "\n")
            for r in rows:
                g.write(json.dumps(r, ensure_ascii=False) + "\n")
        summary.append((kind, sheet_name, len(rows), out_path))

    # ---- relink seeds ------------------------------------------------------
    rel_summary = []
    for (ka, kb), edges in sorted(em.edges.items()):
        p = os.path.join(reldir, f"{ka}__{kb}.jsonl")
        with open(p, "w", encoding="utf-8", newline="\n") as g:
            g.write(json.dumps({
                "_meta": {"fromKind": ka, "toKind": kb, "mechanism": "hard",
                          "buildId": buildid, "edges": len(edges),
                          "emitted": now,
                          "note": "valid:true verified against target sheet ids; "
                                  "valid:null target has no inline lines "
                                  "(hidden/datafile-backed); valid:false dangling"}
            }, ensure_ascii=False) + "\n")
            for e in edges:
                g.write(json.dumps(e, ensure_ascii=False) + "\n")
        dangle = sum(1 for e in edges if e["valid"] is False)
        unv = sum(1 for e in edges if e["valid"] is None)
        rel_summary.append((f"{ka}__{kb}", len(edges), dangle, unv))

    print("datasets:")
    for k, sh, n, p in summary:
        print(f"  {k:<6} <- {sh:<10} {n:>5} rows -> {p}")
    print(f"relink seeds: {len(rel_summary)} files")
    tot = sum(n for _, n, _, _ in rel_summary)
    dtot = sum(d for *_, d, _ in rel_summary)
    utot = sum(u for *_, u in rel_summary)
    for name, n, d, u in sorted(rel_summary, key=lambda x: -x[1]):
        flag = f" DANGLING={d}" if d else ""
        flag += f" UNVERIFIABLE={u}" if u else ""
        print(f"  {name:<28} {n:>6} edges{flag}")
    print(f"total edges={tot} dangling={dtot} unverifiable={utot}")

    # content-status distribution for the cut-content ledger
    done = collections.Counter(
        l.get("done") for l in em.sheets["item"].get("lines", []))
    print("item.done distribution (enum TODO,Coded,Ok,Wait):", dict(done))
    if em.extra_keys:
        print("undeclared payload keys preserved verbatim:",
              dict(em.extra_keys.most_common()))


if __name__ == "__main__":
    main(sys.argv)
