"""Map-pipeline test suite — spec-map-pipeline.mdx §6 + §7 (TestWriter brief,
docs/briefs/testwriter-map.mdx).

Written against the SPEC, not against an implementation: every case that
needs ``pipeline/map_tiles.py`` skips with a clear reason while the module
is absent, so ``python -m pytest pipeline/tests -q`` stays green-on-skips
before CodeWriter lands (brief requirement).

Three layers (same shape as test_harvest):

1. **Fixture layer** (always runs): the measured §1 numbers reconcile to the
   last digit (class sums, Δ=0 grand total, DDS subtotal, flag splits,
   outlier arithmetic, duplicate-group bytes); the 273⊂276 subset relation +
   3-cell residue + 703 holes close arithmetically; the lexicographic-vs-
   numeric trap is demonstrated on plain strings; synthetic mini-world and
   gradient-tile fixtures mirror the measured relations with exact seam
   constants; the maps.json contract (embedded schema + semantic rules) and
   the MEDIA-CATALOGUE exclusion table validate themselves.
2. **Tool layer** (skips until ``pipeline/map_tiles.py`` exists): signed
   xy-parser, path-pattern-first classification, CR-insensitive entry rows,
   byte accounting over synthetic manifests, negative-origin rebase traps,
   orientation handling, seam metric + planted off-by-one detection, mosaic
   assembly order, hole-alpha, served-plane exclusions.
3. **Integration smoke** (marked ``integration``, skipped unless
   ``--run-integration``): real recon TSV / committed harvest artifacts /
   extracted tiles — never touched by layers 1–2.

Committed-fixture discipline (AC1 input handling): only NUMERIC expectations
are committed here (counts/sizes/flag splits/crc-group sizes/hashes) — cell-set
membership comes from local-only artifacts at integration time, except the
three residue cells quoted from the reviewed spec itself (§1 fold-in).

Mosaic coordinate convention (contract): ``assemble_mosaic`` returns an array
covering the union bbox **rebased to pixel origin** — cell ``(xMin, yMin)``
sits at ``[0, 0]``, so a full-bbox albedo assembly is exactly
``(40·H, 52·W, 4)``. ``origin_px``/``rebase_origin`` expose the raw vs rebased
origins so the negative-pixel-space fact stays visible in code and test.

Contract surface assumed of ``pipeline/map_tiles.py`` (rename here first if
CodeWriter lands a different filename)::

    parse_tile_name(name) -> (x, y)                     # signed decimal ints
    classify_path(relpath) -> class|None                # pak-relative OR data/ tail
    tile_sort_key(cell) -> (x, y)                       # numeric, never lexical
    in_world_bounds(cell) -> bool                       # X [-8..43], Y [0..39]
    parse_entry_row(line) -> (relpath, size, flag)      # CR-insensitive row
    summarize_entries(entries) -> {class: {"n","bytes","flags"}}   # + "index";
                                                        # off-pattern rows land
                                                        # in "_off_pattern"
    byte_delta(summary) -> int                          # bytes matching no class
    origin_px(x, y, tile_w, tile_h) -> (px, py)         # may be NEGATIVE
    rebase_origin(x_min, y_min, tile_w, tile_h) -> (ox, oy)
    world_pixel_size(bounds, tile_w, tile_h) -> (w, h)
    edge_delta(edge_a, edge_b) -> float                 # mean abs Δ, D2 metric
    assemble_mosaic(tiles, tile_w, tile_h, *, y_axis) -> (rows, cols, 4) uint8
                                                        # axis REQUIRED: raises
                                                        # on None/unresolved
    EXPECTED_GEOMETRY_FIELDS                            # the seven-field set
    SERVED_TILE_RE / served_tile_template(buildid)      # A1 canonical shape
    decode_dds_rgba(path) -> rows                       # AC5 hook (albedo)
    parse_dds_header(buf) / DDS_TRIPLES                 # AC3 hooks
    water_plateau_fraction(vals) / PLATEAU_FRACTION_GATE / PYRAMID_CORR_GATE
                                                        # AC4 hooks (frozen gates)
    fit_transform(pairs) / apply_transform(t, wx, wy) / invert_transform(t, px, py)
    D6_BUDGET_PX                                        # None until D6 freezes it

Schema ownership (arbiter M1): ``contracts/maps.schema.json`` is the ONE
owner of every enum — ``transform.d`` is ``number|null`` (the CLI accepts ±1
for either axis; nothing couples north-up to d=-1), ``tileUnitPx`` is an
object keyed by layer id. ``PINNED_LATER`` below enumerates candidate
post-dig VALUES for readability and is never used as a validation constraint.

Served-plane canonical URL shape (arbiter A1, pinned BOTH sides this commit):
``/map-tiles/v{buildid}/albedo/{z}/{x}/{y}.webp`` — version segment per
FRAMEWORK §2.5, zoom segment z∈[0..3] because the emitted pyramid is z0..z3,
rebased non-negative integer tile indices (tx = x − xMin). Parity between
this file's pattern and the module's is asserted in-suite.

Marker-row carrier decision (arbiter A2): the shipped taxonomy lives in
``marker-layers.types[]`` (kind/carrier/coordinateGate/pins — pins stay 0
while D5 is open); future coordinate rows live in ``marks[]`` and each MUST
carry provenance ``{carrier, digId, buildid}`` with a carrier from the
seven-field geometry vocabulary or the known prefab carriers (exact-string
allowlist, not a token grep). Both shapes are validated below.
"""

import hashlib
import json
import re
import struct
import sys
from pathlib import Path

import pytest

PACK_ROOT = Path(__file__).resolve().parents[2]
PIPELINE = PACK_ROOT / "pipeline"
CONTRACTS = PACK_ROOT / "contracts"
SCRATCH = PACK_ROOT / "output" / "_recon-scratch"  # local-only, never committed
DIG = PACK_ROOT / "output" / "_dig-map"            # rerun dig artifacts (local)
RECON_TSV = SCRATCH / "map-pak-entries.tsv"
HARVEST = PACK_ROOT / "extracted" / "harvest"
MAP_TILES_DIR = HARVEST / "map" / "assets" / "worldmap" / "data"
MAP_SUMMARY = HARVEST / "map.summary.json"
MAP_MANIFEST = HARVEST / "map.manifest.jsonl"
RERUN_MANIFEST = DIG / "map.manifest.jsonl"        # map_tiles extract re-run
MAPS_JSON = PACK_ROOT / "extracted" / "data" / "maps.json"   # emitted registry
CELLS_DIR = PACK_ROOT / "extracted" / "data" / "cells"       # D3 emission

# pipeline is a non-package (no __init__.py) — stub sys.path once (harvest precedent).
if str(PIPELINE) not in sys.path:
    sys.path.insert(0, str(PIPELINE))

# ---------------------------------------------------------------------------
# Measured expectations — spec-map-pipeline.mdx §1/§2 (buildid 20318128)
# ---------------------------------------------------------------------------

BUILDID = 20318128
CLASSES = ("albedo", "normal", "splat", "height", "height_s")
N_PER_CLASS = 1377
TOTAL_ENTRIES = 6886
TOTAL_BYTES = 27_888_786_275          # Σ(class bytes) + textures.json, Δ=0 invariant
INDEX_NAME = "data/textures.json"
INDEX_BYTES = 2_531

CLASS_FILE_BYTES = {                  # uniform file size per class (§1 table)
    "albedo": 262_272,
    "normal": 2_097_280,
    "splat": 16_777_344,
    "height": 1_048_576,              # except height_x0_y0.raw = 4 MiB outlier
    "height_s": 65_536,
}
CLASS_TOTAL_BYTES = {
    "albedo": 361_148_544,
    "normal": 2_887_954_560,
    "splat": 23_102_402_688,
    "height": 1_447_034_880,          # 1376 normal-size + the single outlier
    "height_s": 90_243_072,
}
HEIGHT_OUTLIER_NAME = "height_x0_y0.raw"
HEIGHT_OUTLIER_BYTES = 4_194_304

FLAG_SPLITS = {                       # pak flag histogram per class (§1)
    "albedo": {0: N_PER_CLASS},
    "normal": {0: 119, 2: 1258},
    "splat": {2: N_PER_CLASS},
    "height": {0: N_PER_CLASS},
    "height_s": {0: N_PER_CLASS},
}

DDS_FILES = 4_131                     # 3 × 1377; matches harvest detect_census.dds
DDS_BYTES = 26_351_505_792

# §2 format triples: (width, height, fourcc, payload B) — mip-less, 128 B header.
FORMAT_TRIPLES = {
    "albedo": (512, 512, "DXT5", 262_144),
    "normal": (2048, 2048, "DXT1", 2_097_152),
    "splat": (2048, 2048, None, 16_777_216),   # uncompressed RGBA8, flags 0x41
}
DDS_HEADER_BYTES = 128
RAW_FULL_BYTES = 1_048_576            # 512² × f32 hypothesis (D2 open)
RAW_S_BYTES = 65_536                  # 128² × f32
MISROUTED_RAW = {"total": 16, "json_extra": 6, "xml": 10}   # known magic false-positive mode

X_MIN, X_MAX = -8, 43
Y_MIN, Y_MAX = 0, 39
BBOX_CELLS = (X_MAX - X_MIN + 1) * (Y_MAX - Y_MIN + 1)      # 52 × 40 = 2080
PRESENT_CELLS = 1_377
HOLE_CELLS = BBOX_CELLS - PRESENT_CELLS                     # 703

# Duplicate payloads — kept and catalogued, never dropped (§1 honesty table).
# Class labels per the measured placement (map_tiles.py: the "height" row of
# the spec table resolves to the _s pyramid tiles on rerun measurement).
DUP_ALBEDO_CRC = "0ff430e9"
DUP_ALBEDO_N = 276
DUP_ALBEDO_BYTES = 72_387_072
DUP_SPLAT_CRC = "78c858d4"
DUP_SPLAT_N = 273
DUP_SPLAT_BYTES = 4_580_214_912
DUP_PAIRS = (("splat", "782458d4", 2), ("height_s", "db05e56a", 2))
RESIDUE_CELLS = ((7, 27), (7, 28), (28, 24))   # placeholder cells w/ non-uniform splat

# Seven-field geometry-flavored CDB vocabulary (§3, review fold-in F13).
SEVEN_FIELDS = (
    "place@props@worldmapNameOffset",
    "region@props@minimap",
    "place@props.samePosAs",
    "place@props.worldmapZoom",
    "place@props.hudOffset",
    "place@props.fowRadius",
    "region@props.waterHeight",
)

# §4 candidate post-dig VALUES — enumerated for readability, NEVER validation
# constraints (arbiter M1: the enum owner is contracts/maps.schema.json, where
# d is number|null and tileUnitPx is an object; the CLI accepts ±1 for either
# axis, so nothing here couples north-up to d=-1).
PINNED_LATER = {"yAxis": "north-up", "d": -1, "tileSizePx": 512, "format": "webp"}
DIRECTIONS = ("north-up", "south-up")
TILE_PX_SOURCE_MEASURED = 512         # albedo source measures 512² (not a pin)

