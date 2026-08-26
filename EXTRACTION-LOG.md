# Wartales — EXTRACTION-LOG

Pin file for extraction reproducibility (extraction-doctrine.md Principle
two: tool + version + client buildid, so any result can be reproduced after
a game patch) and the **defaults source read by the pack entrypoint**
(`run_all.ps1` / `run_all.sh`, [DR-2026-08-18-pipeline]). Doctrine: a fresh
clone + fresh game copy + the entrypoint must reproduce the full
`extracted/` output A→Z with no second document.

Exploration work is journaled in
[docs/data-dig-log.mdx](docs/data-dig-log.mdx) (append-only dig log); this
file records the standing pins, stage statuses, and stage runs. A tooling
change or game patch updates this log and the entrypoint in the same commit
(AGENTS.md rule 5).

<!-- RUN_ALL-DEFAULTS-BEGIN
CLIENT: A:\SteamLibrary\steamapps\common\Wartales
BUILDID: 20318128
PAKS: assets.pak content.pak map.pak res.pak
OUT: extracted/harvest
CDB: extracted/harvest/res/data.cdb
PYTHON: C:\Python314\python.exe
RUN_ALL-DEFAULTS-END -->

The block above is machine-readable and parsed by `run_all.ps1`
(keys CLIENT, BUILDID, PAKS, OUT, CDB, PYTHON — keep verbatim, ASCII only).
`CDB` names the CastleDB brain consumed by stages 4–6 — the HARVEST OUTPUT
`extracted/harvest/res/data.cdb`, never the scratch dig-era copy under
`pipeline/tools/_verify/` (spec-stages-datasets §1 input-source rule).
Override at invocation: `run_all.ps1 <stage-or-client-path>`,
`--client <path>`, `--dry-run`, `--list`.

---

## 1. Client + environment pins

| Pin | Value | Measured |
|---|---|---|
| Host | NE8K Windows 11 Pro (10.0.22631) — the data host; extraction never copies paks off it | extraction-host.md |
| Client root | `A:\SteamLibrary\steamapps\common\Wartales` (Steam appid 1527950, Heaps/HashLink engine) | 2026-08-25 |
| **Client buildid** | **20318128** — `"buildid"` in `steamapps/appmanifest_1527950.acf`; queued TargetBuildID **21238928** may swap the install mid-work | re-measured 2026-08-25 |
| PAK container version byte | **0** on all four paks (read live 2026-08-24; recorded per spec-harvest §9.4 backfill plan; harvest stamps it into each `X.summary.json`) | 2026-08-24 |
| Python | `C:\Python314\python.exe` — CPython **3.14.7**, stdlib only for every pipeline tool | 2026-08-25 |

Client container fingerprints at the pinned buildid (harvest re-measures
size+mtime into each `X.summary.json` every run; a mismatch is patch drift —
see §4):

| Pak | Bytes | mtime |
|---|---:|---|
| assets.pak | 9,217,464,877 | 2025-10-12 23:34:51 +03:00 |
| content.pak | 7,366,857,765 | 2025-10-12 23:34:51 +03:00 |
| map.pak | 27,889,015,798 | 2025-10-12 23:34:51 +03:00 |
| res.pak | 767,099,483 | 2025-10-12 23:34:51 +03:00 |

(map.pak size confirms the corrected expectation in
[docs/spec-harvest.mdx §2.3](docs/spec-harvest.mdx); total payload ≈42.1 GiB
across 40,201 files.)

## 2. Tool provenance

