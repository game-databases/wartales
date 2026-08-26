#!/usr/bin/env python3
"""Locale-bridge dig (wartales digs 2 + 14): textKey -> export_<locale>.xml
addressing; per-locale overlays + locale_availability.jsonl for ALL CDB
kinds with text leaves; texts_<l>.xml UI-string layer; R5 fr-vintage
buildid-fallback stamping.

Run:  python pipeline/tools/locale_bridge_dig.py
Read-only inputs:
  extracted/data/_draft/<kind>.jsonl                 (dig-1/3/7 datasets)
  extracted/harvest/_lang-bridge/export_<locale>.xml (9 locales)
  extracted/harvest/_lang-bridge/texts*.xml          (master fr + 8 locales)
Writes:
  extracted/locales/<locale>/<kind>.json      overlays, all kinds x 9
  extracted/locales/ui/<locale>.json          site-chrome namespace (fr
                                              sourced from master texts.xml)
  extracted/locales/ui/_inventory.json        group inventory + coverage
  extracted/relinks/locale_availability.jsonl one row per kind x entity
  extracted/relinks/locale_availability.meta.json  per-locale stamp table
                                              (R5 rule; never invents stamps)
  output/_dig-locale-wave2/report.json        measured proofs (scratch)

Two resolution mechanisms (dig 14):
  A. ref-driven -- every draft kind whose rows carry structured textKey
     refs. Nested CDB lists resolve positionally: subSheet segments map to
     <seg><line{i}> chains in file order, exactly as cdb_emit walked them;
     the k-th array index of the draft becomes line{k}.
     r2 extension (verify-dig14-b B1): prose in typeStr-17 struct columns
     that NO ref addresses (notify props.texts family) emits under its
     verbatim export path key -- see FALLBACK_TEXT_PATTERNS; frozen
     wave-1 kinds are excluded (byte-freeze) and their measured strays
     stay a ledgered residual.
  B. id-join structural -- seven kinds whose prose lives in typeStr-17
     structs or datafile-backed rows (place/group/element datafile-backed;
     battle/fiefPlace/fiefAdministration/fiefMission struct columns). Their
     drafts hold dev-pivot French inline and carry no refs; the export side
     holds the translated leaves. Resolved by joining draft ids to export
     entry ids (proven total on the export side) and flattening each
     entry's leaves; dotted tag names kept verbatim, line<N> normalized to
     [k]. r2 fix (verify-dig14-b M1): flatten_struct counts occurrences
     PER ELEMENT -- the r1 shared counters dict dropped repeated tags at
     index>=1 across sibling <lineN> wrappers (12,295 cell-slots).
UI layer r2 (verify-dig14-b M3): nested <g> groups are inventoried and
emitted under full outer/inner/id keys; the fr-vintage id-less rows stay
unaddressable and account for the measured en-fr key delta.
Deterministic: fixed RNG seed, sorted iteration everywhere, no wall-clock
in emitted artifacts.
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
SCRATCH = PACK / "output/_dig-locale-wave2"

LOCALES = ["en", "fr", "de", "es", "pl", "pt-BR", "ru", "ko", "zh"]
PIVOT = "en"                      # market pivot (spec.md locales.canonical)
KINDS = {"item": ("item", ["name", "desc"]),
         "skill": ("skill", ["name", "desc"]),
         "class": ("unitClass", ["name"])}   # wave-1 pins (byte-compatible)
FIELD_ALIAS = {"name": "name", "desc": "description"}   # top-level only
SEED = 20318128                   # client buildid, deterministic samples
SAMPLE_N = {"item": 30, "skill": 15, "class": 10}   # >=20 required by brief
NEW_SAMPLE_N = 3                  # round-trip sample per dig-14 kind
BUILDID = "20318128"              # pack buildid; R5 fallback stamp source

# dig 14 -- kinds whose text lives OUTSIDE localizable columns (mechanism B)
STRUCT_KINDS = {
    # kind                designated name field(s) on the flattened export path
    "place":              ["world.name"],
    "group":              ["props.name"],
    "element":            ["npc.name"],
    "battle":             ["props.name"],
    "fiefPlace":          ["names.defaultName"],
    "fiefAdministration": ["inf.name"],
    "fiefMission":        ["text.title"],
}
NAME_PREFERENCE = ("name", "title")   # mechanism-A namedLocales pick
UI_SOURCE = [("fr", "texts.xml")] + \
    [(loc, f"texts_{loc}.xml") for loc in LOCALES if loc != "fr"]

# dig 14 -- prose-column vocabulary per mechanism-B sheet, derived from the
# complete wildcard-shape enumeration of export_en.xml (every shape listed;
# anything NOT matching is structure: sub-row wrappers and named rows).
# Text cells take their FULL raw span, so inline markup (<br/>, <img .../>,
# escaped rich-text) stays verbatim per locale-key-convention §2.
def _pats(*exprs):
    return [re.compile("^" + e + "$") for e in exprs]

STRUCT_TEXT_PATTERNS = {
    "place": _pats(r"world\.name", r"props\.shortenedName",
                   r"props\.sport\.rules\[\d+\]\.desc"),
    "group": _pats(r"props\.(?:name|bountyDesc|desc)"),
    "element": _pats(
        r"npc\.name",
        r"items\.desc",
        r"dialog\.[^.\[\]]+\.text",
        r"dialog\.[^.\[\]]+\.choices\[\d+\]\.props\."
        r"(?:customTxt|disableReason|tipText)",
        r"dialog\.[^.\[\]]+\.choices\[\d+\]\.gains\.customDesc"
        r"\[\d+\]\.text",
        r"props\.goals\[\d+\]\.title",
        r"props\.goals\[\d+\]\.props\.helpTip",
        r"props\.goals\[\d+\]\.props\.helpTips\[\d+\]\.text"),
    "battle": _pats(r"props\.name"),
    "fiefPlace": _pats(r"names\.(?:defaultName|districtName|pluralName)",
                       r"props\.effects\[\d+\]\.desc"),
    "fiefAdministration": _pats(r"inf\.(?:name|desc|shortName)"),
    "fiefMission": _pats(r"text\.(?:title|desc)"),
}

# dig 14 r2 -- refless inline-prose columns in mechanism-A kinds (the
# verify-dig14-b B1 class). CastleDB marks only some columns localizable,
# but typeStr-17 struct columns of A-kinds rows also carry dev-pivot prose
# that the exporter translates per locale (notify `props.texts` is the
# emblematic family: the draft's only ref points at a `title` leaf the
# exporter never writes, while the translated text sits in
# <props.texts><lineN><text>). Vocabulary pinned from the complete
# wildcard-shape enumeration of stray non-empty leaves across ALL NINE
# locales (every shape listed; anything else is structure or markup
# fragments inside a cell span). Cells are emitted only where the entity's
# OWN refs do not already cover the path template, so nested-ref kinds
# (confessions/mission/tutorial) gain nothing. Frozen wave-1 kinds are
# excluded entirely (byte-freeze); their measured strays stay a ledgered
# residual (FROZEN_KIND_STRAYS).
FALLBACK_TEXT_PATTERNS = {
    "bonus": _pats(r"props\.(?:title|additionalText|negativeDesc)"),
    "counter": _pats(r"props\.(?:songTitle|title|titleWoman)"),
    "fiefAlignment": _pats(r"names\.(?:name|fullName)"),
    "fiefEvent": _pats(r"consequences\.descOverrides\.once",
                       r"consequences\.effects\[\d+\]\.desc",
                       r"params\.[^.\[\]]+\.emptyText"),
    "groupType": _pats(r"descs\.[^.\[\]]+",
                       r"props\.tavern\.(?:name|desc)"),
    "itemType": _pats(r"props\.nameCraftCategory"),
    "notify": _pats(r"props\.texts\[\d+\]\.text",
                    r"props\.(?:actionTip|stackDesc|stackTitle)"),
    "region": _pats(r"setting\.(?:title|desc)"),
    "startChoice": _pats(r"props\.troopNames\[\d+\]\.name"),
    "trait": _pats(r"props\.tavern\.desc"),
}

# Measured-but-NOT-emitted stray prose in the byte-frozen wave-1 kinds
# (recorded in the report so nothing is silently dropped; emitting would
# change frozen overlay artifacts, which needs an owner call).
FROZEN_KIND_STRAYS = {
    "item": _pats(r"props\.actionTitle", r"tool\.preventRemove"),
    "skill": _pats(r"props\.(?:descPassiveGroup|playerDesc)"),
}

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


# ---------------------------------------------------- dig 14: tree parser --
_TAGOPEN = re.compile(r"<(?P<close>/)?(?P<tag>[A-Za-z_][\w.\-]*)"
                      r"(?P<attrs>[^<>]*?)?(?P<self>/)?>")


class Node:
    __slots__ = ("tag", "attrs", "start", "end", "children", "order")

    def __init__(self, tag, attrs, start):
        self.tag = tag
        self.attrs = attrs
        self.start = start              # offset just past the open tag
        self.end = None                 # offset just before the closing tag
        self.children: dict[str, list["Node"]] = {}
        self.order: list["Node"] = []

    def add(self, child: "Node"):
        self.children.setdefault(child.tag, []).append(child)
        self.order.append(child)


def parse_tree(path: Path):
    """-> (raw, content_root Node)

    Stack builder over the same raw text the storage tokenizer reads; leaf
    values stay exact raw spans (html.unescape ONCE at access), children
    keep file order and multiplicity. Algorithmically independent of
    parse_export -- together they are the dual-parser proof."""
    raw = path.read_text(encoding="utf-8-sig")
    doc = Node("#doc", {}, 0)
    stack = [doc]
    for m in _TAGOPEN.finditer(raw):
        tag = m.group("tag")
        if tag[0] in "!?":              # prolog/doctype -- not element syntax
            continue
        attrs = {}
        if m.group("attrs"):
            attrs = dict(re.findall(r'([\w.\-]+)="([^"]*)"', m.group("attrs")))
        if m.group("close"):
            top = stack.pop()
            if top.tag != tag:
                raise ValueError(f"{path.name}: </{tag}> at {m.start()} "
                                 f"closes <{top.tag}> (malformed nesting)")
            top.end = m.start()
        elif m.group("self"):
            node = Node(tag, attrs, m.end())
            node.end = m.end()
            stack[-1].add(node)
        else:
            node = Node(tag, attrs, m.end())
            stack[-1].add(node)
            stack.append(node)
    if len(stack) != 1:
        raise ValueError(f"{path.name}: {len(stack) - 1} unclosed elements")
    tops = doc.order
    if len(tops) != 1:
        raise ValueError(f"{path.name}: expected exactly 1 root element, "
                         f"got {[t.tag for t in tops]}")
    return raw, tops[0]


def node_value(raw: str, node: Node) -> str:
    """The game string: exact raw span between the leaf's tags, entities
    unescaped once. Child markup (<br/>, escaped rich-text) stays verbatim."""
    return html.unescape(raw[node.start:node.end])


def n_child(node: "Node | None", tag: str, idx: int = 0) -> "Node | None":
    if node is None:
        return None
    lst = node.children.get(tag)
    return lst[idx] if lst and idx < len(lst) else None


_LINE_RE = re.compile(r"^line\d+$")


def flatten_entry(node: Node, raw: str,
                  prefix: tuple, out: list):
    """Depth-first flatten of an entry subtree into [(components, value)].
    Each component is (tag, line_index_or_None); dotted tags stay ATOMIC
    (a '.' inside a tag is the tag's own name, never a separator); line<N>
    wrappers become index N; repeated same-name wrappers index from their
    second occurrence."""
    counts: dict[str, int] = {}
    for child in node.order:
        rep = counts.get(child.tag, 0)
        counts[child.tag] = rep + 1
        if child.children:                          # wrapper, not a leaf
            line_keys = sorted((k for k in child.children
                                if _LINE_RE.match(k)),
                               key=lambda s: int(s[4:]))
            if line_keys:
                for k in line_keys:
                    for g in child.children[k]:
                        flatten_entry(g, raw,
                                      prefix + ((child.tag, int(k[4:])),),
                                      out)
            elif rep:                               # 2nd+ same-name wrapper
                flatten_entry(child, raw, prefix + ((child.tag, rep),), out)
            else:
                flatten_entry(child, raw, prefix + ((child.tag, None),), out)
        else:
            out.append((prefix + ((child.tag, None if rep == 0 else rep),),
                        node_value(raw, child)))


def _comp(tag: str, idx: "int | None") -> str:
    return f"{tag}[{idx}]" if idx is not None else tag


def render_path(comps: tuple) -> str:
    return ".".join(_comp(t, i) for t, i in comps)


def template_path(comps: tuple) -> str:
    return ".".join(f"{t}[]" if i is not None else t for t, i in comps)


def flatten_root(raw: str, entry: Node) -> dict[str, tuple]:
    """-> {rendered.path: (components, value)}"""
    pairs: list = []
    flatten_entry(entry, raw, (), pairs)
    return {render_path(c): (c, v) for c, v in pairs}


def flatten_struct(entry: Node, raw: str, patterns: list,
                   anomalies: "list | None" = None):
    """Mechanism-B flattener: walk the entry tree; a node whose rendered
    path matches a prose pattern is a TEXT CELL (full raw span -- inline
    markup stays verbatim); everything else is structure to recurse
    through. line<N> children index their wrapper component transparently,
    exactly like scan_leaf_map.

    Counters are PER-ELEMENT (fresh dict for every recursed subtree,
    matching scan_leaf_map's per-frame counters and flatten_entry). The
    dig-14 r1 emit shared one counters dict across sibling <lineN>
    subtrees, so a repeated tag at index>=1 gained a spurious segment
    (…text[1]) missed its prose pattern and was silently dropped
    (verify-dig14-b M1: 12,295 cell-slots); per-element counting keeps
    them."""
    out: dict[str, tuple] = {}

    def rec(node: Node, comps: tuple, counters: dict):
        for ch in node.order:
            m = _LINE_RE.match(ch.tag)
            if m:
                nc = comps[:-1] + ((comps[-1][0], int(m.group(0)[4:])),)
                rec(ch, nc, {})                 # fresh per-line-subtree scope
                continue
            cnt = counters.get(ch.tag, 0)
            counters[ch.tag] = cnt + 1
            c2 = comps + ((ch.tag, None if cnt == 0 else cnt),)
            p = render_path(c2)
            if any(rx.match(p) for rx in patterns):
                v = node_value(raw, ch)
                if p in out and out[p][1] != v and anomalies is not None:
                    anomalies.append(p)
                out[p] = (c2, v)
            else:
                rec(ch, c2, {})

    rec(entry, (), {})
    return out


def raw_path_match(block: str, steps: list[tuple[str, "int | None"]],
                   col: str, want: str) -> "bool | None":
    """Independent raw-bytes extraction along an explicit step list.
    True  = a <col> leaf at that address unescapes exactly to `want`
    False = <col> leaves exist at the address but none matches
    None  = the address carries no <col> leaf"""
    pos = 0
    for tag, li in steps:
        m = re.compile("<" + re.escape(tag) + ">").search(block, pos)
        if m is None:
            return None
        pos = m.end()
        if li is not None:
            ml = re.compile("<line" + str(li) + ">").search(block, pos)
            if ml is None:
                return None
            pos = ml.end()
    found = matched = False
    while True:
        m2 = re.compile(r"<([\w.\-]+)(/?)>").search(block, pos)
        if m2 is None:
            break
        tag, slash = m2.group(1), m2.group(2)
        if slash:                           # self-closing leaf
            start = end = m2.end()
            pos = m2.end()
        else:
            close = re.compile(r"</" + re.escape(tag) + r">").search(
                block, m2.end())
            if close is None:
                pos = m2.end()
                continue
            start, end = m2.end(), close.start()
            pos = close.end()
        if tag == col:
            found = True
            if html.unescape(block[start:end]) == want:
                matched = True
                break
    return None if not found else matched


def _scan_attrs(inner: str) -> dict[str, str]:
    """Quote-aware attribute parse of everything between '<tag' and '>'."""
    attrs: dict[str, str] = {}
    i, n = 0, len(inner)
    while i < n:
        while i < n and (inner[i].isspace() or inner[i] == "/"):
            i += 1
        if i >= n:
            break
        eq = inner.find("=", i)
        if eq == -1:
            break
        key = inner[i:eq].strip()
        q = inner.find('"', eq + 1)
        qe = inner.find('"', q + 1) if q != -1 else -1
        if qe == -1:
            break
        attrs[key.lstrip("/")] = inner[q + 1:qe]
        i = qe + 1
    return attrs


def _collapse(comps: tuple) -> tuple:
    """Canonical component form shared with flatten_entry: a literal
    <lineN> child collapses onto its wrapper's component as the index
    ((X,None),(lineN,N)) -> (X,N)."""
    out: list = []
    for tg, ix in comps:
        m = re.fullmatch(r"line(\d+)", tg)
        if m and out and out[-1][1] is None:
            out[-1] = (out[-1][0], int(m.group(1)))
            continue
        out.append((tg, ix))
    return tuple(out)


def _sheet_prose_pats(sheet: "str | None"):
    """Prose-pattern vocabulary of a CDB sheet: mechanism-B struct sheets
    plus (dig 14 r2) the refless inline-prose families of A kinds."""
    return STRUCT_TEXT_PATTERNS.get(sheet) or \
        FALLBACK_TEXT_PATTERNS.get(sheet)


def scan_leaf_map(path: Path):
    """-> (raw, leaves, ui_leaves)

    Second, algorithmically independent extractor: NO regex tokenizer --
    quote-aware str.find scanning, an explicit stack, per-parent occurrence
    counters, and line<N> indices recorded during descent. Every leaf's
    entity-decoded span lands in
        leaves[(sheet, entry_tag, rendered_path)] -> [values]
    (list: duplicate entry tags in the fr vintage append, they never
    overwrite). texts_*.xml roots are keyed
        ui_leaves[(group_path_or_None, t_id)] -> [values]; the group path
    is the full '/'-joined chain of <g id> ancestors (nested groups
    included, verify-dig14-b M3).
    Shares no code with parse_tree/parse_export; agreement between the two
    on every emitted string is the dig-14 dual-extractor proof."""
    raw = path.read_text(encoding="utf-8-sig")
    leaves: dict[tuple, list] = {}
    ui_leaves: dict[tuple, list] = {}
    # stack entry: [tag, content_start, comps, counters, has_kids,
    #               gpath(tuple of <g id> ancestors), uikey]
    stack: list[list] = []
    cur_sheet = None
    cur_entry = None
    i = 0
    while True:
        lt = raw.find("<", i)
        if lt == -1:
            break
        if raw.startswith("<!", lt) or raw.startswith("<?", lt):
            j = raw.find(">", lt)
            if j == -1:
                break
            i = j + 1
            continue
        gt = raw.find(">", lt)
        if gt == -1:
            break
        inner = raw[lt + 1:gt]
        i = gt + 1
        if inner.startswith("/"):
            tag = inner[1:].strip()
            if not stack or stack[-1][0] != tag:
                raise ValueError(f"{path.name}: </{tag}> at {lt} mismatches "
                                 f"stack top "
                                 f"{stack[-1][0] if stack else None}")
            t, cs, comps, _cnt, kids, _gpath, uikey = stack.pop()
            if stack:
                stack[-1][4] = True          # parent now has children
            if t == "sheet":
                cur_sheet = None
                cur_entry = None
            elif stack and stack[-1][0] == "sheet" and t == cur_entry:
                cur_entry = None             # next sibling entry takes over
            val = html.unescape(raw[cs:lt])
            if cur_sheet is not None and cur_entry is not None:
                rpath = ".".join(
                    _comp(tg, ix) for tg, ix in _collapse(comps)[1:])
                pats = _sheet_prose_pats(cur_sheet)
                # a prose-pattern cell records its FULL span even when it
                # carries inline-markup children; other nodes record only
                # when childless
                if not kids or (pats and any(rx.match(rpath)
                                             for rx in pats)):
                    leaves.setdefault(
                        (cur_sheet, cur_entry, rpath), []).append(val)
            elif uikey is not None:
                # <t> values are always text cells, markup included
                ui_leaves.setdefault(uikey, []).append(val)
            continue
        selfclose = inner.endswith("/")
        sp = inner.split(None, 1)
        tag = sp[0]
        attrs = _scan_attrs(sp[1].rstrip("/")) if len(sp) > 1 else {}
        if stack:
            parent = stack[-1]
            m = re.fullmatch(r"line(\d+)", tag)
            if m:
                # <lineN> is transparent: it INDEXES its wrapper element,
                # rewriting the parent's own component in place; the line
                # element shares the corrected comps (children inherit).
                idx = int(m.group(1))
                pcomps = parent[2]
                parent[2] = pcomps[:-1] + ((pcomps[-1][0], idx),)
                comps = parent[2]
            else:
                cnt = parent[3].get(tag, 0)
                parent[3][tag] = cnt + 1
                comp = (tag, None if cnt == 0 else cnt)
                comps = parent[2] + (comp,)
            gpath = parent[5]
        else:
            comps, gpath = (), ()
        if tag == "sheet":
            if not selfclose:
                cur_sheet = attrs.get("name")
                cur_entry = None
                stack.append([tag, gt + 1, (), {}, False, (), None])
            continue
        if selfclose:
            if cur_sheet is not None and cur_entry is not None:
                rpath = ".".join(
                    _comp(tg, ix) for tg, ix in _collapse(comps)[1:])
                pats = _sheet_prose_pats(cur_sheet)
                if not pats or any(rx.match(rpath) for rx in pats):
                    leaves.setdefault(
                        (cur_sheet, cur_entry, rpath), []).append("")
            continue
        if cur_sheet is not None and cur_entry is None and \
                stack and stack[-1][0] == "sheet":
            cur_entry = tag
        uikey = None
        if cur_sheet is None and tag == "t":      # texts-file namespace
            tid = attrs.get("id") or attrs.get("_id")
            if tid is not None:
                uikey = ("/".join(gpath) if gpath else None, tid)
        if tag == "g":
            gpath = gpath + (attrs.get("id", "?"),)
        stack.append([tag, gt + 1, comps, {}, False, gpath, uikey])
    return raw, leaves, ui_leaves


# ------------------------------------------------------------------ drafts --
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


def iter_refs(obj, arrays):
    """Yield (ref, enclosing_array_indices) over a draft row in document
    order. cdb_emit guarantees: a ref nested inside k code-8 lists carries
    a subSheet with exactly k '@'-segments naming those lists in order."""
    if isinstance(obj, dict):
        tk = obj.get("textKey")
        if isinstance(tk, dict) and "bridge" in tk:
            yield tk, tuple(arrays)
        for v in obj.values():
            yield from iter_refs(v, arrays)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from iter_refs(v, arrays + [i])


def discover_ref_kinds():
    """All draft datasets carrying textKey refs -> {kind: (sheet, rows)}."""
    found = {}
    for p in sorted(DRAFT.glob("*.jsonl")):
        kind = p.stem
        if kind == "worldmap_overlays":
            continue                     # JSON sidecar, not a dataset
        meta, rows = load_draft(kind)
        if any(True for r in rows for _ in iter_refs(r, [])):
            found[kind] = (meta["sourceSheet"], rows)
    return found


def template_of(tk: dict, arr_names: tuple) -> str:
    """Field-path template for availability: subSheet segments become
    `seg[]` levels, the leaf column closes the path; top-level desc keeps
    its site alias (wave-1 schema parity)."""
    segs = tk["subSheet"].split("@")[1:] if tk.get("subSheet") else []
    if not segs:
        return FIELD_ALIAS.get(tk["column"], tk["column"])
    return "".join(f"{s}[]" for s in segs) + tk["column"]


# ------------------------------------------------------------------- main --
def main() -> int:
    report: dict = {"locales": LOCALES, "seed": SEED, "buildId": BUILDID}

    # -- wave-1 parser over all 9 bridges (headers + duplicate census) -------
    idx: dict[str, dict] = {}
    headers: dict[str, dict] = {}
    dups_all: list[str] = []
    for loc in LOCALES:
        h, sheets, dups = parse_export(BRIDGE / f"export_{loc}.xml")
        headers[loc] = h
        idx[loc] = sheets
        dups_all += [f"{loc}:{d}" for d in dups]
    report["duplicate_row_ids"] = dups_all
    report["headers"] = headers

    # -- dig 14: algorithm-independent tree parse of every locale ------------
    trees: dict[str, tuple[str, Node]] = {}
    for loc in LOCALES:
        trees[loc] = parse_tree(BRIDGE / f"export_{loc}.xml")

    def tree_sheets(loc: str) -> dict[str, Node]:
        _, cdb = trees[loc]
        return {sh.attrs.get("name"): sh for sh in cdb.order}

    tsheets = {loc: tree_sheets(loc) for loc in LOCALES}

    # -- dual-parser structure proof (en): tree builder vs ElementTree -------
    et_en = parse_export_et(BRIDGE / "export_en.xml")

    def et_leaf_paths(el, comps: tuple, acc: set):
        """Leaf-path signature over the SAME component grammar as
        flatten_entry/scan_leaf_map: <lineN> is transparent and indexes its
        wrapper component; repeated named wrappers index from 2nd."""
        kids: dict[str, list] = {}
        for c in el:
            kids.setdefault(c.tag, []).append(c)
        if not kids:
            acc.add(render_path(comps) or "(self)")
            return
        counters: dict[str, int] = {}
        for c in el:
            m = _LINE_RE.match(c.tag)
            if m:
                nc = comps[:-1] + ((comps[-1][0], int(m.group(0)[4:])),)
                et_leaf_paths(c, nc, acc)
            else:
                cnt = counters.get(c.tag, 0)
                counters[c.tag] = cnt + 1
                et_leaf_paths(c, comps + ((c.tag, None if cnt == 0 else cnt),
                                          ), acc)

    dp: dict[str, dict] = {}
    for sname, sh_node in sorted(tsheets["en"].items()):
        if sname in STRUCT_TEXT_PATTERNS:
            # mechanism-B sheets are proven by tree-vs-scanner agreement
            # instead (their prose cells carry inline children, which the
            # childless-only ET signature cannot name)
            continue
        sig_tree: dict[str, set] = {}
        for ent in sh_node.order:
            sig_tree.setdefault(ent.tag, set()).update(
                flatten_root(trees["en"][0], ent))
        sig_et: dict[str, set] = {}
        for rid, cols in et_en.get(sname, {}).items():
            acc: set = set()
            for col_tag, col_el in cols.items():
                et_leaf_paths(col_el, ((col_tag, None),), acc)
            sig_et[rid] = acc
        mism = {rid for rid in sig_tree
                if rid not in sig_et or sig_tree[rid] != sig_et[rid]}
        ex = []
        for rid in sorted(mism)[:3]:
            only_t = sorted(sig_tree.get(rid, set()) -
                            sig_et.get(rid, set()))[:2]
            only_e = sorted(sig_et.get(rid, set()) -
                            sig_tree.get(rid, set()))[:2]
            ex.append({"id": rid, "only_tree": only_t, "only_et": only_e})
        dp[sname] = {"entries_tree": len(sig_tree),
                     "entries_et": len(sig_et),
                     "row_set_equal": set(sig_tree) == set(sig_et),
                     "path_mismatches": len(mism),
                     "examples": ex}
    spot = ("confessions", "tutorial")      # >=2 kinds required by brief
    report["dual_parser_structure_en"] = {
        "sheets_compared": len(dp),
        "sheets_skipped_struct": sorted(STRUCT_TEXT_PATTERNS),
        "skipped_reason": "mechanism-B sheets proven by tree-vs-scanner "
                          "agreement on every emitted cell instead",
        "sheets_row_set_mismatch": [s for s, v in dp.items()
                                    if not v["row_set_equal"]],
        "sheets_with_path_mismatch": sum(1 for v in dp.values()
                                         if v["path_mismatches"]),
        "spotcheck_kinds": {k: dp[k] for k in spot},
        "per_sheet": {s: v for s, v in dp.items() if v["path_mismatches"]},
    }

    # ==================================================== mechanism A =======
    ref_kinds = discover_ref_kinds()
    report["ref_kinds"] = {
        k: {"sheet": s, "rows": len(rows),
            "refs": sum(1 for r in rows for _ in iter_refs(r, []))}
        for k, (s, rows) in sorted(ref_kinds.items())}

    # dig 14: independent scanner maps (verification side)
    scans: dict[str, tuple] = {}
    for loc in LOCALES:
        _, leafmap, _ui = scan_leaf_map(BRIDGE / f"export_{loc}.xml")
        scans[loc] = leafmap

    a_state = {k: {loc: {"ok": 0, "empty": 0, "missing": 0}
                   for loc in LOCALES} for k in ref_kinds}
    a_raw = {k: {loc: {"matched": 0, "mismatched": 0, "absent": 0}
                 for loc in LOCALES} for k in ref_kinds}
    a_overlay = {loc: {} for loc in LOCALES}          # loc -> kind -> id -> v
    a_ok_tpl: dict[str, dict[str, dict[str, set]]] = {
        k: {loc: {} for loc in LOCALES} for k in ref_kinds}
    a_named: dict[str, dict[str, dict[str, bool]]] = {
        k: {loc: {} for loc in LOCALES} for k in ref_kinds}
    a_missing_split = {k: {loc: {"absent_entity": 0,
                                 "absent_entity_cells": 0,
                                 "partial_cell": 0}
                           for loc in LOCALES} for k in ref_kinds}
    filler_instances = {k: {loc: 0 for loc in LOCALES}
                        for k in ref_kinds}
    en_states: dict[tuple, str] = {}
    a_cand: dict[str, dict[str, list]] = {}
    raw_examples: list[str] = []
    # dig 14 r2 -- refless inline-prose emission (verify-dig14-b B1):
    # per-entity template sets + raw-span verification counters + the
    # measured-but-frozen stray ledger for the wave-1 kinds.
    a_fb_tpl: dict[str, dict[str, dict[str, set]]] = {
        k: {loc: {} for loc in LOCALES} for k in ref_kinds}
    a_fb_ncells: dict[str, dict[str, dict[str, int]]] = {
        k: {loc: {} for loc in LOCALES} for k in ref_kinds}
    a_fb_raw = {k: {loc: {"matched": 0, "mismatched": 0, "absent": 0}
                    for loc in LOCALES} for k in ref_kinds}
    fb_anomalies: list[str] = []
    frozen_stray_ids: dict[str, dict[str, set]] = \
        {k: {loc: set() for loc in LOCALES} for k in FROZEN_KIND_STRAYS}
    frozen_stray_cells: dict[str, dict[str, int]] = \
        {k: {loc: 0 for loc in LOCALES} for k in FROZEN_KIND_STRAYS}

    for kind, (sheet, rows) in sorted(ref_kinds.items()):
        sheet_entries: dict[str, dict] = {}
        for loc in LOCALES:
            sh_node = tsheets[loc].get(sheet)
            sheet_entries[loc] = ({e.tag: e for e in sh_node.order}
                                  if sh_node is not None else {})
        seen_ids: set[str] = set()
        for r in rows:
            rid = r["id"]
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
            row_refs = [(tk, arrs) for tk, arrs in iter_refs(r, [])]
            # wave-1 kinds stay byte-frozen to their dig-2 field sets --
            # e.g. skill.levels refs (80, 74 resolving) are NOT part of the
            # frozen overlay schema; ledgered as a measured residual.
            allowed_cols = (KINDS[kind][1] if kind in KINDS else None)
            a_cand.setdefault(kind, {})[rid] = \
                sorted({template_of(tk, ar) for tk, ar in row_refs
                        if allowed_cols is None or
                        (not ar and tk["column"] in allowed_cols)})

            def transform(obj, arr_names):
                if isinstance(obj, dict):
                    tk = obj.get("textKey")
                    if isinstance(tk, dict) and "bridge" in tk:
                        if allowed_cols is not None and \
                                (arr_names or tk["column"]
                                 not in allowed_cols):
                            return None
                        return ("__REF__", tk, arr_names)
                    out = {}
                    for kk, vv in obj.items():
                        rv = transform(vv, arr_names)
                        if rv is not None:
                            out[kk] = rv
                    return out or None
                if isinstance(obj, list):
                    lst = []
                    for i, vv in enumerate(obj):
                        rv = transform(vv, arr_names + (i,))
                        if rv is not None:
                            lst.append(rv)
                    return lst or None
                return None                              # payload scalars

            skeleton = transform(r, ())
            # path templates already addressed by this row's own refs
            # (component-tuple form; a ref's subSheet segments map onto the
            # same seg[] chain flatten_struct renders)
            cov_t: set = set()
            for tk, _ar in row_refs:
                segs = (tk["subSheet"].split("@")[1:]
                        if tk.get("subSheet") else [])
                cov_t.add(tuple(f"{s}[]" for s in segs) + (tk["column"],))
            fb_pats = (None if kind in KINDS
                       else FALLBACK_TEXT_PATTERNS.get(kind))
            fs_pats = FROZEN_KIND_STRAYS.get(kind)
            for loc in LOCALES:
                ok_tpls: set = set()
                named_ok = False
                missing_here = absent_ent = partial = absent_contrib = 0
                ent_missing_any = False

                def resolve(obj, arr_names):
                    nonlocal named_ok, missing_here, absent_ent, partial
                    nonlocal ent_missing_any, absent_contrib
                    if isinstance(obj, tuple) and obj and obj[0] == "__REF__":
                        _, tk, ar = obj
                        segs = (tk["subSheet"].split("@")[1:]
                                if tk.get("subSheet") else [])
                        entry = n_child(tsheets[loc].get(tk["sheet"]),
                                        tk["row"])
                        node = entry
                        for seg, ai in zip(segs, ar):
                            node = n_child(n_child(node, seg), f"line{ai}")
                        leaf = n_child(node, tk["column"])
                        v = node_value(trees[loc][0], leaf) \
                            if leaf is not None else None
                        state = ("ok" if v else "empty") \
                            if v is not None else "missing"
                        a_state[kind][loc][state] += 1
                        tpl = template_of(tk, ar)
                        state_key = (tk["sheet"], tk["row"],
                                     tk.get("subSheet"), tk["column"], ar)
                        if loc == PIVOT:
                            en_states[state_key] = state
                        elif state == "missing" and \
                                en_states.get(state_key) == "ok":
                            filler_instances[kind][loc] += 1
                        if state == "ok":
                            ok_tpls.add(tpl)
                            if not ar and tk["column"] in NAME_PREFERENCE:
                                named_ok = True
                            comps = tuple(zip(segs, ar)) + \
                                ((tk["column"], None),)
                            rkey = (tk["sheet"], tk["row"],
                                    ".".join(_comp(tg, ix)
                                             for tg, ix in comps))
                            got = scans[loc].get(rkey, [])
                            if v in got:
                                a_raw[kind][loc]["matched"] += 1
                            elif got:
                                a_raw[kind][loc]["mismatched"] += 1
                                if len(raw_examples) < 8:
                                    raw_examples.append(
                                        f"{loc}:{kind}/{rid}/"
                                        f"{tk['column']}:mismatch")
                            else:
                                a_raw[kind][loc]["absent"] += 1
                                if len(raw_examples) < 8:
                                    raw_examples.append(
                                        f"{loc}:{kind}/{rid}/"
                                        f"{tk['column']}:absent")
                        elif state == "missing":
                            ent_missing_any = True
                            missing_here += 1
                        return v if v else None
                    if isinstance(obj, dict):
                        out = {}
                        for kk, vv in obj.items():
                            rv = resolve(vv, arr_names)
                            if rv is not None:
                                out[kk] = rv
                        return out or None
                    if isinstance(obj, list):
                        lst = []
                        for vv in obj:
                            rv = resolve(vv, arr_names)
                            if rv is not None:
                                lst.append(rv)
                        return lst or None
                    return None

                body = resolve(skeleton, ()) if skeleton else None
                if body and "desc" in body:
                    # site alias (wave-1 schema parity, convention §2):
                    # top-level desc -> description; nested descs stay
                    # verbatim identifiers
                    body["description"] = body.pop("desc")

                # ---- dig 14 r2: refless inline-prose cells (B1) --------
                # prose the refs never address (e.g. notify props.texts)
                # emits under its verbatim export path key; covered paths,
                # blanks and frozen kinds are excluded. Every emitted cell
                # is raw-span verified against scan_leaf_map like B cells.
                fb_cells: dict = {}
                fb_tpls: set = set()
                if fb_pats is not None:
                    ent_node = sheet_entries[loc].get(rid)
                    if ent_node is not None:
                        fb_full = flatten_struct(ent_node, trees[loc][0],
                                                 fb_pats, fb_anomalies)
                        for p, (c2, v) in sorted(fb_full.items()):
                            if not v.strip():
                                continue      # omit-until-translated
                            tpl_c = tuple(f"{t}[]" if ix is not None else t
                                          for t, ix in c2)
                            if tpl_c in cov_t:
                                continue      # refs already address it
                            fb_cells[p] = v
                            fb_tpls.add(re.sub(r"\[\d+\]", "[]", p))
                            got = scans[loc].get((sheet, rid, p), [])
                            if v in got:
                                a_fb_raw[kind][loc]["matched"] += 1
                            elif got:
                                a_fb_raw[kind][loc]["mismatched"] += 1
                            else:
                                a_fb_raw[kind][loc]["absent"] += 1
                    if fb_cells:
                        body = dict(body) if body else {}
                        body.update(fb_cells)
                if fs_pats is not None:
                    fent = sheet_entries[loc].get(rid)
                    if fent is not None:
                        ffl = flatten_struct(fent, trees[loc][0], fs_pats)
                        hit = [p for p, (_c, v) in ffl.items() if v.strip()]
                        if hit:
                            frozen_stray_ids[kind][loc].add(rid)
                            frozen_stray_cells[kind][loc] += len(hit)

                if body:
                    a_overlay[loc].setdefault(kind, {})[rid] = body
                a_ok_tpl[kind][loc][rid] = ok_tpls
                a_fb_tpl[kind][loc][rid] = fb_tpls
                if fb_cells:
                    a_fb_ncells[kind][loc][rid] = len(fb_cells)
                a_named[kind][loc][rid] = named_ok
                if ent_missing_any:
                    if missing_here == len(row_refs):
                        absent_ent += 1
                        absent_contrib += missing_here
                    else:
                        partial += missing_here
                a_missing_split[kind][loc]["absent_entity"] += absent_ent
                a_missing_split[kind][loc]["absent_entity_cells"] += \
                    absent_contrib
                a_missing_split[kind][loc]["partial_cell"] += partial

    # ==================================================== mechanism B =======
    b_overlay = {loc: {} for loc in LOCALES}          # loc -> kind -> id -> v
    b_state = {k: {loc: {"ok": 0, "empty": 0, "missing": 0}
                   for loc in LOCALES} for k in STRUCT_KINDS}
    b_raw = {k: {loc: {"matched": 0, "mismatched": 0, "absent": 0}
                 for loc in LOCALES} for k in STRUCT_KINDS}
    b_templates: dict[str, set] = {k: set() for k in STRUCT_KINDS}
    b_name_hits: dict[str, dict[str, int]] = {
        k: {loc: 0 for loc in LOCALES} for k in STRUCT_KINDS}
    b_export_only: dict[str, dict[str, list]] = {k: {} for k in STRUCT_KINDS}
    b_dup_occ: dict[str, int] = {}

    for kind, name_fields in sorted(STRUCT_KINDS.items()):
        _, rows = load_draft(kind)
        id_counts: dict[str, int] = {}
        for r in rows:
            id_counts[r["id"]] = id_counts.get(r["id"], 0) + 1
        ids_sorted = sorted(id_counts)
        b_dup_occ[kind] = sum(c - 1 for c in id_counts.values()) \
            if max(id_counts.values()) > 1 else 0
        for loc in LOCALES:
            sh = tsheets[loc].get(kind)
            entries = {e.tag: e for e in sh.order} if sh else {}
            b_export_only[kind][loc] = \
                sorted(set(entries) - set(ids_sorted))
            for rid in ids_sorted:
                ent = entries.get(rid)
                if ent is None:
                    continue
                fl_full = flatten_struct(ent, trees[loc][0],
                                         STRUCT_TEXT_PATTERNS[kind],
                                         fb_anomalies)
                if fl_full:
                    fl = {p: v for p, (c, v) in fl_full.items()}
                    b_overlay[loc].setdefault(kind, {})[rid] = fl
                    b_state[kind][loc]["ok"] += len(fl)
                    b_templates[kind].update(
                        template_path(c) for c, _ in fl_full.values())
                    if any(fl.get(nf) for nf in name_fields):
                        b_name_hits[kind][loc] += 1
                    for p, (_c, v) in fl_full.items():
                        got = scans[loc].get((kind, rid, p), [])
                        if v in got:
                            b_raw[kind][loc]["matched"] += 1
                        elif got:
                            b_raw[kind][loc]["mismatched"] += 1
                        else:
                            b_raw[kind][loc]["absent"] += 1

    # ---- availability rows (A + B, one per distinct draft id) --------------
    avail: list[dict] = []
    for kind in sorted(set(ref_kinds) | set(STRUCT_KINDS)):
        if kind in STRUCT_KINDS:
            _, rows = load_draft(kind)
            ids_sorted = sorted({r["id"] for r in rows})
            name_fields = STRUCT_KINDS[kind]
            for rid in ids_sorted:
                # candidates = the entity's OWN templates (union over
                # locales; the nine files are parallel) -- never the whole
                # kind universe (element's ~2.7k named dialog rows would
                # otherwise materialize thousands of booleans per row)
                cands: set = set()
                for loc in LOCALES:
                    fl = b_overlay[loc].get(kind, {}).get(rid, {})
                    cands |= {re.sub(r"\[\d+\]", "[]", p)
                              for p in fl} if fl else set()
                cands_sorted = sorted(cands)
                fld: dict[str, dict[str, bool]] = {}
                available: list[str] = []
                named: list[str] = []
                for loc in LOCALES:
                    fl = b_overlay[loc].get(kind, {}).get(rid, {})
                    tpl_set = ({re.sub(r"\[\d+\]", "[]", p) for p in fl}
                               if fl else set())
                    fld[loc] = {t: t in tpl_set for t in cands_sorted}
                    if fl:
                        available.append(loc)
                    if any(fl.get(nf) for nf in name_fields):
                        named.append(loc)
                avail.append({"kind": kind, "id": rid,
                              "availableLocales": available,
                              "namedLocales": named,
                              "fields": fld})
        else:
            _, rows = ref_kinds[kind]
            seen: set = set()
            for r in rows:
                rid = r["id"]
                if rid in seen:
                    continue
                seen.add(rid)
                has_name_col = any(
                    not ar and tk["column"] in NAME_PREFERENCE
                    for tk, ar in iter_refs(r, []))
                cands = set(a_cand.get(kind, {}).get(rid, []))
                fb_union: set = set()
                for loc in LOCALES:
                    fb_union |= a_fb_tpl[kind][loc].get(rid, set())
                cands = sorted(cands | fb_union)
                if kind in KINDS:
                    # frozen wave-1 row shape: both keys always present
                    cands = ["description", "name"]
                fld: dict[str, dict[str, bool]] = {}
                available: list[str] = []
                named: list[str] = []
                for loc in LOCALES:
                    ok_t = a_ok_tpl[kind][loc].get(rid, set())
                    fb_t = a_fb_tpl[kind][loc].get(rid, set())
                    fld[loc] = {t: (t in ok_t or t in fb_t) for t in cands}
                    if ok_t or fb_t:
                        available.append(loc)
                    nm = a_named[kind][loc].get(rid, False)
                    if nm:
                        named.append(loc)
                    elif not has_name_col:
                        nm = bool(ok_t)
                        if nm:
                            named.append(loc)
                avail.append({"kind": kind, "id": rid,
                              "availableLocales": available,
                              "namedLocales": named,
                              "fields": fld})

    # ---- kind-wide template universes (report sizes only) -------------------
    tpl_universe: dict[str, list] = {}
    for kind in ref_kinds:
        uni: set = set()
        for cand in a_cand.get(kind, {}).values():
            uni.update(cand)
        tpl_universe[kind] = sorted(uni)

    # ---- overlays to disk (pivot first, ids sorted) -------------------------
    OUT_LOCALES.mkdir(parents=True, exist_ok=True)
    all_kinds = sorted(set(ref_kinds) | set(STRUCT_KINDS))
    overlay_stats: dict[str, dict[str, int]] = {}
    for loc in LOCALES:
        locdir = OUT_LOCALES / loc
        locdir.mkdir(parents=True, exist_ok=True)
        overlay_stats[loc] = {}
        for kind in all_kinds:
            src = (b_overlay[loc].get(kind, {}) if kind in STRUCT_KINDS
                   else a_overlay[loc].get(kind, {}))
            out = {rid: src[rid] for rid in sorted(src)}
            (locdir / f"{kind}.json").write_text(
                json.dumps(out, ensure_ascii=False, indent=1,
                           sort_keys=True) + "\n", encoding="utf-8")
            overlay_stats[loc][kind] = len(out)
    report["overlay_entity_counts"] = overlay_stats

    # ---- availability jsonl -------------------------------------------------
    OUT_RELINKS.mkdir(parents=True, exist_ok=True)
    with (OUT_RELINKS / "locale_availability.jsonl").open(
            "w", encoding="utf-8", newline="\n") as f:
        for row in sorted(avail, key=lambda x: (x["kind"], x["id"])):
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True)
                    + "\n")
    report["availability_rows"] = len(avail)
    report["availability_rows_by_kind"] = {
        k: sum(1 for r in avail if r["kind"] == k) for k in all_kinds}

    # ================================================ UI-string layer ========
    def parse_ui(path: Path):
        """-> (strings, top_groups, nested_totals, problems, root_attrs)

        Keys are `id` for top-level <t>, `group/id` inside a top-level
        <g>, and the FULL `outer/inner/id` chain inside nested <g>
        blocks (verify-dig14-b M3: the r1 emit walked only direct
        children, silently excluding 105+ nested groups / their keyed
        strings). Returns per-top-group inventories with nested counts
        so the omission is quantified, not just logged."""
        raw, rootn = parse_tree(path)
        strings: dict[str, str] = {}
        top_groups: dict[str, dict] = {}
        nested = {"groups": 0, "keys": 0}
        problems: list[str] = []
        dup_keys: list[str] = []

        def walk(node: Node, gpath: tuple, top: "str | None"):
            for child in node.order:
                gp = "/".join(gpath) if gpath else "<root>"
                if child.tag == "t":
                    tid = child.attrs.get("id") or child.attrs.get("_id")
                    if tid is None:
                        problems.append(f"{gp}: <t> without id/_id "
                                        f"@{child.start}")
                        continue
                    key = "/".join(gpath + (tid,))
                    if key in strings:
                        dup_keys.append(key)
                    strings[key] = node_value(raw, child)
                    if top is not None:
                        st = top_groups.setdefault(
                            top, {"keys": 0, "nestedGroups": 0,
                                  "nestedKeys": 0})
                        st["keys"] += 1
                        if len(gpath) >= 2:
                            st["nestedKeys"] += 1
                            nested["keys"] += 1
                elif child.tag == "g":
                    gid = child.attrs.get("id", "?")
                    if gpath:
                        # a group below the top level
                        nested["groups"] += 1
                        if top is not None:
                            top_groups[top]["nestedGroups"] += 1
                        walk(child, gpath + (gid,), top)
                    else:
                        top_groups.setdefault(
                            gid, {"keys": 0, "nestedGroups": 0,
                                  "nestedKeys": 0})
                        walk(child, (gid,), gid)
                else:
                    problems.append(f"{gp}: unexpected <{child.tag}>")

        walk(rootn, (), None)
        groups = {g: dict(sorted(st.items()))
                  for g, st in sorted(top_groups.items())}
        return (strings, groups, nested, problems, dup_keys,
                rootn.attrs)

    ui_strings: dict[str, dict[str, str]] = {}
    ui_groups: dict[str, dict[str, dict]] = {}
    ui_nested: dict[str, dict] = {}
    ui_problems: dict[str, list[str]] = {}
    ui_dup_keys: dict[str, list[str]] = {}
    ui_attrs: dict[str, dict] = {}
    for loc, fname in UI_SOURCE:
        st, gr, ne, pr, dk, rat = parse_ui(BRIDGE / fname)
        ui_strings[loc] = st
        ui_groups[loc] = gr
        ui_nested[loc] = ne
        ui_problems[loc] = pr
        ui_dup_keys[loc] = dk
        ui_attrs[loc] = rat

    # exhaustive dual-extractor verification of every UI value: the stored
    # strings come from parse_tree; the check reads scan_leaf_map's
    # independently built (group-path, t-id) map from the same raw bytes.
    # A stored key `outer/inner/tid` maps to ((outer/inner), tid) -- the
    # LAST segment is always the <t> id, the rest the <g id> chain.
    ui_raw = {loc: {"matched": 0, "mismatched": 0, "absent": 0}
              for loc, _ in UI_SOURCE}
    ui_scan: dict[str, dict] = {}
    for loc, fname in UI_SOURCE:
        _, _lm, uil = scan_leaf_map(BRIDGE / fname)
        ui_scan[loc] = uil
    for loc, fname in UI_SOURCE:
        uil = ui_scan[loc]
        for key, want in ui_strings[loc].items():
            parts = key.split("/")
            skey = ("/".join(parts[:-1]) or None, parts[-1])
            got = uil.get(skey, [])
            if want in got:
                ui_raw[loc]["matched"] += 1
            elif got:
                ui_raw[loc]["mismatched"] += 1
            else:
                ui_raw[loc]["absent"] += 1

    pivot_keys = set(ui_strings[PIVOT])
    ui_cov = {}
    for loc, _ in UI_SOURCE:
        ks = set(ui_strings[loc])
        ui_cov[loc] = {
            "strings": len(ks),
            "non_empty": sum(1 for v in ui_strings[loc].values() if v),
            "groupsTopLevel": len(ui_groups[loc]),
            "groupsNested": ui_nested[loc]["groups"],
            "keysInNestedGroups": ui_nested[loc]["keys"],
            "missing_vs_pivot": len(pivot_keys - ks),
            "extra_vs_pivot": len(ks - pivot_keys),
        }
    ui_dir = OUT_LOCALES / "ui"
    ui_dir.mkdir(parents=True, exist_ok=True)
    for loc, _ in UI_SOURCE:
        (ui_dir / f"{loc}.json").write_text(
            json.dumps(ui_strings[loc], ensure_ascii=False, indent=1,
                       sort_keys=True) + "\n", encoding="utf-8")
    inventory = {
        "_meta": {"tool": "pipeline/tools/locale_bridge_dig.py",
                  "seed": SEED, "buildId": BUILDID,
                  "note": "site-chrome i18n namespace, separate from game "
                          "content (localization-architecture §4); fr "
                          "sourced from master texts.xml (dev-pivot "
                          "French, accent-stripped ids). Nested <g> "
                          "groups are INCLUDED since the dig-14 r2 fix "
                          "(verify-dig14-b M3): keys use the full "
                          "outer/inner/id chain; groupInventory.keys "
                          "counts every descendant <t>, nestedKeys those "
                          "below the top level"},
        "totals": ui_cov,
        "groupInventory": [
            {"id": g, **ui_groups[PIVOT][g]}
            for g in sorted(ui_groups[PIVOT])],
        "topLevelKeys": sorted(k for k in ui_strings[PIVOT]
                               if "/" not in k),
        "parseProblems": ui_problems,
        "duplicateKeys": {k: v for k, v in ui_dup_keys.items() if v},
        "rawSpanVerification": ui_raw,
    }
    (ui_dir / "_inventory.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=1, sort_keys=True)
        + "\n", encoding="utf-8")
    report["ui"] = {
        "coverage": ui_cov,
        "nested_totals_per_locale": {loc: ui_nested[loc]
                                     for loc, _ in UI_SOURCE},
        "problems": {k: v for k, v in ui_problems.items() if v},
        "raw_span_verification": ui_raw,
    }

    # ------------------------------------------- R5 stamp table (meta) ------
    def stamp_entry(fname, root_attrs):
        if root_attrs.get("revision"):
            e = {"file": fname, "stampedBy": "export-header"}
            e.update(sorted(root_attrs.items()))
            return e
        return {"file": fname, "stampedBy": "buildid-fallback",
                "buildId": BUILDID}

    stamp_meta = {
        "_meta": {"tool": "pipeline/tools/locale_bridge_dig.py",
                  "buildId": BUILDID, "seed": SEED,
                  "rule": "R5 (orchestrator ruling, 2026-08-26): rows "
                          "sourced from a bridge file with no "
                          "version/revision/date header are stamped "
                          "'buildid-fallback' with the pack buildid "
                          "20318128 -- never invented timestamps. Stamps "
                          "are file-level constants, so the table is keyed "
                          "by source file and locale; a row's stamp "
                          "resolves through the locales it lists."},
        "export": {loc: stamp_entry(f"lang/export_{loc}.xml", headers[loc])
                   for loc in LOCALES},
        "ui": {loc: stamp_entry(f"lang/{fname}", ui_attrs[loc])
               for loc, fname in UI_SOURCE},
    }
    (OUT_RELINKS / "locale_availability.meta.json").write_text(
        json.dumps(stamp_meta, ensure_ascii=False, indent=1,
                   sort_keys=True) + "\n", encoding="utf-8")
    report["stamp_meta"] = {
        loc: stamp_meta["export"][loc]["stampedBy"] for loc in LOCALES}

    # ------------------------------------------------- proofs & summary -----
    drift = {}
    for kind in all_kinds:
        rows_kind = [r for r in avail if r["kind"] == kind]
        bridged = [r for r in rows_kind if r["availableLocales"]]
        drift[kind] = {
            "entities": len(rows_kind), "bridged": len(bridged),
            "drift_absent_everywhere": len(rows_kind) - len(bridged),
            "reconciles": len(bridged) +
            (len(rows_kind) - len(bridged)) == len(rows_kind)}
    report["drift_reconciliation"] = drift

    report["filler_class_instances"] = {
        k: {loc: n for loc, n in v.items() if loc != PIVOT}
        for k, v in filler_instances.items()}

    # ---- exhaustive symmetric filler census (verify-dig14-b M2) -----------
    # EVERY (entity, field-template) whose locale-presence vector is
    # non-uniform across the 9 client locales -- mechanism A refs AND
    # mechanism B struct cells AND r2 inline-prose cells, wave-1 kinds
    # included, BOTH directions (a locale missing a cell the pivot has,
    # and a locale holding a cell the pivot lacks). Replaces the r1
    # ref-only counter above, which was structurally blind to mechanism B
    # and to the fr-extra direction.
    filler_rows: list[dict] = []
    for row in avail:
        fld = row["fields"]
        if not fld:
            continue
        for tpl in sorted(next(iter(fld.values()))):
            present = [loc for loc in LOCALES if fld[loc].get(tpl, False)]
            if not present or len(present) == len(LOCALES):
                continue
            inst = {"kind": row["kind"], "id": row["id"], "template": tpl,
                    "present_in": present}
            if PIVOT in present:
                inst["class"] = "pivot-present-locale-gap"
            elif "fr" in present:
                inst["class"] = "fr-extra"
            else:
                inst["class"] = "extra-without-pivot"
            filler_rows.append(inst)
    by_class: dict[str, int] = {}
    for inst in filler_rows:
        by_class[inst["class"]] = by_class.get(inst["class"], 0) + 1
    report["filler_census"] = {
        "definition": "(entity, field-template) with a non-uniform "
                      "locale-presence vector across the 9 client "
                      "locales, all mechanisms, both directions",
        "total": len(filler_rows),
        "by_class": by_class,
        "kinds": sorted({inst["kind"] for inst in filler_rows}),
        "instances": filler_rows,
    }

    # cell-level reconciliation, every A kind x locale (must all be True)
    recon = {}
    for kind in sorted(ref_kinds):
        total_refs = report["ref_kinds"][kind]["refs"]
        recon[kind] = {}
        for loc in LOCALES:
            st = a_state[kind][loc]
            ms = a_missing_split[kind][loc]
            recon[kind][loc] = {
                "cells_total_matches": (st["ok"] + st["empty"]
                                        + st["missing"]) == total_refs,
                "missing_decomposes": (st["missing"] ==
                                       ms["absent_entity_cells"]
                                       + ms["partial_cell"])}
    report["cell_reconciliation_A"] = {
        k: {"all_true": all(v["cells_total_matches"] and
                            v["missing_decomposes"]
                            for v in recon[k].values()),
            "detail_en": recon[k]["en"]} for k in recon}

    report["raw_span_verification_A"] = {
        k: {loc: a_raw[k][loc] for loc in LOCALES} for k in a_raw}
    report["raw_span_verification_B"] = b_raw
    report["cell_states_A"] = {k: {loc: a_state[k][loc] for loc in LOCALES}
                               for k in a_state}
    report["missing_split_A"] = a_missing_split
    report["raw_examples"] = raw_examples
    report["template_universe_sizes"] = {k: len(v) for k, v in
                                         sorted(tpl_universe.items())}
    report["mechanismB_summary"] = {
        k: {"templates": sorted(b_templates[k]),
            "export_only_ids_per_locale": {
                loc: len(v) for loc, v in b_export_only[k].items()},
            "export_only_examples": b_export_only[k][PIVOT][:5],
            "dup_draft_id_extra_occurrences": b_dup_occ[k],
            "namefield_resolves_en": b_name_hits[k][PIVOT],
            } for k in sorted(STRUCT_KINDS)}

    # random-entity round-trip table (wave-1 sizes + 3 per new kind)
    rng = random.Random(SEED)
    proof_rows = []
    for kind in all_kinds:
        if kind in STRUCT_KINDS:
            _, rows = load_draft(kind)
        else:
            _, rows = ref_kinds[kind]
        pool = sorted({r["id"] for r in rows})
        n = SAMPLE_N.get(kind, NEW_SAMPLE_N)
        for rid in rng.sample(pool, min(n, len(pool))):
            rec = {"kind": kind, "id": rid, "locales": {}}
            all9 = True
            for loc in LOCALES:
                v = (b_overlay[loc].get(kind, {}) if kind in STRUCT_KINDS
                     else a_overlay[loc].get(kind, {})).get(rid)
                rec["locales"][loc] = bool(v)
                all9 &= bool(v)
            rec["resolves_in_all_9"] = all9
            proof_rows.append(rec)
    # failures are listed IN FULL (the r1 emit truncated to 20, hiding the
    # 21st) and each carries its export-entry presence so the drift vs
    # locale-gap classification is reproducible from this artifact alone.
    failure_recs = []
    for p in proof_rows:
        if p["resolves_in_all_9"]:
            continue
        kind = p["kind"]
        shname = kind if kind in STRUCT_KINDS else ref_kinds[kind][0]
        entry_present = {}
        for loc in LOCALES:
            shn = tsheets[loc].get(shname)
            entry_present[loc] = shn is not None and \
                n_child(shn, p["id"]) is not None
        failure_recs.append({
            "entity": f"{kind}/{p['id']}",
            "export_entry_present": entry_present,
            "absent_from_exports_everywhere":
                not any(entry_present.values())})
    report["round_trip_sample"] = {
        "entities": len(proof_rows),
        "all9_resolved": sum(1 for p in proof_rows
                             if p["resolves_in_all_9"]),
        "failures": [f"{p['kind']}/{p['id']}" for p in proof_rows
                     if not p["resolves_in_all_9"]],
        "failure_detail": failure_recs,
        "failures_absent_everywhere":
            sum(1 for f in failure_recs
                if f["absent_from_exports_everywhere"]),
        "failures_with_export_entry_somewhere":
            sum(1 for f in failure_recs
                if not f["absent_from_exports_everywhere"])}

    # ---- dig 14 r2 fix-round evidence --------------------------------------
    fb_summary: dict[str, dict] = {}
    for k in sorted(ref_kinds):
        cells_per_loc = {loc: sum(a_fb_ncells[k][loc].values())
                         for loc in LOCALES}
        if not any(cells_per_loc.values()):
            continue
        tpls: set = set()
        for loc in LOCALES:
            for s in a_fb_tpl[k][loc].values():
                tpls |= s
        fb_summary[k] = {
            "templates": sorted(tpls),
            "cells_per_locale": cells_per_loc,
            "entities_with_new_cells_per_locale":
                {loc: len(a_fb_ncells[k][loc]) for loc in LOCALES}}
    report["inline_prose_fallback_A"] = fb_summary
    report["raw_span_verification_A_fallback"] = {
        k: {loc: a_fb_raw[k][loc] for loc in LOCALES} for k in a_fb_raw}
    report["flatten_struct_path_collisions"] = sorted(fb_anomalies)
    report["frozen_kind_stray_prose_measured_not_emitted"] = {
        k: {loc: {"entities": len(frozen_stray_ids[k][loc]),
                  "cells": frozen_stray_cells[k][loc]}
            for loc in LOCALES} for k in FROZEN_KIND_STRAYS}

    SCRATCH.mkdir(parents=True, exist_ok=True)
    (SCRATCH / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True)
        + "\n", encoding="utf-8")

    # console digest (ASCII-safe: Windows console is cp1252)
    print("kinds:", len(all_kinds),
          "(A:", len(ref_kinds), "B:", len(STRUCT_KINDS), ")")
    print("availability rows:", report["availability_rows"])
    rawA = sum(sum(v["matched"] for v in a_raw[k].values()) for k in a_raw)
    rawB = sum(sum(v["matched"] for v in b_raw[k].values()) for k in b_raw)
    badA = sum(sum(v["mismatched"] + v["absent"]
                   for v in a_raw[k].values()) for k in a_raw)
    badB = sum(sum(v["mismatched"] + v["absent"]
                   for v in b_raw[k].values()) for k in b_raw)
    print("raw-span matched:", rawA, "+", rawB, "=", rawA + rawB,
          "| mismatched/absent:", badA + badB)
    fbA = sum(sum(v["matched"] for v in a_fb_raw[k].values())
              for k in a_fb_raw)
    badFb = sum(sum(v["mismatched"] + v["absent"] for v in a_fb_raw[k]
                    .values()) for k in a_fb_raw)
    print("inline-prose fallback cells matched:", fbA,
          "| mismatched/absent:", badFb,
          "| path collisions:", len(fb_anomalies))
    print("dual-parser (en): sheets",
          report["dual_parser_structure_en"]["sheets_compared"],
          "row-mismatch:",
          len(report["dual_parser_structure_en"]["sheets_row_set_mismatch"]),
          "path-mismatch:",
          report["dual_parser_structure_en"]["sheets_with_path_mismatch"])
    print("ui coverage:",
          {loc: ui_cov[loc]["strings"] for loc, _ in UI_SOURCE})
    ui_bad = sum(v["mismatched"] + v["absent"] for v in ui_raw.values())
    print("ui raw-span matched:",
          sum(v["matched"] for v in ui_raw.values()),
          "| mismatched/absent:", ui_bad)
    print("filler census:", report["filler_census"]["total"], "instances",
          report["filler_census"]["by_class"])
    rt = report["round_trip_sample"]
    print("round-trip sample:", rt["all9_resolved"], "/",
          rt["entities"], "resolve in all 9")
    print("report ->", SCRATCH / "report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
