#!/usr/bin/env python3
"""validate_all.py — stage 6 validation-only pass (spec-stages-datasets §5.2).

  python validate_all.py --cdb extracted/harvest/res/data.cdb --buildid <id>
      --datadir extracted/data --reldir extracted/relinks
      --report extracted/validation-report.json
      [--md extracted/VALIDATION-REPORT.md]

Exits 0 iff every check passes; 1 otherwise; 2 on missing inputs (naming the
owning stage — consumer-boundary fail-loud, spec §3.4 rule 6).

Verifier evidence is obtained by INVOKING cdb_verify.py as a child (one
independent verification truth, no reimplementation); availability evidence
by invoking locale_bridge_dig.py as a child and asserting its own printed
report key set (arbiter F7).

The report keeps its wall-clock `generated` deliberately (arbiter F9/m1
declared exemption): run REPORTS are not derived DATA artifacts.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wave_kinds        # noqa: E402
import cdb_verify        # noqa: E402  (CENSUS transcription only — no logic)

TOOL = "pipeline/tools/validate_all.py"
PACK_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
EXPECTED_LOCALES = {"en", "fr", "de", "es", "pl", "pt-BR", "ru", "ko", "zh"}
WAVE1_DRAFT_KINDS = ("item", "skill", "class")
BANNED_HBSON = ("place", "group", "element", "levelProps")

# F3 (arbiter adjudication): RELATIONS.md Full-matrix cells are PARSED back
# into field values and compared against the matrix records — an independent
# re-derivation of the render (T9's approach), never string regeneration.
# Grammar below is relink_catalog.render_direction's documented output.
MODELED_CELL_RE = re.compile(
    r"^modeled · E=(\d+) · card=(\S+) · keys=\[(.*)\] · mech=(\S+) · "
    r"v=(\d+)/(\d+)/(\d+)$")
NON_MODELED_CELL_RE = re.compile(r"^(partial|missing) → (.+)$")


def parse_md_cell(cell):
    """-> parsed field tuple for one rendered direction, or ('unparseable',)."""
    cell = cell.strip()
    m = MODELED_CELL_RE.match(cell)
    if m:
        keys = [k.strip() for k in m.group(3).split(",")] if m.group(3) else []
        return ("modeled", int(m.group(1)), m.group(2), keys,
                m.group(4).split("+"),
                {"true": int(m.group(5)), "false": int(m.group(6)),
                 "null": int(m.group(7))})
    m = NON_MODELED_CELL_RE.match(cell)
    if m:
        return (m.group(1), m.group(2).strip())
    return ("unparseable", cell)


def expected_md_cell(rec):
    """The field values a matrix.json record renders into one MD cell."""
    if rec["status"] == "modeled":
        return ("modeled", rec["edges"], rec["cardinality"],
                list(rec["joinKeys"]), list(rec["mechanism"]),
                dict(rec["validCounts"]))
    return (rec["status"], rec.get("unblock"))


# R7: inline frozen transcription of spec-stages-datasets §3.5 (CENSUS-style,
# ids + kinds + unblock tokens) — `deferred-present` compares
# wave_kinds.DEFERRED against THIS, not against itself; content drift inside
# the module is detectable.
FROZEN_DEFERRED = (
    ("hbson-decoded-kinds",
     ("location-place(sheet place)", "enemy group",
      "npc/dialogue(element)", "poi/battle-scene(levelProps)"),
     "R1"),
    ("achievement", ("achievement",), "R2"),
    ("constant", ("constant",), "none - closure counts it"),
    ("subset-views",
     ("potion/food", "trade-good/price", "path/title",
      "ghost/curse views"),
     "none - joins"),
)


def die(msg):
    print("ERROR: " + msg)
    sys.exit(2)


def raw_jsonl_names(datadir):
    """Unfiltered .jsonl stem listing (R1: the guard must see intruders)."""
    if not os.path.isdir(datadir):
        return None
    return sorted(f[:-6] for f in os.listdir(datadir) if f.endswith(".jsonl"))


def managed_kinds_in(datadir):
    raw = raw_jsonl_names(datadir)
    if raw is None:
        return None
    return [k for k in raw if k in wave_kinds.MANAGED_KINDS]


def relations_md_path(args):
    """R13: the rendered catalog BESIDE THE TREE UNDER TEST — derived from
    --reldir, the same root matrix.json comes from, so one invocation reads
    one source of truth. Resolves to <PACK_ROOT>/extracted/RELATIONS.md for
    every in-pipeline run; out-of-tree validation parity-checks its own
    tree's render instead of the tool pack's."""
    return os.path.join(os.path.dirname(os.path.abspath(args.reldir)),
                        "RELATIONS.md")


def preconditions(args):
    """Exit 2 naming the owning producer when a consumer boundary is broken."""
    if not os.path.isfile(args.cdb):
        die(f"input data.cdb missing: {args.cdb} (owning stage: "
            f"run_all.ps1 harvest)")
    want = sorted(wave_kinds.MANAGED_KINDS)
    raw_names = raw_jsonl_names(args.datadir)
    if raw_names is None:
        die(f"canonical data dir missing: {args.datadir} (owning stage: "
            f"run_all.ps1 datasets)")
    missing = [k for k in want if k not in raw_names]
    if missing:
        # R1: message carries the RAW name listing — it must not claim
        # "exactly" over a filtered list. Non-managed extras are NOT fatal
        # here (spec §5.2: every fault becomes a report record; T10's planted
        # file must reach `hbson-independent` as its own record) — run_all's
        # raw exactly-40 exit-2 block stays the stage-boundary guard.
        die(f"{args.datadir} does not hold all {len(want)} managed kinds "
            f"(owning stage: run_all.ps1 datasets); missing: {missing}; "
            f".jsonl names present: {raw_names}")
    pair_files = sorted(f for f in os.listdir(args.reldir)
                        if wave_kinds.is_pair_name(f)) \
        if os.path.isdir(args.reldir) else []
    if len(pair_files) != wave_kinds.EXPECTED_PAIR_FILES:
        die(f"{args.reldir} holds {len(pair_files)} pair files, expected "
            f"exactly {wave_kinds.EXPECTED_PAIR_FILES} (owning stage: "
            f"run_all.ps1 relink)")
    relmd = relations_md_path(args)
    if not os.path.isfile(relmd):
        die(f"{relmd} missing (owning stage: run_all.ps1 relink)")
    if not os.path.isfile(os.path.join(args.reldir, "matrix.json")):
        die(f"{args.reldir}/matrix.json missing (owning stage: "
            f"run_all.ps1 relink)")
    for kind in WAVE1_DRAFT_KINDS:
        # finding A (arbiter): anchored to PACK_ROOT like every other path in
        # this file — the cwd-relative join exited 2 spuriously from any
        # non-pack cwd.
        p = os.path.join(PACK_ROOT, "extracted", "data", "_draft",
                         f"{kind}.jsonl")
        if not os.path.isfile(p):
            die(f"{p} missing (owning stage: run_all.ps1 datasets)")


class UnreadableInput(Exception):
    """R14: a consumed artifact failed its own read or parse — routed into
    the owning check's report record (fail-loud, named locator) instead of a
    traceback that discards every already-recorded check."""


def load_jsonl(path):
    """-> (_meta object, data lines); raises UnreadableInput on any fault."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        first = json.loads(lines[0])
        if not isinstance(first, dict):
            raise ValueError("meta line is not a JSON object")
        meta = first.get("_meta", {})
        if not isinstance(meta, dict):
            raise ValueError("_meta is not an object")
    except (OSError, ValueError, IndexError) as x:
        # json.JSONDecodeError and UnicodeDecodeError are both ValueError.
        raise UnreadableInput(f"{type(x).__name__}: {x}") from x
    return meta, lines[1:]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cdb", default="extracted/harvest/res/data.cdb")
    ap.add_argument("--buildid", required=True)
    ap.add_argument("--datadir", default="extracted/data")
    ap.add_argument("--reldir", default="extracted/relinks")
    ap.add_argument("--report", default="extracted/validation-report.json")
    ap.add_argument("--md", default="extracted/VALIDATION-REPORT.md")
    args = ap.parse_args(argv)
    preconditions(args)

    tools = os.path.dirname(os.path.abspath(__file__))
    checks = []

    def add(cid, expected, actual, ok):
        checks.append({"id": cid, "expected": expected, "actual": actual,
                       "pass": bool(ok)})
        return bool(ok)

    # ---- child 1: independent verifier over BOTH canonical planes ----------
    verify_argv = [os.path.join(tools, "cdb_verify.py"), args.cdb,
                   "--datadir", args.datadir, "--reldir", args.reldir,
                   "--buildid", args.buildid]
    v = subprocess.run([sys.executable] + verify_argv,
                       capture_output=True, text=True)
    gates = {"cdb_verify": {
        "argv": ["python"] + verify_argv, "exitCode": v.returncode,
        "allChecksPassed": v.returncode == 0
        and "ALL CHECKS PASSED" in v.stdout}}
    add("verifier-gates",
        "cdb_verify over canonical dirs exits 0 (ALL CHECKS PASSED)",
        f"exit {v.returncode}, allChecksPassed="
        f"{gates['cdb_verify']['allChecksPassed']}",
        gates["cdb_verify"]["allChecksPassed"])

    # ---- child 2: deterministic availability regeneration + own report -----
    avail_argv = [os.path.join(tools, "locale_bridge_dig.py")]
    a = subprocess.run([sys.executable] + avail_argv,
                       capture_output=True, text=True)
    report = None
    if a.returncode == 0:
        try:
            report = json.loads(a.stdout)
        except json.JSONDecodeError:
            report = None
    gates["locale_bridge_dig"] = {
        "argv": ["python"] + avail_argv, "exitCode": a.returncode,
        "reportParsed": report is not None}

    # ---- canonical datasets -------------------------------------------------
    # R1/F14: iterate the MANAGED universe only — a non-managed intruder never
    # enters per_kind_rows/total_rows (its verdict belongs to
    # `hbson-independent` as a report record, not to a KeyError here).
    per_kind_rows = {}
    rowcount_mismatch = []
    total_rows = 0
    unreadable_kinds = []
    for kind in managed_kinds_in(args.datadir):
        try:
            meta, rows = load_jsonl(
                os.path.join(args.datadir, kind + ".jsonl"))
        except UnreadableInput as x:
            # R14: the fault belongs to census-closure's own record.
            rowcount_mismatch.append(f"{kind}.jsonl: UNREADABLE ({x})")
            unreadable_kinds.append(kind)
            continue
        per_kind_rows[kind] = len(rows)
        total_rows += len(rows)
        if meta.get("rowCount") != len(rows):
            rowcount_mismatch.append(f"{kind}: _meta.rowCount="
                                     f"{meta.get('rowCount')} != {len(rows)}")

    constants_rows = cdb_verify.CENSUS["constant"]
    constants_path = os.path.join(PACK_ROOT, "extracted", "logic",
                                  "constants.jsonl")
    constants_note = ""
    constants_ok = True
    if os.path.isfile(constants_path):
        try:
            _, const_lines = load_jsonl(constants_path)
            constants_ok = len(const_lines) == constants_rows
            constants_note = f" (logic/constants.jsonl={len(const_lines)})"
        except UnreadableInput as x:
            # R14: the conditional drift tripwire fails loudly instead.
            constants_ok = False
            constants_note = f" (logic/constants.jsonl UNREADABLE: {x})"
    closure_total = total_rows + constants_rows
    add("census-closure",
        f"sum(canonical rows) + {constants_rows} (verifier census "
        f"`constant`) == 11473{constants_note}",
        f"{total_rows} + {constants_rows} == {closure_total}"
        + (f"; readFaults={rowcount_mismatch[:4]}"
           if rowcount_mismatch else ""),                # R14 locator
        closure_total == 11473 and not rowcount_mismatch and constants_ok)

    deviations = []
    for kind in sorted(per_kind_rows):
        sheet = wave_kinds.KIND_SHEETS[kind]
        want = cdb_verify.CENSUS[sheet]
        if per_kind_rows[kind] != want:
            deviations.append(f"{kind}: {per_kind_rows[kind]} != {want}")
    # R14: an unreadable kind never entered per_kind_rows — name it here too.
    deviations.extend(f"{k}.jsonl: unreadable"
                      for k in sorted(unreadable_kinds))
    add("census-per-kind",
        "each of the 40 kinds equals its census-table value",
        f"{len(deviations)} deviations" + (
            ": " + "; ".join(deviations[:8]) if deviations else ""),
        not deviations and len(per_kind_rows) == 40)

    # ---- canonical relinks --------------------------------------------------
    pair_files = sorted(f for f in os.listdir(args.reldir)
                        if wave_kinds.is_pair_name(f))
    edge_total = valid_true = valid_false = valid_null = 0
    null_by_file = {}
    mech_bad = []
    edge_read_faults = []                 # R14: relink-integrity's own record
    for fn in pair_files:
        try:
            _, rows = load_jsonl(os.path.join(args.reldir, fn))
        except UnreadableInput as x:
            edge_read_faults.append(f"{fn}: {x}")
            continue
        edge_total += len(rows)
        nulls = 0
        for ln_i, r in enumerate(rows, 1):
            try:
                e = json.loads(r)
                if not isinstance(e, dict):
                    raise ValueError("edge row is not an object")
            except ValueError as x:
                edge_read_faults.append(f"{fn}:{ln_i}: {x}")
                continue
            if e.get("valid") is True:
                valid_true += 1
            elif e.get("valid") is False:
                valid_false += 1
            else:
                valid_null += 1
                nulls += 1
            if e.get("mechanism") != "hard":
                mech_bad.append(fn)
        if nulls:
            null_by_file[fn[:-6]] = nulls
    frozen_split = {"env__place": 61, "frescos__place": 9,
                    "fiefGoal__element": 2}
    split_txt = "+".join(str(null_by_file.get(k, 0)) for k in frozen_split)
    add("relink-integrity",
        f"pairFiles={wave_kinds.EXPECTED_PAIR_FILES}; edges=19130; "
        f"valid:false=0; valid:null=72 ({'+'.join(str(v) for v in frozen_split.values())}); "
        f"mechanism=hard",
        f"pairFiles={len(pair_files)}; edges={edge_total}; "
        f"valid:false={valid_false}; valid:null={valid_null} ({split_txt}); "
        f"non-hard={sorted(set(mech_bad)) or 0}"
        + (f"; readFaults={edge_read_faults[:4]}"
           if edge_read_faults else ""),                 # R14 locator
        len(pair_files) == wave_kinds.EXPECTED_PAIR_FILES
        and edge_total == 19130 and valid_false == 0 and valid_null == 72
        and null_by_file == frozen_split and not mech_bad
        and not edge_read_faults)

    # ---- availability (from the generator's OWN report, arbiter F7) --------
    if report is None:
        add("availability-regenerated",
            "locale_bridge_dig exits 0 and prints a parseable report",
            f"exit {a.returncode}, parsed={(a.returncode == 0)}", False)
        avail_rows = avail_per_kind = 0
        overlay_entities = None
    else:
        avail_read_faults = []            # R14: owning check's own record
        try:
            with open(os.path.join(args.reldir, "locale_availability.jsonl"),
                      encoding="utf-8") as f:
                avail_lines = f.read().splitlines()
        except (OSError, ValueError) as x:
            avail_lines = []
            avail_read_faults.append(
                f"locale_availability.jsonl: UNREADABLE "
                f"{type(x).__name__}: {x}")
        avail_per_kind = {}
        locale_law_bad = []
        for row_i, r in enumerate(avail_lines, 1):
            try:
                row = json.loads(r)
                kind_name = row["kind"]
                av = set(row["availableLocales"])
                named = set(row["namedLocales"])
            except (ValueError, KeyError, TypeError) as x:
                # R14: a malformed row is this check's record, not a crash.
                avail_read_faults.append(
                    f"row{row_i}: UNREADABLE {type(x).__name__}: {x}")
                continue
            avail_per_kind[kind_name] = avail_per_kind.get(kind_name, 0) + 1
            # F4 corrected invariant, frozen from measurement (2026-08-25):
            # both histograms are strictly bimodal {0: 458/560, 9: 3321/3219}
            # — a row lawfully carries ALL official locales or NONE; partial
            # sets do not exist and under-reporting must fail.
            if av not in (set(), EXPECTED_LOCALES) \
                    or named not in (set(), EXPECTED_LOCALES):
                locale_law_bad.append(
                    f"{kind_name}/{row.get('id', '?')}: "
                    f"av={sorted(av)} named={sorted(named)}")
        fillers = report.get("filler_class_cells", {})
        grid_keys = [(k, loc) for k in sorted(fillers)
                     for loc in sorted(fillers[k])]
        grid_bad = [(k, loc, v) for k, locs in sorted(fillers.items())
                    for loc, v in sorted(locs.items()) if v != 0]
        locales_ok = set(report.get("locales", [])) == EXPECTED_LOCALES
        overlay_entities = sum(
            sum(loc.values()) for loc in
            report.get("overlay_entity_counts", {}).values())
        add("availability-regenerated",
            "rows=3779 (item=2125 skill=1373 class=281); locales=9; per-row "
            "available/named locale sets in {empty, exact 9-official set} "
            "(measured bimodal law); filler_class_cells grid = 3kinds x "
            "9locales = 27 keys, all 0",
            f"rows={len(avail_lines)} "
            f"(item={avail_per_kind.get('item')} skill={avail_per_kind.get('skill')} "
            f"class={avail_per_kind.get('class')}); locales="
            f"{len(set(report.get('locales', [])))}; "
            f"localeLawViolations={locale_law_bad[:4] or 0}; "
            f"grid={len(grid_keys)} keys, {len(grid_bad)} nonzero"
            + (f"; readFaults={avail_read_faults[:4]}"
               if avail_read_faults else ""),            # R14 locator
            len(avail_lines) == 3779
            and avail_per_kind == {"item": 2125, "skill": 1373, "class": 281}
            and locales_ok and not locale_law_bad
            and len(grid_keys) == 27 and not grid_bad
            and not avail_read_faults)

    # ---- catalog parity -----------------------------------------------------
    # R13: BOTH parity inputs come from the tree under test — matrix.json AND
    # the rendered RELATIONS.md beside it (--reldir root), never the tool's
    # own PACK_ROOT. R14: the whole computation is fault-routed — any read/
    # parse/shape fault lands IN the catalog-parity record (named locator)
    # instead of discarding every already-recorded check.
    def catalog_parity():
        matrix_path = os.path.join(args.reldir, "matrix.json")
        with open(matrix_path, "rb") as f:
            matrix_raw = f.read()
        matrix_sha = hashlib.sha256(matrix_raw).hexdigest()
        mx = json.loads(matrix_raw.decode("utf-8"))
        uncovered = []
        for p in mx.get("pairs", []):
            for side in ("forward", "reverse"):
                rec = p[side]
                if rec["status"] != "modeled" and not rec.get("unblock"):
                    uncovered.append(f"{p['a']}–{p['b']}:{side}")
        md_path = relations_md_path(args)
        with open(md_path, encoding="utf-8") as f:
            relations_md = f.read()
        marker_ok = f"matrix.json sha256: `{matrix_sha}`" in relations_md
        section = re.split(r"^## ", relations_md, flags=re.M)
        matrix_section = next((s for s in section
                               if s.startswith("Full matrix")), "")
        md_matrix_rows = sum(1 for ln in matrix_section.splitlines()
                             if ln.startswith("| `"))
        # F3: row-for-row parse-and-compare — every rendered cell must re-derive
        # from its matrix record's FIELD VALUES (status, edges, cardinality,
        # joinKeys, mechanism, validCounts triple; non-modeled: status + unblock).
        md_cells = {}
        for ln in matrix_section.splitlines():
            if not ln.startswith("| `"):
                continue
            parts = ln.split("|")
            if len(parts) >= 5:
                md_cells[parts[1].strip()] = (parse_md_cell(parts[2]),
                                              parse_md_cell(parts[3]))
        cell_mismatches = []
        for p in mx.get("pairs", []):
            label = f"`{p['a']}–{p['b']}`"
            got_pair = md_cells.pop(label, None)
            if got_pair is None:
                cell_mismatches.append(
                    f"{label}: row missing from RELATIONS.md")
                continue
            for side, got_cell in (("forward", got_pair[0]),
                                   ("reverse", got_pair[1])):
                want_cell = expected_md_cell(p[side])
                if got_cell != want_cell:
                    cell_mismatches.append(
                        f"{label}:{side}: MD {got_cell!r} != matrix "
                        f"{want_cell!r}")
        cell_mismatches.extend(f"{lbl}: unexpected MD row"
                               for lbl in sorted(md_cells))
        actual = (f"pairCount={mx.get('pairCount')}; "
                  f"uncovered={uncovered[:4] or 0}; "
                  f"markerMatch={marker_ok}; mdMatrixRows={md_matrix_rows}; "
                  f"cellMismatches={cell_mismatches[:4] or 0}")
        ok = (mx.get("pairCount") == 780 and not uncovered and marker_ok
              and md_matrix_rows == 780 and not cell_mismatches)
        return ok, actual

    try:
        cat_ok, cat_actual = catalog_parity()
    except (OSError, ValueError, KeyError, TypeError, IndexError,
            AttributeError) as x:
        cat_ok = False                       # R14: record, never a lost report
        cat_actual = (f"UNREADABLE catalog inputs ({args.reldir}/matrix.json"
                      f" + {relations_md_path(args)}): "
                      f"{type(x).__name__}: {x}")
    add("catalog-parity",
        "pairCount=780; every non-modeled direction carries exactly one "
        "unblock; RELATIONS.md rendered from this matrix (sha256 marker + "
        "row-for-row parse-and-compare of rendered cells)",
        cat_actual, cat_ok)

    # ---- deferred honesty ---------------------------------------------------
    # R7: compare the module against the inline frozen §3.5 transcription
    # (ids + kinds + unblock tokens) — not wave_kinds against itself.
    module_shape = tuple((d.get("id"), tuple(d.get("kinds") or ()),
                          d.get("unblock")) for d in wave_kinds.DEFERRED)
    frozen_match = module_shape == FROZEN_DEFERRED
    deferred_ids = [d["id"] for d in wave_kinds.DEFERRED]
    deferred_ok = (bool(wave_kinds.DEFERRED)
                   and frozen_match
                   and all(d.get("unblock") for d in wave_kinds.DEFERRED))
    add("deferred-present",
        "deferred[] matches the frozen §3.5 honesty list with unblock "
        f"pointers: {[f[0] for f in FROZEN_DEFERRED]}",
        f"{deferred_ids} (frozenMatch={frozen_match})", deferred_ok)

    # ---- parallel-dig independence -----------------------------------------
    # R6: recursive over BOTH canonical planes — matching the check's own
    # words ("anywhere under canonical dirs") — pruning any path component
    # named `_draft` so the lawful wave-3 draft corpora never false-fail.
    # Fail on the four banned HBSON names; count-and-report every other
    # non-managed .jsonl in the record (never crash on extras, R1).
    intruders = []
    non_managed = []
    for directory in (args.datadir, args.reldir):
        for root, dirs, files in os.walk(directory):
            dirs[:] = sorted(d for d in dirs if d != "_draft")
            for fn in sorted(files):
                if not fn.endswith(".jsonl"):
                    continue
                base = fn[:-6]
                # R12: anchored to the walked plane root — unanchored,
                # ntpath.relpath resolves against the CWD and RAISES across
                # Windows drives (ValueError, crash without report, review
                # r2 A4); plane-rooted records are cwd-independent.
                rel = os.path.relpath(os.path.join(root, fn), directory)
                if base in BANNED_HBSON:
                    intruders.append(rel)
                elif base not in wave_kinds.MANAGED_KINDS \
                        and not wave_kinds.is_pair_name(fn):
                    non_managed.append(rel)
    add("hbson-independent",
        "no place|group|element|levelProps.jsonl anywhere under canonical "
        "dirs, _draft subtrees pruned (parallel-dig guarantee, AC11); other "
        f"non-managed .jsonl counted-and-reported ({len(non_managed)} lawful "
        "today)",
        f"banned={intruders or 'absent'}; nonManaged={len(non_managed)}"
        + (f" -> {non_managed[:6]}" if non_managed else ""),
        not intruders)

    # ---- envelope -----------------------------------------------------------
    overall = all(c["pass"] for c in checks)
    envelope = {
        "buildId": args.buildid,
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "tool": TOOL,
        "pass": overall,
        "checks": checks,
        "gates": gates,
        "counts": {
            "datasetsRows": total_rows,
            "censusTotal": closure_total,
            "constants": {
                "rows": constants_rows,
                "source": "verifier census",
                "producer": "pipeline/tools/formula_emit.py (dig 2; wiring "
                            "queued with the formulas/decompile track)",
            },
            "relinkFiles": len(pair_files),
            "relinkEdges": edge_total,
            "validTrue": valid_true,
            "validFalse": valid_false,
            "validNull": valid_null,
            "availabilityRows":
                sum(avail_per_kind.values()) if report is not None else 0,
            "availabilityPerKind": avail_per_kind,
            "overlayEntities": overlay_entities,
        },
        "deferred": list(wave_kinds.DEFERRED),
    }
    with open(args.report, "w", encoding="utf-8", newline="\n") as g:
        g.write(json.dumps(envelope, ensure_ascii=False, indent=1) + "\n")
    write_md(args.md, envelope)
    print(f"validation: {'PASS' if overall else 'FAIL'} "
          f"({sum(c['pass'] for c in checks)}/{len(checks)} checks)")
    for c in checks:
        print(f"  [{'ok' if c['pass'] else 'FAIL'}] {c['id']}: {c['actual']}")
    print(f"wrote {args.report} + {args.md}")
    return 0 if overall else 1


