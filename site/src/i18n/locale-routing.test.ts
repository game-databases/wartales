// F4 §7.2 — locale-routing.test.ts (node-env, beside src/i18n/locales.ts).
//
// Spec: docs/spec-f4-app-shell.mdx §7 item 2 + §2 (locale table) + §3
// (routing contract). Laws under test:
//   - exactly the 9 frozen client locales (§2 table, spec.md locales.official);
//   - `en` is the sole bare pivot ([DR-2026-08-20-locale-urls]);
//   - URL prefixes (= id column) unique;
//   - BCP-47 column valid: `pt-br` -> `pt-BR`, `zh` -> `zh-Hans`, identity ×7;
//   - native names non-empty;
//   - exactly ONE row has id !== clientCode — `pt-br` -> `pt-BR`, the §2(r1b)
//     page↔data-plane join;
//   - routing.ts declares that table as its segments with defaultLocale "en",
//     localePrefix "as-needed", localeDetection false (§3 — pivot bare, no
//     negotiation; the `/en/*` 301 law itself is curl-verified by
//     scripts/smoke.mjs, not here);
//   - request.ts validates the resolved id and calls notFound() BEFORE any
//     message access (§3 rule 5 / m5 r1).
//
// BLIND suite: written against the spec alone. The module export SHAPE is not
// pinned by the spec, so discovery below accepts the reasonable spellings
// (array-of-rows or id-keyed map, common field aliases) and fails LOUDLY
// naming what it looked for when nothing qualifies — a missing or
// nonconformant shell must land red, never vacuously green.

