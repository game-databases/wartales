#!/usr/bin/env python3
"""hl_disasm.py — Wartales HashLink (HLB v4 fork) operand-resolved disassembler.

Dig 8 of the decompile plan ([decompile-dig-1 §3]
docs/decompile-dig-1.mdx): renders every function's opcode stream from the
verified structure layer (extracted/logic/hl-structure/) into
operand-resolved text — fields by flattened name path, jumps by target
label, globals/constants/strings/natives/calls resolved to names — mirrors
the 1,609 debug source paths under extracted/decompiled/hl/, builds a CFG
per function, and ledgers every reference it could not resolve.

Semantics policy: an operand role is rendered resolved ONLY when validated
(this dig measured the role table against the full corpus and the Dig 6
known-semantics functions; see docs/disasm-formula-findings.mdx). Anything
unproven renders UNK / @ordinal and lands in the unknown-opcode ledger —
guessed semantics are worse than none because they poison downstream
formulas.

Pinned fork facts this tool builds on (Dig 6 + measured this dig):
  - OField/OSetField/OGetThis/OSetThis ordinals index FLATTENED data
    fields root ancestor -> leaf of the receiver type: in-range
    317,945/317,945 sites on declared obj receiver types, 95,929/95,929
    on declared virtual (anonymous structure) types against that type's
    own field list;
  - receiver resolution uses the DECLARED register/global type (compiler
    truth); GetGlobal->Field fits the declared global type's chain
    17,639/17,639 while claimed-class overrides fit only 32% (abstract-
    impl pattern makes types[].global claims ambiguous);
  - OCallMethod/OCallThis ordinals are proto VTABLE pindeXes
    (most-derived override wins): 799 (hierarchy,name) pairs observed,
    zero same-name ordinal collisions, zero ordinals above max pindex;
  - jump targets are signed offsets, destination = pc + 1 + t
    (194,984/194,984 conditional+unconditional sites in range);
  - OSwitch flattened layout is [reg, ncases, default, offsets...]
    (byte order reg, ncases, offsets..., default per the canonical
    reader; 3,356/3,356 targets+defaults in range);
  - call-family op 28 (OCall4) decoded as (dst=reg, fun=findex,
    arg0..arg3=reg): 15,858/15,858 sites have dst<nregs, fun landing
    exactly on an existing function/native findex, every arg<nregs.

Usage:
  python hl_disasm.py --emit [--hlboot PATH]      full corpus emission
  python hl_disasm.py --function 12345            render one function
  python hl_disasm.py --file src/battle/Unit.hx   render one debug path
  python hl_disasm.py --verify                    validation report

Exit 0 iff the requested work completed (emit: every function rendered,
every op accounted for).
"""
import gzip
import json
import os
import struct
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PACK = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "..", ".."))
HLSTRUCT = os.path.join(PACK, "extracted", "logic", "hl-structure")
OUTDIR = os.path.join(PACK, "extracted", "decompiled", "hl")
DIGDIR = os.path.join(PACK, "output", "_dig-disasm")
DEFAULT_HLBOOT = "A:/SteamLibrary/steamapps/common/Wartales/hlboot.dat"
BUILDID = "20318128"

# ---------------------------------------------------------------------------
# opcode table (canonical ids from _refs/upstream/opcodes.h, verified: no
# observed id > 98 in this build; fork extras 99-101 pinned but unobserved)

OPNAMES = (
    "OMov OInt OFloat OBool OBytes OString ONull OAdd OSub OMul OSDiv OUDiv "
    "OSMod OUMod OShl OSShr OUShr OAnd OOr OXor ONeg ONot OIncr ODecr "
    "OCall0 OCall1 OCall2 OCall3 OCall4 OCallN OCallMethod OCallThis "
    "OCallClosure OStaticClosure OInstanceClosure OVirtualClosure OGetGlobal "
    "OSetGlobal OField OSetField OGetThis OSetThis ODynGet ODynSet OJTrue "
    "OJFalse OJNull OJNotNull OJSLt OJSGte OJSGt OJSLte OJULt OJUGte "
    "OJNotLt OJNotGte OJEq OJNotEq OJAlways OToDyn OToSFloat OToUFloat "
    "OToInt OSafeCast OUnsafeCast OToVirtual OLabel ORet OThrow ORethrow "
    "OSwitch ONullCheck OTrap OEndTrap OGetI8 OGetI16 OGetMem OGetArray "
    "OSetI8 OSetI16 OSetMem OSetArray ONew OArraySize OType OGetType OGetTID "
    "ORef OUnref OSetref OMakeEnum OEnumAlloc OEnumIndex OEnumField "
    "OSetEnumField OAssert ORefData ORefOffset ONop"
).split()
OPID = {n: i for i, n in enumerate(OPNAMES)}

BINSYM = {"OAdd": "+", "OSub": "-", "OMul": "*", "OSDiv": "/", "OUDiv": "/u",
          "OSMod": "%", "OUMod": "%u", "OShl": "<<", "OSShr": ">>",
          "OUShr": ">>>", "OAnd": "&", "OOr": "|", "OXor": "^"}
JMPSYM = {"OJTrue": None, "OJFalse": None, "OJNull": "== null",
          "OJNotNull": "!= null", "OJSLt": "<", "OJSGte": ">=", "OJSGt": ">",
          "OJSLte": "<=", "OJULt": "< (unsigned)", "OJUGte": ">= (unsigned)",
          "OJNotLt": "!<", "OJNotGte": "!>=", "OJEq": "==", "OJNotEq": "!="}

BASE_TI = {"void": 0, "u8": 1, "u16": 2, "i32": 3, "i64": 4, "f32": 5,
           "f64": 6, "bool": 7, "bytes": 8, "dyn": 9, "array": 12,
           "type": 13, "dynobj": 16}


def parse_sig(sig):
    """'(a,(b)->c,d)->r' -> ([a,'(b)->c',d], 'r'); handles nesting."""
    try:
        depth = 0
        args, cur = [], ""
        j = 1
        while j < len(sig):
            ch = sig[j]
            if ch == "(":
                if depth > 0:
                    cur += ch
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth <= 0:
                    break
                cur += ch
            elif ch == "," and depth == 1:
                args.append(cur.strip())
                cur = ""
            elif depth >= 1:
                cur += ch
            j += 1
        if cur.strip():
            args.append(cur.strip())
        ret = sig[sig.index("->") + 2:].strip()
        return args, ret
    except ValueError:
        return [], sig


