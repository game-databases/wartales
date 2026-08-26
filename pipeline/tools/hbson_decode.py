"""hbson_decode.py — strict HBSON (Heaps binary object notation) decoder for Wartales.

Clean-room reader for the `HBSON\0` container shipped inside res.pak /
content.pak / assets.pak (`.prefab` and `.l3d` payloads, routed by magic —
extensions lie). Grammar reversed in docs/hbson-format.mdx from three
oracles: the byte corpus itself, the CastleDB hidden sub-sheet schemas of
data.cdb, and the hxd.fmt.hbson.Reader/Writer functions of hlboot.dat
(f#40899 / f#40900 / f#47570, disassembled via the hl-structure datasets).

Zero-slack standard (wtpak/hlboot precedent): every byte accounted for;
strict EOF landing; loud failure on any unaccounted pattern.

Usage:
  python hbson_decode.py <file>            -> JSON on stdout
  python hbson_decode.py <dir> --out D     -> mirror tree of .json under D
           [--stats F]      aggregate decode report (JSON)
           [--limit N]      cap files decoded per run (dirs only)
           [--no-strict]    collect errors instead of failing the run
           [--quiet]        suppress per-file progress

Python 3.14, stdlib only.
"""
from __future__ import annotations

import argparse
import io
import json
import struct
import sys
from pathlib import Path

MAGIC = b"HBSON\x00"

TAG_INT0 = 0x00          # constant integer 0
TAG_U8 = 0x01
TAG_I32 = 0x02
TAG_F64 = 0x03
TAG_TRUE = 0x04
TAG_FALSE = 0x05
TAG_NULL = 0x06
TAG_OBJ_EMPTY = 0x07
TAG_OBJ_U8 = 0x08
TAG_OBJ_I32 = 0x09
TAG_STRING = 0x0A
TAG_ARR_EMPTY = 0x0B
TAG_ARR_U8 = 0x0C
TAG_ARR_I32 = 0x0D

STR_FLAG_BITS = 30       # top two bits of the string word carry the form
STR_MASK_LEN = 0x3FFFFFFF


class HbsonError(ValueError):
    """Any violation of the grammar; carries file path + offset context."""