import { describe, expect, it, beforeAll } from "vitest";
import { readFileSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const siteRoot = join(here, "..", "..");

// ---- the §2 table, verbatim -------------------------------------------------

type Row = {
  id: string;
  clientCode: string;
  bcp47: string;
  native: string;
};

const TABLE: Row[] = [
  { id: "en", clientCode: "en", bcp47: "en", native: "English" },
  { id: "de", clientCode: "de", bcp47: "de", native: "Deutsch" },
  { id: "es", clientCode: "es", bcp47: "es", native: "Español" },
  { id: "fr", clientCode: "fr", bcp47: "fr", native: "Français" },
  { id: "ko", clientCode: "ko", bcp47: "ko", native: "한국어" },
  { id: "pl", clientCode: "pl", bcp47: "pl", native: "Polski" },
  { id: "pt-br", clientCode: "pt-BR", bcp47: "pt-BR", native: "Português (Brasil)" },
  { id: "ru", clientCode: "ru", bcp47: "ru", native: "Русский" },
  { id: "zh", clientCode: "zh", bcp47: "zh-Hans", native: "简体中文" },
];

const EXPECTED_IDS = TABLE.map((r) => r.id).sort();
const EXPECTED_CLIENT_CODES = TABLE.map((r) => r.clientCode).sort();
const EXPECTED_BCP47: Record<string, string> = Object.fromEntries(
  TABLE.map((r) => [r.id, r.bcp47])
);

// ---- tolerant module-shape discovery ---------------------------------------

type AnyRec = Record<string, unknown>;

const ID_KEYS = ["id", "segment", "urlSegment", "pageSegment", "slug"];
const CLIENT_KEYS = ["clientCode", "client", "client_code", "gameCode", "pak"];
const BCP_KEYS = ["bcp47", "bcp47Tag", "htmlLang", "lang", "tag", "hreflang"];
const NATIVE_KEYS = ["native", "nativeName", "endonym", "name", "label"];
const PIVOT_KEYS = ["pivot", "isPivot", "bare", "isBare", "isDefault", "default"];

const pick = (o: AnyRec, keys: string[]): unknown => {
  for (const k of keys) if (o[k] !== undefined) return o[k];
  return undefined;
};

function looksLikeRow(v: unknown): v is AnyRec {
  return (
    typeof v === "object" &&
    v !== null &&
    !Array.isArray(v) &&
    pick(v as AnyRec, ID_KEYS) !== undefined
  );
}

function discoverRows(mod: AnyRec): { rows: AnyRec[]; via: string } | null {
  const preferred = [
    "LOCALE_TABLE", "LOCALES", "localeTable", "locales",
    "LOCALE_ROWS", "localeRows", "rows", "TABLE", "table", "default",
  ];
  for (const name of preferred) {
    const hit = probe(mod[name], name);
    if (hit) return hit;
  }
  for (const [name, v] of Object.entries(mod)) {
    const hit = probe(v, name);
    if (hit) return hit;
  }
  return null;
}

function probe(v: unknown, via: string): { rows: AnyRec[]; via: string } | null {
  if (Array.isArray(v) && v.length > 0 && v.every(looksLikeRow)) {
    return { rows: v as AnyRec[], via };
  }
  if (typeof v === "object" && v !== null && !Array.isArray(v)) {
    const entries = Object.entries(v as AnyRec).filter(([k]) => k !== "default");
    if (
      entries.length > 0 &&
      entries.every(([, val]) => looksLikeRow(val))
    ) {
      return {
        rows: entries.map(([k, val]) => ({
          id: (val as AnyRec).id ?? k,
          ...(val as AnyRec),
        })),
        via,
      };
    }
  }
  return null;
}

function discoverRouting(mod: AnyRec): AnyRec | null {
  const candidates = ["routing", "ROUTING", "default"];
  for (const name of candidates) {
    const v = mod[name];
    if (
      typeof v === "object" &&
      v !== null &&
      Array.isArray((v as AnyRec).locales)
    ) {
      return v as AnyRec;
    }
  }
  for (const v of Object.values(mod)) {
    if (
      typeof v === "object" &&
      v !== null &&
      Array.isArray((v as AnyRec).locales) &&
      "defaultLocale" in (v as AnyRec)
    ) {
      return v as AnyRec;
    }
  }
  return null;
}

// ---- fixtures loaded once ---------------------------------------------------

let rows: AnyRec[] | null = null;
let rowsVia = "";
let localesError: Error | null = null;
let routing: AnyRec | null = null;
let routingError: Error | null = null;
let requestSrc: string | null = null;

beforeAll(async () => {
  try {
    const loc = (await import("./locales")) as unknown as AnyRec;
    const found = discoverRows(loc);
    if (!found) {
      localesError = new Error(
        `src/i18n/locales.ts exports [${Object.keys(loc).join(", ")}] but none ` +
          `is recognizably the §2 table (wanted an array of rows carrying an ` +
          `id-like key (${ID_KEYS.join("|")}), or an id-keyed map of such rows)`
      );
    } else {
      rows = found.rows;
      rowsVia = found.via;
    }
  } catch (e) {
    localesError = e as Error;
  }

  try {
    const rt = (await import("./routing")) as unknown as AnyRec;
    routing = discoverRouting(rt);
    if (!routing) {
      routingError = new Error(
        `src/i18n/routing.ts exports [${Object.keys(rt).join(", ")}] but none ` +
          `carries { locales: string[], defaultLocale } — the §3 defineRouting ` +
          `product`
      );
    }
  } catch (e) {
    routingError = e as Error;
  }

  const requestTs = join(here, "request.ts");
  if (existsSync(requestTs)) {
    try {
      requestSrc = readFileSync(requestTs, "utf8");
    } catch {
      requestSrc = null;
    }
  }
});

function needRows(): AnyRec[] {
  if (localesError) {
    throw new Error(
      `src/i18n/locales.ts missing or unreadable (§2 single-source law): ${localesError.message}`
    );
  }
  if (!rows) throw localesError ?? new Error("locale table not discovered");
  return rows;
}

const fieldOf = (r: AnyRec, keys: string[]): unknown => pick(r, keys);

// ---- the suite --------------------------------------------------------------

describe("§2 locale table — one table, one derivation", () => {
  it("exports a recognizable locale table", () => {
    const got = needRows();
    expect(got.length, `table discovered via export "${rowsVia}"`).toBeGreaterThan(0);
  });

  it("has exactly the 9 frozen client locales (ids and client codes)", () => {
    const got = needRows();
    const ids = got.map((r) => String(fieldOf(r, ID_KEYS))).sort();
    expect(ids, `ids (via "${rowsVia}")`).toEqual(EXPECTED_IDS);
    const codes = got.map((r) => String(fieldOf(r, CLIENT_KEYS))).sort();
    expect(
      codes,
      "client codes must equal the frozen spec.md locales.official set"
    ).toEqual(EXPECTED_CLIENT_CODES);
  });

  it("keeps ids and URL prefixes unique", () => {
    const got = needRows();
    const ids = got.map((r) => String(fieldOf(r, ID_KEYS)));
    expect(new Set(ids).size, "duplicate locale ids").toBe(ids.length);
    const prefixes = got.map(
      (r) =>
        fieldOf(r, ["prefix", "urlPrefix", "pathPrefix"]) ??
        fieldOf(r, ID_KEYS)
    );
    const strs = prefixes.map((p) => String(p));
    expect(new Set(strs).size, "duplicate URL prefixes").toBe(strs.length);
  });

  it("maps BCP-47 correctly: identity ×7, pt-br→pt-BR, zh→zh-Hans", () => {
    const got = needRows();
    for (const r of got) {
      const id = String(fieldOf(r, ID_KEYS));
      const tag = fieldOf(r, BCP_KEYS);
      expect(tag, `--bcp47 column for '${id}'`).toBeDefined();
      expect(String(tag), `<html lang> for '/${id}'`).toBe(EXPECTED_BCP47[id]);
    }
  });

  it("makes en the sole bare pivot and the routing defaultLocale", () => {
    const got = needRows();
    const flagged = got.filter((r) =>
      PIVOT_KEYS.some((k) => r[k] === true)
    );
    if (flagged.length > 0) {
      expect(
        flagged.map((r) => String(fieldOf(r, ID_KEYS))).sort(),
        "pivot/bare flag must mark exactly the EN row"
      ).toEqual(["en"]);
    }
    const enPrefix = got
      .filter((r) => String(fieldOf(r, ID_KEYS)) === "en")
      .map((r) => fieldOf(r, ["prefix", "urlPrefix", "pathPrefix"]));
    for (const p of enPrefix) {
      expect(
        p === undefined || p === null || p === "" || p === false || p === "none",
        "EN must carry no locale prefix (bare pivot)"
      ).toBe(true);
    }
    expect(routingError).toBeNull();
    expect(
      String(routing && routing.defaultLocale),
      "§3: defaultLocale must be 'en'"
    ).toBe("en");
  });

  it("carries a non-empty native name for every row", () => {
    const got = needRows();
    for (const r of got) {
      const id = String(fieldOf(r, ID_KEYS));
      const native = fieldOf(r, NATIVE_KEYS);
      expect(native, `native name missing for '${id}'`).toBeDefined();
      expect(
        typeof native === "string" && native.trim().length > 0,
        `native name for '${id}' must be a non-empty string`
      ).toBe(true);
    }
  });

  it("has exactly ONE row with id !== clientCode: pt-br → pt-BR (§2 r1b)", () => {
    const got = needRows();
    const divergent = got
      .filter(
        (r) =>
          String(fieldOf(r, ID_KEYS)) !== String(fieldOf(r, CLIENT_KEYS))
      )
      .map((r) => ({
        id: String(fieldOf(r, ID_KEYS)),
        clientCode: String(fieldOf(r, CLIENT_KEYS)),
      }));
    expect(divergent).toEqual([{ id: "pt-br", clientCode: "pt-BR" }]);
  });
});

describe("§3 routing contract (static facts behind the /en 301 + no-negotiation laws)", () => {
  it("routing.ts is importable and exposes the defineRouting product", () => {
    if (routingError) {
      throw new Error(`src/i18n/routing.ts missing or unusable: ${routingError.message}`);
    }
    expect(routing).not.toBeNull();
  });

  it("declares exactly the §2 table ids as its locale segments", () => {
    const got = needRows();
    if (routingError) throw new Error(routingError.message);
    const segments = ((routing as AnyRec).locales as unknown[])
      .map((s) => String(s))
      .sort();
    expect(segments).toEqual(EXPECTED_IDS);
    // §2: "No second mapping may appear anywhere in site/" — the router must
    // derive its segments from the table, not restate a different set.
    expect(segments).toEqual(got.map((r) => String(fieldOf(r, ID_KEYS))).sort());
  });

  it("pins localePrefix 'as-needed' and localeDetection false (no negotiation)", () => {
    if (routingError) throw new Error(routingError.message);
    expect((routing as AnyRec).localePrefix).toBe("as-needed");
    expect((routing as AnyRec).localeDetection).toBe(false);
  });
});

describe("§3 rule 5 / m5 r1 — unknown-segment 404 mechanism (static half)", () => {
  it("request.ts validates the locale id and calls notFound() before messages resolve", () => {
    expect(
      requestSrc,
      "site/src/i18n/request.ts must exist (§1 tree) — the dynamic half of " +
        "this law (curl /xx/foo → 404, never a redirect) is smoke.mjs AC-leg 4"
    ).not.toBeNull();
    expect(
      /notFound\s*\(/.test(requestSrc as string),
      "request.ts must call notFound() on any id outside the §2 table " +
        "(§1 tree comment, m5 r1)"
    ).toBe(true);
  });
});
