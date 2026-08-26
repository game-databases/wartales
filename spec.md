# Wartales — Game Spec (template v2.2, DRAFT R2 — unfrozen)

Drafted 2026-08-24 from the scout wave; revised same day (R2) once both
awaited reports landed. Shorthands: **recon** = `docs/client-recon.mdx` ·
**scratch** = `output/_recon-scratch/` (pak entry TSVs + probe logs,
local-only) · **COMP** = `docs/competitor-research.mdx` · **TOOL** =
`docs/toolchain-validation.mdx` · **PLAN** = `tools-plan.md` · **INDEX** =
`design/sources/INDEX.mdx` · **DR** = `_foundation/decision-register.md`
[DR-2026-08-24-wartales-roster]. No `[PENDING-SCOUT]` holes remain; what is
still unknown is stated as unknown, cited. Freeze is the orchestrator's call
after Arbiter review.

```yaml
game: Wartales                          # Shiro Games, 2021; tactical mercenary RPG (recon §0); store release 2023-04-12,
                                        # 35,533 reviews "Very Positive", 600k+ copies by 2023-05, 8 content DLCs 2023-12→2026-04 (COMP anchors)
folder: wartales                        # pack 52; client on NE8K A:\SteamLibrary\steamapps\common\Wartales\ (DR);
                                        # buildid 20318128 validated / TargetBuildID 21238928 queued (TOOL preamble)
tier: TBD (owner D3 call; provisional umbrella per [DR-2026-08-24-wartales-roster] ¶2–3)
                                        # owner domain call pending (question queue Q1) — [DR-2026-08-24-wartales-roster];
                                        # roster row lands only when tier leaves provisional. Localhost-first regardless.
lifecycle: live                         # Fires in the Capital DLC shipped 2026-04 (COMP anchors) — still shipping content
domain: "{hub}/games/wartales/"         # PROVISIONAL umbrella path per tier; locale-routing: prefixes, pivot EN bare paths
                                        # ([DR-2026-08-20-locale-urls]); localhost-first build proceeds now
stack: next                             # default profile §2.20; corpus expected under ≲30k Astro gate — re-check after P1 counts × 9 locales

identity:
  steam:                                # field ref: _foundation/live-monitoring.md §4
    apps:
      - { appid: 1527950, role: primary, lifecycle: live, coverage-label: "Steam-connected sessions" }
                                        # ✅ appmanifest buildid 20318128 (recon §0); CCU 1,752 @ fetch 2026-08-24 keyless (COMP anchors)
      - { appid: 3899740, role: dlc, lifecycle: live, coverage-label: "Steam-connected sessions" }   # Fief ✅ appdetails (INDEX)
      - { appid: 2903960, role: dlc, lifecycle: live, coverage-label: "Steam-connected sessions" }   # Tavern Opens! ✅ (INDEX)
      - { appid: 2692400, role: dlc, lifecycle: live, coverage-label: "Steam-connected sessions" }   # Pirates of Belerion ✅ (INDEX)
      - { appid: 4165520, role: dlc, lifecycle: live, coverage-label: "Steam-connected sessions" }   # Curse of Rigel ✅ (INDEX)
      - { appid: 3112270, role: dlc, lifecycle: live, coverage-label: "Steam-connected sessions" }   # The Pits ✅ (INDEX)
      - { appid: 3335020, role: dlc, lifecycle: live, coverage-label: "Steam-connected sessions" }   # Skelmar Invasion ✅ (INDEX)
      - { appid: 3559560, role: dlc, lifecycle: live, coverage-label: "Steam-connected sessions" }   # Beast Hunt ✅ (INDEX)
      - { appid: 4490120, role: dlc, lifecycle: live, coverage-label: "Steam-connected sessions" }   # Fires in the Capital ✅ (INDEX), 2026-04 (COMP)
                                        # 8-DLC content roster independently corroborated by COMP anchors; non-content apps
                                        # (soundtrack? supporter packs?) unenumerated → missing-data
    store-cc: us                        # appdetails proven live (INDEX + COMP anchor pulls)

locales:                                # §2.4 launch-blocking
  official: [en, fr, de, es, pl, pt-BR, ru, ko, zh]
                                        # ✅ client-verified 2026-08-24: res.pak:/lang/{texts,export}_<l>.xml pair ×9 (scratch TSV; recon §4);
                                        # store list matches exactly — EN* FR DE ES-ES PL PT-BR RU ZH-HANS KO, full audio EN+KO (COMP anchors)
  canonical: en                         # market pivot; dev pivot is French — root texts.xml is FR source, ids accent-stripped
                                        # French ("dbutant","aucun") (recon §4)
  ui-locales: []                        # none evidenced — wartales.com unreachable (INDEX gaps)
  community: [ja]                       # no official JA yet an unofficial JA-translation guide trends on Steam hub (COMP §2.6, §4#20) —
                                        # declared per §2.4 as authored-translation/community-overlay opportunity, ship call at build time;
                                        # RU largest non-EN signal (12.8k-comment megathread, COMP §2.7) but RU already official
  source-per-locale:
    all: client-pack                    # res.pak:/lang/* ships all 9 in-client ✅ extracted & adler-MATCHed ×17 (_verify/, 2026-08-24):
                                        # wtpak.py extract res.pak lang/{texts,export}_<l>.xml ×17 → stored==computed adler32, 17/17 MATCH;
                                        # XML parse trivial, not yet run end-to-end
    ja: authored-translation            # community overlay candidate (COMP §4#20) — no client JA strings exist
    filler-policy: omit-until-translated # DECLARED per localization-architecture §5.5 — ja authored-lane rows absent from the
                                        # client stay omitted until translated (omission picked over filler; total coverage makes either defensible)
    code-mapping: { zh: zh-Hans }       # client code `zh` ships store-named zh-Hans (localization-architecture §5.2)
    availability-log: extracted/relinks/locale_availability.jsonl
                                        # drives link rows, sitemaps, coverage stats; regenerated per rerun (localization-architecture §5.4)
  locale-cells: none                    # one worldwide client, no region/era coupling evidenced (recon §4)

axes:                                   # §2.18
  version-eras: continuous              # buildid stamps (20318128→21238928 observed); texts_/export_ headers add free
                                        # per-record version/revision/date stamps for patch-diffing (recon §0, §8.10)
  platforms: none-declared              # Windows Steam client only on disk; no console/port evidence
  game-modes: [single-player, online-co-op]
                                        # co-op over Steam networking (recon §8.6); no data fork between modes evidenced.
                                        # Difficulty modes (Region Locked / Adaptive Exploration / Extreme) behave as uninspectable
                                        # config (COMP §3.3) — plane-axis candidate, values [P0-DIG] (PLAN row 9); declare when read
  variant-axes: { item: [quality-tier] }
                                        # UI tints prove tiers (INDEX); +1/+2 superior = +10%/+20% stats + armor-layer slots (COMP §3.1);
                                        # exact enum from CDB item/bonus sheets P1

# Source shorthands (presence from recon TSVs; READ verdicts from TOOL):
#   CDB = res.pak:/data.cdb — CastleDB brain, 6,088,918 B, adler-MATCH extract (TOOL §1); container decoded:
#         CastleDB JSON w/ customTypes + compress flag, 386 sheets enumerated (icon 801, notify 482 rows)
#         (TOOL §5); row-level emit not yet run end-to-end → P1
#   EXP = res.pak:/lang/export_<l>.xml (+ root texts_en.xml) — CDB text export, 35 sheets × <entry><text>
#         leaves (9,912 @en); IS the entity↔text relink bridge (recon §4)
#   PRE = content.pak:/prefabs — all 15,248 entries exact vs TSV, wtpak-verified (TOOL §1); HBSON blobs;
#         subdir census: battle 6,656 / backgrounds 2,697 / fx 1,734 / places 1,454 / camp 820 /
#         buildings 279 / activity 45 / … (scratch)
#   REG = res.pak:/content/regions/<tree>/ — 11 trees, 724 prefabs: POI 453 / Towns 156 / Secrets 115
#         (scratch res-pak-entries.tsv) — the map-marker/town corpus (relations M4)
#   UIA = assets.pak:/ui — 813 icon/style entries (.asl + atlases + style.css 779 KB); route textures by
#         MAGIC never extension — assets .png mostly DDS payloads (7,769/8,447) (TOOL §1 §3)
#   CHARS = assets.pak:/chars — 6,128 character/creature assets; .fbx are ALL HMD models; portraits are
#         2D textures among the rest (TOOL §1, recon §8.3)
#   HLB = hlboot.dat — HashLink bytecode v4 (`HLB\x04`), 16,102,040 B (TOOL §2)

entities:                               # containers from TSV evidence; read-verdicts per TOOL
  item:
    key: game-id                        # CDB numeric ids; slug at normalize; text join via EXP item/itemType sheets
    attributes: [type, quality-tier, weight, value, bonuses, effects, equip-slot, icons]
    variant-axes: [quality-tier]
    sources:
      - { role: stats, class: client-extraction, container: CDB, codec: castledb-reader, readiness: verified,
          readiness-note: "pak layer proven (TOOL §1); CastleDB decoded, 386-sheet census (TOOL §5); row emit P1",
          fallback: "TOOL §4 A (validated) / B (CDBTool)", provenance: client, durability: durable }
      - { role: display, class: client-extraction, container: UIA, codec: asl-icon-styles, readiness: on-disk,
          readiness-note: "route by magic — DDS hides behind .png (TOOL §3)", provenance: client, durability: durable }
      - { role: reconciliation, class: client-extraction, container: EXP, codec: cdb-export-xml, readiness: verified,
          readiness-note: "counted by recon §4 (9,912 leaves @en)", provenance: client, durability: durable }
  skill:
    key: game-id
    attributes: [cost-ap, cooldown, element, effects, status-applied, class-list, icons]
    sources:
      - { role: primary, class: client-extraction, container: "CDB sheets skill/effect/status/condition/bonus/element",
          codec: castledb-reader, readiness: verified, readiness-note: "same CDB verdict as item (TOOL §1 §5)",
          fallback: "TOOL §4 A / B", provenance: client, durability: durable }
      - { role: display, class: client-extraction, container: UIA, codec: asl-icon-styles, readiness: on-disk,
          provenance: client, durability: durable }
  status-trait:                         # grouped kind pair — buffs/debuffs + unit traits (EXP sheets for both)
    key: game-id
    attributes: [duration, effects, stacking, category]
    sources:
      - { role: primary, class: client-extraction, container: "CDB sheets status/trait/condition", codec: castledb-reader,
          readiness: verified, readiness-note: "stacking caps partly community-measured (COMP §3.2)",
          provenance: client, durability: durable }
  class:
    key: game-id
    attributes: [name, skill-set, stat-growth, start-equipment]
    sources:
      - { role: primary, class: client-extraction, container: "CDB sheet startChoice (+unit schema TBD-P1)",
          codec: castledb-reader, readiness: on-disk,
          readiness-note: "startChoice ✅ EXP 35; no dedicated class sheet — unresolved-P1 (386-sheet census may hold it)",
          provenance: client, durability: durable }
  companion:                            # hired characters; distinct from enemy troops
    key: game-id
    attributes: [class, attributes, traits, wounds, level, wages, portraits]
    sources:
      - { role: stats, class: client-extraction, container: CDB, codec: castledb-reader, readiness: verified,
          provenance: client, durability: durable }
      - { role: display, class: client-extraction, container: CHARS, codec: magic-routed-unpack, readiness: on-disk,
          readiness-note: "portraits = 2D textures among 6,128; extensions lie (TOOL §1, recon §8.3)",
          provenance: client, durability: durable }
  unit-enemy:                           # enemy trichotomy beasts/champions/humans + elite flag (COMP §3.1)
    key: game-id
    attributes: [type, stats, skills, loot-table, region-pool, tier, elite-flag]
    sources:
      - { role: stats, class: client-extraction, container: "CDB sheets group/groupType/battle", codec: castledb-reader,
          readiness: verified, provenance: client, durability: durable }
      - { role: baseline, class: client-extraction, container: "PRE /prefabs/battle/** (6,656)", codec: hbson,
          readiness: on-disk, readiness-note: "HBSON magic identified, decode unproven (TOOL §1)",
          provenance: client, durability: durable }
  battle-scene:                         # tactical maps as data (grid terrain, spawn points)
    key: game-id
    attributes: [terrain-grid, size, spawns, region]
    sources:
      - { role: primary, class: client-extraction, container: "PRE /prefabs/battle/*/terrain/*.bin (5,880)", codec: terrain-bin,
          readiness: on-disk, readiness-note: "content .bin census = raw float arrays (TOOL §1); grid layout P1",
          provenance: client, durability: durable }
  recipe:
    key: game-id
    attributes: [station, inputs, outputs, profession, acquisition-sites]
    sources:
      - { role: primary, class: client-extraction, container: "res.pak:/content/script/*.hx (11: region-named quest scripts + World.hx + Paths.hx) + formulas.hx (687 B) + PRE activity prefabs (45)",
          codec: hscript+hbson, readiness: on-disk,
          readiness-note: "NO recipe sheet in EXP 35; script set reads quest-flavored (scratch TSV) — recipe split TBD-P1",
          provenance: client, durability: durable }
  quest:
    key: game-id
    attributes: [giver, steps, rewards, region, chain, dialogue-choices]
    sources:
      - { role: primary, class: client-extraction, container: "CDB sheets mission/fiefMission/tutorial/confessions",
          codec: castledb-reader, readiness: verified, provenance: client, durability: durable }
      - { role: baseline, class: client-extraction, container: "res.pak:/content/script/*.hx region-named hscripts", codec: hscript,
          readiness: on-disk, readiness-note: "candidacy from naming (trees = regions, scratch TSV) — confirm P1",
          provenance: client, durability: durable }
  region:
    key: game-id
    attributes: [name, bounds-shape, hunt-tables, adjacency, poi-list]
    sources:
      - { role: primary, class: client-extraction, container: "REG trees: Alazar_1, Alazar_Aneding, Belerion_1, Edoran_1/2, Gosenberg_1/2, Harag_1, InterRegion_1/2, Worldwide", codec: hbson,
          readiness: on-disk, readiness-note: "CORRECTS R1: map.pak holds ONLY tiles+height (4,131 .dds/2,754 .raw/1 json, scratch;
          sole .json = /assets/worldmap/data/textures.json (texture index)); region structure lives here, decode gated on HBSON",
          provenance: client, durability: durable }
      - { role: reconciliation, class: client-extraction, container: "CDB sheet region", codec: castledb-reader,
          readiness: verified, provenance: client, durability: durable }
  poi-marker:                           # NEW — REG POI 453 + Secrets 115 prefabs = on-map marker corpus (M4)
    key: game-id
    attributes: [type, region, map-pos, respawn-flag]
    sources:
      - { role: primary, class: client-extraction, container: "REG /POI/*.prefab + /Secret*/**/*.prefab (115 = Secrets 103 + Secret 12)", codec: hbson,
          readiness: on-disk, readiness-note: "names enumerate vocabulary (A1BorderPost, A1CryptAdmiral…, scratch); coords inside HBSON — decode P0-relevant",
          provenance: client, durability: durable }
  location-place:
    key: game-id
    attributes: [kind, region, services, map-pos]
    sources:
      - { role: primary, class: client-extraction, container: "CDB sheets place/fiefPlace + REG /Towns/*.prefab (156)",
          codec: castledb-reader+hbson, readiness: on-disk, provenance: client, durability: durable }
      - { role: baseline, class: client-extraction, container: "PRE /prefabs/places/** (1,454 incl. fiefdom/*)", codec: hbson,
          readiness: on-disk, provenance: client, durability: durable }
  npc-vendor:
    key: game-id
    attributes: [role, stock, prices, location, dialogue]
    sources:
      - { role: primary, class: client-extraction, container: "PRE places/fiefdom prefabs + CDB (schema TBD-P1)",
          codec: hbson+castledb-reader, readiness: on-disk, provenance: client, durability: durable }
  faction-kingdom:
    key: game-id
    attributes: [standing-effects, regions, relations]
    sources:
      - { role: primary, class: client-extraction, container: "CDB sheets kingdom/group/groupType", codec: castledb-reader,
          readiness: verified, provenance: client, durability: durable }
  fief:                                 # governance subsystem — laws/events/population/administration all have EXP sheets
    key: game-id
    attributes: [districts, laws, events, population, alignment, administration]
    sources:
      - { role: primary, class: client-extraction, container: "CDB fiefPopulation/fiefPlace/fiefMission/fiefLaw/fiefEvent/fiefCondition/fiefAlignment/fiefAdministration",
          codec: castledb-reader, readiness: verified, provenance: client, durability: durable }
      - { role: baseline, class: client-extraction, container: "res.pak:/content/fiefdom (25) + PRE places/fiefdom/**",
          codec: hbson, readiness: on-disk, provenance: client, durability: durable }
  animal-mount:
    key: game-id
    attributes: [stats, carry-capacity, capture-requirements, fodder]
    sources:
      - { role: primary, class: client-extraction, container: "CDB (sheet TBD-P1) + CHARS display", codec: castledb-reader,
          readiness: on-disk, provenance: client, durability: durable }
  building-camp:
    key: game-id
    attributes: [function, upgrades, staffing, recipes, adjacency-effects]
    sources:
      - { role: primary, class: client-extraction, container: "PRE /prefabs/camp (820) + /buildings (279) + CDB TBD-P1",
          codec: hbson+castledb-reader, readiness: on-disk, provenance: client, durability: durable }
  lore-document:
    key: slug                           # documents carry no stable numeric id — key on EXP/texts group id
    attributes: [body, region, faction, confessions-set]
    sources:
      - { role: primary, class: client-extraction, container: "EXP confessions + texts_<l>.xml groups", codec: cdb-export-xml,
          readiness: verified, readiness-note: "texts EN: 2,148 strings / 237 groups (recon §4)",
          provenance: client, durability: durable }
  achievement:
    key: steam-api-name                 # NOT among EXP 35 sheets — lives on the Steam surface
    attributes: [name, description, global-percent, unlock-condition]
    sources:
      - { role: primary, class: official-feed, container: steam-web/GetSchemaForGame, codec: none, readiness: unverified,
          readiness-note: "schema endpoint unprobed; conditions also [P0-DIG]-able client-side (PLAN row 18)",
          provenance: official, durability: durable }
      - { role: baseline, class: official-api, container: steam-web/appdetails, codec: none, readiness: verified,
          readiness-note: "count-only ✅ 235 achievements live-fetched 2026-08-24 (COMP anchors); 20 achievement guides = demand (COMP §2.6)",
          provenance: official, durability: durable }

relations:                              # SEED = COMP §7 applied relinking delta ([DR-2026-08-17-relink]): 8 must-have chains (M)
                                        # + 8 extraction-only edges (E); inverted indexes emitted per pair; mechanism: hard/logic/inferred
  - "M1 region ↔ location-place ↔ building-camp ↔ item (containment → market/regional goods; hard, CDB place/fiefPlace + REG Towns) [COMP §7.1]"
  - "M2 item ↔ blueprint ↔ station/profession ↔ materials → quality-tier outcomes incl. golden-strike odds (hard+logic) [COMP §7.2]"
  - "M3 weapon(item) ↔ class ↔ specialization ↔ skill, DLC-gating flags (hard) [COMP §7.3]"
  - "M4 region ↔ poi-marker — ≥12 typed layers: crossings, knowledge books, unique recruits, secrets, treasures, bosses,
     black-market agents, resources, camp equipment, fishing spots, veins, bandit reinforcements (hard, REG POI/Secrets) [COMP §7.4]"
  - "M5 location-place ↔ trade-good(item) price matrix × distance gradient × perk/meal modifier caps
     (logic; caps hand-measured ≈35% buy-cut / ≈25% sell-bonus, COMP §3.2) [COMP §7.5]"
  - "M6 status-trait ↔ skill / item(oils,stamps) / weapon (hard) [COMP §7.6]"
  - "M7 quest/npc ↔ dialogue-choice ↔ outcome — interrogations (hard; confessions = strongest CLIENT row, PLAN row 16) [COMP §7.7]"
  - "M8 unit-enemy beasts/champions/humans + elite-flag ↔ spawn tables (hard, group/groupType + battle prefabs) [COMP §7.8]"
  - "E1 weighted drop/spawn/capture probabilities: unit-enemy↔item (loot), region↔unit-enemy (spawns),
     unit-enemy↔companion (capture→recruit odds) — logic, decompiled [COMP §7]"
  - "E2 recipe ↔ acquisition-site multi-source typed: one recipe, N sites — the halcyan2 gap nobody models (hard) [COMP §7]"
  - "E3 versioned truth: every relation value carries buildId stamp; patch-diff re-emits (per-record staleness) [COMP §7]"
  - "E4 economy closure: companion(wages) ↔ building-camp(rest) ↔ item(provisions) ↔ price matrix, one computable model (logic) [COMP §7]"
  - "E5 game-mode(difficulty) ↔ scaling parameter sets over region/unit (logic, P0-DIG) [COMP §7]"
  - "E6 achievement ↔ unlock-condition graph, 235 nodes (mixed) [COMP §7]"
  - "E7 locale parity bridge: every entity ↔ EXP text leaves ×9 locales (hard, the recon §4 join) [COMP §7]"
  - "E8 complete pairwise matrix incl. inferred edges (doctrine Principle one) [COMP §7]"
  # carried from R1 draft, folded under chains: skill↔class (M3); trait↔companion; companion↔class;
  # battle-scene↔region; building-camp↔recipe (M2); building-camp↔companion (E4); animal-mount↔companion (E1);
  # faction-kingdom↔region; fief↔region; fief↔faction-kingdom; region↔region adjacency (feeds M5 gradient);
  # lore-document↔region/faction; location-place↔npc-vendor (M1/M5); quest↔item rewards; quest↔location-place steps

maps:                                   # §2.6 ESSENTIAL — top-priority workstream; gates site-ready ([DR-2026-08-16])
  imagery-path: client-extracted        # map.pak albedo+normal+splat DDS tile grid, x/y addressed; parse EXACT: 6,886 files,
                                        # 0 mismatches vs TSV, 1,612 entries >4 GiB sampled adler-MATCH (TOOL §1); 4,131 .dds ≈ 24.5 GB
                                        # in map.pak of 31.7 GB pack-wide (TOOL §3, recon §7) + height_x-y.raw/_s float pyramid
  layers: [world-strategic,             # albedo pyramid + height raw grids (scratch map-pak-entries.tsv)
           region-overlays,             # CORRECTED: overlays ride res.pak:/content/worldmap.l3d + wmap_current.prefab (HBSON scenes),
                                        # NOT map.pak JSONs (no region-shape JSONs; the sole map.pak .json is a texture
                                        # index — scratch); legend red/green states (INDEX shot-05)
           marker-layers,               # REG POI/Towns/Secrets prefabs; vocabulary inherits the 62.6k-visit guide legend (COMP §3.2)
           hunt-regions,                # hunt panel checklist (INDEX shot-04)
           battle-tactical,             # content.pak terrain bins DECODED (Dig 12: 97 scenes × 64 m tiles × h/n/i/w roles;
                                        # local-meter CRS, 1 m tactical cells — battle_scene.jsonl); own CRS family confirmed,
                                        # no worldmap anchor (coordinate-transform untouched)
           fief-districts]              # district icons/tooltips (INDEX shots 06–07)
  coordinate-transform: RESOLVED-D11    # single global axis-aligned affine (no rect-per-map needed): stored mosaic px = world·4
                                        # (128-unit cells; origin = tile x0/y0 top-left); scale is carrier arithmetic
                                        # (worldmap.prefab offsetX −1536 == minTileX −12 × 128; worldSize 8192) — pinned in maps.json
                                        # `coordinateTransform` with validation battery (data-dig-log Dig 11); served A1 shape untouched
  coordinate-sources: { poi-marker: resolved-D11, location-place: resolved-D11, encounter-spawn: unknown-P1,
                        vendor-npc: unknown-P1, fief-district: unknown-P1 }
                                        # D11: poi/town/secret/anchor world coords validated + projected (poi_tile_coords.jsonl,
                                        # towns 61/61 on land); the three P1 slices stay gated on PRE/fief carriers as before
  readiness: ACHIEVABLE                 # upgraded again (Dig 11): imagery path (TOOL §1) + HBSON decode (Dig 7) + transform
                                        # (D11 pin in maps.json) all closed; remaining map work is P1 slices + polygon emission

economy:
  npc-prices: yes                       # item/region/place/constant sheets [CLIENT] (PLAN row 1); regional variance + perk/meal caps
                                        # hand-measured ≈35%/≈25% (COMP §3.2); exact formula [P0-DIG] (CDB+HLB)
  market-feed: none                     # no player market exists
  streaming: none                       # single-player/co-op; no server-side economy surfaces (recon §8.6)

live:                                   # _foundation/live-monitoring.md §4 shapes
  steam:
    enabled: yes
    key-ref: shared
    surfaces: [appdetails, news, ccu]   # news feed proven live (INDEX); keyless CCU fetched clean 2026-08-24 (COMP anchors)
    ccu:
      durability: ephemeral
      history: streaming                 # JSONL from first production poll ([DR-2026-08-15] D1)
      coverage-label: "Steam-connected sessions"
    publish: { artifact: snapshot-json, path: live/steam, history-path: live/steam/ccu.jsonl }
  # catalogue: omitted — co-op is friend-hosted lobbies, no public advertised server list (recon §8.6);
  # co-op stability pain (COMP §4#16) is a live-monitoring product for the live plan, not a catalogue

tools:                                  # SCORED LIST = PLAN §3 (site-sections tool-discovery method); rubric T/C/D/M /20.
                                        # NO dedicated web tooling exists on any observable surface (COMP §2.5) — all lanes open
  - { name: company-companion-build-planner, type: planner, score: 18, flagship: yes,
      evidence: "PLAN §3#1+MVP scope; pain #1/#17; 38.2k-visit build guide; owner directive names builders (DR)" }
  - { name: trade-route-planner-price-atlas, type: planner, score: 17,
      evidence: "PLAN §3#2; pain #4/#5; four hand-built price artifacts decay per patch (COMP §2.8)" }
  - { name: owned-interactive-map, type: data-product, score: 16,
      evidence: "PLAN §3#3; Map Genie ABSENT (COMP §2.3); 62.6k-visit static guide = demand" }
  - { name: recipe-blueprint-explorer, type: data-product, score: 16,
      evidence: "PLAN §3#4; pain #19; multi-location wiki-gap quote (COMP §3.2)" }
  - { name: interrogation-dialogue-db, type: data-product, score: 16,
      evidence: "PLAN §3#5; pain #12 — 13.9k visits for ONE quest; confessions sheet [CLIENT]" }
  - { name: capture-recruit-explorer, type: calculator, score: 15,
      evidence: "PLAN §3#6; pain #2/#3/#18; 14.1k-visit prisoner guide" }
  - { name: food-efficiency-upkeep-calculator, type: calculator, score: 15,
      evidence: "PLAN §3#7; pain #13; top-rated food guide + 362-pt thread" }
  - { name: achievement-checklist-hub, type: tracker, score: 15,
      evidence: "PLAN §3#8; 235 achievements, zero incumbent coverage (COMP §7)" }
  - { name: spawn-scaling-inspector, type: data-product, score: 14,
      evidence: "PLAN §3#9; pain #9/#17; modes as uninspectable config (COMP §3.3)" }
  - { name: camp-layout-designer, type: planner, score: 13,
      evidence: "PLAN §3#10; pain #15; 222-pt + 95-pt camp threads" }
  # Excluded (PLAN §3): arena-betting advisor (score 12, watchlist until The Pits P0-DIG); co-op status
  # troubleshooter → live-monitoring plan. Ship order: PLAN §4.

automation:                             # §2.12
  update-trigger: build-id              # manifest diff — TargetBuildID 21238928 queued (recon §0); rerun on landing =
                                        # first patch-diff dataset free (PROG log)
  patch-cadence: quarterly-content      # BACKFILLED: 8 content DLCs 2023-12→2026-04 ≈ drop per ~3.6 months (COMP anchors);
                                        # buildid cadence single-observation until 21238928 lands
  staleness-model: per-record           # buildid stamps + per-locale version/revision/date headers (recon §8.10);
                                        # version stamps ARE this community's freshness idiom (COMP §5.5)
  watches: [manifest-drift, steam-endpoint-death, appdetails-drift, key-rotation]

satellite:                              # §2.17
  platform: overwolf                    # default candidate; single-player/co-op limits overlay value — expect status:no after gep-check
  status: considered
  gep-check: open

legal:                                  # facts + tags only — legality analysis stays owner-domain (AGENTS.md rule 2)
  data: client-derived only; no third-party datasets ingested (COMP findings are observations of incumbents,
        not sources — e.g. Fandom pages carry CC-BY-SA, recorded repo-only as a fact about that site, COMP §2.2);
        our license tags still to record at first pull; provenance repo-only per AGENTS.md rule 3
  tooling: wtpak.py self-authored clean-room — VALIDATED primary reader, all four paks exact, no
        encryption/compression, adler32-only integrity (TOOL §1); cross-check PAKTool (`paktool-0.0.3-win-x64.zip`, sha256
        at first use) expand of res.pak (byte-identical PNG sha256; license tag not captured, TOOL §1); hlbc 0.5.0 (MIT) FAILS
        on fork type-kinds ≥19 (TOOL §2); hlboot_probe.py written from canonical HashLink reader semantics
        (_refs/hl_code.c); texture chain texconv+cwebp planned (TOOL §3); QuickBMS unneeded (fallback C pinned)
  fan-program: monitoring               # D6 registry; pursue at earliest published eligibility; packet prepared at freeze
  avoid-list: [player-save-data]        # save/ + prefs.sav are user data — datasets come from client files only (recon §6)
  personal-data: none                   # no player names in any planned surface; co-op peers never collected
  malware-policy: n/a                   # acquisition path = official Steam install on NE8K; no forum/leaked artifacts

external-dependencies: [steam-news-rss (official dev posts → News input), steam-appdetails/ccu (@gamedb/steam)]
content-policy-holes:                   # §2.13 + [DR-2026-08-18-media-scope]
  - 3D-ban → HMD models catalogue-first: 6,946 .fbx=HMD in assets.pak alone (TOOL §1), 7,204 / 2.13 GB
    pack-wide (recon §7); MEDIA-CATALOGUE.md; no renders on site
  - audio offload → Wwise 2.49 GiB (2.67 GB) loose under res/ (23 .bnk + 7,021 .wem; EN(US) voice alone 6,959 wem/1.49 GB)
  - video: none exists anywhere in install (verified, recon §7) — no hole
  - heavy-textures catalogue-first → .dds 31.7 GB (map tiles 24.5 GB, TOOL §3) + .png 6.42 GB; bulk conversion
    waits on owner pick; conversion chain DDS→texconv→webp defined (TOOL §3)
  - extension-lie rule → route ALL textures by magic: .png≈DDS payloads, .fbx=HMD, .prefab/.l3d=HBSON,
    .tx=Heaps atlas TBD (TOOL §1)
  - imagery strategy → 2D only: UIA icons/.asl styles, CHARS portrait textures, UI crops (INDEX pool)

missing-data:                           # mirrors future missingdata.md — remaining gaps, none pending-scout
  - wartales.wiki.gg depth unverifiable (domain-wide 401 wall, COMP §2.1); pixel design screenshots owed (COMP §1 §5)
  - HBSON payload decode unproven (magic only) — gates POI/prefab/worldmap.l3d/town coords (TOOL §1)
  - HL bytecode type-walk blocked on fork type-kinds ≥19: header+strings strict-parse ✅ (75,321/75,321),
    26 types clean then drift; continuation mechanical, no crypto; fallback D runtime loader dump (TOOL §2)
  - hscript evaluation unread (formulas.hx 687 B prime suspect; 12 .hx sources)
  - RESOLVED by spec-harvest.mdx §2.1, pending CodeWriter proof: flag-2 file-node fields (A,B) — bit-2 selects f64
    position encoding; header u32@0x08 — i32 dataSize, Σsizes mod 2³²; version byte 0 recorded into the EXTRACTION-LOG
    backfill plan; dataSize i32 wraps >4 GiB — entry sums authoritative (TOOL §1)
  - CDB row-level emit not yet run end-to-end (container+sheet census done, TOOL §5)
  - RESOLVED (Dig 11): world↔tile transform pinned in maps.json `coordinateTransform`; map.pak still has no
    vector shapes — region polygons now derivable from layers2D masks through the pinned sampler (queue)
  - recipe container unresolved (no EXP sheet; scripts read quest-flavored); class representation unresolved
  - non-content Steam apps (soundtrack/supporter) unenumerated; GetSchemaForGame unprobed (count 235 ✅ appdetails)
  - buildid patch cadence single-observation until 21238928 lands; wartales.com unreachable (INDEX gaps)

status: { research: done, spec-frozen: true, adapter: not-started,
          full-pull: not-started, site: not-started, maps: not-started,
          locales-complete: false, seo-layer: not-started, verified: false }
# research: client-recon ✅ · design sources ✅ · competitor-research ✅ (incl. applied delta §7)
#           · toolchain-validation ✅ (pak layer proven; HLB seeded, mechanical continuation)
# FROZEN 2026-08-24 by the orchestrator per docs/arbiter-delta.mdx APPROVE-FOR-FREEZE
# (delta re-check; original rulings docs/arbiter-specs.mdx). Changes now require a DR entry.
```
