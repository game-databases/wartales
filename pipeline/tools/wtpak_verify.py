#!/usr/bin/env python3
"""wtpak_verify.py — reconcile wtpak.py listings against recon TSVs + prove extraction.

R2 toolchain scout artifact. For each pak:
  1. parse index with wtpak.Reader (canonical Heaps semantics),
  2. compare every file entry (path, size, adler32) against the recon scout's TSV,
  3. extract ONE representative entry, check magic bytes + recomputed adler32.

Writes nothing outside wartales/pipeline/tools/_verify/.

Usage: python wtpak_verify.py <game-dir> <scratch-dir>
"""
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wtpak import Reader

MAGICS = {
    "png": (b"\x89PNG\r\n\x1a\n", "PNG image"),
    "jpg": (b"\xff\xd8", "JPEG image"),
    "jpeg": (b"\xff\xd8", "JPEG image"),
    "dds": (b"DDS ", "DDS texture"),
}


def reconcile(pak_path, tsv_path):
    r = Reader(pak_path)
    r.root = r.parse()
    mine = {p: (e["size"], e["adler"]) for p, e in r.iter_files()}
    n_tsv = 0
    mismatches = []
    with open(tsv_path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            path, _flag, _pos, size, adler_hex = line.split("\t")
            path = path.lstrip("/")
            n_tsv += 1
            m = mine.get(path)
            if m is None:
                mismatches.append(("MISSING_IN_WTPAK", path))
            elif m[0] != int(size):
                mismatches.append(("SIZE_DIFF", path, m[0], size))
            elif m[1] != int(adler_hex, 16):
                mismatches.append(("ADLER_DIFF", path, f"{m[1]:08x}", adler_hex))
    extra = sorted(set(mine) - {l.split("\t")[0].lstrip("/")
                                for l in open(tsv_path, encoding="utf-8") if l.strip()})
    return r, mine, n_tsv, mismatches, extra


def pick(mine, ext):
    for p in sorted(mine):
        if p.lower().endswith("." + ext):
            return p
    return None


def extract(r, mine, pak_path, member, outdir):
    e = next(e for p, e in Reader.iter_files(r) if p == member)
    data = r.read_file_bytes(e)
    out = os.path.join(outdir, f"extract-{os.path.basename(pak_path)}-{os.path.basename(member)}")
    with open(out, "wb") as g:
        g.write(data)
    ext = member.rsplit(".", 1)[-1].lower()
    magic, label = MAGICS.get(ext, (None, ext))
    got = data[: len(magic)] if magic else data[:8]
    ok_magic = got == magic if magic else None
    adler = zlib.adler32(data) & 0xFFFFFFFF
    return {
        "member": member,
        "size": len(data),
        "expected_magic": magic.hex() if magic else "-",
        "got": got.hex(),
        "magic": "MATCH" if ok_magic else ("MISMATCH" if magic else "n/a"),
        "label": label,
        "adler_stored": f"{e['adler']:08x}",
        "adler_computed": f"{adler:08x}",
        "adler": "MATCH" if adler == e["adler"] else "MISMATCH",
        "outfile": out,
    }


def peek(r, e, n=6):
    r.f.seek(int(e["pos"]) + r.header_size)
    return r.f.read(n)


def magic_name(b):
    if b.startswith(b"\x89PNG"):
        return "png"
    if b.startswith(b"\xff\xd8"):
        return "jpeg"
    if b.startswith(b"DDS "):
        return "dds"
    if b.startswith(b"PK\x03\x04"):
        return "zip"
    if b.startswith(b"\x1f\x8b"):
        return "gzip"
    if b.startswith(b"HMD"):
        return "hmd"
    if b.startswith(b"{"):
        return "json"
    if b.startswith(b"<"):
        return "xml"
    return b.hex() or "empty"


def census(r, mine, exts):
    """Per-extension true-format distribution via 6-byte peeks (cheap, whole-ext coverage)."""
    from collections import Counter
    buckets = {e: Counter() for e in exts}
    for p, e in Reader.iter_files(r):
        root_ext = p.rsplit(".", 1)[-1].lower()
        if root_ext in buckets:
            buckets[root_ext][magic_name(peek(r, e))] += 1
    for ext, c in buckets.items():
        if c:
            dist = ", ".join(f"{k}:{v:,}" for k, v in c.most_common())
            print(f"  census .{ext:<5} -> {dist}")


def main():
    game, scratch, outdir = sys.argv[1], sys.argv[2], os.path.join(os.path.dirname(os.path.abspath(__file__)), "_verify")
    os.makedirs(outdir, exist_ok=True)
    plan = {
        "res": ("res-pak-entries.tsv", [("png", 1), ("cdb", 0)],
                ("dds", "jpg", "png", "prefab", "cdb")),
        "assets": ("assets-pak-entries.tsv", [("png", 1)], ("png", "jpg", "tx", "envs", "fbx")),
        "content": ("content-pak-entries.tsv", [("dds", 1)], ("dds", "png", "bin", "hmd", "l3d", "dat")),
        "map": ("map-pak-entries.tsv", [("dds", 1)], ("dds", "raw")),
    }
    for name, (tsv, picks, cexts) in plan.items():
        pak = os.path.join(game, name + ".pak")
        r, mine, n_tsv, bad, extra = reconcile(pak, os.path.join(scratch, tsv))
        print(f"=== {name}.pak ===")
        print(f"wtpak files={len(mine):,}  tsv rows={n_tsv:,}  mismatches={len(bad)}  wtpak-only={len(extra)}")
        census(r, mine, cexts)
        for b in bad[:10]:
            print("  MISMATCH", b)
        for p in extra[:10]:
            print("  EXTRA", p)
        for ext, nth in picks:
            cands = sorted(p for p in mine if p.lower().endswith("." + ext))
            if not cands:
                continue
            member = cands[min(nth, len(cands) - 1)]
            res = extract(r, mine, pak, member, outdir)
            print(f"  extract {res['member']} ({res['size']:,} B) magic[{res['label']}] "
                  f"expected={res['expected_magic']} got={res['got']} -> {res['magic']} | "
                  f"adler {res['adler_stored']} vs {res['adler_computed']} -> {res['adler']}")


if __name__ == "__main__":
    main()
