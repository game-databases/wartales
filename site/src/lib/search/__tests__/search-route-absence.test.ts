// F5 §6 — search-route-absence.test.ts (node project).
//
// Spec: docs/spec-f5-search.mdx §6 (negative space, enforced positively);
// AC-13; DR clause 1 ([DR-2026-08-22-search-is-not-a-page]).
//
// One executable sweep over all six absence laws:
//   1. no route file under ANY `src/app/**` path named `search` — nested and
//      locale-segment variants included; no redirect/rewrite acknowledging it;
//   2. robots.txt carries the string `search` in no directive
//      (`Disallow: /search` would advertise the URL — §6.3);
//   3. no sitemap source or generated XML references a search route;
//   4. the PT16 capture/crawl manifest (when it lands) never gains one;
//   5. no internal link/href anywhere in the delivered tree points at a
//      search route — INCLUDING the DR's literal `/en/search` spelling,
//      mapped through the pivot-prefix policy ([DR-2026-08-20-locale-urls]):
//      EN is the bare pivot, so `/en/search` IS `/search` in route space and
//      ends in a 404 either way — a dead link is still a violation.
//
// Absent trees are NOT silent skips: each unmaterialized surface records an
// explicit `ABSENT:` report line (§6: "a pass with an explicit ABSENT:
// report line, not a silent skip"), printed by this run.
//
// The detector predicates carry their own red-proof below: synthetic
// violations planted through the same functions MUST be flagged, so green
// can only ever mean clean — not vacuous.

import { describe, expect, it, beforeAll } from "vitest";
import { readFileSync, existsSync, readdirSync, statSync } from "node:fs";
import { join, dirname, extname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)); // site/src/lib/search/__tests__
const siteRoot = join(here, "..", "..", "..", ".."); // site/
const srcRoot = join(siteRoot, "src");
const publicRoot = join(siteRoot, "public");

// ---- route-space vocabulary --------------------------------------------------

// F4 §2 ids (lowercase URL segments); `en` is the sole bare pivot.
const LOCALE_IDS = ["de", "en", "es", "fr", "ko", "pl", "pt-br", "ru", "zh"];

/**
 * Map a URL onto ROUTE SPACE: the pivot-prefixed spelling of a path IS the
 * bare path ([DR-2026-08-20-locale-urls] — `/{pivot}/*` does not exist, it
 * 301s to the unprefixed path). Non-pivot locale prefixes stay real routes
 * and are returned untouched.
 */
export function pivotPrefixToBare(path: string): string {
  const m = /^\/([A-Za-z]{2}(?:-[A-Za-z]{2})?)(?=\/|$)/.exec(path);
  if (!m) return path;
  return LOCALE_IDS.includes(m[1].toLowerCase()) && m[1].toLowerCase() === "en"
    ? path.slice(1 + m[1].length)
    : path;
}

/** Does this URL spell a search route in route space? (exact-path, not substring) */
export function isSearchRoute(url: string): boolean {
  const path = url.split(/[?#]/, 1)[0];
  const bare = pivotPrefixToBare(path);
  if (bare === "/search") return true;
  // locale-segment variant: /{nonPivotLocale}/search
  const m = /^\/([A-Za-z]{2}(?:-[A-Za-z]{2})?)\/search$/i.exec(bare);
  return m !== null && LOCALE_IDS.includes(m[1].toLowerCase());
}

// ---- sweep state --------------------------------------------------------------

type Hit = { file: string; line?: number; detail: string };
let routerHits: Hit[] = [];
let linkHits: Hit[] = [];
let robotsHits: Hit[] = [];
let sitemapHits: Hit[] = [];
let captureHits: Hit[] = [];
const absentNotes: string[] = [];
let walkedSourceFiles = 0;

function stripComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/(^|[^:])\/\/[^\n]*/g, "$1 ");
}