class Decoder:
    """Streaming decoder over one blob.

    decode() returns the plain Python value. The instance keeps counters
    consumed by --stats and a form trace usable for byte-exact re-encoding
    (see reencode()).
    """

    def __init__(self, data: bytes, name: str = "<blob>"):
        if not data.startswith(MAGIC):
            raise HbsonError(f"{name}: bad magic {data[:6]!r}")
        self.b = data
        self.name = name
        self.i = len(MAGIC)
        self.n = len(data)
        # string table: bit-30-form strings push here in encounter order;
        # backrefs (form 0) index into it (Reader.readString semantics).
        self.strtbl: list[str] = []
        self.stats = {
            "tags": {},
            "strings": {"inline_ascii": 0, "inline_utf8": 0, "backrefs": 0},
            "max_depth": 0,
        }

    # -- primitive reads ---------------------------------------------------

    def _need(self, k: int, what: str) -> None:
        if self.i + k > self.n:
            raise HbsonError(
                f"{self.name}: truncated {what} at offset {self.i} "
                f"(need {k} B, {self.n - self.i} B left)")

    def _byte(self) -> int:
        self._need(1, "tag/payload byte")
        v = self.b[self.i]
        self.i += 1
        return v

    def _u8(self) -> int:
        return self._byte()

    def _i32(self) -> int:
        self._need(4, "i32")
        v = struct.unpack_from("<i", self.b, self.i)[0]
        self.i += 4
        return v

    def _f64(self) -> float:
        self._need(8, "f64")
        v = struct.unpack_from("<d", self.b, self.i)[0]
        self.i += 8
        return v

    def _count(self, tag: int) -> int:
        n = self._u8() if tag == TAG_OBJ_U8 or tag == TAG_ARR_U8 else self._i32()
        if n < 0:
            raise HbsonError(f"{self.name}: negative count {n} at offset {self.i - 4}")
        return n

    def _string_word(self) -> tuple[int, int]:
        w = self._i32()
        return (w >> STR_FLAG_BITS) & 3, w & STR_MASK_LEN

    def _string(self) -> str:
        form, ln = self._string_word()
        if form == 0:
            # back-reference into the running table
            if ln >= len(self.strtbl):
                raise HbsonError(
                    f"{self.name}: string backref {ln} out of range "
                    f"(table has {len(self.strtbl)}) at offset {self.i}")
            self.stats["strings"]["backrefs"] += 1
            return self.strtbl[ln]
        self._need(ln, "string payload")
        raw = self.b[self.i:self.i + ln]
        self.i += ln
        try:
            s = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            raise HbsonError(
                f"{self.name}: invalid UTF-8 in {ln}-byte string at "
                f"offset {self.i - ln}: {e}") from e
        if form == 1:
            self.strtbl.append(s)
            self.stats["strings"]["inline_ascii"] += 1
        else:
            self.stats["strings"]["inline_utf8"] += 1
        return s

    # -- recursive descent -------------------------------------------------

    def value(self, depth: int = 0) -> object:
        st = self.stats["tags"]
        tag = self._byte()
        st[tag] = st.get(tag, 0) + 1
        if depth > self.stats["max_depth"]:
            self.stats["max_depth"] = depth
        if tag == TAG_INT0:
            return 0
        if tag == TAG_U8:
            return self._u8()
        if tag == TAG_I32:
            return self._i32()
        if tag == TAG_F64:
            return self._f64()
        if tag == TAG_TRUE:
            return True
        if tag == TAG_FALSE:
            return False
        if tag == TAG_NULL:
            return None
        if tag == TAG_OBJ_EMPTY:
            return {}
        if tag in (TAG_OBJ_U8, TAG_OBJ_I32):
            n = self._count(tag)
            o: dict = {}
            for _ in range(n):
                k = self._string()
                o[k] = self.value(depth + 1)   # last field wins (setField order)
            return o
        if tag == TAG_STRING:
            return self._string()
        if tag == TAG_ARR_EMPTY:
            return []
        if tag in (TAG_ARR_U8, TAG_ARR_I32):
            n = self._count(tag)
            return [self.value(depth + 1) for _ in range(n)]
        raise HbsonError(f"{self.name}: unknown tag 0x{tag:02x} at offset {self.i - 1}")

    def decode(self) -> object:
        v = self.value()
        if self.i != self.n:
            raise HbsonError(
                f"{self.name}: trailing slack — {self.n - self.i} unconsumed "
                f"bytes after value end at offset {self.i}")
        return v


# ---------------------------------------------------------------------------
# Byte-exact re-encoder (proof side). Form choices are replayed from the
# original via a parallel form trace; canonical forms follow Writer.writeRec.
# ---------------------------------------------------------------------------

def encode_canonical(v, forms: dict | None = None, key: str = "$") -> bytes:
    """Re-encode a decoded value.

    With `forms` (the map recorded by decode_with_forms) this replays the
    original's exact tag choices and must reproduce the input byte-for-byte.
    Without it, canonical Writer.writeRec rules are applied (int: 0 / u8 / i32,
    containers: empty / u8 / i32, strings always bit-31 UTF-8 form).
    """
    out = bytearray(MAGIC)
    _enc_value(out, v, forms, key)
    return bytes(out)


