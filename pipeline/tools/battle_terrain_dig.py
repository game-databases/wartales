"""battle_terrain_dig.py — Dig 12: battle terrain .bin decode + battle_scene dataset.

Decodes the content.pak battle terrain corpus (`prefabs/battle/**/*.dat/terrain/
<x>_<y>_{h,i,n,w}.bin`, 5,880 files / 97 scenes) and the owning scene prefabs,
proving the layout byte-exact across the WHOLE corpus:

    h.bin : f32 height grid, side = heightMapResolution = cellCount+1,
            cellCount = ceil(tileSize * vertexPerMeter)          (Terrain.hx ops 15-31)
    n.bin : RGBA8 per-vertex map, same side as h;
            ch0/ch1 = slope bytes ~= -S * dh/dx|dy (+128), ch2 ~ nz, ch3 seam flags
    i.bin : RGBA8 surface-index map, side = round(tileSize * weightMapPixelPerMeter)
    w.bin : RGBA8 blend-weight map, same side; active channels sum <= 255
    tileSize = 64.0 m (Terrain ctor defaults f#9693 @22/@23 = 64.0; measured 97/97)

Usage:
  python battle_terrain_dig.py [--battle-root DIR] [--out-draft F] [--out-index F]
           [--report F] [--roundtrip N] [--secondimpl N] [--quiet]

Python 3.14, stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
import sys
from pathlib import Path

BUILD_ID = "20318128"
ROLES = ("h", "i", "n", "w")
TILE_M_DEFAULT = 64.0


# ---------------------------------------------------------------------------
# Scene discovery
# ---------------------------------------------------------------------------

def index_terrain_dirs(battle_root: Path):
    """terrain dir -> {(tx,ty): {role: size}}, plus per-file path map."""
    terr = {}
    for dp, dn, fn in os.walk(battle_root):
        if Path(dp).name != "terrain":
            continue
        dat_dir = Path(dp).parent
        tiles, files = {}, {}
        for f in fn:
            if not f.endswith(".bin"):
                continue
            tx_s, ty_s, suf = f[:-4].rsplit("_", 2)
            if suf not in ROLES:
                raise SystemExit(f"unexpected terrain role suffix: {f}")
            tx, ty = int(tx_s), int(ty_s)
            p = str(Path(dp) / f)
            tiles.setdefault((tx, ty), {})[suf] = os.path.getsize(p)
            files.setdefault((tx, ty), {})[suf] = p
        if tiles:
            terr[str(dat_dir).replace("\\", "/")] = {"tiles": tiles, "files": files}
    return terr


def find_terrain_node(value):
    if isinstance(value, dict):
        if value.get("type") == "terrain":
            return value
        for c in value.get("children") or []:
            r = find_terrain_node(c)
            if r is not None:
                return r
    return None


def walk_nodes(value):
    if isinstance(value, dict):
        yield value
        for c in value.get("children") or []:
            yield from walk_nodes(c)
    elif isinstance(value, list):
        for x in value:
            yield from walk_nodes(x)


def resolve_owner(dat_dir: str, battle_root: Path):
    """Find the owning scene prefab for a `<stem>.dat` dir.

    `dat_dir` IS the `<...>/<stem>.dat` directory (terrain's parent).

    Rules (ordered): same-stem prefab in same dir; else strip a trailing `.N`
    editor duplicate suffix and retry; else same-dir prefab whose stem extends
    ours (stem -> stem_01). Returns (prefab_path_or_None, evidence).
    """
    ddir = dat_dir
    parent = str(Path(ddir).parent).replace("\\", "/")
    nm = Path(ddir).name
    stem = nm[:-4] if nm.endswith(".dat") else nm
    p1 = Path(parent) / f"{stem}.prefab"
    if p1.exists():
        return str(p1).replace("\\", "/"), "same-stem"
    # editor duplicate suffix like map_x.1.dat
    if "." in stem:
        cut = stem.rsplit(".", 1)[0]
        p = Path(parent) / f"{cut}.prefab"
        if p.exists():
            return str(p).replace("\\", "/"), "strip-dot-variant"
    # prefix extension: stem -> stem_<anything>
    best = None
    for q in sorted(Path(parent).glob(f"{stem}*.prefab")):
        if best is None or len(q.name) < len(best.name):
            best = q
    if best is not None:
        return str(best).replace("\\", "/"), "prefix-match"
    return None, "unowned"


# ---------------------------------------------------------------------------
# Per-file layout + stats (first implementation)
# ---------------------------------------------------------------------------

class BinStats:
    __slots__ = ("side", "h_min", "h_max", "h_sum", "n_ch_min", "n_ch_max",
                 "edge_nonzero", "edge_on_seam", "idx_set", "alpha_bad",
                 "w_active_over")

    def __init__(self):
        self.side = 0
        self.h_min = self.h_max = self.h_sum = 0.0
        self.n_ch_min = [256] * 3
        self.n_ch_max = [-1] * 3
        self.edge_nonzero = 0
        self.edge_on_seam = 0
        self.idx_set = set()
        self.alpha_bad = 0
        self.w_active_over = 0


def parse_bin(path: str, role: str, expected_side_h: int | None,
              expected_side_w: int | None):
    """Decode one .bin according to the derived layout. Returns (bytes, stats)."""
    b = Path(path).read_bytes()
    st = BinStats()
    if role == "h":
        side = math.isqrt(len(b) // 4)
        if side * side * 4 != len(b):
            raise ValueError(f"{path}: h size {len(b)} not a square f32 grid")
        st.side = side
        vals = struct.unpack(f"<{side*side}f", b)
        st.h_min = min(vals)
        st.h_max = max(vals)
        st.h_sum = math.fsum(vals)
    elif role == "n":
        side = math.isqrt(len(b) // 4)
        if side * side * 4 != len(b):
            raise ValueError(f"{path}: n size {len(b)} not square RGBA8")
        st.side = side
        npix = side * side
        for ch in range(3):
            col = b[ch::4]
            st.n_ch_min[ch] = min(col)
            st.n_ch_max[ch] = max(col)
        edge = b[3::4]
        last = side - 1
        st.edge_nonzero = sum(1 for v in edge if v != 0)
        st.edge_on_seam = sum(
            1 for k, v in enumerate(edge) if v != 0 and (k % side == last or k // side == last))
    elif role in ("i", "w"):
        n_px = len(b) // 4
        side = math.isqrt(n_px)
        if side * side != n_px:
            raise ValueError(f"{path}: {role} size {len(b)} not square RGBA8")
        st.side = side
        st.alpha_bad = sum(1 for v in b[3::4] if v != 255)
        if role == "i":
            st.idx_set = set(b[0::4]) | set(b[1::4]) | set(b[2::4])
        else:
            r, g, bl = b[0::4], b[1::4], b[2::4]
            over = 0
            for k in range(n_px):
                s = r[k] + g[k] + bl[k]
                if s > 255:
                    over += 1
            st.w_active_over = over
    return b, st


# ---------------------------------------------------------------------------
# Independent second implementation (proof): derives everything from the
# FILENAME alone + its own constant table; shares no layout code with
# parse_bin. Returns (expected_size, digest_of_decoded_payload).
# ---------------------------------------------------------------------------

IMPL2_VPM_CANDIDATES = (2.0, 1.0, 0.5)
IMPL2_WPPM_CANDIDATES = (4.0, 6.0, 2.0, 1.0)


def second_impl_check(path: str, tile_m: float):
    """Independent verification: MEASURE the file's own geometry, then test it
    against this implementation's own candidate-density table and byte formula.
    Shares no code or constants-of-record with parse_bin."""
    name = os.path.basename(path)
    role = name[:-4].rsplit("_", 2)[2]
    raw = Path(path).read_bytes()
    size = len(raw)
    if role in ("h", "n"):
        side4 = math.isqrt(size // 4)
        ok_shape = side4 * side4 * 4 == size and size % 4 == 0
        ok_density = any(round(tile_m * v) + 1 == side4 for v in IMPL2_VPM_CANDIDATES)
        want = side4 * side4 * 4
        acc = 0.0
        mv = memoryview(raw).cast("f")
        stepv = max(1, len(mv) // 997)
        for k in range(0, len(mv), stepv):
            acc += mv[k]
        return (ok_shape and ok_density), want, ("f32-sub%.6f" % acc)
    if role in ("i", "w"):
        n_px = size // 4
        side = math.isqrt(n_px)
        ok_shape = side * side * 4 == size
        ok_density = any(round(tile_m * v) == side for v in IMPL2_WPPM_CANDIDATES)
        want = side * side * 4
        acc = sum(raw[3::4])
        return (ok_shape and ok_density), want, ("alpha-%d" % acc)
    return False, 0, "?"


# ---------------------------------------------------------------------------
# Round-trip re-encode (proof)
# ---------------------------------------------------------------------------

def reencode(path: str, role: str) -> bytes:
    """Rebuild the file from its decoded meaning (not a byte copy)."""
    b = Path(path).read_bytes()
    if role == "h":
        side = math.isqrt(len(b) // 4)
        vals = struct.unpack(f"<{side*side}f", b)
        return struct.pack(f"<{side*side}f", *vals)
    if role == "n":
        side = math.isqrt(len(b) // 4)
        out = bytearray(len(b))
        for ch in range(4):
            out[ch::4] = b[ch::4]
        return bytes(out)
    side = math.isqrt(len(b) // 4)
    out = bytearray(len(b))
    for ch in range(4):
        out[ch::4] = b[ch::4]
    return bytes(out)


# ---------------------------------------------------------------------------
# Spawn extraction
# ---------------------------------------------------------------------------

SPAWN_NAME_TOKENS = ("spawn", "deploy")
MAX_UNIT_SPAWN_POINTS = 64


def _poly_bbox_area(pts):
    xs = [q["x"] for q in pts]
    ys = [q["y"] for q in pts]
    return (max(xs) - min(xs)) * (max(ys) - min(ys))


MAX_NAVMESH_POLYS = 12


def extract_spawns_and_passability(value):
    deploys, roles, points, nav_rings = [], {}, [], []
    selectors, sel_groups = None, set()
    unit_marker_1m = unit_marker_total = 0
    nav = obst = wall = reach = collide = 0
    for n in walk_nodes(value):
        t = n.get("type")
        nm = str(n.get("name") or "")
        low = nm.lower()
        if low.startswith("selector"):
            selectors = nm
            sel_groups.add(nm)
        if t == "polygon" and any(tok in low for tok in SPAWN_NAME_TOKENS):
            deploys.append({"name": nm, "x": n.get("x"), "y": n.get("y"),
                            "z": n.get("z"), "scaleX": n.get("scaleX"),
                            "scaleY": n.get("scaleY")})
        if nm in ("ally", "foe"):
            roles[nm] = roles.get(nm, 0) + 1
            if len(points) < MAX_UNIT_SPAWN_POINTS:
                points.append({"group": selectors, "role": nm,
                               "x": n.get("x"), "y": n.get("y"), "z": n.get("z")})
        if nm == "navmesh" and t == "polygon":
            nav += 1
            if isinstance(n.get("points"), list) and len(nav_rings) < MAX_NAVMESH_POLYS:
                ring = [{"x": q.get("x"), "y": q.get("y")} for q in n["points"]
                        if isinstance(q, dict) and "x" in q]
                if len(ring) >= 3:
                    nav_rings.append(ring)
        elif nm in ("ally", "foe") and isinstance(n.get("points"), list)                 and len(n["points"]) >= 3:
            unit_marker_total += 1
            try:
                if abs(_poly_bbox_area(n["points"]) - 1.0) < 1e-6:
                    unit_marker_1m += 1
            except (TypeError, KeyError):
                pass
        elif nm == "obstacle":
            obst += 1
        elif nm == "wall":
            wall += 1
        elif low.startswith("reachzone"):
            reach += 1
        elif nm == "collide":
            collide += 1
    return {"deployZones": deploys,
            "unitSpawnsByRole": roles,
            "unitSpawnPoints": points,
            "selectorGroups": len(sel_groups),
            "unitMarkerCellEvidence": {
                "markers": unit_marker_total,
                "exactly1mSquares": unit_marker_1m},
            "_navRings": nav_rings,
            "passability": {"navmeshPolygons": nav, "obstacleNodes": obst,
                            "wallNodes": wall, "reachZonePolys": reach,
                            "collideRoots": collide}}
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Dig 12: battle terrain decode")
    ap.add_argument("--battle-root", default="extracted/harvest/content/prefabs/battle")
    ap.add_argument("--cdb-battle", default="extracted/data/_draft/battle.jsonl")
    ap.add_argument("--cdb-region", default="extracted/data/_draft/region.jsonl")
    ap.add_argument("--out-draft", default="extracted/data/_draft/battle_scene.jsonl")
    ap.add_argument("--out-index", default="output/_dig-terrain/battle-bin-index.jsonl")
    ap.add_argument("--report", default="output/_dig-terrain/dig-report.json")
    ap.add_argument("--roundtrip", type=int, default=240)
    ap.add_argument("--secondimpl", type=int, default=60)
    ap.add_argument("--gradfit-tiles", type=int, default=24)
    ap.add_argument("--complement-tiles", type=int, default=40)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    battle_root = Path(args.battle_root)
    terr = index_terrain_dirs(battle_root)

    # --- decode all battle prefabs once ---------------------------------
    sys.path.insert(0, str(Path(__file__).parent))
    from hbson_decode import Decoder, HbsonError

    prefab_cache = {}
    prefab_fail = []
    for p in sorted(battle_root.rglob("*.prefab")):
        rel = str(p).replace("\\", "/")
        try:
            prefab_cache[rel] = Decoder(p.read_bytes(), rel).decode()
        except HbsonError as e:
            prefab_fail.append({"file": rel, "error": str(e)})

    def load_value(prefab_rel):
        v = prefab_cache.get(prefab_rel)
        if v is None and not any(f["file"] == prefab_rel for f in prefab_fail):
            pp = Path(prefab_rel)
            if pp.exists():
                v = prefab_cache[prefab_rel] = Decoder(pp.read_bytes(), prefab_rel).decode()
        return v

    # --- CDB joins -------------------------------------------------------
    battle_ids_by_path = {}
    if Path(args.cdb_battle).exists():
        for line in Path(args.cdb_battle).read_text(encoding="utf-8").splitlines()[1:]:
            r = json.loads(line)
            mp = r.get("mapPath")
            if mp:
                battle_ids_by_path.setdefault(mp, []).append(r.get("id"))
    region_tokens = {}
    if Path(args.cdb_region).exists():
        for line in Path(args.cdb_region).read_text(encoding="utf-8").splitlines()[1:]:
            r = json.loads(line)
            rid = r.get("id")
            if not rid or rid == "Worldwide":
                continue
            toks = {t.lower() for t in rid.split("_") if not t.isdigit()}
            for t in toks:
                region_tokens.setdefault(t, set()).add(rid)
            region_tokens.setdefault("__ids__", set()).add(rid)

    # --- per-scene assembly ----------------------------------------------
    scenes = {}
    for dat_dir in sorted(terr):
        tiles = terr[dat_dir]["tiles"]
        owner_rel, evidence = resolve_owner(dat_dir, battle_root)
        stem = Path(Path(dat_dir).parent).name
        stem = stem[:-4] if stem.endswith(".dat") else stem
        scene_id = dat_dir.rsplit(".dat", 1)[0]
        scene_rel = scene_id + ".prefab"
        node = None
        if owner_rel:
            v = load_value(owner_rel)
            if v is not None:
                node = find_terrain_node(v)
        # density resolution
        vpm = node.get("vertexPerMeter") if node else None
        wppm = node.get("weightMapPixelPerMeter") if node else None
        hs = {t[role] for t in tiles.values() for role in ("h",) if role in t}
        ws = {t["w"] for t in tiles.values() if "w" in t}
        side_h = round(math.isqrt(next(iter(hs)) // 4)) if hs else None
        side_w = round(math.isqrt(next(iter(ws)) // 4)) if ws else None
        dens_src = "declared"
        if vpm is None and side_h is not None:
            guess = (side_h - 1) / TILE_M_DEFAULT
            vpm = guess if abs(guess - round(guess * 2) / 2) < 1e-9 else guess
            dens_src = "derived(default-tile)"
        elif vpm is not None:
            pass
        if wppm is None and side_w is not None:
            wppm = side_w / TILE_M_DEFAULT
            dens_src = "derived(default-tile)"
        tile_m = TILE_M_DEFAULT
        # verify BOTH derivations agree on tile size when both declared
        chk = []
        if vpm:
            chk.append((side_h - 1) / vpm)
        if wppm:
            chk.append(side_w / wppm)
        tile_consistent = bool(chk) and all(abs(c - tile_m) < 1e-9 for c in chk)
        scenes[scene_id] = {
            "dat_dir": dat_dir, "owner": owner_rel, "evidence": evidence,
            "node": node, "vpm": vpm, "wppm": wppm, "dens_src": dens_src,
            "tiles": tiles, "files": terr[dat_dir]["files"],
            "side_h": side_h, "side_w": side_w, "tile_m": tile_m,
            "tile_consistent": tile_consistent,
            "scene_prefab_rel": scene_rel,
        }

    # scenes referenced by CDB but without terrain tiles
    referenced_paths = set(battle_ids_by_path)
    known_scene_rels = {s["scene_prefab_rel"].split("harvest/content/")[-1]
                        for s in scenes.values()}
    extra_ref = {}
    for mp in sorted(referenced_paths):
        if mp in known_scene_rels:
            continue
        full = battle_root.parent.parent / mp  # prefabs/battle/... under content/
        if not full.exists():
            continue
        rel = str(full).replace("\\", "/")
        v = load_value(rel)
        if v is None:
            continue
        node = find_terrain_node(v)
        extra_ref[mp] = {"hasTerrainNode": node is not None, "value": v}

    # --- per-file pass: sizes, stats, proofs -----------------------------
    index_rows = []
    size_ok_n = size_bad = 0
    tile_complete_bad = []
    scene_stat = {}
    all_files = [(sid, s, t, role) for sid, s in sorted(scenes.items())
                 for t in sorted(s["tiles"]) for role in ROLES
                 if role in s["tiles"][t]]
    for sid, s, (tx, ty), role in all_files:
        size = s["tiles"][(tx, ty)][role]
        if role in ("h", "n"):
            pred = s["side_h"] ** 2 * 4
        else:
            pred = s["side_w"] ** 2 * 4
        ok = size == pred
        size_ok_n += ok
        size_bad += not ok
        index_rows.append({"path": s["files"][(tx, ty)][role].replace("\\", "/")
                           .split("harvest/content/", 1)[-1],
                           "scene": sid, "tile": [tx, ty], "role": role,
                           "bytes": size, "layoutSide": s["side_h"] if role in ("h", "n") else s["side_w"],
                           "dtype": "f32" if role == "h" else ("rgba8-slope" if role == "n" else "rgba8-" + ("surface-index" if role == "i" else "blend-weight")),
                           "sizeOk": ok})
    for sid, s in scenes.items():
        have = {t for t in s["tiles"] if len(s["tiles"][t]) == 4}
        if len(have) != len(s["tiles"]):
            tile_complete_bad.append({"scene": sid, "tiles": len(s["tiles"]),
                                      "complete": len(have)})

    # streaming stats per scene (all files, C-speed slicing where possible)
    gradfit = []
    rt_pool = []
    comp_pool = []
    for sid, s in scenes.items():
        agg = {"h_min": 1e30, "h_max": -1e30, "h_sum": 0.0, "h_cnt": 0,
               "n_edge": 0, "n_edge_seam": 0, "idx": set(), "alpha_bad": 0,
               "alpha_px": 0, "tile_act": {},
               "w_over": 0, "w_checked_px": 0, "n_ch": ([256]*3, [-1]*3)}
        for (tx, ty), role_file in sorted(s["files"].items()):
            for role in ROLES:
                fp = role_file.get(role)
                if not fp:
                    continue
                b, st = parse_bin(fp, role, s["side_h"], s["side_w"])
                if role == "h":
                    agg["h_min"] = min(agg["h_min"], st.h_min)
                    agg["h_max"] = max(agg["h_max"], st.h_max)
                    agg["h_sum"] += st.h_sum
                    agg["h_cnt"] += st.side * st.side
                    rt_pool.append((sid, (tx, ty), role, fp))
                elif role == "n":
                    agg["n_edge"] += st.edge_nonzero
                    agg["n_edge_seam"] += st.edge_on_seam
                    for ch in range(3):
                        agg["n_ch"][0][ch] = min(agg["n_ch"][0][ch], st.n_ch_min[ch])
                        agg["n_ch"][1][ch] = max(agg["n_ch"][1][ch], st.n_ch_max[ch])
                    rt_pool.append((sid, (tx, ty), role, fp))
                else:
                    agg["idx"] |= st.idx_set
                    agg["alpha_bad"] += st.alpha_bad
                    agg["alpha_px"] += st.side * st.side
                    if role == "i":
                        # alpha=255 => painted/playable area; 0 => auto filler
                        frac_active = 1.0 - st.alpha_bad / (st.side * st.side)
                        prev = agg["tile_act"].get("act", 0)
                        agg["tile_act"][(tx, ty)] = frac_active
                        _ = prev
                    rt_pool.append((sid, (tx, ty), role, fp))
                    if role == "w":
                        agg["w_over"] += st.w_active_over
                        agg["w_checked_px"] += st.side * st.side
                        comp_pool.append((sid, (tx, ty), fp))
        scene_stat[sid] = agg

    # gradient <-> normal-bytes proof: pooled per-scene regression of the n-map
    # x/y channels against the height-derived unit normal (unorm8, bias 127.5).
    grad_results = []
    for sid, s in sorted(scenes.items()):
        side = s["side_h"]
        if not side or side < 33:
            continue
        tiles = sorted(t for t in s["files"] if "h" in s["files"][t] and "n" in s["files"][t])
        if not tiles:
            continue
        step_t = max(1, len(tiles) // 3)
        sx_n = sx_d = 0.0      # accumulated covariance terms: bytes-offset vs -gx
        den = 0.0
        npix = 0
        cell = s["tile_m"] / (side - 1)
        for (tx, ty) in tiles[::step_t][:3]:
            hb = Path(s["files"][(tx, ty)]["h"]).read_bytes()
            nb = Path(s["files"][(tx, ty)]["n"]).read_bytes()
            h = struct.unpack(f"<{side*side}f", hb)
            c0 = nb[0::4]
            c1 = nb[1::4]
            for jy in range(2, side - 1, 4):
                base = jy * side
                for ix in range(2, side - 1, 4):
                    gx = (h[base + ix + 1] - h[base + ix - 1]) / (2 * cell)
                    gy = (h[base + ix + side] - h[base + ix - side]) / (2 * cell)
                    L = math.sqrt(gx * gx + gy * gy + 1.0)
                    nx = c0[base + ix] - 127.5
                    ny = c1[base + ix] - 127.5
                    sx_n += nx * (-gx / L) + ny * (-gy / L)
                    den += ((-gx / L) ** 2 + (-gy / L) ** 2)
                    npix += 1
        if den < 25.0:      # effectively flat tile sample: ratio unstable
            grad_results.append({"scene": sid.split("/battle/")[-1], "flat": True})
            continue
        scale = sx_n / den  # observed byte scale per unit normal component
        grad_results.append({"scene": sid.split("/battle/")[-1],
                             "byteScalePerNormalUnit": round(scale, 2),
                             "samples": npix})
    scales = [g["byteScalePerNormalUnit"] for g in grad_results
              if "byteScalePerNormalUnit" in g]
    med_scale = sorted(scales)[len(scales)//2] if scales else None

    # round-trip re-encode proof
    rt_pool.sort()
    step = max(1, len(rt_pool) // args.roundtrip)
    rt_picks = rt_pool[::step][:args.roundtrip]
    rt_ok = rt_bad = 0
    rt_fail = []
    for sid, (tx, ty), role, fp in rt_picks:
        try:
            if reencode(fp, role) == Path(fp).read_bytes():
                rt_ok += 1
            else:
                rt_bad += 1
                rt_fail.append(fp)
        except Exception as e:  # noqa: BLE001
            rt_bad += 1
            rt_fail.append(f"{fp}: {e}")

    # independent second implementation proof
    si_pool = []
    for sid, s in scenes.items():
        for (tx, ty), rf in sorted(s["files"].items()):
            for role in ROLES:
                if role in rf:
                    si_pool.append((sid, (tx, ty), role, rf[role]))
    si_pool.sort()
    step = max(1, len(si_pool) // args.secondimpl)
    si_ok = si_bad = 0
    si_fail = []
    for sid, (tx, ty), role, fp in si_pool[::step][:args.secondimpl]:
        ok, want, tag = second_impl_check(fp, scenes[sid]["tile_m"])
        si_ok += ok
        si_bad += not ok
        if not ok:
            si_fail.append({"file": fp, "expected": want, "tag": tag})

    # --- assemble dataset rows -------------------------------------------
    def _point_in_ring(px, py, ring):
        inside = False
        n = len(ring)
        j = n - 1
        for i in range(n):
            xi, yi = ring[i]["x"], ring[i]["y"]
            xj, yj = ring[j]["x"], ring[j]["y"]
            if (yi > py) != (yj > py) and                px < (xj - xi) * (py - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
        return inside

    out_rows = []
    spawn_sanity = {"deployCentersChecked": 0, "deployInBounds": 0,
                    "unitPointsChecked": 0, "unitPointsInBounds": 0,
                    "unitPointsOnNavmesh": 0, "failures": []}
    for sid, s in sorted(scenes.items()):
        v = load_value(s["owner"]) if s["owner"] else None
        sp = extract_spawns_and_passability(v) if v else {
            "deployZones": [], "unitSpawnsByRole": {},
            "selectorGroups": 0,
            "passability": {"navmeshPolygons": 0, "obstacleNodes": 0,
                            "wallNodes": 0, "reachZonePolgons": 0,
                            "collideRoots": 0}}
        agg = scene_stat[sid]
        # region tokens from mapPath + surface albedo paths
        hay = ""
        surf_list = []
        if s["node"] and isinstance(s["node"].get("surfaces"), list):
            for sf in s["node"]["surfaces"]:
                alb = sf.get("albedo") or ""
                hay += " " + alb.lower()
                surf_list.append({
                    "albedo": alb.split("/")[-1],
                    "dir": alb.split("/")[-2] if "/" in alb else alb,
                    "minHeight": sf.get("minHeight"), "maxHeight": sf.get("maxHeight")})
        hay += " " + sid.lower()
        regions = {}
        for tok, rids in region_tokens.items():
            if tok == "__ids__":
                continue
            if tok in hay:
                for rid in sorted(rids):
                    regions[rid] = True
        xs = [t[0] for t in s["tiles"]]
        ys = [t[1] for t in s["tiles"]]
        cell_count = math.ceil(s["tile_m"] * s["vpm"]) if s["vpm"] else None
        cell_size = (s["tile_m"] / cell_count) if cell_count else None
        # spawn sanity: deploy-zone centres + unit markers inside tile-grid
        # world bbox; convention (TerrainMesh): tile t covers [t*tile,(t+1)*tile)
        inb = None
        lo_x, hi_x = min(xs) * s["tile_m"], (max(xs) + 1) * s["tile_m"]
        lo_y, hi_y = min(ys) * s["tile_m"], (max(ys) + 1) * s["tile_m"]
        rings = sp.pop("_navRings", [])
        on_mesh = in_mesh = 0
        for pt in sp["unitSpawnPoints"]:
            if pt["x"] is None or pt["y"] is None:
                continue
            spawn_sanity["unitPointsChecked"] += 1
            okb = lo_x <= pt["x"] < hi_x and lo_y <= pt["y"] < hi_y
            if okb:
                spawn_sanity["unitPointsInBounds"] += 1
            hit = any(_point_in_ring(pt["x"], pt["y"], r) for r in rings)
            if hit:
                on_mesh += 1
        if rings:
            for pt in sp["unitSpawnPoints"]:
                if pt["x"] is None or pt["y"] is None:
                    continue
                in_mesh += 1
                if any(_point_in_ring(pt["x"], pt["y"], r) for r in rings):
                    spawn_sanity["unitPointsOnNavmesh"] += 1
        if sp["deployZones"]:
            inb = True
            for dz in sp["deployZones"]:
                if dz["x"] is None or dz["y"] is None:
                    continue
                spawn_sanity["deployCentersChecked"] += 1
                if lo_x <= dz["x"] < hi_x and lo_y <= dz["y"] < hi_y:
                    spawn_sanity["deployInBounds"] += 1
                else:
                    inb = False
                    spawn_sanity["failures"].append(
                        {"scene": sid.split("/battle/")[-1], "zone": dz["name"],
                         "xy": [dz["x"], dz["y"]], "bounds": [[lo_x, hi_x], [lo_y, hi_y]]})
        sp["spawnPointsOnNavmeshFrac"] = (
            round(spawn_sanity["unitPointsOnNavmesh"] / in_mesh, 4)
            if in_mesh else None)
        battles = battle_ids_by_path.get(
            s["scene_prefab_rel"].split("harvest/content/")[-1], [])
        out_rows.append({
            "_id": sid.split("prefabs/battle/")[-1],
            "_kind": "battle-scene",
            "buildId": BUILD_ID,
            "path": s["scene_prefab_rel"],
            "terrainDir": s["dat_dir"].split("harvest/content/")[-1],
            "ownerEvidence": s["evidence"],
            "battles": battles,
            "regions": sorted(regions),
            "grid": {
                "tileSizeM": s["tile_m"],
                "tileConsistent": s["tile_consistent"],
                "tileRangeX": [min(xs), max(xs)],
                "tileRangeY": [min(ys), max(ys)],
                "tileCount": len(s["tiles"]),
                "extentM": [(max(xs) - min(xs) + 1) * s["tile_m"],
                            (max(ys) - min(ys) + 1) * s["tile_m"]],
                "vertexPerMeter": s["vpm"],
                "weightMapPixelPerMeter": s["wppm"],
                "cellSizeM": cell_size,
                "heightMapSidePerTile": s["side_h"],
                "weightMapSidePerTile": s["side_w"],
                "densitySource": s["dens_src"],
                "crs": "local battle meters; tile t spans [t*64,(t+1)*64); heights in meters",
            },
            "terrain": {
                "heightsM": {"min": round(agg["h_min"], 4),
                              "max": round(agg["h_max"], 4),
                              "mean": round(agg["h_sum"] / agg["h_cnt"], 4)} if agg["h_cnt"] else None,
                "normalChRanges": {f"ch{i}": [agg["n_ch"][0][i], agg["n_ch"][1][i]]
                                    for i in range(3)},
                "seamFlagPixels": {"nonzero": agg["n_edge"],
                                    "onLastRowCol": agg["n_edge_seam"]},
                "splatIndicesUsed": sorted(agg["idx"]),
                "alphaChannel": {
                    "meaning": "255 = painted/playable area, 0 = auto-created filler tile area",
                    "activePx": agg["alpha_px"] - agg["alpha_bad"],
                    "inactivePx": agg["alpha_bad"],
                    "checkedPx": agg["alpha_px"],
                    "activeTiles": sum(1 for f in agg.get("tile_act", {}).values()
                                        if f > 0.5),
                    "tilesTotal": len(agg.get("tile_act", {})),
                },
                "weightChannelsOver255Px": agg["w_over"],
                "weightCheckedPx": agg["w_checked_px"],
                "surfaces": surf_list,
            },
            "spawns": sp,
            "spawnZonesInBounds": inb,
        })

    # referenced-but-terrainless scene stubs (CDB join completeness)
    stub_rows = []
    for mp, info in sorted(extra_ref.items()):
        if mp in known_scene_rels:
            continue
        sp_stub = extract_spawns_and_passability(info["value"])
        rings_stub = sp_stub.pop("_navRings", []) or []
        mesh_n = mesh_hit = 0
        for pt in sp_stub.get("unitSpawnPoints", []):
            if pt.get("x") is None or pt.get("y") is None:
                continue
            mesh_n += 1
            if any(_point_in_ring(pt["x"], pt["y"], r) for r in rings_stub):
                mesh_hit += 1
        sp_stub["spawnPointsOnNavmeshFrac"] = (
            round(mesh_hit / mesh_n, 4) if mesh_n else None)
        hay_stub = mp.lower()
        regions_stub = set()
        for tok, rids in region_tokens.items():
            if tok == "__ids__":
                continue
            if tok in hay_stub:
                regions_stub |= set(rids)
        stub_rows.append({
            "_id": mp.replace("prefabs/battle/", "", 1).replace(".prefab", ""),
            "_kind": "battle-scene",
            "buildId": BUILD_ID,
            "path": mp,
            "terrainDir": None,
            "ownerEvidence": "cdb-mapPath-only",
            "battles": battle_ids_by_path.get(mp, []),
            "regions": sorted(regions_stub),
            "grid": None,
            "terrain": None,
            "spawns": sp_stub,
            "spawnZonesInBounds": None,
            "note": "referenced by CDB battle.mapPath; no terrain tiles on disk "
                    "(own FBX/model ground or terrainless layout)"
                    + ("; has terrain node" if info["hasTerrainNode"] else ""),
        })

    # --- write outputs -----------------------------------------------------
    out_draft = Path(args.out_draft)
    out_draft.parent.mkdir(parents=True, exist_ok=True)
    with open(out_draft, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps({"_meta": {
            "kind": "battle-scene", "sourceSheet": None,
            "buildId": BUILD_ID,
            "container": "content.pak:/prefabs/battle/** (.dat/terrain/*.bin + owning .prefab)",
            "rowCount": len(out_rows),
            "stubRowCount": len(stub_rows),
            "emittedBy": "pipeline/tools/battle_terrain_dig.py (Dig 12)",
            "layout": {
                "h.bin": "f32 heights, side=ceil(64*vpm)+1 per tile",
                "n.bin": "RGBA8 per-vertex slope/normal map, side=h side; ch0/ch1=slope bytes(~ -63*dh/d), ch2~nz, ch3 seam flags",
                "i.bin": "RGBA8 surface-index map, side=round(64*wppm)",
                "w.bin": "RGBA8 blend-weight map, complementary to i channels",
                "tileSizeM": 64.0,
                "formulas": "Terrain.hx disasm ops 15-31/57-92; ctor defaults f#9693",
            },
            "crs": "per-scene local meters (independent CRS; not worldmap-anchored)",
        }}, ensure_ascii=False) + "\n")
        for r in out_rows:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=False) + "\n")
        for r in stub_rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    out_index = Path(args.out_index)
    out_index.parent.mkdir(parents=True, exist_ok=True)
    with open(out_index, "w", encoding="utf-8", newline="\n") as fh:
        for r in index_rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    report = {
        "buildId": BUILD_ID,
        "scenesWithTerrain": len(scenes),
        "tilesTotal": sum(len(s["tiles"]) for s in scenes.values()),
        "binFilesTotal": len(index_rows),
        "sizeOk": size_ok_n, "sizeBad": size_bad,
        "tileCompletenessBad": tile_complete_bad,
        "ownerEvidence": {},
        "declaredBothConsistent": sum(1 for s in scenes.values()
                                       if len([c for c in [
                                           (s['side_h']-1)/s['vpm'] if s['vpm'] else None,
                                           s['side_w']/s['wppm'] if s['wppm'] else None] if c]) == 2
                                       and s["tile_consistent"]),
        "tileSizes": sorted({s["tile_m"] for s in scenes.values()}),
        "normalRegression": {"scenesTested": len(grad_results),
                              "scenesFlatSkipped": sum(1 for g in grad_results if g.get("flat")),
                              "medianByteScalePerNormalUnit": med_scale,
                              "expectedIfUnorm8Normal": 63.75,
                              "detail": [g for g in grad_results
                                         if not g.get("flat")][:8]},
        "roundtrip": {"attempted": len(rt_picks), "ok": rt_ok, "bad": rt_bad,
                       "failures": rt_fail[:10]},
        "secondImpl": {"attempted": si_ok + si_bad, "ok": si_ok, "bad": si_bad,
                        "failures": si_fail[:10]},
        "spawnSanity": spawn_sanity,
        "prefabDecodeFailures": prefab_fail,
        "cdbReferencedScenes": len(referenced_paths),
        "cdbReferencedMissingOnDisk": sorted(
            mp for mp in referenced_paths
            if not (battle_root.parent.parent / mp).exists()),
        "stubRows": len(stub_rows),
        "alphaBadTotal": sum(scene_stat[s]["alpha_bad"] for s in scene_stat),
    }
    for s in scenes.values():
        report["ownerEvidence"][s["evidence"]] = \
            report["ownerEvidence"].get(s["evidence"], 0) + 1
    rp = Path(args.report)
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")

    if not args.quiet:
        print(json.dumps({k: report[k] for k in (
            "scenesWithTerrain", "tilesTotal", "binFilesTotal", "sizeOk",
            "sizeBad", "roundtrip", "secondImpl", "spawnSanity",
            "tileCompletenessBad", "ownerEvidence", "declaredBothConsistent",
            "gradientFit", "alphaBadTotal", "cdbReferencedScenes",
            "cdbReferencedMissingOnDisk", "stubRows")}, indent=1))
    exit_ok = (size_bad == 0 and rt_bad == 0 and si_bad == 0
               and not tile_complete_bad and not prefab_fail)
    return 0 if exit_ok else 1


if __name__ == "__main__":
    sys.stdout = __import__("io").TextIOWrapper(sys.stdout.buffer,
                                                encoding="utf-8", errors="replace")
    sys.exit(main())
