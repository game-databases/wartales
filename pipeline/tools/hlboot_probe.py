#!/usr/bin/env python3
"""hlboot_probe.py — Wartales HashLink bytecode (HLB v4 fork) reader/digger.

History: seeded R2 as a header/strings probe (docs/toolchain-validation.mdx
§2); extended same day into the full structural dig once the true layout was
pinned empirically (_dig_explore.py kept as the exploration log):

  HLB\x04 | flags | ints | floats | strings | debug-files block (hasdebug) |
  types | globals | natives | functions (+per-fn debug infos + assigns) |
  constants -> EOF

Canonical semantics: _refs/hl_code.c (= hashlink 1.13 src/code.c reader);
v4-era opcode table pinned at _refs/upstream/opcodes.h. Wartales ships a
FORK of HashLink: its runtime exports hlt_dynobj / hl_guid_str, matching the
_refs/hl.h enum family (HDYN=9..HGUID=23), and the bytecode carries type
kinds >= 24 plus possibly extra opcodes. Novel-kind payloads and fork-opcode
encodings are INFERRED by constraint search and PROVEN by round-trip: every
section consumes exactly its bytes and the whole walk ends at EOF with zero
slack — the same standard as wtpak's Sigma-sizes==span proof.

Usage:
  python hlboot_probe.py [hlboot.dat] [--emit] [--quiet]
--emit writes extracted/logic/hl-structure/{types,functions,globals,
natives,constants}.jsonl + strings.txt under the pack root.
Exit code 0 iff zero slack achieved.
"""
import struct
import sys
import os
import time
import json
import collections

DEFAULT_HLBOOT = "A:/SteamLibrary/steamapps/common/Wartales/hlboot.dat"

# Base type-kind map (hypothesis confirmed live at types-region start:
# first bytes 00 01 02 03 04 05 06 07 decode as HVOID..HBOOL in sequence).
KIND_NAMES = {
    0: "HVOID", 1: "HUI8", 2: "HUI16", 3: "HI32", 4: "HI64", 5: "HF32",
    6: "HF64", 7: "HBOOL", 8: "HBYTES", 9: "HDYN", 10: "HFUN", 11: "HOBJ",
    12: "HARRAY", 13: "HTYPE", 14: "HREF", 15: "HVIRTUAL", 16: "HDYNOBJ",
    17: "HABSTRACT", 18: "HENUM", 19: "HNULL", 20: "HMETHOD", 21: "HSTRUCT",
    22: "HPACKED", 23: "HGUID",
}
PAYLOAD_OF = {}
for _lay, _ks in [
    ("fun", (10, 20)), ("obj", (11, 21)), ("virt", (15,)), ("abs", (17,)),
    ("enum", (18,)), ("tref", (14, 19, 22)),
    ("none", (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 13, 16, 23)),
]:
    for _k in _ks:
        PAYLOAD_OF[_k] = _lay

CANDIDATE_LAYOUTS = ["tref", "none", "abs", "fun", "virt", "enum", "obj"]
CANDIDATE_OPENCODINGS = [2, 3, 1, 0, 4, "callN", 5, 6, "switch"]


class FormatError(Exception):
    pass