| Tool | Status | Provenance | Pin |
|---|---|---|---|
| `pipeline/harvest.py` | tracked | built from [docs/spec-harvest.mdx](docs/spec-harvest.mdx); round-1 arbiter fixes applied; unit suite 35 pass / 0 fail / 3 skipped; review chain in `docs/review-harvest-*r2.mdx` | commit `8030454013a090d5c226551b6c87e6ddea089a3e` ("wartales: harvest.py round-1 fixes") |
| `pipeline/tools/wtpak.py` | local-only¹ | self-authored clean-room PAK reader (`Reader` class — single source of tree-parse truth; spec.md legal.tooling). Validated end-to-end: zero-slack parse of all four paks, 0 mismatches vs the 40,201-row recon TSVs ([toolchain-validation §1](docs/toolchain-validation.mdx)) | sha256 `e58e2ddcfddec118d4ca16a3d2818ae2c9db28c0e8ede43244b8e7d802b65252` (6,016 B) |
| `pipeline/tools/hlboot_probe.py` | local-only¹ | HashLink bytecode walker written from canonical reader semantics (`pipeline/tools/_refs/hl_code.c`); `--emit` produced `extracted/logic/hl-structure/` (52,114 functions, 46,891 types, 75,321 strings) with a zero-slack round-trip proof + two-implementation cross-check ([decompile-dig-1](docs/decompile-dig-1.mdx)) | sha256 `62ecc204bae5ca2007758986cddb561ae88002acc29c8fb0cb290a954219a179` (34,455 B) |
| `pipeline/tools/cdb_emit.py` | local-only¹ | CastleDB dataset + relink-seed emitter (digs 1–3; waves 1–2; preserves undeclared row keys); r1: `--buildid` flag (spec §3.6, default keeps recorded outputs valid) | sha256 `3013abd228eb1d20381006e6efa52d2b869f147fc8a4971dca6a6ab2fd2f591b` (13,823 B) |
| `pipeline/tools/cdb_verify.py` | local-only¹ | independent dataset verifier sharing no code with the emitter; r1: `--buildid` flag + managed-universe/pair-name scan scope with skip enumeration (spec §3.6/§10 hole 1); r2: dangling>0 is a fail() gate (§3.3/§4.4) and pair files require `_meta.buildId` == `--buildid` (arbiter W2/F6-tool/R5) | sha256 `cc9c5b6e698fa46aca379d3dcd4b307d4b21ffe30ec197def3ff48f501ef9bfa` (18,329 B) |
| `pipeline/tools/wave_kinds.py` | local-only¹ | neutral managed-universe module: the 40 kind↔sheet pairs of waves 1+2 as membership metadata only (spec §3.4 rule 1); also carries the frozen §3.5 deferred list + `EXPECTED_PAIR_FILES = 51` | sha256 `e96a95c31c3936d72fdccd98a737ba2271ff91304b7dde1c3a7551d6374d61e3` (5,329 B) |
| `pipeline/tools/promote_drafts.py` | local-only¹ | stage-4/5 promotion: verifier-proven `_draft` corpora → canonical planes; equality exempts only `_meta.emitted`; atomic `.part`+`os.replace`; stale-tripwire exit 1 / precondition exit 2; ignore-and-enumerate ledger (spec §3.4); r2: payload equality byte-exact (CRLF/final-LF drift = update), argparse usage errors exit 2, draft-set-universe completeness precondition exit 2 before any write, ledger names `poi_tile_coords.jsonl` (D11) / `battle_scene.jsonl` (D12) and enumerates subdirectories (arbiter W3/R2–R4/R9) | sha256 `f3516e1f27c2407685b1716ea6abca2c7b4a83373585f63b67ce4457363416d5` (11,885 B) |
| `pipeline/tools/relink_catalog.py` | local-only¹ | stage 5 catalog generator: derives `RELATIONS.md` + `relinks/matrix.json` from canonical bytes only — no wall-clock stamp, byte-stable reruns (arbiter F9); carries the Dig-7 adjudication freeze (env__place 61 / frescos__place 9 / fiefGoal__element 2) beside the regeneration-honest null flags (spec §4.2/§4.4); r2: a zero-edge pair file never renders `modeled` — §4.3's ≥1-edge rule enforced, evidence-less directions fall through the ladder with their unblock (arbiter W4/R11) | sha256 `f795286debda25b5f6d770d1d05d1e2963063b29af0e98ee94e768c8078f08c8` (19,328 B) |
| `pipeline/tools/validate_all.py` | local-only¹ | stage-6 validator: invokes `cdb_verify.py` + `locale_bridge_dig.py` as children (one independent truth each), lands `validation-report.json` + `VALIDATION-REPORT.md`, reconciles to census 11,473; keeps its `generated` deliberately (spec §5.2/§10 hole 3); r2: census loops filtered to the managed universe so non-managed intruders become `hbson-independent` report records instead of a KeyError crash, that check now walks both canonical planes recursively pruning `_draft`, `deferred-present` compares an inline frozen §3.5 transcription, `catalog-parity` parse-and-compares every rendered RELATIONS.md cell against the matrix records, availability locale sets enforce the measured bimodal law {∅, exact-9}, wave-1-draft precondition anchored to PACK_ROOT (arbiter W1/R1/R6/R7/F3/F4/finding A) | sha256 `c3224362e3c8cb05accfae7cd1c501464a658b6cd5c86b30bdbc2ccfb5dcf5a3` (28,228 B) |
| `pipeline/tools/fit_world_transform.py` | local-only¹ | D6/D11 transform battery: carrier reads (layers2D + heightmap nodes via hbson_decode), validation gates, emits the `coordinate-transform.json` the registry cites | sha256 `1dc9ebf12251439bd751fdd72809613e3551fe2dea43742a011b5bb78e492ef0` (43,638 B) |
| `pipeline/tools/emit_tile_coords.py` | local-only¹ | tile-space join of poi_coordinates.jsonl → `poi_tile_coords.jsonl` (Dig 11 deliverable; stdlib only) | sha256 `d05d356e07a1cfc10483649f06e66a22b37b8467a4858355b135188bae8454d0` (6,490 B) |

