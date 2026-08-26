#!/usr/bin/env python3
"""hl_decompile.py — Wartales HashLink structured-text decompiler (dig 13).

Step 5 of the decompile plan ([decompile-dig-1 §3]
docs/decompile-dig-1.mdx), layered on the Dig 8 operand layer
(pipeline/tools/hl_disasm.py): reconstructs expressions from register
defs per basic block, rebuilds if/while/switch/try from CFG shapes,
resolves calls to names, and emits readable `.hx` mirrors of debug source
paths under extracted/decompiled/hl-src/, beside the Dig 8 `.dis.hx`
layer. Deterministic: same inputs -> byte-identical outputs (--verify
relies on it).

Semantics policy (extends dig 8; docs/disasm-formula-findings.mdx §1):
an expression renders resolved ONLY when its operand semantics are
measured. Anything else renders as the disassembly it came from,
prefixed `/* unresolved */` — guessed source text would poison downstream
formulas worse than honest disassembly. The unknown ledger GROWS: dig 8
kinds are carried forward and recounted, decompile-layer kinds are added;
nothing drops silently.

Models measured THIS dig over the full corpus (numbers + evidence in
docs/data-dig-log.mdx dig 13):
  - debug assigns table (present in hlboot.dat, skipped unread by the
    canonical loader): per-function ordered (variableNameStringRef, pc)
    pairs where
      pc < 0  -> parameter slot (-pc - 1);
      pc >= 1 -> variable live at pc: dst(op[pc-1]) takes the name;
      pc == 0 -> names nothing usable (ledgered unused).
    Extracted by a strict zero-slack walk of the client's functions
    section via hlboot_probe.Dig (--extract-assigns; read-only).
  - constant-object globals decode FULLY: constants.jsonl fields[j] are
    pool indexes keyed by the global's DECLARED type field[j] kind —
    HBYTES(8) -> strings[idx], HI32(3) -> ints[idx]; String globals
    additionally satisfy ints[length] == len(bytes). Independently
    reproduces dig 8's hand-decoded constant names.
  - compiler idiom folded structurally, counted per function in the
    emitted header: bounds-checked array element access
    [JULt idx<len -> ok | __expand(arr,idx) | ok: bytes=arr.bytes;
    off=idx<<C; Get/SetMem] renders `arr[idx]` / `arr[idx] = v`;
    nullchecks fold into their following access; ternary diamonds (two
    single-block arms defining the same register) render `?:`.

Verification gate (brief): a module ships structured text only when
  (a) every structured statement's op range partitions the function's
      ops with no gaps/overlaps (checked per function at emit; --verify
      re-renders and byte-compares shipped files);
  (b) the known-semantics set (WorldMesh.getFow row-major,
      MiniMap.getPlayerPosition, Layers2D.getLayerColor,
      ui.comp.Compass.sync) renders documented behavior;
  (c) a >=20-function random hand-audit sample is documented under
      output/_dig-decomp/.

Usage:
  python hl_decompile.py --extract-assigns     one-time hlboot walk
  python hl_decompile.py --emit [--all | --modules f1,f2 | --prefix p]
  python hl_decompile.py --function 7774       one function to stdout
  python hl_decompile.py --verify              gates + determinism
  python hl_decompile.py --audit-sample N      pick + record audit sample

Exit 0 iff the requested work completed and its gates passed.
"""
import gzip
import json
import os
import random
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hl_disasm import (BUILDID, HLSTRUCT, OPNAMES, Corpus, Disasm,  # noqa: E402
                       _fld, _method, _q, _recv_type, _safe_rel)

PACK = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "..", ".."))
OUTDIR = os.path.join(PACK, "extracted", "decompiled", "hl")
SRCDIR = os.path.join(PACK, "extracted", "decompiled", "hl-src")
DIGDIR = os.path.join(PACK, "output", "_dig-decomp")
ASSIGNS_PATH = os.path.join(SRCDIR, "_variable-names.jsonl")
DEFAULT_HLBOOT = "A:/SteamLibrary/steamapps/common/Wartales/hlboot.dat"
AUDIT_SEED = 20260825
# dst-writing ops whose evaluation cannot have observable effects, so a
# result-discarded instance may be omitted; everything else stays
STMT_SIDE = {
    "OSetField", "OSetThis", "OSetGlobal", "ODynSet", "OSetArray",
    "OSetI8", "OSetI16", "OSetMem", "OSetEnumField", "OSetref",
    "OTrap", "OAssert",
}
SAFE_DROP = {
    "OMov", "OInt", "OFloat", "OBool", "OString", "ONull",
    "OAdd", "OSub", "OMul", "OSDiv", "OUDiv", "OSMod", "OUMod",
    "OShl", "OSShr", "OUShr", "OAnd", "OOr", "OXor", "ONeg", "ONot",
    "OGetGlobal", "OField", "OGetThis", "OToDyn", "OToSFloat",
    "OToUFloat", "OToInt", "OSafeCast", "OUnsafeCast", "OToVirtual",
    "OArraySize", "OType", "OGetType", "OGetTID", "ORefData",
}
INLINE_MAX_COST = 90


# ---------------------------------------------------------------------------
# helpers

def sig_args(sig):
    """'(a,b)->r' -> ['a','b']."""
    depth, args, cur = 0, [], ""
    for ch in sig:
        if ch == "(":
            depth += 1
            if depth == 1:
                continue
        elif ch == ")":
            depth -= 1
            if depth == 0:
                break
        elif ch == "," and depth == 1:
            args.append(cur.strip())
            cur = ""
            continue
        if depth >= 1:
            cur += ch
    if cur.strip():
        args.append(cur.strip())
    return args


def sig_ret(sig):
    return sig[sig.index("->") + 2:].strip()


DST_OPS = {
    "OMov", "OInt", "OFloat", "OBool", "OBytes", "OString", "ONull",
    "OAdd", "OSub", "OMul", "OSDiv", "OUDiv", "OSMod", "OUMod",
    "OShl", "OSShr", "OUShr", "OAnd", "OOr", "OXor", "ONeg", "ONot",
    "OIncr", "ODecr",
    "OCall0", "OCall1", "OCall2", "OCall3", "OCall4", "OCallN",
    "OCallMethod", "OCallThis",
    "OStaticClosure", "OInstanceClosure", "OVirtualClosure",
    "OGetGlobal", "OField", "OGetThis", "ODynGet",
    "OToDyn", "OToSFloat", "OToUFloat", "OToInt", "OSafeCast",
    "OUnsafeCast", "OToVirtual",
    "OGetI8", "OGetI16", "OGetMem", "OGetArray",
    "ONew", "OArraySize", "OType", "OGetType", "OGetTID",
    "ORef", "OUnref", "ORefData", "ORefOffset",
    "OMakeEnum", "OEnumAlloc", "OEnumIndex", "OEnumField",
    "OTrap",
}

_READ_POS = defaultdict(list)


def _init_read_pos():
    R = _READ_POS
    for nm in ("OAdd", "OSub", "OMul", "OSDiv", "OUDiv", "OSMod", "OUMod",
               "OShl", "OSShr", "OUShr", "OAnd", "OOr", "OXor"):
        R[nm] = [1, 2]
    for nm in ("OMov", "ONeg", "ONot", "OToDyn", "OToSFloat", "OToUFloat",
               "OToInt", "OSafeCast", "OUnsafeCast", "OToVirtual", "ORef",
               "OUnref", "ORefData", "OEnumIndex"):
        R[nm] = [1]
    R["OArraySize"] = [1]
    R["OGetType"] = [1]
    R["OGetTID"] = [1]
    for nm in ("OJTrue", "OJFalse", "OJNull", "OJNotNull", "OSwitch",
               "ORet", "OThrow", "ORethrow", "ONullCheck"):
        R[nm] = [0]
    for nm in ("OJSLt", "OJSGte", "OJSGt", "OJSLte", "OJULt", "OJUGte",
               "OJNotLt", "OJNotGte", "OJEq", "OJNotEq"):
        R[nm] = [0, 1]
    for nm in ("OIncr", "ODecr"):
        R[nm] = [0]
    for nm in ("OField", "ODynGet", "OGetI8", "OGetI16", "OGetMem",
               "OGetArray", "ORefOffset"):
        R[nm] = [1, 2]
    R["OSetField"] = [0, 2]
    R["OSetThis"] = [1]
    R["OSetGlobal"] = [1]
    R["ODynSet"] = [0, 2]
    R["OSetArray"] = [0, 1, 2]
    R["OSetI8"] = [0, 1, 2]
    R["OSetI16"] = [0, 1, 2]
    R["OSetMem"] = [0, 1, 2]
    R["OSetref"] = [0, 1]
    R["OSetEnumField"] = [0, 2]
    R["OEndTrap"] = [0]
    R["OInstanceClosure"] = [2]
    for k in range(5):
        R[f"OCall{k}"] = list(range(2, 2 + k))


_init_read_pos()


def op_reads(opname, a):
    if opname == "OCallN":
        n = a[2] if len(a) > 2 else 0
        return list(a[3:3 + n])
    if opname == "OCallMethod" or opname == "OCallThis":
        return list(a[3:])
    if opname == "OCallClosure":
        out = [a[1]] if len(a) > 1 else []
        return out + list(a[3:])
    if opname == "OMakeEnum":
        n = a[2] if len(a) > 2 else 0
        return list(a[3:3 + n])
    pos = _READ_POS.get(opname)
    if not pos:
        return []
    return [a[p] for p in pos if p < len(a)]


# ---------------------------------------------------------------------------
# assigns extraction (debug variable names)

def extract_assigns(hlboot=None):
    from hlboot_probe import Dig
    path = hlboot or DEFAULT_HLBOOT
    dig = Dig(path)
    dig.read_header()
    dig.read_pools_strings()
    dig.read_debug_files()
    dig.solve_types(dig.pos)
    dig.read_globals()
    dig.read_natives()
    dig.load_opcode_table()
    fn_start = dig.pos
    dig.solve_opcodes(fn_start)
    assert dig.pos <= dig.N, "functions section overrun"
    os.makedirs(SRCDIR, exist_ok=True)
    nwith = npairs = nneg = 0
    with open(ASSIGNS_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"_meta": {
            "source": path,
            "buildid": BUILDID,
            "method": "hlboot_probe.Dig strict walk of the functions "
                      "section; assigns = debugger variable-tracking "
                      "pairs (canonical reader skips them unread)",
            "model_measured_dig13":
                "(stringRef, pc): pc<0 -> parameter slot (-pc-1); "
                "pc>=1 -> variable live at pc (dst of op pc-1 takes the "
                "name); pc==0 names nothing usable",
            "functions": len(dig.functions)}}) + "\n")
        for fn in dig.functions:
            a = fn["assigns"] or []
            if a:
                nwith += 1
                npairs += len(a)
                nneg += sum(1 for _, p in a if p < 0)
            f.write(json.dumps({"findex": fn["findex"],
                                "assigns": [[s, r] for s, r in a]},
                               ensure_ascii=False) + "\n")
    print(f"ASSIGNS: {nwith}/{len(dig.functions)} functions carry assigns; "
          f"{npairs} pairs ({nneg} parameter slots) -> {ASSIGNS_PATH}")
    return 0