# AC4 frozen gates (EXTRACTION-LOG §6 freeze record; module constants must
# equal these — asserted in-suite so neither side moves alone).
FROZEN_GATES = {"plateauFraction": 0.5, "pyramidCorr": 0.99}

# Golden FILE fingerprints (sha256 of the raw pak payload bytes, computed off
# the extracted corpus at brief time; buildid-scoped via MAP_SUMMARY counts).
GOLDEN_TILES = {
    "albedo": ("albedo_x-1_y10.dds", 262_272,
               "063a29d63055e5f43f109c75aae1f9973e986354fb64b2dd78f55d54ae9209e6"),
    "normal": ("normal_x-1_y10.dds", 2_097_280,
               "b5ebf6cfb0c9ed57704ef9a4e4a03a78e18ed2dd7ab1c9fe09f72d99ab8185a2"),
    "splat": ("splat_x-1_y10.dds", 16_777_344,
              "48a31a8c41f8262aeef21654bdd3186108a08a79ca5d098fc1ba42db9d80b5e8"),
    "height": ("height_x-1_y10.raw", RAW_FULL_BYTES,
               "0dfc24b01f19b9a229a5324b67f3913f164fc4ca89f02fc831d59a1d4ec78fee"),
    "height_outlier": (HEIGHT_OUTLIER_NAME, HEIGHT_OUTLIER_BYTES,
                       "e53aee6b021e4a8353fa59d7ffcf164f1785fff28307f595b5cfeeb831b4a5df"),
    "height_s": ("height_x-1_y10_s.raw", RAW_S_BYTES,
                 "4490c1909957e612c3e94d6cdb5e0bff0cc12cb7c8c180b351c9c3ed2c627718"),
}

# Mo2 — golden DECODED fingerprints alongside the raw-byte ones (spec §6:
# one extracted tile per class *decodes* to a pinned checksum). sha256 over
# the canonical RGBA decode bytes: convert("RGBA") then, for albedo only, the
# module's alpha-flatten (alpha := 255). The .raw classes decode to a byte-
# identical reinterpretation (headerless f32), so their decode checksum would
# duplicate GOLDEN_TILES — the D2 proof covers their semantics instead.
GOLDEN_DECODED = {
    "albedo": ("albedo_x-1_y10.dds",
               "d383a583d0b8e2f88c7a1cdfd8d37a82789b221d0eca4e3071e864428ea2c618"),
    "normal": ("normal_x-1_y10.dds",
               "d65a3e1a27d188cc9af3135ac0a7c42e7e536617315ceb558e075b88f66e40f2"),
    "splat": ("splat_x-1_y10.dds",
              "db9da4dab4854c32d5ee9f77ca38a86c3a73060a4bcb63524a6a3d492316c42b"),
}

# Served plane: albedo-derived webp tiles ONLY (DR-2026-08-18-media-scope, §4),
# in the A1 canonical shape — version + zoom segments, rebased indices. Pinned
# identically in pipeline/map_tiles.py; parity asserted in-suite.
SERVED_TEMPLATE = f"/map-tiles/v{BUILDID}/albedo/{{z}}/{{x}}/{{y}}.webp"
SERVED_TILE_RE_PATTERN = r"/map-tiles/v\d+/albedo/[0-3]/\d+/\d+\.webp"
SERVED_TILE_RE = re.compile(SERVED_TILE_RE_PATTERN)
HEAVY_OFFLOAD_CLASSES = {             # data-plane inputs handed to MEDIA-CATALOGUE
    "normal": CLASS_TOTAL_BYTES["normal"],
    "splat": CLASS_TOTAL_BYTES["splat"],
    "height": CLASS_TOTAL_BYTES["height"],
    "height_s": CLASS_TOTAL_BYTES["height_s"],
}

PROVENANCE_KEYS = {"carrier", "digId", "buildid"}   # AC7 coordinate-row provenance

# A2 allowlist — exact carrier strings, not a token grep ("\bREG\b" matched
# "not actually REG"). The seven-field vocabulary plus the spec §3 carriers.
KNOWN_CARRIERS = frozenset({
    *SEVEN_FIELDS,
    "REG POI prefab transform",
    "REG Towns prefab transform",
    "REG POI prefab (H-POI)",
    "PRE battle/group prefabs",
    "PRE places/fiefdom prefabs",
    "PRE places/fiefdom + CDB place schema (P1)",
})

PROVENANCE_KEYS = {"carrier", "digId", "buildid"}   # AC7 coordinate-row provenance


def _map():
    """Import the map pipeline module; SKIP while it does not exist yet."""
    try:
        import map_tiles  # noqa: F401  (contract: pipeline/map_tiles.py)
    except ModuleNotFoundError as exc:
        pytest.skip(
            "map pipeline not implemented yet (pipeline/map_tiles.py absent: "
            f"{exc}); green-on-skips per TestWriter brief"
        )
    return sys.modules["map_tiles"]


def _need(mod, *names):
    """Skip unless the module carries the contracted symbols (docstring table)."""
    missing = [n for n in names if not hasattr(mod, n)]
    if missing:
        pytest.skip(
            "map_tiles lacks contracted symbol(s): " + ", ".join(missing)
            + " — see test_map_tiles module docstring"
        )


# ---------------------------------------------------------------------------
# Synthetic fixtures mirroring the measured relations (fixture layer)
# ---------------------------------------------------------------------------

def _synthetic_world():
    """Deterministic mini-world shaped like §1's measured relations.

    bbox 5×5 = 25 cells, 17 present (8 holes), a 7-cell albedo-placeholder
    family containing a strict 4-cell "no-splat mask" family whose complement
    is a 3-cell residue — the 273⊂276+3 shape at checkable scale.
    """
    present = {
        (0, 0), (1, 0), (2, 0),
        (0, 1), (1, 1), (2, 1), (3, 1),
        (-1, 2), (0, 2), (1, 2), (2, 2),
        (1, 3), (2, 3), (3, 3),
        (0, 4), (2, 4), (3, 4),
    }
    placeholder = {(0, 1), (2, 1), (-1, 2), (1, 2), (2, 2), (1, 3), (2, 4)}
    mask = {(2, 1), (1, 2), (2, 2), (1, 3)}
    return present, placeholder, mask


_SEAM_W = _SEAM_H = 2            # synthetic tile size in px — small on purpose:
                                 # f(gx,gy) must stay a legal byte (< 256) even at
                                 # the bbox extreme x=43 once assembly actually runs
_SEAM_V_STEP = 2                 # f(gx,gy) = 2·gx + 3·gy  → vertical seam Δ = 2
_SEAM_H_STEP = 3                 # horizontal seam Δ = 3
_SEAM_V_OFFBY = 2 * _SEAM_W      # one-column misplacement Δ = 4
_SEAM_H_OFFBY = 3 * _SEAM_H      # one-row misplacement Δ = 6


_SEAM_BIAS = 40                  # keeps f >= 0 at gx=-8*W while max stays < 256


def _seam_pixel(gx, gy):
    v = _SEAM_BIAS + _SEAM_V_STEP * gx + _SEAM_H_STEP * gy
    assert 0 <= v < 256          # stays a legal grayscale byte on this world
    return v


def _seam_tile(x, y):
    """RGBA rows for the tile at cell (x, y) of the gradient world."""
    return [
        [
            (_seam_pixel(x * _SEAM_W + u, y * _SEAM_H + v),) * 3 + (255,)
            for u in range(_SEAM_W)
        ]
        for v in range(_SEAM_H)
    ]


def _column(pixels_rows, u):
    return [row[u][0] for row in pixels_rows]


def _row(pixels_rows, v):
    return [px[0] for px in pixels_rows[v]]


# ---------------------------------------------------------------------------
# Family 1 — fixture self-tests: the committed numbers reconcile (always runs)
# ---------------------------------------------------------------------------

def test_fixture_class_table_reconciles_to_the_last_digit():
    for cls in CLASSES:
        if cls == "height":
            total = (N_PER_CLASS - 1) * CLASS_FILE_BYTES[cls] + HEIGHT_OUTLIER_BYTES
        else:
            total = N_PER_CLASS * CLASS_FILE_BYTES[cls]
        assert total == CLASS_TOTAL_BYTES[cls], cls
    grand = sum(CLASS_TOTAL_BYTES.values()) + INDEX_BYTES
    assert grand == TOTAL_BYTES                    # §1 Δ=0 invariant, fixture side


def test_fixture_counts_sum_to_pak_total():
    assert len(CLASSES) * N_PER_CLASS + 1 == TOTAL_ENTRIES


def test_fixture_flag_splits_sum_to_class_counts():
    for cls, split in FLAG_SPLITS.items():
        assert sum(split.values()) == N_PER_CLASS, cls
        assert set(split) <= {0, 2}               # measured pak-flag vocabulary
    assert FLAG_SPLITS["normal"] == {0: 119, 2: 1258}


def test_fixture_duplicate_groups_live_inside_class_sums():
    assert DUP_ALBEDO_N * CLASS_FILE_BYTES["albedo"] == DUP_ALBEDO_BYTES
    assert DUP_SPLAT_N * CLASS_FILE_BYTES["splat"] == DUP_SPLAT_BYTES
    assert DUP_ALBEDO_BYTES <= CLASS_TOTAL_BYTES["albedo"]
    assert DUP_SPLAT_BYTES <= CLASS_TOTAL_BYTES["splat"]
    for cls, _crc, n in DUP_PAIRS:
        assert n == 2 and n * CLASS_FILE_BYTES[cls] <= CLASS_TOTAL_BYTES[cls]


def test_fixture_subset_relation_273_in_276_with_residue_3():
    # Measured: overlap 273 ⇒ strict subset; exactly 3 placeholder cells carry
    # non-uniform splat (the "uniform no-splat over ocean" prediction, §1).
    assert DUP_SPLAT_N < DUP_ALBEDO_N
    assert DUP_ALBEDO_N - DUP_SPLAT_N == len(RESIDUE_CELLS) == 3
    present, placeholder, mask = _synthetic_world()
    assert mask < placeholder                              # strict subset
    assert len(placeholder - mask) == len(RESIDUE_CELLS)   # same shape at scale
    assert placeholder <= present and mask <= present


def test_fixture_hole_arithmetic_closes():
    assert (X_MAX - X_MIN + 1, Y_MAX - Y_MIN + 1) == (52, 40)
    assert BBOX_CELLS == 2080
    assert BBOX_CELLS - PRESENT_CELLS == HOLE_CELLS == 703