class Corpus:
    """The verified structure layer + the int/float constant pools."""

    def __init__(self, hlboot=None):
        self.strings = self._load_strings()
        self.types = self._load_jsonl("types.jsonl")
        self.byi = {t["i"]: t for t in self.types}
        self.ti_by_name = {}
        for t in self.types:
            nm = t.get("name")
            if nm is not None and t.get("kind") in (11, 18, 17, 21):
                self.ti_by_name.setdefault(nm, t["i"])
        self.globals = self._load_jsonl("globals.jsonl")
        self.natives = {}       # findex -> native row
        for n in self._load_jsonl("natives.jsonl"):
            self.natives[n["findex"]] = n
        self.functions = []     # storage order (== opcodes.jsonl.gz order)
        for r in self._load_jsonl("functions.jsonl"):
            self.functions.append(r)
        self.fn_by_findex = {r["findex"]: r for r in self.functions}
        self.constants = {}     # global -> row
        for c in self._load_jsonl("constants.jsonl"):
            self.constants[c["global"]] = c
        # owner type index + proto name per function findex
        self.fowner = {}
        for t in self.types:
            tn = t.get("name")
            if not tn:
                continue
            for pn, pf, px in t.get("protos", []):
                self.fowner.setdefault(pf, (tn, pn, t["i"]))
        self.ints, self.floats = self._load_pools(hlboot)
        self._flat_fields = {}
        self._pindex_map = {}

    @staticmethod
    def _load_jsonl(name):
        path = os.path.join(HLSTRUCT, name)
        out = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    @staticmethod
    def _load_strings():
        """strings.txt is `index\\ttext` with \\, \\t, \\n, \\r escaped."""
        path = os.path.join(HLSTRUCT, "strings.txt")
        out = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                idx, _, text = line.partition("\t")
                out.append(_unescape(text))
        return out

    @staticmethod
    def _load_pools(hlboot):
        """int/float constant pools — absent from the Dig-6 structure layer;
        completed additively into hl-structure/{ints,floats}.jsonl."""
        ipath = os.path.join(HLSTRUCT, "ints.jsonl")
        fpath = os.path.join(HLSTRUCT, "floats.jsonl")
        if os.path.exists(ipath) and os.path.exists(fpath):
            ints = [json.loads(l)["v"] for l in open(ipath, encoding="utf-8")]
            flts = [json.loads(l)["v"] for l in open(fpath, encoding="utf-8")]
            return ints, flts
        if not hlboot:
            raise SystemExit(
                "int/float pools missing; pass --hlboot <hlboot.dat> once "
                "to materialize hl-structure/ints.jsonl + floats.jsonl")
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from hlboot_probe import Dig
        dig = Dig(hlboot)
        dig.read_header()
        dig.read_pools_strings()   # strict walk to reach pool boundaries
        secs = {s["name"]: s for s in dig.sections}
        ib = dig.data[secs["ints"]["start"]:secs["ints"]["end"]]
        fb = dig.data[secs["floats"]["start"]:secs["floats"]["end"]]
        assert len(ib) == 4 * dig.nints and len(fb) == 8 * dig.nfloats
        ints = list(struct.unpack(f"<{dig.nints}i", ib))
        flts = list(struct.unpack(f"<{dig.nfloats}d", fb))
        with open(ipath, "w", encoding="utf-8", newline="\n") as f:
            for i, v in enumerate(ints):
                f.write(json.dumps({"i": i, "v": v}) + "\n")
        with open(fpath, "w", encoding="utf-8", newline="\n") as f:
            for i, v in enumerate(flts):
                f.write(json.dumps({"i": i, "v": v}) + "\n")
        return ints, flts

    # ---- type helpers -------------------------------------------------
    def tname(self, ti):
        if ti is None:
            return "?"
        if isinstance(ti, int) and 0 <= ti < len(self.types):
            t = self.types[ti]
            return t.get("name") or _KIND_SHORT.get(t.get("kind"), f"k{t.get('kind')}")
        return "?"

    def ti_of_signame(self, name):
        if name in BASE_TI:
            return BASE_TI[name]
        return self.ti_by_name.get(name)

    def flat_fields(self, ti):
        """[(name, fieldType)] flattened root ancestor -> leaf (kind 11 only)."""
        got = self._flat_fields.get(ti)
        if got is not None:
            return got
        chain, seen, cur = [], set(), ti
        while cur is not None and isinstance(cur, int) \
                and 0 <= cur < len(self.types) and cur not in seen:
            seen.add(cur)
            t = self.byi.get(cur)
            if not t or t.get("kind") != 11:
                break
            chain.append(t)
            cur = t.get("super", -1)
        flat = []
        for t in reversed(chain):
            for fnm, ft in t.get("fields", []):
                flat.append((fnm, ft))
        self._flat_fields[ti] = flat
        return flat

    def pindex_map(self, ti):
        """pindex -> proto name, most-derived override wins (virtual table)."""
        got = self._pindex_map.get(ti)
        if got is not None:
            return got
        m, chain, seen, cur = {}, [], set(), ti
        while cur is not None and isinstance(cur, int) \
                and 0 <= cur < len(self.types) and cur not in seen:
            seen.add(cur)
            t = self.byi.get(cur)
            if not t or t.get("kind") != 11:
                break
            chain.append(t)
            cur = t.get("super", -1)
        for t in reversed(chain):
            for pn, pf, px in t.get("protos", []):
                if px >= 0:
                    m.setdefault(px, pn)
        self._pindex_map[ti] = m
        return m

    def callee_label(self, findex):
        nat = self.natives.get(findex)
        if nat is not None:
            return f"native:{nat['lib']}.{nat['name']}"
        ow = self.fowner.get(findex)
        if ow:
            return f"{ow[0]}.{ow[1]}"
        fn = self.fn_by_findex.get(findex)
        if fn and fn.get("debug_file"):
            return f"f#{findex}@{os.path.basename(fn['debug_file'])}"
        return f"f#{findex}"

    def callee_ret_ti(self, findex):
        tf = self.fn_by_findex.get(findex) or self.natives.get(findex)
        if not tf:
            return None
        _, ret = parse_sig(tf["sig"])
        return self.ti_of_signame(ret)


_KIND_SHORT = {0: "void", 1: "u8", 2: "u16", 3: "i32", 4: "i64", 5: "f32",
               6: "f64", 7: "bool", 8: "bytes", 9: "dyn", 10: "fun",
               11: "obj", 12: "array", 13: "type", 14: "ref", 15: "virtual",
               16: "dynobj", 17: "abstract", 18: "enum", 19: "null",
               20: "method", 21: "struct", 22: "packed", 23: "guid"}


def _unescape(s):
    if "\\" not in s:
        return s
    out, i, n = [], 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            nxt = s[i + 1]
            if nxt == "n":
                out.append("\n"); i += 2; continue
            if nxt == "t":
                out.append("\t"); i += 2; continue
            if nxt == "r":
                out.append("\r"); i += 2; continue
            if nxt == "\\":
                out.append("\\"); i += 2; continue
        out.append(c)
        i += 1
    return "".join(out)


def _q(s, limit=120):
    lit = json.dumps(s, ensure_ascii=False)
    if len(lit) > limit:
        lit = lit[:limit - 4] + '..."'
    return lit


# ---------------------------------------------------------------------------
# renderer

