// F5 §9 suite 1 — normalize.test.ts (node project).
//
// Spec: docs/spec-f5-search.mdx §4.3 + §9 item 1; AC-9 (r2) + AC-11.
// Table-driven over the §4.3 eight-step pipeline. Every expected value below
// was EXECUTED against the spec's own pipeline verbatim before freezing
// (r2 discipline — "frozen to what the §4.3 pipeline actually yields"), and
// the ko jamo law is the r2 re-freeze: the r1 full-equivalence case was FALSE
// under this pipeline and is DELETED — what holds is (a) syllables decompose
// WITH jongseong finals, (b) compatibility jamo fold to choseong/jungseong
// only, (c) the two are NOT equal, (d) the shared leading-jamo PREFIX
// property `normalize("한국").startsWith(normalize("ㅎㅏ"))` — all tier-2
// matching needs no more than that.
//
// This file also carries the AC-11 environment-purity guard: a grep over the
// matcher sources for window|document|navigator|localStorage|fetch|node:
//
// BLIND suite: written against the spec alone. The module is imported
// tolerantly (normalizeName | normalize | default); a missing or differently-
// shaped module lands RED naming what was looked for — never vacuous green.

import { describe, expect, it, beforeAll } from "vitest";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)); // site/src/lib/search/__tests__
const searchDir = join(here, "..");

type NormalizeFn = (s: string) => string;

let normalizeName: NormalizeFn | null = null;
let moduleError: Error | null = null;
let exportNames: string[] = [];

beforeAll(async () => {
  try {
    const mod = (await import("../normalize")) as unknown as Record<string, unknown>;
    exportNames = Object.keys(mod);
    const candidates = ["normalizeName", "normalize", "default"];
    for (const name of candidates) {
      const v = mod[name];
      if (typeof v === "function") {
        normalizeName = (v as NormalizeFn).bind(mod);
        break;
      }
      // default-export namespace shape: { normalizeName }
      if (v && typeof v === "object") {
        const inner = (v as Record<string, unknown>)["normalizeName"];
        if (typeof inner === "function") {
          normalizeName = inner as NormalizeFn;
          break;
        }
      }
    }
    if (!normalizeName) {
      moduleError = new Error(
        `src/lib/search/normalize.ts exports [${exportNames.join(", ")}] but none is a ` +
          `callable — wanted "normalizeName" (§4.3 pins the name), "normalize", or a default`
      );
    }
  } catch (e) {
    moduleError = e as Error;
  }
});

function needNorm(): NormalizeFn {
  if (moduleError) throw moduleError;
  return normalizeName as NormalizeFn;
}

// ---- the frozen table (§9 item 1; every row executed at write time) --------

// Codepoint-exact literals for the ko law — written \u-escaped so the file's
// encoding can never silently rewrite a jamo (spec r2 N-1: "literals written
// codepoint-exact").
const HAN_SYLLABLES = "한국"; // 한국 U+D55C U+AD6D
const JAMO_FULL = "ㅎㅏㄴㄱㅜㄱ"; // ㅎㅏㄴㄱㅜㄱ
const JAMO_PARTIAL = "ㅎㅏ"; // ㅎㅏ
const HAN_NORM = "한국"; // choseong/jung/jong conjoining
const JAMO_FULL_NORM = "하ᄂ구ᄀ"; // compat → choseong/jungseong ONLY

type Row = { input: string; expected: string; why: string };

const TABLE: Row[] = [
  { input: "Ёж", expected: "еж", why: "ru: ё NFKD-decomposes to е + U+0308, mark-strip folds it (§4.3 ru bullet)" },
  { input: "Épée", expected: "epee", why: "fr accents fold through NFKD + mark-strip (§4.3 fr/de/es bullet)" },
  { input: "Włóczęga", expected: "wloczega", why: "pl explicit step-7 fold — U+0142 has NO Unicode decomposition (r1 M3)" },
  { input: "Łódź", expected: "lodz", why: "pl explicit fold incl. capital Ł (§9.1)" },
  { input: "<b>X</b>", expected: "x", why: "rich-text tag strip (§9.1)" },
  {
    input: "<item>OilBrave</item> Concentrate",
    expected: "oilbrave concentrate",
    why: "the measured oil-concentrate family: tags → space keeps words from fusing (§4.3 step 1)",
  },
  { input: "Leiche von [NAME]", expected: "leiche von", why: "bracket macro strip; trailing space trimmed (§9.1, AllyCorpse de)" },
  { input: "[Guard]X", expected: "x", why: "markup-wrapped macro dies; replacement with space then trim (§4.3 steps 1–2)" },
  { input: "<bad>::value::</bad> X", expected: "x", why: "::color:: span strip (§9.1)" },
  { input: HAN_SYLLABLES, expected: HAN_NORM, why: "ko: syllables decompose WITH jongseong finals (r2 N-1)" },
  { input: JAMO_FULL, expected: JAMO_FULL_NORM, why: "ko: compatibility jamo fold to choseong/jungseong only, never jongseong (r2 N-1)" },
  { input: "长剑", expected: "长剑", why: "zh hanzi pass NFKD/NFD unchanged (§4.3 zh bullet)" },
  { input: "ＸＹ", expected: "xy", why: "full-width compatibility fold (§4.3 zh bullet / step 4)" },
  { input: "A   B\tC", expected: "a b c", why: "whitespace collapse to single spaces (step 8)" },
];

