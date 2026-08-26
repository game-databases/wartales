#!/usr/bin/env python3
"""relink_catalog.py — stage 5: derive the honest ordered-pair catalog from
the CANONICAL bytes (spec-stages-datasets §4.2), plus — since the Dig 16
R10b amendment (arbiter-rule8-gate §2.1) — the verified dig-15 `_logic`
evidence layer beside them.

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

Dig 16 amendment (R10b canonical wiring). When `<reldir>/_logic/` exists
(the dig-15 evidence layer: 107 family files + `_ledger.jsonl`), the
catalog gains ADDITIVE envelope sections — `derivedEvidence{}`, `ledgered`,
`provenance`, new `totals.*` counters, per-direction `evidence` /
`ledgerClass` fields and upgraded `unblock` pointers on wired directions —
WITHOUT touching the canonical edge plane: the hard-modeled pair files stay
byte-identical, so cdb_verify's exact multiset gate over them is unaffected.
Derived directions carry `unblock` = `wired (dig 16): <family>` + an
`evidence` block (family file + sha256 + mechanisms + promotion rule);
ledgered directions carry `unblock` = `ledgered (dig 15): <class>` and stay
OUT of every edge set. Trees without a `_logic/` layer (the synthetic T8/
T12 test worlds) emit exactly the pre-amendment shape. All values remain a
pure function of the scanned bytes.

Stamp policy (arbiter F9): NO wall-clock `generated` anywhere — both files
are derived DATA artifacts whose content is a pure function of the canonical
bytes, so rerunning stage 5 twice yields byte-identical output. The run
REPORTS (validation-report.{json,md}) keep their stamp deliberately.

Status vocabulary (spec §4.3, frozen):
  modeled   canonical pair file exists for this direction with >=1 edge;
  partial   family evidenced (reverse modeled / reference-free source kind /
            schema-declared ref column) but this direction uncovered;
  missing   no evidence either way. Every non-modeled direction carries
            exactly one unblock pointer — post-amendment that pointer names
            its resolution (wired family) or its ledger class instead of a
            future dig token.
"""
import argparse
import collections
import hashlib
import json
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wave_kinds  # noqa: E402

UPGRADE = "ordered-pair upgrade dig"
R3 = "R3"

# -- Dig 16 R10b constants -----------------------------------------------------
LOGIC_SUBDIR = "_logic"          # evidence layer under --reldir
LEDGER_NAME = "_ledger.jsonl"    # bar-1 residue ledger (no _meta line)
LEDGER_DEFERRED_NAME = "_ledger_deferred.jsonl"  # dig-17 below-bar ledger
# dig-17 deferred-kind outbound carriers: sources OUTSIDE the 40-kind
# scaffold whose outbound mass the dig-17 admission rule covers (the dig-15
# rule's clause (4) exclusions, admitted by Dig 17).
DEFERRED_SOURCES = frozenset(
    {"element", "group", "place", "levelProps"})
EVIDENCE_DIG = "dig 15"          # produced the _logic layer
WIRING_DIG = "dig 16"            # wires it into this catalog
ADMISSION_RULE = (
    "data.cdb-declared 6:<target> reference column (top-level sheet or hidden "
    "sub-sheet `A@b@c` chain), >=1 populated value resolving into the target "
    "kind's id set, positive polarity, managed scaffold kinds only — dig-15 "
    "fix-round family-admission rule (FIX_ROUND_CARRIERS in "
    "dig15_logic_edges.py; census proof output/_dig15-fix/p1_census.json)")

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