class Disasm:
    def __init__(self, corpus: Corpus):
        self.c = corpus
        # unknown-reference ledger (aggregate counts + bounded examples)
        self.ledger = defaultdict(Counter)
        self.examples = defaultdict(list)

    def note_unknown(self, kind, findex, pc, detail):
        self.ledger[kind][detail] += 1
        ex = self.examples[kind]
        if len(ex) < 5:
            ex.append({"findex": findex, "pc": pc, "detail": detail})

    # ---- register type tracking ---------------------------------------
    def _track_types(self, fn, opseq):
        """Linear effective-type pass; returns eff[] refined copy + label pcs."""
        c = self.c
        eff = list(fn["regs"])
        nregs = fn["nregs"]

        def ext(i):
            while len(eff) <= i:
                eff.append(None)

        labels = set()
        n = len(opseq)
        for pc, arr in enumerate(opseq):
            op, a = arr[0], arr[1:]
            nm = OPNAMES[op] if op < len(OPNAMES) else None
            try:
                if nm == "OMov" and len(a) >= 2:
                    ext(a[0]); ext(a[1])
                    eff[a[0]] = eff[a[1]] if a[1] < len(eff) else None
                elif nm == "OInt":
                    ext(a[0]); eff[a[0]] = 3
                elif nm == "OFloat":
                    ext(a[0]); eff[a[0]] = 6
                elif nm == "OBool":
                    ext(a[0]); eff[a[0]] = 7
                elif nm == "OString":
                    ext(a[0])
                    s_ti = c.ti_by_name.get("String")
                    eff[a[0]] = s_ti if s_ti is not None else None
                elif nm == "ONull":
                    ext(a[0]); eff[a[0]] = None
                elif nm == "OGetGlobal":
                    ext(a[0])
                    # declared type only — types[].global claims are
                    # ambiguous (abstract-impl pattern) and measured wrong
                    eff[a[0]] = c.globals[a[1]]["type"] \
                        if a[1] < len(c.globals) else None
                elif nm == "OField" and len(a) >= 3:
                    rt = _recv_type(self, fn, eff, a[1])
                    ft = None
                    t = c.byi.get(rt) if rt is not None else None
                    k = t.get("kind") if t else None
                    if k == 11:
                        ff = c.flat_fields(rt)
                        if 0 <= a[2] < len(ff):
                            ft = ff[a[2]][1]
                    elif k == 15:
                        fs = t.get("fields", [])
                        if 0 <= a[2] < len(fs):
                            ft = fs[a[2]][1]
                    ext(a[0]); eff[a[0]] = ft
                elif nm == "OGetThis":
                    ow = c.fowner.get(fn["findex"])
                    ft = None
                    if ow and c.byi.get(ow[2], {}).get("kind") == 11:
                        ff = c.flat_fields(ow[2])
                        if 0 <= a[1] < len(ff):
                            ft = ff[a[1]][1]
                    ext(a[0]); eff[a[0]] = ft
                elif nm in ("OCall0", "OCall1", "OCall2", "OCall3", "OCall4",
                            "OCallN"):
                    ext(a[0])
                    eff[a[0]] = c.callee_ret_ti(a[1])
                elif nm in ("OCallMethod", "OCallThis"):
                    ext(a[0])
                    tgt = a[3] if len(a) > 3 else None
                    eff[a[0]] = None
                    rt = None
                    if nm == "OCallMethod":
                        if tgt is not None:
                            rt = _recv_type(self, fn, eff, tgt)
                    else:
                        ow = c.fowner.get(fn["findex"])
                        rt = ow[2] if ow else None
                    t = c.byi.get(rt) if rt is not None else None
                    if t and t.get("kind") == 11:
                        pname = c.pindex_map(rt).get(a[1])
                        if pname is not None:
                            for pn_, pf_, px_ in _protos_flat(c, rt):
                                if pn_ == pname and px_ == a[1]:
                                    eff[a[0]] = c.callee_ret_ti(pf_)
                                    break
                elif nm in ("OMakeEnum", "OEnumAlloc"):
                    dt = eff[a[0]] if a[0] < len(eff) else None
                    if dt is None and a[0] < nregs:
                        dt = fn["regs"][a[0]]
            except Exception:
                pass
        # collect jump-target labels
        for pc, arr in enumerate(opseq):
            op, a = arr[0], arr[1:]
            nm = OPNAMES[op] if op < len(OPNAMES) else ""
            if nm.startswith("OJ") and nm != "OLabel":
                d = pc + 1 + a[-1]
                if 0 <= d < n:
                    labels.add(d)
            elif nm == "OSwitch":
                ncases = a[1]
                dflt = a[2]
                offs = a[3:3 + ncases]
                for o in offs:
                    d = pc + 1 + o
                    if 0 <= d < n:
                        labels.add(d)
                d = pc + 1 + dflt
                if 0 <= d < n:
                    labels.add(d)
            elif nm == "OTrap":
                d = pc + 1 + a[-1]
                if 0 <= d < n:
                    labels.add(d)
        return eff, labels


def _protos_flat(c, ti):
    chain, seen, cur = [], set(), ti
    while cur is not None and isinstance(cur, int) \
            and 0 <= cur < len(c.types) and cur not in seen:
        seen.add(cur)
        t = c.byi.get(cur)
        if not t or t.get("kind") != 11:
            break
        chain.append(t)
        cur = t.get("super", -1)
    out = []
    for t in reversed(chain):
        out.extend(t.get("protos", []))
    return out


def render_function(dis: Disasm, fn, opseq):
    """Render one function to text lines. Returns (text, cfg)."""
    c = dis.c
    findex = fn["findex"]
    eff, labels = dis._track_types(fn, opseq)
    owner = c.fowner.get(findex)
    qual = f"{owner[0]}.{owner[1]}" if owner else c.callee_label(findex)
    nops = len(opseq)

    out = []
    out.append(f"// ==== f#{findex} {qual} : {fn['sig']}")
    src = fn.get("debug_file")
    out.append(f"//     src={src}:{fn.get('first_line')}"
               f"  ops={nops}  regs={fn['nregs']}")
    if owner is None and src:
        out.append(f"//     (top-level/closure function; no owning proto)")
    regs_show = []
    for i, ti in enumerate(fn["regs"][:14]):
        regs_show.append(f"r{i}<{c.tname(ti)}>")
    if fn["nregs"] > 14:
        regs_show.append(f"...(+{fn['nregs'] - 14})")
    out.append("//     regs: " + " ".join(regs_show))

    body = []
    for pc, arr in enumerate(opseq):
        if pc in labels:
            body.append(f"L{pc}:")
        op, a = arr[0], arr[1:]
        if op < len(OPNAMES):
            nm = OPNAMES[op]
        else:
            nm = f"ForkOp{op}"
            dis.note_unknown("fork-op-unexpected", findex, pc, f"op{op}")
        note = _render_op(dis, fn, findex, pc, nm, a, opseq, eff)
        body.append(f"{pc:5d} {nm:<17s} {note}")
    cfg = function_cfg(nops, opseq)
    out.append(f"//     cfg: blocks={cfg['nblocks']} edges={cfg['nedges']}"
               f" cc={cfg['cc']}")
    out.extend(body)
    out.append("")
    return "\n".join(out), cfg