def _enc_value(out: bytearray, v, forms, key) -> None:
    if isinstance(v, bool):                      # before int check!
        out.append(forms.get(key, TAG_TRUE if v else TAG_FALSE))
    elif v is None:
        out.append(forms.get(key, TAG_NULL))
    elif isinstance(v, int):
        if forms and key in forms:
            t = forms[key]
            out.append(t)
            if t == TAG_U8:
                out.append(v)
            elif t == TAG_I32:
                out += struct.pack("<i", v)
            # TAG_INT0 has no payload
        else:
            if v == 0:
                out.append(TAG_INT0)
            elif 0 <= v <= 255:
                out.append(TAG_U8); out.append(v)
            else:
                out.append(TAG_I32); out += struct.pack("<i", v)
    elif isinstance(v, float):
        out.append(forms.get(key, TAG_F64))
        out += struct.pack("<d", v)
    elif isinstance(v, str):
        if forms and isinstance(forms.get(key), tuple) and forms[key][0] == "s":
            _, form, idx = forms[key]
            out.append(TAG_STRING)
            if form == 0:
                # back-reference word replayed verbatim
                out += struct.pack("<I", idx)
            else:
                raw = v.encode("utf-8")
                out += struct.pack("<I", len(raw) | (form << STR_FLAG_BITS))
                out += raw
            return
        raw = v.encode("utf-8")
        out.append(TAG_STRING)
        out += struct.pack("<I", len(raw) | (2 << STR_FLAG_BITS))
        out += raw
    elif isinstance(v, dict):
        n = len(v)
        if forms and key in forms:
            t = forms[key]
        else:
            t = TAG_OBJ_EMPTY if n == 0 else (TAG_OBJ_U8 if n < 256 else TAG_OBJ_I32)
        out.append(t)
        if t != TAG_OBJ_EMPTY:
            if t == TAG_OBJ_U8:
                out.append(n)
            else:
                out += struct.pack("<i", n)
            for fi, (k, val) in enumerate(v.items()):
                # keys: BARE string (word + bytes), never the 0x0A tag byte
                kp = f"{key}#k{fi}"
                if forms and isinstance(forms.get(kp), tuple) and forms[kp][0] == "s":
                    _, kform, kidx = forms[kp]
                    if kform == 0:
                        out += struct.pack("<I", kidx)
                    else:
                        kraw = k.encode("utf-8")
                        out += struct.pack("<I", len(kraw) | (kform << STR_FLAG_BITS))
                        out += kraw
                else:
                    kraw = k.encode("utf-8")
                    out += struct.pack("<I", len(kraw) | (1 << STR_FLAG_BITS))
                    out += kraw
                _enc_value(out, val, forms, f"{key}.{k}")
    elif isinstance(v, list):
        n = len(v)
        if forms and key in forms:
            t = forms[key]
        else:
            t = TAG_ARR_EMPTY if n == 0 else (TAG_ARR_U8 if n < 256 else TAG_ARR_I32)
        out.append(t)
        if t != TAG_ARR_EMPTY:
            if t == TAG_ARR_U8:
                out.append(n)
            else:
                out += struct.pack("<i", n)
            for idx, val in enumerate(v):
                _enc_value(out, val, forms, f"{key}[{idx}]")
    else:
        raise HbsonError(f"cannot re-encode {type(v)} at {key}")


class FormTracingDecoder(Decoder):
    """Decoder that additionally records every node's original tag so a
    re-encode can replay exact form choices (byte-exact round-trip proof).

    forms maps '$'-style paths ('$' root, '.key' for object fields,
    '[i]' for array items) -> tag byte; string nodes store
    TAG_STRING | (string-form << 8).
    """

    def __init__(self, data: bytes, name: str = "<blob>"):
        super().__init__(data, name)
        self.forms: dict = {}
        self._ks: list[str] = []

    def _key(self) -> str:
        return "$" + "".join(self._ks)

    def value(self, depth: int = 0) -> object:
        self._need(1, "tag byte")
        tag = self.b[self.i]
        key = self._key()
        if tag == TAG_OBJ_EMPTY or tag == TAG_ARR_EMPTY or \
           tag in (TAG_INT0, TAG_U8, TAG_I32, TAG_F64, TAG_TRUE, TAG_FALSE, TAG_NULL):
            self.forms[key] = tag
        elif tag == TAG_STRING:
            w = struct.unpack_from("<i", self.b, self.i + 1)[0]
            form = (w >> STR_FLAG_BITS) & 3
            # string entries are tuples: ("s", form, backref_index_or_None)
            self.forms[key] = ("s", form,
                               (w & STR_MASK_LEN) if form == 0 else None)
        elif tag in (TAG_OBJ_U8, TAG_OBJ_I32, TAG_ARR_U8, TAG_ARR_I32):
            self.forms[key] = tag

        if tag in (TAG_OBJ_U8, TAG_OBJ_I32):
            self.i += 1
            n = self._count(tag)
            o: dict = {}
            self._ks.append("")
            base = self._key()          # object's own path; _ks mutates below
            fi = 0
            for _ in range(n):
                # Field keys are BARE strings (no 0x0A tag byte): the u32
                # form-word starts directly at self.i. Record its form so
                # re-encoding keeps the string-table sequence byte-exact.
                kw = struct.unpack_from("<i", self.b, self.i)[0]
                kform = (kw >> STR_FLAG_BITS) & 3
                self.forms[f"{base}#k{fi}"] = (
                    "s", kform, (kw & STR_MASK_LEN) if kform == 0 else None)
                k = self._string()
                self._ks[-1] = f".{k}"
                o[k] = self.value(depth + 1)
                fi += 1
            self._ks.pop()
            return o
        if tag in (TAG_ARR_U8, TAG_ARR_I32):
            self.i += 1
            n = self._count(tag)
            arr = []
            self._ks.append("")
            for idx in range(n):
                self._ks[-1] = f"[{idx}]"
                arr.append(self.value(depth + 1))
            self._ks.pop()
            return arr
        if tag == TAG_STRING:
            self.i += 1
            return self._string()
        return super().value(depth)