¹ The repo-root `.gitignore` `tools/` rule (meant for the Windows toolchain
dirs) also swallows pack-local `pipeline/tools/`, so these validated tools
exist only on NE8K until negation lines land (the `!anvil-empire/tools/`
precedent). Until then, a truly fresh clone needs them restored by hash from
an existing checkout — recorded here rather than papered over.

## 3. Stage table

Fixed order; run all stages with no arguments, or one stage by name. Only
BUILT stages execute; NOT BUILT stages fail loudly (exit 3) naming their
unblock pointer.

| # | Stage | Status | Produces | Notes |
|---|---|---|---|---|
| 1 | harvest | **BUILT** | `extracted/harvest/<pak>/…` payloads + `<pak>.manifest.jsonl` + `<pak>.summary.json` | idempotent + resumable (every entry adler-reverified each run; matched entries skipped); `--dry-run` prints the exact command line |
| 2 | map | **BUILT** | `extracted/data/maps.json` + `contracts/maps.schema.json` (schema-validated) | `pipeline/map_tiles.py registry`; cites only this-run measurements, so `rawproof`+`pyramid-ratio` artifacts must exist — full imagery pass is `python pipeline/map_tiles.py run` |
| 3 | decompile | NOT BUILT | `extracted/decompiled/…` | stub → [docs/decompile-dig-1.mdx](docs/decompile-dig-1.mdx): structure layer done (`extracted/logic/hl-structure/`), operand-level disassembler + decompiler is the next build |
| 4 | datasets | **BUILT** | `extracted/data/<kind>.jsonl` (40 managed kinds) | waves 1+2 regenerated into `_draft` by `cdb_emit.py`, `cdb_verify.py` GATE, `promote_drafts.py --plane data`, canonical re-verify ([spec-stages-datasets §3](docs/spec-stages-datasets.mdx)) |
| 5 | relink | **BUILT** | `extracted/relinks/<from>__<to>.jsonl` (51 pair files) + `RELATIONS.md` + `relinks/matrix.json` | promote the seed pairs, canonical verify over BOTH planes, catalog derived from canonical bytes ([spec-stages-datasets §4](docs/spec-stages-datasets.mdx)) |
| 6 | emit | **BUILT** | `relinks/locale_availability.jsonl` + overlays (regen) + `validation-report.json` + `VALIDATION-REPORT.md` | validation only — availability regen (`locale_bridge_dig.py`) + `validate_all.py` reconciling everything to census 11,473 ([spec-stages-datasets §5](docs/spec-stages-datasets.mdx)) |