@pytest.mark.parametrize(
    "cls,w,h,fourcc,payload",
    [(k, *v) for k, v in FORMAT_TRIPLES.items()],
)
def test_fixture_format_triples_payload_arithmetic(cls, w, h, fourcc, payload):
    if cls == "albedo":
        assert w * h * 1 == payload                        # BC3 @ 1 B/px
    elif cls == "normal":
        assert w * h // 2 == payload                       # BC1 @ 0.5 B/px
    else:
        assert w * h * 4 == payload                        # RGBA8 @ 4 B/px
    assert CLASS_FILE_BYTES[cls] - payload == DDS_HEADER_BYTES   # classic header only
    assert fourcc in (None, "DXT1", "DXT5")                # no DX10 extended header


def test_fixture_raw_layout_arithmetic_and_known_misroute_mode():
    assert 512 * 512 * 4 == RAW_FULL_BYTES                 # headerless f32 grids
    assert 128 * 128 * 4 == RAW_S_BYTES
    assert HEIGHT_OUTLIER_BYTES == 1024 * 1024 * 4         # D2: 1024² hypothesis
    assert MISROUTED_RAW["json_extra"] + MISROUTED_RAW["xml"] == MISROUTED_RAW["total"]
    assert INDEX_BYTES < DDS_HEADER_BYTES * 32             # tiny index, sanity


def test_fixture_lexicographic_vs_numeric_trap_is_real():
    names = ["x-10_y1", "x-2_y1", "x-8_y1", "x0_y1", "x43_y1"]
    key = lambda s: int(re.search(r"x(-?\d+)", s).group(1))  # noqa: E731
    assert sorted(names) != sorted(names, key=key)         # lexical ≠ numeric
    assert int("-8") < int("-2")                           # yet -8 sorts before -2
    assert sorted(names, key=key)[:3] == ["x-10_y1", "x-8_y1", "x-2_y1"]
    assert sorted(names)[0] == "x-10_y1"                   # lexical puts -10 FIRST


def test_fixture_synthetic_world_dimensions_mirror_relations():
    present, placeholder, mask = _synthetic_world()
    xs = [x for x, _ in present]; ys = [y for _, y in present]
    bbox_cells = (max(xs) - min(xs) + 1) * (max(ys) - min(ys) + 1)
    assert bbox_cells == 25 and len(present) == 17
    assert bbox_cells - len(present) == 8                  # real holes exist
    assert len(placeholder) - len(mask) == 3               # residue shape


def test_fixture_seam_gradient_tiles_edges_continue_exactly():
    a, b, c = _seam_tile(0, 0), _seam_tile(1, 0), _seam_tile(0, 1)
    # Correct neighbors continue the global gradient by exactly one step.
    for va, vb in zip(_column(a, _SEAM_W - 1), _column(b, 0)):
        assert vb - va == _SEAM_V_STEP
    for va, vc in zip(_row(a, _SEAM_H - 1), _row(c, 0)):
        assert vc - va == _SEAM_H_STEP
    # A planted (x±1)·W-style misplacement jumps a full tile plus one step.
    shifted = _column(_seam_tile(2, 0), 0)
    offs = [abs(pb - pa) for pa, pb in zip(_column(a, _SEAM_W - 1), shifted)]
    assert offs == [_SEAM_V_OFFBY + _SEAM_V_STEP] * len(offs)


def test_fixture_seven_field_geometry_vocabulary_is_complete():
    assert len(SEVEN_FIELDS) == 7 == len(set(SEVEN_FIELDS))
    assert all(isinstance(f, str) and "@" in f for f in SEVEN_FIELDS)


def test_fixture_media_exclusion_table_covers_every_heavy_class():
    assert set(HEAVY_OFFLOAD_CLASSES) == {"normal", "splat", "height", "height_s"}
    for cls, total in HEAVY_OFFLOAD_CLASSES.items():
        assert total == CLASS_TOTAL_BYTES[cls]             # catalogue sees true sizes
    assert "albedo" not in HEAVY_OFFLOAD_CLASSES           # the ONLY served class


def test_fixture_served_template_cannot_express_forbidden_classes():
    # A1 canonical shape: version + zoom segments, rebased non-negative indices
    served = SERVED_TEMPLATE.format(z=3, x=0, y=39)
    assert served == f"/map-tiles/v{BUILDID}/albedo/3/0/39.webp"
    assert SERVED_TILE_RE.fullmatch(served)
    assert served.endswith(".webp") and "albedo" in served
    for bad_ext in (".dds", ".raw"):
        assert bad_ext not in served
    for token in ("splat", "normal", "height"):
        assert token not in SERVED_TEMPLATE
    # The rebased tile index space is non-negative integers (tx = x − xMin);
    # world-coordinate negatives belong to the CRS/rebase layer, not URLs.
    for bad in ("/map-tiles/v1/albedo/3/-1/7.webp",
                "/map-tiles/albedo/-8/39.webp",          # flat, unversioned
                "/map-tiles/v9/albedo/z/x/y.webp",
                "/map-tiles/v1/splat/3/1/2.webp",
                "/map-tiles/v1/albedo/3/1/2.dds",
                "/map-tiles/v1/albedo/4/1/2.webp",       # z outside [0..3]
                "/map-tiles/v1/albedo/3/1/2.png"):
        assert not SERVED_TILE_RE.fullmatch(bad), bad


def test_fixture_pinned_later_values_are_enumerated_not_defaulted():
    assert set(PINNED_LATER) == {"yAxis", "d", "tileSizePx", "format"}
    assert PINNED_LATER["yAxis"] in DIRECTIONS
    # The four D6/D1 answers stay out of the pre-dig registry sample (§4: null
    # beats guesses); they exist only as enumerated post-dig values here.


# ---------------------------------------------------------------------------
# Family 6 — maps.json contract, fixture side (always runs)
# ---------------------------------------------------------------------------

_AUTHORITY_SCHEMA_CACHE = None


def _authority_schema():
    """The PUBLISHED contract is the one owner of every maps.json enum (M1)."""
    global _AUTHORITY_SCHEMA_CACHE
    if _AUTHORITY_SCHEMA_CACHE is None:
        path = CONTRACTS / "maps.schema.json"
        assert path.exists(), (
            f"published contract absent: {path} — it is committed; the suite "
            "never validates against a private fork of it again")
        _AUTHORITY_SCHEMA_CACHE = json.loads(path.read_text(encoding="utf-8"))
    return _AUTHORITY_SCHEMA_CACHE


try:                                    # belt-and-braces when available
    import jsonschema as _jsonschema
except ImportError:                     # pragma: no cover
    _jsonschema = None


def _validate(doc, schema, path="$"):
    """Tiny validator covering the authority schema's constructs:
    type (str|list), enum, const, required, properties, items, oneOf.

    Dependency-free so family 6 always runs; bool never passes as int/number
    (reviewer nit, reproduced live before the guard).
    """
    types = schema.get("type")
    if types:
        types = [types] if isinstance(types, str) else list(types)
        names = {
            "object": dict, "array": list, "string": str,
            "integer": int, "number": (int, float), "null": type(None),
        }
        py_types = tuple(names[t] for t in types)
        if isinstance(doc, bool) and "boolean" not in types:
            raise AssertionError(
                f"{path}: bool is not {'|'.join(types)} (JSON boolean ≠ number)")
        if not isinstance(doc, py_types):
            raise AssertionError(
                f"{path}: expected type {'|'.join(types)}, got {type(doc).__name__}")
    if "const" in schema and doc != schema["const"]:
        raise AssertionError(f"{path}: {doc!r} != const {schema['const']!r}")
    if "enum" in schema and doc not in schema["enum"]:
        raise AssertionError(f"{path}: {doc!r} not in enum {schema['enum']!r}")
    if "oneOf" in schema:
        branches = 0
        for sub in schema["oneOf"]:
            try:
                _validate(doc, sub, path)
                branches += 1
            except AssertionError:
                pass
        if branches != 1:
            raise AssertionError(
                f"{path}: oneOf matched {branches}/1 branches: {doc!r}")
    if isinstance(doc, dict):
        for req in schema.get("required", []):
            if req not in doc:
                raise AssertionError(f"{path}: missing required key {req!r}")
        for key, sub in schema.get("properties", {}).items():
            if key in doc:
                _validate(doc[key], sub, f"{path}.{key}")
    if isinstance(doc, list) and "items" in schema:
        for i, item in enumerate(doc):
            _validate(item, schema["items"], f"{path}[{i}]")


def _marker_row_carries_coordinates(mark, _depth=2):
    """Mo5 — ANY coordinate-shaped field counts, not just literal x/y keys."""
    if _depth < 0 or not isinstance(mark, dict):
        return False
    for key, value in mark.items():
        if key in ("x", "y", "lat", "lng", "lon"):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return True
        if key in ("pos", "position", "offset", "coords", "coordinate", "point"):
            if (isinstance(value, (list, tuple)) and len(value) == 2
                    and all(isinstance(v, (int, float))
                            and not isinstance(v, bool) for v in value)):
                return True
        if isinstance(value, dict) and _marker_row_carries_coordinates(
                value, _depth - 1):
            return True
    return False


def _sample_registry(pinned=False):
    """maps.json shaped like the §4 sample, valid under the PUBLISHED schema.

    D6 answers stay null unless pinned; ``tileUnitPx`` is always an object
    (the published contract's own enum — null is NOT legal there).
    """
    d = PINNED_LATER["d"] if pinned else None
    unit = PINNED_LATER["tileSizePx"] if pinned else None
    fmt = PINNED_LATER["format"] if pinned else None
    axis = PINNED_LATER["yAxis"] if pinned else None

    def tiles_layer(layer_id, source):
        return {
            "id": layer_id,
            "kind": "tiles",
            "imagery": {"tileTemplate": SERVED_TEMPLATE, "tileSizePx": unit,
                        "format": fmt, "minZoom": 0, "maxZoom": 3},
            "bounds": {"xMin": X_MIN, "yMin": Y_MIN, "xMax": X_MAX, "yMax": Y_MAX},
            "cells": f"cells/{layer_id}.cells.json",
            "provenance": "client-extracted",
            "source": source,
        }

    bbox = {"xMin": X_MIN, "yMin": Y_MIN, "xMax": X_MAX, "yMax": Y_MAX}
    return {
        "buildid": BUILDID,
        "crs": {
            "type": "wartales-world",
            "yAxis": axis,
            "transform": {"a": 1, "b": 0, "c": 0, "d": d,
                          "tileUnitPx": ({"world-strategic": unit}
                                         if pinned else {})},
        },
        "layers": [
            tiles_layer("world-strategic", "map.pak:data/albedo"),
            {**tiles_layer("height", "map.pak:data/height"), "kind": "grid"},
            {"id": "region-overlays", "kind": "vector",
             "sourceRef": "res.pak:/content/worldmap.l3d", "bounds": None,
             "provenance": "client-extracted"},
            {"id": "marker-layers", "kind": "markers", "marks": [],
             "bounds": None, "provenance": "client-extracted",
             "types": [{"kind": "poi-marker",
                        "carrier": "REG POI 453 + Secrets 115 prefabs (HBSON)",
                        "coordinateGate": "D5", "pins": 0}]},   # A2 shipped shape
        ],
        "regions": [
            {"id": "region_edoran", "nameKey": "export_en.region.edoran",
             "polygonRef": None, "bounds": None},
        ],
    }