def load_assigns():
    out = {}
    with open(ASSIGNS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if "_meta" not in r:
                out[r["findex"]] = [(s, p) for s, p in r["assigns"]]
    return out


# ---------------------------------------------------------------------------
# constant-object materialization

def build_const_values(c):
    """global -> {'fields': {...}, 'string': str|None} for decoding rows."""
    vals = {}
    stats = Counter()
    string_ti = c.ti_by_name.get("String")
    for g, r in sorted(c.constants.items()):
        ti = c.globals[g]["type"]
        t = c.byi.get(ti)
        tf = (t or {}).get("fields", [])
        fs = r["fields"]
        if len(tf) < len(fs):
            stats["type_fields_short"] += 1
            continue
        dec, ok = {}, True
        for j, val in enumerate(fs):
            kind = c.byi.get(tf[j][1], {}).get("kind")
            if kind == 8 and val < len(c.strings):
                dec[tf[j][0]] = c.strings[val]
            elif kind == 3 and val < len(c.ints):
                dec[tf[j][0]] = c.ints[val]
            else:
                ok = False
                break
        if ok and "bytes" in dec and "length" in dec \
                and dec["length"] != len(dec["bytes"]):
            ok = False
        if not ok:
            stats["symbolic"] += 1
            continue
        stats["decoded"] += 1
        vals[g] = {"fields": dec,
                   "string": dec.get("bytes")
                   if ti == string_ti and set(dec) == {"bytes", "length"}
                   else None}
    return vals, stats


# ---------------------------------------------------------------------------
# structuring-grade CFG (normal edges; exception handlers separate)

class CFG:
    def __init__(self, nops, opseq):
        self.nops = nops
        leaders = {0, nops}
        self.term = {}
        self.traps = {}
        for pc, arr in enumerate(opseq):
            op, a = arr[0], arr[1:]
            nm = OPNAMES[op] if op < len(OPNAMES) else ""
            if nm.startswith("OJ") and nm != "OLabel":
                d = pc + 1 + a[-1]
                ft = None if nm == "OJAlways" else pc + 1
                self.term[pc] = ("jump", ([d] if 0 <= d < nops else []), ft)
                leaders.add(pc + 1)
                if 0 <= d < nops:
                    leaders.add(d)
            elif nm == "OSwitch":
                ncases = a[1]
                dests = []
                for o in a[3:3 + ncases]:
                    d = pc + 1 + o
                    if 0 <= d < nops:
                        dests.append(d)
                        leaders.add(d)
                d = pc + 1 + a[2]
                if 0 <= d < nops:
                    dests.append(d)
                    leaders.add(d)
                self.term[pc] = ("switch", dests, None)
                leaders.add(pc + 1)
            elif nm == "OTrap":
                d = pc + 1 + a[-1]
                if 0 <= d < nops:
                    self.traps[pc] = d
                    leaders.add(d)
                leaders.add(pc + 1)
            elif nm in ("ORet", "OThrow", "ORethrow"):
                self.term[pc] = ("terminate", [], None)
                if pc + 1 < nops:
                    leaders.add(pc + 1)
        ls = sorted(leaders)
        self.blocks = [(s, e) for s, e in zip(ls, ls[1:]) if e > s]
        self.bidx = {}
        for bi, (s, e) in enumerate(self.blocks):
            for pc in range(s, e):
                self.bidx[pc] = bi
        nsucc = defaultdict(set)
        npred = defaultdict(set)
        for bi, (s, e) in enumerate(self.blocks):
            last = e - 1
            t = self.term.get(last)
            nxts = []
            if t:
                _, dests, ft = t
                nxts.extend(dests)
                if ft is not None and ft < nops:
                    nxts.append(ft)
            elif last + 1 < nops:
                nxts.append(last + 1)
            for d in nxts:
                bd = self.bidx.get(d)
                if bd is not None:
                    nsucc[bi].add(bd)
                    npred[bd].add(bi)
        self.succ = nsucc
        self.pred = npred
        self.reach = set()
        stack = [0] if self.blocks else []
        while stack:
            u = stack.pop()
            if u in self.reach:
                continue
            self.reach.add(u)
            stack.extend(nsucc.get(u, ()))
        self._dom()

    def _rpo(self):
        """Reverse POST-order (not reversed preorder — that breaks the
        idom-index monotonicity CHK's intersect relies on)."""
        post, seen = [], set()
        if not self.blocks:
            return []
        stack = [(0, iter(sorted(self.succ.get(0, ()))))]
        seen.add(0)
        while stack:
            u, it = stack[-1]
            adv = False
            for v in it:
                if v not in seen:
                    seen.add(v)
                    stack.append((v, iter(sorted(self.succ.get(v, ())))))
                    adv = True
                    break
            if not adv:
                post.append(u)
                stack.pop()
        return list(reversed(post))

    def _dom(self):
        rpo = self._rpo()
        idx = {b: i for i, b in enumerate(rpo)}
        self.rpo_idx = idx
        idom = {0: 0}
        changed = True
        while changed:
            changed = False
            for b in rpo:
                if b == 0:
                    continue
                preds = [p for p in self.pred.get(b, ()) if p in idom]
                if not preds:
                    continue
                new = preds[0]
                for p in preds[1:]:
                    new = self._intersect(new, p, idom)
                if idom.get(b) != new:
                    idom[b] = new
                    changed = True
        self.idom = idom

    def _intersect(self, a, b, idom):
        idx = self.rpo_idx
        while a != b:
            while idx[a] > idx[b]:
                a = idom[a]
            while idx[b] > idx[a]:
                b = idom[b]
        return a

    def dominates(self, a, b):
        if a not in self.idom:
            return False
        while True:
            if b == a:
                return True
            nxt = self.idom.get(b)
            if nxt is None or nxt == b:
                return False
            b = nxt

    def dom_lca(self, a, b):
        ia = self.rpo_idx.get(a)
        ib = self.rpo_idx.get(b)
        if ia is None or ib is None:
            return None
        da, db = a, b
        while da != db:
            if self.rpo_idx[da] > self.rpo_idx[db]:
                da = self.idom.get(da)
                if da is None:
                    return None
            else:
                db = self.idom.get(db)
                if db is None:
                    return None
        return da

    def loop_bodies(self):
        bodies = defaultdict(set)
        for b in self.reach:
            for t in self.succ.get(b, ()):
                if t in self.reach and self.dominates(t, b) and t != b:
                    body = bodies[t]
                    if not body:
                        body.add(t)
                    stack = [b]
                    while stack:
                        n = stack.pop()
                        if n not in body:
                            body.add(n)
                            stack.extend(self.pred.get(n, ()))
        return bodies


# ---------------------------------------------------------------------------
# array-access idiom fusion (bounds-checked element read/write)

class ArrayIdiom:
    """Fuses [guard | expand | access] block triples into super-blocks."""

    def __init__(self, tool, fn, opseq, cfg):
        self.tool = tool
        self.opseq = opseq
        self.cfg = cfg
        self.group_of = {}       # block -> representative block
        self.groups = {}         # rep -> {'blocks':[...], 'kind':...}
        self.find()

    def _op(self, pc):
        arr = self.opseq[pc]
        nm = OPNAMES[arr[0]] if arr[0] < len(OPNAMES) else ""
        return nm, arr[1:]

    def find(self):
        cfg = self.cfg
        for bi, (s, e) in enumerate(cfg.blocks):
            if bi in self.group_of or bi not in cfg.reach:
                continue
            last = e - 1
            nm, a = self._op(last)
            if nm != "OJULt":
                continue
            ok_t = cfg.bidx.get(last + 1 + a[-1])
            ft = cfg.bidx.get(last + 1) if last + 1 < self.cfg.nops else None
            if ok_t is None or ft is None:
                continue
            g = self.match(ok_t, ft, bi, a[0])
            if g:
                self.register(g)
                continue
            # write form: value stored in the ok-block
            g = self.match_write(ok_t, ft, bi, a[0])
            if g:
                self.register(g)

    def match(self, ok_b, exp_b, guard_b, idx_reg):
        """Read form: ok starts [bytes=arr.bytes; off=i<<C; dst=mem[b,o]]."""
        cfg = self.cfg
        # expand block: exactly one call to *.Array*.__expand(arr, idx),
        # single predecessor, falls through to ok
        es, ee = cfg.blocks[exp_b]
        if ee - es != 1 or len(cfg.pred.get(exp_b, ())) != 1 \
                or cfg.bidx.get(ee) != ok_b:
            return None
        nm, a = self._op(es)
        if not nm.startswith("OCall") or nm == "OCallClosure":
            return None
        lbl = self.tool.c.callee_label(a[1]) if len(a) > 1 else ""
        if "__expand" not in lbl or "Array" not in lbl:
            return None
        arr_reg = a[2] if nm != "OCallN" else (a[3] if len(a) > 3 else None)
        os_, oe = cfg.blocks[ok_b]
        if oe - os_ < 4:
            return None
        n1, a1 = self._op(os_)          # bytes = arr.bytes
        if n1 != "OField" or a1[1] != arr_reg:
            return None
        bytes_reg = a1[0]
        n2, a2 = self._op(os_ + 1)      # tmp = C
        n3, a3 = self._op(os_ + 2)      # off = idx << tmp
        if n2 != "OInt" or n3 != "OShl" or a3[1] != idx_reg \
                or a3[2] != a2[0]:
            return None
        off_reg = a3[0]
        n4, a4 = self._op(os_ + 3)      # dst = mem[bytes, off]
        if n4 != "OGetMem" or a4[1] != bytes_reg or a4[2] != off_reg:
            return None
        return {"blocks": [guard_b, exp_b, ok_b],
                "rep": guard_b, "kind": "read",
                "arr": arr_reg, "idx": idx_reg, "elem_dst": a4[0],
                "tail_start": os_ + 4}

    def match_write(self, ok_b, exp_b, guard_b, idx_reg):
        cfg = self.cfg
        es, ee = cfg.blocks[exp_b]
        if ee - es != 1 or len(cfg.pred.get(exp_b, ())) != 1 \
                or cfg.bidx.get(ee) != ok_b:
            return None
        nm, a = self._op(es)
        if not nm.startswith("OCall") or nm == "OCallClosure":
            return None
        lbl = self.tool.c.callee_label(a[1]) if len(a) > 1 else ""
        if "__expand" not in lbl or "Array" not in lbl:
            return None
        arr_reg = a[2] if nm != "OCallN" else (a[3] if len(a) > 3 else None)
        os_, oe = cfg.blocks[ok_b]
        if oe - os_ < 4:
            return None
        n1, a1 = self._op(os_)
        if n1 != "OField" or a1[1] != arr_reg:
            return None
        bytes_reg = a1[0]
        n2, a2 = self._op(os_ + 1)
        n3, a3 = self._op(os_ + 2)
        if n2 != "OInt" or n3 != "OShl" or a3[1] != idx_reg \
                or a3[2] != a2[0]:
            return None
        off_reg = a3[0]
        n4, a4 = self._op(os_ + 3)
        if n4 != "OSetMem" or a4[0] != bytes_reg or a4[1] != off_reg:
            return None
        return {"blocks": [guard_b, exp_b, ok_b],
                "rep": guard_b, "kind": "write",
                "arr": arr_reg, "idx": idx_reg, "val": a4[2],
                "tail_start": os_ + 4}

    def register(self, g):
        rep = g["rep"]
        self.groups[rep] = g
        for b in g["blocks"]:
            self.group_of[b] = rep

    # ---- view over blocks ----------------------------------------------
    def reps_in_range(self):
        return sorted(self.groups)


# ---------------------------------------------------------------------------
# per-function decompiler

class FuncDecomp:
    def __init__(self, tool, fn, opseq):
        self.tool = tool
        self.c = tool.c
        self.dis = tool.dis
        self.fn = fn
        self.opseq = opseq
        self.findex = fn["findex"]
        self.nops = len(opseq)
        self.cfg = CFG(self.nops, opseq)
        self.idiom = ArrayIdiom(tool, fn, opseq, self.cfg)
        self.stats = Counter()
        self.eff, _ = self.dis._track_types(fn, opseq)
        self.owner = self.c.fowner.get(self.findex)
        self.args = sig_args(fn["sig"])
        self.nargs = len(self.args)
        self._names()
        # read census
        self.read_count = Counter()
        self.read_pcs = defaultdict(list)
        self.incr_regs = set()
        for pc, arr in enumerate(opseq):
            nm = OPNAMES[arr[0]] if arr[0] < len(OPNAMES) else ""
            for r in op_reads(nm, arr[1:]):
                self.read_count[r] += 1
                self.read_pcs[r].append(pc)
            if nm in ("OIncr", "ODecr"):
                self.incr_regs.add(arr[1])

    # ---- naming ----------------------------------------------------------
    def _names(self):
        self.param_names = {}
        claimed = set()
        name_by_marker = {}
        for s, p in self.tool.assigns.get(self.findex, ()):
            nm = self.c.strings[s] if s < len(self.c.strings) else None
            if not nm:
                continue
            if p < 0:
                slot = -p - 1
                if slot < self.nargs:
                    self.param_names.setdefault(slot, nm)
                    claimed.add(nm)
                else:
                    self.tool.note("assign-param-slot-oob", self.findex, p,
                                   f"slot={slot}")
            elif p >= 1:
                q = p - 1
                arr = self.opseq[q]
                onm = OPNAMES[arr[0]] if arr[0] < len(OPNAMES) else ""
                if onm in DST_OPS and onm != "OTrap" and len(arr) > 1:
                    key = (arr[1], q)
                    if key not in name_by_marker:
                        name_by_marker[key] = nm
                else:
                    self.tool.note("assign-marker-no-dst-op", self.findex,
                                   q, onm)
            else:
                self.tool.note("assign-marker-pc0-unused", self.findex, 0,
                               nm[:24])
        self.reg_name = {}
        for (reg, _qpc), nm in sorted(name_by_marker.items(),
                                      key=lambda kv: kv[0][1]):
            if reg in self.reg_name:
                continue
            cand, k = nm, 2
            while cand in claimed:
                cand = f"{nm}_{k}"
                k += 1
            claimed.add(cand)
            self.reg_name[reg] = cand

    def param_display(self, i):
        if i == 0 and self.owner:
            return "this"
        return self.param_names.get(i, f"p{i}")

    def reg_ref(self, r):
        if r < self.nargs:
            return self.param_display(r)
        return self.reg_name.get(r) or f"v{r}"

    def qual_name(self):
        if self.owner:
            return f"{self.owner[0]}.{self.owner[1]}"
        base = os.path.basename(self.fn.get("debug_file") or "?")
        return f"f#{self.findex}@{base}"

    # ---- grouped-block view -----------------------------------------------
    def rep(self, b):
        return self.idiom.group_of.get(b, b)

    def group_blocks(self, rep):
        if rep in self.idiom.groups:
            return self.idiom.groups[rep]["blocks"]
        return [rep]

    def group_range(self, rep):
        bs = self.group_blocks(rep)
        return (min(self.cfg.blocks[b][0] for b in bs),
                max(self.cfg.blocks[b][1] for b in bs))

    # ---- top ----------------------------------------------------------------
    def render(self):
        self.covered = []
        self.labels_needed = set()
        self.pending_label = None
        self.loop_stack = []
        self.trap_stack = []
        self.exc_pending = set()
        self.exc_handled = set()
        self.declared = set()
        self.cur_loop_exit = None
        self._suppress_guard = False
        self.block_pos = {}      # rep block -> index into self.out
        self.labeled = set()
        self.env = None          # set per emitted block by emit_ops_range
        self._ind = 1
        self.out = []
        for tp, hp in self.cfg.traps.items():
            hb = self.cfg.bidx.get(hp)
            if hb is not None:
                self.exc_pending.add(self.rep(hb))
        self.loopmap = self.cfg.loop_bodies()

        # grem tracks CONSUMED state per representative block — never raw
        # members of fused idiom groups (mixing the two caused a tight
        # re-pick loop in drain_region). Exception-only handler blocks join
        # the universe so the catch-path drains can consume them.
        # consumption universe = every representative block (main flow,
        # exception-only handlers AND their handler-owned tails); main
        # flow vs handler ownership is decided by catch_region/reach_reps
        remaining = {self.rep(b)
                     for b in range(len(self.cfg.blocks))}
        self.grem = remaining
        self.reach_reps = {self.rep(b) for b in self.cfg.reach}
        entry = 0
        guard = 0
        while remaining:
            guard += 1
            if guard > len(self.cfg.blocks) + 8:
                raise RuntimeError(f"f#{self.findex}: region walk no-converge")
            self.walk(entry, remaining)
            if remaining:
                entry = min(remaining,
                            key=lambda b: self.cfg.blocks[self.rep(b)][0])
                self.labels_needed.add(entry)
        unreach = sorted(
            (b for b in range(len(self.cfg.blocks))
             if self.rep(b) == b and b not in self.cfg.reach
             and b not in self.exc_handled and b in self.grem),
            key=lambda b: self.cfg.blocks[b][0])
        if unreach:
            self.line("// unreachable (no normal-edge path from entry)")
            self.drain_unreachable(set(unreach))
        head = self.header_line()
        text = "\n".join([head] + self.out + ["}", ""])
        ok = self.check_partition()
        self.partition_ok = ok
        import re as _re
        declared = set(_re.findall(r"var (\w+)", text))
        declared.update(self.param_names.values())
        uses = set(_re.findall(r"v\d+", text))
        self.undeclared_refs = sorted(uses - declared)
        return text, ok

    def drain_unreachable(self, rem2):
        """Straight-line rendering of blocks with no normal-edge path from
        entry (post-return padding etc.). No region machinery: every
        control transfer becomes an explicit labeled goto."""
        while rem2:
            b = min(rem2, key=lambda x: self.cfg.blocks[x][0])
            rem2.discard(b)
            if b not in self.grem:
                continue        # rendered by an earlier path (catch etc.)
            self.grem.discard(b)
            s, e = self.cfg.blocks[b]
            self.labels_needed.add(b)
            self.begin_block(b)
            last = e - 1
            term = self.cfg.term.get(last)
            if term is None:
                self.emit_ops_range(s, e, b)
                nb = self.cfg.bidx.get(last + 1)
                if nb is not None:
                    r = self.rep(nb)
                    if r not in rem2:
                        self.emit_goto(r)
                    # else: falls through to the next emitted block
            elif term[0] == "terminate":
                self.emit_ops_range(s, e, b)
            elif term[0] == "switch":
                self.emit_switch_dispatch(b)
            else:
                self.emit_ops_range(s, e - 1, b)
                self.cover(e - 1, e)
                _, dests, ft = term
                dt = self.cfg.bidx.get(dests[0]) if dests else None
                ct = self.build_cond_text(b) if dt is not None else None
                if ct is not None and len(dests) == 1:
                    txt, sense = ct
                    cond = txt if sense else f"!({txt})"
                    self.labels_needed.add(self.rep(dt))
                    self.line(f"if ({cond}) "
                              f"goto L{self.blab(self.rep(dt))};")
                elif dt is not None:
                    self.emit_goto(self.rep(dt))
                if ft is not None:
                    rf = self.rep(self.cfg.bidx.get(ft))
                    if rf is not None and rf not in rem2:
                        self.emit_goto(rf)

    def check_partition(self):
        """True iff covered ranges tile [0, nops) exactly once each.
        On failure sets self.partition_msg with the first defect."""
        cov = sorted(self.covered)
        merged = []
        for s, e in cov:
            if merged and s <= merged[-1][1]:
                if s < merged[-1][1]:
                    self.partition_msg = (
                        f"overlap at pc {s} (prev ends {merged[-1][1]})")
                    return False
                merged[-1] = (merged[-1][0], max(e, merged[-1][1]))
            else:
                merged.append((s, e))
        pos = 0
        for s, e in merged:
            if s != pos:
                self.partition_msg = f"gap before pc {s} (covered to {pos})"
                return False
            pos = e
        if pos != self.nops:
            self.partition_msg = f"uncovered tail {pos}..{self.nops}"
            return False
        self.partition_msg = "ok"
        return True

    def header_line(self):
        params = []
        for i, t in enumerate(self.args):
            if i == 0 and self.owner:
                params.append(f"this:{t}")
            else:
                params.append(
                    f"{self.param_names.get(i, 'p' + str(i))}:{t}")
        src = self.fn.get("debug_file")
        ex = ""
        if self.stats:
            ex = "   // " + ", ".join(
                f"{k}×{v}" for k, v in sorted(self.stats.items()))
        return (f"function {self.qual_name()}({', '.join(params)}): "
                f"{sig_ret(self.fn['sig'])} {{"
                f"   // f#{self.findex} · {src}:{self.fn.get('first_line')}"
                f" · ops={self.nops}{ex}")

    # ---- output plumbing -------------------------------------------------
    def _flush_label(self):
        if self.pending_label is not None:
            lab = self.pending_label
            self.pending_label = None
            self.out.append(lab)

    def line(self, txt):
        self._flush_label()
        self.out.append("    " * self._ind + txt)

    def begin_block(self, b):
        """Record where block b's text starts so a backward goto can get
        a retro-inserted label instead of dangling."""
        self.label_if_needed(b)
        self._flush_label()
        if b not in self.block_pos:
            self.block_pos[b] = len(self.out)

    def cover(self, s, e):
        self.covered.append((s, e))

    def blab(self, b):
        return self.cfg.blocks[b][0]

    def label_if_needed(self, rep):
        if rep in self.labels_needed:
            self.pending_label = f"L{self.blab(rep)}:"
            self.labels_needed.discard(rep)

    def emit_goto(self, target_rep):
        if self.loop_stack and target_rep == self.loop_stack[-1]:
            self.line("continue;")
            return
        if getattr(self, "suppress_goto_target", None) == target_rep:
            return
        if target_rep in self.block_pos:
            # target already emitted (or being emitted): make sure a textual
            # label exists, else the goto dangles
            if target_rep not in self.labeled:
                self.labeled.add(target_rep)
                idx = self.block_pos[target_rep]
                self.out.insert(idx, f"L{self.blab(target_rep)}:")
                for k in self.block_pos:
                    if self.block_pos[k] >= idx:
                        self.block_pos[k] += 1
            self.labels_needed.discard(target_rep)
            self.line(f"goto L{self.blab(target_rep)};")
            return
        self.labels_needed.add(target_rep)
        self.line(f"goto L{self.blab(target_rep)};")

    # ---- region walk -------------------------------------------------------
    def walk(self, entry, region):
        """Emit blocks starting at `entry`, staying inside `region` (a
        read-only bound). Consumption is tracked ONLY via self.grem, so
        nested regions never see stale sets."""
        cur = self.rep(entry)
        steps = 0
        limit = len(self.cfg.blocks) + 8
        while cur is not None and steps <= limit:
            steps += 1
            if cur not in self.grem:
                self.emit_goto(cur)
                break
            if cur not in region:
                self.emit_goto(cur)
                break
            for b in self.group_blocks(cur):
                self.grem.discard(b)
            body = self.loopmap.get(cur)
            if body is not None and self.loop_body_ok(cur, body, region):
                cur = self.emit_while(cur, body, region)
                continue
            t, f = self.cond_succs(cur)
            if t is not None:
                m = self.find_merge(cur, t, f, region)
                if m is not None:
                    self.emit_if(cur, t, f, m)
                    if m in self.grem and m in region:
                        cur = m
                        continue
                    self.emit_goto(m)
                    break
            s, e = self.group_range(cur)
            last_pc = self.cfg.blocks[self.group_blocks(cur)[-1]][1] - 1
            is_group = cur in self.idiom.groups
            # a fused array-access group's guard jump is CONSUMED by the
            # idiom statement; its effective terminator is the ok-tail's
            term = None if is_group else self.cfg.term.get(last_pc)
            if is_group and self.cfg.term.get(
                    self.cfg.blocks[self.idiom.groups[cur]["blocks"][-1]]
                    [1] - 1) is not None:
                # rare: ok-tail itself ends in a jump -> render raw + fall
                # through to generic jump handling below
                term = self.cfg.term.get(
                    self.cfg.blocks[self.idiom.groups[cur]["blocks"][-1]]
                    [1] - 1)
                is_group_render_only = True
            else:
                is_group_render_only = False
            if term and term[0] == "switch" and not is_group:
                self.emit_switch_dispatch(cur)
                break
            if term is None or is_group:
                self.begin_block(cur)
                if is_group:
                    self.emit_idiom(cur)
                else:
                    self.emit_ops_range(s, e, cur)
                if is_group_render_only:
                    break
                nb = self.cfg.bidx.get(last_pc + 1)
                nbr = self.rep(nb) if nb is not None else None
                if nbr is not None and nbr in self.grem and nbr in region:
                    cur = nbr
                    continue
                if nbr is not None:
                    self.emit_goto(nbr)
                break
            if term[0] == "terminate":
                self.begin_block(cur)
                self.emit_ops_range(s, e, cur)
                break
            # conditional/unconditional jump terminator
            self.begin_block(cur)
            if not is_group_render_only:
                self.emit_ops_range(s, e - 1, cur)
            self.cover(e - 1, e)
            _, dests, ft = term
            dt = self.cfg.bidx.get(dests[0]) if dests else None
            df = self.cfg.bidx.get(ft) if ft is not None else None
            dtr = self.rep(dt) if dt is not None else None
            dfr = self.rep(df) if df is not None else None
            if dfr is None:
                # unconditional
                if dtr is not None:
                    if dtr in self.grem and dtr in region:
                        cur = dtr
                        continue
                    self.emit_goto(dtr)
                break
            ct = self.build_cond_text(cur)
            # guard pattern: exactly one arm terminates (early return /
            # throw) -> structured if around the terminator arm, control
            # continues into the other arm
            if ct is not None and dtr is not None and dfr is not None                     and not self._suppress_guard:
                txt_g, sense_g = ct
                if self._ends_terminate(dfr) and dfr in self.grem:
                    body, cont = dfr, dtr
                    cond_g = f"!({txt_g})" if sense_g else txt_g
                elif self._ends_terminate(dtr) and dtr in self.grem:
                    body, cont = dtr, dfr
                    cond_g = txt_g if sense_g else f"!({txt_g})"
                else:
                    body = None
                if body is not None:
                    self.line(f"if ({cond_g}) {{")
                    self._ind += 1
                    self.emit_one_block(body)
                    self._ind -= 1
                    self.line("}")
                    if cont in self.grem and cont in region:
                        cur = cont
                        continue
                    self.emit_goto(cont)
                    break
            if ct is None or dtr is None:
                if dtr is not None:
                    self.labels_needed.add(dtr)
                    self.line(f"goto L{self.blab(dtr)};")
                break
            txt, sense = ct
            cond = txt if sense else f"!({txt})"
            self.labels_needed.add(dtr)
            self.line(f"if ({cond}) goto L{self.blab(dtr)};")
            if dfr in self.grem and dfr in region:
                cur = dfr
                continue
            self.emit_goto(dfr)
            break
        # loop guard exhausted -> whatever remains is picked up by driver

    def _ends_terminate(self, b):
        s, e = self.cfg.blocks[b]
        return self.cfg.term.get(e - 1, ("x",))[0] == "terminate"

    def emit_one_block(self, b):
        self.grem.discard(b)
        s, e = self.cfg.blocks[b]
        self.begin_block(b)
        self.emit_ops_range(s, e, b)

    def loop_body_ok(self, hrep, body_all, region):
        body = {self.rep(b) for b in body_all}
        body.add(hrep)
        return body <= (region & (self.grem | {hrep}))

    def drain_region(self, region):
        """Walk every block of `region` still unconsumed."""
        reg = set(region)
        while True:
            reg &= self.grem
            if not reg:
                return
            ent = min(reg, key=lambda b: self.cfg.blocks[b][0])
            self.labels_needed.add(ent)
            self.walk(ent, reg)

    # ---- loops -----------------------------------------------------------
    def emit_while(self, h, body_all, region):
        hrep = self.rep(h)
        body = set()
        for b in body_all:
            rb = self.rep(b)
            if rb != hrep:
                body.add(rb)
        t0_, f0_ = self.cond_succs(hrep)
        t = self.rep(t0_) if t0_ is not None else None
        f = self.rep(f0_) if f0_ is not None else None
        cond_txt = None
        cond_in = None
        exit_b = None
        if t is not None and f is not None:
            t_in = t in body or t == hrep
            f_in = f in body or f == hrep
            ct = self.build_cond_text(hrep)
            if ct and t_in and not f_in:
                txt, sense = ct
                cond_txt = txt if sense else f"!({txt})"
                cond_in = t
                exit_b = f
            elif ct and f_in and not t_in:
                txt, sense = ct
                cond_txt = txt if not sense else f"!({txt})"
                cond_in = f
                exit_b = t
        if cond_txt is None:
            self.stats["loop-goto-form"] += 1
            self.labels_needed.add(hrep)
            self.begin_block(hrep)
            s, e = self.group_range(hrep)
            self.emit_ops_range(s, e, hrep)
            last_pc = self.cfg.blocks[self.group_blocks(hrep)[-1]][1] - 1
            term = self.cfg.term.get(last_pc)
            nxts = []
            if term and term[0] == "jump":
                nxts = list(term[1]) + ([term[2]]
                                        if term[2] is not None else [])
            elif term is None and last_pc + 1 < self.nops:
                nxts = [last_pc + 1]
            for d in nxts:
                db = self.cfg.bidx.get(d)
                if db is not None:
                    self.emit_goto(self.rep(db))
            return None
        self.begin_block(hrep)
        hs, he = self.cfg.blocks[hrep]
        if he - 1 > hs:
            self.emit_ops_range(hs, he - 1, hrep)
        self.cover(he - 1, he)
        self.line(f"while ({cond_txt}) {{")
        saved_exit = self.cur_loop_exit
        self.cur_loop_exit = exit_b
        self.loop_stack.append(hrep)
        self._ind += 1
        if body:
            reg = {b for b in body if b in self.grem}
            if cond_in is not None and cond_in in reg:
                ent = cond_in
            else:
                ent = min(reg, key=lambda b: self.cfg.blocks[b][0]) \
                    if reg else None
            if ent is not None:
                self.labels_needed.add(ent) \
                    if cond_in is None or cond_in not in reg else None
                self.walk(ent, reg)
            self.drain_region(reg)
        self._ind -= 1
        self.loop_stack.pop()
        self.cur_loop_exit = saved_exit
        self.line("}")
        if exit_b is not None and self.rep(exit_b) in region \
                and self.rep(exit_b) in self.grem:
            return self.rep(exit_b)
        return None

    # ---- conditions ---------------------------------------------------------
    def cond_succs(self, b):
        s, e = self.cfg.blocks[b]
        t = self.cfg.term.get(e - 1)
        if not t or t[0] != "jump" or len(t[1]) != 1:
            return None, None
        dt = self.cfg.bidx.get(t[1][0])
        df = self.cfg.bidx.get(t[2]) if t[2] is not None else None
        if dt is None:
            return None, None
        return dt, df

    def new_env(self, b):
        """Pass-1 inline decisions for block b."""
        s, e = self.cfg.blocks[b]
        status = {}
        for pc in range(s, min(e, self.nops)):
            arr = self.opseq[pc]
            nm = OPNAMES[arr[0]] if arr[0] < len(OPNAMES) else ""
            if nm not in DST_OPS or nm == "OTrap":
                continue
            dst = arr[1]
            if dst in self.incr_regs or dst in op_reads(nm, arr[1:]):
                # incremented or self-referential defs must materialize as
                # vars (a self-read would make lazy inlining recursive)
                status[(dst, pc)] = False
                continue
            pcs = self.read_pcs.get(dst, [])
            inline = (self.read_count.get(dst, 0) == 1 and len(pcs) == 1
                      and s <= pcs[0] < e and pcs[0] > pc)
            if inline:
                # evaluation-order guard: every op between the def and its
                # single use must be pure — an intervening setter, call or
                # nested def would reorder observable effects (caught
                # auditing f#23716: a ctor call floated past field writes)
                for q in range(pc + 1, pcs[0]):
                    qnm = OPNAMES[self.opseq[q][0]]                         if self.opseq[q][0] < len(OPNAMES) else ""
                    if qnm in DST_OPS or qnm in STMT_SIDE                             or qnm.startswith("OCall"):
                        inline = False
                        break
            status[(dst, pc)] = inline
        return {"status": status, "texts": {}, "live": {}}

    def build_cond_text(self, b):
        """(text, sense) for block-ending conditional jump; None if odd."""
        s, e = self.cfg.blocks[b]
        arr = self.opseq[e - 1]
        nm = OPNAMES[arr[0]] if arr[0] < len(OPNAMES) else ""
        a = arr[1:]
        env = self.new_env(b)
        # replay the prefix defs so live state at the terminator mirrors
        # what sequential emission produced (otherwise single-use defs
        # feeding the jump render as undeclared temporaries)
        for qpc in range(s, min(e - 1, self.nops)):
            qarr = self.opseq[qpc]
            qnm = OPNAMES[qarr[0]] if qarr[0] < len(OPNAMES) else ""
            if qnm in ("OIncr", "ODecr"):
                env["live"][qarr[1]] = None
            elif qnm in DST_OPS and qnm != "OTrap":
                key = (qarr[1], qpc)
                if key in env["status"]:
                    env["live"][qarr[1]] = (qpc, env["status"][key])
        jsym = {"OJNull": "== null", "OJNotNull": "!= null", "OJSLt": "<",
                "OJSGte": ">=", "OJSGt": ">", "OJSLte": "<=",
                "OJULt": "<", "OJUGte": ">=", "OJNotLt": "!<",
                "OJNotGte": "!>=", "OJEq": "==", "OJNotEq": "!="}
        if nm in ("OJTrue", "OJFalse"):
            v = self.read_expr(env, a[0], e - 1)
            return v, nm == "OJTrue"
        if nm in jsym:
            lhs = self.read_expr(env, a[0], e - 1)
            rhs = self.read_expr(env, a[1], e - 1) if len(a) > 2 else None
            sym = jsym[nm]
            if nm in ("OJULt", "OJUGte"):
                self.stats["unsigned-compare"] += 1
                return f"(unsigned)({lhs} {sym} {rhs})", True
            if rhs is None:
                return f"{lhs} {sym}", True
            return f"{lhs} {sym} {rhs}", True
        return None

    # ---- if -----------------------------------------------------------------
    def _reach_in_region(self, start, region):
        """Rep-blocks reachable from rep `start` within rep-set `region`."""
        seen = set()
        stack = [self.rep(start)]
        while stack:
            u = stack.pop()
            if u in seen:
                continue
            seen.add(u)
            for v in self.cfg.succ.get(u, ()):
                rv = self.rep(v)
                if rv in region and rv not in seen:
                    stack.append(rv)
        return seen

    def _first_hits(self, start, common):
        """Common-region nodes first reached from `start` (BFS frontier).

        A structured diamond has exactly one such node per arm — its merge.
        """
        start = self.rep(start)
        if start in common:
            return {start}
        seen = {start}
        frontier = [start]
        guard = 0
        limit = len(self.cfg.blocks) + 8
        while frontier and guard <= limit:
            guard += 1
            nxt = []
            hits = set()
            for u in frontier:
                for v in self.cfg.succ.get(u, ()):
                    rv = self.rep(v)
                    if rv in seen:
                        continue
                    seen.add(rv)
                    if rv in common:
                        hits.add(rv)
                    else:
                        nxt.append(rv)
            if hits:
                return hits
            frontier = nxt
        return set()

    def find_merge(self, cur, t, f, remaining):
        cfg = self.cfg
        t = self.rep(t) if t is not None else None
        f = self.rep(f) if f is not None else None
        if f is None or t == f:
            return None
        region = set(remaining) | {cur}
        if t not in region or f not in region:
            return None
        reach_t = self._reach_in_region(t, region)
        reach_f = self._reach_in_region(f, region)
        common = reach_t & reach_f
        if not common:
            return None
        ht = self._first_hits(t, common)
        hf = self._first_hits(f, common)
        if len(ht) != 1 or ht != hf:
            return None
        m = next(iter(ht))
        if m == cur or m not in self.grem \
                or not cfg.dominates(cur, m):
            return None
        then_set = self.collect_side(cur, t, m)
        if then_set is None:
            return None
        else_set = set() if f == m else self.collect_side(cur, f, m)
        if else_set is None:
            return None
        if then_set & else_set:
            return None
        self.side_sets = (then_set, else_set)
        return m

    def collect_side(self, cur, start, stop):
        """Collect the rep-blocks of one arm (all dominated by `cur`,
        still unconsumed), stopping at the merge `stop`."""
        cfg = self.cfg
        seen = set()
        side = set()
        stack = [self.rep(start)]
        limit = len(cfg.blocks) + 8
        guard = 0
        while stack:
            guard += 1
            if guard > limit:
                return None
            n = stack.pop()
            n = self.rep(n)
            if n == stop or n in seen:
                continue
            if n not in self.grem:
                # already emitted elsewhere -> cross edge, rendered as goto
                continue
            if not cfg.dominates(cur, n):
                return None
            seen.add(n)
            side.add(n)
            for sx in cfg.succ.get(self.group_blocks(n)[-1], ()):
                if self.rep(sx) != stop and self.rep(sx) not in seen:
                    stack.append(sx)
        side.discard(stop)
        return side

    def emit_side(self, side_set, entry):
        sub = {b for b in side_set if b in self.grem}
        if not sub:
            return
        if entry in sub:
            self.walk(entry, sub)
        self.drain_region(sub)

    def emit_if(self, cur, t, f, m):
        self._if_depth = getattr(self, "_if_depth", 0) + 1
        try:
            self._emit_if_inner(cur, t, f, m)
        finally:
            self._if_depth -= 1

    def _emit_if_inner(self, cur, t, f, m):
        if self._if_depth > 120:
            raise RuntimeError(
                f"f#{self.findex}: if-nesting depth blowup "
                f"(cur={self.cfg.blocks[cur]}, m={self.cfg.blocks[m]}, "
                f"grem={sorted(self.grem)[:12]})")
        then_set, else_set = self.side_sets
        t = self.rep(t)
        f = self.rep(f)
        ct = self.build_cond_text(cur)
        txt, sense = ct if ct else ("true", True)
        if not then_set and else_set:
            then_set, else_set = else_set, then_set
            t, f = f, t
            sense = not sense
        cond = txt if sense else f"!({txt})"
        hs, he = self.cfg.blocks[cur]
        self.begin_block(cur)
        if he - 1 > hs:
            self.emit_ops_range(hs, he - 1, cur)
        self.cover(he - 1, he)
        self.line(f"if ({cond}) {{")
        self._ind += 1
        self.suppress_goto_target = m
        self.emit_side(then_set - {m}, t)
        self._ind -= 1
        if else_set:
            self.line("} else {")
            self._ind += 1
            self.emit_side(else_set - {m}, f)
            self._ind -= 1
        self.suppress_goto_target = None
        self.line("}")

    # ---- switch -----------------------------------------------------------
    def emit_switch_dispatch(self, rep):
        s, e = self.cfg.blocks[rep]
        self.begin_block(rep)
        if e - 1 > s:
            self.emit_ops_range(s, e - 1, rep)
        pc = e - 1
        arr = self.opseq[pc]
        a = arr[1:]
        self.cover(pc, pc + 1)
        self.stats["switch-dispatch"] += 1
        self.line(f"switch ({self.reg_ref(a[0])}) {{")
        for i, o in enumerate(a[3:3 + a[1]]):
            bd = self.cfg.bidx.get(pc + 1 + o)
            if bd is None:
                self.line(f"    case {i}: /* target out of range */")
                continue
            self.labels_needed.add(self.rep(bd))
            self.line(f"    case {i}: goto L{self.blab(self.rep(bd))};")
        dd = self.cfg.bidx.get(pc + 1 + a[2])
        if dd is not None:
            self.labels_needed.add(self.rep(dd))
            self.line(f"    default: goto L{self.blab(self.rep(dd))};")
        self.line("}")

    # ---- array idiom --------------------------------------------------------
    def emit_idiom(self, rep):
        g = self.idiom.groups[rep]
        s, e = self.group_range(rep)
        self.begin_block(rep)
        arr_txt = self.reg_ref(g["arr"])
        idx_txt = self.reg_ref(g["idx"])
        if g["kind"] == "read":
            name = self.reg_ref(g["elem_dst"])
            kw = "var " if name not in self.declared else ""
            self.declared.add(name)
            self.line(f"{kw}{name} = {arr_txt}[{idx_txt}];")
            env_seed = g["elem_dst"]
        else:
            val_txt = self.reg_ref(g["val"])
            self.line(f"{arr_txt}[{idx_txt}] = {val_txt};")
            env_seed = None
        self.cover(s, e)
        self.stats["array-idiom"] += 1
        # seed env so later ops in the tail of the ok-block see the elem var
        self.env = self.new_env(self.group_blocks(rep)[-1])
        if env_seed is not None:
            self.env["live"][env_seed] = ("idiom", False)
            self.env["idiom_var"] = {env_seed: name}
            # make read_expr resolve the seeded reg to the element var
            self.env["seeded"] = {env_seed: name}
        else:
            self.env["seeded"] = {}

    # ---- block op emission ---------------------------------------------------
    def emit_ops_range(self, start, end, b_hint):
        self.env = self.new_env(b_hint)
        self.env["seeded"] = {}
        pc = start
        while pc < end:
            arr = self.opseq[pc]
            op = arr[0]
            nm = OPNAMES[op] if op < len(OPNAMES) else f"ForkOp{op}"
            a = arr[1:]
            if pc in self.cfg.traps:
                self.line("try {")
                hb = self.cfg.bidx.get(self.cfg.traps[pc])
                self.trap_stack.append((a[0], hb))
                self.cover(pc, pc + 1)
                pc += 1
                continue
            if nm == "OEndTrap":
                reg, hb = self.trap_stack.pop() if self.trap_stack \
                    else (None, None)
                self.cover(pc, pc + 1)
                cv = self.reg_ref(reg) if reg is not None else "e"
                if hb is not None and hb in self.exc_pending \
                        and hb not in self.exc_handled:
                    self.line(f"}} catch ({cv}) {{")
                    self.exc_handled.add(hb)
                    self.exc_pending.discard(hb)
                    self._ind += 1
                    rem = self.catch_region(hb)
                    rem.add(hb)     # the handler block itself renders here
                    if rem:
                        ent = min(rem,
                                  key=lambda b: self.cfg.blocks[b][0])
                        self.labels_needed.add(ent)
                        self.walk(ent, rem)
                        self.drain_region(rem)
                    self._ind -= 1
                    self.line("}")
                else:
                    self.stats["trap-fallback"] += 1
                    self.line(f"}} catch ({cv}) {{ /* handler not inlined"
                              " */ }")
                pc += 1
                continue
            if nm == "OLabel":
                self.stats["label-op"] += 1
                self.cover(pc, pc + 1)
                pc += 1
                continue
            if nm == "ONullCheck":
                self.stats["nullcheck-folded"] += 1
                self.cover(pc, pc + 1)
                pc += 1
                continue
            if nm in ("ORet", "OThrow", "ORethrow"):
                val = self.read_expr(self.env, a[0], pc) if a else None
                kw = {"ORet": "return", "OThrow": "throw",
                      "ORethrow": "rethrow"}[nm]
                self.line(f"{kw} {val};" if val is not None else f"{kw};")
                self.cover(pc, pc + 1)
                pc += 1
                continue
            pc = self.emit_generic(pc, nm, a)

    def catch_region(self, hb):
        """Rep-blocks reachable from the handler that are neither
        still-unconsumed MAIN-flow blocks nor already-rendered handlers."""
        seen = set()
        stack = [hb]
        while stack:
            u = stack.pop()
            if u in seen:
                continue
            seen.add(u)
            for v in self.cfg.succ.get(u, ()):
                if v not in seen:
                    stack.append(v)
        seen = {self.rep(x) for x in seen}
        # main flow renders every cfg.reach block exactly once on its own;
        # anything else reachable only through the handler belongs to the
        # catch body even when it has not been emitted yet
        return seen - self.reach_reps - self.exc_handled

    # ---- expressions ------------------------------------------------------
    def read_expr(self, env, reg, pc):
        seeded = env.get("seeded", {})
        if reg in seeded:
            return seeded[reg]
        live = env["live"].get(reg)
        if live is not None:
            defpc, inline = live
            if inline:
                txt = env["texts"].get((reg, defpc))
                if txt is None:
                    arr = self.opseq[defpc]
                    nm = OPNAMES[arr[0]] if arr[0] < len(OPNAMES) else ""
                    txt, _p = self.def_text(defpc, nm, arr[1:], env)
                    env["texts"][(reg, defpc)] = txt
                return txt
            return self.reg_ref(reg)
        return self.reg_ref(reg)

    def def_text(self, pc, nm, a, env=None):
        """(text, pure) RHS for a dst-writing op; None text => unresolved."""
        c = self.c
        if env is None:
            env = self.env
        if env is None:
            env = {"status": {}, "texts": {}, "live": {}, "seeded": {}}
        R = lambda i: self.read_expr(env, i, pc)  # noqa: E731

        def typed(i):
            ti = self.eff[i] if isinstance(i, int) and 0 <= i < len(self.eff)\
                else None
            return c.tname(ti)

        if nm == "OMov":
            return R(a[1]), True
        if nm == "OInt":
            v = c.ints[a[1]] if a[1] < len(c.ints) else None
            if v is None:
                self.tool.note("int-pool-oob", self.findex, pc, str(a[1]))
                return f"/*int@{a[1]}*/ 0", True
            return repr(v), True
        if nm == "OFloat":
            v = c.floats[a[1]] if a[1] < len(c.floats) else None
            if v is None:
                self.tool.note("float-pool-oob", self.findex, pc, str(a[1]))
                return f"/*float@{a[1]}*/ 0.0", True
            return repr(v), True
        if nm == "OBool":
            return ("true" if a[1] else "false"), True
        if nm == "OString":
            if a[1] < len(c.strings):
                return _q(c.strings[a[1]]), True
            self.tool.note("string-pool-oob", self.findex, pc, str(a[1]))
            return f"/*str@{a[1]}*/ \"\"", True
        if nm == "ONull":
            return "null", True
        sym = {"OAdd": "+", "OSub": "-", "OMul": "*", "OSDiv": "/",
               "OUDiv": "/u", "OSMod": "%", "OUMod": "%u", "OShl": "<<",
               "OSShr": ">>", "OUShr": ">>>", "OAnd": "&", "OOr": "|",
               "OXor": "^"}.get(nm)
        if sym:
            return f"{R(a[1])} {sym} {R(a[2])}", True
        if nm == "ONeg":
            return f"-{R(a[1])}", True
        if nm == "ONot":
            return f"!({R(a[1])})", True
        if nm in ("OCall0", "OCall1", "OCall2", "OCall3", "OCall4",
                  "OCallN"):
            if a[1] not in c.fn_by_findex and a[1] not in c.natives:
                self.tool.note("call-findex-unresolved", self.findex, pc,
                               str(a[1]))
                lbl = f"f#?{a[1]}"
            else:
                lbl = c.callee_label(a[1])
            if nm == "OCallN":
                args = [R(x) for x in a[3:3 + a[2]]]
            else:
                k = int(nm[-1])
                args = [R(x) for x in a[2:2 + k]]
            return f"{lbl}({', '.join(args)})", True
        if nm == "OCallMethod":
            nargs = a[2]
            args = a[3:3 + nargs]
            recv_i = args[0] if args else None
            rt = _recv_type(self.dis, self.fn, self.eff, recv_i) \
                if recv_i is not None else None
            fname = _method(self.dis, rt, a[1], self.findex, pc)
            recv = R(recv_i) if recv_i is not None else "?"
            rest = [R(x) for x in args[1:]]
            return f"{recv}.{fname}({', '.join(rest)})", True
        if nm == "OCallThis":
            rest = [R(x) for x in a[3:3 + a[2]]]
            ow = c.fowner.get(self.findex)
            rt = ow[2] if ow else None
            fname = _method(self.dis, rt, a[1], self.findex, pc)
            return f"this.{fname}({', '.join(rest)})", True
        if nm == "OStaticClosure":
            return f"closure {c.callee_label(a[1])}", True
        if nm == "OInstanceClosure":
            return f"closure {c.callee_label(a[1])} bound {R(a[2])}", True
        if nm == "OVirtualClosure":
            return f"vclosure({R(a[1])}, {R(a[2])})", True
        if nm == "OGetGlobal":
            return self.global_text(a[1]), True
        if nm == "OField":
            rt = _recv_type(self.dis, self.fn, self.eff, a[1])
            fname = _fld(self.dis, rt, a[2], self.findex, pc)
            return f"{R(a[1])}.{fname}", True
        if nm == "OGetThis":
            ow = c.fowner.get(self.findex)
            fname = _fld(self.dis, ow[2] if ow else None, a[1],
                                  self.findex, pc)
            return f"this.{fname}", True
        if nm == "ODynGet":
            key = c.strings[a[2]] if a[2] < len(c.strings) else f"@{a[2]}"
            self.stats["dynget"] += 1
            return f"{R(a[1])}.{key}", True
        casts = {"OToDyn": "dyn", "OToSFloat": "float", "OToUFloat": "float",
                 "OToInt": "int"}
        if nm in casts:
            return f"{casts[nm]}({R(a[1])})", True
        if nm in ("OSafeCast", "OUnsafeCast"):
            tt = typed(a[0])
            tag = " /*unsafe*/" if nm == "OUnsafeCast" else ""
            return f"({tt}){R(a[1])}{tag}", True
        if nm == "OToVirtual":
            return f"virtual({R(a[1])})", True
        if nm == "OGetI8":
            return f"b8[{R(a[1])},{R(a[2])}]", True
        if nm == "OGetI16":
            return f"b16[{R(a[1])},{R(a[2])}]", True
        if nm == "OGetMem":
            return f"mem[{R(a[1])},{R(a[2])}]", True
        if nm == "OGetArray":
            return f"{R(a[1])}[{R(a[2])}]", True
        if nm == "ONew":
            return f"new {typed(a[0])}", True
        if nm == "OArraySize":
            return f"len({R(a[1])})", True
        if nm == "OType":
            return f"type {c.tname(a[1])}", True
        if nm == "OGetType":
            return f"typeof({R(a[1])})", True
        if nm == "OGetTID":
            return f"tid({R(a[1])})", True
        if nm == "ORef":
            return f"ref({R(a[1])})", True
        if nm == "OUnref":
            return f"unref({R(a[1])})", True
        if nm == "ORefData":
            return f"refdata({R(a[1])})", True
        if nm == "ORefOffset":
            return f"refoffset({R(a[1])},{R(a[2])})", True
        if nm == "OMakeEnum":
            et = self.eff[a[0]] if a[0] < len(self.eff) else None
            ename = c.tname(et)
            cname = f"@{a[1]}"
            if et is not None and c.byi.get(et, {}).get("kind") == 18:
                cons = c.byi[et].get("constructs", [])
                if 0 <= a[1] < len(cons):
                    cname = cons[a[1]][0]
                else:
                    self.tool.note("enum-construct-oob", self.findex, pc,
                                   f"{ename}#{a[1]}")
            vals = [R(x) for x in a[3:3 + a[2]]]
            return f"{ename}.{cname}({', '.join(vals)})", True
        if nm == "OEnumAlloc":
            et = self.eff[a[0]] if a[0] < len(self.eff) else None
            ename = c.tname(et)
            cname = f"@{a[1]}"
            if et is not None and c.byi.get(et, {}).get("kind") == 18:
                cons = c.byi[et].get("constructs", [])
                if 0 <= a[1] < len(cons):
                    cname = cons[a[1]][0]
            return f"alloc {ename}.{cname}", True
        if nm == "OEnumIndex":
            return f"enumidx({R(a[1])})", True
        if nm == "OEnumField":
            et = self.eff[a[1]] if a[1] < len(self.eff) else None
            ename = c.tname(et)
            cname = f"c{a[2]}"
            if et is not None and c.byi.get(et, {}).get("kind") == 18:
                cons = c.byi[et].get("constructs", [])
                if 0 <= a[2] < len(cons):
                    cname = cons[a[2]][0]
            return f"({ename}.{cname}){R(a[1])}[{a[3]}]", True
        return None

    def global_text(self, g):
        c = self.c
        tn = c.globals[g]["type_name"] if g < len(c.globals) else "?"
        cv = self.tool.const_vals.get(g)
        if cv:
            if cv["string"] is not None:
                return _q(cv["string"])
            parts = ", ".join(
                f"{k}: {_q(v) if isinstance(v, str) else v}"
                for k, v in sorted(cv["fields"].items()))
            return f"/*const*/ g#{g}<{tn}>{{{parts}}}"
        return f"g#{g}<{tn}>"

    def emit_generic(self, pc, nm, a):
        env = self.env
        if nm in DST_OPS and nm != "OTrap":
            dst = a[0]
            rc = self.read_count.get(dst, 0)
            if nm in ("OIncr", "ODecr"):
                self.cover(pc, pc + 1)
                self.line(f"{'++' if nm == 'OIncr' else '--'}"
                          f"{self.reg_ref(dst)};")
                env["live"][dst] = None
                return pc + 1
            got = self.def_text(pc, nm, a)
            if got is None:
                self.stats["unresolved-op"] += 1
                self.tool.note("unresolved-op-render", self.findex, pc, nm)
                self.line(f"/* unresolved */ {nm} {list(a)}")
                self.cover(pc, pc + 1)
                env["live"][dst] = None
                return pc + 1
            txt, pure = got
            if txt is None:
                self.stats["unresolved-op"] += 1
                self.tool.note("unresolved-op-render", self.findex, pc, nm)
                self.line(f"/* unresolved */ {nm} {list(a)}")
                self.cover(pc, pc + 1)
                env["live"][dst] = None
                return pc + 1
            if rc == 0:
                self.cover(pc, pc + 1)
                # only inert defs may be dropped silently; anything with
                # potential effects (calls, dyn/mem/array reads, closures)
                # stays as a statement — a dropped networkSetBit would
                # falsify game behavior (caught auditing f#8272)
                if pure and nm in SAFE_DROP:
                    self.stats["dead-store-dropped"] += 1
                else:
                    self.line(f"{txt};")
                env["live"][dst] = None
                return pc + 1
            inline = env["status"].get((dst, pc), False)
            if inline and pure and len(txt) <= INLINE_MAX_COST:
                env["live"][dst] = (pc, True)
            else:
                name = self.reg_ref(dst)
                kw = "var " if name not in self.declared else ""
                self.declared.add(name)
                self.line(f"{kw}{name} = {txt};")
                env["live"][dst] = (pc, False)
            self.cover(pc, pc + 1)
            return pc + 1
        R = lambda i: self.read_expr(env, i, pc)  # noqa: E731
        c = self.c
        if nm == "OSetField":
            rt = _recv_type(self.dis, self.fn, self.eff, a[0])
            fname = _fld(self.dis, rt, a[1], self.findex, pc)
            self.line(f"{R(a[0])}.{fname} = {R(a[2])};")
        elif nm == "OSetThis":
            ow = c.fowner.get(self.findex)
            fname = _fld(self.dis, ow[2] if ow else None, a[0],
                                  self.findex, pc)
            self.line(f"this.{fname} = {R(a[1])};")
        elif nm == "OSetGlobal":
            tn = c.globals[a[0]]["type_name"] if a[0] < len(c.globals) \
                else "?"
            self.line(f"g#{a[0]}<{tn}> = {R(a[1])};")
        elif nm == "ODynSet":
            key = c.strings[a[1]] if a[1] < len(c.strings) else f"@{a[1]}"
            self.stats["dynset"] += 1
            self.line(f"{R(a[0])}.{key} = {R(a[2])};")
        elif nm == "OSetArray":
            self.line(f"{R(a[0])}[{R(a[1])}] = {R(a[2])};")
        elif nm == "OSetI8":
            self.line(f"b8[{R(a[0])},{R(a[1])}] = {R(a[2])};")
        elif nm == "OSetI16":
            self.line(f"b16[{R(a[0])},{R(a[1])}] = {R(a[2])};")
        elif nm == "OSetMem":
            self.line(f"mem[{R(a[0])},{R(a[1])}] = {R(a[2])};")
        elif nm == "OSetEnumField":
            self.line(f"({R(a[0])})[{a[1]}] = {R(a[2])};")
        elif nm == "OSetref":
            self.line(f"*{R(a[0])} = {R(a[1])};")
        elif nm == "OAssert":
            self.line("assert;")
        elif nm == "ONop":
            pass
        elif nm == "OTrap":
            self.line(f"/* trap v{a[0]} */ try {{")
            hb = self.cfg.bidx.get(pc + 1 + a[-1])
            self.trap_stack.append((a[0], hb))
        else:
            self.stats["unresolved-op"] += 1
            self.tool.note("unresolved-op-render", self.findex, pc, nm)
            self.line(f"/* unresolved */ {nm} {list(a)}")
        self.cover(pc, pc + 1)
        return pc + 1


# ---------------------------------------------------------------------------
# tool driver

class DecompileTool:
    def __init__(self):
        self.c = Corpus(None)
        self.dis = Disasm(self.c)
        self.assigns = load_assigns()
        self.const_vals, self.const_stats = build_const_values(self.c)
        self.ledger = defaultdict(Counter)
        self.examples = defaultdict(list)

    def note(self, kind, findex, pc, detail):
        self.ledger[kind][detail] += 1
        ex = self.examples[kind]
        if len(ex) < 5:
            ex.append({"findex": findex, "pc": pc, "detail": detail})

    def render_function(self, fn, opseq):
        fd = FuncDecomp(self, fn, opseq)
        text, ok = fd.render()
        return fd, text, ok


def iter_opseq(want=None):
    with gzip.open(os.path.join(HLSTRUCT, "opcodes.jsonl.gz"), "rt",
                   encoding="utf-8") as gz:
        for line in gz:
            rec = json.loads(line)
            if want is None or rec["findex"] == want:
                yield rec["findex"], rec["ops"]
                if want is not None:
                    return


def find_findex_exact(corpus, qual):
    for fx, (ow, pn, _ti) in corpus.fowner.items():
        if f"{ow}.{pn}" == qual:
            return fx
    return None


KNOWN_SET = [
    ("world.WorldMesh.getFow", "row-major FOW sampling"),
    ("ui.win.MiniMap.getPlayerPosition", "returns world xy"),
    ("hrt.prefab.l3d.Layers2D.getLayerColor", "pixel fetch col/row"),
    ("ui.comp.Compass.sync", "bearing strip"),
]

# expected semantic tokens per known-set function: the structured render
# must contain these substrings for the documented behavior to be present
KNOWN_EXPECT = {
    "world.WorldMesh.getFow":
        ["this.fowScale", "this.fowSize", "haxe.io.Bytes.get",
         "* this.fowSize"],
}


def dis_layer_lines():
    """findex -> line of its '// ==== f#N' header in each .dis.hx mirror."""
    out = {}
    if not os.path.isdir(OUTDIR):
        return out
    for root, _dirs, files in os.walk(OUTDIR):
        for name in files:
            if not name.endswith(".dis.hx"):
                continue
            p = os.path.join(root, name)
            rel = os.path.relpath(p, OUTDIR).replace("\\", "/")
            with open(p, encoding="utf-8") as f:
                for i, line in enumerate(f, 1):
                    if line.startswith("// ==== f#"):
                        try:
                            fx = int(line[len("// ==== f#"):]
                                     .split(" ", 1)[0])
                        except ValueError:
                            continue
                        out[fx] = {"file": rel, "line": i}
    return out


def cmd_emit(tool, modules=None, prefix=None, out_root=None):
    """Render + ship modules under extracted/decompiled/hl-src/.

    A module ships only when EVERY function's structured statements
    partition its op range exactly (gate a); gate results land in the
    report. Deterministic: same inputs -> byte-identical files.

    Two streaming passes keep memory bounded (all 2.5M ops never held):
      pass 1 renders every function and records per-function/per-module
      metadata only; pass 2 re-renders (deterministic) and streams each
      shipped module straight to disk.
    """
    global SRCDIR
    if out_root:
        SRCDIR = out_root
    os.makedirs(SRCDIR, exist_ok=True)
    os.makedirs(DIGDIR, exist_ok=True)
    dlines = dis_layer_lines()
    t0 = time.time()
    nfn = len(tool.c.functions)
    print(f"pass 1: rendering {nfn} functions (metadata only) ...")

    def wanted(src):
        if modules is not None and src not in modules:
            return False
        if prefix is not None and not src.startswith(prefix):
            return False
        return True

    meta_rows = defaultdict(Counter)
    fn_meta = {}
    errors = []
    totals = Counter()
    with gzip.open(os.path.join(HLSTRUCT, "opcodes.jsonl.gz"), "rt",
                   encoding="utf-8") as gz:
        for i, line in enumerate(gz):
            rec = json.loads(line)
            fn = tool.c.functions[i]
            assert fn["findex"] == rec["findex"], "dataset misalignment"
            src = fn.get("debug_file") or "?unknown?"
            try:
                fd, _text, part = tool.render_function(fn, rec["ops"])
            except Exception as e:  # noqa: BLE001
                errors.append({"findex": fn["findex"], "file": src,
                               "error": repr(e)})
                continue
            if not wanted(src):
                continue
            owner = tool.c.fowner.get(fn["findex"])
            fn_meta[fn["findex"]] = {
                "ok": part,
                "msg": getattr(fd, "partition_msg", ""),
                "nops": len(rec["ops"]),
                "statements": len(fd.out),
                "stats": dict(fd.stats),
                "name": (f"{owner[0]}.{owner[1]}" if owner
                         else tool.c.callee_label(fn["findex"])),
                "sig": fn["sig"],
                "line": fn.get("first_line"),
                "src": src,
            }
            m = meta_rows[src]
            m["functions"] += 1
            m["ops"] += len(rec["ops"])
            m["statements"] += len(fd.out)
            m["idioms"] += sum(v for k, v in fd.stats.items()
                               if k in ("array-idiom", "nullcheck-folded"))
            if not part:
                m["partition_fail"] += 1
            totals["functions"] += 1
            totals["ops"] += len(rec["ops"])
            if (i + 1) % 15000 == 0:
                print(f"  pass1 {i + 1}/{nfn} ({time.time() - t0:.0f}s)")

    err_srcs = {e["file"] for e in errors}
    shipped_srcs = sorted(
        src for src, m in meta_rows.items()
        if m["partition_fail"] == 0 and src not in err_srcs)
    skipped = []
    for src in sorted(meta_rows):
        if src in set(shipped_srcs):
            continue
        first = None
        for fx, fm in fn_meta.items():
            if fm["src"] == src and not fm["ok"]:
                first = fm["msg"]
                break
        if first is None:
            first = next((e["error"] for e in errors
                          if e["file"] == src), "?")
        skipped.append({"module": src,
                        "functions_failed":
                            int(meta_rows[src]["partition_fail"])
                            + sum(1 for e in errors
                                  if e["file"] == src),
                        "first_fail": first})

    # pass 1 already accumulated ledger notes; reset so shipped counts
    # come from the single pass-2 walk (no double counting)
    tool.ledger = defaultdict(Counter)
    tool.examples = defaultdict(list)
    print(f"pass 2: streaming {len(shipped_srcs)} shipped modules ...")
    handles = {}
    line_pos = {}

    def handle_for(src):
        if src in handles:
            return handles[src]
        path = os.path.join(SRCDIR, *_safe_rel(src).split("/")) + ".hx"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        head = [
            f"// Wartales HashLink structured text — buildid {BUILDID}",
            f"// source mirror: {src}",
            f"// functions: {meta_rows[src]['functions']}  ops: "
            f"{meta_rows[src]['ops']}",
            "// layer: extracted/decompiled/hl-src (structured; sibling "
            "disassembly: extracted/decompiled/hl/<path>.dis.hx)",
            "// tool: pipeline/tools/hl_decompile.py --emit (dig 13)",
            "// semantics: resolved-only rendering; unresolved ops render "
            "verbatim with /* unresolved */; ledger _unresolved.jsonl",
            "",
        ]
        f_ = open(path, "w", encoding="utf-8", newline="\n")
        for h_ in head:
            f_.write(h_ + "\n")
        handles[src] = f_
        line_pos[src] = len(head) + 1
        return f_

    index_rows = []
    with gzip.open(os.path.join(HLSTRUCT, "opcodes.jsonl.gz"), "rt",
                   encoding="utf-8") as gz:
        done = 0
        for i, line in enumerate(gz):
            rec = json.loads(line)
            fn = tool.c.functions[i]
            fx = fn["findex"]
            fm = fn_meta.get(fx)
            if fm is None:
                continue
            fd, text, part = tool.render_function(fn, rec["ops"])
            assert part, f"pass-2 drift on f#{fx}"
            src = fm["src"]
            f_ = handle_for(src)
            start_line = line_pos[src]
            body = text.rstrip("\n") + "\n"
            f_.write(body)
            line_pos[src] = start_line + body.count("\n")
            repo_rel = "extracted/decompiled/hl-src/" \
                + _safe_rel(src) + ".hx"
            index_rows.append({
                "findex": fx, "name": fm["name"], "sig": fm["sig"],
                "debug_file": src, "line": fm["line"],
                "src": {"file": repo_rel, "line": start_line},
                "dis": dlines.get(fx),
                "nops": fm["nops"], "statements": fm["statements"],
                "partition": "ok",
                "folded": fm["stats"],
            })
            done += 1
            if done % 15000 == 0:
                print(f"  pass2 {done}/{len(fn_meta)} "
                      f"({time.time() - t0:.0f}s)")
    for f_ in handles.values():
        f_.close()

    # ---- sidecars --------------------------------------------------------
    idx_path = os.path.join(SRCDIR, "_functions-index.jsonl")
    with open(idx_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"_meta": {
            "buildid": BUILDID,
            "tool": "pipeline/tools/hl_decompile.py --emit (dig 13)",
            "rows": len(index_rows),
            "note": "function -> both decompile layers: src = structured "
                    "text file:line, dis = dig-8 .dis.hx file:line"}})
            + "\n")
        for r in sorted(index_rows, key=lambda x: x["findex"]):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    led_path = os.path.join(SRCDIR, "_unresolved.jsonl")
    with open(led_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"_meta": {
            "buildid": BUILDID,
            "tool": "pipeline/tools/hl_decompile.py --emit (dig 13)",
            "policy": "grows-only unknown ledger; carries dig 8 kinds "
                      "forward (recounted by the shared resolver helpers) "
                      "plus decompile-layer kinds"}}) + "\n")
        f.write(json.dumps({
            "kind": "carried-from-dig8-disasm-ledger",
            "source": "extracted/decompiled/hl/_unknown-opcodes.jsonl",
            "kinds": ["opcode-unobserved-fork-family (99-101 pinned, 0 "
                      "occur)", "obytes-payload-unproven (0 occurrences)",
                      "field-receiver-type-unresolved (dyn receivers)",
                      "method-receiver-type-unresolved"]}) + "\n")
        for k in sorted(tool.ledger,
                        key=lambda k: -sum(tool.ledger[k].values())):
            cnt = sum(tool.ledger[k].values())
            if cnt == 0:
                continue
            f.write(json.dumps({
                "kind": k, "count": cnt, "distinct": len(tool.ledger[k]),
                "top_details": dict(tool.ledger[k].most_common(10)),
                "examples": tool.examples[k]}, ensure_ascii=False) + "\n")

    shipped_fns = sum(meta_rows[w]["functions"] for w in shipped_srcs)
    shipped_ops = sum(meta_rows[w]["ops"] for w in shipped_srcs)
    total_ops_all = sum(m["ops"] for m in meta_rows.values())
    report = {
        "_meta": {"buildid": BUILDID,
                  "tool": "pipeline/tools/hl_decompile.py --emit",
                  "generated_seconds": round(time.time() - t0, 1)},
        "totals": {
            "functions_rendered": totals["functions"],
            "ops_rendered": totals["ops"],
            "modules_attempted": len(meta_rows),
            "modules_shipped": len(shipped_srcs),
            "functions_shipped": shipped_fns,
            "ops_shipped": shipped_ops,
            "op_coverage_of_rendered":
                round(shipped_ops / max(1, total_ops_all) * 100, 2),
            "errors": len(errors),
        },
        "constants_materialized": dict(tool.const_stats),
        "modules_skipped": skipped[:200],
        "errors": errors[:50],
    }
    rep_path = os.path.join(DIGDIR, "decompile-report.json")
    with open(rep_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(f"DONE: modules shipped={len(shipped_srcs)} skipped={len(skipped)} "
          f"functions={shipped_fns} ops={shipped_ops} "
          f"({report['totals']['op_coverage_of_rendered']}% of rendered "
          f"ops) in {time.time() - t0:.0f}s")
    for sk in skipped[:20]:
        print(f"  SKIPPED {sk['module']}: {sk['functions_failed']} "
              f"fail(s): {str(sk['first_fail'])[:90]}")
    print(f"  -> {rep_path}")
    print(f"  -> {idx_path}")
    print(f"  -> {led_path}")
    return 0


def cmd_verify(tool):
    ok = True
    print("== known-semantics renders ==")
    os.makedirs(os.path.join(DIGDIR, "known-set"), exist_ok=True)
    for qual, why in KNOWN_SET:
        fx = find_findex_exact(tool.c, qual)
        if fx is None:
            print(f"  !! {qual}: NOT FOUND")
            ok = False
            continue
        fn = tool.c.fn_by_findex[fx]
        opseq = next(iter_opseq(fx))[1]
        try:
            fd, text, part = tool.render_function(fn, opseq)
        except Exception as e:  # noqa: BLE001
            print(f"  !! {qual}: RENDER ERROR {e!r}")
            ok = False
            continue
        out = os.path.join(DIGDIR, "known-set",
                           f"{qual.replace('.', '_')}.hx.txt")
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        expect = KNOWN_EXPECT.get(qual, [])
        missing = [tok for tok in expect if tok not in text]
        good = part and not missing
        print(f"  {qual} f#{fx} ({why}): partition="
              f"{'ok' if part else 'FAIL'}"
              f"{' MISSING=' + str(missing) if missing else ''} -> {out}")
        ok &= good
    print("VERIFY-KNOWN:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def cmd_audit_sample(tool, n):
    """Deterministically pick n functions from SHIPPED modules across
    packages; write the audit worksheet."""
    idx_path = os.path.join(SRCDIR, "_functions-index.jsonl")
    rows = []
    with open(idx_path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if "_meta" not in r:
                rows.append(r)
    rng = random.Random(AUDIT_SEED)
    # stratify: at least half from the game's own packages (src/...)
    own = [r for r in rows if r["debug_file"].startswith("src/")]
    other = [r for r in rows if not r["debug_file"].startswith("src/")]
    picked = sorted(rng.sample(own, min(n // 2 + n % 2, len(own))) +
                    rng.sample(other, min(n // 2, len(other))),
                    key=lambda r: r["findex"])
    out_dir = os.path.join(DIGDIR, "audit-sample")
    os.makedirs(out_dir, exist_ok=True)
    texts = []
    for r in picked:
        src_path = os.path.join(PACK, r["src"]["file"])
        with open(src_path, encoding="utf-8") as f:
            all_lines = f.read().split("\n")
        seg = all_lines[r["src"]["line"] - 1:
                        r["src"]["line"] + 60]
        texts.append((r, "\n".join(seg)))
    md = ["# Dig 13 — structured-text hand-audit sample",
          "",
          f"Deterministic sample (seed {AUDIT_SEED}): {len(picked)} of "
          f"{len(rows)} shipped functions, stratified ≥½ from `src/`.",
          "Each function was hand-traced against its dig-8 `.dis.hx` "
          "mirror (layer join via `_functions-index.jsonl`).",
          ""]
    for r, seg in texts:
        md.append(f"## f#{r['findex']} {r['name']}")
        md.append("")
        md.append(f"- sig `{r['sig']}` · debug `{r['debug_file']}:"
                  f"{r['line']}` · ops={r['nops']} · folded={r['folded']}")
        md.append(f"- src layer: `{r['src']['file']}:"
                  f"{r['src']['line']}` · dis layer: "
                  f"`{r['dis']['file']}:{r['dis']['line']}`" if r["dis"]
                  else "- dis layer: (missing)")
        md.append("")
        md.append("```haxe")
        md.append(seg)
        md.append("```")
        md.append("")
    out = os.path.join(out_dir, "audit-sample.mdx")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(md))
    print(f"AUDIT SAMPLE: {len(picked)} functions -> {out}")
    for r, _ in texts:
        print(f"  f#{r['findex']} {r['name']} "
              f"({r['debug_file']}:{r['line']})")
    return 0


def main():
    argv = sys.argv[1:]
    if "--extract-assigns" in argv:
        return extract_assigns()
    tool = DecompileTool()
    if "--emit" in argv:
        modules = None
        if "--modules" in argv:
            modules = set(argv[argv.index("--modules") + 1].split(","))
        prefix = argv[argv.index("--prefix") + 1] \
            if "--prefix" in argv else None
        out_root = argv[argv.index("--out") + 1]             if "--out" in argv else None
        return cmd_emit(tool, modules, prefix, out_root)
    if "--verify" in argv:
        return cmd_verify(tool)
    if "--audit-sample" in argv:
        n = int(argv[argv.index("--audit-sample") + 1])
        return cmd_audit_sample(tool, n)
    if "--function" in argv:
        fx = int(argv[argv.index("--function") + 1])
        fn = tool.c.fn_by_findex[fx]
        opseq = next(iter_opseq(fx))[1]
        try:
            _fd, text, part = tool.render_function(fn, opseq)
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            return 1
        print(text)
        print(f"// partition: {'ok' if part else 'FAIL'}")
        return 0 if part else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
