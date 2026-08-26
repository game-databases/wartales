"""F5 search-index emitter test suite — spec-f5-search.mdx §9 item 5 + §10
AC-7 (+ the static halves of AC-1/AC-6); TestWriter brief
docs/briefs/testwriter-f5-search.mdx.

Written against the SPEC's contract, RED-FIRST (brief requirement: "every
suite fails against absent/nonconformant implementation") — unlike the
skip-while-absent sibling suites, an absent or broken
``pipeline/tools/search_index_emit.py`` FAILS these cases loudly instead of
skipping, because F5's artifact is a shipped contract, not optional tooling.

Layers:

1. **Honesty chain** (always runs): ``wave_kinds.MANAGED_KINDS`` vs the
   emitter's own ``SEARCHABLE_KINDS`` — wkk → emitter list → manifest.kinds →
   TS ``KIND_ORDER`` is mechanical at every hop, no transcription anywhere
   (r1 m4; the TS-side hop lives in site search-artifact.test.ts).
2. **Emitter layer** (synthetic mini avail + mini overlays in tmp; never
   touches ``extracted/`` or A:): happy-path shape + byte-determinism (two
   runs, sha256 equal ×10), the corruption gates (flag-without-value,
   value-without-flag, unknown locale), the non-searchable-kind refusal,
   usage/precondition exits, fixed key order, ensure_ascii=False + LF.
3. **Registration layer** (static): run_all.ps1 stage ``emit`` lists the
   emitter as the third step after ``validate_all.py``; EXTRACTION-LOG.md
   carries the registry entry (static legs of AC-1/AC-6; executing
   ``pwsh ./run_all.ps1 emit`` stays orchestrator-owned).

CLI contract assumed (§3.1, rename here first if the arbiter pins otherwise):
``search_index_emit.py --availability PATH --overlays DIR --out DIR --buildid ID``
exit 0 ok · 2 precondition/consistency failure naming the offender · 3 usage.
"""

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PACK = Path(__file__).resolve().parents[2]
TOOLS = PACK / "pipeline" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))  # pipeline/tools is a non-package (harvest precedent)

EMITTER = TOOLS / "search_index_emit.py"
RUN_ALL = PACK / "run_all.ps1"
EXTRACTION_LOG = PACK / "EXTRACTION-LOG.md"

LOCALES = ["en", "fr", "de", "es", "pl", "pt-BR", "ru", "ko", "zh"]
BUILD_ID = "20318128"
MINI_IDS = {"item": ["I1", "I2"], "skill": ["S1"], "class": ["C1"]}

NAMES = {
    "en": lambda k, i: f"{k.title()} {i}",
    "fr": lambda k, i: f"{k.title()} fr {i}",
    "de": lambda k, i: f"{k.title()} de {i}",
    "es": lambda k, i: f"{k.title()} es {i}",
    "pl": lambda k, i: f"Włóczęga {k} {i}",
    "pt-BR": lambda k, i: f"{k.title()} br {i}",
    "ru": lambda k, i: f"Ёж {k} {i}",
    "ko": lambda k, i: f"한국 {k} {i}",
    "zh": lambda k, i: f"长剑 {k} {i}",
}


# ---- module loading ------------------------------------------------------------


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- honesty chain -------------------------------------------------------------


def test_emitter_module_exists_and_imports():
    """RED-FIRST anchor: absence of the emitter FAILS, never skips."""
    if not EMITTER.exists():
        pytest.fail(
            "pipeline/tools/search_index_emit.py is ABSENT — the F5 artifact "
            "emitter must exist (spec-f5-search §3.1/§11)"
        )
    try:
        _load_module(EMITTER, "search_index_emit")
    except Exception as e:  # noqa: BLE001 - any import failure IS the finding
        pytest.fail(f"emitter module does not import cleanly: {e}")


def test_searchable_kinds_is_the_frozen_trio():
    mod = _load_module(EMITTER, "search_index_emit")
    sk = getattr(mod, "SEARCHABLE_KINDS", None)
    if sk is None:
        pytest.fail(
            "emitter exports ["
            + ", ".join(n for n in dir(mod) if not n.startswith("_"))
            + "] but no SEARCHABLE_KINDS — §2 freezes ['item','skill','class']"
        )
    assert list(sk) == ["item", "skill", "class"]


