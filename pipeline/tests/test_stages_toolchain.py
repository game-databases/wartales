"""Stages 4–6 TOOL layer — spec-stages-datasets.mdx §7 cases T1–T12 +
integration I1–I4 (companion to test_stages_datasets.py, which carries the
fixture/parity/regeneration layers and the AC/T inventory map).

Written against the SPEC's contract under the blind parallel build: the new
tools (``promote_drafts.py``, ``relink_catalog.py``, ``validate_all.py``)
are invoked ONLY through their CLI surfaces (names, arguments, exit codes,
stdout contracts pinned by §3.4/§4.2/§5.1/§5.2) via ``subprocess`` — never
imported, never read. Every case skips on tool-file existence until
CodeWriter lands, then arms automatically.

The mini CastleDB world (``_mini_db``) is a synthetic stand-in shaped to the
verifier's OWN frozen constraints (census line counts, the dig-log wave-1
pair table, Σ 19,130 edges, the 61/9/2 null decomposition) so that TODAY's
proven emitter + verifier round-trip it cleanly (T1) — no A:, no real
corpus, committed numeric expectations only. Its edge budgets are arithmetic,
not game data. Per arbiter F7 it also carries three §7-sketch features the
original build omitted: ONE localizable column (exact-shape textKey ref,
checked by the verifier), ONE undeclared payload key (preserved verbatim +
counted), and ONE id-less sheet under ``_meta.keyRule`` with synthetic ids
(the leaf ``env`` carrier — nothing references it).

Injection discipline: T7 drives the promoter through a ``runpy`` child that
monkeypatches ``os.replace`` to raise mid-copy — the §3.4 rule-2 mechanism —
so atomicity is tested through the pinned surface without touching tool
source.

T10 is split (arbiter F11) into a green case + parametrized one-fault cases
over a session green-tree fixture; the RED case (planted ``place.jsonl``)
runs independently of the other legs' preconditions. The spec's sixth fault,
"deferred list emptied", is NOT injectable through files: the validator
derives ``deferred[]`` from ``wave_kinds.DEFERRED`` against its inline
frozen §3.5 transcription (W1/R7) — no tree artifact feeds it — so that leg
is DROPPED with this cause rather than faked; the deferred content is
pinned by test_stages_datasets.py's deferred-shape fixtures and the
wave_kinds.DEFERRED parity case.

Integration cases (--run-integration, NE8K) drive the real corpus and the
entrypoint; the real-tree legs that would mutate ``extracted/`` state beyond
a stage's own deterministic product (locale_availability regen) snapshot and
restore bytes+mtimes, and the ones needing exclusive mutation of shared
files (constants-drift, corrupted-CDB-through-the-entrypoint) skip with the
manual procedure named instead.
"""

import hashlib
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PACK_ROOT = Path(__file__).resolve().parents[2]
TOOLS = PACK_ROOT / "pipeline" / "tools"
TESTS = PACK_ROOT / "pipeline" / "tests"
HARVEST_CDB = PACK_ROOT / "extracted" / "harvest" / "res" / "data.cdb"
RUN_ALL_PS1 = PACK_ROOT / "run_all.ps1"

PROMOTE = TOOLS / "promote_drafts.py"
CATALOG = TOOLS / "relink_catalog.py"
VALIDATE = TOOLS / "validate_all.py"

BUILDID = "20318128"
BUILDID_ALT = "21238928"                 # §3.6's example next-buildid
EMIT = TOOLS / "cdb_emit.py"
VERIFY = TOOLS / "cdb_verify.py"
STAMP = "2026-08-25T00:00:00"

MANAGED_KINDS = (
    # wave 1
    "class", "item", "skill",
    # wave 2 (37; recipe <- craft)
    "icon", "sound", "counter", "recipe", "bonus", "notify", "loot",
    "fiefEvent", "status", "trait", "groupType", "itemType", "tutorial",
    "input", "env", "confessions", "unitPattern", "credits", "battle",
    "effect", "activity", "startChoice", "fiefGoal", "mission", "fiefPlace",
    "fiefCondition", "fiefLaw", "region", "kingdom", "frescos",
    "fiefAlignment", "fiefAdministration", "fiefPopulation", "amb",
    "fiefMission", "condition", "attribute",
)


def _sheet_of(kind):
    return {"recipe": "craft", "class": "unitClass"}.get(kind, kind)


CENSUS_MINI = {_sheet_of(k): n for k, n in (
    ("icon", 801), ("sound", 848), ("counter", 622), ("recipe", 667),
    ("bonus", 495), ("notify", 482), ("loot", 382), ("fiefEvent", 377),
    ("status", 330), ("trait", 214), ("attribute", 27), ("groupType", 97),
    ("itemType", 96), ("tutorial", 81), ("input", 84), ("env", 87),
    ("confessions", 87), ("unitPattern", 70), ("credits", 67), ("battle", 133),
    ("effect", 66), ("activity", 24), ("startChoice", 29), ("fiefGoal", 55),
    ("mission", 22), ("fiefPlace", 19), ("fiefCondition", 20),
    ("fiefLaw", 43), ("region", 13), ("kingdom", 9), ("frescos", 9),
    ("fiefAlignment", 5), ("fiefAdministration", 15), ("fiefPopulation", 11),
    ("amb", 11), ("fiefMission", 12), ("condition", 18),
    ("item", 2125), ("skill", 1373), ("unitClass", 281),
)}

# ---- mini-world edge budgets (arithmetic, chosen to satisfy the verifier's
# frozen tables: DIG1_EDGES wave-1 pairs, Σ 19,130, nulls 61/9/2) ----------
DIG1 = {
    "class__attribute": 1672, "item__itemType": 2095, "class__item": 914,
    "class__skill": 874, "item__attribute": 728, "class__itemType": 221,
    "class__groupType": 122, "class__region": 10,
}
EDGES_TOTAL = 19_130
NULL_BUDGET = {"env": ("place", 61), "frescos": ("place", 9),
               "fiefGoal": ("element", 2)}          # targets have NO lines


def _spread(total, buckets):
    base, rem = divmod(total, buckets)
    return [base + (1 if i < rem else 0) for i in range(buckets)]


def _sid(sheet, i):
    return f"{sheet}_{i:04d}"


def _mini_db():
    """Deterministic census-shaped CastleDB JSON (dict).

    Edge accounting (all arithmetic, no game content):
      - wave-1 pairs reproduce DIG1 exactly (six unitClass[] lists + item's
        itemType cell + item.attrs[]);
      - env/frescos/fiefGoal carry the 61/9/2 refs into the LINELESS roots
        place/element (valid:null carriers);
      - every remaining census sheet carries one hard ref to its ring
        successor (plus a second ref on the leading rows) until the filler
        budget closes Sigma exactly at 19,130. Sheets are MUTATED in place
        when they need special columns — never shadowed by a second entry.

    §7-sketch features exercised here since arbiter F7: one localizable
    column (`item.label` -> exact-shape textKey ref), one undeclared payload
    key preserved verbatim on a skill row (emitter counter > 0), and ONE
    id-less sheet emitted under `keyRule` with synthetic ids accepted by the
    verifier — the leaf `env` carrier, which nothing references.

    Remaining divergences from the real corpus (disclosure, F7): payloads
    are arithmetic ring refs, not game content; `frescos` keeps a native id
    column here while the real corpus keys it on its unique `place` ref;
    localization is ONE column vs the whole localized corpus; the undeclared
    key is one planted occurrence vs the measured 133; enum/customType tables
    stay empty.
    """
    db = {"sheets": [], "customTypes": []}

    def add_sheet(name, columns, lines):
        assert not any(s["name"] == name for s in db["sheets"]), name
        db["sheets"].append({"name": name, "columns": columns,
                             "lines": lines})

    def sheet_entry(name):
        return next(s for s in db["sheets"] if s["name"] == name)

    idc = {"name": "id", "typeStr": "0", "opt": False}

    # empty datafile-backed roots: declared, ZERO inline lines (§3.5/T3)
    for name in ("place", "element"):
        add_sheet(name, [dict(idc)], [])

    # ---- filler ring over the 37 non-null-budget census sheets -------------
    fillers = [s for s in CENSUS_MINI if s not in NULL_BUDGET]
    rows_fillers = sum(CENSUS_MINI[s] for s in fillers)
    peer_budget = EDGES_TOTAL - sum(DIG1.values()) - sum(
        n for _t, n in NULL_BUDGET.values())
    extra_budget = peer_budget - rows_fillers
    assert 0 <= extra_budget <= rows_fillers

    succ = {}
    for idx, sheet in enumerate(fillers):
        tgt = fillers[(idx + 1) % len(fillers)]          # closed ring
        if (sheet, tgt) == ("item", "itemType"):
            tgt = "icon"      # keep DIG1-pinned item__itemType uncontaminated
        succ[sheet] = tgt

    for sheet in fillers:
        tgt = succ[sheet]
        cols = [dict(idc), {"name": "peer", "typeStr": f"6:{tgt}",
                            "opt": True}]
        extras = min(CENSUS_MINI[sheet], max(extra_budget, 0))
        extra_budget -= extras
        if extras:
            cols.append({"name": "peerB", "typeStr": f"6:{tgt}",
                         "opt": True})
        lines = []
        for i in range(CENSUS_MINI[sheet]):
            row = {"id": _sid(sheet, i), "peer": _sid(tgt, i % CENSUS_MINI[tgt])}
            if i < extras:
                row["peerB"] = _sid(tgt, (i * 7 + 3) % CENSUS_MINI[tgt])
            lines.append(row)
        add_sheet(sheet, cols, lines)

    # ---- null-carrier sheets ----------------------------------------------
    for sheet, (target, count) in NULL_BUDGET.items():
        col_name = "place" if target == "place" else "element"
        # F7: `env` is the mini world's ID-LESS carrier — emitted under
        # `_meta.keyRule` with synthetic zero-padded ids (the §3.2/§10-hole-6
        # path) and accepted by the verifier's synth_id. Nothing references
        # env, so no edge budget moves.
        keyless = sheet == "env"
        cols = ([] if keyless else [dict(idc)]) + [
            {"name": col_name, "typeStr": f"6:{target}", "opt": True}]
        lines = []
        for i in range(CENSUS_MINI[sheet]):
            row = {} if keyless else {"id": _sid(sheet, i)}
            if i < count:
                row[col_name] = _sid(target, i)   # target has no ids -> null
            lines.append(row)
        add_sheet(sheet, cols, lines)

    # ---- item: fold wave-1 columns INTO its filler-ring entry --------------
    item = sheet_entry("item")
    item["columns"] += [
        {"name": "itemType", "typeStr": "6:itemType", "opt": True},
        {"name": "attrs", "typeStr": "8", "opt": True},
        # F7: ONE localizable column — the emitter must render an exact-shape
        # textKey ref and the verifier's exact-shape comparison must accept
        # it (T1's gate proves both at once). `item` keeps TINY_BRIDGE
        # coverage intact for the catalog cases (driftAbsent stays []).
        {"name": "label", "typeStr": "1", "kind": "localizable",
         "opt": True}]
    add_sheet("item@attrs",
              [{"name": "ref", "typeStr": "6:attribute", "opt": False}], [])
    attr_counts = _spread(DIG1["item__attribute"], CENSUS_MINI["item"])
    ctr = 0
    for i, row in enumerate(item["lines"]):
        if i < DIG1["item__itemType"]:
            row["itemType"] = _sid("itemType", i % CENSUS_MINI["itemType"])
        row["label"] = f"tw-item-prose-{i:04d}"
        k = attr_counts[i]
        refs = [_sid("attribute", (ctr + j) % CENSUS_MINI["attribute"])
                for j in range(k)]
        ctr += k
        if refs:
            row["attrs"] = [{"ref": r} for r in refs]

    # ---- unitClass: six list columns carrying the rest of DIG1 -------------
    uc = sheet_entry("unitClass")
    lists = [("attrs", "attribute", DIG1["class__attribute"]),
             ("items", "item", DIG1["class__item"]),
             ("skills", "skill", DIG1["class__skill"]),
             ("itypes", "itemType", DIG1["class__itemType"]),
             ("gtypes", "groupType", DIG1["class__groupType"]),
             ("regs", "region", DIG1["class__region"])]
    for col, target, _n in lists:
        uc["columns"].append({"name": col, "typeStr": "8", "opt": True})
        add_sheet(f"unitClass@{col}",
                  [{"name": "ref", "typeStr": f"6:{target}", "opt": False}],
                  [])
    counters = {col: 0 for col, _t, _n in lists}
    sizes = {col: _spread(n, CENSUS_MINI["unitClass"]) for col, _t, n in lists}
    for i, row in enumerate(uc["lines"]):
        for col, target, _n in lists:
            k = sizes[col][i]
            refs = [_sid(target, (counters[col] + j) % CENSUS_MINI[target])
                    for j in range(k)]
            counters[col] += k
            if refs:
                row[col] = [{"ref": r} for r in refs]

    # ---- F7: one UNDECLARED payload key, preserved verbatim ----------------
    # Outside the declared schema -> the emitter must keep it verbatim and
    # count it (`undeclared payload keys preserved verbatim`), and the
    # verifier's preservation check must accept it (doctrine principle zero).
    sheet_entry("skill")["lines"][0]["__tw_undeclared__"] = \
        "preserve-me-verbatim"

    # ---- builder self-check: the designed edge surface ---------------------
    wave1_pairs = set(DIG1)
    ring_pairs = {f"{s}__{succ[s]}" for s in fillers}
    expected_pairs = wave1_pairs | ring_pairs | set(NULL_BUDGET_COMPOSED)
    assert len(expected_pairs) == MINI_PAIR_FILES == 48
    assert not (ring_pairs & (wave1_pairs | set(NULL_BUDGET_COMPOSED)))
    return db


