#!/usr/bin/env python3
"""relink_catalog.py — stage 5: derive the honest ordered-pair catalog from
the CANONICAL bytes (spec-stages-datasets §4.2).

  python relink_catalog.py [--datadir extracted/data] [--reldir extracted/relinks]
      [--bridge extracted/harvest/_lang-bridge/export_en.xml]
      [--out-md extracted/RELATIONS.md] [--out-json extracted/relinks/matrix.json]

Outputs:
  - extracted/relinks/matrix.json — machine-readable: one record per
    unordered kind pair {a, b, forward, reverse, unblock} ({a,b} stored
    lexicographic by kind name; forward = a→b), plus self-pair records
    (kind↔itself files — outside the C(40,2) space) and deferred-target-pair
    records (targets outside the 40 managed kinds).
  - extracted/RELATIONS.md — human catalog rendered FROM matrix.json.

Stamp policy (arbiter F9): NO wall-clock `generated` anywhere — both files
are derived DATA artifacts whose content is a pure function of the canonical
bytes, so rerunning stage 5 twice yields byte-identical output. The run
REPORTS (validation-report.{json,md}) keep their stamp deliberately.

Status vocabulary (spec §4.3, frozen):
  modeled   canonical pair file exists for this direction with >=1 edge;
  partial   family evidenced (reverse modeled / reference-free source kind /
            schema-declared ref column) but this direction uncovered;
  missing   no evidence either way. Every non-modeled direction carries
            exactly one unblock pointer.
"""
import argparse
import hashlib
import json
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wave_kinds  # noqa: E402

UPGRADE = "ordered-pair upgrade dig"
R3 = "R3"

# Dig-7 adjudication freeze (spec §4.4): file base -> unverifiableBefore.
# Regeneration drops the as-found `verifiedBy` stamps every run BY DESIGN,
# so the adjudication is carried HERE beside the regeneration-honest null
# flag until id registries enter the pipeline (wave 3, unblock R1). Growth
# AND shrinkage of these counts is drift -> exit 1 (re-freeze procedure,
# EXTRACTION-LOG §5).
D7_LEDGER = {
    "env__place": 61,
    "frescos__place": 9,
    "fiefGoal__element": 2,
}
D7_TEXT = ("verifiedBy: Dig D7 (hbson_emit.py) against the decoded HBON id "
           "set; allEdgesVerifiedTrue: true")


def die(msg, code=2):
    print("ERROR: " + msg)
    sys.exit(code)


def read_meta_and_rows(path):
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    meta = json.loads(lines[0]).get("_meta", {})
    return meta, lines[1:]


def cardinality(edges, n_from, n_to):
    if n_from == edges and n_to < edges:
        return "many:1"
    if n_to == edges and n_from < edges:
        return "1:many"
    if n_from == edges == n_to:
        return "1:1"
    return "many:many"


def aggregate(pair_path):
    """-> per-direction aggregates from one canonical pair file."""
    meta, rows = read_meta_and_rows(pair_path)
    agg = {"file": os.path.basename(pair_path),
           "rawFrom": meta.get("fromKind"), "rawTo": meta.get("toKind"),
           "edges": 0, "fromIds": set(), "toIds": set(), "joinKeys": set(),
           "mechanism": set(), "valid": {"true": 0, "false": 0, "null": 0}}
    for r in rows:
        e = json.loads(r)
        agg["edges"] += 1
        agg["fromIds"].add(e.get("fromId"))
        agg["toIds"].add(e.get("toId"))
        agg["joinKeys"].add(e.get("column"))
        agg["mechanism"].add(e.get("mechanism"))
        v = e.get("valid")
        key = "true" if v is True else ("false" if v is False else "null")
        agg["valid"][key] += 1
    return agg


