"""Harvest-stage test suite — spec-harvest.mdx §7 (TestWriter piece F3).

Written against the SPEC, not against an implementation: every case that
needs ``pipeline/harvest.py`` skips with a clear reason while the module
is absent, so ``python -m pytest pipeline/tests -q`` is green-on-skips
before CodeWriter lands (brief requirement).

Three layers:

1. **Fixture/reader layer** (always runs): mini-paks written byte-for-byte
   per §2.2 and gated on a round-trip through the validated seed reader
   ``pipeline/tools/wtpak.py::Reader`` (§7 unit assertion, "A1" in the
   brief). These prove the fixtures themselves before the tool under test
   exists.
2. **Tool layer** (skips until ``pipeline/harvest.py`` exists): CLI exit
   codes (§3.1), manifest/summary contract (§3.2), resume semantics
   (§3.3), collisions (§4.1), media hook (§4.2), detect vocabulary (§4.3),
   §7 cases 1–14, reconciliation against CRLF scratch-shaped TSVs.
3. **Integration smoke** (marked ``integration``, skipped unless
   ``--run-integration``): res.pak end-to-end against the real client on
   A: — never touched by layers 1–2.

Sparse-fixture note: §7 cases 3/13 demand real f64 positions above 2³¹ /
2³², and the §2.2 tiling invariant forbids gaps — so Σsizes must honestly
cross those marks. The pad bytes are left as filesystem holes (seek past
EOF + truncate); the .pak files read correctly everywhere while occupying
~KB on disk. NEVER full-extract these fixtures (that would write a multi-
GiB zero file) — manifest-level paths only (``--manifest-only``,
``--list``, parse).
"""

import hashlib
import json
import os
import random
import struct
import subprocess
import sys
import zlib
from functools import lru_cache
from pathlib import Path

import pytest

PACK_ROOT = Path(__file__).resolve().parents[2]
PIPELINE = PACK_ROOT / "pipeline"
TOOLS = PIPELINE / "tools"
HARVEST = PIPELINE / "harvest.py"
SCRATCH = PACK_ROOT / "output" / "_recon-scratch"  # local-only, never committed (spec §1)
VERIFY = TOOLS / "_verify"
CLIENT_DIR = Path(os.environ.get("WARTALES_CLIENT", r"A:\SteamLibrary\steamapps\common\Wartales"))
RES_PAK = CLIENT_DIR / "res.pak"
RES_TSV = SCRATCH / "res-pak-entries.tsv"

U32 = 2**32
I32_MAX = 2**31 - 1

# pipeline/tools is a non-package (no __init__.py) — stub sys.path once (§7).
sys.path.insert(0, str(TOOLS))
from wtpak import Reader  # noqa: E402


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def require_harvest():
    """Skip green while the implementation hasn't landed yet."""
    if not HARVEST.exists():
        pytest.skip(
            "pipeline/harvest.py absent — TestWriter precedes CodeWriter "
            "(green-on-skips by design)"
        )


def run_harvest(out, paks, extra=(), timeout=300):
    """Run pipeline/harvest.py through its CLI contract (§3.1)."""
    require_harvest()
    cmd = [sys.executable, str(HARVEST)]
    for p in paks:
        cmd += ["--pak", str(p)]
    cmd += ["--out", str(out), *extra]
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout,
    )


@lru_cache(maxsize=None)
def zero_adler(size):
    """adler32 of `size` zero bytes without materializing them (hole pads)."""
    acc = 1
    chunk = bytes(1 << 20)
    left = size
    while left:
        n = min(left, len(chunk))
        acc = zlib.adler32(chunk[:n], acc)
        left -= n
    return acc & 0xFFFFFFFF


def signed_u32(total):
    """Σ payload bytes reduced mod 2³², interpreted as i32 (§2.1 dataSize)."""
    v = total % U32
    return v - U32 if v >= 2**31 else v


# ---- mini-pak writer: mirrors §2.2 byte-for-byte -------------------------

class FileSpec:
    def __init__(self, name, data=b"", flag=None, zeros_size=None):
        self.name = name
        self.data = data.encode("utf-8") if isinstance(data, str) else data
        self.flag = flag  # None → auto: bit2 iff offset exceeds i32 range (§2.1)
        self.zeros_size = zeros_size  # all-zero payload of this size, holed

    @property
    def size(self):
        return self.zeros_size if self.zeros_size is not None else len(self.data)


class DirSpec:
    def __init__(self, name, *children):
        self.name = name
        self.children = list(children)


def F(name, data=b"", flag=None):
    return FileSpec(name, data, flag)


def Z(name, size, flag=None):
    """Hole pad entry: `size` zero bytes that exist logically, not on disk."""
    return FileSpec(name, None, flag, zeros_size=size)


def D(name="", *children):
    return DirSpec(name, *children)


class Rec:
    __slots__ = ("path", "flag", "offset", "size", "adler", "data", "zeros")

    def __init__(self, path, flag, offset, size, adler, data, zeros):
        self.path, self.flag, self.offset = path, flag, offset
        self.size, self.adler, self.data, self.zeros = size, adler, data, zeros


class PakInfo:
    def __init__(self, path, version, header_size, data_size_stored, total,
                 recs, n_dirs, n_files):
        self.path = path
        self.version = version
        self.header_size = header_size
        self.data_size_stored = data_size_stored
        self.total = total  # Σ payload sizes — the tiling span
        self.recs = recs  # file records, DFS pre-order
        self.n_dirs = n_dirs
        self.n_files = n_files

    @property
    def by_path(self):
        return {r.path: r for r in self.recs}


def write_pak(path, root, *, version=0, magic=b"PAK", data_marker=b"DATA",
              trailing_index_junk=b"", data_size_override=None):
    """Write a synthetic pak per §2.2 and return its expected PakInfo.

    Payload positions tile [0, Σsizes) gap-free in DFS file order; flag bit 2
    selects f64 position encoding; the tree trailer is b"DATA"; nameLen
    counts UTF-8 BYTES.
    """
    assert isinstance(root, DirSpec) and root.name == "", "root is the unnamed dir"
    recs = []
    n_dirs = 1  # wtpak.Reader counts the root dir itself
    next_off = 0

    def walk(node, prefix):
        nonlocal next_off, n_dirs
        for c in node.children:
            full = prefix + c.name
            if isinstance(c, DirSpec):
                n_dirs += 1
                walk(c, full + "/")
            else:
                assert len(c.name.encode("utf-8")) <= 255, "u8 nameLen ceiling"
                assert c.size <= U32 - 1, "entry size is u32"
                flag = c.flag if c.flag is not None else (
                    2 if next_off > I32_MAX else 0)
                adler = (zero_adler(c.size) if c.zeros_size is not None
                         else zlib.adler32(c.data) & 0xFFFFFFFF)
                recs.append(Rec("/" + full, flag, next_off, c.size, adler,
                                c.data, c.zeros_size is not None))
                next_off += c.size

    walk(root, "")
    total = next_off
    enc_recs = iter(recs)  # encode() walks files in the same DFS order

    def encode(node):
        nb = node.name.encode("utf-8")
        assert len(nb) <= 255, f"name exceeds u8 BYTE ceiling: {node.name!r}"
        out = bytes([len(nb)]) + nb
        if isinstance(node, DirSpec):
            out += bytes([1]) + struct.pack("<I", len(node.children))
            for c in node.children:
                out += encode(c)
            return out
        rec = next(enc_recs)
        out += bytes([rec.flag])
        out += (struct.pack("<d", float(rec.offset)) if rec.flag & 2
                else struct.pack("<i", rec.offset))
        out += struct.pack("<I", rec.size)
        out += struct.pack("<I", rec.adler)
        return out

    index = encode(root) + trailing_index_junk
    stored = signed_u32(total) if data_size_override is None else data_size_override
    header_size = 12 + len(index) + 4
    with open(path, "wb") as fh:
        fh.write(magic + bytes([version]) + struct.pack("<ii", header_size, stored))
        fh.write(index)
        fh.write(data_marker)
        base = header_size
        for r in recs:
            if r.zeros:
                continue  # hole; truncate() below pins the logical span
            fh.seek(base + r.offset)
            fh.write(r.data)
        fh.truncate(base + total)
    return PakInfo(path, version, header_size, stored, total, recs,
                   n_dirs, len(recs))


