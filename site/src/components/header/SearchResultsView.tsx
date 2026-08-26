/**
 * The in-place results surface (spec-f5-search §5.4). Presentational only:
 * it receives the COMPLETE hit set from the matcher and owns the two
 * presentation laws — grouping by kind in KIND_ORDER order with FULL
 * per-kind counts (capping never lies about coverage), and the overall
 * render cap of the first 50 hits.
 *
 * Anti-slop contract (DR-2026-08-22-copy-earns-its-place §3; AC-15): zero
 * matches render the count `0` beside the echoed query — nothing else. No
 * instructional copy, no suggestions module, no "did you mean".
 *
 * Fix round r2:
 * - M-1 — `unavailable` (failed artifact fetch) renders a plain-word
 *   absence state with a retry affordance ([DR-2026-08-22-numbers-
 *   stand-alone] §1: a fail-closed cell reads as missing, NEVER as a
 *   fabricated measured `0`). The `0`+echo state stays scoped to genuine
 *   zero matches (§5.4).
 * - m-8 — hits whose kind sits outside KIND_ORDER are SURFACED in their
 *   own trailing groups (labelled by the kind itself), not silently
 *   dropped — searchRows deliberately sorts them last rather than
 *   refusing, so the §12 map-search reuse keeps honest output.
 */
import { KIND_ORDER, type SearchHit } from "../../lib/search/searchRows";
import type { SearchChrome } from "../../lib/i18n/search-chrome";

/**
 * Render cap: first 50 hits overall (the network page-size choice,
 * DR-2026-08-18-page-size). A named constant, not a derivation.
 */
export const MAX_RENDERED_ROWS = 50;

/** Kind → chrome key. No second kind vocabulary may appear anywhere. */
const KIND_LABEL_KEY = {
  item: "search.kind.item",
  skill: "search.kind.skill",
  class: "search.kind.class",
} as const;

export interface SearchResultsViewProps {
  hits: SearchHit[];
  /** The raw query as typed — echoed verbatim in the zero state. */
  query: string;
  chrome: SearchChrome;
  /**
   * The artifact fetch failed (M-1): render plain-word absence + retry,
   * never the zero-match state.
   */
  unavailable?: boolean;
  /** Re-fetch the artifact now, while the field stays open. */
  onRetry?: () => void;
  /** Focus return paths owned by the field's state machine. */
  onArrowUp: () => void;
  onEscape: () => void;
}

interface KindGroup {
  kind: string;
  total: number;
  hits: SearchHit[];
}

/**
 * Groups the FULL hit set by kind with full counts: KIND_ORDER groups
 * first, then any out-of-vocabulary kind as its own trailing group in
 * stable name order (m-8 — surfaced, never dropped).
 */
function groupHits(hits: SearchHit[]): KindGroup[] {
  const known = new Map<string, KindGroup>();
  for (const kind of KIND_ORDER) {
    known.set(kind, { kind, total: 0, hits: [] });
  }
  const extras = new Map<string, KindGroup>();
  for (const hit of hits) {
    let group = known.get(hit.row.kind);
    if (!group) {
      group = extras.get(hit.row.kind);
      if (!group) {
        group = { kind: hit.row.kind, total: 0, hits: [] };
        extras.set(hit.row.kind, group);
      }
    }
    group.total += 1;
    group.hits.push(hit);
  }
  const groups = [...known.values()].filter((g) => g.total > 0);
  return groups.concat(
    [...extras.values()].sort((a, b) => (a.kind < b.kind ? -1 : a.kind > b.kind ? 1 : 0))
  );
}

/** Chrome label for a known kind; an unknown kind labels itself (m-8). */
function kindLabelKey(kind: string): string | null {
  return kind in KIND_LABEL_KEY
    ? KIND_LABEL_KEY[kind as keyof typeof KIND_LABEL_KEY]
    : null;
}

function capToRendered(groups: KindGroup[]): Map<string, SearchHit[]> {
  const rendered = new Map<string, SearchHit[]>();
  let budget = MAX_RENDERED_ROWS;
  for (const group of groups) {
    const slice = group.hits.slice(0, Math.max(0, budget));
    rendered.set(group.kind, slice);
    budget -= slice.length;
    if (budget <= 0) break;
  }
  return rendered;
}

export default function SearchResultsView({
  hits,
  query,
  chrome,
  unavailable = false,
  onRetry,
  onArrowUp,
  onEscape,
}: SearchResultsViewProps) {
  const groups = groupHits(hits);
  const rendered = capToRendered(groups);
  /** Known kinds resolve through the §8 facet labels; others self-label. */
  const labelFor = (kind: string): string => {
    const key = kindLabelKey(kind);
    return key ? chrome(key as Parameters<typeof chrome>[0]) : kind;
  };

  return (
    <div
      data-search-results=""
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          onEscape();
        } else if (e.key === "ArrowUp") {
          e.preventDefault();
          onArrowUp();
        }
      }}
    >
      {/* Landmark boundary for screen-reader users (§7) — chrome, not copy. */}
      <h1 className="sr-only">{chrome("search.resultHeading")}</h1>

      {unavailable ? (
        /* M-1 — the artifact could not be fetched: plain-word absence
            ([DR-2026-08-22-numbers-stand-alone] §1), a retry affordance,
            and NEVER the zero-match state, which would print a fabricated
            measured `0` for whatever the reader typed. */
        <div className="flex flex-col items-start gap-g5 py-g8">
          <p className="font-ui text-lg text-text-desc">
            {chrome("search.unavailable")}
          </p>
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              aria-label={chrome("search.retry")}
              className={[
                "flex h-[44px] items-center px-g4 font-ui text-sm text-text-main",
                "transition-[color,box-shadow] duration-[var(--duration-fast)] ease-[var(--ease-state)]",
                "hover:text-accent-foreground hover:[box-shadow:var(--effect-hover-outline)]",
                "outline-none focus-visible:text-accent-foreground focus-visible:[box-shadow:var(--effect-gold-highlight-ring)]",
              ].join(" ")}
            >
              {chrome("search.retry")}
            </button>
          )}
        </div>
      ) : groups.length === 0 ? (
        <p className="py-g8 font-ui text-lg">
          <span className="text-text-emph">
            {chrome.count("search.countTemplate", { count: 0 })}
          </span>{" "}
          <span className="text-text-desc">{query}</span>
        </p>
      ) : (
        <div className="flex flex-col gap-g8">
          {groups.map((group) => (
            <section key={group.kind}>
              {/* A counted number carries no word beyond its label
                  (DR-2026-08-21-drop-chip-words-and-updated-column). An
                  out-of-vocabulary kind labels itself (m-8). */}
              <h2 className="font-flavor text-lg text-text-emph">
                {labelFor(group.kind)}{" "}
                <span className="text-text-main">{group.total}</span>
              </h2>
              <ul className="mt-g4 flex list-none flex-col">
                {(rendered.get(group.kind) ?? []).map(({ row }) => (
                  <li key={row.id}>
                    <a
                      href={row.href}
                      className={[
                        "flex min-h-[44px] items-center px-g4 font-ui text-base",
                        "text-text-main transition-[color,box-shadow] duration-[var(--duration-fast)] ease-[var(--ease-state)]",
                        "hover:text-accent-foreground hover:[box-shadow:var(--effect-hover-outline)]",
                        "outline-none focus-visible:text-accent-foreground focus-visible:[box-shadow:var(--effect-gold-highlight-ring)]",
                      ].join(" ")}
                    >
                      {row.name}
                    </a>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