def render_direction(rec):
    if rec["status"] == "modeled":
        keys = ", ".join(rec["joinKeys"])
        vc = rec["validCounts"]
        return (f"modeled · E={rec['edges']} · card={rec['cardinality']} · "
                f"keys=[{keys}] · mech={'+'.join(rec['mechanism'])} · "
                f"v={vc['true']}/{vc['false']}/{vc['null']}")
    return f"{rec['status']} → {rec['unblock']}"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--datadir", default="extracted/data")
    ap.add_argument("--reldir", default="extracted/relinks")
    ap.add_argument("--bridge",
                    default="extracted/harvest/_lang-bridge/export_en.xml")
    ap.add_argument("--out-md", dest="out_md", default="extracted/RELATIONS.md")
    ap.add_argument("--out-json", dest="out_json",
                    default="extracted/relinks/matrix.json")
    args = ap.parse_args(argv)

    # -- canonical datasets: exactly the 40 managed kinds (equality) --------
    if not os.path.isdir(args.datadir):
        die(f"canonical data dir missing: {args.datadir} "
            f"(owning stage: run_all.ps1 datasets)")
    files = sorted(f for f in os.listdir(args.datadir) if f.endswith(".jsonl"))
    found = {f[:-6] for f in files}
    missing = sorted(wave_kinds.MANAGED_KINDS - found)
    extra = sorted(found - wave_kinds.MANAGED_KINDS)
    if missing or extra:
        die(f"{args.datadir} does not hold exactly the 40 managed kinds "
            f"(owning stage: run_all.ps1 datasets); missing: {missing}; "
            f"unexpected: {extra}")
    datasets = {}
    buildids = set()
    top_ref_kinds = set()
    for fn in files:
        meta, rows = read_meta_and_rows(os.path.join(args.datadir, fn))
        datasets[fn[:-6]] = {"meta": meta, "rows": rows}
        buildids.add(meta.get("buildId"))
        if any(str(c.get("typeStr", "")).startswith("6:")
               for c in meta.get("columns", [])):
            top_ref_kinds.add(fn[:-6])
    if len(buildids) > 1:
        die(f"canonical datasets carry divergent buildIds: {sorted(buildids)}")
    buildid = next(iter(buildids)) if buildids else None

    # -- canonical pair files -------------------------------------------------
    all_rel = sorted(f for f in os.listdir(args.reldir)
                     if f.endswith(".jsonl")) \
        if os.path.isdir(args.reldir) else []
    pair_names = [f for f in all_rel if wave_kinds.is_pair_name(f)]
    skipped_rel = [f for f in all_rel if not wave_kinds.is_pair_name(f)]

    directions = {}          # (kindFrom, kindTo) -> aggregate, x != y
    self_pairs = []          # kind == same kind
    deferred_targets = []    # toKind outside the managed universe
    tot_edges = tot_true = tot_false = tot_null = 0
    for fn in pair_names:
        agg = aggregate(os.path.join(args.reldir, fn))
        kf = wave_kinds.SHEET_TO_KIND.get(agg["rawFrom"], agg["rawFrom"])
        kt = wave_kinds.SHEET_TO_KIND.get(agg["rawTo"], agg["rawTo"])
        tot_edges += agg["edges"]
        tot_true += agg["valid"]["true"]
        tot_false += agg["valid"]["false"]
        tot_null += agg["valid"]["null"]
        rec = {
            "file": fn, "joinKeys": sorted(agg["joinKeys"]),
            "edges": agg["edges"],
            "cardinality": cardinality(agg["edges"], len(agg["fromIds"]),
                                       len(agg["toIds"])),
            "mechanism": sorted(m for m in agg["mechanism"] if m),
            "validCounts": agg["valid"],
        }
        if kf == kt:
            self_pairs.append({"kind": kf, **rec})
        elif kt not in wave_kinds.MANAGED_KINDS:
            frozen = D7_LEDGER.get(fn[:-6])
            if frozen is not None and agg["valid"]["null"] != frozen:
                die(f"unverifiable ledger drift for {fn}: measured "
                    f"valid:null={agg['valid']['null']} != frozen "
                    f"{frozen} - re-freeze per EXTRACTION-LOG §5", code=1)
            state = ("dig-adjudicated pending wiring"
                     if frozen else "unknown")
            deferred_targets.append({
                "fromKind": kf, "target": agg["rawTo"], **rec,
                "state": state, "unblock": "R1",
                "adjudication": D7_TEXT if frozen else "-"})
        else:
            directions[(kf, kt)] = rec
    del skipped_rel  # counted by cdb_verify's scan report; not catalog input

    # kinds that demonstrably carry hard references anywhere (any target,
    # incl. itself and deferred targets) — feeds the reference-free test
    outbound_kinds = {}
    for kf, kt in directions:
        outbound_kinds.setdefault(kf, set()).add(kt)
    for r in self_pairs:
        outbound_kinds.setdefault(r["kind"], set()).add(r["kind"])
    for r in deferred_targets:
        outbound_kinds.setdefault(r["fromKind"], set()).add(r["target"])

    def direction_record(x, y):
        got = directions.get((x, y))
        # R11 / spec §4.3: `modeled` requires >=1 edge — a zero-edge pair
        # file is evidence-less and falls through the ladder below (carrying
        # its unblock), never renders modeled.
        if got is not None and got["edges"] > 0:
            return {"status": "modeled", "joinKeys": got["joinKeys"],
                    "edges": got["edges"], "cardinality": got["cardinality"],
                    "mechanism": got["mechanism"],
                    "validCounts": got["validCounts"], "unblock": None}
        if (y, x) in directions:                      # reverse-modeled family
            return {"status": "partial", "joinKeys": [], "edges": 0,
                    "cardinality": None, "mechanism": [],
                    "validCounts": {"true": 0, "false": 0, "null": 0},
                    "unblock": UPGRADE}
        refs_anywhere = bool(outbound_kinds.get(x))
        if not refs_anywhere and x not in top_ref_kinds:
            # generalized skill__* rule (spec §4.3, Dig 1 finding 4): the
            # kind emits zero hard references anywhere - its relations live
            # in code, not data
            return {"status": "partial", "joinKeys": [], "edges": 0,
                    "cardinality": None, "mechanism": [],
                    "validCounts": {"true": 0, "false": 0, "null": 0},
                    "unblock": R3}
        if x in top_ref_kinds:                        # schema names the family
            status = "partial"
        else:                                         # no evidence either way
            status = "missing"
        return {"status": status, "joinKeys": [], "edges": 0,
                "cardinality": None, "mechanism": [],
                "validCounts": {"true": 0, "false": 0, "null": 0},
                "unblock": UPGRADE}

    kinds = sorted(wave_kinds.MANAGED_KINDS)
    pairs = []
    modeled_directions = 0
    for i, a in enumerate(kinds):
        for b in kinds[i + 1:]:
            fwd = direction_record(a, b)
            rev = direction_record(b, a)
            modeled_directions += (fwd["status"] == "modeled") + \
                                  (rev["status"] == "modeled")
            pairs.append({"a": a, "b": b, "forward": fwd, "reverse": rev,
                          "unblock": fwd["unblock"] or rev["unblock"]})

    # -- textKey coverage vs the en bridge ------------------------------------
    used_sheets = set()

    def scan_tk(o):
        if isinstance(o, dict):
            tk = o.get("textKey")
            if isinstance(tk, dict) and tk.get("sheet"):
                used_sheets.add(tk["sheet"])
            for v in o.values():
                scan_tk(v)
        elif isinstance(o, list):
            for v in o:
                scan_tk(v)

    for d in datasets.values():
        for r in d["rows"]:
            scan_tk(json.loads(r))
    if not os.path.isfile(args.bridge):
        die(f"en bridge missing: {args.bridge} (harvest output)")
    bridge_sheets = {c.get("name") for c in ET.parse(args.bridge).getroot()
                     if c.tag == "sheet"}
    covered = sorted(s for s in used_sheets if s in bridge_sheets)
    absent = sorted(s for s in used_sheets if s not in bridge_sheets)

    matrix = {
        "buildId": buildid,
        "kindCount": len(kinds),
        "pairCount": len(pairs),
        "totals": {
            "files": len(pair_names), "edges": tot_edges,
            "validTrue": tot_true, "validFalse": tot_false,
            "validNull": tot_null,
            "modeledDirections": modeled_directions,
            "orderedDirections": len(kinds) * (len(kinds) - 1),
            "selfPairFiles": len(self_pairs),
            "deferredTargetFiles": len(deferred_targets),
        },
        "pairs": pairs,
        "selfPairs": sorted(self_pairs, key=lambda r: r["kind"]),
        "deferredTargetPairs": sorted(deferred_targets,
                                      key=lambda r: r["file"]),
        "textKeyCoverage": {
            "usedSheets": len(used_sheets), "bridgeSheets": len(bridge_sheets),
            "covered": covered, "driftAbsent": absent,
        },
    }
    os.makedirs(os.path.dirname(args.out_json) or ".", exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8", newline="\n") as g:
        g.write(json.dumps(matrix, ensure_ascii=False, indent=1) + "\n")

    with open(args.out_json, "rb") as f:
        matrix_sha = hashlib.sha256(f.read()).hexdigest()
    write_relations_md(args.out_md, matrix, matrix_sha)
    print(f"catalog: {len(pairs)} unordered pairs "
          f"({modeled_directions} modeled directions of "
          f"{matrix['totals']['orderedDirections']}), "
          f"{len(self_pairs)} self-pair files, "
          f"{len(deferred_targets)} deferred-target files")
    print(f"totals: files={len(pair_names)} edges={tot_edges} "
          f"dangling={tot_false} unverifiable={tot_null}")
    print(f"wrote {args.out_json} (sha256 {matrix_sha[:16]}...) + {args.out_md}")
    return 0


def write_relations_md(out_md, m, matrix_sha):
    L = []
    w = L.append
    t = m["totals"]
    w("# Wartales — RELATIONS.md (relink catalog)")
    w("")
    w("Derived DATA artifact: rendered by `pipeline/tools/relink_catalog.py`")
    w("from the canonical bytes of `extracted/data/*.jsonl` +")
    w("`extracted/relinks/*.jsonl`. No wall-clock stamp (arbiter F9):")
    w("rerunning stage 5 over the same bytes is byte-identical.")
    w("")
    w(f"- buildId: {m['buildId']}")
    w("- tool: pipeline/tools/relink_catalog.py")
    w(f"- matrix.json sha256: `{matrix_sha}` "
      "(byte-derived parity marker asserted by validate_all `catalog-parity`)")
    w(f"- totals: {t['files']} pair files · {t['edges']:,} edges · "
      f"dangling(valid:false) {t['validFalse']} · "
      f"unverifiable(valid:null) {t['validNull']}")
    w(f"- directions: modeled {t['modeledDirections']}/"
      f"{t['orderedDirections']} · self-pair files {t['selfPairFiles']} · "
      f"deferred-target files {t['deferredTargetFiles']}")
    tkc = m["textKeyCoverage"]
    w(f"- textKey coverage: {len(tkc['covered'])}/{tkc['usedSheets']} emitted "
      f"sheets in the en bridge ({tkc['bridgeSheets']} sheets), "
      f"drift-absent {len(tkc['driftAbsent'])}")
    w("- Relation chains M1–M8/E1–E8 (COMP §7 applied delta): cross-referenced")
    w("  from [spec.md `relations`](../spec.md), not re-done here "
      "(spec-stages-datasets §4.3).")
    w("")
    w("## Modeled-pair index")
    w("")
    w("| pair | direction | join keys | edges | cardinality | mechanism | "
      "valid true/false/null |")
    w("|---|---|---|---:|---|---|---|")

    def index_row(pair_label, direction_label, rec, note=""):
        vc = rec["validCounts"]
        w(f"| {pair_label}{note} | {direction_label} | "
          f"`{', '.join(rec['joinKeys'])}` | {rec['edges']} | "
          f"{rec['cardinality']} | {'+'.join(rec['mechanism'])} | "
          f"{vc['true']}/{vc['false']}/{vc['null']} |")

    for p in m["pairs"]:
        for side, label in (("forward", p["a"] + "→" + p["b"]),
                            ("reverse", p["b"] + "→" + p["a"])):
            rec = p[side]
            if rec["status"] == "modeled":
                index_row(f"`{p['a']}–{p['b']}`", label, rec)
    for r in m["selfPairs"]:
        index_row(f"`{r['kind']}–{r['kind']}`", "self", r)
    for r in m["deferredTargetPairs"]:
        index_row(f"`{r['fromKind']}–{r['target']}`",
                  f"{r['fromKind']}→{r['target']}", r,
                  note=f" (deferred target `{r['target']}`)")
    w("")
    w(f"## Full matrix — {m['pairCount']} unordered pairs × both directions")
    w("")
    w("One row per unordered pair `{a, b}` (lexicographic; forward = a→b),")
    w("grouped under its from-kind `a`. Cell: `status → unblock` for")
    w("non-modeled directions; full detail when modeled.")
    current_a = None
    for p in m["pairs"]:
        if p["a"] != current_a:
            current_a = p["a"]
            w("")
            w(f"### a = `{current_a}`")
            w("")
            w(f"| {current_a}–b | {current_a}→b | b→{current_a} | unblock |")
            w("|---|---|---|---|")
        w(f"| `{p['a']}–{p['b']}` | {render_direction(p['forward'])} | "
          f"{render_direction(p['reverse'])} | {p['unblock']} |")
    w("")
    w("## Self-pairs (kind ↔ itself)")
    w("")
    if m["selfPairs"]:
        w("| kind | file | join keys | edges | cardinality | mechanism | "
          "valid true/false/null |")
        w("|---|---|---|---:|---|---|---|")
        for r in m["selfPairs"]:
            vc = r["validCounts"]
            w(f"| {r['kind']} | `{r['file']}` | "
              f"`{', '.join(r['joinKeys'])}` | {r['edges']} | "
              f"{r['cardinality']} | {'+'.join(r['mechanism'])} | "
              f"{vc['true']}/{vc['false']}/{vc['null']} |")
    w("")
    w("## Unverifiable-edge ledger (valid:null — regeneration-honest flag)")
    w("")
    w("`valid:null` = declared target sheet has no inline lines (hidden")
    w("sub-sheets or datafile-backed roots). Never counted dangling; MUST")
    w("stay enumerated. State is either *unknown* (no evidence yet, unblock")
    w("R1) or *dig-adjudicated pending wiring* — every current entry: Dig 7")
    w("resolved them true against the decoded HBON id set, but regeneration")
    w("drops the stamps each run by design (spec-stages-datasets §4.4), so")
    w("the machine flag stays null until id registries enter the pipeline")
    w("(wave 3).")
    w("")
    w("| pair | file | edges | valid:null | state | unblock | adjudication |")
    w("|---|---|---|---:|---|---|---|")
    for r in m["deferredTargetPairs"]:
        vc = r["validCounts"]
        w(f"| `{r['fromKind']}→{r['target']}` | `{r['file']}` | {r['edges']} | "
          f"{vc['null']} | {r['state']} | {r['unblock']} | "
          f"{r['adjudication']} |")
    w("")
    w("## Dangling policy (valid:false)")
    w("")
    w(f"Dangling count pack-wide: **{t['validFalse']}**. A dangling edge is an")
    w("emitter/verifier disagreement or real authoring drift — never silently")
    w("shipped, downgraded, or dropped; any positive count fails cdb_verify")
    w("(exit 1) and therefore stage 5. Diagnose before rerun.")
    w("")
    w("## Deferred kinds (not promoted by stages 4–6)")
    w("")
    w("| id | kinds | why | unblock |")
    w("|---|---|---|---|")
    for d in wave_kinds.DEFERRED:
        w(f"| {d['id']} | {', '.join(d['kinds'])} | {d['why']} | "
          f"{d['unblock']} |")
    w("")
    with open(out_md, "w", encoding="utf-8", newline="\n") as g:
        g.write("\n".join(L))


if __name__ == "__main__":
    sys.exit(main())
