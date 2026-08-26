// F4 §7.5 — shell-hygiene.test.ts (node-env, beside the F1 canon it guards).
//
// Spec: docs/spec-f4-app-shell.mdx §7 item 5, §6, AC 9/10 — this suite IS
// "AC 9's failing command for both slices" (color AND non-color literals).
// Sweep scope (§7.5 r1): src/components/** + src/app/** AND
// src/styles/globals.css — every file where a token declaration could land.
// tokens.css/tokens.test.ts are excluded (the canon cannot self-hit).
//
// Absence laws swept:
//   - stock Tailwind palette classes (slate|gray|zinc|neutral|stone-*-N);
//   - raw numeric spacing utilities (p-4, gap-2, …) — the game rhythm ships
//     only as named utilities --spacing-g1..g8 (§6.3); arbitrary-length
//     brackets are legal ONLY when riding var(--spacing-g*)/var(--space-*));
//   - rounded-* corner utilities (r1b — square is F1 §2.4 canon);
//   - `oklch(` anywhere in swept sources;
//   - any canon-token NAME from tokens.css re-declared outside tokens.css —
//     in CSS only in the aliasing form (`--color-bg-1: var(--bg-1)`), never
//     a literal copy, COLOR OR NON-COLOR (r1b): radius length, font stack,
//     duration — any non-var() right side whose left side matches a canon
//     token name fails here; in TS/TSX inline styles a canon-named custom
//     property assignment is banned outright;
//   - any --radius-* declaration at all in globals.css (§6 r1b omission);
//   - a second definition of a tokens.css recipe (.wt-panel, .rarity-tier-*,
//     moveGradient) anywhere in the sweep (§6 item 5).
// Wiring laws asserted (§6, brief deliverable 1 "token wiring/hygiene"):
//   - @theme maps the enumerated game tokens + shadcn slots, every canon-
//     sourced right side a var() reference;
//   - base layer color-scheme: dark; no `.dark` variant exists.

import { describe, expect, it, beforeAll } from "vitest";
import { readFileSync, existsSync, readdirSync, statSync } from "node:fs";
import { join, dirname, extname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)); // site/src/styles
const srcRoot = join(here, "..");
const siteRoot = join(srcRoot, "..");

type Violation = { file: string; rule: string; detail: string };

let violations: Violation[] = [];
let sweptFiles: string[] = [];
let canonNames: Set<string> = new Set();
let setupError: Error | null = null;

// ---- helpers ----------------------------------------------------------------

function stripComments(src: string, flavor: "css" | "code"): string {
  let s = src.replace(/\/\*[\s\S]*?\*\//g, " ");
  if (flavor === "code") s = s.replace(/(^|[^:])\/\/[^\n]*/g, "$1 ");
  return s;
}

function lineOf(text: string, idx: number): number {
  return text.slice(0, idx).split("\n").length;
}

function parseCanonNames(): Set<string> {
  const raw = readFileSync(join(here, "tokens.css"), "utf8");
  const css = stripComments(raw, "css");
  const names = new Set<string>();
  for (const m of css.matchAll(/--([a-zA-Z0-9-]+)\s*:/g)) names.add(m[1]);
  return names;
}

function walk(dir: string, exts: Set<string>, acc: string[]): void {
  if (!existsSync(dir)) return;
  for (const ent of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, ent.name);
    if (ent.isDirectory()) walk(p, exts, acc);
    else if (exts.has(extname(ent.name)) && !/[.]test\.[tj]sx?$/.test(ent.name)) {
      acc.push(p);
    }
  }
}

/** className token with variant/responsive prefixes and !important stripped */
function baseClass(tok: string): string {
  let t = tok.trim().replace(/!$/, "");
  t = t.split("/")[0];
  const colon = t.lastIndexOf(":");
  if (colon >= 0) t = t.slice(colon + 1);
  return t.replace(/^[,(]+/, "").replace(/[;,)\]]+$/, "");
}

const STOCK_PALETTE = /^(?:slate|gray|zinc|neutral|stone)-(\d{2,3})$/;
function paletteHit(tok: string): boolean {
  const m = STOCK_PALETTE.exec(baseClass(tok));
  if (!m) return false;
  const n = Number(m[1]);
  return n >= 50 && n <= 950 && n % 50 === 0; // Tailwind's stock shade ladder
}