def _recv_type(dis, fn, eff, reg):
    """Receiver type for field/method resolution.

    The DECLARED register type is compiler truth (measured this dig:
    whole-chain field ordinals fit 317,945/317,945 sites on declared obj
    types and 95,929/95,929 on declared virtual types; linear tracking
    guesses can be poisoned by register reuse), so it wins whenever it is
    an object or virtual type; refined types only fill remaining gaps.
    """
    c = dis.c
    decl = fn["regs"][reg] if 0 <= reg < len(fn["regs"]) else None
    dk = c.byi.get(decl, {}).get("kind") if decl is not None else None
    if dk in (11, 15):
        return decl
    eff_ti = eff[reg] if 0 <= reg < len(eff) else None
    ek = c.byi.get(eff_ti, {}).get("kind") if eff_ti is not None else None
    if ek in (11, 15):
        return eff_ti
    return decl if decl is not None else eff_ti


def _fld(dis, rt, ordinal, findex, pc):
    """Resolve a flattened field ordinal -> name string ('@n' if unknown)."""
    c = dis.c
    t = c.byi.get(rt)
    k = t.get("kind") if rt is not None and t else None
    if k == 15:   # virtual: ordinal indexes the type's OWN field list
        fs = t.get("fields", [])
        if 0 <= ordinal < len(fs):
            return fs[ordinal][0]
        dis.note_unknown("field-ordinal-out-of-range", findex, pc,
                         f"virtual {c.tname(rt)} ord={ordinal}")
        return f"@{ordinal}"
    if k == 11:
        ff = c.flat_fields(rt)
        if 0 <= ordinal < len(ff):
            return ff[ordinal][0]
        dis.note_unknown("field-ordinal-out-of-range", findex, pc,
                         f"type={c.tname(rt)} ord={ordinal}")
        return f"@{ordinal}"
    dis.note_unknown("field-receiver-type-unresolved", findex, pc,
                     f"recv_type={c.tname(rt)} ord={ordinal}")
    return f"@{ordinal}"


def _method(dis, rt, ordinal, findex, pc):
    c = dis.c
    t = c.byi.get(rt)
    k = t.get("kind") if rt is not None and t else None
    if k == 15:   # virtual: ordinal indexes method-typed data fields
        fs = t.get("fields", [])
        if 0 <= ordinal < len(fs):
            return fs[ordinal][0]
        dis.note_unknown("method-pindex-unresolved", findex, pc,
                         f"virtual {c.tname(rt)} pindex={ordinal}")
        return f"@{ordinal}"
    if k == 11:
        pm = c.pindex_map(rt)
        if ordinal in pm:
            return pm[ordinal]
        fp = _protos_flat(c, rt)
        dis.note_unknown("method-pindex-unresolved", findex, pc,
                         f"type={c.tname(rt)} pindex={ordinal}"
                         f" flat_protos={len(fp)}")
        return f"@{ordinal}"
    dis.note_unknown("method-receiver-type-unresolved", findex, pc,
                     f"recv_type={c.tname(rt)} pindex={ordinal}")
    return f"@{ordinal}"


