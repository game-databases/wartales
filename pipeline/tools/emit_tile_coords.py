#!/usr/bin/env python3
"""emit_tile_coords.py — D11 deliverable: tile-space join of POI coordinates.

Reads ``extracted/relinks/_draft/poi_coordinates.jsonl`` (Dig 7 carrier A2
rows) and the measured transform record
``output/_dig-map/coordinate-transform.json`` (fit_world_transform.py), and
emits ``extracted/relinks/_draft/poi_tile_coords.jsonl``: every original row
verbatim plus a ``tile`` block giving

  px/py      stored-plane mosaic pixels   (px = a*wx + tx, py = dGrid*wy + ty)
  cell       the owning albedo cell        [cx, cy]
  z3         served tile index at native zoom (rebased, non-negative) + URL

Rows without coordinates (status unreferenced) are carried through verbatim
with no invented geometry. Land/sea flag uses the payload-hash geography rule
(no-splat ocean mask family 78c858d4 over present cells).

Usage:
  python pipeline/tools/emit_tile_coords.py [--buildid 20318128]

Python 3.14, stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

PACKROOT = Path(__file__).resolve().parents[2]
POI_IN = PACKROOT / "extracted/relinks/_draft/poi_coordinates.jsonl"
TRANSFORM = PACKROOT / "output/_dig-map/coordinate-transform.json"
MANIFEST = PACKROOT / "output/_dig-map/map.manifest.jsonl"
OUT = PACKROOT / "extracted/relinks/_draft/poi_tile_coords.jsonl"


def require(cond, msg):
    if not cond:
        raise SystemExit(f"emit_tile_coords: FAIL-LOUD: {msg}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--buildid", type=int, default=20318128)
    args = ap.parse_args(argv)

    doc = json.loads(TRANSFORM.read_text(encoding="utf-8"))
    require(doc.get("verdict", "").startswith("CONFIRMED"),
            f"transform verdict {doc.get('verdict')!r} — refusing to project")
    t = doc["transform"]
    a = t["worldToStoredPx"]["a"]
    b = t["worldToStoredPx"]["b"]
    tx0 = t["worldToStoredPx"]["tx"]
    c = t["worldToStoredPx"]["c"]
    dg = t["worldToStoredPx"]["dGrid"]
    ty0 = t["worldToStoredPx"]["ty"]
    u = t["cellUnits"]
    x_min, y_min = -8, 0     # map_tiles.BBOX floors (served rebase)

    sea_splat = set()
    rx_count = 0
    with open(MANIFEST, encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            m = None
            m = re.search(r"/splat/splat_x(-?\d+)_y(\d+)\.dds$", row["path"])
            if m:
                if row["hash"] == "78c858d4":
                    sea_splat.add((int(m.group(1)), int(m.group(2))))
            rx_count += 1
    require(rx_count > 0, "rerun manifest empty")

    rows_out = []
    stats = Counter()
    with open(POI_IN, encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            if "_meta" in rec:
                continue
            out = dict(rec)
            if rec.get("x") is not None and rec.get("y") is not None:
                wx, wy = float(rec["x"]), float(rec["y"])
                px = a * wx + b * wy + tx0
                py = c * wx + dg * wy + ty0
                cx = int(wx // u)
                cy = int(wy // u)
                cy = int(wy // u)
                on_land = ((cx, cy) not in sea_splat)
                in_bbox = (-8 <= cx <= 43 and 0 <= cy <= 39)
                # served indices exist only inside the measured pyramid —
                # an off-plane marker keeps honest px/cell but no URL
                z3_tile = [cx - x_min, cy - y_min] if in_bbox else None
                z3_url = (f"/map-tiles/v{args.buildid}/albedo/3/"
                          f"{cx - x_min}/{cy - y_min}.webp") if in_bbox else None
                out["tile"] = {
                    "plane": "stored",
                    "px": round(px, 3), "py": round(py, 3),
                    "cell": [cx, cy],
                    "z3Tile": z3_tile,
                    "z3Url": z3_url,
                    "inAlbedoBbox": in_bbox,
                    "onLandBySplatHash": on_land,
                }
                stats[f"{rec['kind']}:projected"] += 1
                stats["bbox:inside" if in_bbox else "bbox:outside"] += 1
                stats["land" if on_land else "seaCell"] += 1
            else:
                stats["nullCarriedThrough"] += 1
            rows_out.append(out)

    meta = {
        "_meta": {
            "contract": "marker-row carrier A2 (EXTRACTION-LOG section 5)",
            "digId": "D11", "buildid": args.buildid,
            "source": "extracted/relinks/_draft/poi_coordinates.jsonl (Dig 7)",
            "transform": {
                "measurement": "output/_dig-map/coordinate-transform.json",
                "tool": "pipeline/tools/fit_world_transform.py",
                "model": t["model"],
                "cellUnits": u,
                "pxPerWorldUnit": t["pxPerWorldUnit"],
                "formula": "px = a*wx + tx ; py = dGrid*wy + ty "
                           "(stored mosaic plane; origin = top-left corner "
                           "of tile column x0 / row y0)",
                "servedRebase": f"z3 tile index = cell - bbox floor "
                                f"(xMin={x_min}, yMin={y_min}); URL shape A1 "
                                f"untouched",
            },
            "rowCount": len(rows_out),
            "stats": dict(sorted(stats.items())),
            "tool": "pipeline/tools/emit_tile_coords.py",
            "note": "original Dig 7 fields preserved verbatim; 'tile' block "
                    "added by this join; null-coordinate rows carried "
                    "through with no invented geometry",
        }
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(meta, ensure_ascii=False,
                            separators=(",", ":")) + "\n")
        for r in rows_out:
            fh.write(json.dumps(r, ensure_ascii=False,
                                separators=(",", ":")) + "\n")
    print(f"[D11] {OUT.name}: {len(rows_out)} rows "
          f"({stats['bbox:inside']} inside bbox, "
          f"{stats['bbox:outside']} outside, "
          f"{stats['nullCarriedThrough']} null carried through)")
    print(f"[D11] stats: {dict(sorted(stats.items()))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
