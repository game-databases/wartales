#!/usr/bin/env python3
"""harvest.py — Wartales harvest stage: byte-identical extraction of Shiro PAK archives.

Raw-layer stage per docs/spec-harvest.mdx: extracts every entry of the four
`PAK\\0` archives into <out>/<pak>/, emitting per-entry JSONL manifests that
reconcile against the recon scratch TSVs on (path, size, adler32). Nothing
interprets payloads here (spec §8).

Reader lineage: imports wtpak.Reader (single source of reader truth) and
subclasses it as HarvestReader. The subclass changes nothing about wire-format
semantics — it only (a) exposes the flags byte the base class parses and drops,
(b) bounds childCount by remaining index bytes so a corrupt index fails loudly
instead of walking billions of nodes (spec §7.14), (c) records index slack
instead of raising, so --no-strict can downgrade it per spec §3.1.

Run shape is two-phase: every tree is parsed, collision-scanned, and
invariant-checked, and the space + runtime-budget gates are measured across
the WHOLE --pak scope, before the first payload byte is written (§4.4).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import struct
import sys
import time
import zlib
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent / "tools"
sys.path.insert(0, str(_TOOLS_DIR))
import wtpak  # noqa: E402  (seed reader — pipeline/tools/wtpak.py)

try:  # survive downstream `| head` closing the pipe (Windows raises on flush)
    import signal
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except (ImportError, AttributeError):
    pass

HARVEST_VERSION = "1.0.0"
CHUNK_BYTES = 4 * 1024 * 1024          # spec §5: sequential, 4 MiB chunks
PEEK_BYTES = 16                        # spec §4.3 detect window
CALIBRATION_BYTES = 64 * 1024 * 1024   # preflight throughput probe per pak
WALL_BUDGET_SECONDS = 30 * 60          # spec §5 fail-loud tripwire
FREE_SPACE_MARGIN = 1.05               # spec §4.4 space gate
MAX_PAKS = 4                           # spec §3.1
SAMPLES_PER_PAK = 10                   # spec §6 criterion c

MEDIA_EXTENSIONS = frozenset(
    ".wem .bnk .wav .ogg .mp3 .flac .bik .bk2 .usm .webm .mp4 .avi .ogv .mov".split()
)
_MEDIA_EXT_TUPLE = tuple(MEDIA_EXTENSIONS)  # endswith wants a tuple; hoist off the hot loop
ASCII_WS = b" \t\n\r\v\f"
MAGIC_TOKENS = (
    (b"DDS ", "dds"),
    (b"\x89PNG", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"HMD", "hmd"),
    (b"HBSON\x00", "hbson"),
    (b"\x76\x2f\x31\x01", "tx"),
    (b"PK\x03\x04", "zip"),
    (b"\x1f\x8b", "gzip"),
)


def silence_broken_stdout():
    """Point fd 1 at devnull after a closed-pipe write failure.

    win32 has no SIGPIPE; once the consumer (`| head`) is gone a failed flush
    leaves data in the buffer and interpreter shutdown fails again — CPython's
    exit-120 path. Redirecting the descriptor lets every later flush succeed.
    """
    try:
        fd = os.open(os.devnull, os.O_WRONLY)
        os.dup2(fd, 1)
        os.close(fd)
    except OSError:
        pass


class UsageError(Exception):
    """Bad invocation or failed preflight gate — exit 2."""


class FormatFailure(Exception):
    """Format/integrity failure — exit 3."""


class CollisionError(Exception):
    """Duplicate or case-clashing output path — exit 4."""


class BudgetBreach(Exception):
    """Measured projection exceeds the 30-minute cap — stop and report, exit 2."""


class HarvestReader(wtpak.Reader):
    """wtpak.Reader + flags exposure, childCount bound, tolerant slack."""

    def read_entry(self):
        start = self.pos
        name_len = self._u8()
        if self.pos + name_len > len(self.index):
            raise FormatFailure(
                f"truncated index: node at byte {start} claims a {name_len}-byte name")
        try:
            name = self.index[self.pos:self.pos + name_len].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FormatFailure(f"node at byte {start}: undecodable name: {exc}")
        if "\\" in name:  # no verbatim filesystem mapping exists for a backslash name
            raise FormatFailure(
                f"node at byte {start}: name {name!r} contains '\\' — "
                f"unmappable onto a filesystem layout")
        self.pos += name_len  # consume the name bytes (base reader does the same)
        flags = self._u8()
        if flags & 1:  # directory — child bound: every child consumes >= 2 index bytes
            child_count = self._i32()
            remaining = len(self.index) - self.pos
            if child_count < 0 or child_count * 2 > remaining:
                raise FormatFailure(
                    f"implausible childCount {child_count} in dir {name!r} "
                    f"({remaining} index bytes left)")
            children = [self.read_entry() for _ in range(child_count)]
            return {"name": name, "dir": True, "flags": flags, "children": children}
        if flags & 2:  # dataPosition serialized as IEEE-754 f64 (above the 32-bit mark)
            pos = self._f64()
            if not pos.is_integer():
                raise FormatFailure(
                    f"{name!r}: f64 dataPosition {pos!r} is not integral")
        else:
            pos = float(self._i32())
        size = self._i32()          # field is u32 (spec §2.2); base helper reads i32
        if size < 0:
            size += 1 << 32
        return {
            "name": name, "dir": False, "flags": flags,
            "pos": int(pos),        # relative to header_size
            "size": size,
            "adler": self._i32() & 0xFFFFFFFF,
        }

    def parse(self):
        self.root = self.read_entry()
        self.slack = len(self.index) - self.pos  # enforced by caller per --strict
        return self.root


def longpath(p) -> str:
    """Absolute normalized path, \\\\?\\-prefixed on Windows (spec §4.4 policy);
    UNC shares take the \\\\?\\UNC\\ form."""
    s = os.path.abspath(str(p))
    if os.name == "nt" and not s.startswith("\\\\?\\"):
        if s.startswith("\\\\"):
            s = "\\\\?\\UNC" + s[1:]
        else:
            s = "\\\\?\\" + s
    return s


def detect_token(head: bytes) -> str:
    if not head:
        return "empty"
    for magic, token in MAGIC_TOKENS:
        if head.startswith(magic):
            return token
    stripped = head.lstrip(ASCII_WS)
    if stripped[:1] == b"{":
        return "json"
    if stripped[:1] == b"<":
        return "xml"
    return "u:" + head[:4].hex()


def ext_is_media(rel_path: str) -> bool:
    """Extension half of the §4.2 carve-out (magic half fires during the walk)."""
    return rel_path.lower().endswith(_MEDIA_EXT_TUPLE)


def scope_work(contexts) -> dict:
    """Payload bytes this run must move, per pak — media rows move none."""
    work_by_path = {}
    for ctx in contexts:
        work = sum(e["size"] for rel, e in ctx["files"] if not ext_is_media(rel))
        if work:
            work_by_path[str(ctx["path"])] = work
    return work_by_path


def _mpeg_audio_frame(head: bytes) -> bool:
    """Validated MPEG audio frame header: sync/version/layer/bitrate/rate legal."""
    w = int.from_bytes(head[:4], "big")
    if w & 0xFFE00000 != 0xFFE00000:
        return False  # 11-bit frame sync
    if w >> 19 & 0x3 == 0x1:
        return False  # version '01' reserved
    if w >> 17 & 0x3 == 0x0:
        return False  # layer '00' reserved
    if w >> 12 & 0xF in (0x0, 0xF):
        return False  # bitrate '0000' (free) / '1111' (invalid)
    return w >> 10 & 0x3 != 0x3  # sample rate '11' reserved


def is_av_container(head: bytes) -> bool:
    """Audio/video container magics for the §4.2 carve-out hook.

    Bare FF-Fx sync is not enough — a UTF-16LE BOM (FF FE) matched it; an
    MPEG row needs a fully legal frame header.
    """
    if len(head) < 4:
        return False
    if head.startswith((b"OggS", b"fLaC", b"ID3", b"BIKe", b"\x1a\x45\xdf\xa3")):
        return True
    if _mpeg_audio_frame(head):
        return True  # MPEG audio frame (mp3)
    if head[4:8] == b"ftyp":
        return True  # ISO-BMFF (mp4/mov/m4a)
    if head.startswith(b"RIFF") and head[8:12] in (b"WAVE", b"AVI "):
        return True
    return False


def load_pak(pak_path: Path) -> HarvestReader:
    """Parse header + tree; structural failures raise FormatFailure."""
    try:
        reader = HarvestReader(str(pak_path))
    except (ValueError, struct.error, IndexError) as exc:
        # bad magic / truncated header+index buffer (a 3-byte file dies here too)
        raise FormatFailure(f"{pak_path}: {exc}")
    except OSError as exc:
        raise UsageError(f"cannot read --pak {pak_path}: {exc}")
    try:
        reader.parse()
    except (struct.error, IndexError) as exc:
        raise FormatFailure(f"{pak_path}: truncated index: {exc}")
    except RecursionError:
        raise FormatFailure(f"{pak_path}: index nesting exceeds recursion limit")
    finally:
        reader.f.close()  # index-only past parse — payloads use the phase-B handle
    return reader


def flatten(reader: HarvestReader) -> tuple[list, int]:
    """DFS file list [(rel_path, entry)], plus dir count including root.

    Dir-count definition pinned by reconciliation: wtpak.Reader counts every
    directory node including the unnamed root, matching ground truth
    724 / 1,225 / 8 / 127 (spec §2.3).
    """
    files = list(reader.iter_files())

    def count_dirs(node) -> int:
        n = 1 if node["dir"] else 0
        for child in node.get("children", ()):
            n += count_dirs(child)
        return n

    return files, count_dirs(reader.root)


def check_collisions(files, pak_label: str):
    """§4.1: duplicate full path everywhere; case-clash on Windows targets;
    a file target doubling as another entry's parent directory."""
    seen_exact = {}
    seen_folded = {}
    all_rels = {rel for rel, _entry in files}
    for rel, _entry in files:
        loc = f"{pak_label}:/{rel}"
        if rel in seen_exact:
            raise CollisionError(
                f"duplicate full path resolves to one target — both tree "
                f"locations: {seen_exact[rel]} and {loc}")
        folded = rel.casefold()
        hit = seen_folded.get(folded)
        if hit and hit != rel and os.name == "nt":
            raise CollisionError(
                f"case-clashing paths collide on a Windows target — both tree "
                f"locations: {hit} and {loc}")
        parts = rel.split("/")
        for i in range(1, len(parts)):
            ancestor = "/".join(parts[:i])
            if ancestor in all_rels:
                raise CollisionError(
                    f"a file target doubles as another entry's parent directory "
                    f"— both tree locations: {pak_label}:/{ancestor} and {loc}")
        seen_exact[rel] = loc
        seen_folded.setdefault(folded, loc)


