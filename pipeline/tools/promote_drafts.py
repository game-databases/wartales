#!/usr/bin/env python3
"""promote_drafts.py — stage 4/5 promotion of the verifier-proven draft
corpora to canonical planes (spec-stages-datasets §3.4).

  python promote_drafts.py --plane data|relinks|both
      [--datadir extracted/data/_draft] [--reldir extracted/relinks/_draft]
      [--out-data extracted/data] [--out-relinks extracted/relinks]
      [--buildid <id>]

Behavior contract (spec §3.4):

1. Scope guard: the managed universe is exactly wave_kinds.MANAGED_KINDS
   (data plane: `<kind>.jsonl`) and `<from>__<to>.jsonl` pair names (relink
   plane). Name-pattern whitelist, never blacklist — `maps.json`, `cells/`,
   `locale_availability.jsonl` etc. are invisible. Non-managed draft entries
   are ignored AND enumerated on stdout with a reason.
2. Equality rule (idempotency): candidate == target iff the payload BYTES
   after line 1 are byte-equal (R2 — line endings / final-newline
   differences are drift, not equality) AND `_meta` equals except
   `emitted`, which is exempt. Equal -> skip untouched; different ->
   atomic replace via `<target>.part` + os.replace.
3. Stale tripwire: an existing managed-name canonical file absent from the
   draft set exits 1 naming it; never deleted, never renamed.
4. Precondition: a missing referenced draft dir exits 2 naming it; the
   draft set must also cover the full managed universe for the selected
   planes (40 kinds / 51 pair files from wave_kinds) or the run exits 2
   naming the missing entries BEFORE any write (R4 — no partial
   promotion of a truncated draft set over an empty canonical dir).
5. Provenance: promoted bytes ARE the verified draft bytes (byte-for-byte,
   `_meta.emitted` included).
6. Deletion semantics: restore-and-pass — a missing canonical target whose
   draft exists is recreated (counted `updated`, exit 0).

CLI is argparse (R3): usage errors / unknown --plane values exit 2.
Non-managed draft entries are ignored AND enumerated on stdout with their
reason (R9 ledger); subdirectory entries enumerate as "subdirectory (never
scanned)" instead of being skipped silently.

Exit codes: 0 ok | 1 drift/stale-tripwire | 2 missing precondition/usage.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wave_kinds  # noqa: E402

IGNORE_REASONS = {
    "achievement.jsonl":
        "wave-3 promotion decision (Dig-10 keyless Steam emission)",
    "place.jsonl": "wave-3 HBSON decode (Dig 7); id-registry wiring pending",
    "group.jsonl": "wave-3 HBSON decode (Dig 7); id-registry wiring pending",
    "element.jsonl": "wave-3 HBSON decode (Dig 7); id-registry wiring pending",
    "levelProps.jsonl":
        "wave-3 HBSON decode (Dig 7); id-registry wiring pending",
    "worldmap_overlays.json": "D7 other-plane product (overlay carrier)",
    "poi_coordinates.jsonl":
        "D7 other-plane product (A2 marker rows land in maps.json marks[])",
    # R9: factual dig products named in the enumeration ledger
    "poi_tile_coords.jsonl":
        "D11 tile-space marker join (world<->tile transform fit; A2 "
        "contract rows land via maps.json marks[])",
    "battle_scene.jsonl":
        "D12 battle terrain grid decode (tactical scenes; map plane, not a "
        "managed dataset)",
}


def load_parts(path):
    """-> (raw bytes, _meta dict or None, payload BYTES after line 1).

    R2: the payload stays raw bytes — one split after the `_meta` line — so
    equality sees line-ending / final-newline drift that a splitlines()
    comparison silently forgives.
    """
    with open(path, "rb") as f:
        raw = f.read()
    nl = raw.find(b"\n")
    head = raw if nl == -1 else raw[:nl]
    try:
        meta = json.loads(head.decode("utf-8")).get("_meta")
    except (json.JSONDecodeError, UnicodeDecodeError):
        meta = None
    return raw, meta, (b"" if nl == -1 else raw[nl + 1:])


def meta_equal(a, b):
    """_meta equality exempting exactly the `emitted` timestamp (rule 2)."""
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    a = {k: v for k, v in a.items() if k != "emitted"}
    b = {k: v for k, v in b.items() if k != "emitted"}
    return a == b


def atomic_copy(raw, target):
    """Write `raw` to target atomically; no .part residue on any failure."""
    tmp = target + ".part"
    try:
        with open(tmp, "wb") as g:
            g.write(raw)
            g.flush()
            os.fsync(g.fileno())
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class Plane:
    def __init__(self, name, draft_dir, out_dir, buildid):
        self.name = name
        self.draft_dir = draft_dir
        self.out_dir = out_dir
        self.buildid = buildid
        self.updated = 0
        self.unchanged = 0

    def scan_draft(self):
        """-> ({managed_name: path}, [ignored entries]) for this plane's rule."""
        raise NotImplementedError

    def managed_names_in(self, directory):
        """Managed-name files present in a canonical dir."""
        raise NotImplementedError

    def universe_missing(self, drafts):
        """Managed-universe entries absent from the draft set (R4)."""
        raise NotImplementedError

    def ignore_reason(self, fn):
        p = os.path.join(self.draft_dir, fn)
        if os.path.isdir(p):
            return "subdirectory (never scanned)"
        return IGNORE_REASONS.get(fn, "non-managed name")

    # -- shared skeleton -----------------------------------------------------
    def run(self):
        if not os.path.isdir(self.draft_dir):
            print("ERROR: %s: draft dir missing: %s"
                  % (self.name, self.draft_dir))
            return 2
        drafts, ignored = self.scan_draft()
        for fn in ignored:
            print("ignore %s/%s (%s)"
                  % (self.draft_dir, fn, self.ignore_reason(fn)))

        # --buildid drift check BEFORE any write (fail-loud, nothing written)
        if self.buildid:
            stale = []
            for name, path in sorted(drafts.items()):
                _, meta, _ = load_parts(path)
                bid = meta.get("buildId") if isinstance(meta, dict) else None
                if bid != self.buildid:
                    stale.append("%s (buildId %r != %r)"
                                 % (path, bid, self.buildid))
            if stale:
                print("DRIFT: draft buildId mismatch (--buildid %s):"
                      % self.buildid)
                for s in stale:
                    print("  " + s)
                return 1

        # stale tripwire (rule 3): managed-name canonical without a draft
        ghosts = sorted(n for n in self.managed_names_in(self.out_dir)
                        if n not in drafts)
        if ghosts and os.path.isdir(self.out_dir):
            print("STALE: managed-name canonical file(s) absent from the "
                  "draft set - never deleted, rerun after re-pin:")
            for n in ghosts:
                print("  %s" % os.path.join(self.out_dir, n))
            return 1

        # universe completeness (R4): before ANY write — a truncated draft
        # set over an equally empty canonical dir must not promote partially.
        incomplete = self.universe_missing(drafts)
        if incomplete:
            print("ERROR: %s: draft set covers %d of the managed universe "
                  "entries; missing: %s"
                  % (self.name, len(drafts), ", ".join(incomplete)))
            return 2

        os.makedirs(self.out_dir, exist_ok=True)
        for name in sorted(drafts):
            src = drafts[name]
            dst = os.path.join(self.out_dir, name)
            raw, meta_s, payload_src = load_parts(src)
            if os.path.isfile(dst):
                _, meta_t, payload_dst = load_parts(dst)
                # R2: byte-exact payloads; _meta structural with `emitted`
                # exempt (rule 2)
                if meta_equal(meta_s, meta_t) \
                        and payload_src == payload_dst:
                    self.unchanged += 1
                    continue
            atomic_copy(raw, dst)
            self.updated += 1
            print("updated %s" % dst)
        return 0


