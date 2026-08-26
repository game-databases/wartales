#!/usr/bin/env python3
"""Locale-bridge dig (wartales dig 2): pin textKey -> export_<locale>.xml
addressing, emit per-locale overlays + locale_availability.jsonl.

Run:  python pipeline/tools/locale_bridge_dig.py
Read-only inputs:
  extracted/data/_draft/{item,skill,class}.jsonl   (dig-1 datasets)
  extracted/harvest/_lang-bridge/export_<locale>.xml (9 locales)
Writes:
  extracted/locales/<locale>/{item,skill,class}.json
  extracted/relinks/locale_availability.jsonl
Deterministic: fixed RNG seed, sorted iteration everywhere.
"""

from __future__ import annotations

import html
import json
import random
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

PACK = Path(__file__).resolve().parents[2]
BRIDGE = PACK / "extracted/harvest/_lang-bridge"
DRAFT = PACK / "extracted/data/_draft"
OUT_LOCALES = PACK / "extracted/locales"
OUT_RELINKS = PACK / "extracted/relinks"

LOCALES = ["en", "fr", "de", "es", "pl", "pt-BR", "ru", "ko", "zh"]
PIVOT = "en"                      # market pivot (spec.md locales.canonical)
KINDS = {"item": ("item", ["name", "desc"]),
         "skill": ("skill", ["name", "desc"]),
         "class": ("unitClass", ["name"])}
FIELD_ALIAS = {"name": "name", "desc": "description"}
SEED = 20318128                   # client buildid, deterministic samples
SAMPLE_N = {"item": 30, "skill": 15, "class": 10}   # >=20 required by brief

# ---------------------------------------------------------------- parsing --
# Machine-generated CastleDB export; scanned with a small token state machine
# over the raw text so stored leaf values keep their exact original bytes
# (child elements like <br/> survive verbatim; entities unescaped once).
TOKEN = re.compile(
    r'<sheet name="(?P<sheet>[^"]+)"\s*/?>'
    r'|</sheet>'
    r'|<(?P<open>[^/>\s]+)(?P<selfclose>\s*/>)?>'
    r'|</(?P<close>[^/>\s]+)>',
)


def parse_export(path: Path):
    """-> (headers dict, {sheet: {row: {col: value}}}, dup_rows list)

    State machine over raw text so each column value keeps its exact
    original bytes (child elements such as <br/> stay inside the value,
    verbatim); entities unescaped once to yield the game's true string."""
    raw = path.read_text(encoding="utf-8-sig")
    m_head = re.match(r'\s*<cdb ([^>]*)>', raw)
    headers = {} if m_head is None else \
        dict(re.findall(r'(\w+)="([^"]*)"', m_head.group(1)))
    sheets: dict[str, dict[str, dict[str, str]]] = {}
    order: dict[str, list[str]] = {}            # entry names in file order
    dups: list[str] = []
    sheet = entry = None
    collecting: tuple[str, int] | None = None   # (col tag, value start)
    inner: list[str] = []                       # open tags inside a value
    for m in TOKEN.finditer(raw):
        if m.group("sheet"):
            sheet = m.group("sheet")
            sheets.setdefault(sheet, {})
            entry = None
        elif m.group(0) == "</sheet>":
            sheet = entry = None
        elif m.group("open"):
            tag = m.group("open")
            selfclosing = m.group("selfclose") is not None
            if collecting is not None:
                if not selfclosing:
                    inner.append(tag)       # stays part of the raw value
            elif sheet is not None and entry is None:
                entry = tag                 # entry node under sheet
                sheets[sheet][entry] = {}
                order.setdefault(sheet, []).append(entry)
            elif entry is not None:
                if selfclosing:
                    sheets[sheet][entry][tag] = ""
                else:
                    collecting = (tag, m.end())
        elif m.group("close"):
            tag = m.group("close")
            if collecting is not None:
                if inner and inner[-1] == tag:
                    inner.pop()
                elif tag == collecting[0]:
                    val = html.unescape(raw[collecting[1]:m.start()])
                    sheets[sheet][entry][tag] = val
                    collecting = None
            elif tag == entry and sheet is not None:
                entry = None
    for sname, names in order.items():
        seen: set[str] = set()
        for rid in names:
            if rid in seen and f"{sname}/{rid}" not in dups:
                dups.append(f"{sname}/{rid}")
            seen.add(rid)
    return headers, sheets, dups


