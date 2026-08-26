/**
 * The one matching function, both sides (spec-f5-search §4; DR clause 5:
 * what matches cannot depend on which side answered). Pure TypeScript, no
 * runtime deps; imports touch nothing environmental (AC-11 guard) —
 * server code and the client island import THIS file identically.
 */
import { normalizeName } from "./normalize";

export interface SearchRow {
  kind: string;
  id: string;
  name: string;
  href: string;
}

export interface SearchHit {
  row: SearchRow;
  tier: 1 | 2 | 3;
}

/** DR clause 4 — two characters, the owner's number. Not derived anywhere. */
export const MIN_QUERY_CHARS = 2;

/**
 * Tie-break + grouping order. NOT an independent literal: manifest.kinds
 * publishes SEARCHABLE_KINDS from the emitter and the artifact suite
 * asserts KIND_ORDER deep-equals it each run — the honesty chain
 * wave_kinds → emitter → manifest.kinds → KIND_ORDER is mechanical at
 * every hop (spec-f5 §4.1).
 */
export const KIND_ORDER = ["item", "skill", "class"] as const;

const KIND_INDEX: ReadonlyMap<string, number> = new Map(
  KIND_ORDER.map((k, i) => [k as string, i])
);

/**
 * Returns ALL hits, best-first; rendering caps are the component's
 * business (§5.4). Empty for anything shorter than MIN_QUERY_CHARS after
 * normalization — defense in depth; the component never calls below the
 * threshold anyway (§4.1).
 *
 * Total order over hits: tier asc, then normalized-name length asc
 * (shorter = more specific), then kind in KIND_ORDER order, then id
 * lexicographic — a total order, so shuffling the input array cannot
 * change the output order.
 */
export function searchRows(
  rows: readonly SearchRow[],
  query: string
): SearchHit[] {
  const q = normalizeName(query);
  if (q.length < MIN_QUERY_CHARS) return [];

  const hits: { row: SearchRow; tier: 1 | 2 | 3; len: number }[] = [];
  for (const row of rows) {
    const n = normalizeName(row.name);
    let tier: 1 | 2 | 3 | null = null;
    if (n === q) {
      tier = 1;
    } else if (wordEdgeMatch(n, q)) {
      tier = 2;
    } else if (n.includes(q)) {
      tier = 3;
    }
    if (tier !== null) hits.push({ row, tier, len: n.length });
  }

  return hits
    .sort(
      (a, b) =>
        a.tier - b.tier ||
        a.len - b.len ||
        (KIND_INDEX.get(a.row.kind) ?? KIND_ORDER.length) -
          (KIND_INDEX.get(b.row.kind) ?? KIND_ORDER.length) ||
        (a.row.id < b.row.id ? -1 : a.row.id > b.row.id ? 1 : 0)
    )
    .map((h) => ({ row: h.row, tier: h.tier }));
}

/**
 * Tier 2 — prefix at a word edge: `n` starts with `q`, or some occurrence
 * of `q` at position i > 0 sits right after a space (post-normalization
 * the only separator IS the space). Every occurrence is checked so a
 * first-hit-at-position-0 cannot mask a later word-edge hit.
 */
function wordEdgeMatch(n: string, q: string): boolean {
  if (n.startsWith(q)) return true;
  let i = n.indexOf(q);
  while (i > 0) {
    if (n[i - 1] === " ") return true;
    i = n.indexOf(q, i + 1);
  }
  return false;
}
