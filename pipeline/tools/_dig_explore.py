#!/usr/bin/env python3
"""_dig_explore.py — section-boundary exploration for the Wartales HLB v4 fork.

Anchors the unknown layout empirically:
  1. locate the debug-paths blob (hxd/App.hx...) and fit the canonical
     strings-block signature (UINDEX count + i32 size + blob + UINDEX lens)
  2. score candidate offsets as "globals region" (nglobals consecutive
     UINDEXes all within [0,ntypes))
  3. greedy UINDEX value histograms at candidate boundaries
"""
import struct, sys, collections

PATH = "A:/SteamLibrary/steamapps/common/Wartales/hlboot.dat"
data = open(PATH, "rb").read()
N = len(data)


def uindex(b, p):
    x = b[p]
    p += 1
    if x & 0x80 == 0:
        return x & 0x7F, p
    if x & 0x40 == 0:
        c = b[p]; p += 1
        v = ((x & 31) << 8) | c
        return (-v if x & 0x20 else v), p
    c, d, e = b[p], b[p + 1], b[p + 2]; p += 3
    v = ((x & 31) << 24) | (c << 16) | (d << 8) | e
    return (-v if x & 0x20 else v), p


# --- header ---
assert data[:3] == b"HLB"
ver = data[3]
p = 4


def ui():
    global p
    v, p = uindex(data, p)
    return v


flags = ui()
nints, nfloats, nstrings = ui(), ui(), ui()
ntypes, nglobals, nnatives, nfunctions = ui(), ui(), ui(), ui()
nconstants = ui()
entrypoint = ui()
print(f"header: v{ver} flags={flags:#x} ints={nints} floats={nfloats} strs={nstrings} "
      f"types={ntypes} globals={nglobals} natives={nnatives} funcs={nfunctions} "
      f"consts={nconstants} entry={entrypoint}")
p += 4 * nints + 8 * nfloats
ssize = struct.unpack_from("<i", data, p)[0]
p += 4
sblob = p
p += ssize
strs = []
q = sblob
for _ in range(nstrings):
    sz, p = uindex(data, p)
    strs.append(data[q:q + sz])
    q += sz + 1
strs = [s.decode("utf-8", "replace") for s in strs]
print(f"strings ok: {len(strs)}, region end p={p:#x}")
types_start = p

# --- 1. debug blob anchor ---
anchor = data.find(b"hxd/App.hx\x00")
print(f"\n[hxd/App.hx] first at {anchor:#x}; occurrences={data.count(b'hxd/App.hx')}")
# walk backwards: is there an i32 size ending exactly at anchor?
for back in range(1, 6):
    cand_size = struct.unpack_from("<i", data, anchor - back)[0] if anchor - back >= 0 else 0
    pass
blob_end = anchor
while blob_end < N and data[blob_end] != 0:
    blob_end += 1
blob_end += 1
# try to fit a full strings block: count prefix then i32 size then blob
# search window before anchor for (count, size) such that blob spans [.., some end]
print("bytes before anchor:", data[anchor - 24:anchor].hex(" "))
# find the extent of a run of NUL-terminated printable paths starting near anchor
start_guess = anchor
end = start_guess
n_paths = 0
while end < N:
    nxt = data.find(b"\x00", end)
    if nxt < 0 or nxt - end > 300 or not all(32 <= c < 127 for c in data[end:nxt]):
        break
    n_paths += 1
    end = nxt + 1
print(f"run of printable NUL-terminated strings from {start_guess:#x}: {n_paths} entries, ends {end:#x}")
print("bytes after run:", data[end:end + 24].hex(" "))
size_field = struct.unpack_from("<i", data, start_guess - 4)[0]
print(f"i32 right before run = {size_field} (run len guess {end - start_guess})")
cnt_field, cp = uindex(data, start_guess - 8) if start_guess >= 8 else (None, None)
print(f"UINDEX before that = {cnt_field}")

# --- 2. globals-region scoring: from offset o, decode nglobals UINDEXes, all in [0,ntypes)? ---
def globals_fit(o, limit=None):
    q = o
    cnt = nglobals
    mx = 0
    for _ in range(cnt):
        if q >= N:
            return None
        try:
            v, q = uindex(data, q)
        except IndexError:
            return None
        if not (0 <= v < ntypes):
            return None
        if v > mx:
            mx = v
    return q, mx

print("\n[globals-fit scan] testing candidate offsets:")
cands = {
    "after_strings(types_start)": types_start,
}
if size_field == (end - start_guess):
    cands["after_debug_run"] = end
for name, o in cands.items():
    r = globals_fit(o)
    print(f"  {name} @{o:#x}: {'FITS -> ends %d (%#x), max tref %d' % r if r else 'no'}")

# sliding scan around the debug-run end and types_start +- small window
print("\n[sliding scan] offsets whose next nglobals UINDEXes are ALL valid type refs:")
hits = []
lo = max(0, types_start - 64)
hi = min(N - 16, (end + 4096) if end else types_start + 65536)
for o in range(lo, hi):
    r = globals_fit(o, )
    if r:
        hits.append((o, r[0]))
        if len(hits) > 20:
            break
for h in hits[:20]:
    print(f"  start {h[0]:#x} -> globals end {h[1]:#x}")

# --- 3. greedy UINDEX histogram right after strings ---
print("\n[greedy UINDEX values after strings, first 60]:")
q = types_start
vals = []
for _ in range(60):
    v, q = uindex(data, q)
    vals.append(v)
print(vals)
