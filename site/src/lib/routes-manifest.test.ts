// F4 §7.4 — routes-manifest.test.ts (node-env, beside src/lib/routes-manifest.ts).
//
// Spec: docs/spec-f4-app-shell.mdx §7 item 4 + §5. Laws under test:
//   - nav/footer links render ONLY from src/lib/routes-manifest.ts entries
//     whose target route exists (`live: true`) — dead nav links cannot ship,
//     so every live href must resolve to an existing route file on disk;
//   - every manifest entry's `labelKey` names a chrome key present in ALL
//     NINE message files, and comes from the §4 13-key inventory (r1 M2: at
//     F4 exactly the home row's `chrome.header.homeLabel`);
//   - the F4 fixture manifest holds exactly one live row:
//     { id: "home", href: "/", labelKey: "chrome.header.homeLabel", live: true };
//   - no internal link may ever emit `/en` (§3 rule 2) and no search link
//     exists anywhere in F4 output (§5 / AC 11).
//
// BLIND suite: written against the spec alone; export shape discovered
// tolerantly, failures name what was looked for.

import { describe, expect, it, beforeAll } from "vitest";
import { readFileSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)); // site/src/lib
const siteRoot = join(here, "..", "..");

const HOME_FIXTURE = {
  id: "home",
  href: "/",
  labelKey: "chrome.header.homeLabel",
};

// §4 inventory — labelKeys are drawn from it, never a second vocabulary.
const INVENTORY_13 = new Set([
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
]);

type AnyRec = Record<string, unknown>;
type Entry = { id: string; href: string; labelKey: string; live: boolean };

let manifestError: Error | null = null;
let entries: Entry[] | null = null;
let via = "";
let chromeKeySets: { id: string; keys: Set<string> }[] | null = null;
let messagesError: Error | null = null;

function flattenKeys(obj: unknown, prefix = "", out: Set<string> = new Set()): Set<string> {
  if (typeof obj !== "object" || obj === null) return out;
  for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (typeof v === "object" && v !== null) flattenKeys(v, key, out);
    else out.add(key);
  }
  return out;
}

function discoverEntries(mod: AnyRec): { list: unknown[]; via: string } | null {
  const preferred = [
    "ROUTES_MANIFEST", "routesManifest", "MANIFEST", "manifest",
    "NAV", "nav", "sections", "items", "rows", "routes", "default",
  ];
  for (const name of preferred) {
    if (Array.isArray(mod[name])) return { list: mod[name], via: name };
  }
  // container objects: first array-of-objects property wins
  for (const [name, v] of Object.entries(mod)) {
    if (
      Array.isArray(v) &&
      v.length > 0 &&
      v.every((x) => typeof x === "object" && x !== null)
    ) {
      return { list: v, via: name };
    }
    if (
      typeof v === "object" &&
      v !== null &&
      !Array.isArray(v)
    ) {
      for (const [n2, v2] of Object.entries(v as AnyRec)) {
        if (Array.isArray(v2) && v2.length > 0 && v2.every((x) => typeof x === "object" && x !== null)) {
          return { list: v2, via: `${name}.${n2}` };
        }
      }
    }
  }
  return null;
}

function normalize(list: unknown[]): Entry[] {
  return list.map((raw) => {
    const r = raw as AnyRec;
    return {
      id: String(r.id ?? ""),
      href: String(r.href ?? r.path ?? r.url ?? ""),
      labelKey: String(r.labelKey ?? r.label_key ?? ""),
      live: r.live === true,
    };
  });
}

