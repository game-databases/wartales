// F4 §7.3 — chrome-parity.test.ts (node-env, beside the site/messages/*.json
// files it guards — the tokens.test.ts-beside-tokens.css placement precedent).
//
// Spec: docs/spec-f4-app-shell.mdx §7 item 3 + §4. Gates under test:
//   - nine locale message files exist, each a SINGLE `chrome` namespace object;
//   - identical key set ×9, and exactly the §4 13-key inventory at F4 (no
//     extra keys — F5's `search.*` enters with F5's commit, not before; no
//     "explains-the-UI" slop keys);
//   - every value a non-empty string;
//   - identical {placeholder} sets per key across locales;
//   - stub ledger `_stub-keys.json` lists exactly the still-stubbed keys,
//     every listed key byte-identical across all nine files, and at F4 the
//     ledger covers all 13.
//
// BLIND suite: written against the spec alone. Ledger shape is not pinned
// (array of keys or key-map both accepted); anything else fails loudly.

import { describe, expect, it, beforeAll } from "vitest";
import { readFileSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)); // site/messages
const messagesDir = here;

const LOCALE_IDS = ["en", "de", "es", "fr", "ko", "pl", "pt-br", "ru", "zh"];

// §4 initial key inventory — exactly 13, EN stub values at F4.
const INVENTORY_13 = [
  "chrome.nav.database",
  "chrome.nav.map",
  "chrome.nav.guides",
  "chrome.nav.news",
  "chrome.nav.tools",
  "chrome.header.homeLabel",
  "chrome.locale.triggerLabel",
  "chrome.locale.listLabel",
  "chrome.a11y.skipToContent",
  "chrome.footer.label",
  "chrome.footer.sections",
  "chrome.notFound.title",
  "chrome.notFound.body",
].sort();

const LEDGER_FILE = "_stub-keys.json";

type Loaded = { id: string; flat: Map<string, string> };
let loaded: Loaded[] = [];
let loadErrors: string[] = [];
let ledgerKeys: string[] | null = null;
let ledgerError: string | null = null;

/** Flatten a single-namespace chrome object into dotted keys. */
function flatten(obj: unknown, prefix = "", out: Map<string, string> = new Map()): Map<string, string> {
  if (typeof obj !== "object" || obj === null) return out;
  for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (typeof v === "object" && v !== null) flatten(v, key, out);
    else out.set(key, String(v));
  }
  return out;
}

function ledgerKeyList(raw: unknown): string[] {
  if (Array.isArray(raw)) return raw.map((x) => String(x));
  if (typeof raw === "object" && raw !== null) return Object.keys(raw);
  throw new Error(`ledger must be an array of keys or a key map, got ${typeof raw}`);
}

beforeAll(() => {
  for (const id of LOCALE_IDS) {
    const file = join(messagesDir, `${id}.json`);
    if (!existsSync(file)) {
      loadErrors.push(`${id}.json: missing`);
      continue;
    }
    try {
      const parsed = JSON.parse(readFileSync(file, "utf8"));
      loaded.push({ id, flat: flatten(parsed) });
    } catch (e) {
      loadErrors.push(`${id}.json: unparsable JSON (${(e as Error).message})`);
    }
  }

  const ledgerPath = join(messagesDir, LEDGER_FILE);
  if (!existsSync(ledgerPath)) {
    ledgerError = `${LEDGER_FILE} missing — §4 makes the stub policy mechanical`;
  } else {
    try {
      ledgerKeys = ledgerKeyList(JSON.parse(readFileSync(ledgerPath, "utf8")));
    } catch (e) {
      ledgerError = `${LEDGER_FILE}: ${(e as Error).message}`;
    }
  }
});

function needLoaded(): Loaded[] {
  if (loadErrors.length > 0) {
    throw new Error(
      `§4 requires site/messages/<id>.json ×9 (${LOCALE_IDS.join(", ")}); ` +
        `problems: ${loadErrors.join("; ")}`
    );
  }
  return loaded;
}