// Ordered longest-first so px/py/pt… win over p, space-x over space.
const SPACING_PROPS = [
  "space-x", "space-y", "gap-x", "gap-y",
  "px", "py", "pt", "pr", "pb", "pl", "ps", "pe",
  "mx", "my", "mt", "mr", "mb", "ml", "ms", "me",
  "gap", "p", "m",
];
function spacingHit(tok: string): string | null {
  let base = baseClass(tok);
  if (base.startsWith("-")) base = base.slice(1);
  for (const prop of SPACING_PROPS) {
    if (base !== prop && !base.startsWith(prop + "-")) continue;
    const value = base === prop ? "" : base.slice(prop.length + 1);
    if (!value) return null; // bare prop is not a utility
    if (/^\d+(\.\d+)?$/.test(value)) {
      return `raw numeric spacing '${tok}' — use the named g-scale (§6.3: p-g4, gap-g5, …)`;
    }
    const br = /^\[(.+)\]$/.exec(value);
    if (br && !/var\(--(?:spacing-g\d|space-\d)\b/.test(br[1])) {
      return `arbitrary spacing '${tok}' must ride var(--spacing-g*)/var(--space-*)`;
    }
    return null;
  }
  return null;
}

function roundedHit(tok: string): boolean {
  const b = baseClass(tok);
  return b === "rounded" || b.startsWith("rounded-"); // square is F1 §2.4 canon
}

function extractStringLiterals(src: string): string[] {
  const out: string[] = [];
  const patterns = [
    /"((?:\\.|[^"\\\n])*)"/g,
    /'((?:\\.|[^'\\\n])*)'/g,
    /`((?:\\.|[^`\\])*)`/gs,
  ];
  for (const re of patterns) for (const m of src.matchAll(re)) out.push(m[1]);
  return out;
}

const VAR_FORM = /^var\(--[a-zA-Z0-9-]+(?:\s*,[\s\S]*?)?\)$/;
const CANON_DECL = /--([a-zA-Z0-9-]+)\s*:\s*([^;{}]+)[;{}]/g;

function themeBlocks(css: string): string[] {
  const blocks: string[] = [];
  const re = /@theme\b[^{]*\{/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(css))) {
    let depth = 1;
    let i = re.lastIndex;
    while (i < css.length && depth > 0) {
      if (css[i] === "{") depth++;
      else if (css[i] === "}") depth--;
      i++;
    }
    blocks.push(css.slice(re.lastIndex, i - 1));
    re.lastIndex = i;
  }
  return blocks;
}

// §6.2/§6.3 required @theme wiring: [theme property, required var() source].
// Exact-source rows must alias that canon token verbatim; null rows only
// demand SOME var() right side (font stacks ride the verify-at-install duty).
const SHADCN_COLOR_SLOTS = [
  "background", "foreground", "card", "card-foreground",
  "popover", "popover-foreground", "primary", "primary-foreground",
  "secondary", "secondary-foreground", "muted", "muted-foreground",
  "accent", "accent-foreground", "destructive", "destructive-foreground",
  "border", "input", "ring",
  "chart-1", "chart-2", "chart-3", "chart-4", "chart-5",
  "sidebar", "sidebar-foreground", "sidebar-primary",
  "sidebar-primary-foreground", "sidebar-accent", "sidebar-accent-foreground",
  "sidebar-border", "sidebar-ring",
];
const GAME_EXACT: [string, string][] = [
  ["--color-bg-1", "--bg-1"],
  ["--color-bg-2", "--bg-2"],
  ["--color-bg-3", "--bg-3"],
  ["--color-bg-4", "--bg-4"],
  ["--color-panel-well", "--panel-well"],
  ["--color-selection", "--selection"],
  ["--color-positive", "--positive"],
  ["--color-negative", "--negative"],
  ["--color-warning", "--warning"],
  ...[0, 1, 2, 3].map((n) => [`--color-rarity-${n}`, `--rarity-${n}`] as [string, string]),
  ...[1, 2, 3].map((n) => [`--color-light-rarity-${n}`, `--light-rarity-${n}`] as [string, string]),
  ...SHADCN_COLOR_SLOTS.filter((s) => s.startsWith("chart")).map(
    (s) => [`--color-${s}`, `--${s}`] as [string, string]
  ),
  ...[1, 2, 3, 4].map((n) => [`--color-player-${n}`, `--player-${n}`] as [string, string]),
];
const GAME_VARFORM_ONLY = [
  "--font-ui", "--font-flavor", "--font-cjk",
  "--font-sans", "--font-serif", "--font-mono",
  "--text-sm", "--text-base", "--text-dialog", "--text-lg", "--text-display",
];

beforeAll(() => {
  try {
    canonNames = parseCanonNames();

    const targets: { path: string; kind: "dir" | "file"; label: string }[] = [
      { path: join(srcRoot, "components"), kind: "dir", label: "src/components/**" },
      { path: join(srcRoot, "app"), kind: "dir", label: "src/app/**" },
      { path: join(here, "globals.css"), kind: "file", label: "src/styles/globals.css" },
    ];
    for (const t of targets) {
      if (!existsSync(t.path)) {
        violations.push({
          file: t.label,
          rule: "sweep-target",
          detail: "§7.5 sweep target missing — the shell piece has not landed",
        });
      }
    }

    const exts = new Set([".ts", ".tsx", ".css"]);
    const files: string[] = [];
    walk(join(srcRoot, "components"), exts, files);
    walk(join(srcRoot, "app"), exts, files);
    if (existsSync(join(here, "globals.css"))) files.push(join(here, "globals.css"));
    sweptFiles = files;

    for (const file of files) {
      const rel = file.slice(siteRoot.length + 1);
      const raw = readFileSync(file, "utf8");
      const isCss = extname(file) === ".css";
      const codeOnly = isCss ? stripComments(raw, "css") : stripComments(raw, "code");

      // -- class-token bans (string literals in ts/tsx; whole text in css) ----
      const tokenSources: string[] = isCss
        ? [codeOnly.split(/\s+/).join(" ")]
        : extractStringLiterals(raw).flatMap((s) => s.split(/\s+/));
      for (const tok of tokenSources) {
        if (paletteHit(tok)) {
          violations.push({ file: rel, rule: "stock-palette", detail: `'${tok}' (AC 10)` });
        }
        const sp = spacingHit(tok);
        if (sp) violations.push({ file: rel, rule: "numeric-spacing", detail: sp });
        if (roundedHit(tok)) {
          violations.push({ file: rel, rule: "rounded-corner", detail: `'${tok}' — square is F1 §2.4 canon (r1b)` });
        }
      }

      // -- oklch ban ----------------------------------------------------------
      const okIdx = codeOnly.indexOf("oklch(");
      if (okIdx >= 0) {
        violations.push({ file: rel, rule: "oklch", detail: `line ${lineOf(codeOnly, okIdx)} (AC 10)` });
      }

      // -- canon redeclaration -------------------------------------------------
      if (isCss) {
        for (const m of codeOnly.matchAll(CANON_DECL)) {
          const [, name, rhsRaw] = m;
          const rhs = String(rhsRaw).trim();
          if (name.startsWith("radius") || name === "radius") {
            violations.push({
              file: rel, rule: "radius-ban",
              detail: `--${name} declared — globals.css declares NO --radius-* at all (§6 r1b)`,
            });
            continue;
          }
          if (canonNames.has(name) && !VAR_FORM.test(rhs)) {
            violations.push({
              file: rel, rule: "canon-literal",
              detail: `--${name}: '${rhs}' — canon-named declarations outside tokens.css ` +
                `must take the var() aliasing form, COLOR OR NON-COLOR (§6.2 r1/r1b; AC 9)`,
            });
          }
        }
        for (const m of codeOnly.matchAll(
          /\.wt-panel\s*[,{:]|\.rarity-tier-[A-Za-z0-9_-]*\s*[,{:]|@keyframes\s+moveGradient\b/g
        )) {
          violations.push({
            file: rel, rule: "recipe-redefinition",
            detail: `'${m[0].trim()}' — component recipes live only in tokens.css (§6 item 5)`,
          });
        }
      } else {
        for (const m of codeOnly.matchAll(/["']--([a-zA-Z0-9-]+)["']\s*:/g)) {
          if (canonNames.has(m[1])) {
            violations.push({
              file: rel, rule: "canon-literal",
              detail: `inline custom property '--${m[1]}' assigned in ${rel} — canon tokens are ` +
                `never re-stated outside tokens.css (AC 9)`,
            });
          }
        }
      }
    }

    // -- @theme wiring audit (globals.css only) --------------------------------
    const globalsPath = join(here, "globals.css");
    if (existsSync(globalsPath)) {
      const css = stripComments(readFileSync(globalsPath, "utf8"), "css");
      const themeDecl = new Map<string, string>();
      for (const block of themeBlocks(css)) {
        for (const m of block.matchAll(/--([a-zA-Z0-9-]+)\s*:\s*([^;{}]+)/g)) {
          if (!themeDecl.has(`--${m[1]}`)) themeDecl.set(`--${m[1]}`, m[2].trim());
        }
      }

      const want = (prop: string, check: (rhs: string) => string | null) => {
        const rhs = themeDecl.get(prop);
        if (rhs === undefined) {
          violations.push({
            file: "site/src/styles/globals.css", rule: "theme-wiring",
            detail: `${prop} missing — §6.2/§6.3 requires this mapping`,
          });
          return;
        }
        const why = check(rhs);
        if (why) {
          violations.push({
            file: "site/src/styles/globals.css", rule: "theme-aliasing",
            detail: `${prop}: '${rhs}' — ${why}`,
          });
        }
      };
      const exact = (src: string) => (rhs: string) =>
        rhs.replace(/\s+/g, "") === `var(${src})`
          ? null
          : `must alias exactly var(${src}) (§6.2 aliasing law)`;
      const anyVar = () => (rhs: string) =>
        VAR_FORM.test(rhs)
          ? null
          : `right side must be a var() reference into the canon stacks — never a literal, ` +
            `COLOR OR NON-COLOR (§6.2 r1/r1b; AC 9's failing command)`;

      for (const [prop, src] of GAME_EXACT) want(prop, exact(src));
      for (const prop of GAME_VARFORM_ONLY) want(prop, anyVar());
      for (let n = 1; n <= 8; n++) want(`--spacing-g${n}`, exact(`--space-${n}`));

      if (!/color-scheme\s*:\s*dark/.test(css)) {
        violations.push({
          file: "site/src/styles/globals.css", rule: "base-layer",
          detail: "base layer must declare color-scheme: dark (§6 item 4)",
        });
      }
      if (/\.dark\b\s*[,{]/.test(css)) {
        violations.push({
          file: "site/src/styles/globals.css", rule: "dark-variant",
          detail: "no .dark variant exists — :root IS dark (F1 canon, §6 item 4)",
        });
      }
    }
  } catch (e) {
    setupError = e as Error;
  }
});

