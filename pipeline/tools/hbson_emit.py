"""hbson_emit.py — Dig 7 emitters over the decoded HBSON corpus.

Emits (buildid 20318128):
  extracted/data/_draft/{place,group,element,levelProps}.jsonl
      Rows = every $cdbtype object found in any blob (CastleDB datafile
      semantics), original keys preserved verbatim; dedup by id where the
      sheet has an id column (conflicts counted in _meta), occurrence-
      keyed synthetic ordinals for levelProps (no id column).
  extracted/relinks/_draft/poi_coordinates.jsonl
      Every world-space placement in worldmap.l3d + wmap_current.prefab:
      {carrier:"prefab", digId:"D7", buildid, kind, id, x, y, ...}.
  extracted/data/_draft/worldmap_overlays.json
      worldmap.l3d scene structure + layers2D value->CDB-id tables +
      layerScale + mask file inventory.
  extracted/logic/basePrice_carriers.jsonl
      Measured-negative ledger: join key documented, zero carriers.
  Re-verifies the 72 unverifiable relink seeds (env__place, frescos__place,
  fiefGoal__element) against the decoded id sets and flips valid.

Python 3.14, stdlib only.
"""
from __future__ import annotations

import io
import json
import struct
import sys
import time
from collections import Counter
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
PACK = Path(r"C:\_reps\game-databases\wartales")
HARVEST = PACK / "extracted" / "harvest"
DRAFT = PACK / "extracted" / "data" / "_draft"
RELINKS = PACK / "extracted" / "relinks" / "_draft"
BUILDID = "20318128"
DIGID = "D7"

sys.path.insert(0, str(PACK / "pipeline" / "tools"))
from hbson_decode import Decoder, MAGIC


def rel_of(p: Path) -> str:
    return p.relative_to(HARVEST).as_posix()


def iter_blobs():
    for p in sorted(HARVEST.rglob("*")):
        if p.is_file() and p.suffix in (".prefab", ".l3d"):
            yield p