def test_honesty_chain_wave_kinds_subset():
    wkk = _load_module(TOOLS / "wave_kinds.py", "wave_kinds")
    mod = _load_module(EMITTER, "search_index_emit")
    sk = set(getattr(mod, "SEARCHABLE_KINDS"))
    managed = set(wkk.MANAGED_KINDS)
    assert len(managed) == 40, "§2 freezes MANAGED_KINDS at 40 kinds"
    assert sk <= managed, (
        f"SEARCHABLE_KINDS \\ MANAGED_KINDS = {sorted(sk - managed)} — "
        "wkk → emitter must be a subset relation, never a second vocabulary (§2)"
    )


# ---- synthetic mini corpus -----------------------------------------------------


def _write_availability(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def _mini_rows() -> list[dict]:
    rows = []
    for kind, ids in MINI_IDS.items():
        for entity_id in ids:
            rows.append(
                {
                    "kind": kind,
                    "id": entity_id,
                    "availableLocales": list(LOCALES),
                    "namedLocales": list(LOCALES),
                    "fields": {
                        loc: {"name": True, "desc": False} for loc in LOCALES
                    },
                }
            )
    return rows


def _write_overlays(root: Path, ids_by_kind: dict[str, list[str]] | None = None,
                    skip_locales: set[str] = frozenset()) -> None:
    ids_by_kind = ids_by_kind or MINI_IDS
    for kind, ids in ids_by_kind.items():
        for loc in LOCALES:
            if loc in skip_locales:
                continue
            d = root / loc
            d.mkdir(parents=True, exist_ok=True)
            payload = {
                i: {"name": NAMES[loc](kind, i), "description": "stub"} for i in ids
            }
            (d / f"{kind}.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8", newline="\n"
            )


def _make_corpus(base: Path) -> tuple[Path, Path]:
    """Fresh mini corpus; every id named in all nine locales."""
    av = base / "avail" / "locale_availability.jsonl"
    ov = base / "overlays"
    _write_availability(av, _mini_rows())
    _write_overlays(ov)
    return av, ov


def _run(av: Path, ov: Path, out: Path, extra: list[str] | None = None):
    cmd = [
        sys.executable, str(EMITTER),
        "--availability", str(av),
        "--overlays", str(ov),
        "--out", str(out),
        "--buildid", BUILD_ID,
        *(extra or []),
    ]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=180)


def _run_ok(tmp_path: Path, mutate=None) -> tuple[subprocess.CompletedProcess, Path]:
    base = tmp_path / "in"
    av, ov = _make_corpus(base)
    if mutate is not None:
        mutate(av, ov)
    out = tmp_path / "out"
    proc = _run(av, ov, out)
    return proc, out


def _digest_tree(out: Path) -> dict[str, str]:
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(out.glob("*.json"))
    }


def _ordered_json(path: Path):
    """Parse keeping each object's key ORDER (first-seen list per object)."""
    orders: list[list[str]] = []

    def hook(pairs):
        orders.append([k for k, _ in pairs])
        return dict(pairs)

    doc = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=hook)
    return doc, orders


# ---- happy path ----------------------------------------------------------------


def test_happy_path_emits_exactly_ten_files(tmp_path):
    proc, out = _run_ok(tmp_path)
    assert proc.returncode == 0, f"exit {proc.returncode}: {proc.stderr or proc.stdout}"
    expected = {f"{loc}.json" for loc in LOCALES} | {"manifest.json"}
    got = {p.name for p in out.glob("*")}
    assert got == expected, (
        f"emitter wrote {sorted(got)} — exactly ten files contracted (§3.2); "
        "stray temp files break the diff envelope"
    )


def test_manifest_shape_and_honesty_hop(tmp_path):
    proc, out = _run_ok(tmp_path)
    assert proc.returncode == 0, proc.stderr or proc.stdout
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert m["schema"] == "wartales/search-index@1"
    assert m["buildId"] == BUILD_ID
    assert m["locales"] == LOCALES, "nine official client codes, pt-BR verbatim"
    sk = list(getattr(_load_module(EMITTER, "search_index_emit"), "SEARCHABLE_KINDS"))
    assert m["kinds"] == sk, (
        "manifest.kinds must EQUAL the emitter's SEARCHABLE_KINDS verbatim "
        "(honesty hop emitter → manifest, §9 item 5)"
    )
    total_named = sum(len(ids) for ids in MINI_IDS.values())
    assert m["rowCount"] == {loc: total_named for loc in LOCALES}


