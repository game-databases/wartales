// F5 §9 suite 4 — search-artifact.test.ts (node project).
//
// Spec: docs/spec-f5-search.mdx §2 (frozen anchors), §3 (artifact contract),
// §3.3 (href route table, derived-from-F2-§6), §9 item 4; AC-3/AC-4/AC-5.
//
// Reads the EMITTED artifact tree `site/public/data/search/*.json` +
// manifest.json and holds it against:
//   - the frozen §2 anchors: 3,219 rows per locale, 278 class rows, nine
//     official client-code files (`pt-BR` verbatim — DATA-plane naming),
//     kinds == SEARCHABLE_KINDS;
//   - shape exactness: row keys `{kind,id,name,href}` IN THAT ORDER
//     (never sort_keys order — §3.2/r1 m7), top level
//     `schema,locale,buildId,rows`, names non-empty;
//   - the segment vocabulary: pivot EN composes bare, `pt-BR`-keyed file
//     carries `/pt-br/…` hrefs (URL-plane segment, NEVER `/pt-BR/…`), every
//     other locale `/{code}/…`; no href ever contains `/search`;
//   - determinism-adjacent serialization laws: UTF-8, ensure_ascii=False
//     (raw multibyte), LF line endings, fixed key order;
//   - FULL membership bijection against extracted/relinks/locale_availability.jsonl
//     (AC-3: `L ∈ namedLocales ⇔` exactly one row in L.json, both directions,
//     full scan — not sampled);
//   - the TS-side honesty hop: KIND_ORDER deep-equals manifest.kinds (§4.1:
//     "NOT an independent literal").
//
// RED-FIRST discipline: an absent artifact tree FAILS loudly (naming what was
// looked for); empty-set loops are poisoned — every iteration sits behind an
// explicit non-empty/count assertion.

import { describe, expect, it, beforeAll } from "vitest";
import { readFileSync, readdirSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)); // site/src/lib/search/__tests__
const siteRoot = join(here, "..", "..", "..", ".."); // site/
const packRoot = join(siteRoot, "..");
const ARTIFACT_DIR = join(siteRoot, "public", "data", "search");
const AVAIL_PATH = join(packRoot, "extracted", "relinks", "locale_availability.jsonl");

// ---- the frozen vocabulary (§2/§3) ------------------------------------------

const OFFICIAL = ["en", "fr", "de", "es", "pl", "pt-BR", "ru", "ko", "zh"]; // client codes
const SEARCHABLE_KINDS = ["item", "skill", "class"];
const FROZEN_TOTAL = 3219; // §2: named rows per locale — exact, no band
const FROZEN_CLASS = 278; // §2: class facet per locale
const SCHEMA = "wartales/search-index@1";
// URL segment per client code (§3.3 table): pivot en carries none; pt-BR's
// F4 routing segment is lowercase `pt-br`; identity for the rest.
const SEGMENT: Record<string, string> = {
  en: "", // pivot — bare paths ([DR-2026-08-20-locale-urls])
  "pt-BR": "pt-br",
  de: "de", es: "es", fr: "fr", ko: "ko", pl: "pl", ru: "ru", zh: "zh",
};

type Row = { kind: string; id: string; name: string; href: string };
type LocaleFile = {
  schema: string;
  locale: string;
  buildId: string;
  rows: Row[];
};
type Manifest = {
  schema: string;
  buildId: string;
  locales: string[];
  kinds: string[];
  rowCount: Record<string, number>;
};
type AvailRow = {
  kind: string;
  id: string;
  availableLocales: string[];
  namedLocales: string[];
  fields: Record<string, { name?: boolean } & Record<string, unknown>>;
};

let manifest: Manifest | null = null;
let files: Map<string, LocaleFile> = new Map();
let rawText: Map<string, string> = new Map();
let availRows: AvailRow[] | null = null;
let setupError: Error | null = null;

function readJson(path: string): unknown {
  return JSON.parse(readFileSync(path, "utf8"));
}

