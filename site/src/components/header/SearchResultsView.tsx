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
  /** Focus return paths owned by the field's state machine. */
  onArrowUp: () => void;
  onEscape: () => void;
}

interface KindGroup {
  kind: string;
  total: number;
  hits: SearchHit[];
}

/** Groups the FULL hit set by kind (KIND_ORDER order) with full counts. */
function groupHits(hits: SearchHit[]): KindGroup[] {
  const byKind = new Map<string, KindGroup>();
  for (const kind of KIND_ORDER) byKind.set(kind, { kind, total: 0, hits: [] });
  for (const hit of hits) {
    const group = byKind.get(hit.row.kind);
    if (group) {
      group.total += 1;
      group.hits.push(hit);
    }
  }
  return KIND_ORDER.map((k) => byKind.get(k as string)).filter(
    (g): g is KindGroup => !!g && g.total > 0
  );
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
  onArrowUp,
  onEscape,
}: SearchResultsViewProps) {
  const groups = groupHits(hits);
  const rendered = capToRendered(groups);

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

      {groups.length === 0 ? (
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
                  (DR-2026-08-21-drop-chip-words-and-updated-column). */}
              <h2 className="font-flavor text-lg text-text-emph">
                {chrome(KIND_LABEL_KEY[group.kind as keyof typeof KIND_LABEL_KEY])}{" "}
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