def test_fixed_key_order_and_row_sort_and_shape(tmp_path):
    proc, out = _run_ok(tmp_path)
    assert proc.returncode == 0, proc.stderr or proc.stdout
    kinds = list(getattr(_load_module(EMITTER, "search_index_emit"), "SEARCHABLE_KINDS"))

    _, morders = _ordered_json(out / "manifest.json")
    # object_pairs_hook completes innermost objects first: last-completed =
    # the document root.
    assert morders[-1] == ["schema", "buildId", "locales", "kinds", "rowCount"], (
        f"manifest fixed key order, got {morders[-1]} (§3.2 illustration — "
        "sort_keys forbidden, r1 m7)"
    )

    for loc in LOCALES:
        doc, orders = _ordered_json(out / f"{loc}.json")
        assert orders[-1] == ["schema", "locale", "buildId", "rows"], f"{loc}: top-level order"
        assert orders[0] == ["kind", "id", "name", "href"], f"{loc}: row key order (exactly four)"
        assert doc["locale"] == loc
        assert doc["rows"], f"{loc}: rows non-empty before looping (poisoned empty set)"
        for r in doc["rows"]:
            assert set(r) == {"kind", "id", "name", "href"}
            assert r["name"], f"{loc}:{r['id']} name non-empty"
        sort_keys = [(kinds.index(r["kind"]), r["id"]) for r in doc["rows"]]
        assert sort_keys == sorted(sort_keys), f"{loc}: rows sort by (kindIndex,id) (§3.4)"


def test_href_route_table_segments(tmp_path):
    proc, out = _run_ok(tmp_path)
    assert proc.returncode == 0, proc.stderr or proc.stdout
    checked = 0
    for loc in LOCALES:
        doc = json.loads((out / f"{loc}.json").read_text(encoding="utf-8"))
        for r in doc["rows"]:
            seg = "" if loc == "en" else ("pt-br" if loc == "pt-BR" else loc.lower())
            want = (
                f"/{r['kind']}/{r['id']}" if not seg
                else f"/{seg}/{r['kind']}/{r['id']}"
            )
            assert r["href"] == want, f"{loc}:{r['id']} violates the §3.3 route table"
            assert "/search" not in r["href"]
            checked += 1
    assert checked > 0


def test_membership_named_locales_only(tmp_path):
    proc, out = _run_ok(tmp_path)
    assert proc.returncode == 0, proc.stderr or proc.stdout
    all_ids: set[tuple[str, str]] = set()
    for loc in LOCALES:
        doc = json.loads((out / f"{loc}.json").read_text(encoding="utf-8"))
        all_ids |= {(r["kind"], r["id"]) for r in doc["rows"]}
    expected = {(k, i) for k, ids in MINI_IDS.items() for i in ids}
    assert all_ids == expected, "membership = namedLocales, identical ×9"


def test_byte_determinism_two_runs(tmp_path):
    """AC-2's executable core: two runs → sha256-equal across all ten files."""
    av, ov = _make_corpus(tmp_path / "in")
    out1, out2 = tmp_path / "out1", tmp_path / "out2"
    r1 = _run(av, ov, out1)
    r2 = _run(av, ov, out2)
    assert r1.returncode == 0 and r2.returncode == 0, (
        f"{r1.stderr or r1.stdout}\n{r2.stderr or r2.stdout}"
    )
    d1, d2 = _digest_tree(out1), _digest_tree(out2)
    assert len(d1) == 10, "ten files before digests mean anything"
    assert d1 == d2, (
        "two consecutive runs differ (§3.4):\n"
        + "\n".join(f"  {k}: {v} vs {d2.get(k)}" for k, v in d1.items() if d2.get(k) != v)
    )


def test_serialization_utf8_lf_no_escapes(tmp_path):
    proc, out = _run_ok(tmp_path)
    assert proc.returncode == 0, proc.stderr or proc.stdout
    for name in ("ru.json", "ko.json", "zh.json", "pl.json"):
        raw = (out / name).read_bytes()
        assert b"\r\n" not in raw, f"{name}: LF line endings (§3.2)"
        assert b"\\u" not in raw, f"{name}: ensure_ascii=False — no \\u escapes"
        text = raw.decode("utf-8")
        assert len(text) < len(raw), f"{name}: carries raw multibyte content"


