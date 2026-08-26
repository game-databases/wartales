"""Export CDB icon refs to the versioned webp CDN set (dig: icons).

Resolution mechanism pinned by this dig:
  a CDB type-14 `icon` value is an atlas descriptor {file, size, x, y};
  `file` resolves under assets.pak root (harvest: extracted/harvest/assets/),
  the pixel rect is (x*size, y*size, size, size). All referenced atlases are
  genuine PNG by magic (TOOL §3 route-by-magic), so Pillow decodes directly —
  texconv is not needed on this set. `.asl` files are Photoshop layer styles,
  not an addressing layer; style.css `background-tile-pos` corroborates
  tile-index addressing.

Outputs (under output/cdn/v{buildid}/):
  {kind}/{id}.webp   resolved icon, original pixel size, lossless
  {kind}/{id}.webp   placeholder for explicit-missing state (named in misses.jsonl)
  misses.jsonl       one record per explicit-missing entity, with reason
  resolution-proof.jsonl  per-kind proof rows (>=20 samples) + full rates

Run: python pipeline/tools/icon_export.py
"""

import json
import os
import sys
from collections import Counter, defaultdict

from PIL import Image, ImageDraw

Image.MAX_IMAGE_PIXELS = None

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
DRAFT = os.path.join(ROOT, "extracted", "data", "_draft")
ASSETS = os.path.join(ROOT, "extracted", "harvest", "assets")
BUILD = "20318128"
OUT = os.path.join(ROOT, "output", "cdn", f"v{BUILD}")
KINDS = ["item", "skill", "class"]
PROOF_MIN = 20


def placeholder(size):
    """Named explicit-missing state: black square, thin gray frame."""
    im = Image.new("RGBA", (size, size), (10, 10, 10, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, size - 1, size - 1], outline=(70, 70, 70, 255), width=2 if size >= 16 else 1)
    return im


def main():
    atlas_cache = {}
    stats = {}
    misses = []
    proof_rows = []

    for kind in KINDS:
        rows = []
        meta = None
        with open(os.path.join(DRAFT, f"{kind}.jsonl"), encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                if "_meta" in r:
                    meta = r["_meta"]
                    continue
                rows.append(r)

        ids = [r["id"] for r in rows]
        assert len(ids) == len(set(ids)), f"duplicate ids in {kind}"

        kind_dir = os.path.join(OUT, kind)
        os.makedirs(kind_dir, exist_ok=True)
        ph_bytes = None

        st = Counter()
        samples = []
        per_file = Counter()
        distinct_desc = set()

        for r in rows:
            eid = r["id"]
            ic = r.get("icon")
            if not ic:
                reason = "no-icon-ref"
            else:
                distinct_desc.add((ic["file"], ic["size"], ic["x"], ic["y"]))
                path = os.path.join(ASSETS, *ic["file"].split("/"))
                w_tiles = ic.get("width", 1)
                h_tiles = ic.get("height", 1)
                if not os.path.exists(path):
                    reason = "file-missing"
                    detail = ic["file"]
                elif (
                    (ic["y"] + h_tiles) * ic["size"] > Image.open(path).size[1]
                    or (ic["x"] + w_tiles) * ic["size"] > Image.open(path).size[0]
                ):
                    reason = "cell-out-of-bounds"
                    detail = f"{ic['file']} {ic} vs {Image.open(path).size}"
                else:
                    reason = None

            if reason:
                im = placeholder(96 if not ic else ic["size"])
                buf_path = os.path.join(kind_dir, f"{eid}.webp")
                if ph_bytes is None:
                    im.save(buf_path, "WEBP", lossless=True, exact=True)
                    ph_bytes = open(buf_path, "rb").read()
                else:
                    with open(buf_path, "wb") as bf:
                        bf.write(ph_bytes)
                st[reason] += 1
                misses.append({
                    "kind": kind, "id": eid, "reason": reason,
                    **({"detail": detail} if reason == "file-missing" else {}),
                    **({"descriptor": ic} if ic else {}),
                })
                continue

            path = os.path.join(ASSETS, *ic["file"].split("/"))
            if ic["file"] not in atlas_cache:
                atlas_cache[ic["file"]] = Image.open(path).convert("RGBA")
            s = ic["size"]
            w_tiles, h_tiles = ic.get("width", 1), ic.get("height", 1)
            x0, y0 = ic["x"] * s, ic["y"] * s
            crop = atlas_cache[ic["file"]].crop(
                (x0, y0, x0 + w_tiles * s, y0 + h_tiles * s)
            )
            if crop.getchannel("A").getextrema()[1] == 0:
                # resolved to a fully transparent cell: the game's own "no art"
                placeholder(s).save(os.path.join(kind_dir, f"{eid}.webp"), "WEBP", lossless=True, exact=True)
                st["resolved-empty-cell"] += 1
                misses.append({"kind": kind, "id": eid, "reason": "resolved-empty-cell",
                               "descriptor": ic})
                continue

            crop.save(os.path.join(kind_dir, f"{eid}.webp"), "WEBP", lossless=True, exact=True)
            st["resolved-exported"] += 1
            per_file[ic["file"]] += 1
            if len(samples) < PROOF_MIN:
                samples.append({"id": eid, "descriptor": ic,
                                "pixelRect": [x0, y0, w_tiles * s, h_tiles * s],
                                "exported": f"output/cdn/v{BUILD}/{kind}/{eid}.webp"})

        total = len(rows)
        resolved = st["resolved-exported"] + st["resolved-empty-cell"]
        rate = round(resolved / total * 100, 2)
        bytes_kind = sum(
            os.path.getsize(os.path.join(kind_dir, f)) for f in os.listdir(kind_dir)
        )
        stats[kind] = {
            "total": total, "resolved": resolved, "ratePct": rate,
            "exported": st["resolved-exported"],
            "breakdown": dict(st),
            "distinctDescriptors": len(distinct_desc),
            "atlasFilesUsed": len(per_file),
            "bytes": bytes_kind,
            "buildId": meta["buildId"] if meta else BUILD,
        }
        proof_rows.append({
            "kind": kind, "totalEntities": total,
            "iconBearing": sum(per_file.values()) + st["resolved-empty-cell"],
            "resolutionRatePct": rate,
            "mechanism": "atlas descriptor {file,size,x,y} -> pixel rect (x*size,y*size,size,size)",
            "samples": samples,
            "misses": [m for m in misses if m["kind"] == kind][:PROOF_MIN],
        })
        print(f"{kind}: total={total} resolved={resolved} ({rate}%) "
              f"exported={st['resolved-exported']} breakdown={dict(st)} bytes={bytes_kind}")

    with open(os.path.join(OUT, "misses.jsonl"), "w", encoding="utf-8") as fh:
        for m in misses:
            fh.write(json.dumps(m, ensure_ascii=False) + "\n")
    with open(os.path.join(OUT, "resolution-proof.jsonl"), "w", encoding="utf-8") as fh:
        for p in proof_rows:
            fh.write(json.dumps(p, ensure_ascii=False) + "\n")

    tool = {"python": sys.version.split()[0], "pillow": __import__("PIL").__version__,
            "mode": "lossless webp exact=True (RGBA bit-exact incl. rgb-under-alpha), original pixel sizes",
            "texconv": "not needed - all 36 referenced atlases are magic-verified PNG"}
    with open(os.path.join(OUT, "_tool.json"), "w", encoding="utf-8") as fh:
        json.dump(tool, fh, indent=2)
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