/** Does this href have a real route file under src/app/[locale]/? */
export function routeFileExists(href: string): boolean {
  const segs = href
    .replace(/[?#].*$/, "")
    .split("/")
    .filter(Boolean);
  if (segs.some((s) => s.startsWith(":") || s.includes("*"))) return false;
  const dir = segs.length
    ? join(siteRoot, "src", "app", "[locale]", ...segs)
    : join(siteRoot, "src", "app", "[locale]");
  return [".tsx", ".ts", ".jsx", ".js", ".mdx"].some((ext) =>
    existsSync(join(dir, `page${ext}`))
  );
}

beforeAll(async () => {
  try {
    const mod = (await import("./routes-manifest")) as unknown as AnyRec;
    const found = discoverEntries(mod);
    if (!found) {
      manifestError = new Error(
        `src/lib/routes-manifest.ts exports [${Object.keys(mod).join(", ")}] ` +
          `but none is an array of { id, href, labelKey, live } rows`
      );
    } else {
      entries = normalize(found.list);
      via = found.via;
    }
  } catch (e) {
    manifestError = e as Error;
  }

  try {
    chromeKeySets = [];
    for (const id of ["en", "de", "es", "fr", "ko", "pl", "pt-br", "ru", "zh"]) {
      const file = join(siteRoot, "messages", `${id}.json`);
      if (!existsSync(file)) throw new Error(`messages/${id}.json missing`);
      chromeKeySets.push({
        id,
        keys: flattenKeys(JSON.parse(readFileSync(file, "utf8"))),
      });
    }
  } catch (e) {
    messagesError = e as Error;
  }
});

/** No test may pass vacuously over a missing manifest/messages fixture. */
function needEntries(): Entry[] {
  if (manifestError) {
    throw new Error(`src/lib/routes-manifest.ts unusable: ${manifestError.message}`);
  }
  return entries ?? [];
}
function needChromeSets(): { id: string; keys: Set<string> }[] {
  if (messagesError) throw new Error(`message files unreadable: ${messagesError.message}`);
  return chromeKeySets ?? [];
}

describe("§5/§7.4 routes-manifest — render only what exists", () => {
  it("exports a recognizable manifest array", () => {
    if (manifestError) {
      throw new Error(`src/lib/routes-manifest.ts unusable: ${manifestError.message}`);
    }
    expect(entries!.length, `discovered via export "${via}"`).toBeGreaterThan(0);
  });

  it("has well-formed unique entries (id, internal href, labelKey)", () => {
    const list = needEntries();
    expect(list.length, "manifest must not be empty").toBeGreaterThan(0);
    expect(
      new Set(list.map((e) => e.id)).size,
      "manifest ids must be unique"
    ).toBe(list.length);
    for (const e of list) {
      expect(e.id, "every entry needs an id").toBeTruthy();
      expect(e.href.startsWith("/"), `${e.id}: href must be internal (starts with /)`).toBe(true);
      expect(e.labelKey, `${e.id}: every entry carries a labelKey`).toBeTruthy();
    }
  });

  it("holds exactly the one declared F4 live row (r1 M2 fixture)", () => {
    const live = needEntries().filter((e) => e.live);
    expect(live).toHaveLength(1);
    expect(live[0].id).toBe(HOME_FIXTURE.id);
    expect(live[0].href).toBe(HOME_FIXTURE.href);
    expect(live[0].labelKey).toBe(HOME_FIXTURE.labelKey);
  });

  it("resolves every live:true href to an existing route file on disk", () => {
    const dead = needEntries()
      .filter((e) => e.live)
      .filter((e) => !routeFileExists(e.href));
    expect(
      dead.map((e) => `${e.id} -> ${e.href}`),
      "dead nav links cannot ship — create the route or flip live:false"
    ).toEqual([]);
  });

  it("names a chrome key present in all nine message files, from the §4 inventory", () => {
    const chrome = needChromeSets();
    for (const e of needEntries()) {
      expect(
        INVENTORY_13.has(e.labelKey),
        `${e.id}: labelKey '${e.labelKey}' is outside the §4 inventory — no second vocabulary`
      ).toBe(true);
      for (const l of chrome) {
        expect(
          l.keys.has(e.labelKey),
          `${e.id}: labelKey '${e.labelKey}' missing from messages/${l.id}.json`
        ).toBe(true);
      }
    }
  });

  it("never emits /en and never links a search page", () => {
    for (const e of needEntries()) {
      expect(
        e.href === "/en" || e.href.startsWith("/en/") || e.href.startsWith("/en?"),
        `${e.id}: /en/* never exists (§3 rule 2)`
      ).toBe(false);
      expect(
        e.href.startsWith("/search"),
        `${e.id}: there is no /search route or link anywhere in F4 output (AC 11)`
      ).toBe(false);
    }
  });
});