function byId(id: string): Map<string, string> {
  return needLoaded().find((l) => l.id === id)!.flat;
}

describe("§4 chrome i18n — files ×9, one namespace", () => {
  it("ships all nine locale files, parsable", () => {
    needLoaded();
  });

  it("keeps each file a single `chrome` namespace object", () => {
    for (const l of needLoaded()) {
      const file = join(messagesDir, `${l.id}.json`);
      const top = Object.keys(JSON.parse(readFileSync(file, "utf8")));
      expect(
        top.sort(),
        `${l.id}.json top-level keys — game-content namespaces never enter these files`
      ).toEqual(["chrome"]);
    }
  });
});

describe("§7.3 parity gates", () => {
  it("has an identical key set across all nine locales", () => {
    const all = needLoaded();
    const enKeys = [...byId("en").keys()].sort();
    for (const l of all) {
      expect(
        [...l.flat.keys()].sort(),
        `${l.id}.json key set diverges from en.json`
      ).toEqual(enKeys);
    }
  });

  it("carries exactly the §4 13-key inventory at F4 — nothing more, nothing less", () => {
    const keys = [...byId("en").keys()].sort();
    const missing = INVENTORY_13.filter((k) => !keys.includes(k));
    const extra = keys.filter((k) => !INVENTORY_13.includes(k));
    expect(
      missing,
      "missing §4 inventory keys"
    ).toEqual([]);
    expect(
      extra,
      "extra keys beyond the §4 inventory are anti-slop violations; F5's " +
        "`search.*` keys enter with F5's commit, not before"
    ).toEqual([]);
    expect(keys.length).toBe(13);
  });

  it("holds a non-empty string value for every key in every locale", () => {
    for (const l of needLoaded()) {
      for (const [k, v] of l.flat) {
        expect(
          typeof v === "string" && v.trim().length > 0,
          `${l.id}.json ${k} is empty or not a string`
        ).toBe(true);
      }
    }
  });

  it("keeps {placeholder} sets identical per key across locales", () => {
    const ph = (s: string) =>
      [...s.matchAll(/\{([a-zA-Z0-9_]+)\}/g)].map((m) => m[1]).sort();
    const en = byId("en");
    for (const l of needLoaded()) {
      for (const [k, enVal] of en) {
        expect(
          ph(l.flat.get(k) ?? ""),
          `{placeholder} mismatch in ${l.id}.json key ${k}`
        ).toEqual(ph(enVal));
      }
    }
  });
});

describe("§4 stub ledger — the stub policy made mechanical", () => {
  it("parses _stub-keys.json", () => {
    if (ledgerError) throw new Error(ledgerError);
    expect(ledgerKeys).not.toBeNull();
  });

  it("lists only keys that exist in the chrome namespace", () => {
    if (ledgerError) throw new Error(ledgerError);
    const known = new Set(byId("en").keys());
    const unknown = (ledgerKeys as string[]).filter((k) => !known.has(k));
    expect(unknown, "ledger entries outside the chrome key set").toEqual([]);
  });

  it("is byte-identical per stubbed key across all nine files", () => {
    if (ledgerError) throw new Error(ledgerError);
    for (const key of ledgerKeys as string[]) {
      const enVal = byId("en").get(key);
      expect(enVal, `ledger key ${key} missing from en.json`).toBeDefined();
      for (const l of needLoaded()) {
        expect(
          l.flat.get(key),
          `stubbed key ${key} differs in ${l.id}.json — a "translated" value ` +
            `cannot hide inside a stubbed key`
        ).toBe(enVal);
      }
    }
  });

  it("lists all 13 keys at F4 (every value is still a pivot-EN stub)", () => {
    if (ledgerError) throw new Error(ledgerError);
    expect(
      [...new Set(ledgerKeys as string[])].sort(),
      "at F4 all thirteen chrome keys carry pivot-EN stub text and must be " +
        "listed; shrinking the ledger is a later piece's conscious edit"
    ).toEqual(INVENTORY_13);
  });
});