def roundtrip(pak_path, info, *, check_payload=True, allow_dup_paths=False):
    """§7 unit assertion A1: every written mini-pak round-trips through the
    validated seed Reader — header fields, DFS order, per-entry position/
    size/adler, and (non-hole) payload bytes."""
    r = Reader(str(pak_path))
    # raises on bad magic, truncated index, slack ≠ 0, missing DATA;
    # parse() RETURNS the root — iter_files() needs it assigned (wtpak idiom)
    r.root = r.parse()
    assert r.version == info.version
    assert r.header_size == info.header_size
    assert r.data_size == info.data_size_stored
    assert r.data_magic == b"DATA"
    assert (r.n_files, r.n_dirs) == (info.n_files, info.n_dirs)
    got = [("/" + p, e) for p, e in r.iter_files()]
    assert [p for p, _ in got] == [rec.path for rec in info.recs], "DFS order"
    if not allow_dup_paths:
        assert len({p for p, _ in got}) == len(got)
    for rec, (gp, e) in zip(info.recs, got):
        assert gp == rec.path
        assert e["size"] == rec.size
        assert e["adler"] == rec.adler
        assert int(e["pos"]) == rec.offset
        if check_payload and not rec.zeros:
            assert r.read_file_bytes(e) == rec.data
    return r


# ---- scratch-TSV synthesis + reference reconciler ------------------------

def to_tsv(info, *, crlf=True, flag2_offsets="stored", numeric_pad=False):
    """Synthesize a scratch-shaped TSV: HEADERLESS, 5 columns
    path<TAB>flag<TAB>offset<TAB>size<TAB>adler8hex (spec §9.3: row 1 is
    data). `flag2_offsets` may be a callable planting recon-style synthetic
    garbage into flag-2 offset cells (cf. the uniform-2²⁸ map.pak column)."""
    rows = []
    for i, rec in enumerate(info.recs):
        off = rec.offset
        if rec.flag & 2 and flag2_offsets != "stored":
            off = flag2_offsets(i)
        size = f"{rec.size:08d}" if numeric_pad else str(rec.size)
        rows.append(f"{rec.path}\t{rec.flag}\t{off}\t{size}\t{rec.adler:08x}")
    sep = "\r\n" if crlf else "\n"
    return sep.join(rows) + sep


def parse_tsv(tsv_text):
    rows = []
    for line in tsv_text.split("\n"):
        if not line.strip():
            continue
        f = line.rstrip("\r").split("\t")  # strip \r — scratch TSVs are CRLF
        assert len(f) == 5, f"TSV row is not 5 columns: {line!r}"
        rows.append(f)  # headerless: first row is DATA, never skipped (§9.3)
    return rows


def reconcile(tsv_text, rows):
    """Reference implementation of the reconciliation CONTRACT (brief + spec
    §1): strip \\r, compare numerically; (path, size, adler) always; offsets
    compared for flag-0 rows only — NEVER for flag-2 (their TSV column is a
    proven-synthetic reconstruction). Returns mismatch strings."""
    tsv_rows = parse_tsv(tsv_text)
    assert len(tsv_rows) == len(rows), \
        f"row count {len(tsv_rows)} != {len(rows)} (headerless TSV — do not skip row 1)"
    bad = []
    for ts, m in zip(tsv_rows, rows):
        tp, tflag, toff, tsize, tadler = ts
        if tp != m["path"]:
            bad.append(f"path {tp!r} != {m['path']!r}")
        if int(tsize) != int(m["size"]):
            bad.append(f"{tp}: size {tsize} != {m['size']}")
        if int(tadler, 16) != int(m["hash"], 16):
            bad.append(f"{tp}: adler {tadler} != {m['hash']}")
        if int(tflag) == 0 and int(toff) != int(m["offset"]):
            bad.append(f"{tp}: flag-0 offset {toff} != {m['offset']}")
    return bad


def rows_from_info(info):
    return [{"path": r.path, "flag": r.flag, "offset": r.offset,
             "size": r.size, "hash": f"{r.adler:08x}"} for r in info.recs]


def normalize_list_line(line):
    f = line.split("\t")
    assert len(f) == 5, f"--list row is not 5 columns: {line!r}"
    return {"path": f[0], "flag": int(f[1]), "offset": int(f[2]),
            "size": int(f[3]), "hash": f[4]}


# ---- artifact readers -----------------------------------------------------

def read_manifest(out, stem):
    p = Path(out) / f"{stem}.manifest.jsonl"
    raw = p.read_bytes()
    assert b"\r" not in raw, "manifest must be LF-only (§3.2)"
    assert raw.endswith(b"\n"), "manifest ends with a newline"
    return [json.loads(ln) for ln in raw.decode("utf-8").splitlines() if ln]


def read_summary(out, stem):
    return json.loads((Path(out) / f"{stem}.summary.json").read_text(encoding="utf-8"))


def find_report(out):
    """§6 names extracted/harvest-report.json — beside the harvest root."""
    for cand in (Path(out).parent / "harvest-report.json", Path(out) / "harvest-report.json"):
        if cand.exists():
            return cand
    return None


def collect_keys(obj):
    """Lowercased key names anywhere in a nested JSON structure."""
    found = set()
    for k, _ in _walk_items(obj):
        found.add(str(k).rsplit(".", 1)[-1].lower())
    return found