NULL_BUDGET_COMPOSED = tuple(sorted(f"{k}__{v[0]}" for k, v in NULL_BUDGET.items()))
MINI_PAIR_FILES = 48          # 8 wave-1 + 37 ring + 3 null-carriers


def _write_db(path, db):
    path.write_text(json.dumps(db, ensure_ascii=False), encoding="utf-8")


def _run(cmd, timeout=900, cwd=None):
    return subprocess.run(
        [sys.executable, *[str(c) for c in cmd]],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, cwd=cwd,
    )


def _emit(cdb, outdir, reldir, wave=None, buildid=None):
    cmd = [EMIT, cdb, "--outdir", outdir, "--reldir", reldir]
    if wave:
        cmd += ["--wave", wave]
    if buildid:
        cmd += ["--buildid", buildid]
    return _run(cmd)


def _verify(cdb, datadir, reldir, buildid=None):
    cmd = [VERIFY, cdb, "--datadir", datadir, "--reldir", reldir]
    if buildid:
        cmd += ["--buildid", buildid]
    return _run(cmd)


# ---------------------------------------------------------------------------
# Mini world + promoter scratch fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def mini(tmp_path_factory):
    """The census-shaped mini world: db written once, waves emitted once,
    verifier gated once (T1's subject; reused by T2–T4 + the F7 feature
    case)."""
    root = tmp_path_factory.mktemp("mini")
    db_path = root / "data.cdb"
    _write_db(db_path, _mini_db())
    draft, rel = root / "_draft", root / "_rel"
    outs = []
    for wave in ("wave1", "wave2"):
        r = _emit(db_path, draft, rel, wave=wave)
        assert r.returncode == 0, f"mini emit {wave}:\n{r.stdout}\n{r.stderr}"
        outs.append(r.stdout)
    gate = _verify(db_path, draft, rel)
    return {"root": root, "db": db_path, "draft": draft, "rel": rel,
            "gate": gate, "emit_stdout": "\n".join(outs)}


def _need_tool(path):
    if not path.exists():
        pytest.skip(
            f"{path.name} absent — CodeWriter side of the blind build hasn't "
            "landed yet; suite arms itself automatically")


def _tiny_meta(kind):
    return {"kind": kind, "sourceSheet": _sheet_of(kind), "buildId": BUILDID,
            "container": "res.pak:/data.cdb (CastleDB JSON, compress=false)",
            "rowCount": 2, "emitted": STAMP, "tool": "pipeline/tools/cdb_emit.py"}


def _dataset_bytes(kind):
    head = json.dumps({"_meta": _tiny_meta(kind)}, ensure_ascii=False)
    rows = "\n".join(json.dumps({"id": f"{kind}_{i:04d}"},
                                ensure_ascii=False) for i in range(2))
    return head + "\n" + rows + "\n"


def _pair_name_iter():
    """51 deterministic pair names that INCLUDE the pairs the drift cases
    manipulate (class__skill, item__itemType)."""
    combos = list(itertools.islice(
        itertools.combinations(sorted(MANAGED_KINDS), 2), PAIR_FILES_N - 2))
    combos += [("class", "skill"), ("item", "itemType")]
    assert len(set(combos)) == PAIR_FILES_N == 51
    return combos


PAIR_FILES_N = 51


def _pair_bytes(a, b):
    head = json.dumps({"_meta": {"fromKind": a, "toKind": b,
                                 "mechanism": "hard", "buildId": BUILDID,
                                 "edges": 1, "emitted": STAMP}},
                      ensure_ascii=False)
    edge = json.dumps({"fromId": f"{a}_0000", "toId": f"{b}_0000",
                       "column": "peer", "mechanism": "hard", "valid": True},
                      ensure_ascii=False)
    return head + "\n" + edge + "\n"


def _build_draft_trees(root):
    """A full managed universe of tiny drafts: 40 datasets + 51 pair files."""
    ddraft, rdraft = root / "data_draft", root / "rel_draft"
    ddraft.mkdir(parents=True, exist_ok=True)
    rdraft.mkdir(parents=True, exist_ok=True)
    for kind in MANAGED_KINDS:
        (ddraft / f"{kind}.jsonl").write_text(_dataset_bytes(kind),
                                              encoding="utf-8")
    for a, b in _pair_name_iter():
        (rdraft / f"{a}__{b}.jsonl").write_text(_pair_bytes(a, b),
                                                encoding="utf-8")
    return ddraft, rdraft


@pytest.fixture(scope="session")
def promote_scratch(tmp_path_factory):
    """Session draft trees + the tool path; tests clone out-dirs from here."""
    _need_tool(PROMOTE)
    root = tmp_path_factory.mktemp("promote")
    ddraft, rdraft = _build_draft_trees(root)
    return {"root": root, "ddraft": ddraft, "rdraft": rdraft}


def _clone(src, dst):
    if src.exists():
        shutil.copytree(src, dst)
    else:
        dst.mkdir(parents=True)


