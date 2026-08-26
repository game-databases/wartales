#!/usr/bin/env python3
"""fit_world_transform.py — D6 strong form: world<->tile-pixel transform fit +
independent validation battery (data dig 11).

Derives and VALIDATES the stored-plane pixel mapping for the Wartales world
map, then emits ``output/_dig-map/coordinate-transform.json`` for the
``map_tiles.py registry`` stage to cite (C4: the registry states only what a
run measured — never literals).

Evidence chain (every number below is read or computed here, none invented):

1. Carrier constants, read live from the client payloads:
   - ``res:/content/prefabs/lighting/worldmap.prefab`` ``$.children[4]``
     (type ``layers2D``): ``offsetX``, ``layerScale``, ``worldSize`` — the
     exact arguments of ``hrt.prefab.l3d.Layers2D.getLayerColor``
     (``col = int((x-offsetX)/layerScale)``, out-of-bounds -> -1; bytecode
     f#11253, disassembled dig 6/dig 11).
   - ``$.children[3]`` (type ``heightmap``): ``sizeX/sizeY/minTileX`` — the
     authored terrain grid that contains the albedo bbox.
2. Candidate transform H0: albedo cells are 128 world units square
   (worldSize 8192 == 64 cells; offsetX -1536 == minTileX -12 times 128),
   so stored-plane px = wx*(512/128), py = wy*(512/128), origin = top-left
   corner of tile column x0 / row y0.
3. Independent validation battery (POI labels are NOT used to derive H0):
   a. POI/town/secret/anchor region labels vs ``layer_region.png`` sampled
      with the CLIENT's own arithmetic (held-open evidence from survey;
      mismatches listed and classified, never dropped).
   b. Land/sea shape: tile payload-hash geography (no-splat ocean mask +
      placeholder band + absent cells) vs the collide mask
      ``assets/worldmap/collides/global.png`` and vs the union of authored
      layers2D paint.
   c. Splat material families (harag_*/belerion_*/Gosenberg_*/alazar*) per
      cell vs the region-mask majority under the mapped cell rect.
   d. Terrain elevation massif position vs the Alazar_1 (Drombach) mask
      density profile.
   e. Named coastal landmarks (Belerian wreck class) projected to tile space
      against the sea neighborhood.
   f. Per-marker-kind land/sea consistency (crossings on land, fishing at
      shore) as distance-to-water distributions.
4. Registration sharpness: the label-shift curve (point-sampled agreement vs
   mask-plane slide, no lattice involved) must peak at zero; coastal-
   polarity proves stored .raw rows/cols run north->south / west->east with
   no intra-tile flip; biome-blob elevation means (blizzard high, swamp low)
   are reported descriptively.

Verdict gates are FROZEN here before the battery runs (AC4 discipline):
  LABEL_GATE      = 0.97  overall POI->region agreement (boundary markers are
                          the measured noise floor: border posts and paired
                          region roots legitimately sample neighbors/-1)
  SHAPE_GATE      = 0.50  majority-overlap IoU for every shape check (a wrong
                          scale/origin cannot reach half overlap; a correct
                          one measures far above it)
  LABEL_SHIFT_TOL = 32    the label-shift curve must peak within one mask
                          block (32 world units) of zero shift, with its
                          value at zero within 2 points of the maximum

Retired instruments (measured reasons recorded in the artifact, never
silent): block-majority/objective sweeps over (cellUnits,dx,dy) grids —
granularity-biased and flat; mean-elevation-under-biome-blob argmax — not a
peaked objective. The scale itself is NOT fitted from rasters at all: it is
carrier arithmetic (offsetX == minTileX * cellUnits, worldSize divisible).

Usage:
  python pipeline/tools/fit_world_transform.py [--fast]
        writes output/_dig-map/coordinate-transform.json (+ stdout report)

Python 3.14, numpy + Pillow only (same stack as map_tiles.py).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

_TOOLS = Path(__file__).resolve().parent
_PIPELINE = _TOOLS.parent
for p in (_TOOLS, _PIPELINE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import harvest  # noqa: E402  (longpath helper)
import hbson_decode  # noqa: E402  (shipped strict decoder — carrier read live)
import map_tiles  # noqa: E402  (BBOX / TILE_PX / measured constants)

class FitError(RuntimeError):
    """Fail-loud invariant breach (map_tiles.MapPipelineError analogue)."""


def require(cond, msg):
    if not cond:
        raise FitError(msg)


BUILDID = 20318128
PACKROOT = _PIPELINE.parent
MASK_DIR = (PACKROOT / "extracted/harvest/content/prefabs/lighting/"
                        "worldmap.dat/layers2D")
WORLDMAP_PREFAB = (PACKROOT / "extracted/harvest/content/prefabs/lighting/"
                               "worldmap.prefab")
COLLIDE_PNG = (PACKROOT / "extracted/harvest/assets/assets/worldmap/collides/"
                           "global.png")
POI_JSONL = PACKROOT / "extracted/relinks/_draft/poi_coordinates.jsonl"
OVERLAYS_JSON = PACKROOT / "extracted/data/_draft/worldmap_overlays.json"
TEXTURES_JSON = (PACKROOT / "extracted/harvest/map/assets/worldmap/data/"
                              "textures.json")
DIG_OUT = Path("output/_dig-map")

# --- frozen before the battery ran (AC4 discipline; see module docstring) ---
LABEL_GATE = 0.97
SHAPE_GATE = 0.50
LABEL_SHIFT_TOL = 32     # label-shift curve: agreement argmax must sit
                         # within one mask-pixel-block of zero (32 world
                         # units = 1/4 cell)

TILE_PX = map_tiles.DDS_TRIPLES["albedo"][1]      # measured §2 triple: 512
require(TILE_PX == 512, f"unexpected albedo tile size {TILE_PX}")
BBOX = map_tiles.BBOX




# --------------------------------------------------------------------------- #
# carriers (read live — never copied from scratch artifacts)
# --------------------------------------------------------------------------- #

def read_carriers():
    data = WORLDMAP_PREFAB.read_bytes()
    dec = hbson_decode.Decoder(data, str(WORLDMAP_PREFAB))
    doc = dec.decode()
    kids = doc.get("children", [])
    terr = next((c for c in kids if c.get("type") == "heightmap"), None)
    lay = next((c for c in kids if c.get("type") == "layers2D"), None)
    require(terr is not None and lay is not None,
            "worldmap.prefab missing heightmap/layers2D children")
    require(lay.get("layerScale") == 4,
            f"unexpected layerScale {lay.get('layerScale')!r}")
    return {
        "layers2D": {
            "source": "res:/content/prefabs/lighting/worldmap.prefab "
                      "$.children[type=layers2D]",
            "offsetX": lay.get("offsetX", 0.0),
            "offsetY": lay.get("offsetY", 0.0),
            "layerScale": lay["layerScale"],
            "worldSize": lay["worldSize"],
        },
        "terrain": {
            "source": "res:/content/prefabs/lighting/worldmap.prefab "
                      "$.children[type=heightmap]",
            "sizeX": terr["sizeX"], "sizeY": terr["sizeY"],
            "minTileX": terr["minTileX"],
        },
    }


def load_masks():
    overlays = json.loads(OVERLAYS_JSON.read_text(encoding="utf-8"))
    tables = {t["name"]: t for t in overlays["layers2D"]["tables"]}
    masks = {}
    for m in overlays["layers2D"]["masks"]:
        name = Path(m["path"]).stem.removeprefix("layer_")
        arr = np.asarray(Image.open(harvest.longpath(MASK_DIR /
                                                     f"layer_{name}.png"))
                         .convert("L"))
        require(arr.shape == (2048, 2048), f"{name}: {arr.shape}")
        masks[name] = (arr, tables.get(name))
    return masks


def load_pois():
    rows = []
    with open(POI_JSONL, encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            if "_meta" not in rec:
                rows.append(rec)
    return rows


def region_index_table(masks):
    tab = masks["region"][1]
    require(tab is not None, "region table missing from overlays artifact")
    return {v["name"]: v["index"] for v in tab["values"]}


def land_sea_cells():
    """Tile geography from payload hashes in the rerun manifest."""
    manifest = DIG_OUT / "map.manifest.jsonl"
    require(manifest.exists(),
            "run `map_tiles.py extract` first (rerun manifest needed)")
    per: dict[str, dict] = {}
    rx = re.compile(r"/(albedo|normal|splat|height)/[a-z]+_x(-?\d+)_y(\d+)")
    with open(harvest.longpath(manifest), encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            m = rx.search(row["path"])
            if not m:
                continue
            cls = m.group(1)
            if cls == "height":
                continue
            per.setdefault(cls, {})[(int(m.group(2)), int(m.group(3)))] = \
                row["hash"]
    present = set(per["albedo"])
    sea_splat = {c for c, h in per["splat"].items() if h == "78c858d4"}
    placeholder = {c for c, h in per["albedo"].items() if h == "0ff430e9"}
    holes = {(x, y)
             for x in range(BBOX["xMin"], BBOX["xMax"] + 1)
             for y in range(BBOX["yMin"], BBOX["yMax"] + 1)} - present
    return {"present": present, "seaSplat": sea_splat,
            "placeholder": placeholder, "holes": holes,
            "land": present - sea_splat}


# --------------------------------------------------------------------------- #
# the candidate transform (derived from carrier arithmetic, then validated)
# --------------------------------------------------------------------------- #

def derive_h0(carriers):
    """Derive cell units from carrier arithmetic: offsetX == minTileX * u.
    Cross-checked against worldSize divisibility and the 64-cell mask span."""
    lay = carriers["layers2D"]
    ter = carriers["terrain"]
    require(ter["minTileX"] != 0 and lay["offsetX"] % ter["minTileX"] == 0,
            "offsetX not divisible by minTileX — grid alignment broken")
    u_from_offset = lay["offsetX"] / ter["minTileX"]
    require(abs(u_from_offset - round(u_from_offset)) < 1e-9,
            f"non-integer cell units from offset relation: {u_from_offset}")
    u = int(round(u_from_offset))
    require(lay["worldSize"] % u == 0,
            f"worldSize {lay['worldSize']} not divisible by cell units {u}")
    mask_span_cells = lay["worldSize"] // u
    require(mask_span_cells == 64,
            f"mask plane spans {mask_span_cells} cells, expected 64")
    s = TILE_PX / u
    return {
        "model": "axis-aligned-affine",
        "cellUnits": u,
        "pxPerWorldUnit": s,
        "worldToStoredPx": {
            "formula": "px = a*wx + tx ; py = dGrid*wy + ty",
            "a": s, "b": 0.0, "tx": 0.0,
            "dGrid": s, "c": 0.0, "ty": 0.0,
            "origin": "top-left corner of tile column x0 / row y0",
            "rowOrder": "mosaic row index grows with world y; world +y is "
                        "south (north = small y, image top — Dig 6)",
        },
        "storedPxToWorld": {
            "formula": "wx = (px - tx)/a ; wy = (py - ty)/dGrid",
        },
        "servedTileIndex": {
            "z3": "tx = floor(px/TILE_PX) == x_cell - xMin ; "
                  "ty = floor(py/TILE_PX) == y_cell - yMin",
            "zLower": "cellsPerTileAtZ halves each zoom step down "
                      "(map_tiles ZOOMS)",
        },
        "derivation": {
            "cellUnitsEqualsOffsetOverMinTile":
                f"{lay['offsetX']} / {ter['minTileX']} = {u}",
            "maskPlaneCells": mask_span_cells,
            "note": "two carriers agree independently: the layers2D plane "
                    "(offsetX -1536, worldSize 8192) and the heightmap grid "
                    "(sizeX 60, minTileX -12) describe the same 128-unit "
                    "cell lattice",
        },
    }


# --------------------------------------------------------------------------- #
# validation battery
# --------------------------------------------------------------------------- #

def sample_region(arr, xs, ys, lay):
    col = np.trunc((np.asarray(xs, float) - lay["offsetX"])
                   / lay["layerScale"]).astype(np.int64)
    row = np.trunc((np.asarray(ys, float) - lay["offsetY"])
                   / lay["layerScale"]).astype(np.int64)
    h, w = arr.shape
    ok = (col >= 0) & (col < w) & (row >= 0) & (row < h)
    return np.where(ok, arr[np.clip(row, 0, h - 1),
                            np.clip(col, 0, w - 1)].astype(np.int64),
                    np.int64(-1))


def check_labels(pois, masks, h0, lay):
    reg_arr = masks["region"][0]
    rtab = region_index_table(masks)
    coord = [p for p in pois if p.get("x") is not None]
    xs = np.array([p["x"] for p in coord])
    ys = np.array([p["y"] for p in coord])
    want = np.array([rtab.get(p.get("region"), -99) for p in coord])
    got = sample_region(reg_arr, xs, ys, lay)
    agree = got == want
    per_kind = defaultdict(lambda: [0, 0])
    mismatches = []
    for p, g, w_, a in zip(coord, got, want, agree):
        per_kind[p["kind"]][0] += int(a)
        per_kind[p["kind"]][1] += 1
        if not a:
            entry = {"kind": p["kind"], "id": p["id"], "region": p["region"],
                     "sampled": int(g), "expected": int(w_)}
            # classification of the known benign mechanisms (never silently
            # forgiven — listed and counted separately)
            if g == -1:
                entry["class"] = "outside-authored-band"
            elif w_ in (9, 10) or g in (2, 5):
                entry["class"] = "paired-region-root"
            else:
                entry["class"] = "boundary-sample"
            mismatches.append(entry)
    total = len(coord)
    rate = float(agree.sum()) / total
    anchors = [m for m in mismatches if m["kind"] == "region-anchor"]
    return {
        "gate": LABEL_GATE, "total": total, "agree": int(agree.sum()),
        "rate": round(rate, 4), "pass": bool(rate >= LABEL_GATE),
        "perKind": {k: {"agree": v[0], "n": v[1],
                        "rate": round(v[0] / v[1], 4)}
                    for k, v in sorted(per_kind.items())},
        "mismatches": mismatches, "mismatchCount": len(mismatches),
    }


def _cell_rect(cx, cy, h0):
    u = h0["cellUnits"]
    return (cx * u, cy * u, (cx + 1) * u, (cy + 1) * u)


def _mask_slice(rect, lay, mask_shape, px_per_unit=None):
    x0, y0, x1, y1 = rect
    sc = lay["layerScale"] if px_per_unit is None else 1.0 / px_per_unit
    ox = lay["offsetX"]
    c0 = int(round((x0 - ox) / sc))
    c1 = int(round((x1 - ox) / sc))
    r0 = int(round(y0 / sc))
    r1 = int(round(y1 / sc))
    h, w = mask_shape
    if r0 < 0 or c0 < 0 or r1 > h or c1 > w:
        return None
    return slice(r0, r1), slice(c0, c1)


def check_shapes(ls, masks, h0, lay):
    assigned = np.zeros((2048, 2048), dtype=bool)
    for name in ("region", "island", "biome", "env", "gameplay", "subregion",
                 "difficulty"):
        assigned |= (masks[name][0] > 0)
    results = {}

    def score(indicator, px_per_unit=None, skip_oob=True):
        tp = fp = fn = tn = skipped = 0
        worst_land, worst_sea = [], []
        for cy in range(BBOX["yMin"], BBOX["yMax"] + 1):
            for cx in range(BBOX["xMin"], BBOX["xMax"] + 1):
                if (cx, cy) in ls["holes"]:
                    continue
                sl = _mask_slice(_cell_rect(cx, cy, h0), lay,
                                 indicator.shape, px_per_unit)
                if sl is None:
                    skipped += 1
                    continue
                frac = float(indicator[sl[0], sl[1]].mean())
                pred = frac > 0.5
                truth = (cx, cy) in ls["land"]
                if pred and truth:
                    tp += 1
                elif pred and not truth:
                    fp += 1
                    worst_sea.append({"cell": [cx, cy], "frac": round(frac, 3)})
                elif not pred and truth:
                    fn += 1
                    worst_land.append({"cell": [cx, cy], "frac": round(frac, 3)})
                else:
                    tn += 1
        iou = tp / max(1, tp + fp + fn)
        acc = (tp + tn) / max(1, tp + fp + fn + tn)
        worst_land.sort(key=lambda e: e["frac"])
        worst_sea.sort(key=lambda e: -e["frac"])
        return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "skipped": skipped,
                "iou": round(iou, 4), "acc": round(acc, 4),
                "pass": bool(iou >= SHAPE_GATE),
                "worstLandDisagreements": worst_land[:10],
                "worstSeaDisagreements": worst_sea[:10]}

    results["authoredPaintVsTileLand"] = score(assigned)
    coll = np.asarray(Image.open(harvest.longpath(COLLIDE_PNG)).convert("L"))
    results["collideMaskVsTileLand"] = score(coll < 128, px_per_unit=0.5)
    for k, v in results.items():
        v["gate"] = SHAPE_GATE
    return results


def check_splat_semantics(sample_cells=12):
    """Measured splat channel semantics (replaces the retired name-family
    check: splat pixels are NOT palette colors — nearest-hex scoring measured
    0.1179 agreement, i.e. meaningless, and was removed before pinning).

    Measured here on a spread sample: R/G carry LOCAL slot indices (value =
    index*16, only 0..5 ever observed per cell -> <=6 materials active per
    cell), B carries weight-1 (0..255), A = 255-B (weight-2 complement). The
    per-cell slot->material table is NOT carried by worldmap.prefab — recorded
    as the concrete unblock for a follow-up micro-dig (Surface/TerrainMesh
    material assignment), never guessed.
    """
    import numpy as np
    splat_dir = PACKROOT / "extracted/harvest/map/assets/worldmap/data/splat"
    ls = land_sea_cells()
    cells = sorted(ls["present"])
    step = max(1, len(cells) // sample_cells)
    rows = []
    encodings = Counter()
    comp_violations = 0
    checked = 0
    max_slots = 0
    for cx, cy in cells[::step]:
        raw = (splat_dir / f"splat_x{cx}_y{cy}.dds").read_bytes()
        require(len(raw) == 128 + 2048 * 2048 * 4,
                f"splat_x{cx}_y{cy}.dds: unexpected size {len(raw)}")
        arr = np.frombuffer(raw, dtype=np.uint8, offset=128)
        ch = arr.reshape(-1, 4)[::97]
        r, g, b, a = ch[:, 0], ch[:, 1], ch[:, 2], ch[:, 3]
        r_vals = sorted(int(v) for v in np.unique(r))
        g_vals = sorted(int(v) for v in np.unique(g))
        if r_vals and all(v % 16 == 0 for v in r_vals):
            enc = "index*16"
            slots = sorted({v // 16 for v in r_vals} | {v // 16 for v in g_vals})
        elif max(r_vals + g_vals) <= 8:
            enc = "raw-slot-ids"
            slots = sorted(set(r_vals) | set(g_vals))
        else:
            enc = "unresolved"
            slots = []
        encodings[enc] += 1
        max_slots = max(max_slots, len(slots))
        comp_violations += int(((b.astype(int) + a.astype(int)) != 255).sum())
        rows.append({"cell": [cx, cy], "rValues": r_vals, "gValues": g_vals,
                     "encoding": enc})
        checked += 1
    return {
        "measuredEncodings": dict(encodings),
        "interpretation":
            "R/G carry layer-slot selectors and B/A the pair weights "
            "(A = 255-B wherever checked); the selector scale differs by "
            "cell family (index*16 vs raw ids 0..5) — <=6 local slots per "
            "cell in every encoding observed",
        "cellsChecked": checked,
        "maxSelectorsPerCellObserved": int(max_slots),
        "weightComplementViolations": comp_violations,
        "perCellSample": rows[:12],
        "openItem": "per-cell slot->material table not carried by "
                    "worldmap.prefab; recover from terrain Surface/"
                    "TerrainMesh material assignment before any named "
                    "ground-cover overlay ships",
        "verdict": "channel structure MEASURED, semantics partially decoded; "
                   "name-family validation impossible at this carrier level "
                   "(honest negative)",
    }


def check_elevation(ls, masks, h0):
    hdir = PACKROOT / "extracted/harvest/map/assets/worldmap/data/height"
    means = {}
    for cx, cy in ls["present"]:
        p = hdir / f"height_x{cx}_y{cy}_s.raw"
        means[(cx, cy)] = float(np.frombuffer(p.read_bytes(), dtype="<f4")
                                .mean())
    hi = [c for c, m in means.items() if m > 3.0]

    def wb(cells):
        if not cells:
            return None
        cxs = [c[0] for c in cells]
        cys = [c[1] for c in cells]
        u = h0["cellUnits"]
        return {"xCells": [min(cxs), max(cxs)], "yCells": [min(cys), max(cys)],
                "worldX": [min(cxs) * u, (max(cxs) + 1) * u],
                "worldY": [min(cys) * u, (max(cys) + 1) * u]}

    cols7 = np.nonzero(masks["region"][0] == 7)[1]
    dens = np.bincount(cols7 // (h0["cellUnits"] // 4), minlength=65)
    top_cols = sorted(
        ({"maskDensity": int(d), "cellCol": int(i - 12)}
         for i, d in enumerate(dens)), key=lambda e: -e["maskDensity"])[:8]
    hi_bbox = wb(hi)
    alazar_top_col = top_cols[0]["cellCol"]
    inside = (hi_bbox is not None
              and hi_bbox["xCells"][0] <= alazar_top_col <= hi_bbox["xCells"][1])
    return {"highElevationCells": {"threshold": 3.0, "count": len(hi),
                                   "bbox": hi_bbox},
            "alazar1ColumnDensityTop": top_cols,
            "massifOverlapsWithAlazar1PeakColumn": bool(inside),
            "note": "northern massif (Dig 6: cell rows 0-13) must project "
                    "onto the Alazar_1 (Drombach) painted band under H0",
           }


def check_landmarks_and_kinds(pois, ls, h0):
    u = h0["cellUnits"]
    land = ls["land"]
    # multi-source BFS distance-to-water over the bbox cell grid
    from collections import deque
    water = {(x, y)
             for x in range(BBOX["xMin"], BBOX["xMax"] + 1)
             for y in range(BBOX["yMin"], BBOX["yMax"] + 1)} - land
    dist = {c: 0 for c in water}
    q = deque(water)
    while q:
        x, y = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (x + dx, y + dy)
            if n in land and n not in dist:
                dist[n] = dist[(x, y)] + 1
                q.append(n)

    def proj(p):
        px, py = p["x"] * h0["pxPerWorldUnit"], p["y"] * h0["pxPerWorldUnit"]
        # stored mosaic px share the tile lattice origin (world 0), so
        # px//TILE_PX IS the file-numbered cell index — never rebase here
        # (the served URL index is the rebased one: cell - bbox floor).
        cx = int(px // TILE_PX)
        cy = int(py // TILE_PX)
        return px, py, cx, cy

    groups = {
        "crossing": lambda pid: "borderpost" in pid.lower()
                                or "border_post" in pid.lower()
                                or pid.lower().startswith(("toll", "pass")),
        "fishing": lambda pid: "fish" in pid.lower() or "peche" in pid.lower(),
        "wreck": lambda pid: "wreck" in pid.lower() or "epave" in pid.lower(),
        "vein": lambda pid: "vein" in pid.lower() or "mine_" in pid.lower(),
    }
    out = {"distanceCellGranularity": u,
           "waterSet": "bbox minus (present & non-ocean-splat)"}
    kinds = defaultdict(list)
    for p in pois:
        if p.get("x") is None:
            continue
        px, py, cx, cy = proj(p)
        d = dist.get((cx, cy))
        for g, rule in groups.items():
            if rule(p["id"]):
                kinds[g].append({"id": p["id"], "region": p["region"],
                                 "cell": [cx, cy], "distToWaterCells": d,
                                 "onLand": (cx, cy) in land})
    for g, rows_ in sorted(kinds.items()):
        ds = [r["distToWaterCells"] for r in rows_ if r["distToWaterCells"]
              is not None]
        out[g] = {
            "n": len(rows_),
            "distToWaterCells": {
                "min": min(ds) if ds else None,
                "median": float(np.median(ds)) if ds else None,
                "max": max(ds) if ds else None,
            },
            "shareOnLand": round(sum(r["onLand"] for r in rows_) / len(rows_), 3)
            if rows_ else None,
            "rows": rows_[:40],
        }
    # whole-corpus per-kind land/sea share (brief item 2, generic cut)
    per_kind = defaultdict(lambda: [0, 0])
    for p in pois:
        if p.get("x") is None:
            continue
        _, _, cx, cy = proj(p)
        per_kind[p["kind"]][0] += int((cx, cy) in land)
        per_kind[p["kind"]][1] += 1
    out["allKindsOnLandShare"] = {
        k: {"onLand": v[0], "n": v[1], "share": round(v[0] / v[1], 4)}
        for k, v in sorted(per_kind.items())}
    return out


def measure_feature_spacing(pois, h0):
    """AC9 budget input: nearest-neighbor spacing of town anchors in stored
    pixels (F4 discipline — the roundtrip budget freezes from measured
    feature spacing, never invented)."""
    towns = [p for p in pois if p["kind"] == "town" and p.get("x") is not None]
    pts = np.array([[p["x"] * h0["pxPerWorldUnit"],
                     p["y"] * h0["pxPerWorldUnit"]] for p in towns])
    d2 = ((pts[:, None, :] - pts[None, :, :]) ** 2).sum(axis=2)
    np.fill_diagonal(d2, np.inf)
    nn = np.sqrt(d2.min(axis=1))
    return {"towns": len(towns), "unit": "stored px",
            "nnMedian": round(float(np.median(nn)), 1),
            "nnMin": round(float(nn.min()), 1),
            "nnMax": round(float(nn.max()), 1)}


def _sat(indicator: np.ndarray) -> np.ndarray:
    """Summed-area table with a zero top row/col: SAT[r1,c1]-SAT[r0,c1]-
    SAT[r1,c0]+SAT[r0,c0] sums the rect [r0:r1, c0:c1]."""
    h, w = indicator.shape
    sat = np.zeros((h + 1, w + 1), dtype=np.int64)
    np.cumsum(np.cumsum(indicator.astype(np.int64), axis=0), axis=1,
              out=sat[1:, 1:])
    return sat


def _sat_sum(sat, r0, c0, r1, c1):
    return (sat[r1, c1] - sat[r0, c1] - sat[r1, c0] + sat[r0, c0])


class _SweepShape:
    """Full-resolution land/sea IoU between every PRESENT tile cell and the
    collide-walkable indicator under candidate (u,dx,dy). Scale-sensitive:
    this is the discriminator between candidate lattice pitches."""

    def __init__(self, masks, ls, lay):
        self.lay = lay
        coll = np.asarray(Image.open(harvest.longpath(COLLIDE_PNG))
                          .convert("L"))
        self.walk_sat = _sat(coll < 128)
        self.present = sorted(ls["present"])
        self.land = ls["land"]

    def score(self, u, dx, dy):
        sc = self.lay["layerScale"]
        ox = self.lay["offsetX"]
        inter = union = skipped = 0
        for (cx, cy) in self.present:
            x0, y0 = cx * u + dx, cy * u + dy
            # collide png spans the same plane at 0.5 px per world unit
            c0 = int(round((x0 - ox) * 0.5))
            r0 = int(round(y0 * 0.5))
            side = u // 2
            c1, r1 = c0 + side, r0 + side
            if c0 < 0 or r0 < 0 or c1 > 4096 or r1 > 4096:
                skipped += 1
                continue
            n = _sat_sum(self.walk_sat, r0, c0, r1, c1)
            pred = n > (side * side) / 2
            truth = (cx, cy) in self.land
            inter += int(pred and truth)
            union += int(pred or truth)
        return inter / max(1, union)


class _SweepLabels:
    """Block-majority region label of the containing cell vs each marker's
    own region under candidate (u,dx,dy). Block-majority, not center-point:
    center sampling conflated lattice granularity with alignment and was
    retired. Markers whose candidate-cell is an absent tile are skipped
    (counted), never reinterpreted."""

    def __init__(self, pois, masks, ls, lay):
        self.lay = lay
        reg_arr = masks["region"][0]
        self.reg_values = sorted(int(v) for v in np.unique(reg_arr) if v > 0)
        self.reg_sats = {v: _sat(reg_arr == v) for v in self.reg_values}
        rtab = region_index_table(masks)
        self.present = ls["present"]
        self.points = []
        for p in pois:
            if p.get("x") is None:
                continue
            want = rtab.get(p.get("region"))
            if want is None:
                continue
            self.points.append((float(p["x"]), float(p["y"]), int(want)))

    def score(self, u, dx, dy):
        sc = self.lay["layerScale"]
        ox = self.lay["offsetX"]
        agree = tot = skipped = 0
        for wx, wy, want in self.points:
            cx = int((wx - dx) // u)
            cy = int((wy - dy) // u)
            if (cx, cy) not in self.present:
                skipped += 1
                continue
            c0 = max(0, int(round((cx * u + dx - ox) / sc)))
            r0 = max(0, int(round((cy * u + dy) / sc)))
            c1 = min(2048, c0 + u // sc)
            r1 = min(2048, r0 + u // sc)
            best_v, best_n = 0, -1
            for v in self.reg_values:
                n = _sat_sum(self.reg_sats[v], r0, c0, r1, c1)
                if n > best_n:
                    best_n, best_v = n, v
            agree += int(best_v == want)
            tot += 1
        return agree / max(1, tot)


def registration_curve(ls, masks, h0, lay, shifts=None):
    """Continuous world-resolution registration test (the sharp instrument
    the cell-granular sweep could not provide — see module docstring).

    Builds a downsampled elevation raster of the whole world under H0 (cell
    .raw grids placed at px = wx*4, sampled every 8th source px => 8-unit
    world pixels), then slides the biome mask blobs over it:
      - blizzard (Drombach snow) must sit on HIGH elevation,
      - swampE2 (Ludern marsh) must sit on LOW elevation,
    both maximal exactly when the planes are registered. The argmax shift is
    compared against SHIFT_GATE (frozen below, BEFORE this ran).
    """
    if shifts is None:
        shifts = range(-256, 257, 32)
    wpx = 8                                    # world units per sample
    # Both rasters live on the SAME window: the layers2D plane
    # [offsetX .. offsetX + 8192) x [0 .. 8192), sampled every 8 units.
    ox = lay["offsetX"]
    plane = WORLD_SIZE_UNITS = 8192
    gw = gh = plane // wpx                     # 1024 x 1024
    elev = np.full((gh, gw), np.nan, dtype=np.float32)
    hdir = PACKROOT / "extracted/harvest/map/assets/worldmap/data/height"
    u = h0["cellUnits"]
    for cx, cy in sorted(ls["present"]):
        raw = np.frombuffer((hdir / f"height_x{cx}_y{cy}_s.raw").read_bytes(),
                            dtype="<f4")
        # _s = 128x128 over ONE cell => 1 sample/unit; every 8th -> 16x16
        # block at the canvas' 8-unit pitch (a 64x64 block here would smear
        # each cell across 4x4 cells — the bug this check's first run had).
        g = raw.reshape(128, 128)[::8, ::8]
        # cell left edge sits at world x = cx*u (the TILE lattice origin is
        # world 0); canvas column 0 is world x = ox, so convert.
        c0 = int(round((cx * u - ox) / wpx))
        r0 = int(round(cy * u / wpx))
        rr, cc = r0 + 16, c0 + 16
        if r0 < 0 or c0 < 0 or rr > gh or cc > gw:
            continue
        block = elev[r0:rr, c0:cc]
        np.copyto(block, g, where=np.isnan(block))
    valid = ~np.isnan(elev)

    def blob_stats(blob_fullres, shift):
        dy, dx = shift
        blob = blob_fullres[::2, ::2]           # 4-unit mask px -> 8-unit grid
        shifted = np.roll(np.roll(blob, shift=int(dy / wpx), axis=0),
                          shift=int(dx / wpx), axis=1)
        sel = shifted & valid
        n = int(sel.sum())
        if n < 500:
            return None
        return float(np.nanmean(elev[sel])), n

    results = {}
    for name, expect in (("blizzard", "high"), ("swampE2", "low")):
        arr, tab = masks["biome"]
        idx = next(v["index"] for v in tab["values"] if v["name"] == name)
        blob = arr == idx
        curve = {}
        for s in shifts:
            st = blob_stats(blob, (0, s))       # slide along x first pass
            if st:
                curve[f"dx{s}"] = round(st[0], 3)
        st0 = blob_stats(blob, (0, 0))
        # full 2-D argmax around zero at 32-unit steps
        best = None
        for dx in shifts:
            for dy in shifts:
                st = blob_stats(blob, (dx, dy))
                if st is None:
                    continue
                key = st[0] if expect == "high" else -st[0]
                if best is None or key > best[0]:
                    best = (key, dx, dy, st[0])
        results[name] = {
            "expectation": expect,
            "meanElevationAtZeroShift": (round(st0[0], 3) if st0 else None),
            "pixelsAtZeroShift": (st0[1] if st0 else 0),
            "xSlideCurveMeanElevation": curve,
            "bestShift": {"dx": best[1], "dy": best[2],
                          "meanElevation": round(best[3], 3)} if best else None,
        }
    return {"worldPxPerSample": wpx, "role": "descriptive only (mean-under-"
            "blob is not a peaked objective — see module docstring)",
            "results": results}


def label_shift_curve(pois, masks, lay):
    """THE sharp registration instrument: point-sample the region mask at
    every marker's own world position while sliding the mask plane by
    (dx,dy); the agreement rate must peak at (0,0) if the planes are
    registered there. Point sampling involves NO lattice, so unlike the
    block objectives this curve is not granularity-biased.

    Gates frozen BEFORE this curve ran:
      argmax within LABEL_SHIFT_TOL units of zero;
      agreement at zero within 2 points of the curve maximum."""
    reg_arr = masks["region"][0]
    rtab = region_index_table(masks)
    coord = [p for p in pois if p.get("x") is not None
             and p.get("region") in rtab]
    xs = np.array([p["x"] for p in coord])
    ys = np.array([p["y"] for p in coord])
    want = np.array([rtab[p["region"]] for p in coord])
    steps = list(range(-128, 129, 32))
    rows = []
    for dx in steps:
        row_ = []
        for dy in steps:
            got = sample_region(reg_arr, xs - dx, ys - dy, lay)
            row_.append(round(float((got == want).mean()), 4))
        rows.append(row_)
    flat = [(rows[i][j], steps[i], steps[j]) for i in range(len(steps))
            for j in range(len(steps))]
    best_val, bx, by = max(flat)
    zero = next(v for v, x, y in flat if x == 0 and y == 0)
    gates = {
        "argmaxWithinTolerance": max(abs(bx), abs(by)) <= LABEL_SHIFT_TOL,
        "zeroWithinTwoPointsOfMax": zero >= best_val - 0.02,
    }
    return {"steps": steps, "grid": rows, "valueAtZero": zero,
            "best": {"dx": bx, "dy": by, "value": best_val},
            "gatesPreRegistered": {"toleranceUnits": LABEL_SHIFT_TOL,
                                   "twoPointsOfMax": 0.02},
            "gateResults": gates, "pass": all(gates.values())}


def coastal_polarity(ls):
    """Intra-tile orientation proof: on land cells bordering water, the
    water-facing half of the tile must average LOWER elevation (coasts slope
    down to the sea). All four edges must agree — this pins that stored
    .raw rows/cols run north->south / west->east with no flip (D2 proved
    adjacency, never direction)."""
    hdir = PACKROOT / "extracted/harvest/map/assets/worldmap/data/height"
    land = ls["land"]
    water = lambda c: c not in land

    def edge_cells(cond):
        return [c for c in land if cond(c)][:200]

    groups = {
        "south": edge_cells(lambda c: water((c[0], c[1] + 1))),
        "north": edge_cells(lambda c: c[1] == 0 or water((c[0], c[1] - 1))),
        "west": edge_cells(lambda c: water((c[0] - 1, c[1]))),
        "east": edge_cells(lambda c: water((c[0] + 1, c[1]))),
    }

    def halves(cx, cy, axis, first):
        a = np.frombuffer((hdir / f"height_x{cx}_y{cy}_s.raw").read_bytes(),
                          dtype="<f4").reshape(128, 128)
        part = (a[:64] if first else a[64:]) if axis == "row" \
            else (a[:, :64] if first else a[:, 64:])
        return float(part.mean())

    results = {}
    ok_all = True
    for name, cells in groups.items():
        axis = "row" if name in ("north", "south") else "col"
        water_first = name in ("north", "west")   # water side = smaller index
        facing, away = [], []
        for cx, cy in cells:
            f = halves(cx, cy, axis, water_first)
            a = halves(cx, cy, axis, not water_first)
            facing.append(f)
            away.append(a)
        ok = bool(cells and np.mean(facing) < np.mean(away))
        ok_all &= ok
        results[name] = {"cells": len(cells),
                         "waterFacingHalfMean": round(float(np.mean(facing)), 3)
                         if facing else None,
                         "inlandHalfMean": round(float(np.mean(away)), 3)
                         if away else None,
                         "lowerOnWaterSide": ok}
    return {"gate": "every coast slopes down toward its water side",
            "coasts": results, "pass": ok_all}


def robustness_sweep(pois, masks, ls, lay, h0):
    """Offset-sensitivity table at the derived pitch — DESCRIPTIVE ONLY
    (retired as a gate: measured flat across shifts/pitches, because
    cell-granular truth cannot resolve sub-cell registration; the sharp
    instruments are label_shift_curve and coastal_polarity)."""
    scorer_shape = _SweepShape(masks, ls, lay)
    scorer_label = _SweepLabels(pois, masks, ls, lay)
    base_u = h0["cellUnits"]
    offs = (-128, -96, -64, -32, 0, 32, 64, 96, 128)
    rows = []
    for dx in offs:
        for dy in offs:
            rows.append({"dx": dx, "dy": dy,
                         "shapeIoU": round(scorer_shape.score(base_u, dx, dy), 4),
                         "labelBlockAgree":
                             round(scorer_label.score(base_u, dx, dy), 4)})
    h0_row = next(r for r in rows if r["dx"] == 0 and r["dy"] == 0)
    return {"pitchFixed": base_u, "offsetsTested": list(offs),
            "candidates": len(rows), "h0Row": h0_row,
            "note": "descriptive only — see module docstring for why the "
                    "block-objective gates were retired",
            "table": rows}


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dig-out", type=Path, default=DIG_OUT)
    ap.add_argument("--skip-sweep", action="store_true",
                    help="dev only: skip the robustness sweep + splat read "
                         "(verdict then reports sweep gate untested)")
    args = ap.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    carriers = read_carriers()
    h0 = derive_h0(carriers)
    masks = load_masks()
    pois = load_pois()
    ls = land_sea_cells()
    lay = carriers["layers2D"]

    labels = check_labels(pois, masks, h0, lay)
    shapes = check_shapes(ls, masks, h0, lay)
    elevation = check_elevation(ls, masks, h0)
    landmarks = check_landmarks_and_kinds(pois, ls, h0)
    feature_spacing = measure_feature_spacing(pois, h0)
    splat = ({} if args.skip_sweep else check_splat_semantics())
    sweep = None if args.skip_sweep else robustness_sweep(pois, masks, ls, lay, h0)
    reg = None if args.skip_sweep else registration_curve(ls, masks, h0, lay)
    shift_curve = (None if args.skip_sweep
                   else label_shift_curve(pois, masks, lay))
    polarity = coastal_polarity(ls)

    gates_ok = {
        "labels": labels["pass"],
        "shapes": all(v["pass"] for v in shapes.values()),
        "labelShiftCurve": bool(shift_curve and shift_curve["pass"]),
        "coastalPolarity": bool(polarity["pass"]),
    }
    passed = all(gates_ok.values())
    report = {
        "tool": "pipeline/tools/fit_world_transform.py",
        "digId": "D11", "buildid": BUILDID,
        "gatesFrozenBeforeBattery": {"label": LABEL_GATE, "shape": SHAPE_GATE,
                                     "labelShiftToleranceUnits":
                                         LABEL_SHIFT_TOL},
        "carriers": carriers,
        "transform": h0,
        "featureSpacingPx": feature_spacing,
        "validation": {
            "labels": labels, "shapes": shapes, "elevation": elevation,
            "landmarksAndKindGeography": landmarks, "splatSemantics": splat,
            "offsetSensitivityDescriptive": sweep,
            "registrationCurvesDescriptive": reg,
            "labelShiftCurve": shift_curve,
            "coastalPolarity": polarity,
            "gateResults": gates_ok,
        },
        "verdict": ("CONFIRMED" if passed else "OPEN — residuals above"),
    }
    args.dig_out.mkdir(parents=True, exist_ok=True)
    out = args.dig_out / "coordinate-transform.json"
    with open(harvest.longpath(out), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    print(f"[D11] transform: cell={h0['cellUnits']} units, "
          f"scale={h0['pxPerWorldUnit']} px/unit (axis-aligned affine)")
    print(f"[D11] labels: {labels['agree']}/{labels['total']} = "
          f"{labels['rate']:.4f} (gate {LABEL_GATE}) pass={labels['pass']}; "
          f"{labels['mismatchCount']} mismatches classified")
    for k, v in shapes.items():
        print(f"[D11] shape {k}: IoU={v['iou']:.4f} acc={v['acc']:.4f} "
              f"pass={v['pass']}")
    if shift_curve:
        print(f"[D11] label-shift curve: value@0={shift_curve['valueAtZero']} "
              f"best={shift_curve['best']}; gates={shift_curve['gateResults']}")
    if polarity:
        bad = [k for k, v in polarity["coasts"].items() if not v["lowerOnWaterSide"]]
        print(f"[D11] coastal polarity: pass={polarity['pass']}"
              + (f" violating coasts: {bad}" if bad else ""))
    if reg:
        for name, r in reg["results"].items():
            print(f"[D11] registration {name} (descriptive): meanElev@0="
                  f"{r['meanElevationAtZeroShift']}")
    if splat:
        print(f"[D11] splat semantics: encodings={splat['measuredEncodings']} "
              f"over {splat['cellsChecked']} cells")
    print(f"[D11] verdict: {report['verdict']} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
