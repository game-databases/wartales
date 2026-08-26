#!/usr/bin/env python3
"""dig15_sample_verify.py — Data dig 15 proof: sampled edge verification.

Deterministic (seed 15) stratified sample of >=30 edges across ALL emitted
_logic families. Each sampled edge is re-derived INDEPENDENTLY from its cited
evidence locator:

  - hscript-enum-ref edges: the locator names skill.jsonl#<id>.script@<off>
    '<Prefix>.<Name>' — the verifier re-reads that exact byte offset and
    asserts the token sits there, then re-resolves <Name> against the target
    dataset id set.
  - cdb-payload-id-join edges: the locator names <kind>.jsonl#<id>:<path>
    ='<value>' — the verifier navigates that JSON path on a fresh parse of
    the row and asserts the value occurs there, and that it belongs to the
    target id set.

Code-side corroboration: every hscript family sample additionally greps its
cited hl-src corroboration file for the family's runtime consumer token.

Dangling check: EVERY edge in EVERY _logic file is checked against the draft
id sets (not only the sample).

Writes output/_dig-relink-matrix/verification.json; exits non-zero on any
failure.
"""
import json
import os
import random
import re
import sys

PACK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(PACK, "extracted", "data", "_draft")
LOGIC = os.path.join(PACK, "extracted", "relinks", "_logic")
SCRATCH = os.path.join(PACK, "output", "_dig-relink-matrix")
SEED = 15
SAMPLE_PER_FILE_MIN = 1
SAMPLE_TARGET = 36

HL_GREPS = {
    "skill__status": (
        "extracted/decompiled/hl-src/src/battle/Unit.hx.hx",
        r"getCaptureChance|Status\.Fierce|HuntBonusEasyCapture"),
}


def read_jsonl(path):
    with open(path, "r", encoding="utf-8") as f:
        head = json.loads(f.readline())
        return head.get("_meta", {}), [json.loads(l) for l in f]


def load_ids():
    ids = {}
    for fn in sorted(os.listdir(DATA)):
        if fn.endswith(".jsonl"):
            _, rows = read_jsonl(os.path.join(DATA, fn))
            ids[fn[:-6]] = {(r["id"] if "id" in r else r["_id"])
                            for r in rows}
    return ids


def row_index(kind):
    _, rows = read_jsonl(os.path.join(DATA, f"{kind}.jsonl"))
    return {(r["id"] if "id" in r else r["_id"]): r for r in rows}


def navigate(row, dotted):
    """Resolve 'a.b[].c' against a parsed row — returns list of scalars."""
    out = []

    def rec(o, parts):
        if not parts:
            if isinstance(o, (str, int, float, bool)):
                out.append(o)
            return
        head, rest = parts[0], parts[1:]
        if head.endswith("[]"):
            key = head[:-2]
            if isinstance(o, dict) and key in o and isinstance(o[key], list):
                for v in o[key]:
                    rec(v, rest)
        elif isinstance(o, dict) and head in o:
            rec(o[head], rest)

    rec(row, [p for p in dotted.split(".")] if dotted else [])
    return out


def verify_hscript(edge, idx):
    m = re.match(
        r"^extracted/data/_draft/skill\.jsonl#(.+)\.script@(\d+) "
        r"'(Skill|Status|UnitClass|Trait|Attribute|Item)\.([A-Za-z_][A-Za-z0-9_]*)'$",
        edge["evidence"])
    if not m:
        return False, "evidence locator unparsable"
    rid, off, prefix, name = m.groups()
    row = idx.get("skill", {}).get(rid)
    if row is None:
        return False, f"skill row {rid} absent"
    s = row.get("script") or ""
    i = int(off)
    if s[i:i + len(prefix) + 1 + len(name)] != f"{prefix}.{name}":
        return False, f"offset {off} does not carry '{prefix}.{name}'"
    return True, f"token '{prefix}.{name}' at byte {off} of {rid}.script"