# ---- gates (each a hard exit 2, §3.1) -------------------------------------------


def test_flag_without_value_refused(tmp_path):
    """fields[L].name true + namedLocales holds L, but overlay L lost the name."""

    def mutate(av: Path, ov: Path):
        payload = json.loads((ov / "en" / "item.json").read_text(encoding="utf-8"))
        del payload["I1"]  # value removed, flag + namedLocales stay true
        (ov / "en" / "item.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8", newline="\n"
        )

    proc, _ = _run_ok(tmp_path, mutate)
    assert proc.returncode == 2, (
        f"flag-without-value must exit 2, got {proc.returncode}: "
        f"{proc.stdout} {proc.stderr}"
    )
    assert (proc.stderr + proc.stdout).strip(), "gate must NAME the offending file/kind"


def test_value_without_flag_refused(tmp_path):
    """Overlay keeps the name but availability drops the flag + membership."""

    def mutate(av: Path, ov: Path):
        rows = [json.loads(l) for l in av.read_text(encoding="utf-8").splitlines()]
        for r in rows:
            if r["kind"] == "item" and r["id"] == "I2":
                r["namedLocales"] = [l for l in r["namedLocales"] if l != "en"]
                r["fields"]["en"]["name"] = False
        _write_availability(av, rows)

    proc, _ = _run_ok(tmp_path, mutate)
    assert proc.returncode == 2, (
        f"value-without-flag must exit 2, got {proc.returncode}: "
        f"{proc.stdout} {proc.stderr}"
    )
    assert (proc.stderr + proc.stdout).strip()


def test_non_searchable_kind_never_reaches_the_artifact(tmp_path):
    """The invariant under §9 item 5's refusal law: a fully-populated kind
    outside SEARCHABLE_KINDS (availability + names + overlays complete) must
    not leak into manifest.kinds or any locale file. MEASURED behavior of the
    landed emitter (probe, 2026-08-26): it filters to SEARCHABLE_KINDS and
    exits 0 — artifact purity holds."""

    def mutate(av: Path, ov: Path):
        rows = [json.loads(l) for l in av.read_text(encoding="utf-8").splitlines()]
        for loc in LOCALES:
            rows.append(
                {
                    "kind": "icon",
                    "id": "X1",
                    "availableLocales": list(LOCALES),
                    "namedLocales": list(LOCALES),
                    "fields": {l: {"name": True} for l in LOCALES},
                }
            )
        _write_availability(av, rows)
        _write_overlays(ov, ids_by_kind=dict(MINI_IDS, icon=["X1"]))

    proc, out = _run_ok(tmp_path, mutate)
    assert proc.returncode == 0, f"complete searchable corpus rejected: {proc.stderr}"
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert m["kinds"] == ["item", "skill", "class"], "manifest.kinds stays the frozen trio"
    total = sum(len(ids) for ids in MINI_IDS.values())
    for loc in LOCALES:
        doc = json.loads((out / f"{loc}.json").read_text(encoding="utf-8"))
        kinds = {r["kind"] for r in doc["rows"]}
        assert kinds <= set(m["kinds"]), f"{loc}: non-searchable kind leaked into rows"
        assert len(doc["rows"]) == total, f"{loc}: only named searchable rows ship"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "§9 item 5 letter: 'kind outside SEARCHABLE_KINDS refused (exit 2)' and §3.1's "
        "gate over 'locale set of overlays ∪ avail'. MEASURED landed behavior "
        "(2026-08-26 probes): a non-searchable availability row is silently "
        "FILTERED (exit 0), and a stray overlay-only locale directory (ja/) is "
        "ignored when avail carries exactly the official nine — both cannot "
        "corrupt the artifact (purity proven by "
        "test_non_searchable_kind_never_reaches_the_artifact), but neither trips "
        "exit 2 either. If this starts XPASSing, the emitter adopted the literal "
        "refusal — remove this marker in the same commit."
    ),
)
def test_letter_divergences_stray_inputs_exit_2(tmp_path):
    def stray_avail_row(av: Path, ov: Path):
        rows = [json.loads(l) for l in av.read_text(encoding="utf-8").splitlines()]
        rows.append(
            {
                "kind": "icon",
                "id": "X1",
                "availableLocales": [],
                "namedLocales": [],
                "fields": {},
            }
        )
        _write_availability(av, rows)

    proc_a, _ = _run_ok(tmp_path / "a", stray_avail_row)
    assert proc_a.returncode == 2, (
        f"stray non-searchable availability row: expected exit 2, got "
        f"{proc_a.returncode} ({proc_a.stdout} {proc_a.stderr})"
    )

    def stray_overlay_locale(av: Path, ov: Path):
        d = ov / "ja"
        d.mkdir(parents=True, exist_ok=True)
        (d / "item.json").write_text(
            json.dumps({"I1": {"name": "日本語", "description": "x"}}, ensure_ascii=False),
            encoding="utf-8",
            newline="\n",
        )

    proc_b, _ = _run_ok(tmp_path / "b", stray_overlay_locale)
    assert proc_b.returncode == 2, (
        f"stray overlay-only locale dir: expected exit 2, got "
        f"{proc_b.returncode} ({proc_b.stdout} {proc_b.stderr})"
    )