A full no-arguments run currently walks harvest → PASS, map → PASS, then
fails loudly at decompile (exit 3) — correct while the decompiler is unbuilt.
Stages 4–6 execute in isolation (`run_all.ps1 datasets` / `relink` / `emit`)
and join the walk once decompile lands (spec-stages-datasets hole 4).

## 4. Re-run after a game patch (one command)

```sh
powershell -NoProfile -ExecutionPolicy Bypass -File run_all.ps1 --client <path-to-game-files>
```

Harvest verifies + resumes automatically; new/changed entries re-extract.
Then, in the same commit as any tooling change or pin update: refresh
BUILDID + the §1 fingerprint table above (or let a harvest run's
`X.summary.json` measured sizes/mtimes drive the update). Single stages:
`run_all.ps1 harvest`, `run_all.ps1 decompile`, …; rehearsal without writes:
add `--dry-run`. Stages 4–6 (`datasets`, `relink`, `emit`) are part of the
same one-command rerun — both CDB tools take `--buildid`, so a patch rerun
stamps and requires the NEW id; census/relink expectations re-freeze per the
§5 procedure on a new buildid.

## 5. Map imagery pipeline — gate freezes + patch re-pin procedure (2026-08-25)

Recorded BEFORE any of these gates gated a verdict (AC4 discipline:
thresholds frozen from the measured distribution, never invented, never
negotiated after seeing results; arbiter round 1 C3). The suite asserts the
module constants equal these values
(`pipeline/tests/test_map_tiles.py::test_frozen_gates_match_the_module_and_the_freeze_record`).

### D2 — water-height plateau definition + gate

`PLATEAU_FRACTION_GATE = 0.5`. "Plateau" is FROZEN as: a fraction ≥ ½ of one
tile's pixels within ±0.01 of the pin (`region@props@waterHeight` =
−0.4, Belerion_1). Below that, near-pin pixels are shoreline transition —
terrain crossing the pin elevation along the land↔sea-floor gradient — not a
sea level. Measured at buildid 20318128: worst-tile fraction 0.071899…,
ocean-cell mean −4.82 (range −5.92..21.34) ⇒ the −0.4 global sea-level pin is
REFUTED by computation against this gate (`rawproof.json.verdict` is computed
from the metric, never concatenated prose), and the ≤7.19 % worst-tile tail is
the shoreline-band explanation above.

### D7 — `_s` pyramid divergence gate

`PYRAMID_CORR_GATE = 0.99`, justified from the measured distribution before it
gated: box-mean downsampling of smooth float32 terrain reproduces its own `_s`
tile at corr ≥ 0.99 for every ordinary cell (measured mean 0.99935 over all
1,377 co-present cells; min non-origin cell well above the gate). The gate
therefore isolates exactly the one measured exception — `height_x0_y0`
(own-layout corr 0.4496, the 1024×1024 double-resolution LOD) — with a wide
margin, instead of an invented round number.

### AC1 Δ=0 re-pin step (future buildids)

All committed numeric expectations are pinned to buildid **20318128**. After a
game patch lands, Δ=0 is re-established by this DOCUMENTED re-pin procedure —
one commit, never a hand-edit of a single constant:

1. Re-run `python pipeline/map_tiles.py classify --tsv output/_recon-scratch/map-pak-entries.tsv`
   against a freshly regenerated recon TSV; it fails loud naming each drifted
   expectation.
2. Re-freeze from the NEW dig artifacts in one commit: `EXPECTED_TOTALS`,
   `EXPECTED_TOTAL_BYTES`, `BBOX`, `DUP_EXPECTED`/fixture duplicate constants,
   `HEIGHT_OUTLIER_*`, `FORMAT_TRIPLES`/`DDS_TRIPLES`, golden file + decoded
   checksums, and `BUILDID` in both `map_tiles.py` and `test_map_tiles.py`.
3. Re-run rawproof/pyramid-ratio; the GATES above stay fixed unless the new
   measured distribution justifies a new freeze entry here (a new dated
   paragraph, old value kept for the record).