class Dig:
    def __init__(self, path):
        self.path = path
        self.data = open(path, "rb").read()
        self.N = len(self.data)
        self.pos = 0
        self.sections = []
        self.kind_layout = {}      # fork kind id -> layout name
        self.kind_first = {}       # fork kind id -> first type index
        self.op_layout = {}        # fork opcode id -> encoding key
        self.notes = []

    # ---------------- low-level ----------------
    def u8(self):
        v = self.data[self.pos]
        self.pos += 1
        return v

    def i32(self):
        v = struct.unpack_from("<i", self.data, self.pos)[0]
        self.pos += 4
        return v

    def idx(self):
        d = self.data
        p = self.pos
        b = d[p]
        if b & 0x80 == 0:
            self.pos = p + 1
            return b & 0x7F
        if b & 0x40 == 0:
            c = d[p + 1]
            self.pos = p + 2
            v = ((b & 31) << 8) | c
            return -v if b & 0x20 else v
        c = d[p + 1]
        e = d[p + 3]
        v = ((b & 31) << 24) | (c << 16) | (d[p + 2] << 8) | e
        self.pos = p + 4
        return -v if b & 0x20 else v

    def uindex_at(self, p):
        d = self.data
        b = d[p]
        if b & 0x80 == 0:
            return b & 0x7F, p + 1
        if b & 0x40 == 0:
            v = ((b & 31) << 8) | d[p + 1]
            return (-v if b & 0x20 else v), p + 2
        v = ((b & 31) << 24) | (d[p + 1] << 16) | (d[p + 2] << 8) | d[p + 3]
        return (-v if b & 0x20 else v), p + 4

    def need(self, n):
        if self.pos + n > self.N:
            raise FormatError(f"EOF overrun at {self.pos:#x} (+{n})")

    def mark(self, name, start, end=None, extra=None):
        self.sections.append(
            {"name": name, "start": start, "end": self.pos if end is None
             else end, "extra": extra or {}})

    # ---------------- header + pools ----------------
    def read_header(self):
        if self.data[:3] != b"HLB":
            raise FormatError("bad magic")
        self.version = self.data[3]
        self.pos = 4
        self.flags = self.idx()
        self.nints = self.idx()
        self.nfloats = self.idx()
        self.nstrings = self.idx()
        self.nbytes = self.idx() if self.version >= 5 else 0
        self.ntypes = self.idx()
        self.nglobals = self.idx()
        self.nnatives = self.idx()
        self.nfunctions = self.idx()
        self.nconstants = self.idx() if self.version >= 4 else 0
        self.entrypoint = self.idx()
        self.hasdebug = bool(self.flags & 1)

    def read_pools_strings(self):
        self.need(4 * self.nints + 8 * self.nfloats + 4)
        s = self.pos
        self.pos += 4 * self.nints
        self.mark("ints", s)
        s = self.pos
        self.pos += 8 * self.nfloats
        self.mark("floats", s)
        start = self.pos
        ssize = self.i32()
        sblob = self.pos
        self.need(ssize)
        blob = self.data[sblob:sblob + ssize]
        p = sblob + ssize
        out = []
        q = 0
        for i in range(self.nstrings):
            sz, p = self.uindex_at(p)
            out.append(blob[q:q + sz])
            q += sz
            if q >= ssize or blob[q] != 0:
                raise FormatError(
                    f"strings[{i}] NUL/table mismatch ({q}/{ssize})")
            q += 1
        if q != ssize:
            raise FormatError("strings blob slack")
        self.pos = p
        self.strings = [s.decode("utf-8", "replace") for s in out]
        self.strings_raw = out
        self.mark("strings", start, extra={"declared_size": ssize})

    def read_debug_files(self):
        start = self.pos
        ndf = self.idx()
        size = self.i32()
        dblob = self.pos
        self.need(size)
        blob = self.data[dblob:dblob + size]
        p = dblob + size
        q = 0
        dfs = []
        for i in range(ndf):
            sz, p = self.uindex_at(p)
            dfs.append(blob[q:q + sz].decode("utf-8", "replace"))
            q += sz
            if q >= size or blob[q] != 0:
                raise FormatError(f"debugfiles[{i}] NUL mismatch")
            q += 1
        if q != size:
            raise FormatError("debugfiles blob slack")
        self.pos = p
        self.debugfiles = dfs
        self.ndebugfiles = ndf
        self.mark("debugfiles", start, extra={"count": ndf})

    # ---------------- types ----------------
    def read_type_payload(self, lay, ti):
        """Read one type payload; returns summary dict (or None)."""
        d = self.data
        ntypes, nstrs = self.ntypes, self.nstrings
        nglob = self.nglobals
        nfn = self.nfunctions + self.nnatives
        P = self.pos

        def tref(w):
            v = self.idx()
            if not (0 <= v < ntypes):
                raise FormatError(f"type#{ti} {w}: tref {v} oob @{P:#x}")
            return v

        def sref(w):
            v = self.idx()
            if not (0 <= v < nstrs):
                raise FormatError(f"type#{ti} {w}: sidx {v} oob @{P:#x}")
            return v

        def gref(w):
            v = self.idx()
            if not (0 <= v <= nglob):
                raise FormatError(f"type#{ti} {w}: global {v} oob")
            return v

        if lay == "none":
            return None
        if lay == "tref":
            return tref("tparam")
        if lay == "abs":
            return {"name": sref("abs_name")}
        if lay == "name_global":
            return {"name": sref("name"), "global": gref("global")}
        if lay == "fun":
            na = d[self.pos]
            self.pos += 1
            args = [tref(f"arg{i}") for i in range(na)]
            ret = tref("ret")
            return {"nargs": na, "args": args, "ret": ret}
        if lay == "virt":
            nf = self.idx()
            if not (0 <= nf <= 100000):
                raise FormatError(f"type#{ti}: virt nfields {nf}")
            fs = [(sref("vf_name"), tref("vf_t")) for _ in range(nf)]
            return {"fields": fs}
        if lay == "enum":
            name = sref("ename")
            glob = gref("eglobal")
            nc = self.idx()
            if not (0 <= nc <= 100000):
                raise FormatError(f"type#{ti}: enum constructs {nc}")
            cons = []
            for _ in range(nc):
                cn = sref("c_name")
                np_ = self.idx()
                if not (0 <= np_ <= 100000):
                    raise FormatError(f"type#{ti}: construct params {np_}")
                ps = [tref(f"c_param{i}") for i in range(np_)]
                cons.append((cn, ps))
            return {"name": name, "global": glob, "constructs": cons}
        if lay == "obj":
            name = sref("oname")
            sup = self.idx()
            if sup != -1 and not (0 <= sup < ntypes):
                raise FormatError(f"type#{ti}: super {sup} oob")
            glob = gref("oglobal")
            nf = self.idx()
            np_ = self.idx()
            nb = self.idx()
            if not (0 <= nf <= 100000 and 0 <= np_ <= 100000
                    and 0 <= nb <= 100000):
                raise FormatError(f"type#{ti}: obj counts {nf}/{np_}/{nb}")
            fs = [(sref("f_name"), tref("f_t")) for _ in range(nf)]
            ps = []
            for _ in range(np_):
                pn = sref("p_name")
                pf = self.idx()
                pp = self.idx()
                if not (0 <= pf < nfn):
                    raise FormatError(f"type#{ti}: proto findex {pf} oob")
                ps.append((pn, pf, pp))
            bs = [(self.idx(), self.idx()) for _ in range(nb)]
            return {"name": name, "super": sup, "global": glob,
                    "fields": fs, "protos": ps, "bindings": bs}
        raise FormatError(f"unknown layout {lay}")

    def walk_types(self, start, limit=None):
        """Walk types from `start` using current kind mapping.
        Returns (end_pos, records) on success;
        raises BranchNeeded(kind, ti) for unmapped fork kinds."""
        self.pos = start
        recs_kind = []
        recs_summ = []
        recs_off = []
        n = self.ntypes if limit is None else min(limit, self.ntypes)
        get = PAYLOAD_OF.get
        assign = self.kind_layout
        data = self.data
        for ti in range(n):
            off = self.pos
            k = data[off]
            self.pos = off + 1
            lay = get(k)
            if lay is None:
                lay = assign.get(k)
                if lay is None:
                    self.kind_first.setdefault(k, ti)
                    raise BranchNeeded(k, ti)
            summ = self.read_type_payload(lay, ti)
            recs_kind.append(k)
            recs_summ.append((lay, summ))
            recs_off.append(off)
        return self.pos, (recs_kind, recs_summ, recs_off)

    @staticmethod
    def _cands_for(k):
        base = PAYLOAD_OF.get(k)
        if base is None:
            return list(CANDIDATE_LAYOUTS)
        return [base] + [c for c in CANDIDATE_LAYOUTS if c != base]

    def solve_types(self, start):
        """DFS over type-kind layout assignments until the region walks.
        Fork kinds branch over CANDIDATE_LAYOUTS; a base-mapped kind only
        re-branches if its canonical layout proves wrong."""
        while True:
            try:
                end, recs = self.walk_types(start)
                self.types_end = end
                self.type_recs = recs
                self.mark("types", start, extra={
                    "novel_kinds": {k: self.kind_layout[k]
                                    for k in sorted(self.kind_layout)},
                    "kind_first_seen": {k: self.kind_first[k]
                                        for k in sorted(self.kind_first)}})
                return
            except BranchNeeded as br:
                k = br.args[0]
                st = getattr(self, "_tstack", [])
                placed = False
                while st:
                    k2, ci = st[-1]
                    cc = self._cands_for(k2)
                    if ci + 1 < len(cc):
                        st[-1] = (k2, ci + 1)
                        self.kind_layout[k2] = cc[ci + 1]
                        placed = True
                        break
                    del self.kind_layout[k2]
                    st.pop()
                if not placed:
                    st.append((k, 0))
                    self.kind_layout[k] = self._cands_for(k)[0]
                self._tstack = st
            except FormatError:
                # hard failure -> backtrack last decision, else rethrow
                st = getattr(self, "_tstack", [])
                while st:
                    k2, ci = st[-1]
                    cc = self._cands_for(k2)
                    if ci + 1 < len(cc):
                        st[-1] = (k2, ci + 1)
                        self.kind_layout[k2] = cc[ci + 1]
                        break
                    del self.kind_layout[k2]
                    st.pop()
                else:
                    raise
                self._tstack = st

    # ---------------- globals / natives ----------------
    def read_globals(self):
        start = self.pos
        gs = []
        for i in range(self.nglobals):
            v = self.idx()
            if not (0 <= v < self.ntypes):
                raise FormatError(f"globals[{i}] tref {v} oob")
            gs.append(v)
        self.globals = gs
        self.mark("globals", start)

    def read_natives(self):
        start = self.pos
        nv = []
        nfn = self.nfunctions + self.nnatives
        ns = self.nstrings
        for i in range(self.nnatives):
            lib = self.idx()
            name = self.idx()
            t = self.idx()
            fx = self.idx()
            if not (0 <= lib < ns and 0 <= name < ns
                    and 0 <= t < self.ntypes and 0 <= fx < nfn):
                raise FormatError(
                    f"native#{i} ({lib},{name},{t},{fx}) oob @{start:#x}")
            nv.append((lib, name, t, fx))
        self.natives = nv
        self.mark("natives", start)

    # ---------------- functions ----------------
    def load_opcode_table(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "_refs", "upstream", "opcodes.h")
        names, nargs = [], []
        for line in open(path, "r", encoding="utf-8"):
            s = line.strip()
            if s.startswith("OP("):
                inner = s[3:s.rindex(")")]
                nm, na = [x.strip() for x in inner.split(",")]
                if nm != "OLast":
                    names.append(nm)
                    nargs.append(int(na))
        # fork opcodes appended after upstream OLast (99..101), semantics per
        # crashlink's table (N3rdL0rd/crashlink, Dead Cells / Shiro fork
        # family); all plain INDEX operands:
        names += ["OForkPrefetch", "OForkAsm", "OForkCatch"]
        nargs += [3, 3, 1]
        self.op_names = names
        self.op_nargs = nargs
        self.OLast = 99          # first fork opcode id

    def _read_debug_infos(self, nops):
        curfile, curline = -1, 0
        fs, ls = [], []
        i = 0
        u8 = self.u8
        ndf = self.ndebugfiles
        while i < nops:
            c = u8()
            if c & 1:
                curfile = ((c >> 1) << 8) | u8()
                if curfile >= ndf:
                    raise FormatError(f"debug file {curfile} oob")
            elif c & 2:
                count = (c >> 2) & 15
                if i + count > nops:
                    raise FormatError("debug run outside range")
                if count:
                    fs.extend([curfile] * count)
                    ls.extend([curline] * count)
                    i += count
                curline += c >> 6
            elif c & 4:
                curline += c >> 3
                fs.append(curfile)
                ls.append(curline)
                i += 1
            else:
                b2 = u8()
                b3 = u8()
                curline = (c >> 3) | (b2 << 5) | (b3 << 13)
                fs.append(curfile)
                ls.append(curline)
                i += 1
        return fs, ls

    def _read_operands(self, enc):
        if enc == "callN":
            p1 = self.idx()
            p2 = self.idx()
            n = self.u8()
            extra = [self.idx() for _ in range(n)]
            return (p1, p2, n, extra)
        if enc == "switch":
            p1 = self.idx()
            p2 = self.idx()
            if p1 < 0 or p2 < 0 or p2 > 1_000_000:
                raise FormatError(f"switch shape {p1},{p2}")
            extra = [self.idx() for _ in range(p2)]
            p3 = self.idx()
            if p3 < 0:
                raise FormatError("switch default negative")
            return (p1, p2, p3, extra)
        if enc <= 3:
            return tuple(self.idx() for _ in range(enc))
        # canonical case 4 / generic >4: p1,p2,p3 + (enc-3) extra indexes
        p1 = self.idx()
        p2 = self.idx()
        p3 = self.idx()
        extra = [self.idx() for _ in range(enc - 3)]
        return (p1, p2, p3, extra)

    def walk_functions(self, start, limit=None):
        """Returns None on success; raises BranchNeededOp(op, fi, oi);
        raises FormatError on hard failure."""
        self.pos = start
        idx = self.idx
        data = self.data
        ntypes = self.ntypes
        nfn_total = self.nfunctions + self.nnatives
        OLast = self.OLast
        op_nargs = self.op_nargs
        op_names = self.op_names
        op_layout = self.op_layout
        fns = []
        prev_fx = -1
        n = self.nfunctions if limit is None else min(limit,
                                                      self.nfunctions)
        for fi in range(n):
            t = idx()
            fx = idx()
            nregs = idx()
            nops = idx()
            if not (0 <= t < ntypes):
                raise FormatError(f"fn#{fi} type ref {t} oob @{self.pos:#x}")
            # NB: storage order need not be findex order (canonical reader
            # imposes none); bounds + end-of-walk uniqueness carry the proof
            if not (0 <= fx < nfn_total):
                raise FormatError(
                    f"fn#{fi} findex {fx} oob @{self.pos:#x}")
            prev_fx = max(prev_fx, fx)
            if not (0 <= nregs <= 65535 and 0 <= nops <= 10_000_000):
                raise FormatError(f"fn#{fi} shape regs={nregs} ops={nops}")
            regs = []
            for _ in range(nregs):
                rt = idx()
                if not (0 <= rt < ntypes):
                    raise FormatError(f"fn#{fi} reg {rt} oob")
                regs.append(rt)
            opseq = []
            for oi in range(nops):
                op = data[self.pos]
                self.pos += 1
                if op < OLast:
                    na = op_nargs[op]
                    enc = ("switch" if op_names[op] == "OSwitch"
                           else "callN") if na == -1 else na
                elif op < len(op_nargs):
                    # fork opcode with pinned encoding (Prefetch/Asm/Catch)
                    enc = op_nargs[op]
                else:
                    enc = op_layout.get(op)
                    if enc is None:
                        raise BranchNeededOp(op, fi, oi)
                operands = self._read_operands(enc)
                opseq.append((op, operands))
            dbg = None
            assigns = None
            if self.hasdebug:
                df, dl = self._read_debug_infos(nops)
                nas = idx()
                if not (0 <= nas <= 1_000_000):
                    raise FormatError(f"fn#{fi} nassigns {nas}")
                assigns = []
                for _ in range(nas):
                    # canonical reads UINDEX + INDEX fully unchecked
                    # (debugger variable-tracking pairs; signed values legal)
                    assigns.append((idx(), idx()))
                dbg = (df, dl)
            fns.append({"findex": fx, "type": t, "regs": regs,
                        "ops": opseq, "debug": dbg, "assigns": assigns})
        fidxs = [f["findex"] for f in fns]
        if len(set(fidxs)) != len(fidxs):
            dup = [x for x, c in collections.Counter(fidxs).items()
                   if c > 1][:5]
            raise FormatError(f"duplicate findex {dup}")
        self.functions = fns

    def solve_opcodes(self, start):
        """Resolve fork-opcode encodings. Cheap prefix trials first, then a
        confirming full walk; backtrack on any failure."""
        PREFIX = 1500
        stack = []
        while True:
            # phase 1: prefix trial to place new decisions cheaply
            try:
                self.walk_functions(start, limit=PREFIX)
            except BranchNeededOp as bo:
                op = bo.args[0]
                placed = False
                while stack:
                    o2, ci = stack[-1]
                    if ci + 1 < len(CANDIDATE_OPENCODINGS):
                        stack[-1] = (o2, ci + 1)
                        self.op_layout[o2] = CANDIDATE_OPENCODINGS[ci + 1]
                        placed = True
                        break
                    del self.op_layout[o2]
                    stack.pop()
                if not placed:
                    stack.append((op, 0))
                    self.op_layout[op] = CANDIDATE_OPENCODINGS[0]
                continue
            except FormatError:
                while stack:
                    o2, ci = stack[-1]
                    if ci + 1 < len(CANDIDATE_OPENCODINGS):
                        stack[-1] = (o2, ci + 1)
                        self.op_layout[o2] = CANDIDATE_OPENCODINGS[ci + 1]
                        break
                    del self.op_layout[o2]
                    stack.pop()
                else:
                    raise
                continue
            # phase 2: full confirming walk
            try:
                self.walk_functions(start)
                self.mark("functions", start, extra={
                    "fork_opcodes": dict(sorted(
                        (k, self.op_layout[k])
                        for k in self.op_layout))})
                return
            except BranchNeededOp as bo:
                op = bo.args[0]
                stack.append((op, 0))
                self.op_layout[op] = CANDIDATE_OPENCODINGS[0]
            except FormatError:
                while stack:
                    o2, ci = stack[-1]
                    if ci + 1 < len(CANDIDATE_OPENCODINGS):
                        stack[-1] = (o2, ci + 1)
                        self.op_layout[o2] = \
                            CANDIDATE_OPENCODINGS[ci + 1]
                        break
                    del self.op_layout[o2]
                    stack.pop()
                else:
                    raise

    # ---------------- constants ----------------
    def read_constants(self):
        start = self.pos
        cs = []
        for i in range(self.nconstants):
            g = self.idx()
            nf = self.idx()
            if not (0 <= g < self.nglobals) or not (0 <= nf <= 65536):
                raise FormatError(f"constant#{i} g={g} nf={nf}")
            fields = [self.idx() for _ in range(nf)]
            cs.append((g, fields))
        self.constants = cs
        self.mark("constants", start)