def _snapshot(root):
    """relpath -> (size, mtime_ns) of every file under root."""
    return {p.relative_to(root).as_posix(): (p.stat().st_size,
                                             p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*")) if p.is_file()} if root.exists() \
        else {}


def _run_promote(datadir=None, reldir=None, plane="both",
                 out_data=None, out_rel=None, buildid=None):
    cmd = [PROMOTE, "--plane", plane]
    if datadir is not None:
        cmd += ["--datadir", datadir]
    if reldir is not None:
        cmd += ["--reldir", reldir]
    if out_data is not None:
        cmd += ["--out-data", out_data]
    if out_rel is not None:
        cmd += ["--out-relinks", out_rel]
    if buildid is not None:
        cmd += ["--buildid", buildid]
    return _run(cmd)


# ---------------------------------------------------------------------------
# T1–T4 — emit/verify round-trips over the mini world
# ---------------------------------------------------------------------------

def test_t1_mini_cdb_round_trip_emit_then_verify_pass(mini):
    """T1: emit(waves) -> verify PASS on the synthetic census-shaped world."""
    assert mini["gate"].returncode == 0, mini["gate"].stdout
    assert "ALL CHECKS PASSED" in mini["gate"].stdout
    files = sorted(p.name for p in mini["draft"].glob("*.jsonl"))
    assert len(files) == 40
    assert {f[:-6] for f in files} == set(MANAGED_KINDS)
    pairs = sorted(p.name for p in mini["rel"].glob("*__*.jsonl"))
    assert len(pairs) == MINI_PAIR_FILES == 48


def test_t2_planted_dangling_relink_edge_exits_1_naming_it(mini, tmp_path):
    """T2 (file-corruption form, runnable today): a dangling toId in a draft
    pair COPY trips the multiset machinery, exit 1, edge named."""
    bad = tmp_path / "bad_rel"
    bad.mkdir()
    for p in mini["rel"].glob("*__*.jsonl"):
        shutil.copy(p, bad / p.name)
    victim = bad / "class__skill.jsonl"
    lines = victim.read_text(encoding="utf-8").splitlines()
    edge = json.loads(lines[-1])
    edge["toId"] = "__tw_ghost_skill__"
    lines[-1] = json.dumps(edge, ensure_ascii=False)
    victim.write_text("\n".join(lines) + "\n", encoding="utf-8")

    r = _verify(mini["db"], mini["draft"], bad)
    assert r.returncode == 1
    assert "__tw_ghost_skill__" in r.stdout
    assert ("UNEXPECTED edge" in r.stdout) or ("MISSING edge" in r.stdout)


def test_t2b_cdb_seeded_dangling_ref_fails_packwide(tmp_path):
    """T2 (fixture-seeded form, spec §3.3/§4.4 dangling≠0 policy): a ref
    whose target id does not exist makes the GATE exit 1 through the
    pack-wide dangling invariant (F6-tool landed in W2; the old probe-skip
    is retired). The ruled fail line is COUNT-ONLY — here emission agrees
    with the independent recomputation, so the multiset machinery stays
    silent and NO edge name ships; assert exactly the ruled line."""
    db = _mini_db()
    for s in db["sheets"]:
        if s["name"] == "item":
            for row in s["lines"][:1]:
                row["itemType"] = "__tw_no_such_itemType__"
    db_path = tmp_path / "dangling.cdb"
    _write_db(db_path, db)
    draft, rel = tmp_path / "d", tmp_path / "r"
    for wave in ("wave1", "wave2"):
        r = _emit(db_path, draft, rel, wave=wave)
        assert r.returncode == 0, r.stderr
    gate = _verify(db_path, draft, rel)
    assert gate.returncode == 1, gate.stdout
    assert "pack-wide dangling invariant: 1 != 0" in gate.stdout


def test_t3_empty_target_sheet_ref_is_null_pass_dangling_0(mini):
    """T3 / defect-1 rule: refs into declared-but-lineless sheets ship as
    valid:null (unverifiable), never dangling; the gate stays green."""
    assert mini["gate"].returncode == 0
    m = re.search(r"dangling (\d+), unverifiable (\d+)",
                  mini["gate"].stdout)
    assert m and tuple(map(int, m.groups())) == (0, 72)
    got = {}
    for p in mini["rel"].glob("*__*.jsonl"):
        lines = p.read_text(encoding="utf-8").splitlines()
        n = sum(1 for x in lines[1:]
                if json.loads(x).get("valid") is None)
        if n:
            got[p.name[:-6]] = n
    assert got == {"env__place": 61, "frescos__place": 9,
                   "fiefGoal__element": 2}


def test_hole1_non_pair_reldir_entry_skipped_and_enumerated(mini, tmp_path):
    """Hole-1 name rule at the verifier surface (spec §10): a reldir entry
    that is not `<from>__<to>.jsonl` — the D7 poi_coordinates.jsonl orphan —
    is skipped AND enumerated, never parsed as a pair file; the gate stays
    green over an otherwise clean plane. (The H-battery's 'non-pair reldir'
    mutant dies here: a verifier that parsed every .jsonl would fail on the
    planted body instead of enumerating it.)"""
    bad = tmp_path / "rel_with_orphan"
    bad.mkdir()
    for p in mini["rel"].glob("*__*.jsonl"):
        shutil.copy(p, bad / p.name)
    # deliberately pair-unparseable _meta: only the NAME rule keeps this
    # file out of the pair machinery
    (bad / "poi_coordinates.jsonl").write_text('{"_meta":{"edges":"x"}}\n',
                                               encoding="utf-8")
    r = _verify(mini["db"], mini["draft"], bad)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "relink skipped (not <from>__<to>.jsonl)" in r.stdout
    assert "poi_coordinates.jsonl" in r.stdout


def test_f7_mini_world_covers_localizable_undeclared_and_keyrule(mini):
    """Arbiter F7 closure: the mini world now exercises, OFFLINE, the three
    §7-sketch features that previously rode only on corpus-conditional
    layers — textKey fidelity through the verifier's exact-shape check,
    undeclared-key preservation with counter > 0, and the id-less/keyRule
    synthetic-id path accepted by the gate (T1's green is the proof)."""
    assert mini["gate"].returncode == 0, mini["gate"].stdout
    # 1. localizable column -> exact-shape textKey refs in the emitted bytes
    rows = [json.loads(x) for x in
            (mini["draft"] / "item.jsonl").read_text(
                encoding="utf-8").splitlines()[1:]]
    checked = 0
    for r in rows:
        ref = (r.get("label") or {}).get("textKey")
        if ref is None:
            continue
        assert set(ref) >= {"bridge", "sheet", "column", "row"}
        assert ref["bridge"] == "lang/export_<locale>.xml"
        assert ref["sheet"] == "item" and ref["column"] == "label"
        assert ref["row"] == r["id"]
        checked += 1
    assert checked > 0, "localizable column produced no textKey ref"
    # 2. undeclared payload key preserved verbatim + counted by the emitter
    m = re.search(r"undeclared payload keys preserved verbatim: (\{.*\})",
                  mini["emit_stdout"])
    assert m, "emitter printed no preservation counter table"
    table = eval(m.group(1), {"__builtins__": {}})   # noqa: S307 (literal)
    assert table.get("skill@__tw_undeclared__") == 1, table
    preserved = json.loads(
        (mini["draft"] / "skill.jsonl").read_text(
            encoding="utf-8").splitlines()[1])
    assert preserved["__tw_undeclared__"] == "preserve-me-verbatim"
    mg = re.search(r"undeclared payload keys preserved verbatim:\s*(\d+)",
                   mini["gate"].stdout)
    assert mg and int(mg.group(1)) >= 1              # verifier counts it too
    # 3. id-less sheet under keyRule with synthetic ids, gate-accepted
    env_meta = json.loads((mini["draft"] / "env.jsonl").read_text(
        encoding="utf-8").splitlines()[0])["_meta"]
    assert env_meta["kind"] == "env"
    assert all(c["name"] != "id" or c["typeStr"] != "0"
               for c in env_meta["columns"])
    assert "zero-padded row ordinal" in env_meta["keyRule"]
    env_rows = [json.loads(x) for x in
                (mini["draft"] / "env.jsonl").read_text(
                    encoding="utf-8").splitlines()[1:]]
    assert [r["id"] for r in env_rows[:2]] == ["env-0000", "env-0001"]


def test_t4_buildid_flag_stamp_accept_reject_default(mini, tmp_path):
    """T4 / §3.6 retrofit: --buildid stamps X, verify accepts X and rejects
    Y≠X, default absence keeps 20318128. Skips (by stamped-byte probe)
    while the tools still carry the hardcoded constant."""
    alt_root = tmp_path / "alt"
    draft, rel = alt_root / "d", alt_root / "r"
    r = _emit(mini["db"], draft, rel, wave="wave1", buildid=BUILDID_ALT)
    assert r.returncode == 0, r.stderr
    stamped = json.loads(
        (draft / "item.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )["_meta"]["buildId"]
    if stamped != BUILDID_ALT:
        pytest.skip(
            "cdb_emit ignores --buildid (hardcoded BUILD_ID) — spec §3.6 "
            "retrofit not landed; arms automatically when it does")
    # verify accepts X
    ok = _verify(mini["db"], draft, rel, buildid=BUILDID_ALT)
    assert ok.returncode == 0, ok.stdout
    # ...and rejects Y ≠ X
    bad = _verify(mini["db"], draft, rel, buildid="99999999")
    assert bad.returncode == 1
    assert "99999999" in bad.stdout or "buildId" in bad.stdout
    # default absence keeps the pinned client buildid
    dflt_root = tmp_path / "dflt"
    dd, rr = dflt_root / "d", dflt_root / "r"
    r = _emit(mini["db"], dd, rr, wave="wave1")
    assert r.returncode == 0
    assert json.loads((dd / "item.jsonl").read_text(
        encoding="utf-8").splitlines()[0])["_meta"]["buildId"] == BUILDID


# ---------------------------------------------------------------------------
# T5–T7, T11 — promote_drafts (CLI-only)
# ---------------------------------------------------------------------------

def test_t5_promoter_idempotent_second_run_untouched_mtimes(promote_scratch,
                                                            tmp_path):
    """T5 / AC3: first run populates; immediate second run is all-unchanged
    with mtimes untouched; a tampered PAYLOAD row makes exactly that file
    update; tampering ONLY _meta.emitted is exempt-skipped; tampering ONLY
    _meta.buildId updates (F5); a CRLF twin of the payload updates (R2)."""
    out_d, out_r = tmp_path / "od", tmp_path / "or"
    r1 = _run_promote(promote_scratch["ddraft"], promote_scratch["rdraft"],
                      out_data=out_d, out_rel=out_r)
    assert r1.returncode == 0, r1.stdout + r1.stderr
    assert len(list(out_d.glob("*.jsonl"))) == 40
    assert len(list(out_r.glob("*__*.jsonl"))) == 51

    snap = _snapshot(out_d)
    r2 = _run_promote(promote_scratch["ddraft"], promote_scratch["rdraft"],
                      out_data=out_d, out_rel=out_r)
    assert r2.returncode == 0, r2.stdout
    assert _snapshot(out_d) == snap                    # mtimes preserved

    # payload tamper -> exactly that file updated (restored), others idle
    victim = out_d / "trait.jsonl"
    lines = victim.read_text(encoding="utf-8").splitlines()
    lines[1] = json.dumps({"id": "__tw_tampered__"})
    victim.write_text("\n".join(lines) + "\n", encoding="utf-8")
    before = _snapshot(out_d)
    r3 = _run_promote(promote_scratch["ddraft"], promote_scratch["rdraft"],
                      out_data=out_d, out_rel=out_r)
    assert r3.returncode == 0, r3.stdout
    after = _snapshot(out_d)
    changed = {k for k in before if before[k] != after[k]}
    assert changed == {"trait.jsonl"}, changed
    assert json.loads((out_d / "trait.jsonl").read_text(
        encoding="utf-8").splitlines()[1]) == {"id": "trait_0000"}

    # _meta.emitted-only difference -> exempt skip (target untouched)
    victim = out_d / "skill.jsonl"
    lines = victim.read_text(encoding="utf-8").splitlines()
    meta = json.loads(lines[0])
    meta["_meta"]["emitted"] = "1999-01-01T00:00:00"
    lines[0] = json.dumps(meta, ensure_ascii=False)
    victim.write_text("\n".join(lines) + "\n", encoding="utf-8")
    before = _snapshot(out_d)
    r4 = _run_promote(promote_scratch["ddraft"], promote_scratch["rdraft"],
                      out_data=out_d, out_rel=out_r)
    assert r4.returncode == 0
    assert _snapshot(out_d) == before                  # skipped, mtime kept
    assert "1999-01-01" in victim.read_text(encoding="utf-8")

    # F5: tampering ONLY _meta.buildId in the target -> updated. Mutant-
    # killing (H-A): a meta_equal() exempting ALL _meta fields would skip
    # here and go red on the exactly-one-file expectation.
    victim = out_d / "notify.jsonl"
    lines = victim.read_text(encoding="utf-8").splitlines()
    meta = json.loads(lines[0])
    meta["_meta"]["buildId"] = "99999999"
    lines[0] = json.dumps(meta, ensure_ascii=False)
    victim.write_text("\n".join(lines) + "\n", encoding="utf-8")
    before = _snapshot(out_d)
    r5 = _run_promote(promote_scratch["ddraft"], promote_scratch["rdraft"],
                      out_data=out_d, out_rel=out_r)
    assert r5.returncode == 0, r5.stdout
    after = _snapshot(out_d)
    changed = {k for k in before if before[k] != after[k]}
    assert changed == {"notify.jsonl"}, changed
    assert victim.read_bytes() == (
        promote_scratch["ddraft"] / "notify.jsonl").read_bytes()

    # R2-regression (W3-1): payload equality is BYTE-exact — a target whose
    # payload line endings differ from the draft's is drift, counted
    # `updated`, healed back to the EXACT draft bytes (line-ending drift
    # must never read as equality).
    draft_bytes = (
        promote_scratch["ddraft"] / "bonus.jsonl").read_bytes()
    twin = out_d / "bonus.jsonl"
    twin.write_bytes(draft_bytes.replace(b"\r\n", b"\n"))   # LF-normalized
    before = _snapshot(out_d)
    r6 = _run_promote(promote_scratch["ddraft"], promote_scratch["rdraft"],
                      out_data=out_d, out_rel=out_r)
    assert r6.returncode == 0, r6.stdout
    after = _snapshot(out_d)
    changed = {k for k in before if before[k] != after[k]}
    assert changed == {"bonus.jsonl"}, changed
    assert twin.read_bytes() == draft_bytes            # healed byte-exact


def test_t6_promoter_trips_on_ghost_and_enumerates_non_managed(
        promote_scratch, tmp_path):
    """T6 / arbiter F1+F5: ghost/stale managed-name canonical -> exit 1
    NAMING it, nothing deleted; co-located stage products ignored; the six
    non-managed data-plane drafts + the relinks orphan are skipped and
    enumerated on stdout, never promoted; non-managed canonical names never
    tripwire (whitelist, not blacklist)."""
    out_d, out_r = tmp_path / "od", tmp_path / "or"
    assert _run_promote(promote_scratch["ddraft"], promote_scratch["rdraft"],
                        out_data=out_d, out_rel=out_r).returncode == 0

    # ghosts, one per owning plane: managed-name canonical whose draft
    # disappears trips ITS stage at exit 1, naming the file, deleting nothing
    (promote_scratch["ddraft"] / "trait.jsonl").unlink()
    before = _snapshot(out_d) | _snapshot(out_r)
    r = _run_promote(promote_scratch["ddraft"], promote_scratch["rdraft"],
                     plane="data", out_data=out_d, out_rel=out_r)
    assert r.returncode == 1, r.stdout
    assert "trait.jsonl" in r.stdout
    assert (_snapshot(out_d) | _snapshot(out_r)) == before   # nothing deleted
    (promote_scratch["ddraft"] / "trait.jsonl").write_text(
        _dataset_bytes("trait"), encoding="utf-8")

    (promote_scratch["rdraft"] / "class__skill.jsonl").unlink()
    before = _snapshot(out_d) | _snapshot(out_r)
    r = _run_promote(promote_scratch["ddraft"], promote_scratch["rdraft"],
                     plane="relinks", out_data=out_d, out_rel=out_r)
    assert r.returncode == 1, r.stdout
    assert "class__skill.jsonl" in r.stdout
    assert (_snapshot(out_d) | _snapshot(out_r)) == before
    (promote_scratch["rdraft"] / "class__skill.jsonl").write_text(
        _pair_bytes("class", "skill"), encoding="utf-8")

    # co-located products + non-managed entries, both planes
    (out_d / "maps.json").write_text("{}\n", encoding="utf-8")
    cells = out_d / "cells"
    cells.mkdir(exist_ok=True)
    (cells / "x.json").write_text("{}\n", encoding="utf-8")
    (out_d / "locale_availability.jsonl").write_text("", encoding="utf-8")
    (out_r / "RELATIONS.md").write_text("# R\n", encoding="utf-8")
    (out_r / "matrix.json").write_text("{}\n", encoding="utf-8")
    for name in ("achievement.jsonl", "place.jsonl", "group.jsonl",
                 "element.jsonl", "levelProps.jsonl"):
        (promote_scratch["ddraft"] / name).write_text(
            '{"_meta":{"kind":"x"}}\n', encoding="utf-8")
    (promote_scratch["ddraft"] / "worldmap_overlays.json").write_text(
        "{}\n", encoding="utf-8")
    (promote_scratch["rdraft"] / "poi_coordinates.jsonl").write_text(
        '{"_meta":{}}\n', encoding="utf-8")
    # a non-managed CANONICAL name must never tripwire either
    (out_d / "place.jsonl").write_text('{"_meta":{"kind":"place"}}\n',
                                       encoding="utf-8")

    r2 = _run_promote(promote_scratch["ddraft"], promote_scratch["rdraft"],
                      out_data=out_d, out_rel=out_r)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    for name in ("achievement.jsonl", "place.jsonl", "group.jsonl",
                 "element.jsonl", "levelProps.jsonl",
                 "worldmap_overlays.json"):
        assert name in r2.stdout                        # enumerated...
        assert not (out_d / name).exists() or name == "place.jsonl"
    assert "poi_coordinates" in r2.stdout
    assert not (out_r / "poi_coordinates.jsonl").exists()
    assert (out_d / "maps.json").read_text(encoding="utf-8") == "{}\n"
    assert (out_d / "locale_availability.jsonl").read_text() == ""
    assert (out_r / "RELATIONS.md").read_text(encoding="utf-8") == "# R\n"


def test_ac9_restore_and_pass_and_regenerated_exempt(promote_scratch,
                                                     tmp_path):
    """AC9 executable half: deleting a managed canonical file is restored
    from its draft at exit 0 (counted updated); regenerated products are
    exempt from every tripwire."""
    out_d, out_r = tmp_path / "od", tmp_path / "or"
    assert _run_promote(promote_scratch["ddraft"], promote_scratch["rdraft"],
                        out_data=out_d, out_rel=out_r).returncode == 0
    (out_d / "loot.jsonl").unlink()
    (out_r / "item__itemType.jsonl").unlink()
    r = _run_promote(promote_scratch["ddraft"], promote_scratch["rdraft"],
                     out_data=out_d, out_rel=out_r)
    assert r.returncode == 0, r.stdout
    assert (out_d / "loot.jsonl").read_text(encoding="utf-8") == \
        _dataset_bytes("loot")
    assert (out_r / "item__itemType.jsonl").exists()


def test_t7_promoter_atomic_no_part_residue_target_intact(promote_scratch,
                                                          tmp_path):
    """T7: a mid-copy os.replace failure (§3.4 rule-2 mechanism, injected in
    a runpy child — no tool source touched) leaves no .part residue and the
    previous target intact."""
    out_d = tmp_path / "od"
    out_r = tmp_path / "or"
    assert _run_promote(promote_scratch["ddraft"], promote_scratch["rdraft"],
                        out_data=out_d, out_rel=out_r).returncode == 0
    target = "confessions.jsonl"
    victim = out_d / target
    victim.write_text('{"_meta":{"kind":"confessions","tampered":true}}\n',
                      encoding="utf-8")           # observable "previous" state

    driver = tmp_path / "inject_tw.py"
    driver.write_text(
        "import os, runpy, sys\n"
        "real = os.replace\n"
        "tool, needle, *rest = sys.argv[1:]\n"
        "def replace(src, dst):\n"
        "    if str(dst).endswith(needle):\n"
        "        raise RuntimeError('tw-injected mid-copy failure')\n"
        "    return real(src, dst)\n"
        "os.replace = replace\n"
        "sys.argv = [tool] + rest\n"
        "runpy.run_path(tool, run_name='__main__')\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(driver), str(PROMOTE), target,
         "--plane", "both",
         "--datadir", str(promote_scratch["ddraft"]),
         "--reldir", str(promote_scratch["rdraft"]),
         "--out-data", str(out_d), "--out-relinks", str(out_r)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300)
    assert proc.returncode != 0, "injected failure did not stop the promoter"
    assert not list(out_d.rglob("*.part")) and not list(out_r.rglob("*.part"))
    assert "tampered" in victim.read_text(encoding="utf-8")   # previous intact
    # and an honest rerun heals it
    r = _run_promote(promote_scratch["ddraft"], promote_scratch["rdraft"],
                     out_data=out_d, out_rel=out_r)
    assert r.returncode == 0
    assert "tampered" not in victim.read_text(encoding="utf-8")


def test_t11_exit_code_surface_missing_precondition_exit_2(promote_scratch,
                                                           tmp_path):
    """T11 / §3.4 rules 3–4 + §5.2: 0 healthy, 1 drift/tripwire, 2 missing
    precondition (promoter), 2 missing inputs (validator)."""
    out_d, out_r = tmp_path / "od", tmp_path / "or"
    assert _run_promote(promote_scratch["ddraft"], promote_scratch["rdraft"],
                        out_data=out_d, out_rel=out_r).returncode == 0
    # 0: healthy rerun
    assert _run_promote(promote_scratch["ddraft"], promote_scratch["rdraft"],
                        out_data=out_d, out_rel=out_r).returncode == 0
    # 1: ghost/stale tripwire
    (promote_scratch["ddraft"] / "bonus.jsonl").unlink()
    assert _run_promote(promote_scratch["ddraft"], promote_scratch["rdraft"],
                        out_data=out_d, out_rel=out_r).returncode == 1
    (promote_scratch["ddraft"] / "bonus.jsonl").write_text(
        _dataset_bytes("bonus"), encoding="utf-8")
    # 2: missing precondition — the referenced draft dir does not exist
    r = _run_promote(tmp_path / "no_such_dir", promote_scratch["rdraft"],
                     out_data=out_d, out_rel=out_r)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "no_such_dir" in (r.stdout + r.stderr)


# ---------------------------------------------------------------------------
# T8, T9, T12, T13 — relink_catalog (CLI-only, full 40-kind universe)
# ---------------------------------------------------------------------------

CAT_KINDS = ("item", "skill", "trait")     # C(3,2) = 3 arithmetic, pinned in
                                           # test_stages_datasets.test_f7

TINY_BRIDGE = ('<?xml version="1.0" encoding="UTF-8"?>'
               '<cdb><sheet name="item"><i1><name>Item One</name></i1>'
               '<i2><name>Item Two</name></i2></sheet>'
               '<sheet name="skill"><s1><name>Skill One</name></s1></sheet>'
               '</cdb>')

# NOTE on scale: the spec's T8 sketch says "3 kinds => 3 rows"; the landed
# tool (faithfully to AC1/F11) admits ONLY exactly-the-40-managed-kinds
# canonical input, so these cases drive the same semantic assertions at
# universe scale over fully synthetic bytes — 780 scaffold rows with three
# crafted evidence pairs. The divergence is reported to the arbiter.


def _cat_world(root, mini_env, *, reversed_write=False):
    """Full 40-kind synthetic canonical set + a fully crafted relink plane
    of exactly five evidence files: skill->item many:many one-way,
    item->trait 1:1, and the FROZEN null ledger (env__place 61 /
    frescos__place 9 / fiefGoal__element 2 — the catalog freezes this
    decomposition per §4.4). Pairs without files scaffold as partial/
    missing WITH their unblock. reversed_write=True writes everything in
    the opposite order (the arbiter-F13 input)."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "bridge_en.xml").write_text(TINY_BRIDGE, encoding="utf-8")
    data, rel = root / "data", root / "relinks"
    data.mkdir(parents=True)
    rel.mkdir(parents=True)
    ops = []

    def w(path, text):
        ops.append((path, text))

    for src in sorted(mini_env["draft"].glob("*.jsonl")):
        w(data / src.name, src.read_text(encoding="utf-8"))

    def pair_head(frm, n):
        return json.dumps({"_meta": {"fromKind": frm[0], "toKind": frm[1],
                                     "mechanism": "hard", "edges": n,
                                     "buildId": BUILDID}},
                          ensure_ascii=False) + "\n"

    def null_file(fk, tk, count):
        body = "".join(
            json.dumps({"fromId": _sid(fk, i), "toId": _sid(tk, i),
                        "column": tk, "mechanism": "hard",
                        "valid": None}) + "\n" for i in range(count))
        return pair_head((fk, tk), count) + body

    w(rel / "skill__item.jsonl", pair_head(("skill", "item"), 4) + "".join(
        json.dumps(e) + "\n" for e in (
            {"fromId": _sid("skill", 0), "toId": _sid("item", 0),
             "column": "spells", "mechanism": "hard", "valid": True},
            {"fromId": _sid("skill", 0), "toId": _sid("item", 0),
             "column": "spells", "mechanism": "hard", "valid": True},
            {"fromId": _sid("skill", 1), "toId": _sid("item", 1),
             "column": "spells", "mechanism": "hard", "valid": True},
            {"fromId": _sid("skill", 2), "toId": _sid("item", 2),
             "column": "spells", "mechanism": "hard", "valid": True})))
    # E=4, F=3, T=3: hits NO mechanical branch (many:1 needs F==E, its mirror
    # needs T==E, 1:1 needs F==T==E) => unambiguous `many:many`
    w(rel / "item__trait.jsonl", pair_head(("item", "trait"), 1) + json.dumps(
        {"fromId": _sid("item", 0), "toId": _sid("trait", 0),
         "column": "grants", "mechanism": "hard", "valid": True}) + "\n")
    # the frozen unverifiable ledger (§4.4): 61 / 9 / 2
    w(rel / "env__place.jsonl", null_file("env", "place", 61))
    w(rel / "frescos__place.jsonl", null_file("frescos", "place", 9))
    w(rel / "fiefGoal__element.jsonl", null_file("fiefGoal", "element", 2))
    for path, text in reversed(ops) if reversed_write else ops:
        path.write_text(text, encoding="utf-8")
    return data, rel


def _run_catalog(data, rel, md, matrix, bridge=None):
    if bridge is None:
        bridge = data.parent / "bridge_en.xml"
        if not bridge.exists():     # real-tree callers bring their own
            bridge = PACK_ROOT / "extracted" / "harvest" / "_lang-bridge" \
                / "export_en.xml"
    cmd = [CATALOG, "--datadir", data, "--reldir", rel,
           "--bridge", bridge,
           "--out-md", md, "--out-json", matrix]
    return _run(cmd)


def test_t8_catalog_scaffold_semantics_on_synthetic_universe(tmp_path, mini):
    """T8 at universe scale: 780 rows; the modeled direction carries
    joinKeys / cardinality triple / mechanism; the reverse of a one-way pair
    renders partial-or-missing WITH an unblock; deferred-target pairs carry
    R1; every non-modeled direction carries exactly one unblock."""
    _need_tool(CATALOG)
    data, rel = _cat_world(tmp_path / "cat", mini)
    md, matrix = tmp_path / "cat" / "RELATIONS.md", \
        tmp_path / "cat" / "matrix.json"
    r = _run_catalog(data, rel, md, matrix)
    assert r.returncode == 0, r.stdout + r.stderr
    doc = json.loads(matrix.read_text(encoding="utf-8"))
    # F8: wherever matrix.json is loaded, the textKey drift ledger is empty
    assert doc["textKeyCoverage"]["driftAbsent"] == []
    assert doc["kindCount"] == 40 and doc["pairCount"] == 780
    assert len(doc["pairs"]) == 780
    # synthetic totals: 4 + 1 evidence edges + the frozen 72-null ledger
    assert doc["totals"]["edges"] == 77
    assert doc["totals"]["validNull"] == 72 and \
        doc["totals"]["validFalse"] == 0
    key = lambda x: (x["a"], x["b"])          # noqa: E731
    assert [key(x) for x in doc["pairs"]] == sorted(key(x)
                                                    for x in doc["pairs"])
    recs = {key(x): x for x in doc["pairs"]}
    statuses = {s for x in doc["pairs"]
                for s in (x["forward"]["status"], x["reverse"]["status"])}
    assert statuses <= {"modeled", "partial", "missing"}
    for x in doc["pairs"]:
        for side in ("forward", "reverse"):
            d = x[side]
            if d["status"] != "modeled":
                assert d.get("unblock"), (x["a"], x["b"], side)

    # many:many one-way: skill->item modeled, item->skill scaffolded
    rs = recs[("item", "skill")]
    fwd, rev = rs["forward"], rs["reverse"]
    assert fwd["status"] in ("partial", "missing") and fwd["unblock"]
    assert rev["status"] == "modeled"
    assert rev["edges"] == 4 and rev["joinKeys"] == ["spells"]
    assert rev["cardinality"] == "many:many"        # E=4, F=3, T=3 (else-branch)
    assert "hard" in rev["mechanism"]
    assert rev["validCounts"] == {"true": 4, "false": 0, "null": 0}
    assert rev.get("unblock") in (None, "")

    # 1:1 mirror case: E=F=T=1
    it = recs[("item", "trait")]
    modeled = it["forward"] if it["forward"]["status"] == "modeled" \
        else it["reverse"]
    assert modeled["cardinality"] == "1:1"

    # deferred-target leg: env->place lives beside the 780 and carries R1
    dt = json.dumps(doc.get("deferredTargetPairs", []))
    assert "env" in dt and "place" in dt
    assert "R1" in dt, "deferred-target pair lacks the HBSON-decode unblock"


def test_t9_relations_md_parity_with_matrix_json(tmp_path, mini):
    """T9: RELATIONS.md is rendered FROM matrix.json — the Full-matrix
    section carries one row per record whose direction summaries equal the
    JSON fields, and the byte-derived sha marker matches matrix.json."""
    _need_tool(CATALOG)
    root = tmp_path / "cat"
    data, rel = _cat_world(root, mini)
    md, matrix = root / "RELATIONS.md", root / "matrix.json"
    assert _run_catalog(data, rel, md, matrix).returncode == 0
    doc = json.loads(matrix.read_text(encoding="utf-8"))
    recs = {(x["a"], x["b"]): x for x in doc["pairs"]}
    text = md.read_text(encoding="utf-8")
    start = text.index("## Full matrix")
    nxt = text.find("\n## ", start + 1)
    sec = text[start:nxt if nxt != -1 else len(text)]
    rows = [ln for ln in sec.splitlines() if ln.startswith("| `")]
    assert len(rows) == 780
    seen = set()
    pat = re.compile(
        r"(\w+) · E=(\d+) · card=([\w:]+) · keys=\[([^\]]*)\] · "
        r"mech=([^·|]*) · v=(\d+/\d+/\d+)")
    for ln in rows:
        cells = [c.strip() for c in ln.strip("|").split("|")]
        label = cells[0].strip("`").replace("–", "-")     # a–b en dash
        rec = recs[tuple(label.split("-"))]   # kind names carry no dashes
        seen.add(tuple(label.split("-")))
        for cell, side in ((cells[1], "forward"), (cells[2], "reverse")):
            d = rec[side]
            m = pat.match(cell.replace("\\", ""))
            if m:
                # modeled-direction full summary
                assert m.group(1) == d["status"] == "modeled", (label, side)
                assert int(m.group(2)) == d["edges"], (label, side)
                vc = f"{d['validCounts']['true']}/" \
                     f"{d['validCounts']['false']}/{d['validCounts']['null']}"
                assert m.group(6) == vc, (label, side, cell)
                if d["edges"]:
                    assert m.group(4).split(", ") == list(d["joinKeys"])
                    assert m.group(5).strip().split(", ") == \
                        [str(x) for x in d["mechanism"]]
                    assert m.group(3) == d["cardinality"]
            else:
                # scaffolded direction short form: `<status> -> <unblock>`
                ms = re.match(r"(\w+) → (.+)", cell)
                assert ms, (label, side, cell)
                assert ms.group(1) == d["status"] != "modeled", (label, side)
                assert d.get("unblock"), (label, side, "blank unblock")
                assert str(d["unblock"]) in ms.group(2), (label, side, cell)
        # pair-level unblock column: present exactly when not both-modeled
        both_modeled = rec["forward"]["status"] == "modeled" and \
            rec["reverse"]["status"] == "modeled"
        if both_modeled:
            assert cells[3] == "None", ln
        else:
            assert cells[3] and cells[3] != "None", ln   # never blank
    assert seen == set(recs)               # every record, row-for-row
    mk = re.search(r"matrix\.json sha256: `([0-9a-f]{64})`", text)
    assert mk, "MD lacks the byte-derived matrix marker"
    assert mk.group(1) == hashlib.sha256(matrix.read_bytes()).hexdigest()


def test_t12_stage5_products_byte_stable_no_wallclock(tmp_path, mini):
    """T12 / arbiter F9: generating the catalog twice yields byte-identical
    matrix.json + RELATIONS.md; neither carries wall-clock `generated`.
    (validation-report.{json,md} are the declared EXEMPTION — asserted in
    the validator truth-table.)"""
    _need_tool(CATALOG)
    root = tmp_path / "cat"
    data, rel = _cat_world(root, mini)
    md, matrix = root / "RELATIONS.md", root / "matrix.json"
    assert _run_catalog(data, rel, md, matrix).returncode == 0
    h1 = (hashlib.sha256(matrix.read_bytes()).hexdigest(),
          hashlib.sha256(md.read_bytes()).hexdigest())
    md2, matrix2 = root / "R2.md", root / "m2.json"
    assert _run_catalog(data, rel, md2, matrix2).returncode == 0
    h2 = (hashlib.sha256(matrix2.read_bytes()).hexdigest(),
          hashlib.sha256(md2.read_bytes()).hexdigest())
    assert h1 == h2
    mb = matrix.read_text(encoding="utf-8")
    assert '"generated"' not in mb and "'generated'" not in mb
    assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", mb), \
        "wall-clock stamp leaked"
    head = "\n".join(md.read_text(encoding="utf-8").splitlines()[:10])
    assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", head)


def test_t13_catalog_ordering_independent_of_input_order(tmp_path, mini):
    """Arbiter F13 enforcement: shuffled input ORDER (every file written in
    the opposite sequence) produces the identical, lexicographic matrix."""
    _need_tool(CATALOG)
    a_data, a_rel = _cat_world(tmp_path / "ord1", mini)
    b_data, b_rel = _cat_world(tmp_path / "ord2", mini, reversed_write=True)
    out1, out2 = tmp_path / "o1.json", tmp_path / "o2.json"
    assert _run_catalog(a_data, a_rel, tmp_path / "a.md",
                        out1).returncode == 0
    assert _run_catalog(b_data, b_rel, tmp_path / "b.md",
                        out2).returncode == 0
    d1 = json.loads(out1.read_text(encoding="utf-8"))
    d2 = json.loads(out2.read_text(encoding="utf-8"))
    key = lambda r: (r["a"], r["b"])          # noqa: E731
    assert sorted(d1["pairs"], key=key) == sorted(d2["pairs"], key=key)
    assert [key(r) for r in d1["pairs"]] == sorted(key(r)
                                                   for r in d1["pairs"])


SPEC_ENVELOPE_KEYS = {"buildId", "kindCount", "pairCount", "totals", "pairs",
                      "selfPairs", "deferredTargetPairs", "textKeyCoverage"}


def test_matrix_envelope_matches_amended_spec_section_4_2(tmp_path, mini):
    """F2/W5 always-run envelope parity: matrix.json is EXACTLY the amended
    §4.2 enumeration — eight TOP-LEVEL keys (there is no nested `header`
    object; I2's old doc["header"]["pairCount"] KeyError is the regression
    this pins), with the spec-named sub-shapes and an empty drift ledger
    (F8). An envelope rename now fails fast outside --run-integration."""
    _need_tool(CATALOG)
    data, rel = _cat_world(tmp_path / "envelope", mini)
    md, matrix = tmp_path / "envelope" / "RELATIONS.md", \
        tmp_path / "envelope" / "matrix.json"
    assert _run_catalog(data, rel, md, matrix).returncode == 0
    doc = json.loads(matrix.read_text(encoding="utf-8"))
    assert set(doc) == SPEC_ENVELOPE_KEYS
    assert doc["kindCount"] == 40 and doc["pairCount"] == 780
    assert set(doc["totals"]) == {
        "files", "edges", "validTrue", "validFalse", "validNull",
        "modeledDirections", "orderedDirections", "selfPairFiles",
        "deferredTargetFiles"}
    tkc = doc["textKeyCoverage"]
    assert set(tkc) == {"usedSheets", "bridgeSheets", "covered",
                        "driftAbsent"}
    assert tkc["driftAbsent"] == []                      # F8
    for x in doc["pairs"]:
        assert set(x) == {"a", "b", "forward", "reverse", "unblock"}
    for x in doc["deferredTargetPairs"]:
        # §4.2 deferred-target record shape, incl. the two §4.4 ledger fields
        assert set(x) == {"fromKind", "target", "file", "joinKeys", "edges",
                          "cardinality", "mechanism", "validCounts", "state",
                          "unblock", "adjudication"}
        assert x["unblock"] == "R1"


# ---------------------------------------------------------------------------
# T10 — validate_all truth-table over a green synthetic tree (F11 split)
# ---------------------------------------------------------------------------

def _availability_rows(datadir):
    """3,779-row locale_availability.jsonl in the generator's own row shape,
    synthesized from the wave-1 draft ids (numeric contract only). Exactly
    ONE row carries the ∅/∅ locale pair — the measured bimodal law's empty
    arm ({0:458} available / {0:560} named live) pinned LAWFULLY inside the
    green tree; the row count stays 3,779 (F4/W6)."""
    rows = []
    for kind, n in (("item", 2125), ("skill", 1373), ("class", 281)):
        ids = [json.loads(x)["id"] for x in
               (datadir / f"{kind}.jsonl").read_text(
                   encoding="utf-8").splitlines()[1:]]
        assert len(ids) == n, kind
        for rid in ids:
            rows.append(json.dumps({
                "kind": kind, "id": rid,
                "availableLocales": ["en", "fr", "de", "es", "pl", "pt-BR",
                                     "ru", "ko", "zh"],
                "namedLocales": ["en", "fr", "de", "es", "pl", "pt-BR",
                                 "ru", "ko", "zh"],
                "fields": {},
            }, ensure_ascii=False, sort_keys=True))
    last = json.loads(rows[-1])
    last["availableLocales"], last["namedLocales"] = [], []
    rows[-1] = json.dumps(last, ensure_ascii=False, sort_keys=True)
    assert len(rows) == 3_779
    return "\n".join(rows) + "\n"


@pytest.fixture(scope="session")
def st_green(tmp_path_factory):
    """Session GREEN tree for the T10 truth-table (F11 split): the
    validator's checks freeze §2's numbers, so the only tree that can pass
    them is an exact-shape replica — the real draft corpora relocated into
    tmp (never mutating extracted/), plus synthesized availability + catalog
    products. Assembled and validated ONCE; fault cases clone it per-case so
    one fault can never retire another. Skips with the named reason when the
    real inputs are genuinely absent locally."""
    _need_tool(VALIDATE)
    _need_tool(CATALOG)
    if not HARVEST_CDB.exists():
        pytest.skip("validator embeds a real cdb_verify child run; the "
                    "harvest output CDB is absent locally")
    draft_dir = PACK_ROOT / "extracted" / "data" / "_draft"
    seed_dir = PACK_ROOT / "extracted" / "relinks" / "_draft"
    if not (draft_dir / "item.jsonl").exists():
        pytest.skip("real draft corpora absent locally — the validator "
                    "freezes §2's numbers, so no purely invented tree can "
                    "go green")
    seeds = sorted(seed_dir.glob("*__*.jsonl")) if seed_dir.exists() else []
    if len(seeds) != PAIR_FILES_N:
        pytest.skip(f"draft relink seeds number {len(seeds)}, not the "
                    f"frozen {PAIR_FILES_N} — stage inputs drifted")
    root = tmp_path_factory.mktemp("st_green")
    data, rel = root / "data", root / "relinks"
    data.mkdir(parents=True)
    rel.mkdir(parents=True)
    for kind in MANAGED_KINDS:
        shutil.copy(draft_dir / f"{kind}.jsonl", data / f"{kind}.jsonl")
    for p in seeds:
        shutil.copy(p, rel / p.name)
    (rel / "locale_availability.jsonl").write_text(
        _availability_rows(data), encoding="utf-8")
    md, matrix = root / "RELATIONS.md", rel / "matrix.json"
    r = _run_catalog(data, rel, md, matrix)
    if r.returncode != 0:
        pytest.skip("catalog refused the assembled canonical tree: "
                    + (r.stdout + r.stderr)[-300:])
    tree = {"root": root, "data": data, "rel": rel, "md": md,
            "matrix": matrix}
    r = _run_validate(tree)
    if r.returncode == 2:
        pytest.skip(
            "validator exits 2 (missing inputs) on the synthetic tree — an "
            "input outside the spec's CLI surface cannot be provided "
            "offline; arms when the surface allows it")
    assert r.returncode == 0, r.stdout + r.stderr
    return tree


def _run_validate(tree, report=None, mdreport=None):
    _need_tool(VALIDATE)
    report = report or (tree["root"] / "validation-report.json")
    mdreport = mdreport or (tree["root"] / "VALIDATION-REPORT.md")
    # cwd = the tree itself: the validator must be cwd-independent (W1
    # finding A), and a tmp tree can sit on another DRIVE than the pack —
    # ntpath.relpath raises across mounts, so never anchor it to the cwd.
    return _run([VALIDATE, "--cdb", HARVEST_CDB, "--buildid", BUILDID,
                 "--datadir", tree["data"], "--reldir", tree["rel"],
                 "--report", report, "--md", mdreport],
                cwd=tree["root"])


def _fault_tree(st_green, tmp_path, name):
    """A fresh clone of the green tree for ONE fault case; reports are
    OUTPUTS of the validator, never inputs — excluded so a crashed run
    cannot be masked by the green run's stale report (the defect that made
    the old coupled fault-6 leg read a file its own fixture excluded)."""
    dst = tmp_path / f"fault-{name}"
    shutil.copytree(st_green["root"], dst, ignore=shutil.ignore_patterns(
        "validation-report.json", "VALIDATION-REPORT.md"))
    return {"root": dst, "data": dst / "data", "rel": dst / "relinks",
            "md": dst / "RELATIONS.md", "matrix": dst / "relinks"
            / "matrix.json"}


def _check_ids(report_path):
    doc = json.loads(report_path.read_text(encoding="utf-8"))
    return doc, {c["id"]: c["pass"] for c in doc.get("checks", [])}


def test_t10_green_tree_validates_pass_report_contract(st_green):
    """T10 green half: exit 0 / pass:true over the exact-shape tree; the
    report carries closure + buildId + the declared `generated` exemption;
    VALIDATION-REPORT.md states the SAME per-check results as the JSON
    (F13 parse — was existence-only); matrix drift ledger empty (F8)."""
    report = st_green["root"] / "validation-report.json"
    doc, checks = _check_ids(report)
    assert doc["pass"] is True
    assert doc["buildId"] == BUILDID
    assert checks.get("census-closure") is True
    assert "11473" in json.dumps(doc)          # closure embedded (AC7)
    # the declared stamp exemption: run REPORTS carry `generated`
    assert '"generated"' in report.read_text(encoding="utf-8")
    # F8: wherever matrix.json is loaded, the drift ledger must be empty
    mx = json.loads(st_green["matrix"].read_text(encoding="utf-8"))
    assert mx["textKeyCoverage"]["driftAbsent"] == []
    # F13/AC7: parse the MD table; every JSON check id present, same verdict
    mdrep = (st_green["root"] / "VALIDATION-REPORT.md").read_text(
        encoding="utf-8")
    rows = {}
    for ln in mdrep.splitlines():
        m = re.match(r"\| ([a-z0-9-]+) \| .* \| .* \| (true|false) \|$",
                     ln.strip())
        if m:
            rows[m.group(1)] = m.group(2) == "true"
    assert rows, "VALIDATION-REPORT.md carries no check table"
    assert rows == checks


FAULTS = ("rowcount", "dangling-edge", "availability-row-drop",
          "matrix-paircount-diverge", "md-cell-falsified",
          "locale-set-truncated")


@pytest.mark.parametrize("fault", FAULTS)
def test_t10_fault_flips_its_named_check(st_green, tmp_path, fault):
    """T10 fault halves, ONE case each (F11 split — a regression in one leg
    can no longer retire the others): each injected fault exits 1 flipping
    its NAMED check while unrelated checks stay green. The spec's sixth
    fault ('deferred list emptied') has no leg here BY CAUSE: the validator
    derives deferred[] from wave_kinds.DEFERRED against its inline frozen
    §3.5 transcription — no tree artifact feeds it (see module docstring);
    its content is pinned by the datasets-file deferred fixtures + parity."""

    def named(t, cid):
        _, fc = _check_ids(t["root"] / "validation-report.json")
        return fc.get(cid)

    if fault == "rowcount":
        t = _fault_tree(st_green, tmp_path, fault)
        victim = t["data"] / "tutorial.jsonl"
        lines = victim.read_text(encoding="utf-8").splitlines()
        victim.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
        r = _run_validate(t)
        assert r.returncode == 1
        assert named(t, "census-per-kind") is False
        assert named(t, "availability-regenerated") is True

    elif fault == "dangling-edge":
        t = _fault_tree(st_green, tmp_path, fault)
        victim = t["rel"] / "class__skill.jsonl"
        lines = victim.read_text(encoding="utf-8").splitlines()
        e = json.loads(lines[1])
        e["toId"] = "__tw_ghost__"
        lines[1] = json.dumps(e, ensure_ascii=False)
        victim.write_text("\n".join(lines) + "\n", encoding="utf-8")
        r = _run_validate(t)
        assert r.returncode == 1
        assert named(t, "relink-integrity") is False or \
            named(t, "verifier-gates") is False

    elif fault == "availability-row-drop":
        t = _fault_tree(st_green, tmp_path, fault)
        av = t["rel"] / "locale_availability.jsonl"
        av.write_text(
            "".join(av.read_text(encoding="utf-8").splitlines(True)[:-1]),
            encoding="utf-8")
        r = _run_validate(t)
        assert r.returncode == 1
        assert named(t, "availability-regenerated") is False

    elif fault == "matrix-paircount-diverge":
        t = _fault_tree(st_green, tmp_path, fault)
        mj = json.loads(t["matrix"].read_text(encoding="utf-8"))
        mj["pairCount"] = 779
        t["matrix"].write_text(json.dumps(mj, ensure_ascii=False),
                               encoding="utf-8")
        r = _run_validate(t)
        assert r.returncode == 1
        assert named(t, "catalog-parity") is False

    elif fault == "md-cell-falsified":
        # F3/H-B: falsify ONE rendered RELATIONS.md cell's FIELD VALUE (sha
        # marker + row count intact) — the W1 parse-and-compare sub-assertion
        # must see it where sha+row-count alone could not.
        #
        # r2/R13: the validator anchors the rendered file at THE TREE UNDER
        # TEST (<reldir>/../RELATIONS.md — the same root matrix.json comes
        # from), so the victim here is this fault tree's OWN copy. The old
        # leg's window on the SHARED extracted/RELATIONS.md (snapshot /
        # tamper / restore around the run) is gone entirely: the shared
        # artifact is never opened by this suite anymore. The r2/G1+G3
        # atomic-backup hardening is kept verbatim for the local victim —
        # an interrupted restore must still never leave tampered bytes
        # silently behind.
        t = _fault_tree(st_green, tmp_path, fault)
        mj = json.loads(t["matrix"].read_text(encoding="utf-8"))
        modeled = [(p, s) for p in mj["pairs"]
                   for s in ("forward", "reverse")
                   if p[s]["status"] == "modeled" and p[s]["edges"] > 0]
        assert modeled, "no modeled direction to falsify"
        p, side = modeled[0]
        edges = p[side]["edges"]
        label = f"`{p['a']}–{p['b']}`"
        tree_md = t["md"]
        original = tree_md.read_bytes()
        omt = tree_md.stat().st_mtime_ns
        # Restore goes through a FULLY-WRITTEN SAME-VOLUME sibling + ATOMIC
        # os.replace; the BACKUP ITSELF publishes atomically too (r2/G1):
        # staged into a length-verified sibling first, so an ENOSPC mid-
        # staging can never leave a partial .tw-backup behind for the
        # finally below to restore OVER the intact file.
        backup = tree_md.with_name("RELATIONS.md.tw-backup")
        staging = tree_md.with_name("RELATIONS.md.tw-staging")
        # bound BEFORE the try so a pre-tamper raise keeps its true cause
        # instead of dying as an UnboundLocalError in the finally (r2/G3)
        tampered = None
        try:
            staging.write_bytes(original)
            if len(staging.read_bytes()) != len(original):     # r2/G1
                raise RuntimeError(
                    "backup staging short-wrote; refusing to publish a "
                    "partial backup")
            os.replace(staging, backup)
            text = original.decode("utf-8")
            start = text.index("## Full matrix")
            head, sec = text[:start], text[start:]
            # the chosen pair's row: its FIRST modeled cell after the label
            # is the picked direction (forward wins ties by construction)
            needle = re.compile(
                re.escape(f"| {label} | ") + rf"modeled · E={edges} ")
            m = needle.search(sec)
            assert m, f"rendered cell for {label} ({side}) not found"
            sec = sec[:m.start()] + \
                sec[m.start():m.end()].replace(
                    f"E={edges}", f"E={edges - 1}") + sec[m.end():]
            tampered = tree_md.with_name("RELATIONS.md.tw-tampered")
            tampered.write_bytes((head + sec).encode("utf-8"))
            os.replace(tampered, tree_md)
            r = _run_validate(t)
        finally:
            if staging.exists():        # an interrupted staging run leaves
                staging.unlink()        # no debris sibling behind
            if backup.exists():         # exists == fully published (r2/G1)
                os.replace(backup, tree_md)
                os.utime(tree_md, ns=(omt, omt))
            if tampered is not None and tampered.exists():
                tampered.unlink()
        if tree_md.read_bytes() != original:               # loud, never silent
            pytest.fail(
                "tree-local RELATIONS.md failed byte-exact restore — "
                "regenerate with pipeline/tools/relink_catalog.py before "
                "anything else reads it")
        assert r.returncode == 1
        assert named(t, "catalog-parity") is False

    elif fault == "locale-set-truncated":
        # F4/H-C: truncate one row's availableLocales 9 -> 3, row count
        # intact — under-reporting must fail the measured bimodal law.
        t = _fault_tree(st_green, tmp_path, fault)
        av = t["rel"] / "locale_availability.jsonl"
        lines = av.read_text(encoding="utf-8").splitlines()
        for i, ln in enumerate(lines):
            row = json.loads(ln)
            if len(row["availableLocales"]) == 9:
                row["availableLocales"] = ["en", "fr", "de"]
                lines[i] = json.dumps(row, ensure_ascii=False,
                                      sort_keys=True)
                break
        else:
            pytest.fail("no all-9 availability row to truncate")
        av.write_text("\n".join(lines) + "\n", encoding="utf-8")
        r = _run_validate(t)
        assert r.returncode == 1
        assert named(t, "availability-regenerated") is False

    else:
        pytest.fail(f"unhandled T10 fault id {fault!r} — a FAULTS entry "
                    "without a chain branch passes vacuously (r2/G2)")


def test_t10_red_planted_place_jsonl_becomes_a_report_record(st_green,
                                                             tmp_path):
    """T10 RED half (F14/W1), running INDEPENDENTLY of the other legs'
    preconditions: a planted place.jsonl flips hbson-independent to a report
    RECORD — exit 1, report written, no traceback (the validator must record
    every §5.2 check, never crash)."""
    t = _fault_tree(st_green, tmp_path, "hbson-red")
    (t["data"] / "place.jsonl").write_text('{"_meta":{"kind":"place"}}\n',
                                           encoding="utf-8")
    r = _run_validate(t)
    assert r.returncode == 1, \
        "validator exited 0 despite a planted place.jsonl (AC4 breach)"
    rep = t["root"] / "validation-report.json"
    assert rep.exists(), (
        "validator exit 1 left NO report — it crashed instead of recording "
        "the hbson-independent check; stderr tail: " + r.stderr[-300:])
    assert "Traceback" not in r.stderr
    _, fc = _check_ids(rep)
    assert fc.get("hbson-independent") is False


def test_t11_validator_exit_2_missing_inputs(tmp_path):
    """T11 (validator half): missing inputs -> exit 2 naming them."""
    _need_tool(VALIDATE)
    empty = tmp_path / "empty"
    empty.mkdir()
    r = _run([VALIDATE, "--cdb", tmp_path / "absent.cdb",
              "--datadir", empty, "--reldir", empty,
              "--report", tmp_path / "r.json", "--md", tmp_path / "r.md"])
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)


# ---------------------------------------------------------------------------
# Integration layer — real corpus + entrypoint (NE8K, --run-integration)
# ---------------------------------------------------------------------------

def _require(path, what):
    if not Path(path).exists():
        pytest.skip(f"integration artifact absent locally: {what} ({path})")


@pytest.mark.integration
def test_i1_stage4_chain_end_to_end(tmp_path):
    """I1 / §3.1 VERBATIM over the REAL harvested CDB (F1 rewrite — the old
    body gated the real CDB against the MINI session drafts, which provably
    exits 1 on `_meta.columns diverge`): emit waves 1+2 into tmp -> verifier
    GATE -> promote THOSE drafts to a tmp canonical plane -> canonical
    re-verify GATE -> per-kind counts == census, Σ 10,207 -> immediate
    second promotion reports unchanged with mtimes untouched (AC3's promoter
    half; its entrypoint half rides I4)."""
    _need_tool(PROMOTE)
    _require(HARVEST_CDB, "harvest output data.cdb")
    root = tmp_path / "s4"
    draft, rel, canonical = root / "_draft", root / "_rel", root / "data_out"
    # steps 1–2: regenerate the draft corpus deterministically from the CDB
    for wave in ("wave1", "wave2"):
        r = _emit(HARVEST_CDB, draft, rel, wave=wave, buildid=BUILDID)
        assert r.returncode == 0, f"emit {wave}:\n{r.stdout}\n{r.stderr}"
    files = sorted(p.name for p in draft.glob("*.jsonl"))
    assert len(files) == 40
    assert {f[:-6] for f in files} == set(MANAGED_KINDS)
    total = 0
    for kind in MANAGED_KINDS:
        n = len((draft / f"{kind}.jsonl").read_text(
            encoding="utf-8").splitlines()) - 1
        assert n == CENSUS_MINI[_sheet_of(kind)], kind
        total += n
    assert total == 10_207
    # step 3: GATE over the regenerated drafts — canonical write only after 0
    gate1 = _verify(HARVEST_CDB, draft, rel, buildid=BUILDID)
    assert gate1.returncode == 0, gate1.stdout
    assert "ALL CHECKS PASSED" in gate1.stdout
    assert "40 files, 10207 rows" in gate1.stdout
    assert ("edges 19130 (expected 19130), dangling 0, unverifiable 72"
            in gate1.stdout)
    # step 4: promote THE DRAFTS JUST EMITTED (the only canonical write)
    r = _run_promote(datadir=draft, reldir=rel, plane="data",
                     out_data=canonical, buildid=BUILDID)
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(list(canonical.glob("*.jsonl"))) == 40
    # step 5: canonical re-verify — promotion fidelity proven by the gate
    gate2 = _verify(HARVEST_CDB, canonical, rel, buildid=BUILDID)
    assert gate2.returncode == 0, gate2.stdout
    assert "ALL CHECKS PASSED" in gate2.stdout
    canon_total = sum(
        len(p.read_text(encoding="utf-8").splitlines()) - 1
        for p in canonical.glob("*.jsonl"))
    assert canon_total == 10_207
    # AC3 promoter half: second run all-unchanged, mtimes untouched
    snap = {p.name: p.stat().st_mtime_ns for p in canonical.glob("*.jsonl")}
    r2 = _run_promote(datadir=draft, reldir=rel, plane="data",
                      out_data=canonical, buildid=BUILDID)
    assert r2.returncode == 0, r2.stdout
    assert "updated=0" in r2.stdout and "unchanged=40" in r2.stdout
    assert {p.name: p.stat().st_mtime_ns
            for p in canonical.glob("*.jsonl")} == snap


@pytest.mark.integration
def test_i2_stage5_chain_matrix_byte_identity(tmp_path):
    """I2 / §4.1 + AC5/AC6: canonical verify PASS with 19,130/0/72 and the
    exact 61/9/2 decomposition; RELATIONS.md rows == 780; a second catalog
    generation leaves matrix.json + RELATIONS.md byte-identical."""
    _need_tool(PROMOTE)
    _need_tool(CATALOG)
    _require(HARVEST_CDB, "harvest output data.cdb")
    root = tmp_path / "s5"
    data, rel = root / "data", root / "relinks"
    data.mkdir(parents=True)
    rel.mkdir(exist_ok=True)
    draft_dir = PACK_ROOT / "extracted" / "data" / "_draft"
    for kind in MANAGED_KINDS:
        shutil.copy(draft_dir / f"{kind}.jsonl", data / f"{kind}.jsonl")
    for p in (PACK_ROOT / "extracted" / "relinks" / "_draft").glob(
            "*__*.jsonl"):
        shutil.copy(p, rel / p.name)
    # promote the seed pair files through the real CLI surface (the cloned
    # drafts above are the seeds; promotion replaces them in-place)
    seeds = root / "seeds_rel"
    seeds.mkdir()
    for p in rel.glob("*__*.jsonl"):
        shutil.copy(p, seeds / p.name)
    for p in rel.glob("*__*.jsonl"):
        p.unlink()
    rp = _run_promote(plane="relinks", reldir=seeds,
                      datadir=(PACK_ROOT / "extracted" / "data" / "_draft"),
                      out_rel=rel)
    assert rp.returncode == 0, rp.stdout + rp.stderr
    gate = _verify(HARVEST_CDB, data, rel)
    assert gate.returncode == 0, gate.stdout
    assert "dangling 0" in gate.stdout and "unverifiable 72" in gate.stdout
    nulls = {}
    for p in rel.glob("*__*.jsonl"):
        lines = p.read_text(encoding="utf-8").splitlines()[1:]
        n = sum(1 for x in lines if json.loads(x).get("valid") is None)
        if n:
            nulls[p.name[:-6]] = n
    assert nulls == {"env__place": 61, "frescos__place": 9,
                     "fiefGoal__element": 2}
    md, matrix = root / "RELATIONS.md", rel / "matrix.json"
    rc = _run_catalog(data, rel, md, matrix,
                      bridge=PACK_ROOT / "extracted" / "harvest"
                      / "_lang-bridge" / "export_en.xml")
    assert rc.returncode == 0, rc.stdout + rc.stderr
    doc = json.loads(matrix.read_text(encoding="utf-8"))
    # F2: pairCount is TOP-LEVEL (the amended §4.2 envelope has no nested
    # `header` — the old access raised KeyError on every real artifact);
    # pin the full eight-key envelope + empty drift ledger on the REAL
    # artifact too, not only the synthetic parity case.
    assert doc["pairCount"] == 780
    assert set(doc) == SPEC_ENVELOPE_KEYS
    assert doc["textKeyCoverage"]["driftAbsent"] == []          # F8
    assert len(doc["pairs"]) == 780
    h1 = (hashlib.sha256(matrix.read_bytes()).hexdigest(),
          hashlib.sha256(md.read_bytes()).hexdigest())
    rc2 = _run_catalog(data, rel, md, matrix,
                       bridge=PACK_ROOT / "extracted" / "harvest"
                       / "_lang-bridge" / "export_en.xml")
    assert rc2.returncode == 0
    h2 = (hashlib.sha256(matrix.read_bytes()).hexdigest(),
          hashlib.sha256(md.read_bytes()).hexdigest())
    assert h1 == h2                              # arbiter F9 proof


@pytest.mark.integration
def test_i3_availability_rerun_byte_stable_validator_report(tmp_path):
    """I3 / AC7+AC8: the deterministic availability regeneration is
    byte-stable across reruns (bytes snapshotted + restored — the tool owns
    those real paths and is deterministic by seed=buildid), its report grid
    is 27 keys all zero, and the validator reconciles 11,473 over the real
    canonical tree. The constants-drift legs need exclusive mutation of
    extracted/logic/constants.jsonl and are left to the manual procedure
    (spec I3) rather than racing concurrent orchestrators."""
    lbd = TOOLS / "locale_bridge_dig.py"
    avail = PACK_ROOT / "extracted" / "relinks" / "locale_availability.jsonl"
    _require(lbd, "locale_bridge_dig.py")
    before = avail.read_bytes() if avail.exists() else None
    before_mt = avail.stat().st_mtime_ns if avail.exists() else None
    try:
        r = _run([lbd], timeout=1200)
        assert r.returncode == 0, r.stderr[-2000:]
        report = json.loads(r.stdout)
        grid = report["filler_class_cells"]
        keys = {(k, loc) for k in grid for loc in grid[k]}
        assert len(keys) == 27
        assert all(v == 0 for per in grid.values() for v in per.values())
        assert all(grid[k].get("en") == 0 for k in grid)   # structural pivot
                                                           # skip, per kind
        assert avail.exists()
        rows = avail.read_text(encoding="utf-8").splitlines()
        assert len(rows) == 3_779
        per = {}
        for x in rows:
            per[json.loads(x)["kind"]] = per.get(json.loads(x)["kind"], 0) + 1
        assert per == {"item": 2_125, "skill": 1_373, "class": 281}
        r2 = _run([lbd], timeout=1200)
        assert r2.returncode == 0
        if before is not None:
            assert avail.read_bytes() == before   # AC8 rerun byte-identity
        # validator over the REAL canonical planes, when stages 4–6 have run
        if VALIDATE.exists() and (PACK_ROOT / "extracted" / "data" / "item.jsonl")\
                .exists():
            rv = _run([VALIDATE, "--cdb", HARVEST_CDB, "--buildid", BUILDID,
                       "--datadir", PACK_ROOT / "extracted" / "data",
                       "--reldir", PACK_ROOT / "extracted" / "relinks",
                       "--report", tmp_path / "vr.json",
                       "--md", tmp_path / "vr.md"])
            assert rv.returncode == 0, rv.stdout[-2000:]
            doc = json.loads((tmp_path / "vr.json").read_text(
                encoding="utf-8"))
            assert doc["pass"] is True
            assert "11473" in json.dumps(doc)
    finally:
        if before is not None:
            avail.write_bytes(before)
            os.utime(avail, ns=(before_mt, before_mt))


def _log_defaults():
    """The RUN_ALL-DEFAULTS block of EXTRACTION-LOG.md as a dict (the same
    keys run_all.ps1's Read-Defaults consumes)."""
    log = (PACK_ROOT / "EXTRACTION-LOG.md").read_text(encoding="utf-8")
    m = re.search(r"RUN_ALL-DEFAULTS-BEGIN\n(.*?)RUN_ALL-DEFAULTS-END", log,
                  re.S)
    assert m, "EXTRACTION-LOG.md lost its RUN_ALL-DEFAULTS block"
    out = {}
    for ln in m.group(1).splitlines():
        mm = re.match(r"([A-Z]+): (.+)\s*$", ln)
        if mm:
            out[mm.group(1)] = mm.group(2)
    return out


def _stage_product_snapshot():
    """(relpath -> (size, mtime_ns)) over every surface stages 4–6 write —
    bounded stand-in for a whole-extracted/ snapshot (F12 no-mtime leg)."""
    out = {}
    for sub in ("data", "relinks"):
        d = PACK_ROOT / "extracted" / sub
        if d.exists():
            out.update({f"{sub}/{k}": v for k, v in _snapshot(d).items()})
    return out


def test_i4_static_entrypoint_contract_pins_spec_vectors():
    """I4 STATIC half (F12) — always-run greps, no entrypoint invocation:
    run_all.ps1 builds the §3.1/§4.1/§5.1 argv vectors verbatim, requires +
    prints the resolved CDB default, sizes its usage block over the whole
    header, the sh forwarder forwards everything, and EXTRACTION-LOG.md
    carries edits E1–E6 (defaults key, three pinned tool rows, stage table
    rows 4–6 BUILT, isolation paragraph, rerun note, dated history entry).
    The subprocess legs live in the integration case below."""
    text = RUN_ALL_PS1.read_text(encoding="utf-8", errors="replace")
    # §3.1 datasets chain (steps 1–5)
    for frag in (
        "'pipeline/tools/cdb_emit.py', $Cdb",
        "'--outdir', 'extracted/data/_draft'",
        "'--reldir', 'extracted/relinks/_draft'",
        "'--wave', 'wave1'", "'--wave', 'wave2'",
        "'pipeline/tools/cdb_verify.py', $Cdb",
        "'--datadir', 'extracted/data/_draft'",
        "'pipeline/tools/promote_drafts.py', '--plane', 'data',",
        "'--out-data', 'extracted/data',",
        "'--datadir', 'extracted/data'",
    ):
        assert frag in text, frag
    # §4.1 relink chain + §5.1 emit chain
    for frag in (
        "'pipeline/tools/promote_drafts.py', '--plane', 'relinks',",
        "'--out-relinks', 'extracted/relinks'",
        "'pipeline/tools/relink_catalog.py',",
        "'extracted/harvest/_lang-bridge/export_en.xml'",
        "'--out-md', 'extracted/RELATIONS.md'",
        "'--out-json', 'extracted/relinks/matrix.json'",
        "('pipeline/tools/locale_bridge_dig.py')",
        "'pipeline/tools/validate_all.py', '--cdb', $Cdb,",
        "'--report', 'extracted/validation-report.json'",
        "'--md', 'extracted/VALIDATION-REPORT.md'",
    ):
        assert frag in text, frag
    # defaults wiring: CDB required by Read-Defaults and printed by --list
    assert "@('CLIENT', 'BUILDID', 'PAKS', 'OUT', 'CDB', 'PYTHON')" in text
    assert '"  CDB     = {0}"' in text
    # usage block sized over the WHOLE header comment (edit 5)
    m = re.search(r"-TotalCount (\d+)", text)
    assert m, "usage printer lost its -TotalCount literal"
    n_header = 0
    for ln in text.splitlines():
        if ln.startswith("#"):
            n_header += 1
        elif ln.strip():
            break
    assert int(m.group(1)) >= n_header, (m.group(1), n_header)
    # AC10 sentence 6: the sh forwarder forwards EVERY argument verbatim
    sh = (PACK_ROOT / "run_all.sh").read_text(encoding="utf-8")
    assert "exec powershell" in sh and "run_all.ps1" in sh and '"$@"' in sh

    # EXTRACTION-LOG.md edits E1–E6 (spec §6 edit list)
    log = (PACK_ROOT / "EXTRACTION-LOG.md").read_text(encoding="utf-8")
    assert re.search(r"^CDB: extracted/harvest/res/data\.cdb$", log,
                     re.M), "E1"                                   # E1
    for tool in ("promote_drafts.py", "relink_catalog.py",
                 "validate_all.py"):                               # E2
        pat = (r"^\| `pipeline/tools/" + re.escape(tool) +
               r"` .+ sha256 `[0-9a-f]{64}`")
        assert re.search(pat, log, re.M), f"E2 row for {tool}"
    for stage in ("datasets", "relink", "emit"):                   # E3
        assert re.search(rf"^\| \d+ \| {stage} \| \*\*BUILT\*\*", log,
                         re.M), f"E3 stage-table row for {stage}"
    assert "execute in isolation" in log, "E4"                     # E4
    assert re.search(r"part of the\s+same one-command rerun", log), \
        "E5"                                                       # E5
    m6 = re.search(r"^## 6\..*$", log, re.M)
    assert m6, "E6: no §6 history section"
    hist = log[m6.end():]
    assert "2026-08-25" in hist and \
        all(t in hist for t in ("W1", "W2", "W3", "W4")), "E6"     # E6


@pytest.mark.integration
def test_i4_entrypoint_surface_list_dryrun_vectors_forwarder():
    """I4 subprocess half (F12/AC10): --list shows six stages with 4–6 BUILT
    plus the RESOLVED CDB line; unknown flag -> usage exit 2; --dry-run
    datasets|relink|emit prints EVERY step's exact §3.1/§4.1/§5.1 vector
    (resolved python/buildid/CDB substituted) and changes no byte or mtime
    on any stage-write surface; run_all.sh --list behaves IDENTICALLY
    through the forwarder; the decompile stub still stands (E4)."""
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if ps is None:
        pytest.skip("no PowerShell on PATH")
    d = _log_defaults()

    def ra(*args):
        return subprocess.run(
            [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(RUN_ALL_PS1), *args],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=600)

    r = ra("--list")
    assert r.returncode == 0, r.stdout + r.stderr
    for stage in ("harvest", "map", "decompile", "datasets", "relink",
                  "emit"):
        assert stage in r.stdout, stage
    for stage in ("datasets", "relink", "emit"):
        assert not re.search(rf"{stage}.*NOT BUILT", r.stdout), stage
    assert f"CDB     = {d['CDB']}" in r.stdout
    # unknown flag -> usage exit 2
    assert ra("--definitely-not-a-flag").returncode == 2

    # dry-run: EXACT vectors, zero mutation
    before = _stage_product_snapshot()
    bid, cdb, py = d["BUILDID"], d["CDB"], d["PYTHON"]
    rel_draft = "--reldir extracted/relinks/_draft"
    vectors = {
        "datasets": (
            ["cdb_emit.py", cdb, "--outdir extracted/data/_draft",
             rel_draft, "--buildid", bid, "--wave wave1"],
            ["cdb_emit.py", cdb, "--outdir extracted/data/_draft",
             rel_draft, "--buildid", bid, "--wave wave2"],
            ["cdb_verify.py", cdb, "--datadir extracted/data/_draft",
             rel_draft, "--buildid", bid],
            ["promote_drafts.py", "--plane data",
             "--datadir extracted/data/_draft", rel_draft,
             "--out-data extracted/data", "--buildid", bid],
            ["cdb_verify.py", cdb, "--datadir extracted/data",
             "--reldir extracted/relinks/_draft", "--buildid", bid],
        ),
        "relink": (
            ["promote_drafts.py", "--plane relinks",
             "--datadir extracted/data/_draft", rel_draft,
             "--out-relinks extracted/relinks", "--buildid", bid],
            ["cdb_verify.py", cdb, "--datadir extracted/data",
             "--reldir extracted/relinks", "--buildid", bid],
            ["relink_catalog.py", "--datadir extracted/data",
             "--reldir extracted/relinks",
             "--bridge extracted/harvest/_lang-bridge/export_en.xml",
             "--out-md extracted/RELATIONS.md",
             "--out-json extracted/relinks/matrix.json"],
        ),
        "emit": (
            ["locale_bridge_dig.py"],
            ["validate_all.py", "--cdb", cdb, "--buildid", bid,
             "--datadir extracted/data", "--reldir extracted/relinks",
             "--report extracted/validation-report.json",
             "--md extracted/VALIDATION-REPORT.md"],
        ),
    }
    for stage, wants in vectors.items():
        rd = ra("--dry-run", stage)
        assert rd.returncode == 0, rd.stdout + rd.stderr
        lines = [ln for ln in rd.stdout.splitlines()
                 if ln.startswith("[dry-run]")]
        assert len(lines) == len(wants), (stage, lines)
        for ln, want in zip(lines, wants):
            assert ln.startswith(f"[dry-run] {stage}") and \
                "would run:" in ln, ln
            assert py in ln, ln                       # resolved PYTHON
            for tok in want:
                assert tok in ln, (stage, tok, ln)
    assert _stage_product_snapshot() == before, \
        "a --dry-run mutated a stage product"

    # forwarder parity: identical --list through run_all.sh
    sh = shutil.which("sh") or shutil.which("bash")
    if sh is None:
        pytest.skip("no sh on PATH — run_all.sh forwarder parity unrunnable "
                    "here (static identity pinned by the always-run case)")
    rs = subprocess.run([sh, str(PACK_ROOT / "run_all.sh"), "--list"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", timeout=600)
    assert rs.returncode == 0, rs.stdout + rs.stderr
    assert rs.stdout == r.stdout, "forwarder diverged from run_all.ps1"

    # isolation mode: the decompile stub stands, full walk still halts at it
    text = RUN_ALL_PS1.read_text(encoding="utf-8", errors="replace")
    assert "'decompile'" in text and "decompile-dig-1.mdx" in text


@pytest.mark.integration
def test_ac9_consumer_precondition_sandboxed_pack_exits_2_naming_owner(
        tmp_path):
    """AC9 third class (consumer-precondition), executable at the REAL
    entrypoint inside a SANDBOXED pack copy — zero shared-tree mutation: a
    managed canonical name removed or planted, the canonical pair count
    broken, or the relink seed set truncated makes the consumer stage ALONE
    exit 2 NAMING the owning producer (Invoke-Emit / Invoke-Relink
    preconditions)."""
    src_data = PACK_ROOT / "extracted" / "data"
    src_rel = PACK_ROOT / "extracted" / "relinks"
    relations = PACK_ROOT / "extracted" / "RELATIONS.md"
    seed_dir = src_rel / "_draft"
    _require(src_data / "item.jsonl", "canonical data plane (stage 4 ran)")
    _require(src_rel / "matrix.json", "canonical relink plane (stage 5 ran)")
    _require(relations, "RELATIONS.md (stage 5 ran)")
    _require(seed_dir / "class__skill.jsonl", "relink seed drafts")
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if ps is None:
        pytest.skip("no PowerShell on PATH")

    def sandbox(name):
        root = tmp_path / name
        root.mkdir()
        shutil.copy(RUN_ALL_PS1, root / "run_all.ps1")
        (root / "EXTRACTION-LOG.md").write_text(
            "<!-- RUN_ALL-DEFAULTS-BEGIN\n"
            "CLIENT: A:\\SteamLibrary\\steamapps\\common\\Wartales\n"
            f"BUILDID: {BUILDID}\n"
            "PAKS: res.pak\n"
            "OUT: extracted/harvest\n"
            "CDB: extracted/harvest/res/data.cdb\n"
            f"PYTHON: {sys.executable}\n"
            "RUN_ALL-DEFAULTS-END -->\n", encoding="utf-8")
        ex = root / "extracted"
        tools_dst = root / "pipeline" / "tools"
        shutil.copytree(TOOLS, tools_dst, ignore=shutil.ignore_patterns(
            "__pycache__"))
        exd = ex / "data"
        exd.mkdir(parents=True)
        for p in sorted(src_data.glob("*.jsonl")):
            shutil.copy(p, exd / p.name)          # exactly the 40 kinds
        shutil.copytree(src_rel, ex / "relinks")  # pairs + matrix + seeds
        shutil.copy(relations, ex / "RELATIONS.md")
        return root

    def run_stage(root, stage):
        return subprocess.run(
            [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(root / "run_all.ps1"), stage],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=900)

    # (a) deleted managed canonical kind -> emit exits 2 naming datasets
    root = sandbox("del-kind")
    (root / "extracted" / "data" / "trait.jsonl").unlink()
    r = run_stage(root, "emit")
    assert r.returncode == 2, (r.returncode, r.stdout[-500:], r.stderr[-300:])
    assert "trait" in r.stdout and "run_all.ps1 datasets" in r.stdout

    # (b) planted ghost canonical name -> emit exits 2 naming datasets
    root = sandbox("ghost-kind")
    (root / "extracted" / "data" / "place.jsonl").write_text(
        '{"_meta":{"kind":"place"}}\n', encoding="utf-8")
    r = run_stage(root, "emit")
    assert r.returncode == 2, (r.returncode, r.stdout[-500:], r.stderr[-300:])
    assert "place" in r.stdout and "run_all.ps1 datasets" in r.stdout

    # (c) broken canonical pair count -> emit exits 2 naming relink
    root = sandbox("pair-count")
    (root / "extracted" / "relinks" / "class__skill.jsonl").unlink()
    r = run_stage(root, "emit")
    assert r.returncode == 2, (r.returncode, r.stdout[-500:], r.stderr[-300:])
    assert "run_all.ps1 relink" in r.stdout

    # (d) truncated relink SEED set -> relink exits 2 naming datasets
    root = sandbox("seed-count")
    (root / "extracted" / "relinks" / "_draft" /
     "item__itemType.jsonl").unlink()
    r = run_stage(root, "relink")
    assert r.returncode == 2, (r.returncode, r.stdout[-500:], r.stderr[-300:])
    assert "run_all.ps1 datasets" in r.stdout