4. Regenerate `extracted/data/maps.json` via `run_all.ps1 map`.

### Contract decisions pinned this commit

- **Served-tile URL shape (A1):** `/map-tiles/v{buildid}/albedo/{z}/{x}/{y}.webp`
  — version segment (FRAMEWORK §2.5), zoom segment z∈[0..3], rebased
  non-negative tile indices. Pinned identically in `map_tiles.py`
  (`SERVED_TILE_RE` / `served_tile_template`) and `test_map_tiles.py`;
  in-suite parity assertion prevents one-sided drift.
- **Marker-row carrier (A2):** marker taxonomy ships in
  `maps.json → marker-layers.types[]` (`kind`/`carrier`/`coordinateGate`/
  `pins`, pins stay 0 while D5 is open); future coordinate rows live in
  `marks[]` and must carry provenance `{carrier, digId, buildid}` with an
  exact known carrier (seven-field vocabulary or named prefab carriers).

## 6. Log history

- 2026-08-26 — Post-r1 fix waves land; stages 4–6 cleared to ship (verdict
  APPROVE-FOR-SHIP-COMMIT,
  [docs/arbiter-stages-build-r2.mdx](docs/arbiter-stages-build-r2.mdx);
  chain: [docs/review-stages-code-r2.mdx](docs/review-stages-code-r2.mdx)
  R12–R14 + [docs/review-stages-tests-r2.mdx](docs/review-stages-tests-r2.mdx)
  G1–G3). W5 spec amendments fold the round-1 doc-side rulings into
  [spec-stages-datasets.mdx](docs/spec-stages-datasets.mdx) — full §4.2
  envelope enumeration (F13), `[--buildid]` on the stage vectors (R8),
  counter-table freeze policy (specA-A1), `hbson_emit.py` repointed onto
  the harvest output (specA-A2), regeneration-drops-D7-stamps contract
  (specA-B1) — the spec now reads REVISED r1 AS AMENDED. W6 suite fixes
  close every round-1 test finding (F1–F15): default pytest run 187
  passed / 0 failed / 25 skipped, digit-for-digit vs the ruled
  expectation, retiring the r1 handoff state of `2 failed, 48 passed,
  4 skipped` (T10 split green + independent RED, T2b hard-asserts the
  W2 gate, I1 rewritten verbatim per §3.1, F6 pins re-frozen from
  emitter counters == verifier stdout). G1–G3 tests hardening: staged
  `.tmp` backup publication verified by a length check before
  `os.replace`, proven by an ENOSPC fault-injection harness
  (`output/testfixer-g.log`); `else: pytest.fail` closes the
  parametrized FAULTS chain so no fault leg passes vacuously;
  `tampered` bound before the try with guarded staging/unlink cleanup.
  R12–R14 `validate_all.py` fixes: walk relpath re-anchored to the plane
  root so a C:-cwd invocation over a D: tree exits 0 PASS 8/8 with its
  report written (cross-drive repro; the `ValueError: path is on mount
  'D:'` crash is dead); `catalog-parity` reads RELATIONS.md beside the
  tree under test via the `--reldir` anchor (`relations_md_path`) — the
  discriminator probe falsified one modeled cell in the target tree,
  got rc=1 quoting it field-for-field, and the shared pack render stayed
  pristine across every run; malformed inputs route into their owning
  check's record (`UnreadableInput`) — a truncated `matrix.json` still
  writes a parseable 8-record report naming the locator instead of dying
  reportless. Proofs (arbiter r2, first-hand): E1 cross-drive PASS · E2
  parity discriminator · E3 corrupt-matrix report · E4 planted dangling
  edge exit 1 `pack-wide dangling invariant: 1 != 0` · E5 rerun-twice
  byte-stability (`matrix.json 5efaba53…`, `RELATIONS.md 7e8bfb1e…`,
  identical to the shipped products) · E6/E7 suites green · E8 intruder
  shape record-not-crash · E9 shared-tree hashes byte-identical after
  every run. Debts ride along non-blocking (N1 encoding one-liner at the
  next validate_all touch, N2/N3 notes). §2 `validate_all.py` pin
  refreshed this commit to the post-R14 bytes `c3224362…` (28,228 B) —
  the stale `df701495…` (23,264 B) named in the arbiter's pin audit
  (E2 discipline).