def _walk_items(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield f"{prefix}.{k}", v
            yield from _walk_items(v, f"{prefix}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_items(v, f"{prefix}[{i}]")


def leaves(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from leaves(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from leaves(v)
    else:
        yield obj


def payload_targets_absent(out, stem):
    base = Path(out) / stem
    hits = [str(p) for p in base.rglob("*") if p.is_file()] if base.exists() else []
    assert hits == [], f"payloads written despite forbidden run: {hits[:5]}"


# --------------------------------------------------------------------------
# session-scoped sparse fixtures (§7 cases 3 & 13)
# --------------------------------------------------------------------------

@pytest.fixture(scope="session")
def big_above_2pow32(tmp_path_factory):
    """Case 13: an f64-position entry ABOVE 2³² with honest tiling — the pads
    are holes, so the pak reads everywhere but occupies ~KB on disk. Pads are
    split to stay under 2³¹ each: wtpak.Reader parses entry size as SIGNED
    i32, so no single entry may reach 2³¹ (real-corpus max ≈33 MB)."""
    d = tmp_path_factory.mktemp("big32")
    p1, p2 = 1_500_000_000, 1_500_000_000
    p3 = U32 - 100 - p1 - p2  # lands /high.bin exactly at 2³²
    assert max(p1, p2, p3) < 2**31
    root = D("", F("a.bin", b"A" * 100),
             Z("pad1.bin", p1), Z("pad2.bin", p2), Z("pad3.bin", p3),
             F("high.bin", b"HI" * 82, flag=2))
    info = write_pak(d / "hi32.pak", root)
    high = info.by_path["/high.bin"]
    assert high.offset == U32 and high.flag == 2 and info.total == U32 + 164
    roundtrip(info.path, info, check_payload=False)  # holes: no byte read
    return info


@pytest.fixture(scope="session")
def big_wrapped_datasize(tmp_path_factory):
    """Case 3: an f64 entry above 2³¹ whose Σ pushes dataSize past the i32
    wrap — the stored field goes negative; wrap delta must be exactly −2³².
    Pads stay under 2³¹ each (see big_above_2pow32)."""
    h = 2**31 + 2048
    d = tmp_path_factory.mktemp("bigwrap")
    q1 = 1_100_000_000
    q2 = h - 100 - q1
    assert 0 < q2 < 2**31
    root = D("", F("a.bin", b"A" * 100),
             Z("pad1.bin", q1), Z("pad2.bin", q2),
             F("high.bin", bytes(range(128)), flag=2))
    info = write_pak(d / "wrapped.pak", root)
    assert info.total == h + 128 >= 2**31
    assert info.data_size_stored < 0
    assert info.data_size_stored - info.total == -U32
    roundtrip(info.path, info, check_payload=False)
    return info


# ==========================================================================
# layer 1 — fixture/reader (always runs; proves the fixtures themselves)
# ==========================================================================

def test_zero_adler_formula():
    """Ground-truth the shortcut used for hole-pad adlers against real zlib."""
    for n in (0, 1, 100, 65520, 65521, 65522, 3 * 65521 + 7):
        assert zero_adler(n) == zlib.adler32(b"\x00" * n) & 0xFFFFFFFF, n


def test_s7_case1_flat_three_flag0_tiling(tmp_path):
    """§7 case 1: flat pak, three flag-0 files, offsets tile from 0."""
    info = write_pak(tmp_path / "flat.pak",
                     D("", F("one.txt", b"111"), F("two.txt", b"2222"),
                       F("three.txt", b"333333")))
    roundtrip(info.path, info)
    assert [r.offset for r in info.recs] == [0, 3, 7]
    assert all(r.flag == 0 for r in info.recs)
    assert info.total == 13  # 3 + 4 + 6 payload bytes


def test_s7_case2_flag_mix_small_f64(tmp_path):
    """§7 case 2: flag-0/flag-2 mix incl. a flag-2 entry at a SMALL position —
    encoding choice must not imply magnitude semantics (§9.2)."""
    info = write_pak(tmp_path / "mix.pak",
                     D("", D("d", F("f0.txt", b"flag0")),
                       F("small_f64.bin", b"\x01\x02\x03\x04", flag=2),
                       F("plain.bin", b"x" * 10)))
    roundtrip(info.path, info)
    small = info.by_path["/small_f64.bin"]
    assert small.flag == 2 and small.offset == 5  # tiny (after b"flag0"), yet f64-encoded
    assert info.by_path["/d/f0.txt"].flag == 0


def test_s7_case4_unicode_names(tmp_path):
    """§7 case 4: CJK / emoji / accented names; nameLen counts UTF-8 BYTES;
    a multibyte name sitting exactly at the 255-byte u8 ceiling."""
    ceiling = "é" * 127 + "a"  # 254 + 1 = exactly 255 UTF-8 bytes
    assert len(ceiling.encode("utf-8")) == 255
    info = write_pak(
        tmp_path / "uni.pak",
        D("", F("地図データ.json", "{}"),
          F("café_\U0001F600.dat", "smile"),
          F(ceiling, "ceiling")))
    roundtrip(info.path, info)
    paths = {r.path for r in info.recs}
    assert "/地図データ.json" in paths
    assert "/café_\U0001F600.dat" in paths
    assert "/" + ceiling in paths


def test_s7_case5_empty_dir_nested_siblings(tmp_path):
    """§7 case 5: empty dir, deep chains, sibling dirs — dirs are structure
    only (the no-manifest-lines side is pinned at the tool layer)."""
    deep = D("l1", D("l2", D("l3", D("l4", D("l5", D("l6", D("l7", D("l8",
             F("bottom.bin", "deep")))))))))
    info = write_pak(tmp_path / "dirs.pak",
                     D("", D("empty_dir"), D("sib_a", F("x", "x")),
                       D("sib_b", F("y", "y")), deep))
    roundtrip(info.path, info)
    assert info.n_files == 3
    # Reader's dir count includes the root: root + empty + 2 siblings + l1..l8
    assert info.n_dirs == 12
    assert "/empty_dir" not in {r.path for r in info.recs}


def test_s7_case7_zero_byte_entry(tmp_path):
    """§7 case 7 (writer half): a zero-byte entry stores size 0 and adler 1
    (adler32 of b"" is 1); the `empty` detect token is pinned at the tool
    layer."""
    info = write_pak(tmp_path / "void.pak", D("", F("nothing.bin")))
    roundtrip(info.path, info)
    assert info.recs[0].size == 0 and info.recs[0].adler == 1


def test_s7_case13_f64_above_2pow32_exact(big_above_2pow32):
    """§7 case 13: the >2³² position survives the seed reader's parse EXACTLY
    (f64 represents 2³² precisely; manifest fidelity is pinned at the tool
    layer)."""
    info = big_above_2pow32
    r = roundtrip(info.path, info, check_payload=False)
    entries = {"/" + p: e for p, e in r.iter_files()}
    assert int(entries["/high.bin"]["pos"]) == U32
    assert entries["/high.bin"]["size"] == 164


def test_s7_case3_wrapped_datasize_reader_tolerates(big_wrapped_datasize):
    """§7 case 3 (reader half): a negative i32 dataSize field is tolerated —
    the tree parses normally with the wrapped field in place."""
    info = big_wrapped_datasize
    r = roundtrip(info.path, info, check_payload=False)
    assert r.data_size < 0
    entries = {"/" + p: e for p, e in r.iter_files()}
    assert int(entries["/high.bin"]["pos"]) == 2**31 + 2048


def test_s7_case14_implausible_childcount_loud(tmp_path):
    """§7 case 14: an implausible childCount must fail LOUDLY, naming the
    node — never an unbounded walk and never a silently truncated tree.

    Present tense, post-fix: wtpak.Reader reads childCount as SIGNED i32, so
    counts ≥ 2³¹ go negative and range(negative) is EMPTY — silent acceptance
    of a corrupt tree. Harvest validates childCount upstream
    (HarvestReader.read_entry: unsigned interpretation + bound vs remaining
    index bytes), so the crafted cases below exit 3 naming the node TODAY;
    the raw reader's signed-i32 hole stays compensated at the harvest layer.
    """

    def crafted(child_count, tail=b""):
        index = bytes([0])  # root node: empty name...
        index += bytes([1]) + struct.pack("<I", child_count)  # ...dir, absurd count (on-disk u32 bits)
        index += tail
        header_size = 12 + len(index) + 4
        blob = (b"PAK" + bytes([0])
                + struct.pack("<ii", header_size, 0) + index + b"DATA")
        p = tmp_path / f"cc_{child_count & 0xFFFFFFFF:x}_{len(tail)}.pak"
        p.write_bytes(blob)
        return str(p)

    # Moderate lie with insufficient data → the seed reader does raise loud
    # (IndexError/struct.error), bounded by construction: the index is
    # exhausted right after the bogus field.
    r = Reader(crafted(3, tail=bytes([0])))
    with pytest.raises((IndexError, struct.error, ValueError, EOFError,
                        RecursionError)):
        r.parse()

    # Huge count (≥ 2³¹ as u32) → must be a LOUD format failure naming the
    # node, not a silent empty dir.
    pak = crafted(0xFFFFFFFE)
    proc = run_harvest(tmp_path / "out", [pak])
    assert proc.returncode == 3, \
        ("implausible childCount must exit 3; silent empty-dir acceptance is "
         f"the defect this test exists to catch: {proc.stdout!r} {proc.stderr!r}")
    combined = proc.stdout + proc.stderr
    assert "root" in combined or "childcount" in combined.lower(), \
        f"node must be named: {combined!r}"
    payload_targets_absent(tmp_path / "out", Path(pak).stem)


def test_s93_tsv_is_headerless_and_crlf(big_above_2pow32):
    """Contract-hole §9.3 guard: our synthesized scratch TSV keeps row 1 as
    data and survives \r stripping — the comparator's own ground rules."""
    info = big_above_2pow32
    text = to_tsv(info)
    assert "\r\n" in text
    rows = parse_tsv(text)
    assert len(rows) == info.n_files
    assert rows[0][0] == info.recs[0].path == "/a.bin"  # row 1 IS data


# ==========================================================================
# layer 1.5 — reconciliation CONTRACT (pure; runs without the tool)
# ==========================================================================

def test_reconcile_contract_reference(big_above_2pow32):
    """The (path,size,adler)-with-flag-0-offsets-only contract, exercised
    directly: CRLF/LF equivalence, numeric compare, flag-2 offset garbage
    tolerated, real perturbations caught."""
    info = big_above_2pow32
    rows = rows_from_info(info)

    assert reconcile(to_tsv(info), rows) == []
    assert reconcile(to_tsv(info, crlf=False), rows) == []
    assert reconcile(to_tsv(info, numeric_pad=True), rows) == []  # numeric, not textual
    # flag-2 offsets replaced by recon-style uniform-2²⁸ steps → still clean:
    assert reconcile(to_tsv(info, flag2_offsets=lambda i: i * 2**28), rows) == []

    # Negative controls — the comparator must actually bite.
    lines = to_tsv(info).split("\r\n")

    bad_size = list(lines)
    f = bad_size[0].split("\t")
    f[3] = str(int(f[3]) + 1)
    bad_size[0] = "\t".join(f)
    assert reconcile("\r\n".join(bad_size), rows) != []

    bad_adler = list(lines)
    f = bad_adler[-2].split("\t")  # last data row (final element is '')
    f[4] = "deadbeef"
    bad_adler[-2] = "\t".join(f)
    assert reconcile("\r\n".join(bad_adler), rows) != []

    bad_path = list(lines)
    f = bad_path[1].split("\t")
    f[0] = f[0] + "x"
    bad_path[1] = "\t".join(f)
    assert reconcile("\r\n".join(bad_path), rows) != []

    # A flag-0 offset perturbation IS a mismatch — they tile, so comparable.
    bad_off = list(lines)
    f = bad_off[0].split("\t")
    assert f[1] == "0"
    f[2] = str(int(f[2]) + 8)
    bad_off[0] = "\t".join(f)
    assert reconcile("\r\n".join(bad_off), rows) != []


# ==========================================================================
# layer 2 — the tool under test (skips until pipeline/harvest.py lands)
# ==========================================================================

def test_exit_codes_usage_and_preflight(tmp_path):
    """§3.1: usage/preflight failures exit 2 — no --pak given, and a --pak
    that does not exist."""
    proc = run_harvest(tmp_path / "out", [])
    assert proc.returncode == 2, proc.stdout + proc.stderr
    proc = run_harvest(tmp_path / "out", [tmp_path / "missing.pak"])
    assert proc.returncode == 2, proc.stdout + proc.stderr


def test_s7_case6_duplicate_path_exit4_nothing_written(tmp_path):
    """§7 case 6 (+§4.1): duplicate full path twice → exit 4, both locations
    named, nothing written."""
    info = write_pak(tmp_path / "dup.pak",
                     D("", D("sub", F("dup.txt", "one"), F("dup.txt", "two")),
                       F("keep.bin", "k")))
    out = tmp_path / "out"
    proc = run_harvest(out, [info.path])
    assert proc.returncode == 4, proc.stdout + proc.stderr
    combined = proc.stdout + proc.stderr
    assert "/sub/dup.txt" in combined
    assert combined.count("/sub/dup.txt") >= 2, "both colliding locations named"
    payload_targets_absent(out, "dup")


def test_s7_case6_case_only_collision_ntfs(tmp_path):
    """§7 case 6 (+§4.1): case-only collision exits 4 like any duplicate.
    Native NTFS is case-insensitive — this machine IS the mocked target."""
    if os.name != "nt":
        pytest.skip("case-only collision needs a case-insensitive (NTFS) target")
    info = write_pak(tmp_path / "case.pak",
                     D("", F("Shield.png", "A"), F("shield.png", "B")))
    out = tmp_path / "out"
    proc = run_harvest(out, [info.path])
    assert proc.returncode == 4, proc.stdout + proc.stderr
    combined = proc.stdout + proc.stderr
    assert "/Shield.png" in combined and "/shield.png" in combined
    payload_targets_absent(out, "case")


@pytest.mark.parametrize("flavor",
                         ["bad_magic", "slack_junk", "hard_truncate",
                          "no_data_marker", "size_lies"])
def test_s7_case8_corrupt_fixtures_exit3(tmp_path, flavor):
    """§7 case 8 (+§2.2 hard invariants): each corruption exits 3;
    entry-level failures name the offending entry."""
    kw = {}
    if flavor == "bad_magic":
        kw["magic"] = b"PXK"
    elif flavor == "slack_junk":
        kw["trailing_index_junk"] = b"\xde\xad\xbe\xef"  # index slack ≠ 0
    elif flavor == "no_data_marker":
        kw["data_marker"] = b"DATX"
    info = write_pak(tmp_path / "corrupt.pak",
                     D("", F("good.bin", "G" * 64), F("tail.bin", "T" * 32)), **kw)

    if flavor == "hard_truncate":
        raw = info.path.read_bytes()
        info.path.write_bytes(raw[: info.header_size // 2])  # truncated index
    elif flavor == "size_lies":
        # Preflight (index-only) passes; the extract-phase peek/read past EOF
        # must fail loudly naming the entry (§4.3).
        raw = info.path.read_bytes()
        info.path.write_bytes(raw[: info.header_size + info.total - 10])

    proc = run_harvest(tmp_path / "out", [info.path])
    assert proc.returncode == 3, (flavor, proc.stdout, proc.stderr)
    if flavor == "size_lies":
        # FINDING (2026-08-24): with tiling + delta-0 span enforced first
        # (§2.2 hard invariants), the truncation is caught at PREFLIGHT as a
        # span violation — naming the PAK, not the entry. Entry-naming is
        # reachable only when invariants are downgraded (--no-strict), since
        # verified tiling makes extract-phase EOF overrun impossible. Both
        # routes are exit 3; accept either reporter.
        combined = (proc.stdout + proc.stderr).lower()
        assert "/tail.bin" in combined or "span" in combined, \
            "offending entry or span violation must be named"


def test_s7_case8_tampered_source_payload_exit3(tmp_path):
    """§7 case 8, tampered-payload clause: an adler mismatch on the SOURCE is
    detected when its bytes flow — i.e., on extraction into a FRESH output
    root — and exits 3 naming the entry.

    FINDING (2026-08-24, live behavior confirmed): §3.3 resume verifies the
    TARGET files only, so re-running over intact targets after the source is
    corrupted completes rc 0 by design (targets match their stored adlers).
    The mismatch tripwire therefore lives on the extract path."""
    info = write_pak(tmp_path / "src.pak",
                     D("", F("victim.bin", "V" * 100), F("other.bin", "O" * 50)))
    victim = info.by_path["/victim.bin"]
    with open(info.path, "r+b") as fh:  # flip one byte inside its payload region
        fh.seek(info.header_size + victim.offset + 7)
        fh.write(bytes([0xFF]))

    proc = run_harvest(tmp_path / "out_fresh", [info.path])
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "/victim.bin" in proc.stdout + proc.stderr


CORRUPT_STRICTNESS_MATRIX = (
    # flavor             strict  lenient  needle required in the lenient warning
    ("bad_magic",        3,      3,       None),
    ("size_lies",        3,      3,       None),
    ("tampered_payload", 3,      3,       None),
    ("slack_junk",       3,      0,       "slack"),
    ("no_data_marker",   3,      0,       "trailer"),
)


@pytest.mark.parametrize("flavor,strict_rc,lenient_rc,warn_needle",
                         CORRUPT_STRICTNESS_MATRIX)
def test_corrupt_flavor_x_strictness_matrix(tmp_path, flavor,
                                            strict_rc, lenient_rc, warn_needle):
    """Lenient×integrity interaction (arbiter M3t): the exact expected-code
    matrix per corruption flavor. Format/integrity failures (bad magic,
    payload truncation caught by detect/read, adler mismatch after extract)
    are NEVER downgradable — 3 in both modes. §2.2 invariant-list items
    (index slack, missing DATA trailer) downgrade under --no-strict to a rc-0
    warning naming the violation."""
    kw = {}
    if flavor == "bad_magic":
        kw["magic"] = b"PXK"
    elif flavor == "slack_junk":
        kw["trailing_index_junk"] = b"\xde\xad\xbe\xef"
    elif flavor == "no_data_marker":
        kw["data_marker"] = b"DATX"
    info = write_pak(tmp_path / "corrupt.pak",
                     D("", F("good.bin", "G" * 64), F("tail.bin", "T" * 32)), **kw)

    if flavor == "size_lies":
        raw = info.path.read_bytes()
        info.path.write_bytes(raw[: info.header_size + info.total - 10])
    elif flavor == "tampered_payload":
        victim = info.by_path["/good.bin"]
        with open(info.path, "r+b") as fh:
            fh.seek(info.header_size + victim.offset + 7)
            fh.write(bytes([0xFF]))

    strict = run_harvest(tmp_path / "out_strict", [info.path])
    assert strict.returncode == strict_rc, \
        (flavor, "strict", strict.stdout, strict.stderr)
    if strict_rc != 0:
        assert "Traceback" not in strict.stderr

    lenient_out = tmp_path / "out_lenient"
    lenient = run_harvest(lenient_out, [info.path], ["--no-strict"])
    assert lenient.returncode == lenient_rc, \
        (flavor, "lenient", lenient.stdout, lenient.stderr)
    if lenient_rc == 0:
        combined = (lenient.stdout + lenient.stderr).lower()
        assert "warning" in combined, f"{flavor}: downgraded but silent"
        assert warn_needle in combined, \
            f"{flavor}: warning must name the violation ({warn_needle!r})"


def test_s7_case9_idempotency_and_selfheal(tmp_path):
    """§7 case 9 (+§3.3): second run skips everything (extracted=0,
    skipped_reuse=N); mutating ONE harvested byte re-extracts EXACTLY that
    entry and restores its bytes."""
    info = write_pak(tmp_path / "idem.pak",
                     D("", F("alpha.bin", "A" * 256), F("beta.bin", "B" * 512)))
    out = tmp_path / "out"

    p1 = run_harvest(out, [info.path])
    assert p1.returncode == 0, p1.stdout + p1.stderr
    s1 = read_summary(out, "idem")
    assert s1["counts"]["extracted"] == 2
    assert s1["counts"]["skipped_reuse"] == 0

    p2 = run_harvest(out, [info.path])
    assert p2.returncode == 0, p2.stdout + p2.stderr
    s2 = read_summary(out, "idem")
    assert s2["counts"]["extracted"] == 0
    assert s2["counts"]["skipped_reuse"] == 2

    target = out / "idem" / "alpha.bin"
    good = target.read_bytes()
    data = bytearray(good)
    data[3] ^= 0xFF
    target.write_bytes(bytes(data))

    p3 = run_harvest(out, [info.path])
    assert p3.returncode == 0, p3.stdout + p3.stderr
    s3 = read_summary(out, "idem")
    assert s3["counts"]["extracted"] == 1
    assert s3["counts"]["skipped_reuse"] == 1
    assert target.read_bytes() == good  # healed byte-identically


def test_s7_case10_list_and_manifest_only(tmp_path):
    """§7 case 10 (+§3.1): --list prints scratch-order TSV columns and writes
    NOTHING anywhere; --manifest-only emits complete manifests and zero
    payload files."""
    info = write_pak(tmp_path / "lo.pak",
                     D("", D("d", F("a.bin", "a" * 16)),
                       F("b.bin", "b" * 32, flag=2)))
    out = tmp_path / "out"

    proc = run_harvest(out, [info.path], ["--list"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    rows = [normalize_list_line(ln) for ln in proc.stdout.splitlines() if ln.strip()]
    assert [r["path"] for r in rows] == [rec.path for rec in info.recs]
    for r, rec in zip(rows, info.recs):
        assert (r["flag"], r["offset"], r["size"], r["hash"]) == \
            (rec.flag, rec.offset, rec.size, f"{rec.adler:08x}")
    out_dir = Path(out)
    assert not out_dir.exists() or not any(out_dir.rglob("*")), \
        "--list must write nothing anywhere"

    out2 = tmp_path / "out2"
    proc = run_harvest(out2, [info.path], ["--manifest-only"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    man = read_manifest(out2, "lo")
    assert [m["path"] for m in man] == [rec.path for rec in info.recs]
    payload_targets_absent(out2, "lo")


def test_multipak_distinct_stems_both_harvested(tmp_path):
    """Arbiter M1t: the multi-pak headline form. Two distinct-stem archives in
    one run → BOTH manifests and BOTH summaries emitted with their own rows
    and provenance (no silent second-wins), and two per-pak seed entries in
    the acceptance report."""
    a = write_pak(tmp_path / "alpha.pak", D("", F("a.bin", "A" * 64)))
    b = write_pak(tmp_path / "beta.pak",
                  D("", F("b.bin", "B" * 96), F("c.bin", "C" * 32)))
    out = tmp_path / "out"
    proc = run_harvest(out, [a.path, b.path])
    assert proc.returncode == 0, proc.stdout + proc.stderr

    man_a = read_manifest(out, "alpha")
    man_b = read_manifest(out, "beta")
    assert [m["path"] for m in man_a] == ["/a.bin"]
    assert [m["path"] for m in man_b] == ["/b.bin", "/c.bin"]
    assert (out / "alpha" / "a.bin").read_bytes() == b"A" * 64
    assert (out / "beta" / "b.bin").read_bytes() == b"B" * 96

    s_a, s_b = read_summary(out, "alpha"), read_summary(out, "beta")
    assert s_a["source"] == str(a.path), "first pak's summary must survive"
    assert s_b["source"] == str(b.path)

    rep = find_report(out)
    assert rep is not None
    j = json.loads(rep.read_text(encoding="utf-8"))
    assert set(j["paks"]) == {"alpha", "beta"}, "one report entry per pak"
    for stem, total in (("alpha", 64), ("beta", 128)):
        seed = j["paks"][stem]["samples"]["seed"]
        assert type(seed) is int and not isinstance(seed, bool), stem


def test_multipak_same_stem_exit2_names_both_paths(tmp_path):
    """Arbiter M1t/M2 pin: two same-stem archives would write ONE output set —
    refused at preflight with exit 2 naming both paths; nothing written."""
    d1 = tmp_path / "d1"
    d2 = tmp_path / "d2"
    d1.mkdir()
    d2.mkdir()
    p1 = write_pak(d1 / "twin.pak", D("", F("one.bin", "ONE")))
    p2 = write_pak(d2 / "twin.pak", D("", F("two.bin", "TWO" * 8)))
    assert p1.path.stem == p2.path.stem
    out = tmp_path / "out"

    proc = run_harvest(out, [p1.path, p2.path])
    assert proc.returncode == 2, proc.stdout + proc.stderr
    combined = proc.stdout + proc.stderr
    assert str(p1.path) in combined and str(p2.path) in combined, \
        "both colliding --pak paths must be named"
    assert not (out / "twin.manifest.jsonl").exists()
    payload_targets_absent(out, "twin")


def test_manifest_schema_contract(tmp_path):
    """§3.2 manifest contract: exact key set (sha256 appears ONLY with the
    flag), leading-/ forward-slash paths, integer offsets, lowercase 8-hex
    adler, flag ∈ {0,2}, LF-only UTF-8, DFS order, dirs never listed."""
    info = write_pak(tmp_path / "schema.pak",
                     D("", D("dir", F("in.bin", "I" * 8)),
                       F("top.bin", "T" * 24, flag=2), F("z.bin", "")))
    out = tmp_path / "out"
    proc = run_harvest(out, [info.path])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    man = read_manifest(out, "schema")

    assert [m["path"] for m in man] == [rec.path for rec in info.recs]
    for m, rec in zip(man, info.recs):
        assert set(m) == {"path", "flag", "offset", "size", "hash",
                          "detect", "media"}
        assert m["path"][0] == "/" and "\\" not in m["path"]
        assert m["path"] == rec.path
        assert type(m["flag"]) is int and not isinstance(m["flag"], bool)
        assert m["flag"] in (0, 2) and m["flag"] == rec.flag
        assert type(m["offset"]) is int and not isinstance(m["offset"], bool)
        assert m["offset"] == rec.offset
        assert type(m["size"]) is int and not isinstance(m["size"], bool)
        assert m["size"] == rec.size
        assert len(m["hash"]) == 8 and m["hash"] == m["hash"].lower()
        int(m["hash"], 16)  # hex-decodable
        assert m["hash"] == f"{rec.adler:08x}"
        assert m["media"] is False
    assert all(m["path"] != "/dir" for m in man)  # dirs are not listed


def test_manifest_sha256_column(tmp_path):
    """§3.1 --sha256: adds exactly one key, matching the payload digest."""
    info = write_pak(tmp_path / "sh.pak", D("", F("h.bin", "abcd" * 64)))
    out = tmp_path / "out"
    proc = run_harvest(out, [info.path], ["--sha256"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    man = read_manifest(out, "sh")
    assert set(man[0]) == {"path", "flag", "offset", "size", "hash",
                           "detect", "media", "sha256"}
    assert man[0]["sha256"] == hashlib.sha256(info.recs[0].data).hexdigest()


def test_fingerprint_source_sha256_pins_whole_pak(tmp_path):
    """§3.1 --fingerprint: summary provenance carries the WHOLE-pak sha256
    (arbiter L3 addition — the flag previously had zero coverage)."""
    info = write_pak(tmp_path / "fp.pak",
                     D("", F("f1.bin", "abc" * 100), F("f2.bin", "xyz" * 40)))
    out = tmp_path / "out"
    proc = run_harvest(out, [info.path], ["--fingerprint"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    s = read_summary(out, "fp")
    assert s["source_sha256"] == hashlib.sha256(info.path.read_bytes()).hexdigest()


def test_detect_vocabulary_and_extension_lies(tmp_path):
    """§4.3: classification by MAGIC, never extension; packed names preserved
    verbatim; the u:<8hex> fallback and the `empty` token."""
    cases = [
        ("pic.png", b"DDS |\x00\x00\x00\x07\x10", "dds"),           # .png lies
        ("real.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\x00", "png"),
        ("photo.jpg", b"\xff\xd8\xff\xe0\x00\x00\x00\x00", "jpeg"),
        ("mesh.fbx", b"HMD\x00\x00\x00\x00\x00\x00", "hmd"),        # .fbx = HMD
        ("thing.prefab", b"HBSON\x00\x00\x00\x00\x00", "hbson"),
        ("atlas.tx", b"\x76\x2f\x31\x01\x00\x00\x00\x00", "tx"),
        ("cfg.json", b'{"x": 1}', "json"),
        ("ws.json", b" \t\r\n{\"x\":1}", "json"),                   # ws-led '{'
        ("doc.xml", b"<root/>", "xml"),
        ("ws.xml", b"\n <root/>", "xml"),
        ("arch.zip", b"PK\x03\x04\x00\x00\x00\x00", "zip"),
        ("comp.gz", b"\x1f\x8b\x08\x00\x00\x00\x00\x00", "gzip"),
        ("void.bin", b"", "empty"),
        ("terrain.f32", b"\x00\x01\x02\x03\x04\x05\x06\x07", "u:00010203"),
    ]
    payloads = {f"/{n}": d for n, d, _ in cases}
    info = write_pak(tmp_path / "detect.pak",
                     D("", *[F(n, d) for n, d, _ in cases]))
    out = tmp_path / "out"
    proc = run_harvest(out, [info.path])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    man = {m["path"]: m for m in read_manifest(out, "detect")}
    for name, _, token in cases:
        key = f"/{name}"
        assert man[key]["detect"] == token, f"{name}: {man[key]['detect']} != {token}"
        assert (out / "detect" / name).exists()
        assert (out / "detect" / name).read_bytes() == payloads[key]  # verbatim


def test_summary_contract_and_buildid(tmp_path):
    """§3.2 summary contract: measured provenance, version byte recorded
    (never hardcoded — this fixture ships version 1), counts, totals,
    census, throughput, strict flag, --buildid stamp."""
    info = write_pak(tmp_path / "sum.pak",
                     D("", D("d", F("a.bin", "A" * 128)),
                       F("b.bin", "B" * 64, flag=2)), version=1)
    out = tmp_path / "out"
    proc = run_harvest(out, [info.path], ["--buildid", "20318128"])
    assert proc.returncode == 0, proc.stdout + proc.stderr

    s = read_summary(out, "sum")
    # §3.2 concepts, pinned to the implementation's names (verified live
    # 2026-08-24): measured provenance, wrap arithmetic, counts, census,
    # throughput, lineage, buildid, strict flag.
    keys = collect_keys(s)
    for needle in ("version", "header_size", "measured", "mtime",
                   "data_size_field_i32", "wrap_delta_vs_sum_sizes",
                   "count", "files", "dirs", "media", "skipped_reuse",
                   "extracted", "detect_census", "sum_entry_bytes",
                   "wall_seconds", "throughput", "buildid", "strict",
                   "reader"):
        assert any(needle in k for k in keys), f"summary lacks a {needle!r} key"

    assert s["counts"]["files"] == 2
    assert s["counts"]["extracted"] == 2
    assert s["counts"]["skipped_reuse"] == 0
    assert s["counts"]["media"] == 0
    assert s["header_size"] == info.header_size
    assert s["version_byte"] == 1, "version byte recorded, never hardcoded"
    assert s["wrap_delta_vs_sum_sizes"] == 0  # Σ = 197 < 2³¹ → no wrap
    assert s["sum_entry_bytes"] == info.total  # exact path (arbiter L1/L3)
    assert s["measured_size"] == info.path.stat().st_size  # measured provenance
    assert "20318128" in json.dumps(s), "--buildid string reaches summary.json"
    assert s["strict"] is True


def test_wrap_delta_recorded_for_small_pak(tmp_path):
    """§2.1/§3.2: with Σ < 2³¹ the stored dataSize equals Σ and the recorded
    wrap delta is 0 — provenance arithmetic visible in summary.json."""
    info = write_pak(tmp_path / "wrap0.pak", D("", F("a.bin", "A" * 128)))
    assert info.data_size_stored == info.total == 128
    out = tmp_path / "out"
    proc = run_harvest(out, [info.path])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    nums = [v for _, v in _walk_items(read_summary(out, "wrap0"))
            if isinstance(v, int)]
    assert 128 in nums and 0 in nums


def test_s7_case3_wrapdelta_in_summary(big_wrapped_datasize, tmp_path):
    """§7 case 3 (summary half): the wrapped negative dataSize reaches
    summary.json together with its wrap delta vs Σsizes — exactly −2³² here.
    Manifest-level paths only: this fixture is NEVER full-extracted."""
    info = big_wrapped_datasize
    out = tmp_path / "out"
    proc = run_harvest(out, [info.path], ["--manifest-only"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    s = read_summary(out, "wrapped")
    keys = collect_keys(s)
    assert any("data_size_field_i32" in k for k in keys)
    assert any("wrap_delta_vs_sum_sizes" in k for k in keys)
    nums = [v for v in leaves(s) if isinstance(v, int) and abs(v) > 1000]
    assert info.data_size_stored in nums, "negative stored dataSize recorded"
    assert -U32 in nums, "wrap delta (stored − Σsizes) recorded"


def test_data_size_override_wrapped_field_unit(tmp_path):
    """Arbiter L5/m1 synergy unit: a lying dataSize FIELD (negative i32) on a
    tiny pak pins the wrap arithmetic without the 2 GB session fixture —
    field recorded verbatim, masked unsigned kept as provenance only, and the
    delta is UNMASKED: exactly field − Σ (the m1 fix), here a nonzero −12537."""
    stored = -12345
    info = write_pak(tmp_path / "ovr.pak",
                     D("", F("a.bin", "A" * 128), F("b.bin", "B" * 64)),
                     data_size_override=stored)
    assert info.data_size_stored == stored and info.total == 192
    r = roundtrip(info.path, info)
    assert r.data_size == stored

    out = tmp_path / "out"
    proc = run_harvest(out, [info.path])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    s = read_summary(out, "ovr")
    assert s["data_size_field_i32"] == stored
    assert s["data_size_stored_unsigned"] == stored & 0xFFFFFFFF
    assert s["wrap_delta_vs_sum_sizes"] == stored - info.total
    assert s["sum_entry_bytes"] == info.total


def test_s7_case13_manifest_offset_exact_above_2pow32(big_above_2pow32, tmp_path):
    """§7 case 13 (manifest half): the >2³² position keeps exact integer
    fidelity through manifest emission — never float, never truncated."""
    info = big_above_2pow32
    out = tmp_path / "out"
    proc = run_harvest(out, [info.path], ["--manifest-only"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    man = {m["path"]: m for m in read_manifest(out, "hi32")}
    hi = man["/high.bin"]
    assert type(hi["offset"]) is int
    assert hi["offset"] == U32
    assert hi["flag"] == 2 and hi["size"] == 164
    assert sum(m["size"] for m in man.values()) == info.total


def test_s7_case11_media_hook_catalogue_only(tmp_path):
    """§7 case 11 (+§4.2): media-named entries are catalogued, not extracted —
    correct size/offset/hash on media:true rows, no payload file, identical
    rows re-emitted on the second run, counted once per run, exempt from
    verify/reuse accounting."""
    info = write_pak(tmp_path / "media.pak",
                     D("", F("audio/snd.wem", "MEDIAHOOKPAYLOAD"),
                       F("video/clip.bik", "not-actually-bik"),
                       F("normal.bin", "N" * 32)))
    out = tmp_path / "out"

    proc = run_harvest(out, [info.path])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    man1 = read_manifest(out, "media")
    s1 = read_summary(out, "media")
    media_rows = [m for m in man1 if m["media"]]
    assert {m["path"] for m in media_rows} == {"/audio/snd.wem", "/video/clip.bik"}
    for m in media_rows:
        rec = info.by_path[m["path"]]
        assert m["size"] == rec.size and m["offset"] == rec.offset
        assert m["hash"] == f"{rec.adler:08x}"
        assert not (out / "media" / m["path"].lstrip("/")).exists(), \
            "catalogue-only: no payload file"
    assert s1["counts"]["media"] == 2
    assert s1["counts"]["extracted"] == 1  # normal.bin only

    proc2 = run_harvest(out, [info.path])
    assert proc2.returncode == 0, proc2.stdout + proc2.stderr
    man2 = read_manifest(out, "media")
    s2 = read_summary(out, "media")
    assert man2 == man1, "media rows re-emitted identically"
    assert s2["counts"]["media"] == 2  # counted once per run
    assert s2["counts"]["extracted"] == 0
    assert s2["counts"]["skipped_reuse"] == 1  # media exempt from reuse counting


def test_av_container_magic_under_benign_name_is_carve_out(tmp_path):
    """Arbiter M4t — the MAGIC half of the §4.2 carve-out: AV-container magics
    under benign, non-media-extension names are catalogued (media:true),
    never extracted, and loudly warned by name on stderr; payloads whose
    heads fail the validated MPEG/container checks stay normal extracted
    rows. Bare FF-Fx sync alone is deliberately NOT pinned (that branch was
    validated away); the UTF-16LE-BOM casualty class is."""
    rows = [
        # (name, head bytes, is_media)
        ("audio_ogg.dat", b"OggS" + b"\x00" * 12, True),
        ("audio_flac.dat", b"fLaC" + b"\x00" * 12, True),
        ("riff_wave.bin", b"RIFF\x24\x00\x00\x00WAVEfmt ", True),
        ("video_mp4.dat", b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00", True),
        ("matroska.bin", b"\x1a\x45\xdf\xa3B\x82\x88\x40matro", True),
        ("mpeg_frame.dat", b"\xff\xfb\x90\x10" + b"\x00" * 12, True),
        # negatives — extracted normally:
        ("utf16_doc.json", b'\xff\xfe<\x00?\x00x\x00m\x00l\x00', False),
        ("ff_sync_junk.bin", b"\xff\xe0\xff\xff\xff\xff\xff\xff", False),
    ]
    info = write_pak(tmp_path / "avmagic.pak",
                     D("", *[F(n, d) for n, d, _ in rows]))
    out = tmp_path / "out"
    proc = run_harvest(out, [info.path])
    assert proc.returncode == 0, proc.stdout + proc.stderr

    man = {m["path"]: m for m in read_manifest(out, "avmagic")}
    n_media = 0
    for name, data, is_media in rows:
        m = man[f"/{name}"]
        assert m["media"] is is_media, name
        target = out / "avmagic" / name
        if is_media:
            n_media += 1
            assert not target.exists(), f"{name}: catalogue-only row wrote a file"
            assert f"/{name}" in proc.stderr and "[media-hook]" in proc.stderr, \
                f"{name}: magic-driven media row must be warned by name"
        else:
            assert target.exists() and target.read_bytes() == data

    s = read_summary(out, "avmagic")
    assert s["counts"]["media"] == n_media
    assert s["counts"]["extracted"] == len(rows) - n_media


def test_s7_case12_long_path_target(tmp_path):
    """§7 case 12 (+§4.4): a >260-char extracted path either writes cleanly
    under the long-path policy or exits 2 from that policy's preflight —
    never a raw OSError traceback and never a silent truncation."""
    comp = "L" * 100
    info = write_pak(tmp_path / "long.pak",
                     D("", D(comp, D(comp, D(comp, F("leaf.bin", "P" * 64))))))
    projected = len(str(tmp_path / "out" / "long")) + 1 + 3 * (len(comp) + 1) \
        + len("leaf.bin")
    assert projected > 260, f"fixture path too short ({projected})"

    out = tmp_path / "out"
    proc = run_harvest(out, [info.path])
    combined = proc.stdout + proc.stderr
    target = out / "long" / comp / comp / comp / "leaf.bin"
    if proc.returncode == 0:
        assert target.exists() and target.read_bytes() == b"P" * 64
    else:
        assert proc.returncode == 2, combined  # policy preflight refused, loudly
        assert "Traceback" not in proc.stderr
        assert not target.exists()


def test_harvest_report_artifact(tmp_path):
    """§6 preamble: every run writes extracted/harvest-report.json carrying
    per-pak RNG seeds, sample paths, adler results, wall seconds, throughput."""
    info = write_pak(tmp_path / "rep.pak",
                     D("", F("r.bin", "R" * 128), F("s.bin", "S" * 64)))
    out = tmp_path / "out"
    proc = run_harvest(out, [info.path])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    rep = find_report(out)
    assert rep is not None, "acceptance report artifact missing"
    j = json.loads(rep.read_text(encoding="utf-8"))
    keys = collect_keys(j)
    for needle in ("seed", "sample", "adler", "wall", "throughput"):
        assert any(needle in k for k in keys), f"report lacks a {needle!r} key"
    seeds = [v for k, v in _walk_items(j)
             if "seed" in str(k).lower() and isinstance(v, int)]
    assert seeds, "an integer RNG seed must be recorded for reproducibility"


def test_reconcile_vs_list_flag2_offsets_ignored(tmp_path):
    """Brief: reconciliation vs CRLF scratch TSVs — --list output reconciles
    under the contract INCLUDING when the TSV's flag-2 offset cells hold
    recon-style synthetic garbage. Offsets are NEVER compared for flag-2."""
    info = write_pak(tmp_path / "rec.pak",
                     D("", F("f0.bin", "F" * 16), F("f2.bin", "G" * 24, flag=2)))
    out = tmp_path / "out"
    proc = run_harvest(out, [info.path], ["--list"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    rows = [normalize_list_line(ln) for ln in proc.stdout.splitlines() if ln.strip()]

    tsv_true = to_tsv(info)  # CRLF, headerless — the scratch shape
    assert reconcile(tsv_true, rows) == []

    tsv_garbage = to_tsv(info, flag2_offsets=lambda i: i * 2**28)
    assert tsv_garbage != tsv_true
    assert reconcile(tsv_garbage, rows) == [], \
        "flag-2 offsets must never be compared"


def test_reconcile_full_run_manifest_vs_scratch_tsv(tmp_path):
    """Full-run manifests reconcile against the scratch-shaped TSV on
    (path,size,adler); flag-0 offsets additionally match their tiled truth."""
    info = write_pak(tmp_path / "full.pak",
                     D("", D("d", F("x.bin", "X" * 8)),
                       F("y.bin", "Y" * 48, flag=2), F("z.bin", "Z" * 16)))
    out = tmp_path / "out"
    proc = run_harvest(out, [info.path])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    man = read_manifest(out, "full")
    assert reconcile(to_tsv(info), man) == []

    tsv_rows = {r[0]: r for r in parse_tsv(to_tsv(info))}
    for m in man:
        if m["flag"] == 0:
            assert int(tsv_rows[m["path"]][2]) == m["offset"]


def test_no_strict_downgrades_invariants_to_warnings(tmp_path):
    """§3.1: --no-strict downgrades §2.2 invariant violations (index slack) to
    warnings; integrity failures stay non-zero (pinned separately by the
    case-8 tests, which run in default strict mode → 3)."""
    info = write_pak(tmp_path / "slack.pak", D("", F("a.bin", "A" * 16)),
                     trailing_index_junk=b"\xde\xad\xbe\xef")
    out = tmp_path / "out"
    strict = run_harvest(out, [info.path])
    assert strict.returncode == 3, strict.stdout + strict.stderr

    lenient = run_harvest(tmp_path / "out_ns", [info.path], ["--no-strict"])
    combined = lenient.stdout + lenient.stderr
    assert "slack" in combined.lower(), "downgraded violations still warn"
    assert lenient.returncode == 0, combined


# ==========================================================================
# layer 2.5 — in-process seams: §4.4/§5 gates via monkeypatched module
# globals (arbiter M2t: NO test-only CLI flags — import harvest instead)
# ==========================================================================

@pytest.fixture(scope="session")
def harvest_mod():
    """Import pipeline/harvest.py as a module for in-process gate tests."""
    require_harvest()
    if str(PIPELINE) not in sys.path:
        sys.path.insert(0, str(PIPELINE))
    import harvest
    return harvest


class _FakeClock:
    """perf_counter stand-in with a scripted reading list; an unscripted third
    call raises StopIteration instead of silently passing."""

    def __init__(self, readings):
        self._it = iter(readings)

    def __call__(self):
        return next(self._it)


def test_budget_projection_arithmetic(harvest_mod, tmp_path, monkeypatch,
                                      capsys):
    """Arbiter M2t: the measured projection is honest arithmetic — the pak
    file is its own calibration source (CALIBRATION_BYTES == its size) and a
    scripted clock supplies the elapsed time; projected must equal
    Σwork × elapsed / calibrated bytes, printed with the cap."""
    hm = harvest_mod
    info = write_pak(tmp_path / "proj.pak", D("", F("p.bin", b"P" * 4096)))
    pak_bytes = info.path.stat().st_size
    work = {str(info.path): 800_000}  # pretend 800 KB of payload to move
    monkeypatch.setattr(hm, "CALIBRATION_BYTES", pak_bytes)
    monkeypatch.setattr(hm, "WALL_BUDGET_SECONDS", 24 * 3600)  # no breach
    monkeypatch.setattr(hm.time, "perf_counter", _FakeClock([0.0, 10.0]))

    hm.preflight_gates(work, tmp_path / "out")  # must NOT raise

    expected_min = work[str(info.path)] * 10.0 / pak_bytes / 60
    out = capsys.readouterr().out
    assert f"[preflight] measured projection: ~{expected_min:.1f} min " \
           f"(cap {24 * 3600 // 60} min)" in out


def test_budget_breach_stops_and_reports_rc2(harvest_mod, tmp_path,
                                             monkeypatch, capsys):
    """Arbiter M2t: a projection over the wall cap stops-and-reports BEFORE
    any payload byte moves — rc 2 with the §5 tripwire named."""
    hm = harvest_mod
    info = write_pak(tmp_path / "slow.pak", D("", F("s.bin", b"S" * 1024)))
    pak_bytes = info.path.stat().st_size
    monkeypatch.setattr(hm, "CALIBRATION_BYTES", pak_bytes)
    monkeypatch.setattr(hm, "WALL_BUDGET_SECONDS", 60)  # 1-minute cap
    # Scripted 1000 s over the whole ~1 KB file ⇒ rate ≈ 1 B/s; the run's real
    # Σwork (1024 B of payload) then projects to ≈1000× honest seconds.
    monkeypatch.setattr(hm.time, "perf_counter", _FakeClock([0.0, 1000.0]))

    rc = hm.main(["--pak", str(info.path), "--out", str(tmp_path / "out")])

    assert rc == 2, "budget breach must exit 2"
    err = capsys.readouterr().err
    assert "STOP AND REPORT" in err and "spec-harvest §5" in err, err
    assert "preflight projects" in err, "the measured projection must be cited"
    assert not (tmp_path / "out" / "slow.manifest.jsonl").exists(), \
        "breach must stop before Phase B writes anything"


def test_space_gate_exits2_when_margin_unmeetable(harvest_mod, tmp_path,
                                                  monkeypatch, capsys):
    """Arbiter M2t: the §4.4 space gate refuses with rc 2 when required bytes
    exceed free space — exercised by inflating FREE_SPACE_MARGIN, no knob."""
    hm = harvest_mod
    info = write_pak(tmp_path / "fat.pak", D("", F("f.bin", b"F" * 2048)))
    monkeypatch.setattr(hm, "FREE_SPACE_MARGIN", 10 ** 12)

    rc = hm.main(["--pak", str(info.path), "--out", str(tmp_path / "out")])

    assert rc == 2, "space gate must exit 2"
    err = capsys.readouterr().err
    assert "insufficient free space" in err, err
    assert "free on that volume" in err, err
    assert not (tmp_path / "out" / "fat").exists(), \
        "refusal happens before any extraction"


# ==========================================================================
# layer 3 — integration smoke (marked; --run-integration; needs the client)
# ==========================================================================

RES_EXPECT_FILES = 936
RES_EXPECT_DIRS = 127
RES_EXPECT_BYTES = 767_068_478
RES_DATA_CDB_ADLER = 0xD6BC3D60
RES_LANDMARK = "/content/systemic/maps/sealords/sealordMap10Placeholder.png"


def _integration_prereqs():
    missing = []
    if not RES_PAK.exists():
        missing.append(f"client pak {RES_PAK}")
    if not RES_TSV.exists():
        missing.append(f"scratch TSV {RES_TSV}")
    for name in ("extract-res.pak-sealordMap10Placeholder.png",
                 "extract-res.pak-data.cdb"):  # landmark tests read both
        if not (VERIFY / name).exists():
            missing.append(f"_verify landmark {VERIFY / name}")
    return missing


@pytest.fixture(scope="module")
def res_harvest(tmp_path_factory):
    """One heavy shared run: res.pak end-to-end (smallest pak: 767 MB, 936
    entries). Skipped unless --run-integration AND prerequisites exist."""
    missing = _integration_prereqs()
    if missing:
        pytest.skip("integration prerequisites absent: " + "; ".join(missing))
    require_harvest()
    out = tmp_path_factory.mktemp("res-integration")
    proc = run_harvest(out, [RES_PAK], timeout=1800)
    if proc.returncode != 0:
        pytest.fail(f"res.pak harvest failed rc={proc.returncode}: "
                    f"{proc.stdout[-1500:]} {proc.stderr[-1500:]}")
    return out, proc


@pytest.mark.integration
def test_integration_res_counts_totals_idempotency(res_harvest):
    """§7 smoke + §6 criteria 1/2/7: counts 936/127, Σbytes 767,068,478,
    delta-0 span (implied by a strict rc 0), and the immediate-second-run
    idempotency proof (extracted=0, skipped_reuse=936)."""
    out, _ = res_harvest
    man = read_manifest(out, "res")
    assert len(man) == RES_EXPECT_FILES
    assert sum(m["size"] for m in man) == RES_EXPECT_BYTES
    s = read_summary(out, "res")
    assert s["counts"]["files"] == RES_EXPECT_FILES
    assert s["counts"]["dirs"] == RES_EXPECT_DIRS

    proc2 = run_harvest(out, [RES_PAK], timeout=900)
    assert proc2.returncode == 0, proc2.stdout + proc2.stderr
    s2 = read_summary(out, "res")
    assert s2["counts"]["extracted"] == 0
    assert s2["counts"]["skipped_reuse"] == RES_EXPECT_FILES


@pytest.mark.integration
def test_integration_res_seeded_samples_and_landmarks(res_harvest):
    """§6 criterion 3 + §7 smoke landmarks: seeded-RNG 10-sample adler triple-
    match (disk == manifest == scratch col 5), sealord placeholder
    byte-identical to the _verify artifact, data.cdb adler d6bc3d60 MATCH."""
    out, _ = res_harvest
    rep = find_report(out)
    assert rep is not None
    j = json.loads(rep.read_text(encoding="utf-8"))
    seeds = [v for k, v in _walk_items(j)
             if "seed" in str(k).lower() and isinstance(v, int)]
    assert seeds, "per-pak RNG seed must be in the acceptance report"
    seed = seeds[0]

    man = read_manifest(out, "res")
    rng = random.Random(seed)
    sample = rng.sample(man, min(10, len(man)))
    scratch = {r[0]: r for r in parse_tsv(RES_TSV.read_text(encoding="utf-8"))}
    assert len(scratch) == RES_EXPECT_FILES
    for m in sample:
        disk = (out / "res" / m["path"].lstrip("/")).read_bytes()
        assert zlib.adler32(disk) & 0xFFFFFFFF == int(m["hash"], 16)
        assert int(scratch[m["path"]][4], 16) == int(m["hash"], 16)  # TSV col 5

    landmark = out / "res" / RES_LANDMARK.lstrip("/")
    assert landmark.read_bytes() == \
        (VERIFY / "extract-res.pak-sealordMap10Placeholder.png").read_bytes()

    cdb = (out / "res" / "data.cdb").read_bytes()
    assert zlib.adler32(cdb) & 0xFFFFFFFF == RES_DATA_CDB_ADLER
    assert cdb == (VERIFY / "extract-res.pak-data.cdb").read_bytes()


@pytest.mark.integration
def test_integration_res_scratch_reconciliation(res_harvest):
    """§0/§1: harvested res.pak reconciles EXACTLY against the real CRLF
    scratch TSV on (path,size,adler) across all 936 rows — and since res.pak
    is all flag-0, offsets are additionally compared (they tile)."""
    out, _ = res_harvest
    man = read_manifest(out, "res")
    # read_bytes → decode: text-mode read would translate CRLF away before
    # the assertion could see it
    tsv_text = RES_TSV.read_bytes().decode("utf-8")
    assert "\r\n" in tsv_text  # CRLF confirmed live
    bad = reconcile(tsv_text, man)
    assert bad == [], f"{len(bad)} mismatches, first: {bad[:3]}"

    tsv_rows = {r[0]: r for r in parse_tsv(tsv_text)}
    for m in man:
        assert m["flag"] == 0  # res.pak is 936+0 — every entry flag-0
        assert int(tsv_rows[m["path"]][2]) == m["offset"]