def load_evidence_layer(reldir, modeled_dirs, self_pair_kinds):
    """-> (families, derived_dirs, fold_dirs) from `<reldir>/_logic/`, or
    (None, None, None) when the evidence layer is absent (synthetic test
    worlds). One family file per ordered direction `<from>__<to>.jsonl`;
    classification mirrors the dig-15 token map: derived (uncovered matrix
    direction), fold (modeled matrix direction gaining extra carriers),
    self-chain / fold-self (kind↔itself, outside the C(40,2) space)."""
    root = os.path.join(reldir, LOGIC_SUBDIR)
    if not os.path.isdir(root):
        return None, None, None
    families = []
    for fn in sorted(os.listdir(root)):
        if not fn.endswith(".jsonl") or fn in (LEDGER_NAME,
                                               LEDGER_DEFERRED_NAME):
            # ledgers are residue accounting, never family files
            continue
        path = os.path.join(root, fn)
        with open(path, "rb") as g:
            raw = g.read()
        meta = json.loads(raw.decode("utf-8").splitlines()[0]).get("_meta", {})
        kf = wave_kinds.SHEET_TO_KIND.get(meta.get("fromKind"),
                                          meta.get("fromKind"))
        kt = wave_kinds.SHEET_TO_KIND.get(meta.get("toKind"),
                                          meta.get("toKind"))
        mechs, methods, edges = set(), {}, 0
        for ln in raw.decode("utf-8").splitlines()[1:]:
            if not ln.strip():
                continue
            e = json.loads(ln)
            edges += 1
            if e.get("mechanism"):
                mechs.add(e["mechanism"])
            m = (e.get("method") or "?").split(":")[0]
            methods[m] = methods.get(m, 0) + 1
        if kf == kt:
            kind = "fold-self" if kt in self_pair_kinds else "self-chain"
        elif (kf, kt) in modeled_dirs:
            kind = "fold"
        else:
            kind = "derived"
        families.append({
            "file": f"{LOGIC_SUBDIR}/{fn}", "from": kf, "to": kt,
            "edges": edges, "mechanisms": sorted(mechs),
            "methods": dict(sorted(methods.items())),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "admissionTags": list(meta.get("admissionTags", [])),
            "promotionExpectation": meta.get("promotionExpectation"),
            "cdbDeclarations": list(meta.get("cdbDeclarations", [])),
            "class": kind,
        })
    derived = [f for f in families
               if f["class"] == "derived" and f["from"] not in DEFERRED_SOURCES]
    folds = [f for f in families
             if f["class"] in ("fold", "fold-self")
             and f["from"] not in DEFERRED_SOURCES]
    deferred_src = [f for f in families if f["from"] in DEFERRED_SOURCES]
    return families, derived, folds, deferred_src


def load_ledger(reldir):
    """-> list of bar-1 residue ledger rows (`_ledger.jsonl`, no _meta
    line — every physical line is one ledgered direction), or None."""
    path = os.path.join(reldir, LOGIC_SUBDIR, LEDGER_NAME)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as g:
        rows = [json.loads(x) for x in g.read().splitlines() if x.strip()]
    for r in rows:
        frm, _, to = r["dir"].partition("→")
        r["from"], r["to"] = frm, to
    return rows