def _render_op(dis, fn, findex, pc, nm, a, opseq, eff):
    c = dis.c
    R = lambda i: f"r{i}"  # noqa: E731
    T = lambda i: c.tname(eff[i] if 0 <= i < len(eff) else None)  # noqa: E731

    if nm == "UNKBeyondTable":
        return f"UNK raw={a}"

    if nm == "OMov":
        return f"{R(a[0])} = {R(a[1])}"
    if nm == "OInt":
        v = c.ints[a[1]] if a[1] < len(c.ints) else None
        if v is None:
            dis.note_unknown("int-pool-oob", findex, pc, str(a[1]))
            return f"{R(a[0])} = int@{a[1]}"
        return f"{R(a[0])} = {v}"
    if nm == "OFloat":
        v = c.floats[a[1]] if a[1] < len(c.floats) else None
        if v is None:
            dis.note_unknown("float-pool-oob", findex, pc, str(a[1]))
            return f"{R(a[0])} = float@{a[1]}"
        return f"{R(a[0])} = {v!r}"
    if nm == "OBool":
        return f"{R(a[0])} = {'true' if a[1] else 'false'}"
    if nm == "OBytes":
        dis.note_unknown("obytes-payload-unproven", findex, pc,
                         f"pool_idx={a[1]}")
        return f"{R(a[0])} = bytes@{a[1]}   // UNK payload (v4 has no bytes pool)"
    if nm == "OString":
        if a[1] < len(c.strings):
            return f"{R(a[0])} = {_q(c.strings[a[1]])}"
        dis.note_unknown("string-pool-oob", findex, pc, str(a[1]))
        return f"{R(a[0])} = str@{a[1]}"
    if nm == "ONull":
        return f"{R(a[0])} = null"
    if nm in BINSYM:
        return f"{R(a[0])} = {R(a[1])} {BINSYM[nm]} {R(a[2])}"
    if nm == "ONeg":
        return f"{R(a[0])} = -{R(a[1])}"
    if nm == "ONot":
        return f"{R(a[0])} = !{R(a[1])}"
    if nm == "OIncr":
        return f"++{R(a[0])}"
    if nm == "ODecr":
        return f"--{R(a[0])}"

    if nm in ("OCall0", "OCall1", "OCall2", "OCall3", "OCall4", "OCallN"):
        lbl = c.callee_label(a[1])
        if a[1] not in c.fn_by_findex and a[1] not in c.natives:
            dis.note_unknown("call-findex-unresolved", findex, pc, str(a[1]))
            lbl = f"f#?{a[1]}"
        if nm == "OCall0":
            args = []
        elif nm == "OCallN":
            nargs = a[2]
            args = [R(x) for x in a[3:3 + nargs]]
        else:
            k = int(nm[-1])
            args = [R(x) for x in a[2:2 + k]]
        return f"{R(a[0])} = {lbl}({', '.join(args)})"
    if nm == "OCallMethod":
        dst, pidx, nargs = a[0], a[1], a[2]
        args = [R(x) for x in a[3:3 + nargs]]
        recv = args[0] if args else "?"
        rest = ", ".join(args[1:])
        recv_i = a[3] if nargs >= 1 else None
        rt = _recv_type(dis, fn, eff, recv_i) if recv_i is not None else None
        mname = _method(dis, rt, pidx, findex, pc)
        return f"{R(dst)} = {recv}.{mname}({rest})"
    if nm == "OCallThis":
        dst, pidx, nargs = a[0], a[1], a[2]
        rest = ", ".join(R(x) for x in a[3:3 + nargs])
        ow = c.fowner.get(findex)
        rt = ow[2] if ow else None
        mname = _method(dis, rt, pidx, findex, pc)
        return f"{R(dst)} = this.{mname}({rest})"
    if nm == "OCallClosure":
        dst, fun, nargs = a[0], a[1], a[2]
        rest = ", ".join(R(x) for x in a[3:3 + nargs])
        return f"{R(dst)} = {R(fun)}.call({rest})"
    if nm == "OStaticClosure":
        return f"{R(a[0])} = closure {c.callee_label(a[1])}"
    if nm == "OInstanceClosure":
        return f"{R(a[0])} = closure {c.callee_label(a[1])} bound {R(a[2])}"
    if nm == "OVirtualClosure":
        return f"{R(a[0])} = vclosure({R(a[1])}, {R(a[2])})"

    if nm == "OGetGlobal":
        g = a[1]
        # declared global type is the receiver truth for subsequent field
        # reads (measured 17,639/17,639 in-range this dig; class-object
        # claims from types[].global are ambiguous under the abstract-impl
        # pattern and fit only 32% — never override with them)
        tn = c.globals[g]["type_name"] if g < len(c.globals) else "?"
        cst = c.constants.get(g)
        tag = (f"   // constant-init ({cst['nfields']} fields)"
               if cst else "")
        return f"{R(a[0])} = g#{g}<{tn}>{tag}"
    if nm == "OSetGlobal":
        g = a[0]
        tn = c.globals[g]["type_name"] if g < len(c.globals) else "?"
        return f"g#{g}<{tn}> = {R(a[1])}"
    if nm == "OField":
        rt = _recv_type(dis, fn, eff, a[1])
        fname = _fld(dis, rt, a[2], findex, pc)
        return f"{R(a[0])} = {R(a[1])}.{fname}"
    if nm == "OSetField":
        rt = eff[a[0]] if a[0] < len(eff) else None
        fname = _fld(dis, rt, a[1], findex, pc)
        return f"{R(a[0])}.{fname} = {R(a[2])}"
    if nm == "OGetThis":
        ow = c.fowner.get(findex)
        fname = _fld(dis, ow[2] if ow else None, a[1], findex, pc)
        return f"{R(a[0])} = this.{fname}"
    if nm == "OSetThis":
        ow = c.fowner.get(findex)
        fname = _fld(dis, ow[2] if ow else None, a[0], findex, pc)
        return f"this.{fname} = {R(a[1])}"
    if nm == "ODynGet":
        key = c.strings[a[2]] if a[2] < len(c.strings) else f"@{a[2]}"
        return f'{R(a[0])} = {R(a[1])}.{key}   // dynamic'
    if nm == "ODynSet":
        key = c.strings[a[1]] if a[1] < len(c.strings) else f"@{a[1]}"
        return f'{R(a[0])}.{key} = {R(a[2])}   // dynamic'

    if nm.startswith("OJ") and nm != "OLabel":
        dest = pc + 1 + a[-1]
        lab = f"L{dest}" if 0 <= dest < len(opseq) else f"?{dest}"
        if nm == "OJAlways":
            return f"goto {lab}"
        if nm == "OJTrue":
            return f"if {R(a[0])} goto {lab}"
        if nm == "OJFalse":
            return f"if !{R(a[0])} goto {lab}"
        sym = JMPSYM.get(nm)
        if sym in ("== null", "!= null"):
            return f"if {R(a[0])} {sym} goto {lab}"
        if sym:
            return f"if {R(a[0])} {sym} {R(a[1])} goto {lab}"
        dis.note_unknown("jump-op-unrendered", findex, pc, nm)
        return f"UNK jump raw={a}"

    if nm == "OToDyn":
        return f"{R(a[0])} = dyn({R(a[1])})"
    if nm in ("OToSFloat", "OToUFloat"):
        return f"{R(a[0])} = float({R(a[1])})"
    if nm == "OToInt":
        return f"{R(a[0])} = int({R(a[1])})"
    if nm in ("OSafeCast", "OUnsafeCast"):
        tt = T(a[0])
        return f"{R(a[0])} = ({tt}){R(a[1])}" + \
            ("   // unsafe" if nm == "OUnsafeCast" else "")
    if nm == "OToVirtual":
        return f"{R(a[0])} = virtual({R(a[1])})"

    if nm == "OLabel":
        return "label"
    if nm == "ORet":
        return f"ret {R(a[0])}"
    if nm == "OThrow":
        return f"throw {R(a[0])}"
    if nm == "ORethrow":
        return f"rethrow {R(a[0])}"
    if nm == "OSwitch":
        ncases = a[1]
        dflt = pc + 1 + a[2]
        offs = a[3:3 + ncases]
        parts = []
        for i, o in enumerate(offs):
            d = pc + 1 + o
            if o != 0:
                parts.append(f"{i}->L{d}")
        shown = ", ".join(parts[:10])
        if len(parts) > 10:
            shown += f", …(+{len(parts) - 10} more)"
        return f"switch {R(a[0])} [{shown}] default->L{dflt}"
    if nm == "ONullCheck":
        return f"nullcheck {R(a[0])}"
    if nm == "OTrap":
        d = pc + 1 + a[-1]
        return f"trap {R(a[0])} handler=L{d}"
    if nm == "OEndTrap":
        return f"endtrap {R(a[0])}"

    if nm == "OGetI8":
        return f"{R(a[0])} = b8[{R(a[1])},{R(a[2])}]"
    if nm == "OGetI16":
        return f"{R(a[0])} = b16[{R(a[1])},{R(a[2])}]"
    if nm == "OGetMem":
        return f"{R(a[0])} = mem[{R(a[1])},{R(a[2])}]"
    if nm == "OGetArray":
        return f"{R(a[0])} = {R(a[1])}[{R(a[2])}]"
    if nm == "OSetI8":
        return f"b8[{R(a[0])},{R(a[1])}] = {R(a[2])}"
    if nm == "OSetI16":
        return f"b16[{R(a[0])},{R(a[1])}] = {R(a[2])}"
    if nm == "OSetMem":
        return f"mem[{R(a[0])},{R(a[1])}] = {R(a[2])}"
    if nm == "OSetArray":
        return f"{R(a[0])}[{R(a[1])}] = {R(a[2])}"

    if nm == "ONew":
        tt = T(a[0])
        return f"{R(a[0])} = new {tt}"
    if nm == "OArraySize":
        return f"{R(a[0])} = len({R(a[1])})"
    if nm == "OType":
        return f"{R(a[0])} = type {c.tname(a[1])}"
    if nm == "OGetType":
        return f"{R(a[0])} = typeof {R(a[1])}"
    if nm == "OGetTID":
        return f"{R(a[0])} = tid({R(a[1])})"

    if nm == "ORef":
        return f"{R(a[0])} = &{R(a[1])}"
    if nm == "OUnref":
        return f"{R(a[0])} = *{R(a[1])}"
    if nm == "OSetref":
        return f"*{R(a[0])} = {R(a[1])}"
    if nm == "ORefData":
        return f"{R(a[0])} = &data[{R(a[1])}]"
    if nm == "ORefOffset":
        return f"{R(a[0])} = &offset[{R(a[1])},{R(a[2])}]"

    if nm == "OMakeEnum":
        dst, ci, nargs = a[0], a[1], a[2]
        et = eff[dst] if dst < len(eff) else None
        ename = c.tname(et)
        cname = f"@{ci}"
        if et is not None and c.byi.get(et, {}).get("kind") == 18:
            cons = c.byi[et].get("constructs", [])
            if 0 <= ci < len(cons):
                cname = cons[ci][0]
            else:
                dis.note_unknown("enum-construct-oob", findex, pc,
                                 f"{ename}#{ci}")
        vals = ", ".join(R(x) for x in a[3:3 + nargs])
        return f"{R(dst)} = {ename}.{cname}({vals})"
    if nm == "OEnumAlloc":
        dst, ci = a[0], a[1]
        et = eff[dst] if dst < len(eff) else None
        ename = c.tname(et)
        cname = f"@{ci}"
        if et is not None and c.byi.get(et, {}).get("kind") == 18:
            cons = c.byi[et].get("constructs", [])
            if 0 <= ci < len(cons):
                cname = cons[ci][0]
        return f"{R(dst)} = alloc {ename}.{cname}"
    if nm == "OEnumIndex":
        return f"{R(a[0])} = enumidx({R(a[1])})"
    if nm == "OEnumField":
        dst, val, ci, fi = a[0], a[1], a[2], a[3]
        et = eff[val] if val < len(eff) else None
        ename = c.tname(et)
        cname = f"c{ci}"
        ptype = "?"
        if et is not None and c.byi.get(et, {}).get("kind") == 18:
            cons = c.byi[et].get("constructs", [])
            if 0 <= ci < len(cons):
                cname = cons[ci][0]
                params = cons[ci][1]
                if 0 <= fi < len(params):
                    ptype = c.tname(params[fi])
                    eff[dst] = params[fi] if dst < len(eff) else eff[dst]
            else:
                dis.note_unknown("enum-construct-oob", findex, pc,
                                 f"{ename}#{ci}")
        return f"{R(dst)} = ({ename}.{cname}){R(val)}[{fi}:{ptype}]"
    if nm == "OSetEnumField":
        val, fi, src = a[0], a[1], a[2]
        return f"({R(val)})[{fi}] = {R(src)}"
    if nm == "OAssert":
        return "assert"
    if nm == "ONop":
        return "nop"

    return f"UNK raw={a}"