def structural_checks(reader, files, file_size, pak_label, warnings, strict) -> int:
    """§2.2 hard invariants; strict ⇒ fatal, else warning lines. Returns Σsizes."""
    violations = []
    if reader.data_magic != b"DATA":
        violations.append(f'missing "DATA" tree trailer (got {reader.data_magic!r})')
    if reader.slack != 0:
        violations.append(f"index slack != 0 ({reader.slack} unread bytes)")
    sum_sizes = sum(e["size"] for _, e in files)
    span = file_size - reader.header_size
    if sum_sizes != span:
        violations.append(
            f"span check failed: sum(sizes) {sum_sizes} != fileSize - header_size "
            f"{span} (delta {sum_sizes - span})")
    prev_end = 0
    for rel, e in sorted(files, key=lambda t: (t[1]["pos"], t[1]["size"])):
        if e["pos"] != prev_end:
            violations.append(
                f"tiling violation at /{rel}: position {e['pos']} != expected "
                f"{prev_end} (gap/overlap)")
            break
        prev_end = e["pos"] + e["size"]
    else:
        if prev_end != sum_sizes:
            violations.append(
                f"tiling violation: region ends at {prev_end} != sum(sizes) {sum_sizes}")
    if violations:
        if strict:
            raise FormatFailure(f"{pak_label}: " + "; ".join(violations))
        warnings.extend(f"{pak_label}: WARNING (non-strict) {v}" for v in violations)
    return sum_sizes


