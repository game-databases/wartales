// F5 §9 suite 2 — searchRows.test.ts (executed TWICE: node project AND jsdom
// project — see site/vitest.config.ts).
//
// Spec: docs/spec-f5-search.mdx §4.1–§4.4 + §9 item 2; AC-8. Running this one
// file under both environments and passing the SAME frozen expectation table
// in each is the executable form of DR clause 5: "what matches cannot depend
// on which side answered."
//
// Every expected array below is derived by hand from the pinned §4.2 laws —
// tier assignment (exact / word-edge prefix / substring), total order
// `tier asc → n.length asc → KIND_ORDER → id asc` — over a fixture corpus
// carrying ru/fr/ko/zh names (the §9 requirement). Shuffled inputs must
// produce byte-identical outputs (§4.2 "asserted by test").
//
// BLIND suite: written against the spec alone. The module is imported
// tolerantly (searchRows | default); absence lands RED naming the export
// surface found instead — never vacuous green.

import { describe, expect, it, beforeAll } from "vitest";

type SearchRow = { kind: string; id: string; name: string; href: string };
type SearchHit = { row: SearchRow; tier: 1 | 2 | 3 };

let searchRows: ((rows: readonly SearchRow[], q: string) => SearchHit[]) | null = null;
let minQueryChars: unknown;
let moduleError: Error | null = null;
let exportNames: string[] = [];

beforeAll(async () => {
  try {
    const mod = (await import("../searchRows")) as unknown as Record<string, unknown>;
    exportNames = Object.keys(mod);
    const fn =
      typeof mod.searchRows === "function"
        ? mod.searchRows
        : typeof mod.default === "function"
          ? mod.default
          : undefined;
    if (typeof fn !== "function") {
      moduleError = new Error(
        `src/lib/search/searchRows.ts exports [${exportNames.join(", ")}] but no callable ` +
          `searchRows/default — §4.1 pins "export function searchRows(...)"`
      );
    } else {
      searchRows = fn as typeof searchRows;
      minQueryChars = mod.MIN_QUERY_CHARS ?? mod.minQueryChars;
      if (minQueryChars === undefined) {
        moduleError = new Error(
          `src/lib/search/searchRows.ts exports [${exportNames.join(", ")}] but carries no ` +
            `MIN_QUERY_CHARS constant — §4.1 pins it (DR clause 4, "two characters")`
        );
      }
    }
  } catch (e) {
    moduleError = e as Error;
  }
});

function needMatcher() {
  if (moduleError) throw moduleError;
  return searchRows as NonNullable<typeof searchRows>;
}

// ---- fixture corpus ---------------------------------------------------------

const ROWS: SearchRow[] = [
  { kind: "item", id: "i-iron", name: "Iron Sword", href: "/item/i-iron" },
  { kind: "skill", id: "s-m", name: "Sword", href: "/skill/s-m" },
  { kind: "item", id: "i-z", name: "Sword", href: "/item/i-z" },
  { kind: "class", id: "c-a", name: "Sword", href: "/class/c-a" },
  { kind: "item", id: "i-pass", name: "Password", href: "/item/i-pass" },
  { kind: "item", id: "i-fish", name: "Swordfish", href: "/item/i-fish" },
  { kind: "item", id: "i-sworn", name: "Sworn", href: "/item/i-sworn" },
  { kind: "item", id: "i-ezh", name: "Ёж", href: "/item/i-ezh" },
  { kind: "class", id: "c-epee", name: "Épée", href: "/class/c-epee" },
  { kind: "skill", id: "s-han", name: "한국", href: "/skill/s-han" },
  { kind: "item", id: "i-zh", name: "巨兽长剑", href: "/item/i-zh" },
  {
    kind: "item",
    id: "i-oil",
    name: "<item>OilBrave</item> Concentrate",
    href: "/item/i-oil",
  },
];

// ---- frozen expectations: [query, [[hitId, tier], …]] -----------------------

type Expectation = { q: string; want: [string, number][]; why: string };

const EXPECTATIONS: Expectation[] = [
  {
    q: "sword",
    want: [
      ["i-z", 1], ["s-m", 1], ["c-a", 1],
      ["i-fish", 2], ["i-iron", 2],
      ["i-pass", 3],
    ],
    why: "tier1 exact trio ordered by KIND_ORDER (item<skill<class) despite ids saying otherwise; tier2 word-edge ('swordfish' startsWith len9 beats 'iron sword' post-space len10); tier3 mid-word 'password'",
  },
  {
    q: "swor",
    want: [
      ["i-sworn", 2], ["i-z", 2], ["s-m", 2], ["c-a", 2],
      ["i-fish", 2],
      ["i-iron", 2],
      ["i-pass", 3],
    ],
    why: "no tier1; len-5 tier2 group ordered id-asc INSIDE kind item (i-sworn<i-z) then KIND_ORDER (skill, class), then longer names; 'iron sword' joins tier2 via the post-space edge",
  },
  {
    q: "ЁЖ",
    want: [["i-ezh", 1]],
    why: "ru: uppercase ё folds through NFKD+mark-strip+case to еж — exact match (AC-8 ru leg)",
  },
  {
    q: "epe",
    want: [["c-epee", 2]],
    why: "fr accents fold (Épée→epee): unaccented query prefix-matches at the word edge",
  },
  {
    q: "ㅎㅏ",
    want: [["s-han", 2]],
    why: "ko jamo PREFIX law (r2 N-1): partially-typed compatibility jamo prefix-matches the decomposed syllable — NOT equivalence (AC-8 ko leg)",
  },
  {
    q: "한국",
    want: [["s-han", 1]],
    why: "ko: the full syllabic spelling normalizes identically to its own row → tier1",
  },
  {
    q: "长剑",
    want: [["i-zh", 3]],
    why: "zh: hanzi pass normalization intact; 长剑 inside 巨兽长剑 is a mid-word substring → tier3 (the tier that makes zh work)",
  },
  {
    q: "巨兽长剑",
    want: [["i-zh", 1]],
    why: "zh exact → tier1",
  },
  {
    q: "concentrate",
    want: [["i-oil", 2]],
    why: "markup stripped first (<item>OilBrave</item> Concentrate → 'oilbrave concentrate'); post-space word edge → tier2",
  },
  {
    q: "brave",
    want: [["i-oil", 3]],
    why: "mid-word inside the fused 'oilbrave' → genuine tier3",
  },
];