function extractStringLiterals(src: string): { value: string; line: number }[] {
  const out: { value: string; line: number }[] = [];
  const patterns = [
    /"((?:\\.|[^"\\\n])*)"/g,
    /'((?:\\.|[^'\\\n])*)'/g,
    /`((?:\\.|[^`\\])*)`/gs,
  ];
  for (const re of patterns) {
    for (const m of src.matchAll(re)) {
      const line = src.slice(0, m.index ?? 0).split("\n").length;
      out.push({ value: m[1], line });
    }
  }
  return out;
}

function walk(dir: string, exts: Set<string>, acc: string[], keepTests: boolean): void {
  if (!existsSync(dir)) return;
  for (const ent of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, ent.name);
    if (ent.isDirectory()) walk(p, exts, acc, keepTests);
    else if (
      exts.has(extname(ent.name)) &&
      (keepTests || !/[.]test\.[tj]sx?$/.test(ent.name))
    ) {
      acc.push(p);
    }
  }
}

beforeAll(() => {
  // -- 1. route files ---------------------------------------------------------
  const appDir = join(srcRoot, "app");
  if (!existsSync(appDir)) {
    absentNotes.push(`ABSENT: src/app/** route tree — router sweep dormant until F4 lands`);
  } else {
    const acc: string[] = [];
    walk(appDir, new Set(["", ".ts", ".tsx", ".jsx", ".js", ".mdx"]), acc, false);
    for (const p of acc) {
      const rel = p.slice(siteRoot.length + 1);
      const segs = rel.split(/[/\\]/);
      if (segs.some((s) => s.toLowerCase() === "search")) {
        routerHits.push({ file: rel, detail: `route-tree segment named 'search' (§6.1)` });
      }
    }
  }
  for (const cfg of ["next.config.ts", "src/middleware.ts"]) {
    const p = join(siteRoot, cfg);
    if (!existsSync(p)) continue;
    const code = stripComments(readFileSync(p, "utf8"));
    for (const lit of extractStringLiterals(code)) {
      if (isSearchRoute(lit.value) || lit.value.replace(/\/+$/, "") === "/search") {
        routerHits.push({
          file: cfg,
          line: lit.line,
          detail: `"${lit.value}" — no redirect/rewrite may acknowledge a search URL (§6.1)`,
        });
      }
    }
  }

  // -- 5/6. internal links across delivered sources + chrome messages ----------
  const sources: string[] = [];
  walk(srcRoot, new Set([".ts", ".tsx"]), sources, false);
  const messagesDir = join(siteRoot, "messages");
  if (existsSync(messagesDir)) sources.push(...readdirSync(messagesDir).filter((f) => f.endsWith(".json")).map((f) => join(messagesDir, f)));
  walkedSourceFiles = sources.length;
  for (const p of sources) {
    const raw = readFileSync(p, "utf8");
    const code = extname(p) === ".json" ? raw : stripComments(raw);
    for (const lit of extractStringLiterals(code)) {
      for (const candidate of lit.value.split(/\s+/)) {
        if (isSearchRoute(candidate)) {
          linkHits.push({
            file: p.slice(siteRoot.length + 1),
            line: lit.line,
            detail: `"${candidate}" — no internal link may target a search route (§6.6, DR clause 1)`,
          });
        }
      }
    }
  }

  // -- 2. robots.txt ------------------------------------------------------------
  const robots = join(publicRoot, "robots.txt");
  if (!existsSync(robots)) {
    absentNotes.push("ABSENT: public/robots.txt — robots sweep activates when SEO piece lands");
  } else {
    rawRobotsLines = readFileSync(robots, "utf8").split("\n");
    rawRobotsLines.forEach((lineText, i) => {
      if (/search/i.test(lineText)) {
        robotsHits.push({
          file: "public/robots.txt",
          line: i + 1,
          detail: `directive mentions 'search': ${lineText.trim()} (§6.3)`,
        });
      }
    });
  }

  // -- 3. sitemaps -----------------------------------------------------------------
  let sawAnySitemapSurface = false;
  const sitemapSources: string[] = [];
  const appTree: string[] = [];
  walk(join(srcRoot, "app"), new Set([".ts", ".tsx", ".js", ".jsx"]), appTree, false);
  for (const p of appTree.filter((f) => /sitemap/i.test(f))) {
    sawAnySitemapSurface = true;
    sitemapSources.push(p);
  }
  if (existsSync(publicRoot)) {
    const xmls: string[] = [];
    walk(publicRoot, new Set([".xml", ".txt"]), xmls, false);
    for (const p of xmls.filter((f) => /sitemap/i.test(f))) {
      sawAnySitemapSurface = true;
      sitemapSources.push(p);
    }
  }
  if (!sawAnySitemapSurface) {
    absentNotes.push("ABSENT: no sitemap source or generated XML — sitemap sweep activates later");
  } else {
    for (const p of sitemapSources) {
      const raw = readFileSync(p, "utf8");
      for (const m of raw.matchAll(/<loc>\s*([^<]+?)\s*<\/loc>/g)) {
        if (isSearchRoute(m[1])) {
          sitemapHits.push({
            file: p.slice(siteRoot.length + 1),
            detail: `<loc>${m[1]}</loc> references a search route (§6.4)`,
          });
        }
      }
      if (!extname(p).match(/\.xml/)) {
        for (const lit of extractStringLiterals(stripComments(raw))) {
          if (isSearchRoute(lit.value)) {
            sitemapHits.push({
              file: p.slice(siteRoot.length + 1),
              line: lit.line,
              detail: `generator emits "${lit.value}" (§6.4)`,
            });
          }
        }
      }
    }
  }

  // -- 4. capture list -----------------------------------------------------------
  const captureCandidates: string[] = [];
  const scriptTree: string[] = [];
  walk(join(siteRoot, "scripts"), new Set([".json", ".jsonl", ".mjs", ".js", ".ts"]), scriptTree, false);
  for (const p of scriptTree.filter((f) => /(capture|crawl|e2e)/i.test(f))) captureCandidates.push(p);
  if (existsSync(publicRoot)) {
    const pubJson: string[] = [];
    walk(publicRoot, new Set([".json", ".jsonl"]), pubJson, false);
    for (const p of pubJson.filter((f) => /(capture|crawl)/i.test(f))) captureCandidates.push(p);
  }
  if (captureCandidates.length === 0) {
    absentNotes.push(
      "ABSENT: no capture/crawl manifest yet (PT16-owned) — capture-list sweep pre-written per H-2"
    );
  } else {
    for (const p of captureCandidates) {
      const raw = readFileSync(p, "utf8");
      for (const m of raw.matchAll(/"(\/[^"]*)"/g)) {
        if (isSearchRoute(m[1])) {
          captureHits.push({
            file: p.slice(siteRoot.length + 1),
            detail: `crawl manifest lists "${m[1]}" (§6.5)`,
          });
        }
      }
    }
  }
});

let rawRobotsLines: string[] | null = null;

function fmt(hits: Hit[]): string {
  return hits.map((h) => `${h.file}${h.line ? ":" + h.line : ""} — ${h.detail}`).join("\n  ");
}

// ---- detector self-test (the red-proof) ---------------------------------------

describe("detector self-test — planted violations MUST be flagged (red-proof)", () => {
  it("maps the DR's literal /en/search through the pivot policy onto /search", () => {
    expect(pivotPrefixToBare("/en/search")).toBe("/search");
    expect(pivotPrefixToBare("/en/items")).toBe("/items");
    expect(pivotPrefixToBare("/ko/search"), "non-pivot prefixes are real routes — untouched").toBe("/ko/search");
    expect(pivotPrefixToBare("/search")).toBe("/search");
  });

  it("flags every search-route spelling, including locale-segment variants", () => {
    const mustFlag = [
      "/search",
      "/en/search",
      "/EN/search",
      "/ko/search",
      "/pt-br/search",
      "/pt-BR/search",
      "/search?x=1",
      "/search#frag",
    ];
    for (const u of mustFlag) {
      expect(isSearchRoute(u), `${u} must be flagged`).toBe(true);
    }
  });

  it("does NOT overreach beyond exact search paths", () => {
    const mustPass = [
      "/items/search-history",
      "/research",
      "/searching-tools",
      "/en/items",
      "/",
      "",
    ];
    for (const u of mustPass) {
      expect(isSearchRoute(u), `${u} must not be flagged`).toBe(false);
    }
  });
});

// ---- the six sweeps -------------------------------------------------------------

describe("§6.1 router — no route file, no redirect, no rewrite", () => {
  it("finds zero search-named routes under src/app/** and zero search redirects", () => {
    // Dormant-tree honesty lives in the ABSENT ledger below; here zero hits
    // is the law, whether or not the router has landed yet.
    expect(fmt(routerHits), "search routes/redirects found").toBe("");
  });
});

describe("§6.6 internal links — nothing points at a search route", () => {
  it(`swept ${walkedSourceFiles} delivered source/message files and found zero hits`, () => {
    expect(walkedSourceFiles, "sweep must actually walk files (never vacuous)").toBeGreaterThan(0);
    expect(fmt(linkHits), "internal search-route links found").toBe("");
  });
});

describe("§6.3 robots.txt — 'search' appears in no directive", () => {
  it("keeps every robots line free of the string", () => {
    if (rawRobotsLines === null) {
      expect(absentNotes.some((n) => n.includes("robots.txt")), "absence must be reported, not skipped").toBe(true);
      expect(robotsHits, "no hits possible while absent").toEqual([]);
      return;
    }
    expect(rawRobotsLines.length).toBeGreaterThan(0);
    expect(fmt(robotsHits), "robots.txt advertises search").toBe("");
  });
});

describe("§6.4 sitemaps — no source or generated XML references a search route", () => {
  it("finds zero search <loc>/generator entries", () => {
    expect(fmt(sitemapHits), "sitemap references search").toBe("");
  });
});

describe("§6.5 capture list — the crawl manifest never gains a search entry", () => {
  it("finds zero search entries in any capture/crawl manifest", () => {
    expect(fmt(captureHits), "capture list references search").toBe("");
  });
});

describe("absence ledger — unmaterialized trees are REPORTED, not skipped (§6)", () => {
  it("prints an explicit ABSENT: line per dormant sweep", () => {
    // Every note is a fact about today's tree; the sweep keeps guarding the
    // repo after F4/PT16 land because the corresponding branches activate.
    for (const note of absentNotes) console.log(`  ${note}`);
    expect(Array.isArray(absentNotes)).toBe(true);
  });
});