describe("§4.3 normalizeName — the frozen table (AC-9)", () => {
  it("imports a callable normalizeName from src/lib/search/normalize.ts", () => {
    needNorm();
    expect(typeof needNorm()).toBe("function");
  });

  it("yields exactly the executed outputs for every §9.1 case", () => {
    const f = needNorm();
    expect(TABLE.length, "table must not be empty (poisoned empty set)").toBeGreaterThan(0);
    for (const row of TABLE) {
      expect(f(row.input), `${row.why} — input ${JSON.stringify(row.input)}`).toBe(row.expected);
    }
  });

  it("folds the recorded single-locale facts (ё→е, ß NOT folded)", () => {
    const f = needNorm();
    expect(f("ё"), "ё alone folds to е").toBe("е");
    // Recorded accepted gap (§4.3): ß does NOT fold to ss — asserted as the
    // gap itself so a silent "fix" is a conscious spec change, not drift.
    expect(f("ß Straße"), "ß stays verbatim; case folds around it (gap H-5)").toBe("ß straße");
  });

  it("keeps the ko jamo PREFIX law and REJECTS full equivalence (AC-9 r2)", () => {
    const f = needNorm();
    // (a)/(b)/(c) already table-pinned; here the two laws of record:
    expect(f(HAN_SYLLABLES) === f(JAMO_FULL), "full equivalence is FALSE under this pipeline — asserting it would re-introduce the deleted r1 case").toBe(false);
    expect(f(HAN_SYLLABLES).startsWith(f(JAMO_PARTIAL)), "a partially-typed jamo query prefix-matches the decomposed syllable (tier-2 fuel)").toBe(true);
  });
});

describe("§4.3 invariants over the whole table", () => {
  it("is idempotent: f(f(s)) === f(s) for every input incl. markup cases (§9.1)", () => {
    const f = needNorm();
    const inputs = TABLE.map((r) => r.input);
    expect(inputs.length).toBe(TABLE.length);
    for (const s of inputs) {
      expect(f(f(s)), `idempotence at ${JSON.stringify(s)}`).toBe(f(s));
    }
  });

  it("never emits uppercase, leading/trailing whitespace, or markup residue", () => {
    const f = needNorm();
    for (const s of TABLE.map((r) => r.input)) {
      const out = f(s);
      expect(out, `no residual < > at ${JSON.stringify(s)}`).not.toMatch(/[<>]/);
      expect(out === out.toLowerCase(), `case-folded at ${JSON.stringify(s)}`).toBe(true);
      expect(out, `trimmed at ${JSON.stringify(s)}`).toBe(out.trim());
    }
  });
});

// ---------------------------------------------------------------------------
// AC-11 — environment purity: the matcher modules import identically on the
// server and in the browser (DR clause 5), so their SOURCES may touch nothing
// environmental. A source grep, not an import trick: the ban is lexical.
// ---------------------------------------------------------------------------

describe("AC-11 — matcher environment purity", () => {
  const BANNED =
    /\bwindow\b|\bdocument\b|\bnavigator\b|\blocalStorage\b|\bfetch\b|node:/;

  function sourceOf(rel: string): string {
    const p = join(searchDir, rel);
    let raw: string;
    try {
      raw = readFileSync(p, "utf8");
    } catch (e) {
      throw new Error(
        `AC-11 could not read src/lib/search/${rel} — the module must exist for the ` +
          `purity sweep (${(e as Error).message})`
      );
    }
    // Strip comments and string literals first: prose MENTIONING fetch must
    // not fail the sweep, only real usage (m-4 discipline from F4 tests).
    return raw
      .replace(/\/\*[\s\S]*?\*\//g, " ")
      .replace(/(^|[^:])\/\/[^\n]*/g, "$1 ")
      .replace(/"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`/g, '""');
  }

  for (const rel of ["normalize.ts", "searchRows.ts"]) {
    it(`src/lib/search/${rel} touches nothing environmental`, () => {
      const code = sourceOf(rel);
      const hit = BANNED.exec(code);
      expect(
        hit,
        `\`${hit?.[0]}\` found in ${rel} — matcher modules are pure TypeScript ` +
          `(§4.1: no window/document/navigator/localStorage/fetch/node builtins/React)`
      ).toBeNull();
    });
  }
});