def parse_export_et(path: Path):
    """Independent ElementTree pass -> ({sheet:{row:{col: Element}}})."""
    root = ET.parse(path).getroot()
    out: dict[str, dict[str, dict[str, object]]] = {}
    for sh in root:
        rows = out.setdefault(sh.get("name"), {})
        for ent in sh:
            cols = rows.setdefault(ent.tag, {})
            for col in ent:                      # direct children ONLY
                cols[col.tag] = col
    return out


_TAGNAME = re.compile(r"<([^\s/>]+)")
_TAGGED = re.compile(r"<[^>]+>")


def strip_tags(v: str) -> str:
    return _TAGGED.sub("", v)


def build_block_index(raw: str) -> dict[str, list[str]]:
    """Entry-name -> list of raw entry-block bodies (single pass, independent
    of the storage tokenizer). Extra bogus blocks are harmless."""
    idx: dict[str, list[str]] = {}
    for m in re.finditer(r"<([\w.\-]+)>(.*?)</\1>", raw, re.S):
        idx.setdefault(m.group(1), []).append(m.group(2))
    return idx


def raw_leaf_match(blocks: list[str], col: str, want: str) -> bool | None:
    """True if some block holds a <col> leaf whose unescaped span equals
    `want`; False if leaves exist but none match; None if no leaf found."""
    found = matched = False
    for b in blocks:
        pos = 0
        while True:
            m2 = re.compile(r"<([\w.\-]+)(/?)>").search(b, pos)
            if m2 is None:
                break
            tag, slash = m2.group(1), m2.group(2)
            if slash:                       # self-closing leaf
                start = end = m2.end()
                pos = m2.end()
            else:
                close = re.compile(r"</" + re.escape(tag) + r">").search(
                    b, m2.end())
                if close is None:
                    pos = m2.end()
                    continue
                start, end = m2.end(), close.start()
                pos = close.end()
            if tag == col:
                found = True
                if html.unescape(b[start:end]) == want:
                    matched = True
                    break
    return None if not found else matched


# ------------------------------------------------------------------- main --
def load_draft(kind: str):
    rows = []
    meta = None
    with (DRAFT / f"{kind}.jsonl").open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            obj = json.loads(line)
            if i == 0 and "_meta" in obj:
                meta = obj["_meta"]
                continue
            rows.append(obj)
    return meta, rows