def peek_head(handle, abs_offset: int, size: int, label: str) -> bytes:
    want = min(PEEK_BYTES, size)
    try:
        handle.seek(abs_offset)
        head = handle.read(want)
    except OSError as exc:
        raise FormatFailure(f"{label}: detect peek failed: {exc}")
    if len(head) != want:
        raise FormatFailure(
            f"{label}: detect peek runs past EOF (wanted {want} bytes, got {len(head)})")
    return head


def hash_stream(handle, size: int, want_sha: bool, sink=None, label: str = "") -> tuple:
    """Chunked read of `size` bytes from current position; running adler (+sha256).

    Past-EOF mid-read is a format failure naming the entry (spec §4.3)."""
    adler = 1
    sha = hashlib.sha256() if want_sha else None
    remaining = size
    while remaining:
        try:
            chunk = handle.read(min(CHUNK_BYTES, remaining))
        except OSError as exc:
            raise FormatFailure(f"{label}: payload read failed: {exc}")
        if not chunk:
            raise FormatFailure(f"{label}: payload read runs past EOF "
                                f"({remaining} of {size} bytes unread)")
        adler = zlib.adler32(chunk, adler)
        if sha is not None:
            sha.update(chunk)
        if sink is not None:
            sink.write(chunk)
        remaining -= len(chunk)
    return adler & 0xFFFFFFFF, (sha.hexdigest() if sha is not None else None)