function fail(rule: string, title: string): void {
  if (setupError) throw new Error(`shell-hygiene setup failed: ${setupError.message}`);
  // A missing sweep target poisons EVERY law: an absence assertion over a
  // shell that does not exist is vacuously green, which the red-first
  // contract forbids.
  const hits = [
    ...violations.filter((v) => v.rule === "sweep-target"),
    ...violations.filter((v) => v.rule === rule && rule !== "sweep-target"),
  ];
  expect(
    hits.map((v) => `${v.file}: ${v.detail}`).join("\n  "),
    `${title}\n  ${hits.length} violation(s)`
  ).toBe("");
}

describe("§7.5 sweep scope", () => {
  it("finds components/, app/ and globals.css on disk", () => {
    if (setupError) throw new Error(`setup failed: ${setupError.message}`);
    fail("sweep-target", "every §7.5 sweep target must exist");
    expect(sweptFiles.length).toBeGreaterThan(0);
  });

  it("never sweeps the F1 canon itself", () => {
    expect(
      sweptFiles.filter((f) => f.endsWith("tokens.css") || f.endsWith("tokens.test.ts")),
      "tokens.css/tokens.test.ts are excluded from the sweep"
    ).toEqual([]);
  });
});

describe("AC 10 — stock vocabulary absent from shell/app sources", () => {
  it("has zero stock-palette classes (slate|gray|zinc|neutral|stone-*-N)", () =>
    fail("stock-palette", "no stock Tailwind palette classes"));

  it("has zero raw numeric spacing utilities (game rhythm rides --spacing-g*)", () =>
    fail("numeric-spacing", "no raw numeric spacing utilities (§6.3)"));

  it("has zero rounded-* corner utilities (square is canon, r1b)", () =>
    fail("rounded-corner", "no rounded-* corner utilities"));

  it("has zero oklch( occurrences", () => fail("oklch", "no oklch( in swept sources"));
});

describe("AC 9 — the canon is never duplicated (color AND non-color)", () => {
  it("redeclares canon tokens only in var() aliasing form, outside tokens.css", () =>
    fail("canon-literal", "canon-token redeclaration outside tokens.css"));

  it("declares no --radius-* in globals.css at all (§6 r1b)", () =>
    fail("radius-ban", "--radius-* must not appear in globals.css"));

  it("defines token recipes (.wt-panel/.rarity-tier-*/moveGradient) only in tokens.css", () =>
    fail("recipe-redefinition", "second definition of a tokens.css recipe"));
});

describe("§6 token wiring", () => {
  it("maps the enumerated game tokens and shadcn slots through var() aliases", () => {
    fail("theme-wiring", "@theme wiring completeness");
    fail("theme-aliasing", "@theme aliasing law (var() right sides)");
  });

  it("ships the dark-only base layer (color-scheme: dark, no .dark variant)", () => {
    fail("base-layer", "base layer color-scheme");
    fail("dark-variant", "no .dark variant");
  });
});
