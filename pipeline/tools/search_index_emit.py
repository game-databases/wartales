#!/usr/bin/env python3
"""Search-index emitter (spec-f5-search §3) — stage `emit` step 3.

Joins the locale availability plane + the wave-1 locale overlays into the
per-locale header-search index artifact published under
`site/public/data/search/` (nine `{locale}.json` + `manifest.json`). The
index is a DERIVED, DISPOSABLE ARTIFACT (FRAMEWORK §2.1/§2.9): this tool
selects, shapes, and places rows — it derives no game data (AGENTS.md
rule 8); membership comes verbatim from `namedLocales`, names come
verbatim from the overlays, hrefs come from one declared route table.

Reads (nothing else):
  extracted/relinks/locale_availability.jsonl      (--availability)
  extracted/locales/<locale>/{item,skill,class}.json
                                                   (--overlays dir)

Writes (ten files, byte-deterministic — two consecutive runs are
sha256-identical over all ten):
  site/public/data/search/{en,fr,de,es,pl,pt-BR,ru,ko,zh}.json
  site/public/data/search/manifest.json

Determinism contract (§3.4): rows sort by (SEARCHABLE_KINDS index, id);
objects serialize with the FIXED illustrated key order (rows
`kind,id,name,href`; top level `schema,locale,buildId,rows`) — never
`sort_keys`, whose `href,id,kind,name` output would contradict the
published schema; `ensure_ascii=False`, UTF-8, LF; no clock, no
randomness; buildId is the only freshness stamp.

Registered in run_all.ps1 stage `emit` after validate_all.py
([DR-2026-08-18-pipeline]: idempotent, standalone-runnable,
EXTRACTION-LOG-registered).

Exit codes (house pattern): 0 ok | 2 precondition/consistency failure
(names the offending file) | 3 usage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

PACK = Path(__file__).resolve().parents[2]

# The honesty chain starts here (§2): the searchable subset is frozen to
# the wave-1 bridged kinds and is asserted ⊆ MANAGED_KINDS at import time.
# TypeScript never re-declares it: manifest.kinds publishes it and the
# matcher surfaces it as KIND_ORDER (suite 4 deep-equality each run).
sys.path.insert(0, str(PACK / "pipeline" / "tools"))
import wave_kinds  # noqa: E402  (pack-local neutral kind universe)

SEARCHABLE_KINDS = ["item", "skill", "class"]   # frozen; ⊂ MANAGED_KINDS
if not set(SEARCHABLE_KINDS) <= set(wave_kinds.MANAGED_KINDS):
    raise SystemExit(
        "ERROR: SEARCHABLE_KINDS %r is not a subset of wave_kinds.MANAGED_KINDS"
        % (SEARCHABLE_KINDS,)
    )

LOCALES = ["en", "fr", "de", "es", "pl", "pt-BR", "ru", "ko", "zh"]
PIVOT = "en"
SCHEMA_ID = "wartales/search-index@1"

# §3.3 route table — derived-from-F2-§6 (frozen URL law: entity pages
# WITHOUT a /db prefix; pivot `/{kind}/{id}`, locale `/{P}/{kind}/{id}`).
# Key = client code (the artifact's own vocabulary); value = the URL
# segment taken from F4's routing table (lowercase page-plane ids;
# pivot carries NO segment). Client codes never leak into hrefs where
# the segment differs — the pt-BR row is the load-bearing case.
URL_SEGMENTS = {
    PIVOT: None,       # pivot composes bare (DR-2026-08-20-locale-urls)
    "pt-BR": "pt-br",  # F4 §2 recorded lowercase-segment decision
}  # every other segment == its client code


def segment_of(client_code: str):
    seg = URL_SEGMENTS.get(client_code)
    if seg is None and client_code != PIVOT:
        seg = client_code
    return seg


def compose_href(client_code: str, kind: str, entity_id: str) -> str:
    seg = segment_of(client_code)
    prefix = (seg + "/") if seg else ""
    return "/%s%s/%s" % (prefix, kind, entity_id)


def default_buildid() -> str:
    """BUILDID resolved from the EXTRACTION-LOG RUN_ALL-DEFAULTS block
    (DR-2026-08-18-pipeline: the log is the defaults source)."""
    log = PACK / "EXTRACTION-LOG.md"
    begin, end = "RUN_ALL-DEFAULTS-BEGIN", "RUN_ALL-DEFAULTS-END"
    inside = False
    try:
        for line in log.read_text(encoding="utf-8").splitlines():
            if end in line:
                break
            if begin in line:
                inside = True
                continue
            if inside:
                stripped = line.strip()
                if stripped.startswith("BUILDID") and ":" in stripped:
                    return stripped.split(":", 1)[1].strip()
    except OSError:
        pass
    fail2(str(log), "defaults block missing key BUILDID")


def fail2(source: str, why: str) -> None:
    print("ERROR: %s: %s" % (source, why))
    raise SystemExit(2)


class _UsageParser(argparse.ArgumentParser):
    def error(self, message: str):  # usage -> exit 3 (house pattern)
        self.print_usage(sys.stderr)
        print("%s: error: %s" % (self.prog, message), file=sys.stderr)
        raise SystemExit(3)


def parse_args(argv=None) -> argparse.Namespace:
    p = _UsageParser(
        prog="search_index_emit.py",
        description="Emit the F5 header-search index artifact "
                    "(site/public/data/search/) from the locale planes.",
        epilog="Defaults resolve against the pack layout and the "
               "EXTRACTION-LOG RUN_ALL-DEFAULTS block; standalone runs are "
               "allowed and byte-identical to stage runs.",
    )
    p.add_argument("--availability",
                   default=str(PACK / "extracted/relinks/locale_availability.jsonl"),
                   help="locale_availability.jsonl path (default: pack canonical)")
    p.add_argument("--overlays", default=str(PACK / "extracted/locales"),
                   help="locale overlay directory <locale>/<kind>.json "
                        "(default: extracted/locales)")
    p.add_argument("--out", default=str(PACK / "site/public/data/search"),
                   help="artifact output directory "
                        "(default: site/public/data/search)")
    p.add_argument("--buildid", default=None,
                   help="freshness stamp written into every artifact "
                        "(default: BUILDID from EXTRACTION-LOG)")
    return p.parse_args(argv)


def read_availability(path: Path):
    if not path.is_file():
        fail2(str(path),
              "availability plane missing - owning stage: run_all.ps1 emit")
    rows = []
    with path.open(encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                fail2(str(path), "line %d unparsable (%s)" % (n, e))
    return rows


def overlay_path(overlays_root: Path, locale: str, kind: str) -> Path:
    return overlays_root / locale / ("%s.json" % kind)


def read_overlay(path: Path) -> dict:
    if not path.is_file():
        fail2(str(path), "searchable-kind overlay missing - silent partial "
                         "waves cannot ship (spec-f5 §2 growth law)")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def has_name(entry) -> bool:
    return isinstance(entry, dict) and isinstance(entry.get("name"), str) \
        and bool(entry["name"])


def check_consistency(avail_rows, overlays_root: Path,
                      overlays: dict, availability_file: Path) -> dict:
    """§3.1 hard gates — each failure exits 2 naming the offending file."""
    # Locale-set gate: overlays ∪ avail ∩ SEARCHABLE_KINDS must be exactly
    # the nine official codes; an unknown code anywhere is corruption.
    seen = set()
    for row in avail_rows:
        if row.get("kind") in SEARCHABLE_KINDS:
            seen.update(row.get("fields", {}).keys())
    for locale in overlays:
        if locale not in LOCALES:
            fail2(str(overlays_root / locale),
                  "unknown locale code %r - official set is %s"
                  % (locale, ", ".join(LOCALES)))
        seen.add(locale)
    if seen != set(LOCALES):
        missing = sorted(set(LOCALES) - seen)
        extra = sorted(seen - set(LOCALES))
        fail2(str(availability_file),
              "searchable locale set diverges from the nine official codes "
              "(missing: %s; unexpected: %s)" % (missing or "-", extra or "-"))

    named: dict = {}
    seen_pairs: set = set()
    for row in avail_rows:
        if row.get("kind") not in SEARCHABLE_KINDS:
            continue
        pair = (row.get("kind"), row.get("id"))
        if pair in seen_pairs:
            # m-7: duplicates collapsed last-wins and would ship duplicate
            # artifact rows — refuse AT the emitter, naming the file (§3.1).
            fail2(str(availability_file),
                  "duplicate availability row %s/%s - last-wins collapse "
                  "would ship duplicate artifact rows" % pair)
        seen_pairs.add(pair)
        flags = row.get("fields", {})
        have = {loc for loc, f in flags.items() if f.get("name") is True}
        if have != set(row.get("namedLocales", [])):
            fail2(str(availability_file),
                  "%s/%s fields[].name flags disagree with namedLocales"
                  % pair)
        named[pair] = have

    # Gate 1 — flag-without-value is corruption.
    for (kind, entity_id), locales in sorted(named.items()):
        for locale in sorted(locales):
            entry = overlays[locale][kind].get(entity_id)
            if not has_name(entry):
                fail2(str(overlay_path(overlays_root, locale, kind)),
                      "%s/%s flagged name=true in %s but carries no name string"
                      % (kind, entity_id, locale))

    # Gate 2 — value-without-flag likewise.
    for locale in LOCALES:
        for kind in SEARCHABLE_KINDS:
            path = overlay_path(overlays_root, locale, kind)
            for entity_id, entry in overlays[locale][kind].items():
                if not has_name(entry):
                    continue
                have = named.get((kind, entity_id))
                if have is None:
                    fail2(str(path), "%s has no availability row" % entity_id)
                if locale not in have:
                    fail2(str(path),
                          "%s carries a name in %s but avail flags name=false "
                          "there" % (entity_id, locale))
    return named


def emit(out_dir: Path, buildid: str, avail_rows, overlays: dict) -> dict:
    """Build + write the ten artifacts; returns the emitted manifest."""
    by_kind_index = {k: i for i, k in enumerate(SEARCHABLE_KINDS)}
    counts = {}
    reference_ids = None

    out_dir.mkdir(parents=True, exist_ok=True)

    for locale in LOCALES:
        rows = []
        for row in avail_rows:
            kind = row.get("kind")
            if kind not in by_kind_index:
                continue
            if locale not in row.get("namedLocales", []):
                continue
            entity_id = row["id"]
            entry = overlays[locale][kind].get(entity_id)
            rows.append({
                "kind": kind,
                "id": entity_id,
                "name": entry.get("name"),
                "href": compose_href(locale, kind, entity_id),
            })
        rows.sort(key=lambda r: (by_kind_index[r["kind"]], r["id"]))
        counts[locale] = len(rows)
        # Cross-locale identity is part of the determinism contract (§3.4):
        # perfectly parallel presence means one sorted id list across all nine.
        ids = [(r["kind"], r["id"]) for r in rows]
        if reference_ids is None:
            reference_ids = ids
        elif ids != reference_ids:
            fail2(str(out_dir / ("%s.json" % locale)),
                  "sorted (kind,id) list diverges from %s.json" % LOCALES[0])
        doc = {
            "schema": SCHEMA_ID,
            "locale": locale,
            "buildId": buildid,
            "rows": rows,
        }
        write_json(out_dir / ("%s.json" % locale), doc)

    manifest = {
        "schema": SCHEMA_ID,
        "buildId": buildid,
        "locales": list(LOCALES),
        "kinds": list(SEARCHABLE_KINDS),
        "rowCount": {locale: counts[locale] for locale in LOCALES},
    }
    write_json(out_dir / "manifest.json", manifest)
    return manifest


def write_json(path: Path, doc: dict) -> None:
    text = json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n"
    part = path.with_suffix(path.suffix + ".part")
    with part.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(part, path)


def main(argv=None) -> int:
    args = parse_args(argv)

    buildid = args.buildid if args.buildid is not None else default_buildid()
    availability = Path(args.availability)
    overlays_root = Path(args.overlays)
    out_dir = Path(args.out)

    avail_rows = read_availability(availability)

    overlays = {
        locale: {
            kind: read_overlay(overlay_path(overlays_root, locale, kind))
            for kind in SEARCHABLE_KINDS
        }
        for locale in LOCALES
    }

    check_consistency(avail_rows, overlays_root, overlays, availability)
    manifest = emit(out_dir, buildid, avail_rows, overlays)

    blob = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    print("[search-index] %d files -> %s (rows/locale %s, sha256-16 %s)"
          % (len(LOCALES) + 1, out_dir,
             ",".join(str(manifest["rowCount"][l]) for l in LOCALES), digest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