beforeAll(() => {
  try {
    if (!existsSync(AVAIL_PATH)) {
      throw new Error(`availability relink missing: ${AVAIL_PATH} (§2 membership source)`);
    }
    availRows = (readFileSync(AVAIL_PATH, "utf8").trim().split("\n")).map((l) =>
      JSON.parse(l) as AvailRow
    );

    if (!existsSync(ARTIFACT_DIR)) {
      throw new Error(
        `artifact directory absent: ${ARTIFACT_DIR.replace(siteRoot, "site")} — run ` +
          `\`pwsh ./run_all.ps1 emit\` (spec §3.1); until then this suite stays RED by design`
      );
    }
    const found = readdirSync(ARTIFACT_DIR).filter((f) => f.endsWith(".json"));
    expect(
      found.length,
      `expected exactly ten JSON files under site/public/data/search, found [${found.join(", ")}]`
    ).toBe(10);
    for (const code of OFFICIAL) {
      const p = join(ARTIFACT_DIR, `${code}.json`);
      if (!existsSync(p)) {
        throw new Error(`missing locale file ${code}.json — the nine official client codes`);
      }
      rawText.set(code, readFileSync(p, "utf8"));
      const parsed = readJson(p) as LocaleFile;
      files.set(code, parsed);
    }
    const mPath = join(ARTIFACT_DIR, "manifest.json");
    if (!existsSync(mPath)) throw new Error("missing manifest.json");
    rawText.set("manifest.json", readFileSync(mPath, "utf8"));
    manifest = readJson(mPath) as Manifest;
  } catch (e) {
    setupError = e as Error;
  }
});

function needManifest(): Manifest {
  if (setupError && !manifest) throw setupError;
  return manifest as Manifest;
}
function needFiles(): Map<string, LocaleFile> {
  if (setupError && files.size === 0) throw setupError;
  return files;
}
function needAvail(): AvailRow[] {
  if (!availRows || availRows.length === 0) {
    throw new Error(
      `availability relink unusable (${AVAIL_PATH}): ` +
        `${availRows ? "empty" : setupError?.message ?? "not loaded"}`
    );
  }
  return availRows;
}

const kindIndex = (k: string) => {
  const i = SEARCHABLE_KINDS.indexOf(k);
  expect(i, `unknown kind "${k}" in artifact`).toBeGreaterThanOrEqual(0);
  return i;
};
const sortKey = (r: Row): [number, string] => [kindIndex(r.kind), r.id];

/** Expected href for a row, per the §3.3 route table. */
function expectedHref(localeCode: string, r: { kind: string; id: string }): string {
  const seg = SEGMENT[localeCode];
  return seg ? `/${seg}/${r.kind}/${r.id}` : `/${r.kind}/${r.id}`;
}

describe("§3.2 artifact tree — presence before any loop can go vacuous", () => {
  it("holds exactly the nine official client-code files plus manifest.json", () => {
    needFiles();
    needManifest();
    const names = [...files.keys()].sort();
    expect(names).toEqual([...OFFICIAL].sort());
  });
});

describe("§3.2 manifest contract", () => {
  it("declares the published schema and a present buildId (the only freshness stamp)", () => {
    const m = needManifest();
    expect(m.schema).toBe(SCHEMA);
    expect(typeof m.buildId).toBe("string");
    expect(m.buildId.length, "buildId must be non-empty").toBeGreaterThan(0);
  });

  it("publishes locales == the nine official client codes, kinds == SEARCHABLE_KINDS", () => {
    const m = needManifest();
    expect(m.locales).toEqual(OFFICIAL);
    expect(m.kinds).toEqual(SEARCHABLE_KINDS);
  });

  it("rowCount[L] === 3219 for every L (frozen §2 anchor — exact, no band)", () => {
    const m = needManifest();
    expect(Object.keys(m.rowCount).sort()).toEqual([...OFFICIAL].sort());
    for (const code of OFFICIAL) {
      expect(
        m.rowCount[code],
        `rowCount[${code}] must equal the frozen 3,219 (§2 recount-and-refreeze law)`
      ).toBe(FROZEN_TOTAL);
    }
  });
});