def pair_side(pairs_index, x, y):
    """-> (pair record, side key) for direction x→y, or (None, None).
    Pairs are stored {a, b} lexicographic, so normalize before lookup."""
    key = (x, y) if x <= y else (y, x)
    hit = pairs_index.get(key)
    if hit is None:
        return None, None
    a, b, rec = hit
    return rec, ("forward" if a == x else "reverse")


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
    pairs_index = {}
    modeled_directions = 0
    for i, a in enumerate(kinds):
        for b in kinds[i + 1:]:
            fwd = direction_record(a, b)
            rev = direction_record(b, a)
            modeled_directions += (fwd["status"] == "modeled") + \
                                  (rev["status"] == "modeled")
            rec = {"a": a, "b": b, "forward": fwd, "reverse": rev,
                   "unblock": fwd["unblock"] or rev["unblock"]}
            pairs.append(rec)
            pairs_index[(a, b)] = (a, b, rec)

    # -- Dig 16 R10b: wire the dig-15 evidence layer into the catalog --------
    # Canonical EDGE plane untouched; additive envelope sections only.
    families, derived, folds, deferred_src = load_evidence_layer(
        args.reldir, set(directions), {r["kind"] for r in self_pairs})
    ledger_rows = load_ledger(args.reldir)
    wired = {"families": families, "derived": derived, "folds": folds,
             "ledger": ledger_rows}
    if families is not None:
        for fam in derived:
            rec, side = pair_side(pairs_index, fam["from"], fam["to"])
            if rec is None:
                die(f"evidence family {fam['file']} names non-scaffold "
                    f"direction {fam['from']}→{fam['to']}", code=1)
            d = rec[side]
            if d["status"] == "modeled":
                die(f"evidence family {fam['file']} collides with a modeled "
                    f"canonical direction", code=1)
            mechs = "+".join(fam["mechanisms"]) or "-"
            d["unblock"] = (f"wired ({WIRING_DIG}): relinks/{fam['file']} · "
                            f"E={fam['edges']} · mech={mechs}")
            d["evidence"] = {
                "family": f"{LOGIC_SUBDIR}/{os.path.basename(fam['file'])}",
                "sha256": fam["sha256"], "edges": fam["edges"],
                "mechanisms": fam["mechanisms"],
                "promotionExpectation": fam["promotionExpectation"],
            }
            rec["unblock"] = rec["forward"]["unblock"] or \
                rec["reverse"]["unblock"]
        for fam in folds:
            rec, side = pair_side(pairs_index, fam["from"], fam["to"]) \
                if fam["class"] == "fold" else (None, None)
            if fam["class"] == "fold" and rec is None:
                die(f"fold family {fam['file']} names non-scaffold "
                    f"direction {fam['from']}→{fam['to']}", code=1)
            target = rec[side] if rec else None
            entry = {
                "family": f"{LOGIC_SUBDIR}/{os.path.basename(fam['file'])}",
                "sha256": fam["sha256"], "edges": fam["edges"],
                "mechanisms": fam["mechanisms"],
                "promotionExpectation": fam["promotionExpectation"],
                "class": fam["class"],
            }
            if target is not None:
                # additive provenance on the modeled record — the hard join
                # keys / edges / validCounts above stay exactly as measured
                target.setdefault("evidenceFolds", []).append(entry)
            fam["_entry"] = entry
        if ledger_rows is not None:
            seen_dirs = {(f["from"], f["to"]) for f in families}
            for row in ledger_rows:
                x, y = row["from"], row["to"]
                if (x, y) in seen_dirs:
                    die(f"ledger dir {x}→{y} also carries emitted edges "
                        f"(partition violation)", code=1)
                rec, side = pair_side(pairs_index, x, y)
                if rec is None:
                    die(f"ledger dir {x}→{y} outside the managed scaffold",
                        code=1)
                d = rec[side]
                if d["status"] == "modeled" or d.get("evidence"):
                    die(f"ledger dir {x}→{y} collides with a resolved "
                        f"direction", code=1)
                cls = row["unblockClass"]
                d["unblock"] = f"ledgered ({EVIDENCE_DIG}): {cls}"
                d["ledgerClass"] = cls
                rec["unblock"] = rec["forward"]["unblock"] or \
                    rec["reverse"]["unblock"]

    def _method_totals(pool):
        tot = {}
        for fam in pool:
            for m, n in fam["methods"].items():
                tot[m] = tot.get(m, 0) + n
        return dict(sorted(tot.items()))

    # Dig 17: the scaffold-space envelope describes ONLY managed-source
    # families; deferred-source carriers wire into deferredOutbound{} below.
    scaffold_families = [f for f in families or []
                         if f["from"] not in DEFERRED_SOURCES]
    if families is not None and len(scaffold_families) + len(deferred_src) \
            != len(families):
        die("deferred/scaffold family partition broken", code=1)
    ev_methods = _method_totals(scaffold_families) \
        if families is not None else {}
    ev_edges = sum(f["edges"] for f in scaffold_families) \
        if families is not None else 0
    ledger_classes = {}
    if ledger_rows:
        for row in ledger_rows:
            ledger_classes[row["unblockClass"]] = \
                ledger_classes.get(row["unblockClass"], 0) + 1

    def _dir_count(cls):
        return sum(1 for f in scaffold_families if f["class"] == cls)

    if families is not None:
        n_ledgered = sum(ledger_classes.values())
        # envelope consistency (brief §3): every ordered direction resolves to
        # exactly one of modeled / derived-evidence / ledgered.
        ordered_total = len(kinds) * (len(kinds) - 1)
        if modeled_directions + len(derived) + n_ledgered != ordered_total:
            die("envelope inconsistency: modeled + derived + ledgered != "
                "orderedDirections", code=1)
        if len(scaffold_families) != len(derived) + _dir_count("fold") + \
                _dir_count("fold-self") + _dir_count("self-chain"):
            die("evidence family classification does not partition", code=1)
        self_chain_edges = sum(f["edges"] for f in scaffold_families
                               if f["class"] == "self-chain")
        if ev_edges != sum(f["edges"] for f in derived) + \
                sum(f["edges"] for f in folds) + self_chain_edges:
            die("evidence edge total does not reconcile across classes",
                code=1)

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
    if families is not None:
        # Additive Dig 16 amendment: new top-level sections + counters only.
        matrix["totals"].update({
            "evidenceFiles": len(scaffold_families),
            "evidenceEdges": ev_edges,
            "evidenceMethods": ev_methods,
            "derivedDirections": len(derived),
            "foldedModeledDirections": _dir_count("fold"),
            "foldedSelfPairKinds": _dir_count("fold-self"),
            "selfChainFamilies": _dir_count("self-chain"),
            "ledgeredDirections": sum(ledger_classes.values()),
            "ledgerClasses": dict(sorted(ledger_classes.items())),
        })
        matrix["derivedEvidence"] = {
            "sourceDir": f"relinks/{LOGIC_SUBDIR}",
            "evidenceLayer": EVIDENCE_DIG,
            "wiredBy": WIRING_DIG,
            "admissionRule": ADMISSION_RULE,
            "families": len(scaffold_families),
            "edges": ev_edges,
            "methods": ev_methods,
            "directions": [
                {k: f[k] for k in ("from", "to", "edges", "mechanisms",
                                   "methods", "file", "sha256",
                                   "admissionTags", "promotionExpectation",
                                   "cdbDeclarations", "class")}
                for f in sorted(scaffold_families,
                                key=lambda r: (r["from"], r["to"]))
            ],
        }
        # Additive Dig 17 amendment (rider R6): outbound carrier families
        # whose SOURCE is a deferred kind sit OUTSIDE the C(40,2) scaffold
        # space by design — they wire into their own envelope section, never
        # into pairs[]/derivedEvidence wiring.
        matrix["deferredOutbound"] = {
            "sourceDir": f"relinks/{LOGIC_SUBDIR}",
            "producedBy": "dig 17",
            "admissionRule": (
                "dig-17 extension of the dig-15 family-admission rule "
                "(clause (4) deferred sources admitted): data.cdb hidden "
                "sub-sheet 6:<target> declaration OR runtime-registered "
                "CDB-enum namespace in element.script; >=1 populated value "
                "resolving into the target id set; positive polarity; "
                "target has an emitted dataset"),
            "families": len(deferred_src),
            "edges": sum(f["edges"] for f in deferred_src),
            "methods": _method_totals(deferred_src),
            "directions": [
                {k: f[k] for k in ("from", "to", "edges", "mechanisms",
                                   "methods", "file", "sha256",
                                   "admissionTags", "promotionExpectation",
                                   "cdbDeclarations")}
                for f in sorted(deferred_src,
                                key=lambda r: (r["from"], r["to"]))
            ],
        }
        matrix["totals"]["deferredOutboundFamilies"] = len(deferred_src)
        matrix["totals"]["deferredOutboundEdges"] = sum(
            f["edges"] for f in deferred_src)
        matrix["ledgered"] = {
            "sourceFile": f"relinks/{LOGIC_SUBDIR}/{LEDGER_NAME}",
            "rows": sum(ledger_classes.values()),
            "classes": [{"class": c, "directions": n}
                        for c, n in sorted(ledger_classes.items())],
            "edgeSetMembership": "none - ledger rows never become edges "
                                 "(DR bar-1 residue accounting only)",
        }
        ledger_path = os.path.join(args.reldir, LOGIC_SUBDIR, LEDGER_NAME)
        with open(ledger_path, "rb") as g:
            matrix["ledgered"]["sha256"] = hashlib.sha256(g.read()).hexdigest()
        # Additive Dig 17 amendment: the deferred-kind outbound dig emits its
        # own below-bar ledger beside `_ledger.jsonl`; surface it as an
        # envelope record (classes + sha) without touching bar-1 accounting.
        deferred_path = os.path.join(args.reldir, LOGIC_SUBDIR,
                                     LEDGER_DEFERRED_NAME)
        if os.path.isfile(deferred_path):
            drows = [json.loads(x) for x in
                     open(deferred_path, encoding="utf-8").read().splitlines()
                     if x.strip()]
            dmeta = drows[0].get("_meta", {}) if drows else {}
            dcls = collections.Counter(
                r.get("unblockClass") for r in drows[1:] if r.get("unblockClass"))
            matrix["ledgeredDeferred"] = {
                "sourceFile": f"relinks/{LOGIC_SUBDIR}/"
                              f"{LEDGER_DEFERRED_NAME}",
                "producedBy": dmeta.get("dig"),
                "rows": len(drows) - 1,
                "classes": [{"class": c, "rows": n}
                            for c, n in sorted(dcls.items())],
                "edgeSetMembership": "none - below-bar accounting only",
                "sha256": hashlib.sha256(
                    open(deferred_path, "rb").read()).hexdigest(),
            }
        matrix["provenance"] = {
            "catalogTool": "pipeline/tools/relink_catalog.py",
            "amendment": f"{WIRING_DIG} R10b canonical wiring of the "
                         f"{EVIDENCE_DIG} _logic evidence layer "
                         "(arbiter-rule8-gate §2.1): envelope amended "
                         "additively; pre-existing keys keep their frozen "
                         "semantics and the hard-modeled pair-file plane "
                         "stays byte-identical",
            "evidenceVerification": "docs/verify-dig15-a.mdx · "
                                    "docs/verify-dig15-b.mdx · "
                                    "docs/verify-dig15-delta.mdx (all PASS)",
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
    if families is not None:
        print(f"wiring ({WIRING_DIG}): {len(scaffold_families)} "
              f"{EVIDENCE_DIG} "
              f"families / {ev_edges} evidence edges -> "
              f"{len(derived)} derived + {_dir_count('fold')} folded "
              f"directions wired, "
              f"{sum(ledger_classes.values())} directions ledgered")
        print(f"dig-17 deferred-outbound wiring: {len(deferred_src)} "
              f"families / "
              f"{sum(f['edges'] for f in deferred_src)} edges outside the "
              f"scaffold pair space (+ _ledger_deferred.jsonl)")
    print(f"wrote {args.out_json} (sha256 {matrix_sha[:16]}...) + {args.out_md}")
    return 0


def write_evidence_sections(L, m):
    """Dig 16 R10b sections rendered FROM matrix.json (never re-derived):
    derived-evidence wiring tables, ledgered-direction accounting, and the
    open-debt mirror of PROOF.md R10."""
    w = L.append
    de = m["derivedEvidence"]
    led = m["ledgered"]
    t = m["totals"]
    dirs = de["directions"]

    w("## Derived-evidence wiring (dig-15 `_logic` layer · wired by Dig 16)")
    w("")
    w(f"The verified evidence layer (`{de['sourceDir']}/`, {de['families']} "
      f"families · {de['edges']:,} edges; verify-dig15-a/b/delta all PASS) "
      f"is")
    w("wired into this catalog WITHOUT moving a canonical pair file: the")
    w("hard-modeled plane above stays byte-identical; each derived direction")
    w("below gains its edge count with preserved locators (family file +")
    w("sha256); the ledgered residue stays out of every edge set (next")
    w(f"section). Methods: " + " · ".join(
        f"{k} {v:,}" for k, v in de["methods"].items()) + ".")
    w("")
    w(f"Admission rule: {de['admissionRule']}")
    w("")
    w("| direction | evidence edges | mechanisms | family | cdb declarations |")
    w("|---|---:|---|---|---|")
    for f in dirs:
        if f["class"] != "derived":
            continue
        decls = "; ".join(f["cdbDeclarations"]) if f["cdbDeclarations"] else "-"
        w(f"| `{f['from']}→{f['to']}` | {f['edges']} | "
          f"{'+'.join(f['mechanisms'])} | `{f['file']}` | `{decls}` |")
    w("")
    w("### Folded onto modeled directions (extra carriers beside the hard keys)")
    w("")
    w("| direction | evidence edges | mechanisms | family |")
    w("|---|---:|---|---|")
    for f in dirs:
        if f["class"] != "fold":
            continue
        w(f"| `{f['from']}→{f['to']}` | {f['edges']} | "
          f"{'+'.join(f['mechanisms'])} | `{f['file']}` |")
    w("")
    w("### Evidence families on kind↔itself (outside the ordered matrix)")
    w("")
    w("| kind | evidence edges | mechanisms | family | disposition |")
    w("|---|---:|---|---|---|")
    for f in dirs:
        if f["class"] == "fold-self":
            w(f"| {f['from']} | {f['edges']} | {'+'.join(f['mechanisms'])} | "
              f"`{f['file']}` | extra carriers on the canonical self-pair "
              f"file |")
    for f in dirs:
        if f["class"] == "self-chain":
            w(f"| {f['from']} | {f['edges']} | {'+'.join(f['mechanisms'])} | "
              f"`{f['file']}` | evidence only - no canonical self-pair file "
              f"yet |")
    w("")
    w(f"## Ledgered directions ({led['rows']} — DR bar-1 residue, no edges)")
    w("")
    w("Accounting, never an edge set: these ordered directions carry no")
    w("emitted relation at this buildid. Each row's full class text + recheck")
    w(f"pointer lives in `{led['sourceFile']}` (sha256 `{led.get('sha256', '-')}`);")
    w("they appear here so the scaffold totals close exactly:")
    w("modeled + derived + ledgered = "
      f"{t['modeledDirections']} + {t['derivedDirections']} + {led['rows']} "
      f"= {t['orderedDirections']} directions.")
    w("")
    w("| class | directions |")
    w("|---|---:|")
    for c in led["classes"]:
        w(f"| {c['class']} | {c['directions']} |")
    w(f"| **total** | **{led['rows']}** |")
    if m.get("deferredOutbound"):
        do_ = m["deferredOutbound"]
        w("## Deferred-kind outbound carriers (dig-17 `_logic` families)")
        w("")
        w(f"The deferred sources element/group/place/levelProps carry their "
          f"own outbound evidence layer OUTSIDE the C(40,2) scaffold space:")
        w(f"**{do_['families']} families · {do_['edges']:,} edges**, methods "
          + " · ".join(f"{k} {v:,}" for k, v in
                       sorted(do_.get("methods", {}).items())) + ".")
        w("Admission rule: " + do_["admissionRule"])
        w("")
        w("| direction | edges | family | cdb declarations |")
        w("|---|---:|---|---|")
        for f in do_["directions"]:
            decls = "; ".join(f["cdbDeclarations"]) \
                if f["cdbDeclarations"] else "script-enum namespace"
            w(f"| `{f['from']}→{f['to']}` | {f['edges']} | "
              f"`{f['file']}` | `{decls}` |")
        ld = m.get("ledgeredDeferred")
        if ld:
            cls = ", ".join(f"{c['class']} {c['rows']}"
                            for c in ld["classes"])
            w("")
            w(f"Below-bar mass for these sources ledgered in "
              f"`{ld['sourceFile']}` ({ld['rows']} rows: {cls}) — never "
              f"edges.")
        w("")

    w("")
    w("## Open debt (mirrors [PROOF.md R10](PROOF.md))")
    w("")
    w("- (a) code-consumer adjudication of the **60** payload-value name-hit")
    w("  directions (of the 188 `unadjudicated-name-hits`; 128 are own-id")
    w("  coincidences) — hidden-sub-sheet typing is exhausted; rider R4;")
    if m.get("deferredOutbound"):
        do_ = m["deferredOutbound"]
        w("- (b) ~~deferred-kind outbound carriers~~ **LANDED by Dig 17** ")
        w("  (2026-08-26, rider R6): the flagged mass reproduced exactly "
          "(73")
        w("  populated typed paths / 13,429 resolving refs) and emitted as ")
        w(f"  {do_['families']} family files / {do_['edges']:,} edges under ")
        w("  `relinks/_logic/` (typed hidden-sub-sheet joins + "
          "`element.script`")
        w("  CDB-enum references), with the sibling-deferred and `constant` ")
        w("  targets admitted under the recorded extension of the dig-15 ")
        w("  rule; below-bar classes live in `_ledger_deferred.jsonl`; ")
        w("  probes: dangling 0, independent all-locator re-resolution + 45 ")
        w("  break controls rejected, determinism double-run byte-equal, ")
        w("  validate_all legs unchanged ([Dig 17](../docs/data-dig-log.mdx));")
    else:
        w("- (b) deferred-kind outbound carriers: **73** typed paths / "
          "**13,429**")
        w("  resolving refs from element/group/place/levelProps + ~330 enum "
          "refs")
        w("  in `element.script` — rider R6;")
    w("- (c) bar-2 extension dig over the **126** deferred ui/win windows,")
    w("  starting TradeRoute/GarnisonManager/Gambling/Stake/OilPanel/")
    w("  CampChest/WeaponDisplay — rider R5;")
    w("- (d) trade-price-matrix gap: nearest-producer inputs are deferred-kind")
    w("  payload; stock refresh is genuine runtime state — rider R8.")
    w("")
    w("Every class above is re-checked against the TargetBuildID 21238928")
    w("patch-diff.")
    w("")


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
    if "derivedEvidence" in m:
        de = m["derivedEvidence"]
        led = m["ledgered"]
        w(f"- derived-evidence layer ({de['evidenceLayer']}, wired by "
          f"{de['wiredBy']}): {de['families']} families · "
          f"{de['edges']:,} edges · {t['derivedDirections']} derived + "
          f"{t['foldedModeledDirections'] + t['foldedSelfPairKinds']} folded "
          f"directions · {led['rows']} directions ledgered")
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
    if "derivedEvidence" in m:
        write_evidence_sections(L, m)
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