def _assert_bounds_within_measured(doc):
    for layer in doc.get("layers", []):
        bounds = layer.get("bounds")
        if isinstance(bounds, dict):
            assert bounds["xMin"] >= X_MIN, layer["id"]
            assert bounds["yMin"] >= Y_MIN, layer["id"]
            assert bounds["xMax"] <= X_MAX, layer["id"]
            assert bounds["yMax"] <= Y_MAX, layer["id"]


def _assert_tiles_layer_contract(doc):
    for layer in doc.get("layers", []):
        if layer.get("kind") != "tiles":
            continue
        for req in ("provenance", "source", "cells"):
            assert layer.get(req), f"tiles layer {layer['id']!r} lacks {req!r}"


def _assert_imagery_matches_served_plane(doc):
    # Reviewer nit: imagery was unconstrained — a registry advertising
    # /map-tiles/splat/{x}/{y}.dds must fail here, not only at leak-scan time.
    for layer in doc.get("layers", []):
        imagery = layer.get("imagery")
        if not isinstance(imagery, dict):
            continue
        template = imagery.get("tileTemplate")
        assert template, f"layer {layer['id']!r} imagery lacks tileTemplate"
        sample = (template.replace("{z}", "3").replace("{x}", "0")
                          .replace("{y}", "0"))
        assert SERVED_TILE_RE.fullmatch(sample), (
            f"layer {layer['id']!r} tileTemplate {template!r} instantiates to "
            f"{sample!r} — outside the canonical served plane"
        )


def _assert_marker_types_shape(doc):
    # A2: validate the shape the registry ACTUALLY ships — taxonomy rows live
    # in types[] with zero pins while D5 is open.
    for layer in doc.get("layers", []):
        for entry in layer.get("types", []):
            for req in ("kind", "carrier", "coordinateGate", "pins"):
                assert req in entry, f"types row missing {req!r}: {entry}"
            assert isinstance(entry["pins"], int) \
                and not isinstance(entry["pins"], bool) and entry["pins"] >= 0, (
                f"types row pins must be a non-negative int: {entry}")


def _assert_no_instance_family(doc):
    # §4 measured negative: no dungeon/instance map family; interiors are
    # scene backgrounds, battles belong to a separate battle-tactical CRS.
    for layer in doc.get("layers", []):
        lid = layer["id"].lower()
        assert "dungeon" not in lid and "instance" not in lid, layer["id"]
        assert lid != "battle-tactical", "battle-tactical registers its own crs.type"


def _assert_marker_provenance(doc):
    for layer in doc.get("layers", []):
        if layer.get("kind") != "markers":
            continue
        for mark in layer.get("marks", []):
            if not _marker_row_carries_coordinates(mark):
                continue                                # typed-empty row
            prov = mark.get("provenance")
            assert isinstance(prov, dict) and PROVENANCE_KEYS <= set(prov), (
                f"AC7: coordinate-bearing marker {mark.get('id')!r} lacks "
                f"provenance {sorted(PROVENANCE_KEYS)}"
            )
            assert prov["carrier"] in KNOWN_CARRIERS, (
                f"AC7: unknown carrier {prov['carrier']!r} — expected an exact "
                "seven-field vocabulary name or a known prefab carrier "
                f"(token-grep allowlist retired: '\\bREG\\b' matched anything)"
            )


def _assert_zero_pins_while_d5_open(doc):
    """A2 enforcement on the EMITTED registry: taxonomy rows carry pins == 0
    until D5 lands — typed-empty is a contract, not a placeholder."""
    for layer in doc.get("layers", []):
        for entry in layer.get("types", []):
            assert entry.get("pins") == 0, (
                f"D5 open: {entry.get('kind')!r} advertises "
                f"{entry.get('pins')} pins without coordinates")


def _check_registry(doc):
    if _jsonschema is not None:             # real validator when present
        try:
            _jsonschema.validate(doc, _authority_schema())
        except _jsonschema.ValidationError as exc:
            raise AssertionError(f"published schema: {exc.message}") from exc
    _validate(doc, _authority_schema())     # dependency-free authority check
    _assert_bounds_within_measured(doc)
    _assert_tiles_layer_contract(doc)
    _assert_imagery_matches_served_plane(doc)
    _assert_marker_types_shape(doc)
    _assert_no_instance_family(doc)
    _assert_marker_provenance(doc)


def test_registry_validates_against_the_published_contract_itself():
    # M1 load-bearing: fixture samples and the emitted registry both answer to
    # contracts/maps.schema.json; this pins the authority file's own enums.
    schema = _authority_schema()
    transform = schema["properties"]["crs"]["properties"]["transform"]
    assert transform["properties"]["d"] == {"type": ["number", "null"]}
    assert transform["properties"]["tileUnitPx"] == {"type": "object"}
    layers = schema["properties"]["layers"]["items"]
    assert layers["required"] == ["id", "kind", "bounds", "provenance"]
    assert "grid" in layers["properties"]["kind"]["enum"]


def test_registry_sample_with_null_placeholders_validates():
    _check_registry(_sample_registry())


def test_registry_post_dig_pinned_form_validates_too():
    _check_registry(_sample_registry(pinned=True))


@pytest.mark.parametrize("axis,d", [
    ("north-up", -1), ("north-up", 1),      # published schema couples NOTHING:
    ("south-up", -1), ("south-up", 1),      # any ±1 is legal for either axis
])
def test_registry_axis_and_d_sign_decouple_under_published_schema(axis, d):
    doc = _sample_registry(pinned=True)
    doc["crs"]["yAxis"] = axis
    doc["crs"]["transform"]["d"] = float(d)
    _check_registry(doc)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(buildid="20318128"),                  # str, not int
        lambda d: d.update(buildid=True),                        # bool ⊄ integer
        lambda d: d["crs"].update(yAxis="up"),                   # outside enum
        lambda d: d["crs"]["transform"].update(d="<D6>"),        # placeholder string
        lambda d: d["crs"]["transform"].update(tileUnitPx=None),  # not an object
        lambda d: d["crs"]["transform"].pop("d"),                # required field gone
        lambda d: d["crs"].update(type="leaflet"),               # wrong crs.type
        lambda d: d["layers"][0].pop("provenance"),
        lambda d: d["layers"][0].pop("bounds"),                  # M1 negative
        lambda d: d["layers"][1].pop("provenance"),              # grid layer too
        lambda d: d["layers"][0].__setitem__(
            "imagery", {"tileTemplate": "/map-tiles/splat/{z}/{x}/{y}.dds"}),
        lambda d: d["layers"][0].__setitem__(
            "bounds", {"xMin": -9, "yMin": 0, "xMax": 43, "yMax": 39}),  # escapes floor
        lambda d: d["layers"][0].pop("source"),
        lambda d: d["regions"][0].pop("polygonRef"),             # published requires
    ],
    ids=["str-buildid", "bool-buildid", "bad-yaxis", "placeholder-d",
         "null-tileunitpx", "missing-d", "wrong-crs", "tiles-no-provenance",
         "missing-bounds", "grid-no-provenance", "splat-imagery-template",
         "bounds-outside-bbox", "tiles-no-source", "region-no-polygonref"],
)
def test_registry_rejects(mutate):
    doc = _sample_registry()
    mutate(doc)
    with pytest.raises(AssertionError):
        _check_registry(doc)


@pytest.mark.parametrize(
    "bad_id", ["dungeon-interior", "instance-maps", "battle-tactical"],
)
def test_registry_rejects_instance_and_battle_layers(bad_id):
    doc = _sample_registry()
    doc["layers"].append({"id": bad_id, "kind": "tiles"})
    with pytest.raises(AssertionError):
        _check_registry(doc)


@pytest.mark.parametrize(
    "mark",
    [
        {"id": "town_gosenberg", "x": 12.5, "y": -3.25},       # literal x/y
        {"id": "encounter_1", "pos": [12.5, -3.25]},           # Mo5 pos-shape
        {"id": "label_1", "offset": [4, 7]},                   # offset-shape
        {"id": "nested_1", "meta": {"pos": [1.0, 2.0]}},       # nested shape
    ],
    ids=["xy", "pos", "offset", "nested-pos"],
)
def test_registry_rejects_unprovenanced_coordinate_markers(mark):
    doc = _sample_registry()
    doc["layers"][3]["marks"] = [dict(mark, provenance=None)]
    with pytest.raises(AssertionError, match="AC7"):
        _check_registry(doc)


def test_registry_rejects_unknown_carrier_token_trick():
    doc = _sample_registry()
    doc["layers"][3]["marks"] = [
        {"id": "town_gosenberg", "x": 12.5, "y": -3.25,
         "provenance": {"carrier": "not actually REG", "digId": "D5",
                        "buildid": BUILDID}},
    ]
    with pytest.raises(AssertionError, match="AC7"):
        _check_registry(doc)


def test_registry_accepts_provenanced_coordinate_markers():
    doc = _sample_registry()
    doc["layers"][3]["marks"] = [
        {"id": "town_gosenberg", "pos": [12.5, -3.25],
         "provenance": {"carrier": "place@props@worldmapNameOffset",
                        "digId": "D5", "buildid": BUILDID}},
        {"id": "poi_alazar", "x": 0.0, "y": 0.0,
         "provenance": {"carrier": "REG POI prefab transform",
                        "digId": "D5", "buildid": BUILDID}},
    ]
    _check_registry(doc)


def test_registry_zero_pins_rule_fails_loud_when_d5_pins_appear():
    doc = _sample_registry()
    doc["layers"][3]["types"][0]["pins"] = 3
    with pytest.raises(AssertionError, match="D5 open"):
        _assert_zero_pins_while_d5_open(doc)


# ---------------------------------------------------------------------------
# Families 2–5 — parser, transform, seam, mosaic (skip until implementation)
# ---------------------------------------------------------------------------

def test_parse_tile_name_signed_decimal():
    mt = _map(); _need(mt, "parse_tile_name")
    for name, want in [
        ("albedo_x-8_y0.dds", (-8, 0)),
        ("albedo_x43_y39.dds", (43, 39)),
        ("normal_x-1_y10.dds", (-1, 10)),
        ("height_x0_y0.raw", (0, 0)),
        ("height_x3_y4_s.raw", (3, 4)),
    ]:
        assert mt.parse_tile_name(name) == want, name


@pytest.mark.parametrize("bad", ["albedo_x8.dds", "albedo_x8_y39.png", "_x8_y9", "textures.json"])
def test_parse_tile_name_rejects_malformed(bad):
    mt = _map(); _need(mt, "parse_tile_name")
    with pytest.raises(Exception):
        mt.parse_tile_name(bad)