describe("§3.2/§3.4 per-locale file contract", () => {
  it("carries fixed key order at top level and per row (never sort_keys, r1 m7)", () => {
    const fs2 = needFiles();
    for (const code of OFFICIAL) {
      const parsed = JSON.parse(rawText.get(code) as string) as Record<string, unknown>;
      expect(
        Object.keys(parsed),
        `${code}.json top-level key order`
      ).toEqual(["schema", "locale", "buildId", "rows"]);
      const firstRow = Object.keys((parsed.rows as Row[])[0]);
      expect(firstRow, `${code}.json row key order`).toEqual(["kind", "id", "name", "href"]);
    }
    const mf = JSON.parse(rawText.get("manifest.json") as string) as Record<string, unknown>;
    expect(Object.keys(mf), "manifest.json key order").toEqual([
      "schema",
      "buildId",
      "locales",
      "kinds",
      "rowCount",
    ]);
  });

  it("agrees with itself: schema/locale/buildId/rows.length === rowCount[L] === 3219", () => {
    const m = needManifest();
    const fs2 = needFiles();
    for (const code of OFFICIAL) {
      const f = fs2.get(code) as LocaleFile;
      expect(f.schema, `${code}.json schema`).toBe(SCHEMA);
      expect(f.locale, `${code}.json locale field must equal its filename (client code)`).toBe(code);
      expect(f.buildId, `${code}.json buildId`).toBe(m.buildId);
      expect(f.rows.length, `${code}.json rows.length`).toBe(FROZEN_TOTAL);
      expect(f.rows.length).toBe(m.rowCount[code]);
    }
  });

  it("rows carry exactly {kind,id,name,name→href}, non-empty names, searchable kinds only", () => {
    const fs2 = needFiles();
    let seen = 0;
    for (const code of OFFICIAL) {
      const f = fs2.get(code) as LocaleFile;
      expect(f.rows.length).toBeGreaterThan(0);
      for (const r of f.rows) {
        expect(Object.keys(r)).toEqual(["kind", "id", "name", "href"]);
        expect(SEARCHABLE_KINDS).toContain(r.kind);
        expect(r.id.length, `${code}: id non-empty`).toBeGreaterThan(0);
        expect(typeof r.name).toBe("string");
        expect(r.name.length, `${code}:${r.id} name non-empty`).toBeGreaterThan(0);
        seen++;
      }
    }
    expect(seen, "all nine corpora walked (poison against empty loops)").toBe(FROZEN_TOTAL * 9);
  });

  it("sorts rows by (SEARCHABLE_KINDS index, id) — §3.4 determinism law", () => {
    const fs2 = needFiles();
    for (const code of OFFICIAL) {
      const f = fs2.get(code) as LocaleFile;
      const keys = f.rows.map(sortKey);
      const sorted = [...keys].sort((a, b) => a[0] - b[0] || (a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0));
      expect(keys, `${code}.json row order`).toEqual(sorted);
    }
  });

  it("carries ONE identical sorted (kind,id) list across all nine files (AC-4)", () => {
    const fs2 = needFiles();
    // Canonicalize BOTH sides identically before comparing — file order is
    // §3.4's (kindIndex,id); the identity check here is set-shaped.
    const canon = (rows: Row[]): [string, string][] =>
      rows
        .map((r) => [r.kind, r.id] as [string, string])
        .sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0));
    const reference = canon((fs2.get("en") as LocaleFile).rows);
    expect(reference.length).toBe(FROZEN_TOTAL);
    for (const code of OFFICIAL.slice(1)) {
      expect(
        canon((fs2.get(code) as LocaleFile).rows),
        `${code}.json membership diverges from en.json`
      ).toEqual(reference);
    }
  });

  it("contributes exactly 278 class rows per locale, equal facet sizes across locales (AC-4)", () => {
    const fs2 = needFiles();
    const perKind: Record<string, number[]> = {};
    for (const code of OFFICIAL) {
      const f = fs2.get(code) as LocaleFile;
      const counts: Record<string, number> = {};
      for (const r of f.rows) counts[r.kind] = (counts[r.kind] ?? 0) + 1;
      for (const k of SEARCHABLE_KINDS) {
        perKind[k] = perKind[k] ?? [];
        perKind[k].push(counts[k] ?? 0);
      }
    }
    for (const k of SEARCHABLE_KINDS) {
      expect(new Set(perKind[k]).size, `facet '${k}' equal across locales`).toBe(1);
    }
    expect(perKind.class[0], "class facet is the frozen 278 (§2)").toBe(FROZEN_CLASS);
  });
});

describe("§3.3 href route table (derived-from-F2-§6)", () => {
  it("composes every href from its locale's URL segment — pivot bare, pt-BR lowercase", () => {
    const fs2 = needFiles();
    let checked = 0;
    for (const code of OFFICIAL) {
      const f = fs2.get(code) as LocaleFile;
      for (const r of f.rows) {
        expect(r.href, `${code}:${r.id}`).toBe(expectedHref(code, r));
        checked++;
      }
    }
    expect(checked).toBe(FROZEN_TOTAL * 9);
  });

  it("never leaks the client code where the segment differs (no '/pt-BR/' anywhere)", () => {
    const fs2 = needFiles();
    for (const code of OFFICIAL) {
      const f = fs2.get(code) as LocaleFile;
      for (const r of f.rows) {
        expect(r.href.includes("pt-BR"), `${code}:${r.id} → ${r.href}`).toBe(false);
      }
    }
  });

  it("contains no '/search' href — DR clause 1 reaches the data plane", () => {
    const fs2 = needFiles();
    for (const code of OFFICIAL) {
      const f = fs2.get(code) as LocaleFile;
      for (const r of f.rows) {
        expect(r.href.includes("/search"), `${code}:${r.id} → ${r.href}`).toBe(false);
        expect(r.href.startsWith("/"), `${code}:${r.id} internal`).toBe(true);
      }
    }
  });
});