class BranchNeeded(Exception):
    pass


class BranchNeededOp(Exception):
    pass


# ---------------- driver ----------------
def dig_file(path, say, stage="full"):
    """stage: header | types | full  (staged runs skip later sections and
    return slack=None)."""
    dig = Dig(path)
    t0 = time.time()
    dig.read_header()
    say(f"file={path} ({dig.N:,} B)")
    say(f"version={dig.version} flags={dig.flags:#x} "
        f"hasdebug={dig.hasdebug}")
    say(f"ints={dig.nints:,} floats={dig.nfloats:,} "
        f"strings={dig.nstrings:,} types={dig.ntypes:,} "
        f"globals={dig.nglobals:,} natives={dig.nnatives:,} "
        f"functions={dig.nfunctions:,} constants={dig.nconstants:,} "
        f"entrypoint=f#{dig.entrypoint:,}")
    dig.read_pools_strings()
    if dig.hasdebug:
        dig.read_debug_files()
        say(f"strings strict-OK ({len(dig.strings):,}); "
            f"debug files strict-OK ({dig.ndebugfiles:,})")

    types_start = dig.pos
    dig.solve_types(types_start)
    rk, rs, ro = dig.type_recs
    hist = collections.Counter(lay for lay, _ in rs)
    say(f"TYPES COMPLETE: {dig.ntypes:,} types "
        f"{types_start:#x}->{dig.types_end:#x} "
        f"({dig.types_end - types_start:,} B)")
    say(f"  layout histogram: {dict(sorted(hist.items()))}")
    if dig.kind_layout:
        say(f"  NOVEL kinds solved: "
            f"{dict(sorted(dig.kind_layout.items()))}")
        say(f"  first-seen at type#: "
            f"{dict(sorted(dig.kind_first.items()))}")

    dig.read_globals()
    say(f"GLOBALS COMPLETE: {len(dig.globals):,} refs "
        f"(end {dig.pos:#x})")
    dig.read_natives()
    l0, n0, t0_, f0 = dig.natives[0]
    say(f"NATIVES COMPLETE: {len(dig.natives):,} "
        f"(first: {dig.strings[l0]!r}.{dig.strings[n0]!r})")
    if stage != "full":
        return dig, None

    fn_start = dig.pos
    dig.load_opcode_table()
    say(f"opcode table: OLast={dig.OLast} (upstream opcodes.h)")
    dig.solve_opcodes(fn_start)
    total_ops = sum(len(f["ops"]) for f in dig.functions)
    say(f"FUNCTIONS COMPLETE: {len(dig.functions):,} functions, "
        f"{total_ops:,} opcodes, table {fn_start:#x}->{dig.pos:#x} "
        f"({dig.pos - fn_start:,} B)")
    if dig.op_layout:
        say(f"  FORK opcodes solved: {dict(sorted(dig.op_layout.items()))}")

    dig.read_constants()
    say(f"CONSTANTS COMPLETE: {len(dig.constants):,} (end {dig.pos:#x})")
    slack = dig.N - dig.pos
    verdict = "PASS" if slack == 0 else "FAIL"
    say(f"ZERO-SLACK: consumed {dig.pos:,}/{dig.N:,} B -> slack={slack} B "
        f"[{verdict}]  ({time.time() - t0:.1f}s)")
    ep = dig.entrypoint
    fxset = {f["findex"] for f in dig.functions}
    nfx = {n[3] for n in dig.natives}
    maxfx = max(fxset)
    if ep in fxset:
        where = "exact function match"
    elif ep in nfx:
        where = "native findex"
    else:
        where = ("in-range, unused slot" if ep < dig.nfunctions
                 else f"above max function findex ({maxfx})")
    say(f"entrypoint f#{ep:,}: {where}; function findeXes span "
        f"0..{maxfx:,} distinct={len(fxset):,}")
    return dig, slack