def write_md(path, env):
    L = []
    w = L.append
    w("# Wartales — VALIDATION-REPORT.md (stage emit)")
    w("")
    w(f"buildId: {env['buildId']} · tool: {env['tool']} · "
      f"generated: {env['generated']} · "
      f"pass: {str(env['pass']).lower()}")
    w("")
    w("| check | expected | actual | pass |")
    w("|---|---|---|---|")
    for c in env["checks"]:
        exp = c["expected"].replace("|", "\\|")
        act = str(c["actual"]).replace("|", "\\|")
        w(f"| {c['id']} | {exp} | {act} | {str(c['pass']).lower()} |")
    g = env["gates"]
    w("")
    w(f"gates: cdb_verify exit {g['cdb_verify']['exitCode']} "
      f"(ALL CHECKS PASSED: "
      f"{str(g['cdb_verify']['allChecksPassed']).lower()}) · "
      f"locale_bridge_dig exit {g['locale_bridge_dig']['exitCode']} "
      f"(reportParsed: "
      f"{str(g['locale_bridge_dig']['reportParsed']).lower()})")
    w("")
    w(f"counts: {json.dumps(env['counts'], ensure_ascii=False, sort_keys=True)}")
    w("")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L))


if __name__ == "__main__":
    sys.exit(main())