def hash_existing_file(target: Path, size: int, want_sha: bool) -> tuple | None:
    """Streamed adler(+sha) of an already-extracted file; None when short/long.

    A target differing in length cannot match its entry — treated as a miss so
    the caller re-extracts (resume-safe), never a crash."""
    adler = 1
    sha = hashlib.sha256() if want_sha else None
    remaining = size
    try:
        with open(longpath(target), "rb") as fh:
            while remaining:
                chunk = fh.read(min(CHUNK_BYTES, remaining))
                if not chunk:
                    return None
                adler = zlib.adler32(chunk, adler)
                if sha is not None:
                    sha.update(chunk)
                remaining -= len(chunk)
            if fh.read(1):
                return None
    except OSError:
        return None
    return adler & 0xFFFFFFFF, (sha.hexdigest() if sha is not None else None)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(longpath(path), "rb") as fh:
        while True:
            chunk = fh.read(CHUNK_BYTES)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _discard(part: Path):
    try:
        os.unlink(longpath(part))
    except OSError:
        pass


def extract_payload(pak_handle, entry, abs_offset: int, target: Path, label: str,
                    want_sha: bool) -> tuple:
    """Copy payload through <target>.part + os.replace; verify adler before swap."""
    part = target.with_name(target.name + ".part")
    try:
        os.makedirs(longpath(target.parent), exist_ok=True)
        with open(longpath(part), "wb") as sink:
            pak_handle.seek(abs_offset)
            adler, sha_hex = hash_stream(pak_handle, entry["size"], want_sha,
                                         sink=sink, label=label)
        if adler != entry["adler"]:  # integrity failure: exits non-zero even --no-strict
            raise FormatFailure(
                f"{label}: adler mismatch after extraction "
                f"(stored {entry['adler']:08x}, computed {adler:08x})")
        os.replace(longpath(part), longpath(target))  # atomic swap; OSError ⇒ exit 3
    except FormatFailure:
        _discard(part)
        raise
    except OSError as exc:
        _discard(part)
        raise FormatFailure(f"{label}: write failed: {exc}")
    return adler, sha_hex


def preflight_gates(work_by_path: dict, out_dir: Path):
    """§4.4 space gate + §5 measured runtime projection over the WHOLE scope."""
    if not work_by_path:
        return

    anchor = os.path.abspath(str(out_dir))
    while not os.path.isdir(anchor):
        parent = os.path.dirname(anchor)
        if parent == anchor:
            break
        anchor = parent
    free = shutil.disk_usage(anchor).free
    need = int(sum(work_by_path.values()) * FREE_SPACE_MARGIN)
    if free < need:
        raise UsageError(
            f"insufficient free space for --out {out_dir}: {need:,} B required "
            f"(payload x{FREE_SPACE_MARGIN}), {free:,} B free on that volume")

    projected = 0.0
    for pak_str, work in work_by_path.items():
        read = 0
        adler = 1
        start = time.perf_counter()
        with open(pak_str, "rb") as fh:
            while read < CALIBRATION_BYTES:
                chunk = fh.read(CHUNK_BYTES)
                if not chunk:
                    break
                adler = zlib.adler32(chunk, adler)
                read += len(chunk)
        elapsed = max(time.perf_counter() - start, 1e-9)
        rate = read / elapsed if read else float("inf")
        projected += work / rate if rate else 0.0
    print(f"[preflight] measured projection: ~{projected / 60:.1f} min "
          f"(cap {WALL_BUDGET_SECONDS // 60} min)")
    if projected > WALL_BUDGET_SECONDS:
        raise BudgetBreach(
            f"preflight projects {projected / 60:.1f} min > "
            f"{WALL_BUDGET_SECONDS // 60} min cap")