describe("§3.4 serialization laws visible in the bytes", () => {
  it("writes UTF-8 with raw multibyte content (ensure_ascii=False) and LF endings", () => {
    needFiles();
    for (const code of OFFICIAL) {
      const text = rawText.get(code) as string;
      expect(text.includes("\r"), `${code}.json must use LF`).toBe(false);
      expect(/\\u[0-9a-fA-F]{4}/.test(text), `${code}.json must not \\u-escape`).toBe(false);
    }
    // Non-Latin scripts guarantee raw multibyte; their absence would mean an
    // ascii-escaped emitter snuck in.
    for (const code of ["de", "pl", "ru", "ko", "zh"]) {
      const bytes = Buffer.from(rawText.get(code) as string, "utf8");
      expect(
        bytes.length,
        `${code}.json must be larger byte-wise than char-wise when raw UTF-8`
      ).toBeGreaterThan((rawText.get(code) as string).length);
    }
  });

  it("emits nothing but the ten contracted files into the artifact directory", () => {
    needManifest();
    const found = readdirSync(ARTIFACT_DIR).sort();
    expect(found).toEqual([...OFFICIAL.map((c) => `${c}.json`), "manifest.json"].sort());
  });
});

describe("§4.1 honesty chain — TS side", () => {
  it("KIND_ORDER deep-equals manifest.kinds (no transcribed mirror, r1 m4)", async () => {
    const m = needManifest();
    const mod = (await import("../searchRows")) as unknown as Record<string, unknown>;
    const kindOrder = mod.KIND_ORDER ?? mod.kindOrder;
    expect(
      kindOrder,
      `searchRows.ts exports [${Object.keys(mod).join(", ")}] — wanted KIND_ORDER ` +
        `(§4.1 pins the constant; it must mirror manifest.kinds, never restate a list)`
    ).toBeDefined();
    expect(Array.from(kindOrder as readonly string[])).toEqual(m.kinds);
  });
});

describe("AC-3 — FULL membership bijection against availability (not sampled)", () => {
  it("the availability corpus still measures the frozen §2 universe", () => {
    const rows = needAvail();
    expect(rows.length, "avail total (34 kinds)").toBe(14456);
    const sub = rows.filter((r) => SEARCHABLE_KINDS.includes(r.kind));
    expect(sub.length, "searchable universe").toBe(3779);
    const named = sub.filter((r) => r.namedLocales.length > 0);
    expect(named.length, "named universe").toBe(FROZEN_TOTAL);
  });

  it("L ∈ namedLocales ⇔ exactly one row in L.json — both directions, every row", () => {
    const rows = needAvail();
    const fs2 = needFiles();
    const sub = rows.filter((r) => SEARCHABLE_KINDS.includes(r.kind));

    const availById = new Map<string, AvailRow>();
    for (const r of sub) {
      expect(availById.has(`${r.kind}/${r.id}`), `duplicate avail row ${r.kind}/${r.id}`).toBe(false);
      availById.set(`${r.kind}/${r.id}`, r);
    }

    for (const code of OFFICIAL) {
      const f = fs2.get(code) as LocaleFile;
      const seenIds = new Set<string>();
      for (const r of f.rows) {
        const av = availById.get(`${r.kind}/${r.id}`);
        expect(av, `${code}.json row ${r.kind}/${r.id} has no availability row`).toBeDefined();
        expect(
          av?.namedLocales.includes(code),
          `${code}.json ships ${r.kind}/${r.id} but namedLocales lacks ${code}`
        ).toBe(true);
        expect(
          av?.fields?.[code]?.name,
          `${code}.json ships ${r.kind}/${r.id} whose fields[${code}].name flag is false`
        ).toBe(true);
        seenIds.add(`${r.kind}/${r.id}`);
      }
      expect(seenIds.size, `${code}.json duplicate rows`).toBe(f.rows.length);

      for (const av of sub) {
        const present = seenIds.has(`${av.kind}/${av.id}`);
        expect(
          present,
          `${av.kind}/${av.id}: namedLocales=${JSON.stringify(av.namedLocales)} but ` +
            `${present ? "also" : "not"} in ${code}.json`
        ).toBe(av.namedLocales.includes(code));
      }
    }
  });
});