// Deterministic permutations for the shuffle-stability law.
function permutations<T>(xs: readonly T[]): T[][] {
  const out: T[][] = [];
  out.push([...xs]);
  out.push([...xs].reverse());
  const rotated = [...xs.slice(7), ...xs.slice(0, 7)];
  out.push(rotated);
  // fixed-index swap chain (no RNG anywhere)
  const swapped = [...xs];
  for (let i = 0; i + 3 < swapped.length; i += 4) {
    [swapped[i], swapped[i + 3]] = [swapped[i + 3], swapped[i]];
  }
  out.push(swapped);
  return out;
}

describe("§4.2 matching tiers + total order (frozen table)", () => {
  it("imports callable searchRows (+MIN_QUERY_CHARS) from src/lib/search/searchRows.ts", () => {
    needMatcher();
  });

  for (const exp of EXPECTATIONS) {
    it(`matches "${exp.q}" best-first: ${exp.why}`, () => {
      const got = needMatcher()(ROWS, exp.q);
      expect(
        got.map((h) => [h.row.id, h.tier]),
        exp.why
      ).toEqual(exp.want);
      for (const h of got) {
        expect([1, 2, 3]).toContain(h.tier);
        expect(ROWS).toContain(h.row);
      }
    });
  }

  it("is stable under every deterministic input permutation (§4.2)", () => {
    const m = needMatcher();
    expect(EXPECTATIONS.length).toBeGreaterThan(0);
    for (const exp of EXPECTATIONS) {
      const baseline = m(ROWS, exp.q);
      expect(baseline.length, `fixture must answer "${exp.q}"`).toBeGreaterThan(0);
      for (const perm of permutations(ROWS)) {
        expect(
          m(perm, exp.q).map((h) => [h.row.id, h.tier]),
          `permutation changed the order for "${exp.q}"`
        ).toEqual(baseline.map((h) => [h.row.id, h.tier]));
      }
    }
  });

  it("returns ALL hits (render caps are component business, §4.1)", () => {
    // "sw" word-edge/mid-word-matches exactly 7 of the 12 fixture rows; the
    // matcher must hand back every one of them, uncapped.
    const got = needMatcher()(ROWS, "sw");
    expect(got.map((h) => [h.row.id, h.tier])).toEqual([
      ["i-sworn", 2], ["i-z", 2], ["s-m", 2], ["c-a", 2],
      ["i-fish", 2], ["i-iron", 2],
      ["i-pass", 3],
    ]);
  });
});

describe("§4.1 guards (DR clause 4)", () => {
  it("MIN_QUERY_CHARS is the owner's number: 2", () => {
    needMatcher();
    expect(minQueryChars).toBe(2);
  });

  const BELOW: [string, string][] = [
    ["", "empty query"],
    ["a", "single letter"],
    [" a ", "normalizes to one character"],
    ["   ", "whitespace-only normalizes to nothing"],
    ["剑", "one hanzi is ONE normalized character (recorded §5.2 deviation)"],
  ];
  for (const [q, why] of BELOW) {
    it(`returns [] below the threshold: ${why}`, () => {
      const got = needMatcher()(ROWS, q);
      expect(got, `query ${JSON.stringify(q)} (${why})`).toEqual([]);
    });
  }

  it("returns [] over an empty corpus even above threshold (explicit, not vacuous)", () => {
    expect(needMatcher()([], "sword")).toEqual([]);
  });

  it("never mutates the input array", () => {
    const m = needMatcher();
    const copy = ROWS.map((r) => ({ ...r }));
    m(copy, "sword");
    expect(copy).toEqual(ROWS);
  });
});

describe("DR clause 5 — one matcher, both sides (parity battery)", () => {
  it("declares its environment and runs the full table in it", () => {
    const inWindow = typeof window !== "undefined";
    // Each project must really be its own environment; if the projects config
    // ever collapses into one, one of these branches stops existing.
    if (inWindow) {
      expect(typeof document).toBe("object");
    } else {
      expect(typeof window).toBe("undefined");
    }
    // Whatever the side, the answers are the same frozen arrays.
    const m = needMatcher();
    for (const exp of EXPECTATIONS) {
      expect(m(ROWS, exp.q).map((h) => [h.row.id, h.tier])).toEqual(exp.want);
    }
  });
});
