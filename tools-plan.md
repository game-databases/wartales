# Wartales Tools Plan

Produced 2026-08-24 by the Documentator pass, method =
[`_foundation/site-sections.md`](../_foundation/site-sections.md#tool-discovery-process-mandatory-per-pack-rerun-on-every-major-patch)
(compete inventory → mechanics enumeration → moat-first scoring → pain-point
mining → scored list → ship-embed-iterate). Evidence base:
[`docs/competitor-research.mdx`](./docs/competitor-research.mdx) (§2/§4/§6/§7)
and [`docs/client-recon.mdx`](./docs/client-recon.mdx) (buildid 20318128,
Heaps/HashLink, `data.cdb` + `formulas.hx` + hscripts + 16 MB HLB bytecode).
Customization posture: tools are plugins over engine slots, flagships are
launch-scope when research says market gap
([FRAMEWORK §2.16](../FRAMEWORK.md#216-per-game-customization-is-architectural-not-tolerated)).
Re-run this plan on every major patch (the install already carries a queued
update, TargetBuildID 21238928 —
[recon §8](./docs/client-recon.mdx#8-unexpected-findings--open-items)).

---

## 1. Competitor tool inventory

Every incumbent/lane found, with traffic and the evidence basis
([research §2](./docs/competitor-research.mdx#2-inventory-of-incumbents),
[§6](./docs/competitor-research.mdx#6-traffic--scoring-table-input-to-tools-plan)).
Steam figures are measured lifetime counters; `(est.)` marks reasoned
estimates with basis inline; everything else is absence evidence.

| Lane / incumbent | Shape | Traffic (basis) | Tool-relevant finding |
|---|---|---|---|
| wartales.wiki.gg | wiki | low-hundreds of k monthly **(est.**, primary-wiki slot for a 35.5k-review game; walled 401, low confidence**)** | opaque to agents/crawlers; depth unverified |
| wartales.fandom.com | wiki | negligible (239 articles measured) | prose-only, DLC-stale since ~2024-12 |
| Map Genie | map | **absent** (404 + 0 sitemap hits) | the interactive-map lane is empty white space |
| Fextralife | wiki | **absent** (DNS) | one fewer wiki incumbent than assumed |
| gaming.tools | tools | unverified (Cloudflare-walled) | no verifiable Wartales tool found anywhere else either |
| Steam guides hub | manual DB | 62.6k / 38.2k / 14.4k / 14.1k / 13.9k / 12.6k visits on top guides (**measured**) | the de-facto database: static images, version-stamped titles, rots silently |
| Steam discussions | forum | RU megathread 12.8k comments (measured) | raw pain-point stream, no data |
| r/WartalesGame | forum | continuous 2021→2026, top posts 100–600 pts | community mental model (routes, capture, camp, modes) |
| Community spreadsheets | sheets | tens-to-hundreds of pts each | four independent hand-built trade-price artifacts = proven demand |

**Net:** there is no dedicated web tooling for Wartales on any observable
surface — calculators, planners, trackers, and the interactive map are all
open lanes ([research §2.5](./docs/competitor-research.mdx#25-gamingtools--planner-calculator-sites--unverified-walled)).

---

## 2. Mechanics enumeration

What the game computes, from recon evidence (res.pak carries `/data.cdb`
6.09 MB, `/formulas.hx`, 12 hscript sources incl. `World.hx`,
`names.yml`; `export_*.xml` mirrors 35 data.cdb sheet names;
[recon §2](./docs/client-recon.mdx#2-pak-format-fully-decoded),
[§8](./docs/client-recon.mdx#8-unexpected-findings--open-items)) plus the
community relationship model
([research §3](./docs/competitor-research.mdx#3-relationship-model-extraction-the-floor)).

Status legend — **[CLIENT]** the system's data artifact is confirmed present
in the client (named sheet/file observed; values not yet read); **[COMM]**
community-inferred (hand-measured or argued, no client read yet);
**[P0-DIG]** parameters recoverable only by the extraction dig (data.cdb
sheets + HLB bytecode) — flagged for the dataminer's P0.

| # | System | Computes | Evidence | Status |
|---|---|---|---|---|
| 1 | Trade prices & gradients | per-town×good base prices, distance profit gradient, perk/meal modifiers incl. non-stacking exception | 4 hand-built artifacts; caps ≈35% max buy cut / ≈25% max sell bonus hand-measured (Paulus Bruna) | [COMM] caps · exact formula [P0-DIG]; `item`/`region`/`place`/`constant` sheets [CLIENT] |
| 2 | Wages & company upkeep | per-unit wages, level-scaled salaries netted against trade income | route analyses net "food and salaries" | existence [COMM]; parameters [P0-DIG] |
| 3 | Food consumption & ration efficiency | rations/company/time, value-per-coin per provision | top-rated Food Efficiency guide; 362-pt food thread | rules [COMM]/[P0-DIG]; provision items [CLIENT] (`item` sheet) |
| 4 | XP curves & leveling | XP per level, attribute budgets, specialization gating | Fandom Character Development chain; "out-level the zones" threads | curve [P0-DIG] (`formulas.hx` 687 B prime suspect); chain shape [CLIENT] (`attribute`, `startChoice`) |
| 5 | Capture / tame odds | rope quality, HP thresholds, choice paths, beast templates | Ultimate Prisoner Guide 14.1k visits; recurring capture-failure threads | pipeline shape [COMM]; weights [P0-DIG] |
| 6 | Arena betting odds (The Pits) | fighter tiers, payout multipliers | The Pits DLC ships; no community model found | entirely [P0-DIG] |
| 7 | Injury & death resolution | injury tables, death thresholds, treatment costs | Injuries as wiki entity kind; `status`/`condition` sheets | kinds [CLIENT]; table [P0-DIG] |
| 8 | Morale / mood | mood modifiers, rest, events | Fandom Game Mechanics taxonomy (Mood) | kind [CLIENT]-adjacent; numbers [P0-DIG] |
| 9 | Adaptive difficulty & region-lock scaling | spawn levels, XP modifiers per mode (Region Locked / Adaptive Exploration / Extreme) | players reason about modes as uninspectable config | mode names [COMM]; parameter sets [P0-DIG] |
| 10 | Crafting quality tiers & golden strikes | +1/+2 superior (+10%/+20% stats), extra armor-layer slots, Champion Craftsman title edge | Fandom forging math tables; halcyan2 blueprint guide | outcome table [COMM]-measured; exact probabilities [P0-DIG] |
| 11 | Ghost curses | curse application/removal (Ludern/Skelmar content) | Skelmar mission threads | entirely [P0-DIG] |
| 12 | Path perks & titles | modifier sets per path, stacking caps | Paths & Titles wiki kind; measured caps feeding row 1 | kinds [CLIENT]; full modifier table [P0-DIG] |
| 13 | Valor points | generation, sharing across company, spend | zAcEz build guide valor notes; "valor sharing surprises" | existence [COMM]; economy [P0-DIG] |
| 14 | Knowledge system | knowledge books → unlocks | Usikava marker layer (Knowledge Books) | markers [CLIENT]; unlock graph [P0-DIG] |
| 15 | Damage & combat math | weapon damage, armor, crits, positioning, "100+ damage" builds | board question + build guides | formula [P0-DIG] (HLB bytecode); keywords/skills [CLIENT] (`skill`, `effect`, `bonus`, `battle`) |
| 16 | Interrogation / dialogue outcomes | choice → outcome mapping, confession success | Alazar answers guide 13.9k visits for ONE quest | `confessions` + `mission` sheets exist — strongest [CLIENT] row |
| 17 | Loot, drops & respawn | vein/chest/reinforcement weights, respawn flags | Usikava respawn-flagged iron veins; Loot guides 30 | marker vocabulary [CLIENT]; weights [P0-DIG] |
| 18 | Achievement unlock conditions | 235 achievement conditions graph | Steam: 235 achievements, 20 achievement guides | count [CLIENT]; conditions [P0-DIG] |
| 19 | Camp adjacency & rest efficiency | placement bonuses (bears next to beehives), spacing, tool upgrades, rest yield | camp-setup threads 222 pts / 95 pts | effects [COMM]; numbers [P0-DIG] |
| 20 | Prisoner & ransom valuation | recruit-vs-ransom value by tier | "worth recruiting" threads; prisoner guide | tiers [COMM]; values [P0-DIG] |

Rule of thumb applied: *if the game computes it, we can calculator it; if
the game hides it, we can reveal it* — rows 1–20 are the calculator surface;
every [P0-DIG] cell is a dataminer deliverable under AGENTS.md rule 8
(data-before-frontend).

---

## 3. Scored tool list

Rubric, each 1–5: **T** traffic potential (measured demand), **C** build
cost (5 = lightest build), **D** data-readiness (how directly the extracted
corpus yields it), **M** moat/defensibility (can a non-deconstructing
competitor copy it). Total /20. Sorted by score; ties broken by T, then C.

| # | Tool | T | C | D | M | Total | Evidence anchor |
|---|---|---|---|---|---|---|---|
| 1 | **Company & companion build planner** ⭐flagship | 5 | 3 | 5 | 5 | **18** | pain #1/#17; 38.2k-visit build guide; §6 row 3 |
| 2 | Trade route planner + price atlas | 5 | 3 | 4 | 5 | **17** | pain #4/#5; four hand-built artifacts; §6 row 2 |
| 3 | Owned interactive map (all marker layers, state-in-URL) | 5 | 2 | 4 | 5 | **16** | 62.6k-visit map guide; Map Genie absent; §6 row 1 |
| 4 | Recipe / blueprint explorer (multi-source typed) | 3 | 4 | 5 | 4 | **16** | pain #19; 12.6k-visit guide + explicit wiki-gap quote; Crafting 28 guides |
| 5 | Interrogation & dialogue-choice database | 3 | 4 | 5 | 4 | **16** | pain #12; 13.9k visits for ONE quest; `confessions` sheet [CLIENT] |
| 6 | Capture / recruit explorer (prisoners & beasts, exact odds) | 4 | 3 | 3 | 5 | **15** | pain #2/#3/#18; 14.1k-visit prisoner guide |
| 7 | Food-efficiency & upkeep calculator | 3 | 5 | 4 | 3 | **15** | pain #13; top-rated food guide; 362-pt thread |
| 8 | Achievement checklist hub (235 nodes) | 3 | 4 | 5 | 3 | **15** | 235 achievements; 20 achievement guides; zero incumbent coverage |
| 9 | Spawn/scaling inspector (adaptive difficulty & region-lock) | 2 | 4 | 3 | 5 | **14** | pain #9/#17; mode-config threads |
| 10 | Camp layout designer | 3 | 3 | 3 | 4 | **13** | pain #15; 222-pt + 95-pt camp threads |

Excluded from the table, recorded: **arena-betting advisor** (score 12 —
blocked until row-6-style P0-DIG lands on The Pits; watchlist) and the
**co-op status troubleshooter** (pain #16 — a live-monitoring product per
`_foundation/live-monitoring.md`, not a tool plugin; belongs to the pack's
live plan, not this list).

Moat reading: #1, #2, #6, #9 are tools competitors cannot build without full
deconstruction — exact stat/damage formulas, price/perk semantics, capture
weights, and mode parameter sets exist only in `data.cdb` + the 16 MB HLB
bytecode, and every incumbent artifact covering them today is a hand-made
sheet or static guide that rots each patch (zAcEz's build guide: last
updated 2024-10 while eight DLCs shipped through 2026-04).

### Flagship MVP scope — Company & companion build planner (score 18)

Named top tool by the owner directive (promptForDB names build creation);
scored accordingly. MVP ships ONE companion editor, not a party simulator:

- **Inputs:** class → specialization → skills (keyword/tagged), attribute
  allocation against the level budget, traits, weapon + armor-layer loadout;
  company-level slider; difficulty-mode toggle (Region Locked / Adaptive
  Exploration / Extreme). All inputs reactive, address bar follows the
  fields via `replaceState`
  ([DR-2026-08-22-inputs-answer-as-you-type]) — full build state lives in a
  shareable URL from day one, plus import/export code.
- **Computed outputs:** derived stat sheet and damage estimate against
  armor bands from the decompiled formulas; valor/keyword coverage summary.
  Computed numbers carry `data-output-type`; scenario outputs labelled
  what-if per [DR-2026-08-21-drop-chip-words-and-updated-column].
- **Relinking:** every selectable entity renders as a real link to its
  database page; entity pages embed the reverse "used in builds" module
  (interlinking rule).
- **Data dependencies (rule-8 gate, dataminer deliverables):** `skill`,
  `trait`, `attribute`, `effect`, `bonus`, `condition`, `status`,
  `item`/`itemType` sheets from `data.cdb`; damage/stat/XP formulas
  recovered from `hlboot.dat` (`formulas.hx` first read); 9-locale strings
  via `export_*.xml`.
- **Out of MVP:** accounts/community builds (UGC phase), full-party
  composition simulator (v1.1), enemy-side AI simulation.
- **Success measure:** replaces the job of the 38.2k-visit static build
  guide, permanently current per patch.

---

## 4. Ship order

MVP fast → result states in shareable URLs → embedded into related entity
pages (mandatory interlinking rule), refined from usage data.

1. **Wave 0 — shared slots (pre-tool infra):** entity JSON contracts,
   `searchRows`, URL-state kit, calculator UI kit, tooltip/embed primitive
   (FRAMEWORK §2.16 slots; the core ships slots, not game tools).
2. **Wave 1 — fast ships (days after extraction, each interlinked the day
   it ships):** #5 interrogation/dialogue DB → #4 recipe/blueprint explorer
   → #7 food-efficiency calculator. Cheapest, highest data-readiness, and
   each seeds hundreds of entity cross-links.
3. **Wave 2 — flagship:** #1 build planner MVP (scope above) alongside #2
   trade route planner + price atlas v1 (town×good matrix, then perk/meal
   modifier closure once P0-DIG lands).
4. **Wave 3 — owned interactive map (#3):** largest asset pipeline (27.9 GB
   world-tile DDS set → tiles/markers); top priority workstream, gates
   site-ready not launch; marker vocabulary inherited from the 62.6k-visit
   guide's legend.
5. **Wave 4 — long tail riding the patch-diff engine:** #6 capture
   explorer (after odds P0-DIG), #8 achievement hub, #9 scaling inspector,
   #10 camp designer.

Every wave ends with the loop: ship MVP → every result state is a URL →
embed the tool module into the entity pages its inputs/outputs touch
(skill selector → skill pages; atlas cells → town/good pages) → entity
pages surface the tool back ("used in") → refine from usage data.

---

## 5. Evidence links

Candidate → pain-point row
([research §4](./docs/competitor-research.mdx#4-pain-point-mining-each-row--a-tool-candidate))
or competitor gap
([research §2](./docs/competitor-research.mdx#2-inventory-of-incumbents)):

| Tool | Primary evidence | Secondary |
|---|---|---|
| Build planner | pain #1 (class/party comp, 193-pt thread, six per-class videos) | pain #17; 38.2k guide; gap: guides rot vs 8 DLCs |
| Trade planner + atlas | pain #4 (profitability after food+wages) | pain #5; gap: 4 decaying hand sheets (§2.8) |
| Interactive map | gap: Map Genie absent (§2.3) | pain #10/#11; 62.6k guide (§2.6) |
| Recipe explorer | pain #19 (Gosenberg wine; recipe sources) | gap: multi-location sourcing unmodeled anywhere (§3.2 halcyan2 quote) |
| Interrogation DB | pain #12 (13.9k visits, one quest) | gap: no structured dialogue DB in any incumbent |
| Capture explorer | pain #2 (capture how-to ×3 threads) | pain #3, #18; 14.1k prisoner guide |
| Food calculator | pain #13 (cheapest food per ration) | 362-pt food thread |
| Achievement hub | gap: 235 achievements, zero incumbent coverage (§7) | 20 Steam achievement guides |
| Scaling inspector | pain #9 (how does adaptive difficulty work) | pain #17; §3.3 "config switches they can't inspect" |
| Camp designer | pain #15 (camp setup threads) | §3.3 camp-as-layout-puzzle model |

Minimum quota satisfied: 10 scored, evidence-linked candidates (floor ≥5,
[`site-sections.md`](../_foundation/site-sections.md#tool-discovery-process-mandatory-per-pack-rerun-on-every-major-patch)).