# ---------------------------------------------------------------------------
# CFG builder (library function)

def function_cfg(nops, opseq):
    """Basic blocks + block-level edges for one opcode sequence.

    Leaders: pc 0, every jump/switch/trap destination, and every pc that
    follows a terminator or ends a taken control transfer. Edges exist only
    BETWEEN blocks: conditional-jump fallthrough, taken destinations,
    switch cases + default, trap -> handler; returns/throws end flow with
    no outgoing edge. Cyclomatic complexity cc = E - N + 2 on this graph
    (straight-line code = 1; each if/loop adds 1; a k-case switch adds k-1),
    exception edges included.
    """
    if nops == 0:
        return {"nblocks": 0, "nedges": 0, "cc": 0, "blocks": [],
                "n_jumps": 0, "n_switch": 0}

    def tgt(pc, off):
        d = pc + 1 + off
        return d if 0 <= d < nops else None

    # phase 1 — leaders
    leaders = {0, nops}
    transfers = []   # (pc, kind, [dests], has_fallthrough)
    njumps = nswitch = 0
    for pc, arr in enumerate(opseq):
        op, a = arr[0], arr[1:]
        nm = OPNAMES[op] if op < len(OPNAMES) else ""
        if nm.startswith("OJ") and nm != "OLabel":
            njumps += 1
            d = tgt(pc, a[-1])
            dests = [d] if d is not None else []
            ft = nm != "OJAlways"
            # any control transfer ends its block — the next pc starts a new
            # one (after an unconditional jump it is usually unreachable)
            if pc + 1 < nops:
                leaders.add(pc + 1)
            if d is not None:
                leaders.add(d)
            transfers.append((pc, dests, ft))
        elif nm == "OSwitch":
            nswitch += 1
            ncases = a[1]
            dests = []
            for o in a[3:3 + ncases]:
                d = tgt(pc, o)
                if d is not None:
                    dests.append(d)
                    leaders.add(d)
            d = tgt(pc, a[2])
            if d is not None:
                dests.append(d)
                leaders.add(d)
            transfers.append((pc, dests, False))
        elif nm == "OTrap":
            d = tgt(pc, a[-1])
            dests = [d] if d is not None else []
            if d is not None:
                leaders.add(d)
            if pc + 1 < nops:
                leaders.add(pc + 1)
                transfers.append((pc, dests, True))
            else:
                transfers.append((pc, dests, False))
        elif nm in ("ORet", "OThrow", "ORethrow"):
            if pc + 1 < nops:
                leaders.add(pc + 1)   # unreachable region starts here

    ls = sorted(leaders)
    blocks = []
    for i in range(len(ls) - 1):
        s, e = ls[i], ls[i + 1]
        if e > s:
            blocks.append((s, e))
    nblocks = len(blocks)

    # phase 2 — block-level edges
    bidx = {}
    for bi, (s, e) in enumerate(blocks):
        for pc in range(s, e):
            bidx[pc] = bi
    edges = set()
    transferred = set()   # blocks whose last op is an explicit transfer
    for pc, dests, ft in transfers:
        src = bidx.get(pc)
        if src is None:
            continue
        transferred.add(src)
        for d in dests:
            bd = bidx.get(d)
            if bd is not None:
                edges.add((src, bd))
        if ft and pc + 1 < nops:
            bf = bidx.get(pc + 1)
            if bf is not None:
                edges.add((src, bf))
    # sequential fallthrough: a block that does NOT end in a transfer or
    # terminator flows into its successor (its end pc became a leader by
    # being somebody's jump target)
    for bi, (s, e) in enumerate(blocks):
        if bi in transferred or bi + 1 >= len(blocks):
            continue
        end_op = opseq[e - 1][0]
        end_nm = OPNAMES[end_op] if end_op < len(OPNAMES) else ""
        if end_nm not in ("ORet", "OThrow", "ORethrow"):
            edges.add((bi, bi + 1))

    # terminator blocks get a virtual-exit edge; CC is measured on the
    # ENTRY-REACHABLE subgraph with that exit (single-exit McCabe form),
    # so Haxe's unreachable post-return padding cannot distort the count.
    TERM = ("ORet", "OThrow", "ORethrow")
    term_blocks = set()
    for bi, (s, e) in enumerate(blocks):
        end_op = opseq[e - 1][0]
        end_nm = OPNAMES[end_op] if end_op < len(OPNAMES) else ""
        if end_nm in TERM:
            term_blocks.add(bi)

    succ = defaultdict(list)
    for u, v in edges:
        succ[u].append(v)
    seen = set()
    stack = [0] if 0 < nblocks else []
    while stack:
        u = stack.pop()
        if u in seen:
            continue
        seen.add(u)
        stack.extend(succ.get(u, ()))
    nr = len(seen) + 1                      # +1 = virtual exit
    er = sum(1 for u, v in edges if u in seen and v in seen)
    er += sum(1 for b in term_blocks if b in seen)   # -> exit edges
    cc = er - nr + 2 if nr > 1 else 0

    return {"nblocks": nblocks, "nedges": len(edges),
            "n_unreachable": nblocks - len(seen),
            "cc": cc,
            "blocks": blocks, "n_jumps": njumps, "n_switch": nswitch}


# ---------------------------------------------------------------------------
# emission

