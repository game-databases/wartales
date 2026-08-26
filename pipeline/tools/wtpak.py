#!/usr/bin/env python3
"""wtpak.py — independent Heaps.io .pak reader for the Wartales pack.

Implements exactly the semantics of the canonical engine sources
(HeapsIO/heaps hxd/fmt/pak/Reader.hx + Build.hx, fetched 2026-08-24 into
_refs/): 16-byte header, recursive directory index, Adler32 checksums,
absolute data offset = dataPosition + headerSize.

Read-only by default. Used both as the pack's seed pipeline tool and as
the cross-check against third-party extractors.

Usage:
  python wtpak.py list    <pak>                 # header + full index walk + stats
  python wtpak.py entries <pak> [prefix]         # print "size<TAB>path" lines
  python wtpak.py extract <pak> <path> <outfile> [--verify]
"""
import struct
import sys
import zlib

# Survive downstream `| head` closing the pipe (Windows raises OSError on flush).
try:
    import signal
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except (ImportError, AttributeError):
    pass


def read_header(f):
    magic = f.read(3)
    if magic != b"PAK":
        raise ValueError(f"not a PAK file (magic {magic!r})")
    version = f.read(1)[0]
    header_size, data_size = struct.unpack("<ii", f.read(8))
    return version, header_size, data_size


class Reader:
    def __init__(self, path):
        self.path = path
        self.f = open(path, "rb")
        self.version, self.header_size, self.data_size = read_header(self.f)
        self.index = self.f.read(self.header_size - 16)
        if self.index.__len__() != self.header_size - 16:
            raise ValueError("truncated index")
        self.pos = 0
        self.data_magic = self.f.read(4)  # expect b"DATA"
        self.n_files = 0
        self.n_dirs = 0

    def _u8(self):
        v = self.index[self.pos]
        self.pos += 1
        return v

    def _i32(self):
        v = struct.unpack_from("<i", self.index, self.pos)[0]
        self.pos += 4
        return v

    def _f64(self):
        v = struct.unpack_from("<d", self.index, self.pos)[0]
        self.pos += 8
        return v

    def read_entry(self):
        name_len = self._u8()
        name = self.index[self.pos:self.pos + name_len].decode("utf-8")
        self.pos += name_len
        flags = self._u8()
        if flags & 1:  # IS_DIRECTORY
            self.n_dirs += 1
            children = [self.read_entry() for _ in range(self._i32())]
            return {"name": name, "dir": True, "children": children}
        self.n_files += 1
        data_pos = self._f64() if flags & 2 else float(self._i32())
        return {
            "name": name, "dir": False,
            "pos": data_pos,          # relative to end of header
            "size": self._i32(),
            "adler": self._i32() & 0xFFFFFFFF,
        }

    def parse(self):
        root = self.read_entry()
        if self.pos != len(self.index):
            raise ValueError(f"index slack: {len(self.index) - self.pos} unread bytes")
        return root

    def iter_files(self, node=None, prefix=""):
        if node is None:
            node = self.root
        p = f"{prefix}{node['name']}"
        if node["dir"]:
            for c in node["children"]:
                yield from self.iter_files(c, f"{p}/" if p else "")
        else:
            yield p, node

    def read_file_bytes(self, entry):
        self.f.seek(int(entry["pos"]) + self.header_size)
        return self.f.read(entry["size"])


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def cmd_list(pak_path):
    r = Reader(pak_path)
    r.root = r.parse()
    total = 0
    exts = {}
    biggest = []
    for path, e in r.iter_files():
        total += e["size"]
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else "(none)"
        c = exts.get(ext, [0, 0])
        c[0] += 1
        c[1] += e["size"]
        exts[ext] = c
        biggest.append((e["size"], path))
    covered = sum(c[1] for c in exts.values())
    print(f"{pak_path}")
    print(f"  version={r.version} headerSize={r.header_size:,} dataSizeField={r.data_size:,} "
          f"dataMagic={'OK' if r.data_magic == b'DATA' else 'MISSING (' + repr(r.data_magic) + ')'}")
    print(f"  files={r.n_files:,} dirs={r.n_dirs:,} sum(dataSize)={human(total)} ({total:,} B)")
    print(f"  dataSizeField-vs-sum delta={r.data_size - total:+,} B")
    print(f"  extensions ({len(exts)}):")
    for ext, (cnt, sz) in sorted(exts.items(), key=lambda kv: -kv[1][1]):
        print(f"    {ext:<12} {cnt:>8,} files  {human(sz):>12}  ({sz * 100.0 / max(covered, 1):5.2f}% of bytes)")
    biggest.sort(reverse=True)
    print(f"  largest entries:")
    for sz, p in biggest[:5]:
        print(f"    {human(sz):>12}  {p}")


def cmd_entries(pak_path, prefix=""):
    r = Reader(pak_path)
    r.root = r.parse()
    for path, e in r.iter_files():
        if not prefix or path.startswith(prefix):
            print(f"{e['size']}\t{path}")


def cmd_extract(pak_path, member, outfile, verify=False):
    r = Reader(pak_path)
    r.root = r.parse()
    for path, e in r.iter_files():
        if path == member:
            data = r.read_file_bytes(e)
            break
    else:
        raise SystemExit(f"entry not found: {member}")
    with open(outfile, "wb") as g:
        g.write(data)
    adler = zlib.adler32(data) & 0xFFFFFFFF
    ok = adler == e["adler"]
    print(f"extracted {member}: {len(data):,} B -> {outfile}")
    print(f"adler32 stored={e['adler']:08x} computed={adler:08x} -> {'MATCH' if ok else 'MISMATCH'}")
    if verify and not ok:
        raise SystemExit(1)


def main(argv):
    if len(argv) < 3:
        raise SystemExit(__doc__)
    cmd = argv[1]
    if cmd == "list":
        cmd_list(argv[2])
    elif cmd == "entries":
        cmd_entries(argv[2], argv[3] if len(argv) > 3 else "")
    elif cmd == "extract":
        cmd_extract(argv[2], argv[3], argv[4], "--verify" in argv)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