class RunState:
    """Mid-run tripwire state: stop and report, never silently parallelize (§5)."""

    def __init__(self, total_work: int):
        self.started = time.perf_counter()
        self.total = total_work
        self.done = 0
        self.n = 0

    def tick(self, bytes_added: int):
        self.done += bytes_added
        self.n += 1
        if self.n % 512 or self.total <= 0:
            return
        frac = self.done / self.total
        if frac < 0.02:
            return
        projected = (time.perf_counter() - self.started) / frac
        if projected > WALL_BUDGET_SECONDS:
            raise BudgetBreach(
                f"mid-run projection {projected / 60:.1f} min exceeds "
                f"{WALL_BUDGET_SECONDS // 60} min cap "
                f"({self.done / 1048576:.0f}/{self.total / 1048576:.0f} MiB done)")


def prepare_pak(pak_path: Path, args, warnings: list) -> dict | None:
    """Phase A: parse tree, collisions, invariants (--list prints here)."""
    pak_label = pak_path.stem
    reader = load_pak(pak_path)
    files, n_dirs = flatten(reader)
    check_collisions(files, pak_label)
    sum_sizes = structural_checks(reader, files, pak_path.stat().st_size,
                                  pak_label, warnings, args.strict)

    if args.list_mode:  # §2.2 invariants above are mode-unqualified — checked first
        try:
            for rel, e in files:
                print(f"/{rel}\t{e['flags']}\t{e['pos']}\t{e['size']}\t{e['adler']:08x}")
            sys.stdout.flush()
        except OSError:
            silence_broken_stdout()  # consumer closed the pipe (`| head`) — exit 0
            return None

    return {
        "path": pak_path,
        "stem": pak_label,
        "header_size": reader.header_size,
        "version_byte": reader.version,
        "data_size_field_i32": reader.data_size,
        "files": files,
        "dirs": n_dirs,
        "sum_sizes": sum_sizes,
    }


def build_samples(seed: int, files, pkg_dir: Path, manifest_only: bool) -> dict:
    """Seeded-RNG sample; disk-recomputed adlers for acceptance §6 criterion c."""
    rng = random.Random(seed)
    picks = sorted(rng.sample(range(len(files)), min(SAMPLES_PER_PAK, len(files))))
    entries = []
    for i in picks:
        rel, e = files[i]
        rec = {
            "index": i,
            "path": "/" + rel,
            "size": e["size"],
            "stored_adler": f"{e['adler']:08x}",
        }
        if manifest_only:
            rec["recomputed_adler"] = None
            rec["match"] = None
            rec["note"] = "manifest-only run: payloads untouched"
        elif ext_is_media(rel):  # annotated, never match:false — payload is absent by design
            rec["recomputed_adler"] = None
            rec["match"] = None
            rec["note"] = ("media carve-out (spec §4.2): catalogue-only row — "
                           "payload intentionally absent")
        else:
            target = pkg_dir.joinpath(*rel.split("/"))
            got = hash_existing_file(target, e["size"], False)
            rec["recomputed_adler"] = None if got is None else f"{got[0]:08x}"
            rec["match"] = bool(got) and got[0] == e["adler"]
        entries.append(rec)
    return {
        "seed": seed,
        "method": f"random.Random(seed).sample over {len(files)} file entries",
        "entries": entries,
    }