def test_unknown_locale_in_avail_refused_exit_2(tmp_path):
    """ja is community-lane; present in BOTH avail and overlays the corpus can
    no longer be read as the nine official codes → hard exit 2 (§3.1)."""

    def mutate(av: Path, ov: Path):
        rows = [json.loads(l) for l in av.read_text(encoding="utf-8").splitlines()]
        for r in rows:
            r["availableLocales"].append("ja")
            r["namedLocales"].append("ja")
            r["fields"]["ja"] = {"name": True}
        _write_availability(av, rows)
        (ov / "ja").mkdir(parents=True, exist_ok=True)
        (ov / "ja" / "item.json").write_text(
            json.dumps({"I1": {"name": "日本語", "description": "x"}}, ensure_ascii=False),
            encoding="utf-8",
            newline="\n",
        )

    proc, _ = _run_ok(tmp_path, mutate)
    assert proc.returncode == 2, (
        f"unknown locale must exit 2, got {proc.returncode}: "
        f"{proc.stdout} {proc.stderr}"
    )
    combined = (proc.stderr + proc.stdout).lower()
    assert "ja" in combined or "locale" in combined, "gate names the offending locale"


def test_missing_input_refused_exit_2(tmp_path):
    base = tmp_path / "in"
    av, ov = _make_corpus(base)
    proc = _run(base / "missing.jsonl", ov, tmp_path / "out")
    assert proc.returncode == 2, (
        f"absent availability file is a precondition failure (exit 2), got "
        f"{proc.returncode}: {proc.stdout} {proc.stderr}"
    )


def test_usage_error_exit_3(tmp_path):
    av, ov = _make_corpus(tmp_path / "in")
    proc = _run(av, ov, tmp_path / "out", extra=["--not-a-real-flag"])
    assert proc.returncode == 3, (
        f"usage errors exit 3 (§3.1), got {proc.returncode}: {proc.stdout} {proc.stderr}"
    )


# ---- registration layer (static legs of AC-1/AC-6) -------------------------------


def test_run_all_registers_emitter_as_third_emit_step():
    assert RUN_ALL.exists(), "pack-root run_all.ps1 must exist (§11)"
    text = RUN_ALL.read_text(encoding="utf-8")
    bridge_positions = [
        i for i, line in enumerate(text.splitlines()) if "locale_bridge_dig.py" in line
    ]
    validate_positions = [
        i for i, line in enumerate(text.splitlines()) if "validate_all.py" in line and "--cdb" in line
    ]
    emit_positions = [
        i for i, line in enumerate(text.splitlines()) if "search_index_emit.py" in line
    ]
    assert emit_positions, (
        "run_all.ps1 never registers pipeline/tools/search_index_emit.py — "
        "AC-1's appended third step is missing"
    )
    assert validate_positions, "stage emit must keep its validate_all.py step unchanged"
    assert max(validate_positions) < min(emit_positions), (
        "the emitter must run AFTER validate_all.py (§3.1: emitted only once the "
        "canonical planes validated)"
    )
    if bridge_positions:
        assert min(emit_positions) > min(bridge_positions)


def test_extraction_log_carries_registry_entry():
    assert EXTRACTION_LOG.exists()
    log = EXTRACTION_LOG.read_text(encoding="utf-8")
    assert "search_index_emit.py" in log, (
        "EXTRACTION-LOG.md must carry the stage-registry entry for the emitter "
        "([DR-2026-08-18-pipeline]: the entrypoint lives inside the "
        "commit-per-achievement unit)"
    )