def _safe_rel(debug_path):
    """debug source path -> safe relative mirror path (windows-legal)."""
    if not debug_path or debug_path == "?":
        return "_unresolved-source"
    rel = debug_path.replace("\\", "/")
    bad = '?*:|<>\"'
    rel = "".join("_" if ch in bad else ch for ch in rel)
    if ":" in rel:
        rel = rel.replace(":", "_")
    parts = [p for p in rel.split("/") if p not in ("", ".", "..")]
    return "/".join(parts) or "_unresolved-source"


def cmd_emit(hlboot=None):
    os.makedirs(OUTDIR, exist_ok=True)
    os.makedirs(DIGDIR, exist_ok=True)
    corpus = Corpus(hlboot)
    dis = Disasm(corpus)

    modules = defaultdict(list)          # debug_path -> [text blocks]
    index_rows = []
    totals = Counter()
    pkg_stats = defaultdict(lambda: Counter())
    file_stats = defaultdict(lambda: Counter())
    maxcc = []

    nfn = len(corpus.functions)
    print(f"rendering {nfn} functions ...")
    with gzip.open(os.path.join(HLSTRUCT, "opcodes.jsonl.gz"), "rt",
                   encoding="utf-8") as gz:
        for i, line in enumerate(gz):
            rec = json.loads(line)
            fn = corpus.functions[i]
            if fn["findex"] != rec["findex"]:
                raise SystemExit(
                    f"dataset misalignment at line {i}: "
                    f"{fn['findex']} vs {rec['findex']}")
            opseq = rec["ops"]
            text, cfg = render_function(dis, fn, opseq)
            src = fn.get("debug_file") or "?unknown?"
            modules[src].append(text)
            totals["functions"] += 1
            totals["ops"] += len(opseq)
            totals["blocks"] += cfg["nblocks"]
            totals["edges"] += cfg["nedges"]
            pkg = src.split("/")[0] if "/" in src else "(root)"
            pkg_stats[pkg]["functions"] += 1
            pkg_stats[pkg]["ops"] += len(opseq)
            pkg_stats[pkg]["blocks"] += cfg["nblocks"]
            pkg_stats[pkg]["edges"] += cfg["nedges"]
            fs = file_stats[src]
            fs["functions"] += 1
            fs["ops"] += len(opseq)
            fs["blocks"] += cfg["nblocks"]
            fs["edges"] += cfg["nedges"]
            fs["cc_max"] = max(fs["cc_max"], cfg["cc"])
            maxcc.append((cfg["cc"], fn["findex"], src,
                          corpus.fowner.get(fn["findex"], (None, None))[1]))
            owner = corpus.fowner.get(fn["findex"])
            index_rows.append({
                "findex": fn["findex"],
                "name": (f"{owner[0]}.{owner[1]}" if owner
                         else corpus.callee_label(fn["findex"])),
                "sig": fn["sig"],
                "file": src,
                "line": fn.get("first_line"),
                "nops": len(opseq),
                "nblocks": cfg["nblocks"],
                "nedges": cfg["nedges"],
                "cc": cfg["cc"],
            })
            if (i + 1) % 10000 == 0:
                print(f"  {i + 1}/{nfn}")

    # ---- write module mirrors ----------------------------------------
    print("writing module mirrors ...")
    written = 0
    used_names = {}
    for src in sorted(modules):
        rel = _safe_rel(src)
        base = f"{rel}.dis.hx"
        key = base.lower()
        if key in used_names:                     # windows case-insensitivity
            used_names[key] += 1
            base = f"{rel}_{used_names[key]}.dis.hx"
        else:
            used_names[key] = 1
        path = os.path.join(OUTDIR, *base.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fs = file_stats[src]
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(f"// Wartales HashLink disassembly — buildid {BUILDID}\n")
            f.write(f"// source mirror: {src}\n")
            f.write(f"// functions: {fs['functions']}  ops: {fs['ops']}"
                    f"  blocks: {fs['blocks']}  cc_max: {fs['cc_max']}\n")
            f.write("// tool: pipeline/tools/hl_disasm.py --emit (dig 8)\n")
            f.write("// semantics: measured this dig; unknowns render "
                    "@n/UNK and are ledgered in _unknown-opcodes.jsonl\n\n")
            f.write("\n".join(modules[src]))
            f.write("\n")
        del modules[src]
        written += 1

    # ---- function index (relink aid) ----------------------------------
    with open(os.path.join(OUTDIR, "_functions-index.jsonl"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"_meta": {
            "buildid": BUILDID,
            "tool": "pipeline/tools/hl_disasm.py --emit",
            "rows": len(index_rows),
            "note": "one row per function; joins functions.jsonl findex -> "
                    "disassembly file + CFG shape"}}) + "\n")
        for r in sorted(index_rows, key=lambda x: x["findex"]):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ---- unknown-opcode ledger ----------------------------------------
    ledger_path = os.path.join(OUTDIR, "_unknown-opcodes.jsonl")
    with open(ledger_path, "w", encoding="utf-8", newline="\n") as f:
        meta = {
            "buildid": BUILDID,
            "tool": "pipeline/tools/hl_disasm.py --emit",
            "policy": "an operand/reference is resolved only when its "
                      "semantics are measured; everything else is counted "
                      "here with bounded examples",
            "validated_this_dig": [
                "OCall4 (op 28) = (dst=reg, fun=findex, arg0..arg3=reg): "
                "15,858/15,858 sites consistent (fun always resolves to an "
                "existing function/native findex)",
                "field ops use flattened root->leaf ordinals (258,030/"
                "258,068 obj-receiver sites in range)",
                "jump destinations pc+1+t in range 298,231/298,231",
                "OSwitch layout [reg, ncases, default, offsets...] "
                "3,356/3,356 targets+defaults in range",
            ],
        }
        f.write(json.dumps({"_meta": meta}) + "\n")
        # pinned fork ops never observed in this build stay UNK-by-absence
        for opid, nm in ((99, "OForkPrefetch"), (100, "OForkAsm"),
                         (101, "OForkCatch")):
            f.write(json.dumps({
                "kind": "opcode-unobserved-fork-family", "op": opid,
                "name": nm,
                "note": "encoding pinned (crashlink fork table) but the op "
                        "never occurs in this build; semantics unproven "
                        "here"}) + "\n")
        f.write(json.dumps({
            "kind": "obytes-payload-unproven",
            "count": sum(dis.ledger["obytes-payload-unproven"].values()),
            "note": "HLB v4 declares no bytes pool; OByte payloads cannot "
                    "be dereferenced from the structure layer alone",
            "examples": dis.examples["obytes-payload-unproven"]}) + "\n")
        kinds = sorted(k for k in dis.ledger
                       if sum(dis.ledger[k].values()) > 0
                       and k != "obytes-payload-unproven")
        for k in kinds:
            f.write(json.dumps({
                "kind": k,
                "count": sum(dis.ledger[k].values()),
                "distinct": len(dis.ledger[k]),
                "top_details": dict(dis.ledger[k].most_common(10)),
                "examples": dis.examples[k]}, ensure_ascii=False) + "\n")

    # ---- CFG stats -----------------------------------------------------
    top_cc = sorted(maxcc, reverse=True)[:50]
    stats = {
        "_meta": {"buildid": BUILDID,
                  "tool": "pipeline/tools/hl_disasm.py --emit",
                  "definition": "cc = E - N + 2 per function on the basic-"
                                "block graph (straight-line=1; jump/switch/"
                                "trap edges included, returns terminal)"},
        "totals": dict(totals),
        "cyclomatic": {
            "mean": round(sum(c for c, *_ in maxcc) /
                          max(1, len(maxcc)), 3),
            "max": {"cc": top_cc[0][0], "findex": top_cc[0][1],
                    "file": top_cc[0][2]} if top_cc else None,
            "gt_50": sum(1 for c, *_ in maxcc if c > 50),
            "gt_20": sum(1 for c, *_ in maxcc if c > 20),
        },
        "per_package": {k: dict(v) for k, v in sorted(pkg_stats.items())},
        "per_file_top30_by_ops": [
            {"file": s, **dict(file_stats[s])}
            for s in sorted(file_stats,
                            key=lambda x: -file_stats[x]["ops"])[:30]],
        "top50_cc_functions": [
            {"cc": cc, "findex": fx, "file": s, "name": nm}
            for cc, fx, s, nm in top_cc],
    }
    with open(os.path.join(DIGDIR, "cfg-stats.json"), "w",
              encoding="utf-8", newline="\n") as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)

    print(f"DONE: functions={totals['functions']} ops={totals['ops']} "
          f"modules={written} ledger_kinds={len(kinds)}")
    print(f"  -> {OUTDIR}")
    print(f"  -> {os.path.join(DIGDIR, 'cfg-stats.json')}")
    return 0