- 2026-08-25 — Stages 4–6 build fix round r1 (arbiter
  [docs/arbiter-stages-build-r1.mdx](docs/arbiter-stages-build-r1.mdx)
  verdict FIX; items W1–W4 + W7 by CodeFixer). `validate_all.py` (W1):
  census loops iterate the managed universe only, so a planted non-managed
  canonical `.jsonl` lands as a `hbson-independent` report record instead of
  a `KeyError` crash with no report (R1/F14); that check now walks BOTH
  canonical planes recursively pruning `_draft`, failing on the four banned
  HBSON names and count-and-reporting other non-managed `.jsonl` (R6);
  `deferred-present` compares `wave_kinds.DEFERRED` against an inline frozen
  §3.5 transcription (R7); `catalog-parity` parse-and-compares every rendered
  RELATIONS.md cell's field values against the matrix records, closing the
  falsified-MD blindness hole (F3); availability locale sets enforce the
  measured bimodal law {∅, exact 9-official} — 458/560 zero-locale rows stay
  lawful, partial sets fail (F4); wave-1-draft precondition anchored to
  PACK_ROOT so non-pack-cwd invocation no longer exits 2 spuriously
  (finding A). `cdb_verify.py` (W2): dangling > 0 is a fail() gate restoring
  §3.3/§4.4 pack-wide (F6-tool), and pair files require
  `_meta.buildId == --buildid` mirroring the dataset check (R5).
  `promote_drafts.py` (W3): payload equality is byte-exact after the
  `_meta` line — CRLF twins and missing-final-LF targets now count
  `updated` (R2); argparse CLI, usage errors exit 2 (R3); draft-set must
  cover the managed universe (40 kinds / 51 pairs) before any write, else
  exit 2 naming the missing entries (R4); ledger names `poi_tile_coords.jsonl`
  (D11) and `battle_scene.jsonl` (D12) and enumerates subdirectories as
  "subdirectory (never scanned)" (R9). `relink_catalog.py` (W4): a zero-edge
  pair file never renders `modeled` — §4.3 ≥1-edge enforced, evidence-less
  directions fall through the ladder carrying their unblock (R11); §2 pins
  for all four tools refreshed in this commit (E2 discipline). Proofs:
  fakeroot A/B probes — intruder run writes the full report with
  `hbson-independent=False` exit 1 no-traceback while the identical control
  tree passes 8/8; source-authoring dangling edge (ghost id seeded into a
  data.cdb copy, waves regenerated) exits 1 with `pack-wide dangling
  invariant: 1 != 0` as the sole failure; tampered pair-file buildId exits 1
  naming file and id; truncated `--plane` / unknown plane exit 2 cleanly;
  30-of-40 sandbox over an empty out-dir exits 2 naming the missing kinds
  without creating the out-dir; live-draft promotion enumerates both new
  ledger names plus probe subdirectories; CRLF/no-final-LF twins flip to
  `updated` then rerun stable; synthetic zero-edge pair renders
  missing/partial → ordered-pair upgrade dig with 39 modeled directions
  unchanged; validator from a non-pack cwd exits 0. Suite state left for
  TestFixer W6: default suite `2 failed, 48 passed, 4 skipped` — T10's RED
  case (fault 5) flipped green with zero test edits (T10 now fails only on
  its dead fault-6 leg, which reads a report `_fault_copy` deliberately
  excludes) and T2b fails only its ghost-name assertion while the gate
  itself fires rc==1; both are test-file items W6 owns.