def main() -> int:
    report: dict = {"locales": LOCALES, "seed": SEED}

    # -- parse all 9 bridges (state machine) + en again via ElementTree ------
    idx: dict[str, dict] = {}
    headers: dict[str, dict] = {}
    dups_all: list[str] = []
    for loc in LOCALES:
        h, sheets, dups = parse_export(BRIDGE / f"export_{loc}.xml")
        headers[loc] = h
        idx[loc] = sheets
        dups_all += [f"{loc}:{d}" for d in dups]
    et_en = parse_export_et(BRIDGE / "export_en.xml")

    # -- dual-parser agreement on en (structure; exact text where expat is
    #    unambiguous, i.e. leaves with no real child elements) ---------------
    sm, etx = idx["en"], et_en
    mism: list[str] = []
    leaf_total = childless = mixed = 0
    text_mism = markup_mism = struct_mism = 0
    for sname, rows in sm.items():
        erows = etx.get(sname, {})
        if set(rows) != set(erows):
            struct_mism += 1
            mism.append(f"{sname}: row sets differ "
                        f"+{sorted(set(rows) - set(erows))[:3]} "
                        f"-{sorted(set(erows) - set(rows))[:3]}")
            continue
        for rid, cols in rows.items():
            ecols = erows[rid]
            if set(cols) != set(ecols):
                struct_mism += 1
                mism.append(f"{sname}/{rid}: col sets differ")
                continue
            for c, v in cols.items():
                leaf_total += 1
                node = ecols[c]
                if not list(node):            # no real children: expat text
                    childless += 1            # IS the string, byte-exact
                    if v != (node.text or "") and len(mism) < 8:
                        text_mism += 1
                        mism.append(f"{sname}/{rid}/{c}: text differs")
                else:                         # mixed content: entity form is
                    mixed += 1                # ambiguous here -> exhaustive
                    txt_ok = strip_tags(v) == "".join(node.itertext())
                    tags_ok = (_TAGNAME.findall(v)
                               == [k.tag for k in node.iter()
                                   if k is not node])
                    if not txt_ok and len(mism) < 8:
                        text_mism += 1
                        mism.append(f"{sname}/{rid}/{c}: stripped-text differs")
                    elif not tags_ok and len(mism) < 8:
                        markup_mism += 1
                        mism.append(f"{sname}/{rid}/{c}: tag sequence differs")
    report["dual_parser"] = {
        "leaves_compared": leaf_total,
        "childless_exact_checked": childless,
        "mixed_content_leaves": mixed,
        "text_mismatches": text_mism,
        "markup_mismatches": markup_mism,
        "structural_mismatches": struct_mism,
        "first": mism[:6],
    }

    # -- headers --------------------------------------------------------------
    report["headers"] = headers

    # -- resolve every draft ref x every locale -------------------------------
    # cell states per (kind,id,field,locale):
    #   ok        leaf exists, non-empty
    #   empty     leaf exists, empty string
    #   missing   no such sheet/row/col leaf
    drafts = {}
    cov = {k: {loc: {"ok": 0, "empty": 0, "missing": 0} for loc in LOCALES}
           for k in KINDS}
    avail: list[dict] = []
    resolve_fail_examples: list[str] = []
    for kind, (sheet, fields) in KINDS.items():
        meta, rows = load_draft(kind)
        drafts[kind] = (meta, rows)
        assert len(rows) == meta["rowCount"], (kind, len(rows))
        for r in rows:
            rid = r["id"]
            per_locale_fields: dict[str, dict[str, bool]] = {}
            available: list[str] = []
            named: list[str] = []
            for loc in LOCALES:
                fld_present = {}
                any_ok = False
                name_ok = False
                for col in fields:
                    ref = (r.get(col) or {}).get("textKey") if \
                        isinstance(r.get(col), dict) else None
                    if ref is None:
                        state = "missing"       # null cell in data.cdb too
                    else:
                        assert ref["bridge"] == "lang/export_<locale>.xml"
                        assert ref["sheet"] == sheet and ref["column"] == col \
                            and ref["row"] == rid, (kind, rid, col, ref)
                        v = idx[loc].get(sheet, {}).get(rid, {}).get(col)
                        if v is None:
                            state = "missing"
                            if loc == PIVOT and len(resolve_fail_examples) < 20:
                                resolve_fail_examples.append(
                                    f"{kind}/{rid}/{col}@{loc}")
                        elif v == "":
                            state = "empty"
                        else:
                            state = "ok"
                    cov[kind][loc][state] += 1
                    fld_present[FIELD_ALIAS[col]] = state == "ok"
                    any_ok |= state == "ok"
                    name_ok |= col == "name" and state == "ok"
                per_locale_fields[loc] = fld_present
                if any_ok:
                    available.append(loc)
                if name_ok:
                    named.append(loc)
            avail.append({"kind": kind, "id": rid,
                          "availableLocales": available,
                          "namedLocales": named,
                          "fields": per_locale_fields})
    report["coverage"] = cov
    report["pivot_resolve_failures_pivot"] = resolve_fail_examples

    # -- exhaustive raw-span verification: EVERY emitted cell of the three
    #    target sheets x 9 locales must equal its addressed leaf's unescaped
    #    raw span (independent regex extraction path) ------------------------
    raw_ok = raw_fail = raw_absent = 0
    raw_fail_examples: list[str] = []
    block_indexes: dict[str, dict[str, list[str]]] = {}
    for loc in LOCALES:
        text = (BRIDGE / f"export_{loc}.xml").read_text(encoding="utf-8-sig")
        # index only the sheet body: a bare '<cdb>' root (fr export vintage)
        # would otherwise match as one file-sized pseudo-block
        body = text[text.find(">", text.index("<cdb")) + 1:text.rfind("</cdb>")]
        bi = build_block_index(body)
        block_indexes[loc] = bi
        for kind, (sheet, fields) in KINDS.items():
            sheet_rows = idx[loc].get(sheet, {})
            for rid, cols in sheet_rows.items():
                blocks = bi.get(rid, [])
                for col in fields:
                    v = cols.get(col)
                    if v is None or col not in cols:
                        continue
                    res = raw_leaf_match(blocks, col, v)
                    if res is True:
                        raw_ok += 1
                    elif res is None:
                        raw_absent += 1
                        if len(raw_fail_examples) < 8:
                            raw_fail_examples.append(
                                f"{loc}:{sheet}/{rid}/{col}: leaf absent")
                    else:
                        raw_fail += 1
                        if len(raw_fail_examples) < 8:
                            raw_fail_examples.append(
                                f"{loc}:{sheet}/{rid}/{col}: span mismatch")
    report["raw_span_verification"] = {
        "cells_checked": raw_ok + raw_fail + raw_absent,
        "matched": raw_ok, "mismatched": raw_fail, "leaf_absent": raw_absent,
        "examples": raw_fail_examples,
    }

    # -- random-entity round-trip table (>=20 entities x 9 locales) ----------
    rng = random.Random(SEED)
    proof_rows = []
    for kind, n in SAMPLE_N.items():
        _, rows = drafts[kind]
        for r in rng.sample(rows, min(n, len(rows))):
            rid = r["id"]
            rec = {"kind": kind, "id": rid, "locales": {}}
            all9_name = True
            for loc in LOCALES:
                sheet, fields = KINDS[kind]
                name_v = idx[loc][sheet].get(rid, {}).get("name")
                rec["locales"][loc] = {
                    "name": name_v,
                    "description": idx[loc][sheet].get(rid, {})
                                             .get(fields[-1])
                    if len(fields) > 1 else None}
                if not name_v:
                    all9_name = False
            rec["all9_name_resolves"] = all9_name
            proof_rows.append(rec)
    report["proof"] = {
        "sample_sizes": SAMPLE_N,
        "entities": len(proof_rows),
        "all9_name_resolved": sum(1 for p in proof_rows
                                  if p["all9_name_resolves"]),
        "failures": [p["id"] for p in proof_rows
                     if not p["all9_name_resolves"]],
    }

    # -- identical-across-all-9 sanity signal ---------------------------------
    ident = 0
    total_named_cells = 0
    for kind, (sheet, _) in KINDS.items():
        _, rows = drafts[kind]
        for r in rows:
            vals = [idx[l][sheet].get(r["id"], {}).get("name") for l in LOCALES]
            if vals[0]:
                total_named_cells += 1
                if all(v == vals[0] for v in vals):
                    ident += 1
    report["identical_across_9_names"] = {"count": ident,
                                          "of_en_named": total_named_cells}

    # -- emit overlays ---------------------------------------------------------
    OUT_LOCALES.mkdir(parents=True, exist_ok=True)
    overlay_stats = {}
    for loc in LOCALES:
        locdir = OUT_LOCALES / loc
        locdir.mkdir(parents=True, exist_ok=True)
        overlay_stats[loc] = {}
        for kind, (sheet, fields) in KINDS.items():
            _, rows = drafts[kind]
            out = {}
            for r in sorted(rows, key=lambda x: x["id"]):
                rid = r["id"]
                ent = {}
                for col in fields:
                    v = idx[loc][sheet].get(rid, {}).get(col)
                    if v:                       # omit-until-translated: no
                        ent[FIELD_ALIAS[col]] = v   # filler, no other locale
                if ent:
                    out[rid] = ent
            (locdir / f"{kind}.json").write_text(
                json.dumps(out, ensure_ascii=False, indent=1,
                           sort_keys=True) + "\n", encoding="utf-8")
            overlay_stats[loc][kind] = len(out)
    report["overlay_entity_counts"] = overlay_stats

    # -- availability jsonl ----------------------------------------------------
    OUT_RELINKS.mkdir(parents=True, exist_ok=True)
    with (OUT_RELINKS / "locale_availability.jsonl").open(
            "w", encoding="utf-8", newline="\n") as f:
        for row in sorted(avail, key=lambda x: (x["kind"], x["id"])):
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    # -- filler-class counts (en-present but L-absent) ------------------------
    fillers = {k: {loc: 0 for loc in LOCALES} for k in KINDS}
    for kind, (sheet, fields) in KINDS.items():
        _, rows = drafts[kind]
        for r in rows:
            rid = r["id"]
            for loc in LOCALES:
                if loc == PIVOT:
                    continue
                for col in fields:
                    en_ok = bool(idx[PIVOT][sheet].get(rid, {}).get(col))
                    l_ok = bool(idx[loc][sheet].get(rid, {}).get(col))
                    if en_ok and not l_ok:
                        fillers[kind][loc] += 1
    report["filler_class_cells"] = fillers
    report["duplicate_row_ids"] = dups_all
    report["sheet_entry_counts_en"] = {
        sheet: len(idx["en"].get(sheet, {})) for _, (sheet, _) in KINDS.items()}
    report["draft_vs_bridge_ids"] = {}
    for kind, (sheet, _) in KINDS.items():
        _, rows = drafts[kind]
        ids = {r["id"] for r in rows}
        bridge_ids = set(idx["en"].get(sheet, {}))
        report["draft_vs_bridge_ids"][kind] = {
            "draft": len(ids), "bridge_sheet_entries": len(bridge_ids),
            "draft_not_in_bridge": len(ids - bridge_ids),
            "bridge_not_in_draft": len(bridge_ids - ids)}

    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