def harvest_pak(ctx: dict, out_root: Path, args, warnings: list,
                state: RunState) -> dict:
    """Phase B: verify-or-extract every entry, emit manifest + summary."""
    pak_path: Path = ctx["path"]
    pak_label = ctx["stem"]
    # meta writes below need the output root even under --manifest-only
    os.makedirs(longpath(out_root), exist_ok=True)
    started = time.perf_counter()
    pkg_dir = out_root / pak_label
    extracting = not args.manifest_only
    if extracting:
        os.makedirs(longpath(pkg_dir), exist_ok=True)

    rows = []
    census = {}
    counts = {"files": len(ctx["files"]), "dirs": ctx["dirs"], "media": 0,
              "skipped_reuse": 0, "extracted": 0}
    bytes_flowed = 0
    bytes_written = 0

    pak_handle = open(str(pak_path), "rb")  # peeks always; bulk reads only when extracting
    try:
        for rel, e in ctx["files"]:
            label = f"{pak_label}:/{rel}"
            abs_offset = e["pos"] + ctx["header_size"]
            head = peek_head(pak_handle, abs_offset, e["size"], label)
            det = detect_token(head)
            media_ext = ext_is_media(rel)
            media_magic = not media_ext and is_av_container(head)
            media = media_ext or media_magic
            if media_magic:  # hook fired on magic alone — say so loudly (extensions lie)
                print(f"[media-hook] {label}: AV-container magic ({det}) — "
                      f"catalogued, not extracted (spec §4.2)", file=sys.stderr)
            sha_hex = None
            if media:
                counts["media"] += 1  # §4.2: catalogue-only row, no verify, no extract
            elif extracting:
                target = pkg_dir.joinpath(*rel.split("/"))
                existing = hash_existing_file(target, e["size"], args.sha256)
                if existing is not None and existing[0] == e["adler"]:
                    counts["skipped_reuse"] += 1
                    bytes_flowed += e["size"]
                    sha_hex = existing[1]
                else:
                    _, sha_hex = extract_payload(
                        pak_handle, e, abs_offset, target, label, args.sha256)
                    counts["extracted"] += 1
                    bytes_flowed += e["size"]
                    bytes_written += e["size"]
                state.tick(e["size"])
            row = {
                "path": "/" + rel,
                "flag": e["flags"],
                "offset": e["pos"],
                "size": e["size"],
                "hash": f"{e['adler']:08x}",
                "detect": det,
                "media": media,
            }
            if args.sha256 and sha_hex is not None:  # omit, never null — media rows carry none
                row["sha256"] = sha_hex
            rows.append(row)
            cell = census.setdefault(det, {"count": 0, "bytes": 0})
            cell["count"] += 1
            cell["bytes"] += e["size"]
    finally:
        pak_handle.close()

    wall = time.perf_counter() - started
    throughput = (bytes_flowed / 1048576) / wall if wall > 0 else 0.0

    manifest_path = out_root / f"{pak_label}.manifest.jsonl"
    with open(longpath(manifest_path), "w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    st = pak_path.stat()
    summary = {
        "pak": pak_label,
        "source": str(pak_path),
        "measured_size": st.st_size,
        "mtime_epoch": st.st_mtime,
        "mtime_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime)),
        "version_byte": ctx["version_byte"],
        "header_size": ctx["header_size"],
        "data_size_field_i32": ctx["data_size_field_i32"],
        "data_size_stored_unsigned": ctx["data_size_field_i32"] & 0xFFFFFFFF,
        "wrap_delta_vs_sum_sizes": ctx["data_size_field_i32"] - ctx["sum_sizes"],
        "counts": counts,
        "sum_entry_bytes": ctx["sum_sizes"],
        "bytes_written_this_run": bytes_written,
        "detect_census": dict(sorted(census.items(), key=lambda kv: -kv[1]["count"])),
        "wall_seconds": round(wall, 3),
        "throughput_mbps": round(throughput, 2),
        "tool": {
            "harvest_version": HARVEST_VERSION,
            "reader": "pipeline/tools/wtpak.py:wtpak.Reader (HarvestReader subclass)",
            "wtpak_module": str(Path(wtpak.__file__)),
        },
        "buildid": args.buildid,
        "strict": args.strict,
    }
    if args.fingerprint:
        summary["source_sha256"] = sha256_file(pak_path)
    if warnings:
        pak_warnings = [w for w in warnings if w.startswith(f"{pak_label}:")]
        if pak_warnings:
            summary["warnings"] = pak_warnings

    summary_path = out_root / f"{pak_label}.summary.json"
    with open(longpath(summary_path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    print(f"[{pak_label}] {counts['files']:,} entries, "
          f"{ctx['sum_sizes'] / 1048576:.1f} MB, {wall:.1f} s, "
          f"{throughput:.1f} MB/s, extracted={counts['extracted']:,} "
          f"skipped_reuse={counts['skipped_reuse']:,} media={counts['media']:,}")

    seed = int.from_bytes(os.urandom(8), "big")
    return {
        "wall_seconds": round(wall, 3),
        "throughput_mbps": round(throughput, 2),
        "samples": build_samples(seed, ctx["files"], pkg_dir, args.manifest_only),
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="harvest.py",
        description="Wartales harvest stage: byte-identical PAK extraction "
                    "(docs/spec-harvest.mdx)")
    parser.add_argument("--pak", action="append", required=True, metavar="PATH",
                        help="path to a .pak archive; repeatable (max 4)")
    parser.add_argument("--out", default=None, metavar="DIR",
                        help="output root (default <packroot>/extracted/harvest)")
    parser.add_argument("--manifest-only", action="store_true",
                        help="walk tree, write manifest + summary, extract nothing")
    parser.add_argument("--list", dest="list_mode", action="store_true",
                        help="print TSV-order columns to stdout; write nothing")
    parser.add_argument("--sha256", action="store_true",
                        help="add a sha256 column to manifest lines (slower)")
    parser.add_argument("--fingerprint", action="store_true",
                        help="sha256 each whole pak into summary provenance (slow)")
    parser.add_argument("--strict", dest="strict", action="store_true",
                        default=True,
                        help="(default) §2.2 invariant violations are fatal")
    parser.add_argument("--no-strict", dest="strict", action="store_false",
                        help="downgrade §2.2 invariant violations to warnings; "
                             "integrity failures still exit non-zero")
    parser.add_argument("--buildid", default=None, metavar="ID",
                        help="free string stamped into summary.json provenance")
    args = parser.parse_args(argv)
    if args.manifest_only and args.list_mode:
        parser.error("--manifest-only and --list are mutually exclusive")
    return args


def run(args) -> int:
    packroot = Path(__file__).resolve().parent.parent
    out_root = Path(args.out) if args.out else packroot / "extracted" / "harvest"
    if out_root.exists() and not out_root.is_dir():
        raise UsageError(f"--out exists and is not a directory: {out_root}")

    if len(args.pak) > MAX_PAKS:
        raise UsageError(f"--pak accepts at most {MAX_PAKS} archives "
                         f"(got {len(args.pak)})")
    pak_paths = []
    for raw in args.pak:
        p = Path(raw)
        if not p.is_file():
            raise UsageError(f"--pak not found: {raw}")
        pak_paths.append(p)

    claimed_stems: dict[str, Path] = {}
    for p in pak_paths:  # two same-stem archives would silently overwrite one output set
        twin = claimed_stems.get(p.stem.casefold())
        if twin is not None:
            raise UsageError(
                f"duplicate archive stem {p.stem!r}: both --pak paths would "
                f"write one output set — {twin} and {p}")
        claimed_stems[p.stem.casefold()] = p

    warnings: list[str] = []

    # Phase A — every tree parsed and checked before any payload is touched.
    contexts = []
    for pak_path in pak_paths:
        ctx = prepare_pak(pak_path, args, warnings)
        if ctx is not None:
            contexts.append(ctx)
    if args.list_mode:
        return 0

    work_by_path = scope_work(contexts)  # computed once; gates see {} under --manifest-only
    preflight_gates({} if args.manifest_only else work_by_path, out_root)
    state = RunState(sum(work_by_path.values()))

    # Phase B — sequential, single-threaded harvest.
    results = {}
    for ctx in contexts:
        results[ctx["stem"]] = harvest_pak(ctx, out_root, args, warnings, state)

    for w in warnings:
        print(w, file=sys.stderr)

    report = {
        "tool": "harvest",
        "version": HARVEST_VERSION,
        "generated_at_epoch": time.time(),
        "mode": "manifest-only" if args.manifest_only else "full",
        "budget_seconds": WALL_BUDGET_SECONDS,
        "out": str(out_root),
        "buildid": args.buildid,
        "paks": results,
    }
    report_path = out_root / "harvest-report.json"
    with open(longpath(report_path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return 0


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        code = run(parse_args(argv))
        try:
            sys.stdout.flush()
        except OSError:  # final flush onto a closed pipe (`| head`) — writer-side success
            silence_broken_stdout()
            code = 0
        return code
    except UsageError as exc:
        print(f"harvest: usage/preflight failure: {exc}", file=sys.stderr)
        return 2
    except BudgetBreach as exc:
        print("harvest: STOP AND REPORT — runtime budget tripwire "
              "(spec-harvest §5)", file=sys.stderr)
        print(f"harvest: {exc}", file=sys.stderr)
        print("harvest: remedy: point --out at a faster volume; parallelization "
              "is a contingency requiring a new spec note, not an improvisation.",
              file=sys.stderr)
        return 2
    except CollisionError as exc:
        print(f"harvest: output collision: {exc}", file=sys.stderr)
        return 4
    except FormatFailure as exc:
        print(f"harvest: format/integrity failure: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