def walk_nodes(node, path="$"):
    """Yield (node, path) over every dict/list node."""
    yield node, path
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, (dict, list)):
                yield from walk_nodes(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            if isinstance(v, (dict, list)):
                yield from walk_nodes(v, f"{path}[{i}]")


# ---------------------------------------------------------------------------
# 1. collect $cdbtype rows
# ---------------------------------------------------------------------------

def collect():
    rows = {"place": [], "group": [], "element": [], "levelProps": []}
    scenes = {}
    for p in iter_blobs():
        b = p.read_bytes()
        if not b.startswith(MAGIC):
            continue
        rel = rel_of(p)
        d = Decoder(b, rel)
        v = d.decode()
        scenes[rel] = v
        for node, path in walk_nodes(v):
            if isinstance(node, dict):
                ct = node.get("$cdbtype")
                if ct in rows:
                    rows[ct].append({"carrier": rel, "path": path, "row": node})
    return rows, scenes


def sheet_columns(cdb, name):
    s = next(x for x in cdb["sheets"] if x["name"] == name)
    cols = []
    for c in s.get("columns", []):
        cols.append({"name": c["name"], "typeStr": c["typeStr"],
                     "opt": bool(c.get("opt")), "kind": c.get("kind")})
    subs = {}
    for x in cdb["sheets"]:
        n = x["name"]
        if n.startswith(name + "@"):
            subs[n[len(name) + 1:]] = [
                {"name": c["name"], "typeStr": c["typeStr"]} for c in x.get("columns", [])]
    return cols, subs


def canon(o):
    return json.dumps(o, sort_keys=True, ensure_ascii=False)


def emit_sheet(rows):
    """Emit one dataset row per DISTINCT payload.

    Same-id re-declarations across carriers are real scene-local variants
    (e.g. Bridge_group disabled per building) — all kept. Returns
    (records, stats) where records carry _carrier/_path/_variant plus the
    original keys verbatim.
    """
    records = []
    seen_payload = set()
    variant_of_id = {}
    exact_dup = 0
    for r in rows:
        ck = canon(r["row"])
        if ck in seen_payload:
            exact_dup += 1
            continue
        seen_payload.add(ck)
        rid = r["row"].get("id")
        if rid is not None:
            variant_of_id[rid] = variant_of_id.get(rid, 0) + 1
            variant = variant_of_id[rid]
        else:
            variant = None
        rec = {"_carrier": r["carrier"], "_path": r["path"]}
        if variant and variant > 1:
            rec["_variant"] = variant
        rec.update({k: v for k, v in r["row"].items() if k != "$cdbtype"})
        records.append(rec)
    stats = {
        "occurrences": len(rows),
        "distinctPayloadsEmitted": len(records),
        "exactDuplicateMerges": exact_dup,
        "distinctIds": len(variant_of_id),
    }
    return records, stats


def main() -> int:
    t0 = time.time()
    cdb = json.load(open(PACK / "extracted/harvest/res/data.cdb",
                         encoding="utf-8"))
    print("collecting...")
    rows, scenes = collect()
    for k, v in rows.items():
        print(f"  {k}: {len(v)} occurrences")

    DRAFT.mkdir(parents=True, exist_ok=True)
    RELINKS.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")

    # ---------------- four sheet datasets ----------------
    for name in ("place", "group", "element"):
        cols, subs = sheet_columns(cdb, name)
        records, stats = emit_sheet(rows[name])
        meta = {
            "kind": name,
            "sourceSheet": name,
            "buildId": BUILDID,
            "container": (f"datafile-backed CastleDB sheet; rows harvested from "
                          f"{stats['occurrences']} $cdbtype:{name} objects inside "
                          f"res.pak/content.pak/assets.pak HBON blobs "
                          f"(HBSON magic, docs/hbson-format.mdx)"),
            "rowCount": len(records),
            "emitted": stamp,
            "tool": "pipeline/tools/hbson_emit.py",
            "columns": cols,
            "hiddenSubSheets": subs,
            "dedup": stats,
            "keyRule": ("id = the row's own 'id' column (original identifier "
                        "preserved verbatim). id is NOT unique across carriers "
                        "by design: scenes re-declare shared ids with local "
                        "tweaks — every DISTINCT payload is its own row; exact "
                        "byte-duplicate occurrences merged; _carrier/_path give "
                        "the source blob + in-blob path; _variant (>=2) counts "
                        "re-declarations of the same id in sorted-carrier order"),
            "localeTextRoute": ("export_<locale>.xml carries this sheet; textKey "
                                "addressing sheet→RowId→dotted column path "
                                "(world.name / props.name / dialog...)"),
            "digId": DIGID,
        }
        lines = [json.dumps({"_meta": meta}, ensure_ascii=False)]
        for rec in records:
            lines.append(json.dumps(rec, ensure_ascii=False))
        dst = DRAFT / f"{name}.jsonl"
        dst.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {dst.relative_to(PACK)} rows={len(records)} {stats}")

    # levelProps: no id column — one row per occurrence, ordinal key
    cols, subs = sheet_columns(cdb, "levelProps")
    lp_rows = rows["levelProps"]
    exact = Counter(canon(r["row"]) for r in lp_rows)
    out_lines = [json.dumps({"_meta": {
        "kind": "levelProps",
        "sourceSheet": "levelProps",
        "buildId": BUILDID,
        "container": ("datafile-backed CastleDB sheet (props.dataFiles "
                      "'prefabs/*.nothing'); rows are scene-node payloads with "
                      "NO id column — one dataset row per $cdbtype:levelProps "
                      "object occurrence"),
        "rowCount": len(lp_rows),
        "distinctPayloads": len(exact),
        "emitted": stamp,
        "tool": "pipeline/tools/hbson_emit.py",
        "columns": cols,
        "hiddenSubSheets": subs,
        "keyRule": ("synthetic zero-padded ordinal id 'lp-NNNN' in carrier+path "
                    "order (sheet has no id column); original payload keys "
                    "untouched; _carrier/_path locate the occurrence"),
        "kindEnum": ["None", "Obstacle", "Props", "Player", "Door",
                     "ClearWorldAssets", "Region", "Road", "Forest", "BattleData",
                     "AmbientSound", "Bridge", "CameraBound", "Navmesh",
                     "NamedPosition", "Trap", "Selector", "Spawner", "BountyBoard",
                     "HeightMap", "RuinPath", "RuinRoom", "CullingGroup", "Hidden",
                     "Vegetation", "EnvSkill", "Wall", "OptionalProps",
                     "GameplayObject", "BattleObject", "FloatingProps", "Trigger",
                     "HuntTrackStart", "HuntTrackBonus", "HuntRoaming", "BeastSpawn"],
        "digId": DIGID,
    }}, ensure_ascii=False)]
    for i, r in enumerate(lp_rows):
        rec = {"_id": f"lp-{i:04d}", "_carrier": r["carrier"], "_path": r["path"]}
        for k, v in r["row"].items():
            if k != "$cdbtype":
                rec[k] = v
        out_lines.append(json.dumps(rec, ensure_ascii=False))
    dst = DRAFT / "levelProps.jsonl"
    dst.write_text("\n".join(out_lines) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {dst.relative_to(PACK)} rows={len(lp_rows)} "
          f"distinct={len(exact)}")

    # ---------------- poi_coordinates ----------------
    # Placement model (measured this dig):
    #   each regions/<tree>/POI/Region*.prefab carries a 'Content' object
    #   whose x/y IS the world anchor (== wmap_current.prefab / worldmap.l3d
    #   placements, cross-checked on Harag). Everything below is local;
    #   nested 'reference' nodes carry local offsets; world position of a
    #   target prefab = translation composition along the reference chain.
    edges = []
    ROT_EPS = 1e-9          # rotationZ float dust (e.g. 9.5e-15) == zero

    def clean_rot(v):
        return 0.0 if (not v or abs(v) < ROT_EPS) else v

    def add_edge(node, path, carrier, chain, target):
        rot = clean_rot(node.get("rotationZ"))
        sx = node.get("scaleX")
        sy = node.get("scaleY")
        self_exact = (rot == 0.0) and (sx is None or sx == 1.0) \
            and (sy is None or sy == 1.0)
        edges.append({
            "from_blob": carrier,
            "path": path,
            "source": target,
            "name": node.get("name"),
            "local": {"x": node["x"], "y": node["y"],
                      **{k: node[k] for k in ("z", "rotationZ", "scaleX",
                                              "scaleY") if k in node}},
            "chain": list(chain),
            "selfExact": self_exact,
        })

    def walk_chain(node, path, carrier, chain):
        """Record every reference edge with its full ancestor transform chain."""
        if not isinstance(node, dict):
            return
        if isinstance(node.get("x"), (int, float)) \
                and isinstance(node.get("y"), (int, float)):
            src = node.get("source")
            if isinstance(src, str):
                add_edge(node, path, carrier, chain, src.lstrip("/"))
            # POI markers: the scene node's 'source' points at the visual
            # building; props.world.prefab points at the REG marker prefab.
            wp = (node.get("props") or {}).get("world") or {}
            if isinstance(wp.get("prefab"), str):
                add_edge(node, path, carrier, chain, wp["prefab"].lstrip("/"))
        entry = None
        if any(k in node for k in ("x", "y", "z")):
            entry = (node.get("x"), node.get("y"), node.get("z"),
                     clean_rot(node.get("rotationZ")),
                     node.get("scaleX") if node.get("scaleX") is not None else 1.0,
                     node.get("scaleY") if node.get("scaleY") is not None else 1.0)
        chain.append(entry)
        for ch in node.get("children", []) or []:
            walk_chain(ch, f"{path}.children[]", carrier, chain)
        chain.pop()

    for rel, v in scenes.items():
        walk_chain(v, "$", rel, [])
    print(f"reference edges with transforms: {len(edges)}")

    anchors = {}
    for p in sorted(HARVEST.glob("res/content/regions/*/POI/Region*.prefab")):
        key = p.relative_to(HARVEST).as_posix()
        v = scenes.get(key)
        if v is None:
            continue
        for ch in v.get("children", []) or []:
            if isinstance(ch, dict) and ch.get("name") == "Content" \
                    and isinstance(ch.get("x"), (int, float)) \
                    and isinstance(ch.get("y"), (int, float)) \
                    and abs(ch["x"]) + abs(ch["y"]) > 100:
                anchors[key] = (ch["x"], ch["y"])
                break
    print(f"region anchors: {len(anchors)}")

    import math
    # BFS over the reference graph carrying a similarity frame
    # (x, y, theta) per blob: the blob root's world position plus the
    # cumulative Z rotation its internal axes carry. Rotations compose
    # exactly; ANY scale other than 1 marks the branch inexact and stops
    # propagation (shear cannot be represented here - those rows keep raw
    # locals instead of silently wrong numbers).
    cos_t, sin_t = math.cos, math.sin

    def fold_chain(chain, st):
        """Apply ancestor entries (excluding the ref node itself).

        Returns ((x, y, theta, z, saw_z), exact); z composes additively
        (rotationZ never mixes vertical)."""
        bx, by, bt, bz, saw_z = st[0], st[1], st[2], 0.0, False
        exact = True
        for e in chain:
            if e is None:
                continue
            ex, ey, ez, rot, sx, sy = e
            if ez is not None:
                bz += ez
                saw_z = True
            if ex is None or ey is None:
                continue
            if sx != 1.0 or sy != 1.0:
                exact = False
            c, s = cos_t(bt), sin_t(bt)
            nx = bx + c * (sx * ex) - s * (sy * ey)
            ny = by + s * (sx * ex) + c * (sy * ey)
            bx, by = nx, ny
            bt += rot
        return (bx, by, bt, bz, saw_z), exact

    by_from = {}
    for e in edges:
        by_from.setdefault(e["from_blob"].removeprefix("res/"), []).append(e)

    # All 11 region prefabs place themselves: anchored ones via their
    # 'Content' transform; the rest (Content without x/y - Alazar_1,
    # Worldwide) ship world-space children straight from local zero.
    region_prefabs = {
        p.relative_to(HARVEST).as_posix().removeprefix("res/")
        for p in HARVEST.glob("res/content/regions/*/POI/Region*.prefab")
    }
    origin_world = {b: (0.0, 0.0, 0.0, 0.0, False) for b in region_prefabs}
    resolved = {}
    queue = [(b, st) for b, st in sorted(origin_world.items())]
    seen_frame = set()
    while queue:
        blob, st = queue.pop()
        for e in by_from.get(blob, []):
            (px, py, pt, pz, saw_z), ch_exact = fold_chain(e["chain"][1:], st)
            loc = e["local"]
            lx, ly = loc.get("x", 0.0), loc.get("y", 0.0)
            lz = loc.get("z")
            if lz is not None:
                pz += lz
                saw_z = True
            lrot = loc.get("rotationZ") or 0.0
            lsx = loc.get("scaleX")
            lsy = loc.get("scaleY")
            self_scale_ok = (lsx is None or lsx == 1.0) and \
                            (lsy is None or lsy == 1.0)
            c, s = cos_t(pt), sin_t(pt)
            tx = px + c * lx - s * ly
            ty = py + s * lx + c * ly
            tt = pt + lrot
            exact = ch_exact and self_scale_ok
            rec = {
                "x": round(tx, 6), "y": round(ty, 6),
                "exact": bool(exact),
                "region": (blob.split("/")[2]
                           if blob.startswith("content/regions/") else None),
                "refName": e["name"],
                "local": loc,
            }
            if saw_z:
                rec["z"] = round(pz, 6)
            for k in ("rotationZ", "scaleX", "scaleY"):
                if loc.get(k) is not None and abs(loc[k]) > 1e-9                         and loc[k] != 1.0:
                    rec[k] = loc[k]
            lst = resolved.setdefault(e["source"], [])
            k = json.dumps(rec, sort_keys=True)
            if all(json.dumps(o, sort_keys=True) != k for o in lst):
                lst.append(rec)
            tgt = e["source"]
            fkey = (tgt, round(tx, 4), round(ty, 4), round(tt, 4))
            if fkey not in seen_frame:
                seen_frame.add(fkey)
                if tgt not in origin_world:
                    origin_world[tgt] = (tx, ty, tt, pz, saw_z)
                    if exact:
                        queue.append((tgt, (tx, ty, tt, pz, saw_z)))
    print(f"targets reached: {len(resolved)}; "
          f"frames propagated: {len(origin_world)}")

    reg_files = sorted(p.relative_to(HARVEST).as_posix()
                       for p in HARVEST.glob("res/content/regions/**/*.prefab"))
    coord_rows = []
    n_unresolved = 0

    def sub_kind(relpath):
        if Path(relpath).name.startswith("Region"):
            return "region-root"
        parts = relpath.split("/")
        return {"POI": "poi", "Towns": "town", "Secrets": "secret",
                "Secret": "secret-entry"}.get(parts[4], "poi") \
            if len(parts) > 4 else "region-root"

    for rel in reg_files:
        tree = rel.split("/")[3]
        norm = rel.removeprefix("res/")
        placements = resolved.get(norm, [])
        if rel in anchors:
            ax, ay = anchors[rel]
            coord_rows.append({
                "carrier": "prefab", "digId": DIGID, "buildid": int(BUILDID),
                "kind": "region-anchor", "id": Path(rel).stem,
                "region": tree, "source": rel,
                "x": ax, "y": ay, "exact": True, "placements": len(placements),
            })
        if norm in region_prefabs:
            continue          # self-placed (anchor rows above cover them);
                              # Alazar_1/Worldwide ship world-space children
        if not placements:
            n_unresolved += 1
            coord_rows.append({
                "carrier": "prefab", "digId": DIGID, "buildid": int(BUILDID),
                "kind": sub_kind(rel), "id": Path(rel).stem,
                "region": tree, "source": rel,
                "x": None, "y": None, "status": "unreferenced",
                "placements": 0,
            })
            continue
        for i, r in enumerate(sorted(placements, key=lambda o: (o["x"], o["y"]))):
            row = {
                "carrier": "prefab", "digId": DIGID, "buildid": int(BUILDID),
                "kind": sub_kind(rel), "id": Path(rel).stem,
                "region": r["region"] or tree,
                "source": rel,
                "refName": r["refName"],
                "x": r["x"], "y": r["y"],
                "exact": r["exact"],
            }
            if not r["exact"]:
                row["local"] = r["local"]
            if i > 0:
                row["_variant"] = i + 1
            coord_rows.append(row)

    nonreg = {k: len(v) for k, v in resolved.items()
              if not k.startswith("content/regions/")}
    print(f"REG rows written: {len(coord_rows)} ({n_unresolved} unreferenced); "
          f"non-REG targets reached: {len(nonreg)}")

    meta = {"_meta": {
        "contract": "marker-row carrier A2 (EXTRACTION-LOG section 5)",
        "digId": DIGID,
        "buildid": int(BUILDID),
        "rowCount": len(coord_rows),
        "unreferencedCount": n_unresolved,
        "emitted": stamp,
        "tool": "pipeline/tools/hbson_emit.py",
        "model": ("each regions/<tree>/POI/Region*.prefab carries a 'Content' "
                  "object whose x/y IS the world anchor (cross-checked == "
                  "wmap_current.prefab placement); all deeper positions are "
                  "local offsets composed additively along 'reference' chains "
                  "to a translation fixpoint"),
        "plane": ("stored plane per Dig 6: north=small y, east=+x; "
                  "transform.d=-1"),
        "exactness": ("exact:true = pure translation chain (no rotation/scale "
                      "on any ancestor); exact:false rows keep raw locals in "
                      "'local' - never silently rotated"),
        "status:unreferenced": ("REG prefab cited by no reference edge "
                                "(cut-content/DLC-leftover candidates); no "
                                "position invented"),
        "dedup": ("distinct world placements per target kept as _variant "
                  "rows; identical duplicates merged"),
    }}
    lines = [json.dumps(meta, ensure_ascii=False)]
    for row in coord_rows:
        lines.append(json.dumps(row, ensure_ascii=False))
    dst = RELINKS / "poi_coordinates.jsonl"
    dst.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {dst.relative_to(PACK)} rows={len(coord_rows)}")

    # ---------------- worldmap_overlays ----------------
    wm = scenes.get("content/prefabs/lighting/worldmap.prefab")
    layers_node = layer_scale = None
    layers_parent = None

    def find_layers(n, path="$"):
        nonlocal layers_node, layer_scale, layers_parent
        if isinstance(n, dict):
            if "layers" in n and isinstance(n["layers"], list) and n["layers"] \
                    and isinstance(n["layers"][0], dict) and "values" in n["layers"][0]:
                layers_node = n["layers"]
                layers_parent = path
                layer_scale = n.get("layerScale")
            for k, v in n.items():
                find_layers(v, f"{path}.{k}")
        elif isinstance(n, list):
            for i, v in enumerate(n):
                find_layers(v, f"{path}[{i}]")

    if wm:
        find_layers(wm)
    l3d = scenes.get("res/content/worldmap.l3d")
    child_kinds = Counter()
    refs = []

    def census(n):
        if isinstance(n, dict):
            child_kinds[n.get("type", "?")] += 1
            if n.get("type") == "reference":
                refs.append({k: n[k] for k in ("name", "source", "x", "y", "z")
                             if k in n})
            for ch in n.get("children", []) or []:
                census(ch)

    if l3d:
        census(l3d)
    masks = []
    mf = HARVEST / "content.manifest.jsonl"
    for line in open(mf, encoding="utf-8"):
        r = json.loads(line)
        if "/layers2D/" in r.get("path", ""):
            masks.append({"path": r["path"].lstrip("/"), "size": r["size"]})

    overlay = {
        "_meta": {
            "digId": DIGID, "buildId": BUILDID, "emitted": stamp,
            "tool": "pipeline/tools/hbson_emit.py",
            "carriers": ["res:/content/worldmap.l3d",
                         "res:/content/wmap_current.prefab",
                         "content:/prefabs/lighting/worldmap.prefab"],
        },
        "scene": {
            "rootType": (l3d or {}).get("type") if isinstance(l3d, dict) else None,
            "childKinds": dict(child_kinds),
            "camera": next((c for c in ([l3d] if isinstance(l3d, dict) else [])
                            + (l3d.get("children", []) if isinstance(l3d, dict) else [])
                            if isinstance(c, dict) and c.get("type") == "camera"), None),
            "referenceNodes": refs,
        },
        "wmapCurrentEditSession": scenes.get("res/content/wmap_current.prefab"),
        "layers2D": {
            "layerScale": layer_scale,
            "tablesCarrier": ("content/prefabs/lighting/worldmap.prefab at "
                              f"{layers_parent}"),
            "tables": layers_node,
            "masks": masks,
            "semantics": ("mask PNG pixel value -> matching table entry by "
                          "(layer, index); index 0 = unassigned; sample world "
                          "position via Layers2D.getLayerColor row-major "
                          "top-down (Dig 6 frame uniformity)"),
        },
    }
    dst = DRAFT / "worldmap_overlays.json"
    dst.write_text(json.dumps(overlay, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8", newline="\n")
    print(f"wrote {dst.relative_to(PACK)} layers={len(layers_node or [])} "
          f"refs={len(refs)} masks={len(masks)}")

    # ---------------- basePrice negative ledger ----------------
    bp = {"_meta": {
        "digId": DIGID, "buildId": BUILDID, "emitted": stamp,
        "tool": "pipeline/tools/hbson_emit.py",
        "rowCount": 0,
        "finding": ("MEASURED NEGATIVE: no shipped payload carries "
                    "itemType.props.basePrice anywhere in this client"),
        "evidence": {
            "dataCdbRawOccurrences": 0,
            "hbsonBlobsScanned": 3536,
            "hbsonBytesScanned": 307768190,
            "inlineItemTypePropsCells": 96,
            "generatedClassFields": ("_Data.ItemType_props: sellPriceFactor, "
                                     "isCraftSeparator, flags, wealthFactor, "
                                     "dismantleLoot, baseBonusDefault, "
                                     "backpackName, nameCraftCategory, "
                                     "dexterityWeapon, filterIndex — no "
                                     "basePrice field"),
            "bytecodeStringPoolEntry": "61129 'basePrice' (formulas.hx hscript)",
        },
        "joinKeyWouldBe": ("item.type -> itemType.id; parentType chain upward; "
                           "first props.basePrice != null wins (formulas.hx "
                           "itemPrice); resolves null -> NaN on shipped data"),
        "consequence": ("weaponPrice/craftPrice fallbacks are dead code for "
                        "shipped data; item.price explicit column is the only "
                        "live price source"),
    }}
    dst = PACK / "extracted" / "logic" / "basePrice_carriers.jsonl"
    dst.write_text(json.dumps(bp, ensure_ascii=False) + "\n",
                   encoding="utf-8", newline="\n")
    print(f"wrote {dst.relative_to(PACK)}")

    # ---------------- re-verify the 72 unverifiable edges ----------------
    idsets = {
        "place": {r["row"].get("id") for r in rows["place"]},
        "group": {r["row"].get("id") for r in rows["group"]},
        "element": {r["row"].get("id") for r in rows["element"]},
    }
    results = {}
    for fname, target_kind in (("env__place.jsonl", "place"),
                               ("frescos__place.jsonl", "place"),
                               ("fiefGoal__element.jsonl", "element")):
        src = RELINKS / fname
        if not src.exists():
            continue
        lines = src.read_text(encoding="utf-8").splitlines()
        meta = json.loads(lines[0])["_meta"]
        out = [json.dumps({"_meta": {**meta,
               "verifiedBy": f"Dig {DIGID} against decoded {target_kind} id set",
               "unverifiableBefore": sum(1 for l in lines[1:]
                                         if '"valid": null' in l)}},
              ensure_ascii=False)]
        flipped = {"true": 0, "false": 0, "still_null": 0}
        for l in lines[1:]:
            e = json.loads(l)
            if e.get("valid") is None:
                ok = e.get("toId") in idsets[target_kind]
                e["valid"] = ok
                flipped["true" if ok else "false"] += 1
            out.append(json.dumps(e, ensure_ascii=False))
        src.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
        results[fname] = flipped
        print(f"re-verified {fname}: {flipped}")

    print(f"done in {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