- 2026-08-25 — Stages 4–6 BUILT ([spec-stages-datasets.mdx](docs/spec-stages-datasets.mdx)
  REVISED r1): `datasets` / `relink` / `emit` wired into the entrypoint
  following the map pattern (`Invoke-*` functions + shared step runner,
  `| Out-Host` on every native call, `[dry-run] stage i/N would run:` vectors,
  child exit-code propagation, equality preconditions exit 2 naming the
  owning stage); defaults block gains the `CDB` key. New tools:
  `wave_kinds.py` (managed-universe membership metadata), `promote_drafts.py`,
  `relink_catalog.py`, `validate_all.py`. Spec-ordered retrofits: hole 1
  (verifier pair-name + managed-universe scan scope, skip-and-enumerate) and
  hole 2 (`--buildid` on both CDB tools); `hbson_emit.py` input repointed off
  the scratch copy onto the harvest output (F14/A2). Proofs: `--list`;
  `--dry-run` full walk + per stage; isolation PASS runs of all three stages
  (40 kinds / 10,207 rows / 51 pairs / 19,130 edges / dangling 0 /
  unverifiable 72 decomposing 61+9+2 / preserved keys 133; availability
  3,779 = 2,125+1,373+281 with the 27-key filler grid all zero and overlays
  29,889; validator 8/8 reconciling 10,207+1,266 = 11,473; RELATIONS.md 780
  rows, 39 modeled directions of 1,560, matrix sha256 marker parity);
  rerun idempotency (all `unchanged`, canonical mtimes untouched) and
  byte-stable `matrix.json` / `RELATIONS.md` / `locale_availability.jsonl` /
  overlays; drift semantics one per class (ghost canonical file → exit 1
  naming it, never deleted; deleted managed file restored from its draft at
  exit 0 counted `updated`; consumer stage alone → exit 2 naming the
  producer; `--buildid` mismatch → exit 1 before any write). A full no-args
  walk still halts at decompile exit 3 (hole 4, fail-loud intact).
- 2026-08-25 — Dig 11 closes the world↔tile transform (spec `maps.coordinate-transform`,
  PROOF R8): `fit_world_transform.py` battery CONFIRMED under pre-frozen gates
  (labels 509/518 = 0.9826, label-shift curve peak at zero, coastal polarity 4/4,
  collide IoU 0.7988); `registry --y-axis north-up --d-sign -1` landed the Dig 6
  orientation pin + the NEW `coordinateTransform` block (schema +40 lines, additive)
  + AC9 roundtrip budget 128 px (`D6_BUDGET_PX` freeze; activates the suite's
  roundtrip test); `poi_tile_coords.jsonl` 607 rows emitted. Frozen gate constants
  untouched.
- 2026-08-25 — Map-pipeline round-1 fixes (arbiter
  [docs/arbiter-map-build-r1.mdx](docs/arbiter-map-build-r1.mdx)): contract
  adapters so the 21 skipped behavioral tests execute; C2 encounter-spawn +
  vendor-npc added to the marker taxonomy; D2/D7 gate freezes + AC1 re-pin
  procedure recorded in §5; A1/A2 contract decisions pinned; `map` stage wired
  into the entrypoint (§3 table row 2) — which exposed a latent PowerShell bug
  in BOTH child invokers: native stdout flows into the function's return
  stream, so `$rc` captured the child's output plus its exit code and PASS read
  as FAILED; fixed with `| Out-Host` in `Invoke-Harvest` + `Invoke-MapRegistry`
  (proof: `--list`, `--dry-run`, `run_all.ps1 map` → PASS exit 0).
- 2026-08-25 — Created this log + the `run_all.ps1`/`run_all.sh` entrypoint
  (brief `docs/briefs/codewriter-runall.mdx`). Pins of §1–§2 measured on
  NE8K at the pinned buildid 20318128; no payload was extracted during
  creation. Proofs: `--list`, `--dry-run`, stub stages exit 3 with their
  pointers, unknown flag → usage exit 2, and a `harvest.py --manifest-only`
  smoke through the entrypoint's exact argument vector (tree-walk only,
  throwaway out dir since removed) parsed all four paks to the spec §2.3
  counts — 17,131 / 15,248 / 6,886 / 936, version byte 0 confirmed,
  buildid `20318128` stamped into summaries.