def test_parse_tile_range_membership_is_an_explicit_decision():
    mt = _map(); _need(mt, "parse_tile_name", "in_world_bounds")
    # Parser accepts the syntax; world membership is a separate predicate.
    assert mt.in_world_bounds((X_MIN, Y_MIN)) and mt.in_world_bounds((X_MAX, Y_MAX))
    for cell in ((-9, 0), (44, 0), (0, -1), (0, 40)):
        assert not mt.in_world_bounds(cell), cell


def test_classify_path_pattern_first_all_classes():
    mt = _map(); _need(mt, "classify_path")
    wants = {
        "data/albedo/albedo_x1_y2.dds": "albedo",
        "data/normal/normal_x-8_y39.dds": "normal",
        "data/splat/splat_x3_y4.dds": "splat",
        "data/height/height_x0_y0.raw": "height",
        "data/height/height_x3_y4_s.raw": "height_s",
        "data/textures.json": "index",
    }
    for path, cls in wants.items():
        assert mt.classify_path(path) == cls, path
    for path in ("data/foo/x.dds", "data/albedo/albedo_x1_y2.webp",
                 "albedo_x1_y2.dds", "data/textures2.json"):
        assert mt.classify_path(path) is None, path


def test_sort_key_numeric_order_survives_negative_tiles():
    mt = _map(); _need(mt, "tile_sort_key")
    cells = [(0, 0), (-2, 5), (43, 39), (-8, 0), (-10, 1)]
    ordered = sorted(cells, key=mt.tile_sort_key)
    assert ordered == sorted(cells)                        # plain int tuples
    assert [c[0] for c in ordered][:3] == [-10, -8, -2]    # numeric, never lexical


def test_parse_entry_row_is_cr_insensitive():
    mt = _map(); _need(mt, "parse_entry_row")
    row = "data/albedo/albedo_x-8_y0.dds\t262272\t0\r"
    relpath, size, flag = mt.parse_entry_row(row)
    assert relpath == "data/albedo/albedo_x-8_y0.dds"      # \r stripped
    assert (size, flag) == (262_272, 0)
    assert mt.parse_entry_row(row.replace("\r", ""))[1] == 262_272


def test_byte_accounting_over_synthetic_manifest_outlier_rides_along():
    mt = _map(); _need(mt, "parse_entry_row", "summarize_entries", "byte_delta")
    lines = []
    for cls in ("albedo", "normal", "splat"):
        for i, (x, y) in enumerate(((-8, 0), (-1, 10), (0, 0), (43, 39))):
            flag = 2 if i == 3 else 0                      # exercise the split
            lines.append(f"data/{cls}/{cls}_x{x}_y{y}.dds\t{CLASS_FILE_BYTES[cls]}\t{flag}\r\n")
    lines.append(f"data/height/height_x1_y1.raw\t{RAW_FULL_BYTES}\t0\r\n")
    lines.append(f"data/height/{HEIGHT_OUTLIER_NAME}\t{HEIGHT_OUTLIER_BYTES}\t0\r\n")
    lines.append(f"{INDEX_NAME}\t{INDEX_BYTES}\t2\r\n")

    entries = [mt.parse_entry_row(line) for line in lines]
    summary = mt.summarize_entries(entries)
    assert summary["albedo"]["n"] == 4
    assert summary["albedo"]["bytes"] == 4 * CLASS_FILE_BYTES["albedo"]
    assert summary["splat"]["flags"] == {0: 3, 2: 1}       # histogram kept intact
    assert summary["height"]["bytes"] == RAW_FULL_BYTES + HEIGHT_OUTLIER_BYTES
    assert summary["index"]["bytes"] == INDEX_BYTES
    assert mt.byte_delta(summary) == 0                     # nothing silently dropped


def test_origin_px_negative_origin_trap():
    mt = _map(); _need(mt, "origin_px")
    assert mt.origin_px(X_MIN, 0, 512, 512) == (-4096, 0)  # bbox floor ⇒ NEGATIVE px space
    assert mt.origin_px(0, 0, 512, 512) == (0, 0)
    assert mt.origin_px(X_MAX, Y_MAX, 512, 512) == (22016, 19968)


def test_rebase_origin_explicit_never_discovered_in_browser():
    mt = _map(); _need(mt, "rebase_origin", "world_pixel_size")
    assert mt.rebase_origin(X_MIN, Y_MIN, 512, 512) == (4096, 0)   # |floor| · tile
    bounds = {"xMin": X_MIN, "yMin": Y_MIN, "xMax": X_MAX, "yMax": Y_MAX}
    assert mt.world_pixel_size(bounds, 512, 512) == (52 * 512, 40 * 512)  # 26624×20480


def test_edge_delta_matches_d2_metric_semantics():
    mt = _map(); _need(mt, "edge_delta")
    a = _column(_seam_tile(0, 0), _SEAM_W - 1)
    cont = _column(_seam_tile(1, 0), 0)                    # continues gradient
    broke = _column(_seam_tile(2, 0), 0)                   # planted off-by-one
    assert mt.edge_delta(a, cont) == float(_SEAM_V_STEP)   # inside global gradient
    assert mt.edge_delta(a, broke) > float(_SEAM_V_STEP)
    assert mt.edge_delta(a, a) == 0.0                      # identity edges


def test_seam_sweep_catches_assembly_off_by_one():
    mt = _map(); _need(mt, "assemble_mosaic")
    pytest.importorskip("numpy", reason="mosaic assertions need numpy")
    cells = (-1, 0, 1)
    good = {(x, 0): _seam_tile(x, 0) for x in cells}
    mosaic = mt.assemble_mosaic(good, _SEAM_W, _SEAM_H, y_axis="north-up")
    assert mosaic.shape == (_SEAM_H, len(cells) * _SEAM_W, 4)     # rebased to origin
    # Internal vertical tile boundaries continue the gradient by exactly one step.
    for bx in (1 * _SEAM_W - 1, 2 * _SEAM_W - 1):
        pairs = [(int(mosaic[v, bx, 0]), int(mosaic[v, bx + 1, 0]))
                 for v in range(_SEAM_H)]
        assert all(r - l == _SEAM_V_STEP for l, r in pairs), bx

    bad = dict(good)
    bad[(1, 0)] = _seam_tile(2, 0)                         # (x±1)·W mutation
    broken = mt.assemble_mosaic(bad, _SEAM_W, _SEAM_H, y_axis="north-up")
    # the MUTATED boundary is the one between slot x=0 and slot x=1 (the
    # pre-fix body measured the untouched -1|0 seam here and passed on the
    # honest constant — a latent bug the skip had been hiding)
    bx = 2 * _SEAM_W - 1
    offs = [abs(int(broken[v, bx + 1, 0]) - int(broken[v, bx, 0]))
            for v in range(_SEAM_H)]
    assert offs == [_SEAM_V_OFFBY + _SEAM_V_STEP] * len(offs)
    assert sum(offs) / _SEAM_H > _SEAM_V_STEP              # loud, not subtle


def test_seam_sweep_catches_y_direction_misplacement_too():
    # Mo5 symmetry: a planted y-direction misplacement is demonstrated, not
    # assumed — the metric must catch both assembly axes.
    mt = _map(); _need(mt, "assemble_mosaic", "edge_delta")
    pytest.importorskip("numpy", reason="mosaic assertions need numpy")
    good = {(0, 0): _seam_tile(0, 0), (0, 1): _seam_tile(0, 1)}
    bad = dict(good)
    bad[(0, 1)] = _seam_tile(0, 2)                         # (y±1)·H mutation
    up_good = mt.assemble_mosaic(good, _SEAM_W, _SEAM_H, y_axis="north-up")
    up_bad = mt.assemble_mosaic(bad, _SEAM_W, _SEAM_H, y_axis="north-up")
    by = 1 * _SEAM_H - 1                                   # horizontal seam row
    row_delta = [
        abs(int(up_bad[by + 1, u, 0]) - int(up_bad[by, u, 0]))
        - abs(int(up_good[by + 1, u, 0]) - int(up_good[by, u, 0]))
        for u in range(_SEAM_W)
    ]
    assert min(row_delta) > _SEAM_H_STEP                   # every column jumps
    # and edge_delta itself sees it on extracted edges
    a = _row(_seam_tile(0, 0), _SEAM_H - 1)
    cont = _row(_seam_tile(0, 1), 0)
    broke = _row(_seam_tile(0, 2), 0)
    assert mt.edge_delta(a, cont) == float(_SEAM_H_STEP)
    assert mt.edge_delta(a, broke) > mt.edge_delta(a, cont)


def test_assemble_mosaic_requires_orientation_never_hardcodes_it():
    mt = _map(); _need(mt, "assemble_mosaic")
    tiles = {(0, 0): _seam_tile(0, 0)}
    with pytest.raises(Exception):
        mt.assemble_mosaic(tiles, _SEAM_W, _SEAM_H, y_axis=None)   # D6 unanswered


def test_assemble_mosaic_orientation_flip_is_vertical_mirror():
    mt = _map(); _need(mt, "assemble_mosaic")
    pytest.importorskip("numpy", reason="mosaic assertions need numpy")
    tiles = {(x, y): _seam_tile(x, y) for x in (-1, 0) for y in (0, 1)}
    up = mt.assemble_mosaic(tiles, _SEAM_W, _SEAM_H, y_axis="north-up")
    down = mt.assemble_mosaic(tiles, _SEAM_W, _SEAM_H, y_axis="south-up")
    assert up.shape == down.shape == (2 * _SEAM_H, 2 * _SEAM_W, 4)
    assert (up[::-1] == down).all()                        # pure vertical mirror


def test_mosaic_assembly_order_numeric_and_insertion_independent():
    mt = _map(); _need(mt, "assemble_mosaic")
    pytest.importorskip("numpy", reason="mosaic assertions need numpy")
    cells = [(-1, 0), (0, 0), (-8, 1), (43, 1)]
    tiles = {c: _seam_tile(*c) for c in cells}
    a = mt.assemble_mosaic(tiles, _SEAM_W, _SEAM_H, y_axis="north-up")
    shuffled = {c: tiles[c] for c in reversed(list(tiles))}
    b = mt.assemble_mosaic(shuffled, _SEAM_W, _SEAM_H, y_axis="north-up")
    assert (a == b).all()                                  # order-independent, stable
    # Numeric placement, not filename order: cell (-8,1) sits LEFT of (43,1)
    # and one row BELOW row 0 under north-up.
    assert (a[_SEAM_H:, :_SEAM_W] == _seam_tile(-8, 1)).all()