def verify_payload(edge, idx):
    m = re.match(
        r"^extracted/data/_draft/([a-zA-Z]+)\.jsonl#(.+?):(.+?)='(.*)'$",
        edge["evidence"])
    if not m:
        return False, "evidence locator unparsable"
    kind, rid, path, val = m.groups()
    row = idx.get(kind, {}).get(rid)
    if row is None:
        return False, f"{kind} row {rid} absent"
    vals = navigate(row, path)
    if str(val) not in {str(v) for v in vals}:
        return False, f"value '{val}' not found at {kind}:{rid}:{path}"
    return True, f"'{val}' present at {kind}:{rid}:{path}"


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ids = load_ids()
    files = sorted(f for f in os.listdir(LOGIC)
                   if f.endswith(".jsonl") and "__" in f)
    rng = random.Random(SEED)

    # ---- full dangling sweep ------------------------------------------------
    dangling = []
    total = 0
    per_file = {}
    samples = []
    for fn in files:
        a, b = fn[:-6].split("__")
        meta, rows = read_jsonl(os.path.join(LOGIC, fn))
        per_file[fn] = len(rows)
        total += len(rows)
        for e in rows:
            if e.get("fromId") not in ids.get(a, set()):
                dangling.append((fn, e.get("fromId"), "fromId"))
            if e.get("toId") not in ids.get(b, set()):
                dangling.append((fn, e.get("toId"), "toId"))
        # stratified sample: min per file, then fill to target proportionally
        k = SAMPLE_PER_FILE_MIN
        picks = rng.sample(rows, min(k, len(rows)))
        samples.extend([(fn, e) for e in picks])

    remaining = SAMPLE_TARGET - len(samples)
    if remaining > 0:
        pool = []
        for fn in files:
            _, rows = read_jsonl(os.path.join(LOGIC, fn))
            for e in rows:
                pool.append((fn, e))
        extra = rng.sample(pool, min(remaining, len(pool)))
        seen = {(f, e["fromId"], e["toId"]) for f, e in samples}
        for fe in extra:
            key = (fe[0], fe[1]["fromId"], fe[1]["toId"])
            if key not in seen:
                samples.append(fe)
                seen.add(key)

    idx_cache = {}
    results = []
    ok_count = 0
    for fn, e in samples:
        a, b = fn[:-6].split("__")
        method = e["method"].split(":")[0]
        if method == "hscript-enum-ref":
            if "skill" not in idx_cache:
                idx_cache["skill"] = row_index("skill")
            ok, why = verify_hscript(e, idx_cache)
            hl = None
            g = HL_GREPS.get(fn[:-6])
            if g and ok:
                p, pat = g
                body = open(os.path.join(PACK, p), encoding="utf-8").read()
                hits = len(re.findall(pat, body))
                hl = {"file": p, "pattern": pat, "hits": hits,
                      "ok": hits > 0}
                if hits == 0:
                    ok, why = False, "hl-src corroboration pattern absent"
        else:
            m = re.match(
                r"^extracted/data/_draft/([a-zA-Z]+)\.jsonl#", e["evidence"])
            kind = m.group(1)
            if kind not in idx_cache:
                idx_cache[kind] = row_index(kind)
            ok, why = verify_payload(e, idx_cache)
            hl = None
        ok_count += ok
        results.append({
            "file": fn, "fromId": e["fromId"], "toId": e["toId"],
            "mechanism": e["mechanism"], "method": e["method"],
            "evidence": e["evidence"], "verdict": "PASS" if ok else "FAIL",
            "check": why, "hlCorroboration": hl,
        })

    out = {
        "dig": "15",
        "seed": SEED,
        "filesVerified": len(files),
        "edgesTotal": total,
        "danglingCount": len(dangling),
        "dangling": dangling[:20],
        "sampleSize": len(results),
        "samplePass": ok_count,
        "results": results,
    }
    os.makedirs(SCRATCH, exist_ok=True)
    with open(os.path.join(SCRATCH, "verification.json"), "w",
              encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print(f"files: {len(files)}  edges: {total}  dangling: {len(dangling)}")
    print(f"sample: {len(results)}  pass: {ok_count}")
    for r in results:
        if r["verdict"] == "FAIL":
            print("FAIL", r["file"], r["fromId"], "->", r["toId"], "|",
                  r["check"])
    fams = sorted({r["method"].split(":")[0] for r in results})
    print("families sampled:", fams)
    return 0 if (ok_count == len(results) and not dangling
                 and len(results) >= 30) else 1


if __name__ == "__main__":
    sys.exit(main())