# ---------------- emission ----------------
def _sanitize(s):
    return (s.replace("\\", "\\\\").replace("\t", "\\t")
             .replace("\n", "\\n").replace("\r", "\\r"))


def type_display(dig, tidx, seen=None):
    """Human-readable signature for a type index (best effort)."""
    S = dig.strings
    rk, rs, _ = dig.type_recs
    k = rk[tidx]
    lay, summ = rs[tidx]
    KN = KIND_NAMES
    if lay == "obj":
        return S[summ["name"]]
    if lay == "enum":
        return S[summ["name"]]
    if lay == "abs":
        return S[summ["name"]]
    if lay == "fun":
        args = ",".join(type_display(dig, a) for a in summ["args"])
        return f"({args})->{type_display(dig, summ['ret'])}"
    if lay == "tref":
        return f"?{type_display(dig, summ)}"
    if lay == "virt":
        return "virtual{}"
    base = {0: "void", 1: "u8", 2: "u16", 3: "i32", 4: "i64", 5: "f32",
            6: "f64", 7: "bool", 8: "bytes", 9: "dyn", 12: "array",
            13: "type", 16: "dynobj", 23: "guid"}.get(k)
    return base or KN.get(k, f"kind{k}")


def emit_all(dig):
    outdir = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "extracted", "logic", "hl-structure"))
    os.makedirs(outdir, exist_ok=True)
    import gzip
    S = dig.strings
    rk, rs, ro = dig.type_recs

    # strings.txt — full registry with indices
    with open(os.path.join(outdir, "strings.txt"), "w",
              encoding="utf-8", newline="\n") as f:
        for i, s in enumerate(S):
            f.write(f"{i}\t{_sanitize(s)}\n")

    # types.jsonl — kind/name/size/payload summary per type
    with open(os.path.join(outdir, "types.jsonl"), "w",
              encoding="utf-8", newline="\n") as f:
        for i in range(dig.ntypes):
            k = rk[i]
            lay, summ = rs[i]
            size = (ro[i + 1] - ro[i]) if i + 1 < dig.ntypes \
                else (dig.types_end - ro[i])
            rec = {"i": i, "kind": k,
                   "kind_name": KIND_NAMES.get(k, f"FORK_{k}"),
                   "layout": lay, "size_bytes": size}
            if summ:
                if lay == "obj":
                    rec.update({
                        "name": S[summ["name"]],
                        "super": summ["super"],
                        "global": summ["global"],
                        "nfields": len(summ["fields"]),
                        "fields": [[S[n], t] for n, t in summ["fields"]],
                        "protos": [[S[n], fx, px]
                                   for n, fx, px in summ["protos"]],
                        "bindings": summ["bindings"]})
                elif lay == "enum":
                    rec.update({
                        "name": S[summ["name"]],
                        "global": summ["global"],
                        "constructs": [[S[n], ps] for n, ps
                                       in summ["constructs"]]})
                elif lay == "abs":
                    rec["name"] = S[summ["name"]]
                elif lay == "fun":
                    rec.update({"nargs": summ["nargs"],
                                "args": summ["args"], "ret": summ["ret"],
                                "sig": type_display(dig, i)})
                elif lay == "virt":
                    rec.update({"nfields": len(summ["fields"]),
                                "fields": [[S[n], t]
                                           for n, t in summ["fields"]]})
                elif lay == "tref":
                    rec["tparam"] = summ
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # globals.jsonl
    with open(os.path.join(outdir, "globals.jsonl"), "w",
              encoding="utf-8", newline="\n") as f:
        for i, t in enumerate(dig.globals):
            f.write(json.dumps({"i": i, "type": t,
                                "type_name": type_display(dig, t)},
                               ensure_ascii=False) + "\n")

    # natives.jsonl
    with open(os.path.join(outdir, "natives.jsonl"), "w",
              encoding="utf-8", newline="\n") as f:
        for lib, name, t, fx in dig.natives:
            f.write(json.dumps({"lib": S[lib], "name": S[name], "type": t,
                                "findex": fx,
                                "sig": type_display(dig, t)},
                               ensure_ascii=False) + "\n")

    # functions.jsonl — structure + debug resolution (ops -> opcodes.jsonl.gz)
    with open(os.path.join(outdir, "functions.jsonl"), "w",
              encoding="utf-8", newline="\n") as f:
        for fn in dig.functions:
            rec = {"findex": fn["findex"], "type": fn["type"],
                   "sig": type_display(dig, fn["type"]),
                   "nregs": len(fn["regs"]), "regs": fn["regs"],
                   "nops": len(fn["ops"])}
            if fn["debug"]:
                df, dl = fn["debug"]
                if df and df[0] >= 0:
                    rec["debug_file"] = dig.debugfiles[df[0]]
                    rec["first_line"] = dl[0]
                files = sorted({x for x in df if x >= 0})
                rec["debug_files"] = [dig.debugfiles[x] for x in files]
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # opcodes.jsonl.gz — the complete opcode stream per function (raw layer)
    names = dig.op_names
    with gzip.open(os.path.join(outdir, "opcodes.jsonl.gz"), "wt",
                   encoding="utf-8", newline="\n", compresslevel=6) as f:
        for fn in dig.functions:
            ops = []
            for op, operands in fn["ops"]:
                if len(operands) == 4 and isinstance(operands[3], list):
                    ops.append([op, operands[0], operands[1],
                                operands[2]] + operands[3])
                else:
                    ops.append([op] + list(operands))
            f.write(json.dumps({"findex": fn["findex"], "ops": ops},
                               separators=(",", ":")) + "\n")

    # constants.jsonl
    with open(os.path.join(outdir, "constants.jsonl"), "w",
              encoding="utf-8", newline="\n") as f:
        for g, fields in dig.constants:
            f.write(json.dumps({"global": g,
                                "global_type": type_display(dig,
                                                            dig.globals[g]),
                                "nfields": len(fields),
                                "fields": fields},
                               ensure_ascii=False) + "\n")
    print(f"emitted -> {outdir}")
    return outdir


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    quiet = "--quiet" in sys.argv
    stage = "full"
    for a in sys.argv[1:]:
        if a.startswith("--stage="):
            stage = a.split("=", 1)[1]
    path = args[0] if args else DEFAULT_HLBOOT

    lines = []

    def say(*a):
        s = " ".join(str(x) for x in a)
        lines.append(s)
        if not quiet:
            print(s)

    dig, slack = dig_file(path, say, stage=stage)
    logdir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "_verify")
    os.makedirs(logdir, exist_ok=True)
    with open(os.path.join(logdir, "hlboot-dig-log.txt"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    if "--emit" in sys.argv and slack == 0:
        emit_all(dig)
    return 0 if slack is None or slack == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