def test_hole_alpha_zero_exactly_on_hole_set_placeholder_pixels_kept():
    mt = _map(); _need(mt, "assemble_mosaic")
    pytest.importorskip("numpy", reason="mosaic assertions need numpy")
    present, placeholder, _mask = _synthetic_world()
    xs = [x for x, _ in present]; ys = [y for _, y in present]
    bx0, by0 = min(xs), min(ys)
    cols, rows = max(xs) - bx0 + 1, max(ys) - by0 + 1
    tiles = {c: _seam_tile(*c) for c in present}
    mosaic = mt.assemble_mosaic(tiles, _SEAM_W, _SEAM_H, y_axis="north-up")
    assert mosaic.shape == (rows * _SEAM_H, cols * _SEAM_W, 4)

    def region(cx, cy):
        rx = (cx - bx0) * _SEAM_W
        ry = (cy - by0) * _SEAM_H
        return mosaic[ry:ry + _SEAM_H, rx:rx + _SEAM_W]

    bbox = {(x, y) for x in range(bx0, bx0 + cols) for y in range(by0, by0 + rows)}
    holes = bbox - present
    assert len(holes) == 8
    for cell in holes:
        assert (region(*cell) == 0).all(), f"hole cell {cell} not fully transparent"
    for cell in present:
        assert (region(*cell)[..., 3] == 255).all(), f"present cell {cell} lost alpha"
    # Placeholder-textured cells keep the pack's pixels verbatim — ocean is
    # never fabricated from them, and they are never dropped (realtime-goal).
    for cx, cy in placeholder:
        native = _seam_tile(cx, cy)
        got = region(cx, cy).tolist()
        assert got == [[list(px) for px in row] for row in native], (cx, cy)


def test_served_plane_rules_match_fixture_table():
    mt = _map(); _need(mt, "SERVED_TILE_RE", "served_tile_template")
    # A1: BOTH sides pin one canonical shape, this commit — drift fails here.
    assert mt.SERVED_TILE_RE.pattern == SERVED_TILE_RE_PATTERN
    assert mt.served_tile_template(BUILDID) == SERVED_TEMPLATE
    for z in (0, 1, 2, 3):
        assert mt.SERVED_TILE_RE.fullmatch(
            SERVED_TEMPLATE.format(z=z, x=X_MAX - X_MIN, y=Y_MAX))
    for bad in ("/map-tiles/splat/1/2.webp", "/map-tiles/v1/albedo/1/2.dds",
                "/map-tiles/v1/albedo/1/2.raw", "/map-tiles/normal/1/2.webp",
                "/data/splat/splat_x1_y2.dds", "/map-tiles/v1/albedo/1/2.png",
                "/map-tiles/albedo/-8/39.webp",          # unversioned flat form
                "/map-tiles/v1/albedo/-8/39.webp",       # unrebased world coord
                "/map-tiles/v1/albedo/9/1/2.webp"):      # zoom outside [0..3]
        assert not mt.SERVED_TILE_RE.fullmatch(bad), bad


def test_expected_geometry_vocabulary_matches_spec():
    mt = _map(); _need(mt, "EXPECTED_GEOMETRY_FIELDS")
    assert tuple(mt.EXPECTED_GEOMETRY_FIELDS) == SEVEN_FIELDS


# --- M2 hooks: AC3 (format census) + AC4 (finite + frozen-threshold) ---------