class DataPlane(Plane):
    def scan_draft(self):
        drafts = {}
        ignored = []
        for fn in sorted(os.listdir(self.draft_dir)):
            p = os.path.join(self.draft_dir, fn)
            if not os.path.isfile(p):
                ignored.append(fn)          # R9: enumerated, never silent
                continue
            base = fn[:-6] if fn.endswith(".jsonl") else None
            if base in wave_kinds.MANAGED_KINDS:
                drafts[fn] = p
            else:
                ignored.append(fn)
        return drafts, ignored

    def managed_names_in(self, directory):
        if not os.path.isdir(directory):
            return []
        return [fn for fn in os.listdir(directory)
                if fn.endswith(".jsonl")
                and fn[:-6] in wave_kinds.MANAGED_KINDS]

    def universe_missing(self, drafts):
        have = {fn[:-6] for fn in drafts}
        return sorted(k + ".jsonl"
                      for k in wave_kinds.MANAGED_KINDS - have)


class RelinkPlane(Plane):
    def scan_draft(self):
        drafts = {}
        ignored = []
        for fn in sorted(os.listdir(self.draft_dir)):
            p = os.path.join(self.draft_dir, fn)
            if not os.path.isfile(p):
                ignored.append(fn)          # R9: enumerated, never silent
                continue
            if wave_kinds.is_pair_name(fn):
                drafts[fn] = p
            else:
                ignored.append(fn)
        return drafts, ignored

    def managed_names_in(self, directory):
        if not os.path.isdir(directory):
            return []
        return [fn for fn in os.listdir(directory)
                if wave_kinds.is_pair_name(fn)]

    def universe_missing(self, drafts):
        # wave_kinds freezes the pair universe as a COUNT (51), not names —
        # count equality is the enforceable form of rule 4 here.
        n = len(drafts)
        if n == wave_kinds.EXPECTED_PAIR_FILES:
            return []
        return ["<%d of %d expected pair files present>"
                % (n, wave_kinds.EXPECTED_PAIR_FILES)]


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0])
    ap.add_argument("--plane", choices=("data", "relinks", "both"),
                    default="both",
                    help="which canonical plane(s) to promote")
    ap.add_argument("--datadir", default="extracted/data/_draft")
    ap.add_argument("--reldir", default="extracted/relinks/_draft")
    ap.add_argument("--out-data", dest="out_data", default="extracted/data")
    ap.add_argument("--out-relinks", dest="out_relinks",
                    default="extracted/relinks")
    ap.add_argument("--buildid", dest="buildid", default=None,
                    help="fail before any write when a draft _meta.buildId "
                         "differs")
    args = ap.parse_args(argv)

    planes = []
    if args.plane in ("data", "both"):
        planes.append(DataPlane("data", args.datadir, args.out_data,
                                args.buildid))
    if args.plane in ("relinks", "both"):
        planes.append(RelinkPlane("relinks", args.reldir, args.out_relinks,
                                  args.buildid))

    rc = 0
    for pl in planes:
        rc = pl.run()
        if rc != 0:
            break
    for pl in planes:
        print("%s totals: updated=%d unchanged=%d ignored=%d"
              % (pl.name, pl.updated, pl.unchanged,
                 len(pl.scan_draft()[1]) if os.path.isdir(pl.draft_dir) else 0))
    return rc


if __name__ == "__main__":
    sys.exit(main())