def decode_with_forms(data: bytes, name: str = "<blob>"):
    """Decode returning (value, forms); see FormTracingDecoder."""
    d = FormTracingDecoder(data, name)
    v = d.value()
    if d.i != d.n:
        raise HbsonError(f"{name}: trailing slack {d.n - d.i} B after offset {d.i}")
    return v, d.forms


def form_of(forms: dict, key: str):
    """String-word form (0..3) recorded for a path, else None."""
    f = forms.get(key)
    if f is not None and (f & 0xFF) == TAG_STRING:
        return f >> 8
    return f


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def iter_blob_files(root: Path):
    if root.is_file():
        yield root
        return
    for p in sorted(root.rglob("*")):
        if p.is_file():
            with open(p, "rb") as fh:
                head = fh.read(6)
            if head == MAGIC:
                yield p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Strict HBSON decoder (Wartales)")
    ap.add_argument("path", help="file or directory (.prefab/.l3d or any HBSON magic)")
    ap.add_argument("--out", help="output dir for per-file JSON (mirror tree)")
    ap.add_argument("--stats", help="write aggregate stats JSON here")
    ap.add_argument("--limit", type=int, default=0, help="cap number of files")
    ap.add_argument("--no-strict", action="store_true",
                    help="report failures instead of exiting nonzero")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    root = Path(args.path)
    if not root.exists():
        print(f"hbson_decode: no such path: {root}", file=sys.stderr)
        return 2

    outdir = Path(args.out) if args.out else None
    if outdir:
        outdir.mkdir(parents=True, exist_ok=True)

    agg = {
        "files_total": 0, "files_ok": 0, "files_failed": 0,
        "bytes_total": 0, "bytes_ok": 0,
        "tags": {}, "strings": {"inline_ascii": 0, "inline_utf8": 0, "backrefs": 0},
        "failures": [],
    }
    failures = []
    count = 0
    for p in iter_blob_files(root):
        if args.limit and count >= args.limit:
            break
        count += 1
        agg["files_total"] += 1
        rel = p.relative_to(root) if root.is_dir() else Path(p.name)
        try:
            data = p.read_bytes()
        except OSError as e:
            agg["files_failed"] += 1
            failures.append({"file": str(rel), "error": str(e)})
            continue
        agg["bytes_total"] += len(data)
        try:
            dec = Decoder(data, str(rel))
            v = dec.decode()
            agg["files_ok"] += 1
            agg["bytes_ok"] += len(data)
            for k, c in dec.stats["tags"].items():
                agg["tags"][k] = agg["tags"].get(k, 0) + c
            for k in agg["strings"]:
                agg["strings"][k] += dec.stats["strings"][k]
            if outdir:
                dst = outdir / rel.with_suffix(rel.suffix + ".json")
                dst.parent.mkdir(parents=True, exist_ok=True)
                with open(dst, "w", encoding="utf-8", newline="\n") as fh:
                    json.dump(v, fh, ensure_ascii=False, separators=(",", ":"))
            elif root.is_file():
                json.dump(v, sys.stdout, ensure_ascii=False, indent=1)
                print()
            if not args.quiet and not (root.is_file() and args.quiet):
                print(f"ok   {rel} ({len(data)} B)", file=sys.stderr)
        except (HbsonError, OSError) as e:
            agg["files_failed"] += 1
            failures.append({"file": str(rel), "error": str(e)})
            if not args.quiet:
                print(f"FAIL {rel}: {e}", file=sys.stderr)

    agg["bytes_total"] = agg["bytes_ok"]  # failed blobs' bytes are reported per failure

    if args.stats:
        Path(args.stats).parent.mkdir(parents=True, exist_ok=True)
        with open(args.stats, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(agg, fh, ensure_ascii=False, indent=1)

    print(f"hbson_decode: {agg['files_ok']}/{agg['files_total']} ok, "
          f"{agg['files_failed']} failed", file=sys.stderr)
    if failures and not args.no_strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.exit(main())