def _dds_header_bytes(w, h, fourcc, rgb_bits, mips_field, set_mipmap_flag):
    DDSD_MIPMAPCOUNT = 0x20000
    flags = 0x1 | 0x2 | 0x4 | (DDSD_MIPMAPCOUNT if set_mipmap_flag else 0)
    pf_flags = 0x41 if fourcc is None else 0x4
    buf = bytearray(128)
    buf[0:4] = b"DDS "
    struct.pack_into("<7I", buf, 4, 124, flags, h, w,
                     (w * rgb_bits) // 8 or 32, 0, mips_field)
    # DDS_PIXELFORMAT at +76: dwSize@76, dwFlags@80, dwFourCC@84,
    # dwRGBBitCount@88 (parse_dds_header unpacks "<II4sI" from 76)
    struct.pack_into("<II", buf, 76, 32, pf_flags)
    if fourcc is not None:
        buf[84:88] = fourcc.encode("ascii")
    struct.pack_into("<I", buf, 88, rgb_bits)
    return bytes(buf)


@pytest.mark.parametrize("cls,w,h,fourcc,payload",
                         [(k, *v[:2], v[2], v[3]) for k, v in FORMAT_TRIPLES.items()])
def test_dds_header_parser_recovers_measured_class_triples(cls, w, h, fourcc, payload):
    mt = _map(); _need(mt, "parse_dds_header", "DDS_TRIPLES")
    # AC3 hook: the census parser reproduces each measured §2 triple off a
    # synthetic header built to exactly that class's measured fields.
    want_fmt = {None: "RGBA8", "DXT1": "DXT1", "DXT5": "DXT5"}[fourcc]
    rgb_bits = {None: 32, "DXT1": 0, "DXT5": 0}[fourcc]
    head = _dds_header_bytes(w, h, fourcc, rgb_bits, 7, set_mipmap_flag=False)
    info = mt.parse_dds_header(head)
    got = (info["format"], info["width"], info["height"], info["mips"])
    exp = mt.DDS_TRIPLES[cls]
    assert got == tuple(exp), (cls, got, exp)     # mip-less ⇒ effective mips 1
    assert info["rawMipMapCountField"] == 7       # the raw field is NOT trusted


def test_frozen_gates_match_the_module_and_the_freeze_record():
    # AC4 discipline analogue for D2/D7: gates are module CONSTANTS equal to
    # the fixture-frozen values — never negotiated at run time.
    mt = _map()
    _need(mt, "PLATEAU_FRACTION_GATE", "PYRAMID_CORR_GATE",
          "water_plateau_fraction")
    assert mt.PLATEAU_FRACTION_GATE == FROZEN_GATES["plateauFraction"]
    assert mt.PYRAMID_CORR_GATE == FROZEN_GATES["pyramidCorr"]
    half_plateau = [-0.4] * 512 + [-5.0] * 492 + [-0.39] * 20
    ocean_floor = [-5.0] * 1024
    assert mt.water_plateau_fraction(half_plateau) >= mt.PLATEAU_FRACTION_GATE
    assert mt.water_plateau_fraction(ocean_floor) < mt.PLATEAU_FRACTION_GATE
    # A 7%-of-tile shoreline tail does NOT meet the gate — the refuted verdict
    # survives its own measured tail (C3).
    shoreline_tail = [-0.4] * 72 + [-5.0] * 952
    frac = mt.water_plateau_fraction(shoreline_tail)
    assert frac < mt.PLATEAU_FRACTION_GATE and 0.05 < frac < 0.10


def test_transform_fit_recovers_known_affine_absolute_targets():
    # Mo1 as modified: anchors derive from a KNOWN affine spanning 2-D; the
    # fit must recover the parameters and hit ABSOLUTE projected targets —
    # apply∘invert≡identity proves nothing about a fit bug.
    mt = _map(); _need(mt, "fit_transform", "apply_transform", "invert_transform")
    pytest.importorskip("numpy", reason="affine fit needs numpy")
    truth = {"a": 2.0, "b": 0.25, "tx": 100.0,
             "c": -0.5, "d": 1.5, "ty": -40.0}
    world_pts = [(float(x), float(y))
                 for x in (-10.0, 0.0, 3.0, 17.0)
                 for y in (-5.0, 0.0, 9.0)]
    pairs = [(pt, mt.apply_transform(truth, *pt)) for pt in world_pts]
    fitted = mt.fit_transform(pairs)
    for key, value in truth.items():
        assert abs(fitted[key] - value) < 1e-9, key
    for (wx, wy), (px_want, py_want) in pairs:
        px, py = mt.apply_transform(fitted, wx, wy)
        assert abs(px - px_want) <= 1e-6 and abs(py - py_want) <= 1e-6
    # collinear anchors are REFUSED at fit time (roundtrip-only assertions
    # cannot fail on an underdetermined fit — arbiter Mo1 upgrade)
    collinear = [((float(i * 7), float(-i * 3)),
                  (float(i * 7), float(-i * 3))) for i in range(6)]
    with pytest.raises(Exception):
        mt.fit_transform(collinear)


def test_transform_roundtrip_within_d6_budget_when_frozen():
    # AC9's spec-shaped half stays gated on D6's frozen budget (F4: frozen
    # from measured feature spacing BEFORE the run, never negotiated after).
    mt = _map(); _need(mt, "fit_transform", "apply_transform", "invert_transform")
    budget = getattr(mt, "D6_BUDGET_PX", None)
    if budget is None:
        pytest.skip(
            "AC9 runs only once D6 freezes its px budget from the measured "
            "feature spacing (F4 discipline: frozen before the run, never "
            "negotiated after)"
        )
    truth = {"a": 1.0, "b": 0.0, "tx": 0.0, "c": 0.0, "d": 1.0, "ty": 0.0}
    pairs = [((float(x), float(y)), (x * 512.0, y * 512.0))
             for x in (0.0, 7.0, 21.0) for y in (0.0, 11.0)]
    fitted = mt.fit_transform(pairs)
    for (wx, wy), _target in pairs:
        px, py = mt.apply_transform(fitted, wx, wy)
        rx, ry = mt.invert_transform(fitted, px, py)
        assert abs(rx - wx) <= budget and abs(ry - wy) <= budget


# ---------------------------------------------------------------------------
# Integration smoke — real corpus only, --run-integration (skipped by default)
# ---------------------------------------------------------------------------

def _require(path: Path, what: str):
    if not Path(path).exists():
        pytest.skip(f"integration artifact absent locally: {what} ({path})")
    return Path(path)


def _tsv_entries():
    """Parse the local-only recon TSV CR-insensitively with signed ints (AC1).

    Column order re-checked byte-level at arbiter round 1: the file is
    ``path · flag · offset · size · crc`` — reading col 2 as size read FLAGS
    as sizes; that bug is what this parser exists to never repeat.
    """
    mt = _map(); _need(mt, "classify_path", "parse_tile_name")
    _require(RECON_TSV, "recon scratch TSV")
    rows = []
    for line in RECON_TSV.read_text(encoding="utf-8-sig").splitlines():  # eats \r
        line = line.strip("\r").strip("\n")
        if not line or line.lower().startswith(("path", "relpath", "#")):
            continue
        parts = line.split("\t")
        require_cols = 5
        assert len(parts) == require_cols, (
            f"recon TSV row needs {require_cols} cols "
            f"(path·flag·offset·size·crc), got {len(parts)}: {line[:80]!r}")
        path, flag, offset, size, crc = parts
        rows.append({
            "path": path,
            "flag": int(flag),
            "offset": int(offset),
            "size": int(size),
            "crc": crc,
        })
    assert rows, "recon TSV parsed to zero rows — check delimiter/format"
    return mt, rows


@pytest.mark.integration
def test_int_classifier_reproduces_section1_table_exactly():
    mt, rows = _tsv_entries()
    _need(mt, "summarize_entries", "byte_delta")
    entries = [(r["path"], r["size"], r["flag"]) for r in rows]
    summary = mt.summarize_entries(entries)
    assert sum(s["n"] for s in summary.values()) == TOTAL_ENTRIES
    for cls in CLASSES:
        assert summary[cls]["n"] == N_PER_CLASS, cls
        assert summary[cls]["bytes"] == CLASS_TOTAL_BYTES[cls], cls
        assert summary[cls]["flags"] == FLAG_SPLITS[cls], cls
    assert summary["index"]["n"] == 1
    assert summary["index"]["bytes"] == INDEX_BYTES
    assert mt.byte_delta(summary) == 0                     # Δ=0, to the last digit
    dds_n = sum(summary[c]["n"] for c in ("albedo", "normal", "splat"))
    dds_b = sum(summary[c]["bytes"] for c in ("albedo", "normal", "splat"))
    assert (dds_n, dds_b) == (DDS_FILES, DDS_BYTES)


@pytest.mark.integration
def test_int_cell_sets_identical_across_five_classes_holes_close():
    mt, rows = _tsv_entries()
    sets = {cls: set() for cls in CLASSES}
    for r in rows:
        cls = mt.classify_path(r["path"])
        if cls in sets:
            sets[cls].add(mt.parse_tile_name(Path(r["path"]).name))
    albedo = sets["albedo"]
    for cls in CLASSES[1:]:
        assert sets[cls] == albedo, (
            f"AC8: {cls} diverges from albedo ({len(sets[cls])} vs {len(albedo)}) "
            "— fail loudly, never silently reshape bounds"
        )
    assert len(albedo) == PRESENT_CELLS
    holes = {(x, y) for x in range(X_MIN, X_MAX + 1) for y in range(Y_MIN, Y_MAX + 1)} - albedo
    assert len(holes) == HOLE_CELLS                        # 703 within the bbox


def _manifest_hash_groups(mt):
    """Group the RERUN manifest by (class, payload hash).

    Payload-grounded grouping (M3 as modified): cmd_extract verifies adler32
    over disk bytes on BOTH branches — hash-existing streams the adler of the
    file on disk, fresh pulls recompute it — so these hashes are measured
    over payload bytes, near-free, and independent of D3's interpretation
    logic. Returns {(class, hash): set(cells)} plus a pass-through of rows
    with no cell (index).
    """
    _require(RERUN_MANIFEST, "map_tiles extract rerun manifest")
    groups: dict[tuple, set] = {}
    n_rows = 0
    with RERUN_MANIFEST.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            n_rows += 1
            cls = mt.classify_path(row["path"])
            m = re.search(r"_x(-?\d+)_y(\d+)", row["path"])
            cell = (int(m.group(1)), int(m.group(2))) if m else None
            groups.setdefault((cls, row["hash"]), set()).add(cell)
            assert cell is not None or cls == "index", row["path"]
    assert n_rows == TOTAL_ENTRIES
    return groups


@pytest.mark.integration
def test_int_manifest_hash_duplicate_group_sizes_m3():
    """M3 — the flagship duplicate groups reproduced from PAYLOAD hashes."""
    mt = _map(); _need(mt, "classify_path")
    groups = _manifest_hash_groups(mt)
    repeated = {key: len(cells) for key, cells in groups.items() if len(cells) > 1}
    expected = {
        ("albedo", DUP_ALBEDO_CRC): DUP_ALBEDO_N,
        ("splat", DUP_SPLAT_CRC): DUP_SPLAT_N,
        **{(cls, crc): n for cls, crc, n in DUP_PAIRS},
    }
    assert repeated == expected, (
        f"payload-hash grouping drifted: {repeated} != {expected}")
    # every group is a uniform-cell-size family (no accidental collisions)
    for key in expected:
        assert all(mt.in_world_bounds(c) or c is None for c in groups[key])


@pytest.mark.integration
def test_int_placeholder_subset_residue_from_payload_hashes_and_emitted_cells():
    """273 ⊂ 276 + 3 residue, grounded in payload hashes AND cross-checked
    against what D3 actually emitted to extracted/data/cells/."""
    mt = _map(); _need(mt, "classify_path", "in_world_bounds")
    groups = _manifest_hash_groups(mt)
    ph = groups[("albedo", DUP_ALBEDO_CRC)]
    sm = groups[("splat", DUP_SPLAT_CRC)]
    assert None not in ph and None not in sm
    assert len(ph) == DUP_ALBEDO_N and len(sm) == DUP_SPLAT_N
    assert sm < ph                                         # strict subset
    assert ph - sm == {tuple(c) for c in RESIDUE_CELLS}
    assert all(mt.in_world_bounds(c) for c in RESIDUE_CELLS)
    # D3's emitted shared cell map agrees with the payload-hash view
    albedo_cells = CELLS_DIR / "albedo.cells.json"
    doc = json.loads(_require(albedo_cells, "D3 albedo.cells.json").read_text(
        encoding="utf-8"))
    present = {tuple(c) for c in doc["presentCells"]}
    holes = {tuple(c) for c in doc["holeCells"]}
    assert doc["counts"] == {"present": PRESENT_CELLS, "holes": HOLE_CELLS,
                             "bboxCells": BBOX_CELLS}
    assert present | holes == {
        (x, y) for x in range(X_MIN, X_MAX + 1) for y in range(Y_MIN, Y_MAX + 1)}
    assert ph <= present and sm <= present                 # masked cells exist
    assert not (ph & holes)


@pytest.mark.integration
def test_int_manifest_tsv_bijection_same_cr_int_parsing():
    mt, rows = _tsv_entries()
    _require(MAP_MANIFEST, "harvest map.manifest.jsonl")
    tsv = {r["path"]: r["size"] for r in rows}
    matched = 0
    with MAP_MANIFEST.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            path = rec.get("path") or rec.get("relpath") or rec.get("name")
            size = rec.get("size", rec.get("bytes"))
            if path is None or path not in tsv:
                continue
            assert int(size) == tsv[path], path
            matched += 1
    assert matched == TOTAL_ENTRIES, (
        f"manifest↔TSV bijection broke: {matched}/{TOTAL_ENTRIES}"
    )


@pytest.mark.integration
def test_int_golden_file_checksums_per_class():
    _require(MAP_SUMMARY, "map.summary.json")
    doc = json.loads(MAP_SUMMARY.read_text(encoding="utf-8"))
    if doc.get("counts", {}).get("files") != TOTAL_ENTRIES:
        pytest.skip("extracted corpus is not the 20318128-shaped 6886-entry "
                    "tree; golden hashes are buildid-scoped")
    for key, (name, size, sha) in GOLDEN_TILES.items():
        cls = "height" if key.startswith("height") else key
        p = _require(MAP_TILES_DIR / cls / name, f"golden tile {key}")
        h = hashlib.sha256()
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        assert p.stat().st_size == size, key
        assert h.hexdigest() == sha, key


@pytest.mark.integration
def test_int_golden_decode_then_checksum_per_class():
    """Mo2 — the DDS classes DECODE to pinned checksums (spec §6), so a
    decode_dds_rgba/raw-grid bug can no longer hide behind byte-stability."""
    mt = _map(); _need(mt, "decode_dds_rgba")
    np = pytest.importorskip("numpy", reason="decode checksums need numpy")
    pil = pytest.importorskip("PIL", reason="decode checksums need Pillow")
    Image = pil.Image
    _require(MAP_SUMMARY, "map.summary.json")
    for key, (name, sha) in GOLDEN_DECODED.items():
        p = _require(MAP_TILES_DIR / key / name, f"golden tile {key}")
        if key == "albedo":
            arr = mt.decode_dds_rgba(p)          # module's canonical decode
        else:
            arr = np.asarray(Image.open(p).convert("RGBA"))
        digest = hashlib.sha256(np.asarray(arr, dtype=np.uint8).tobytes())
        assert arr.shape == (512, 512, 4) or arr.shape == (2048, 2048, 4), key
        assert digest.hexdigest() == sha, key


@pytest.mark.integration
def test_int_summary_detect_census_documented_modes_only():
    doc = json.loads(_require(MAP_SUMMARY, "map.summary.json").read_text(encoding="utf-8"))
    census = doc.get("detect_census", {})
    assert doc.get("counts", {}).get("files") == TOTAL_ENTRIES
    assert doc.get("sum_entry_bytes") == TOTAL_BYTES
    assert census.get("dds", {}).get("count") == DDS_FILES
    assert census.get("dds", {}).get("bytes") == DDS_BYTES
    j = census.get("json", {}).get("count", 0)
    x = census.get("xml", {}).get("count", 0)
    # Two honest states: the pre-D1 documented false-positive mode (16 raws
    # misrouted by magic sniffing + the real textures.json) or the post-D1
    # corrected mode (exactly the one index JSON). Anything else fails loudly.
    pre_d1 = (j, x) == (1 + MISROUTED_RAW["json_extra"], MISROUTED_RAW["xml"])
    post_d1 = (j, x) == (1, 0)
    assert pre_d1 or post_d1, (
        f"detect census drifted: json={j} xml={x}; expected the documented "
        f"pre-D1 mode ({1 + MISROUTED_RAW['json_extra']}/{MISROUTED_RAW['xml']}) "
        "or the post-D1 corrected mode (1/0)"
    )


@pytest.mark.integration
def test_int_real_corpus_hole_alpha_and_seams_on_assembled_albedo():
    """Mo4/Mo5/nit — the spec's real cases on the REAL corpus: alpha==0
    exactly on the D3-emitted hole set of the assembled albedo (never a set
    the test itself derived), and the seam metric across real neighbor pairs
    in BOTH directions, proven able to catch a planted one-tile shift."""
    mt = _map(); _need(mt, "decode_dds_rgba", "assemble_mosaic", "edge_delta",
                       "classify_path")
    np = pytest.importorskip("numpy", reason="real-corpus assembly needs numpy")
    albedo_dir = _require(MAP_TILES_DIR / "albedo", "extracted albedo tiles")
    cells_doc = json.loads(_require(
        CELLS_DIR / "albedo.cells.json", "D3 albedo.cells.json").read_text(
            encoding="utf-8"))
    holes = {tuple(c) for c in cells_doc["holeCells"]}
    present = {tuple(c) for c in cells_doc["presentCells"]}

    tiles = {}
    for p in sorted(albedo_dir.glob("*.dds")):
        x, y = mt.parse_tile_name(p.name)
        tiles[(x, y)] = mt.decode_dds_rgba(p)
    assert len(tiles) == PRESENT_CELLS and set(tiles) == present

    # Test-local axis choice for an orientation-independent assertion; NO
    # artifact is saved from this assembly (the AC5 overview test below stays
    # gated on maps.json resolving the axis — Mo3).
    mosaic = mt.assemble_mosaic(tiles, TILE_PX_SOURCE_MEASURED,
                                TILE_PX_SOURCE_MEASURED, y_axis="north-up")
    bx0, by0 = X_MIN, Y_MIN

    def block(cx, cy):
        rx = (cx - bx0) * TILE_PX_SOURCE_MEASURED
        ry = (cy - by0) * TILE_PX_SOURCE_MEASURED
        return mosaic[ry:ry + TILE_PX_SOURCE_MEASURED,
                      rx:rx + TILE_PX_SOURCE_MEASURED]

    for cell in holes:
        assert block(*cell)[..., 3].max() == 0, f"hole cell {cell} has alpha>0"
    for cell in present:
        assert (block(*cell)[..., 3] == 255).all(), f"{cell} lost alpha"

    # seam metric across every co-present neighbor pair, both directions
    def seam(arr_a, arr_b):
        return float(np.abs(arr_a[:, -1, :3].astype(np.int16)
                            - arr_b[:, 0, :3]).mean())

    seams_h, seams_v = [], []
    for (x, y), arr in tiles.items():
        right = tiles.get((x + 1, y))
        if right is not None:
            seams_h.append(seam(arr, right))
        below = tiles.get((x, y + 1))
        if below is not None:
            seams_v.append(seam(np.transpose(arr[:, :3], (1, 0, 2)),
                                np.transpose(below[:, :3], (1, 0, 2))))
    measured_max = max(max(seams_h), max(seams_v))
    assert len(seams_h) == 1332          # the recorded horizontal pair count
    # discriminator: plant the synthetic suite's exact mutation — a slot
    # holding the tile two steps right — across every eligible pair and prove
    # the metric catches it on REAL terrain somewhere beyond every honest seam
    candidates = [(x, y) for (x, y) in tiles
                  if (x + 1, y) in tiles and (x + 2, y) in tiles]
    assert candidates
    planted_seams = [seam(tiles[c], tiles[(c[0] + 2, c[1])]) for c in candidates]
    assert max(planted_seams) > measured_max, (
        f"no planted one-tile shift exceeded the honest max seam "
        f"({max(planted_seams)} vs {measured_max})")


@pytest.mark.integration
def test_int_real_pyramid_run_overview_and_orientation_verdict():
    """Mo3 as sharpened — the axis is DRIVEN from the emitted registry; while
    it is null the test skips with that named reason instead of hardcoding an
    answer §2 forbids assuming. The old `yAxis ∈ DIRECTIONS` demand punished
    honesty and is gone."""
    mt = _map(); _need(mt, "parse_tile_name", "assemble_mosaic",
                       "world_pixel_size", "rebase_origin", "decode_dds_rgba")
    np = pytest.importorskip("numpy", reason="pyramid run needs numpy")
    pil = pytest.importorskip("PIL", reason="overview artifact needs Pillow")
    Image = pil.Image
    axis = None
    if MAPS_JSON.exists():
        registry = json.loads(MAPS_JSON.read_text(encoding="utf-8"))
        axis = registry.get("crs", {}).get("yAxis")
    if axis is None:
        pytest.skip("crs.yAxis unresolved in extracted/data/maps.json (D6 "
                    "open) — no overview is emitted rather than silently "
                    "pinning an orientation")
    albedo_dir = _require(MAP_TILES_DIR / "albedo", "extracted albedo tiles")

    tiles = {}
    for p in sorted(albedo_dir.glob("*.dds")):
        x, y = mt.parse_tile_name(p.name)
        tiles[(x, y)] = mt.decode_dds_rgba(p)
    assert len(tiles) == PRESENT_CELLS
    bounds = {"xMin": X_MIN, "yMin": Y_MIN, "xMax": X_MAX, "yMax": Y_MAX}
    w, h = mt.world_pixel_size(bounds, TILE_PX_SOURCE_MEASURED,
                               TILE_PX_SOURCE_MEASURED)
    mosaic = mt.assemble_mosaic(tiles, TILE_PX_SOURCE_MEASURED,
                                TILE_PX_SOURCE_MEASURED, y_axis=axis)
    assert mosaic.shape == (h, w, 4), (
        f"full-bbox albedo overview must be exactly {h}×{w}, got {mosaic.shape}"
    )
    out = PACK_ROOT / "output" / "_map-overview-ac5.png"   # AC5 visual-diff artifact
    Image.fromarray(np.asarray(mosaic)).save(out)


@pytest.mark.integration
def test_int_extract_stage_census_ac2():
    """AC2 hook over the extract stage's own record: full adler census."""
    doc = json.loads(_require(DIG / "extract.json", "map_tiles extract.json").read_text(
        encoding="utf-8"))
    assert doc["entries"] == TOTAL_ENTRIES
    assert doc["adlerMatch"] == TOTAL_ENTRIES             # 6,886/6,886 MATCH
    assert 0 <= doc["pulledFromPak"] <= doc["entries"]
    fp = {k: v["count"] for k, v in doc.get("detectCensus", {}).items()
          if k in ("json", "xml")}
    # the documented false-positive mode: raw floats reading '{'/'<' plus the
    # one real textures.json — anything else means detection drifted
    pre_d1 = fp.get("json", 0) == 1 + MISROUTED_RAW["json_extra"] \
        and fp.get("xml", 0) == MISROUTED_RAW["xml"]
    post_d1 = fp == {"json": 1}
    assert pre_d1 or post_d1, f"detect false-positive mode drifted: {fp}"


@pytest.mark.integration
def test_int_format_census_uniformity_ac3():
    """AC3 hook — 4,131-row format table, per-class triple uniformity."""
    doc = json.loads(_require(DIG / "formats.json", "D1 formats.json").read_text(
        encoding="utf-8"))
    assert doc["rows"] == DDS_FILES
    assert doc["outlierCount"] == 0 and doc["outliers"] == []
    for cls, (w, h, fourcc, payload) in FORMAT_TRIPLES.items():
        fmt = fourcc if fourcc else "RGBA8"
        key = f"{fmt}/{w}x{h}/mips1"
        assert doc["perClassTriples"][cls] == {key: N_PER_CLASS}, cls


@pytest.mark.integration
def test_int_pyramid_ratio_d7_hook():
    """D7 hook — ratio test ran on all co-present cells under the frozen gate."""
    doc = json.loads(_require(DIG / "pyramid-ratio.json",
                              "D7 pyramid-ratio.json").read_text(encoding="utf-8"))
    assert doc["cellsTested"] == PRESENT_CELLS and doc["identityCellSet"] is True
    assert doc.get("gate", FROZEN_GATES["pyramidCorr"]) == FROZEN_GATES["pyramidCorr"]
    strong_key = "strongCellsAtGate" if "strongCellsAtGate" in doc \
        else "strongCells>=0.99"
    assert doc[strong_key] == PRESENT_CELLS - 1           # all but the origin cell
    divergent = [tuple(d["cell"]) for d in doc["divergentCells"]]
    assert divergent == [(0, 0)]                          # the measured exception


@pytest.mark.integration
def test_int_texindex_d4_hook():
    """D4 hook — textures.json verdict: splat material palette, NOT an index."""
    doc = json.loads(_require(DIG / "texindex.json",
                              "D4 texindex.json").read_text(encoding="utf-8"))
    assert doc["entryCount"] == 43                        # 43 terrain materials
    assert doc["nameDuplicates"] == {"snow_harag": 2}
    assert doc["tileNameBijection"] is None               # documented divergence
    assert "NOT a tile index" in doc["verdict"]


@pytest.mark.integration
def test_int_run_all_wires_the_registry_contract():
    """Spec §6 'schema validation wired into run_all' — asserted at last."""
    text = (PACK_ROOT / "run_all.ps1").read_text(encoding="utf-8",
                                                 errors="replace")
    assert "map_tiles.py" in text
    assert "'map'" in text                                # a declared map stage


def test_extraction_log_carries_freeze_and_repin_record():
    """The Δ=0 re-pin step + D2/D7 gate freezes are DOCUMENTED where AC1 says
    (reviewer nit: re-freezing constants per buildid must be a documented
    procedure, never a redesign or a hand-edit)."""
    log = (PACK_ROOT / "EXTRACTION-LOG.md").read_text(encoding="utf-8",
                                                      errors="replace")
    assert "PLATEAU_FRACTION_GATE" in log and "PYRAMID_CORR_GATE" in log
    assert "re-pin" in log.lower()


@pytest.mark.integration
def test_int_media_catalogue_exclusions_on_artifacts():
    mt = _map(); _need(mt, "SERVED_TILE_RE")
    catalogues = sorted(HARVEST.glob("**/MEDIA-CATALOGUE*")) + \
        sorted((PACK_ROOT / "extracted").glob("MEDIA-CATALOGUE*"))
    site = PACK_ROOT / "site"
    served_roots = [d for d in site.rglob("map-tiles") if d.is_dir()] \
        if site.exists() else []
    def _flatten(s):
        # catalogue prose formats names ("height `_s` pyramid") and bytes
        # ("90,243,072") for humans — compare on the deformatted facts
        return re.sub(r"[,\s`_]", "", s)

    for cat in catalogues:
        flat = _flatten(cat.read_text(encoding="utf-8", errors="replace"))
        for cls, total in HEAVY_OFFLOAD_CLASSES.items():
            assert _flatten(cls) in flat and str(total) in flat, (
                f"MEDIA-CATALOGUE must name the {cls} offload candidate "
                f"({total:,} B) explicitly — no offload decision by silence"
            )
    for root in served_roots:
        for p in root.rglob("*"):
            if p.is_file():
                rel = "/map-tiles/" + p.relative_to(root).as_posix()
                assert mt.SERVED_TILE_RE.fullmatch(rel), (
                    f"served-plane leak: {rel} — only albedo-derived webp may ship"
                )
    if not catalogues and not served_roots:
        pytest.skip("neither MEDIA-CATALOGUE nor a built site/map-tiles tree "
                    "exists yet; exclusion rules covered at fixture/tool level")


@pytest.mark.integration
def test_int_maps_json_registry_contract_when_emitted():
    """M1 load-bearing: the EMITTED registry answers to the PUBLISHED schema
    (kind 'grid' and object tileUnitPx included) plus the semantic rules."""
    doc = json.loads(_require(MAPS_JSON, "emitted maps.json registry").read_text(
        encoding="utf-8"))
    _check_registry(doc)
    assert doc.get("buildid") == BUILDID
    kinds = {layer["id"]: layer["kind"] for layer in doc["layers"]}
    assert kinds.get("height") == "grid"                  # the honest shape
    assert isinstance(doc["crs"]["transform"]["tileUnitPx"], dict)
    template = next(l["imagery"]["tileTemplate"] for l in doc["layers"]
                    if l.get("imagery"))
    assert SERVED_TILE_RE.fullmatch(
        template.replace("{z}", "3").replace("{x}", "0").replace("{y}", "0")
    ), f"emitted tileTemplate {template!r} outside the A1 canonical plane"
    # C2: the frozen-spec coordinate-source kinds are all planned in the
    # taxonomy the frontend consumes
    marker_layer = next(l for l in doc["layers"] if l["kind"] == "markers")
    taxonomy = {t["kind"] for t in marker_layer["types"]}
    assert {"encounter-spawn", "vendor-npc"} <= taxonomy
    _assert_zero_pins_while_d5_open(doc)                  # A2, D5 still open