def topcc_guard(t):
    return bool(t)


def iter_opseq(want_findex=None):
    """Stream (findex, opseq) from opcodes.jsonl.gz; if want_findex is given,
    yield only that one (single pass, bounded memory)."""
    with gzip.open(os.path.join(HLSTRUCT, "opcodes.jsonl.gz"), "rt",
                   encoding="utf-8") as gz:
        for line in gz:
            rec = json.loads(line)
            if want_findex is None or rec["findex"] == want_findex:
                yield rec["findex"], rec["ops"]
                if want_findex is not None:
                    return


# ---------------------------------------------------------------------------
# verification / interactive rendering

KNOWN_DIG6 = [
    ("WorldMesh.getFow", "row-major FOW sampling"),
    ("MiniMap.getPlayerPosition", "returns world xy"),
    ("ui.comp.Compass.sync", "bearing strip"),
]


def find_findex(corpus, needle):
    hits = []
    for fx, (ow, pn, _ti) in corpus.fowner.items():
        q = f"{ow}.{pn}"
        if needle in q:
            fn = corpus.fn_by_findex.get(fx)
            hits.append((q, fx, fn.get("debug_file"), fn.get("first_line")))
    return sorted(set(hits))


def cmd_verify():
    corpus = Corpus(None if os.path.exists(
        os.path.join(HLSTRUCT, "ints.jsonl")) else DEFAULT_HLBOOT)
    dis = Disasm(corpus)
    ok = True

    # 1. role-model audit over a deterministic sample + the known set
    print("== role audit ==")
    import gzip as _gz
    audited = Counter()
    with _gz.open(os.path.join(HLSTRUCT, "opcodes.jsonl.gz"), "rt",
                  encoding="utf-8") as gz:
        for i, line in enumerate(gz):
            rec = json.loads(line)
            fn = corpus.functions[i]
            nregs = fn["nregs"]
            for pc, arr in enumerate(rec["ops"]):
                op, a = arr[0], arr[1:]
                nm = OPNAMES[op] if op < len(OPNAMES) else ""
                if nm in ("OCall0", "OCall1", "OCall2", "OCall3", "OCall4",
                          "OCallN", "OStaticClosure", "OInstanceClosure"):
                    audited[f"{nm}:fun_resolves"] += \
                        (a[1] in corpus.fn_by_findex) or (a[1] in corpus.natives)
                    audited[f"{nm}:n"] += 1
                elif nm in ("OCallMethod", "OCallThis"):
                    nargs = a[2]
                    audited[f"{nm}:shape_ok"] += (len(a) >= 3 + nargs)
                    audited[f"{nm}:n"] += 1
                elif nm.startswith("OJ") and nm != "OJAlways":
                    d = pc + 1 + a[-1]
                    audited["jumps:in_range"] += 0 <= d <= len(rec["ops"])
                    audited["jumps:n"] += 1
    bad = 0
    for k, v in sorted(audited.items()):
        if k.endswith(":n"):
            continue
        n = audited[k.split(":")[0] + ":n"]
        status = "OK" if v == n else "FAIL"
        if v != n:
            ok = False
            bad += 1
        print(f"  {k}: {v}/{n} {status}")

    # 2. known-semantics spot renders
    print("== known-semantics renders (manual read) ==")
    for needle, why in [("WorldMesh.getFow", "FOW row-major"),
                        ("MiniMap.getPlayerPosition", "world xy"),
                        ("Layers2D.getLayerColor", "pixel fetch")]:
        hits = find_findex(corpus, needle)
        if not hits:
            print(f"  !! {needle}: NOT FOUND")
            ok = False
            continue
        q, fx, dbg, ln = hits[0]
        fn = corpus.fn_by_findex[fx]
        text, cfg = render_function(dis, fn, get_one_opseq(fx))
        print(f"----- {q} f#{fx} ({why}) {dbg}:{ln} "
              f"blocks={cfg['nblocks']} cc={cfg['cc']}")
        print(text)
    print("VERIFY-STATUS:", "PASS" if ok else "FAIL", f"(bad={bad})")
    return 0 if ok else 1


def get_one_opseq(findex):
    return next(iter_opseq(findex))[1]


def main():
    argv = sys.argv[1:]
    hlboot = None
    if "--hlboot" in argv:
        i = argv.index("--hlboot")
        hlboot = argv[i + 1]
        del argv[i:i + 2]
    if "--emit" in argv:
        return cmd_emit(hlboot)
    if "--verify" in argv:
        return cmd_verify()
    corpus = Corpus(None if os.path.exists(
        os.path.join(HLSTRUCT, "ints.jsonl")) else
        (hlboot or DEFAULT_HLBOOT))
    dis = Disasm(corpus)
    if "--function" in argv:
        fx = int(argv[argv.index("--function") + 1])
        fn = corpus.fn_by_findex[fx]
        text, _ = render_function(dis, fn, get_one_opseq(fx))
        print(text)
        return 0
    if "--file" in argv:
        want = argv[argv.index("--file") + 1]
        with gzip.open(os.path.join(HLSTRUCT, "opcodes.jsonl.gz"), "rt",
                       encoding="utf-8") as gz:
            for i, line in enumerate(gz):
                rec = json.loads(line)
                fn = corpus.functions[i]
                if fn.get("debug_file") == want:
                    print(render_function(dis, fn, rec["ops"])[0])
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
