// Token-parity tests — F1 (design/spec-tokens.mdx §6).
// Runs under vitest (node env): parses site/src/styles/tokens.css directly,
// no browser needed. The Playwright rendered-page crawl (§6.3, templates ×
// locales) arrives with the first real pages; the token-level floor lives here.
import { describe, expect, it } from "vitest";
import { readFileSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
// @ts-expect-error — jpeg-js ships no type declarations; runtime API is { decode }
import jpeg from "jpeg-js";

const here = dirname(fileURLToPath(import.meta.url));
const raw = readFileSync(join(here, "tokens.css"), "utf8");
const css = raw.replace(/\/\*[\s\S]*?\*\//g, ""); // strip comments

// ---- parse custom properties ----------------------------------------------

const decls = new Map<string, string>();
for (const m of css.matchAll(/--([a-zA-Z0-9-]+)\s*:\s*([^;{}]+)[;{}]/g)) {
  if (!decls.has(m[1])) decls.set(m[1], m[2].trim());
}
const get = (name: string): string => {
  const v = decls.get(name.replace(/^--/, ""));
  expect(v, `token ${name} must be defined`).toBeDefined();
  return v as string;
};
/** Follow var(--x) aliases down to a literal. */
function resolve(name: string): string {
  let v = get(name);
  for (let i = 0; i < 8; i++) {
    const m = v.match(/^var\(--([a-zA-Z0-9-]+)\)$/);
    if (!m) return v;
    v = get(m[1]);
  }
  throw new Error(`alias chain too deep at ${name}`);
}

// ---- WCAG relative luminance / contrast -----------------------------------

function luminance(hex: string): number {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  const lin = (c: number) =>
    c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}
function contrast(fg: string, bg: string): number {
  const [a, b] = [luminance(fg), luminance(bg)].sort((x, y) => y - x);
  return (a + 0.05) / (b + 0.05);
}
const ratio = (fgToken: string, bgToken: string) =>
  contrast(resolve(fgToken), resolve(bgToken));

const SURFACES = ["bg-1", "bg-2", "bg-3", "bg-4", "panel-well"] as const;

describe("shadcn variable coverage (AC 5.2)", () => {
  // Full shipped stock set — every name must exist in :root.
  const SHADCN_VARS = [
    "--background", "--foreground",
    "--card", "--card-foreground",
    "--popover", "--popover-foreground",
    "--primary", "--primary-foreground",
    "--secondary", "--secondary-foreground",
    "--muted", "--muted-foreground",
    "--accent", "--accent-foreground",
    "--destructive", "--destructive-foreground",
    "--border", "--input", "--ring",
    "--chart-1", "--chart-2", "--chart-3", "--chart-4", "--chart-5",
    "--sidebar", "--sidebar-foreground",
    "--sidebar-primary", "--sidebar-primary-foreground",
    "--sidebar-accent", "--sidebar-accent-foreground",
    "--sidebar-border", "--sidebar-ring",
    "--radius", "--font-sans", "--font-serif", "--font-mono",
  ];

  it("defines every stock shadcn variable", () => {
    const missing = SHADCN_VARS.filter((v) => !decls.has(v.slice(2)));
    expect(missing, `missing: ${missing.join(", ")}`).toEqual([]);
  });

  it("carries no stock shadcn literals anywhere in the file", () => {
    // Spec §6.1(a) default set: oklch white, HSL-percent white, default
    // radius, default ring. Stronger form: zero oklch() at all — every color
    // in this file is a game-extracted hex or rgb composition.
    expect(css).not.toContain("oklch(");
    expect(css).not.toContain("0 0% 100%");
    expect(css).not.toContain("--radius: 0.625rem");
    expect(css.toLowerCase()).not.toContain("0.625rem");
  });

  it("maps shadcn slots to the spec §2.6 game values verbatim", () => {
    const expected: Record<string, string> = {
      background: "#100F0E",
      foreground: "#9C988A",
      card: "#1B150F",
      "card-foreground": "#DDD8C5",
      popover: "#0C0B09",
      "popover-foreground": "#DDD8C5",
      primary: "#D8A519",
      "primary-foreground": "#1B150F",
      secondary: "#242424",
      "secondary-foreground": "#BEBDBC",
      muted: "#1B1816",
      "muted-foreground": "#969696",
      accent: "#2E2B26", // arbiter F1: buttonBg.png hover-frame mean
      "accent-foreground": "#FFFFFF",
      destructive: "#B63131",
      "destructive-foreground": "#FFF7DB",
      border: "#36322A",
      input: "#494339",
      ring: "#D8A519",
      "chart-1": "#D3B25E",
      "chart-2": "#529B52",
      "chart-3": "#E4696B",
      "chart-4": "#85C1E3",
      "chart-5": "#B5AADE",
      sidebar: "#100F0E",
      "sidebar-foreground": "#9C988A",
      "sidebar-primary": "#D8A519",
      "sidebar-primary-foreground": "#1B150F",
      "sidebar-accent": "#141311",
      "sidebar-accent-foreground": "#DDD8C5",
      "sidebar-border": "#36322A",
      "sidebar-ring": "#D8A519",
    };
    for (const [name, want] of Object.entries(expected)) {
      // resolve(): a slot may legally alias another token (declared once,
      // review T2) — byte parity still ends at the spec's literal.
      expect(resolve(name), `--${name}`).toBe(want);
    }
  });
});

describe("rarity system byte parity (AC 6.1c)", () => {
  it("wash tokens equal the sampled RarityBackground.png frame fills", () => {
    expect(get("rarity-1")).toBe("#151A1E"); // uncommon — steel-blue-black
    expect(get("rarity-2")).toBe("#272310"); // rare — olive-gold-black
    expect(get("rarity-3")).toBe("#251724"); // legendary — violet-black
  });

  it("light tiers equal the item-tip.rarity_* name colors", () => {
    expect(get("light-rarity-1")).toBe("#AAAAFF"); // .rarity_u (#AAF)
    expect(get("light-rarity-2")).toBe("#FFFFAA"); // .rarity_r (#FFA)
    expect(get("light-rarity-3")).toBe("#FF88FF"); // .rarity_legendary (#F8F)
  });

  it("ships the full scale incl. common-no-frame and tip tints", () => {
    for (const n of ["rarity-0", "rarity-1-wash", "rarity-2-wash", "rarity-3-wash"]) {
      expect(decls.has(n)).toBe(true);
    }
    expect(get("rarity-0")).toBe("#BEBDBC"); // untinted neutral, common shows no frame
  });

  it("keeps player identity separate from rarity (§3 warning)", () => {
    const players = [1, 2, 3, 4].map((i) => get(`player-${i}`));
    const rarity = [0, 1, 2, 3].map((i) => get(`rarity-${i}`));
    for (const p of players) expect(rarity).not.toContain(p);
  });
});

describe("radius (AC 6.1d + §2.4)", () => {
  it("is 0 — every game surface is square", () => {
    expect(parseFloat(get("radius"))).toBe(0);
    for (const n of ["radius-sm", "radius-md", "radius-lg", "radius-xl"]) {
      expect(parseFloat(decls.get(n)!)).toBe(0);
    }
  });
});

describe("contrast matrix (AC 6.2)", () => {
  // Expected ratios below are the numbers printed in the spec's own tables;
  // the implementation recomputes them from the tokens (WCAG 2.x formula).
  const close = (got: number, want: number) =>
    expect(got).toBeCloseTo(want, 1);

  it("body text passes AA on every surface it can ship on", () => {
    for (const t of ["foreground", "text-emph", "text-desc", "text-bright", "text-muted"]) {
      for (const s of SURFACES) {
        expect(ratio(t, s), `${t} on ${s}`).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it("reproduces the spec's printed ratios exactly", () => {
    close(ratio("foreground", "bg-3"), 6.26); // --text-main ×160
    close(ratio("text-emph", "bg-3"), 12.67);
    close(ratio("text-desc", "bg-3"), 6.12);
    close(ratio("text-bright", "bg-3"), 9.64);
    close(ratio("text-disabled", "bg-3"), 5.1);
  });

  it("scopes disabled text to well surfaces (4.38:1 on raised chips)", () => {
    // button.disabled rides button/dialog chrome over the dark wells in-game;
    // on --bg-4 chips it would drop to 4.38 — so it ships on wells only.
    for (const s of ["bg-1", "bg-2", "bg-3", "panel-well"] as const) {
      expect(ratio("text-disabled", s), `disabled on ${s}`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("light rarity tiers pass AA on every surface (8.53 / 17.35 / 8.80 on card)", () => {
    for (const t of ["light-rarity-1", "light-rarity-2", "light-rarity-3"]) {
      for (const s of SURFACES) {
        expect(ratio(t, s), `${t} on ${s}`).toBeGreaterThanOrEqual(4.5);
      }
    }
    close(ratio("light-rarity-1", "bg-3"), 8.53);
    close(ratio("light-rarity-2", "bg-3"), 17.35);
    close(ratio("light-rarity-3", "bg-3"), 8.8);
  });

  it("positive green passes AA everywhere", () => {
    for (const s of SURFACES) {
      expect(ratio("positive", s), `positive on ${s}`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("text-facing negative is #E4696B and passes AA; the fill red never carries text", () => {
    expect(resolve("negative").toUpperCase()).toBe("#E4696B");
    for (const s of SURFACES) {
      expect(ratio("negative", s), `negative on ${s}`).toBeGreaterThanOrEqual(4.5);
    }
    // §2.3 ban: #B63131 fails as text on dark (2.99:1) — fill role only.
    expect(resolve("negative-fill").toUpperCase()).toBe("#B63131");
    const textTokens = [...decls.keys()].filter((n) => n.startsWith("text-"));
    for (const t of textTokens) {
      expect(resolve(t).toUpperCase(), `--${t} must not be the fill red`).not.toBe("#B63131");
    }
    expect(ratio("destructive-foreground", "destructive")).toBeGreaterThanOrEqual(4.5);
    close(ratio("destructive-foreground", "destructive"), 5.64);
  });

  it("constrains warning gold to its allowed surface/size combinations", () => {
    // §2.3: body-size only on the darkest wells; elsewhere large-text/fill only.
    expect(ratio("warning", "bg-1")).toBeGreaterThanOrEqual(4.5);
    expect(ratio("warning", "panel-well")).toBeGreaterThanOrEqual(4.5);
    for (const s of ["bg-2", "bg-3", "bg-4"] as const) {
      expect(ratio("warning", s), `warning on ${s} (large/fill)`).toBeGreaterThanOrEqual(3);
    }
    close(ratio("warning", "bg-3"), 4.29);
    close(ratio("warning", "bg-1"), 4.54);
  });

  it("hover wash and gold selection pairs pass AA", () => {
    expect(ratio("accent-foreground", "accent")).toBeGreaterThanOrEqual(4.5);
    expect(ratio("primary-foreground", "primary")).toBeGreaterThanOrEqual(4.5);
  });
});

describe("typography (§1, AC 6.3 floor)", () => {
  const px = (v: string) => {
    const n = parseFloat(v);
    return v.endsWith("rem") ? n * 16 : n;
  };

  it("keeps every length-valued text-* token on the ramp, ≥12px", () => {
    // Structural enumeration: ANY --text-* whose value is itself a size obeys
    // the floor and the §1 ramp — a future --text-xs cannot evade the check by
    // being absent from a name list. Off-ramp outlier sizes (§7 residue) join
    // the ramp constant deliberately, never silently.
    const RAMP = [14, 16, 19, 22, 25];
    const sizes = [...decls.keys()]
      .filter((n) => n.startsWith("text-"))
      .map((n) => [n, decls.get(n)!] as const)
      .filter(([, v]) => /^[\d.]+(px|rem)$/.test(v))
      .map(([n, v]) => [n, px(v)] as const);
    expect(sizes.length).toBeGreaterThan(0);
    for (const [n, v] of sizes) {
      expect(v, `--${n} below the 12px owner floor`).toBeGreaterThanOrEqual(12);
      expect(RAMP, `--${n} = ${v}px is off-ramp — extend §1/§7 consciously`).toContain(v);
    }
  });

  it("matches the game's own ramp: 14 · 16 · 19 · 22 · 25", () => {
    expect(px(get("text-sm"))).toBe(14);
    expect(px(get("text-base"))).toBe(16);
    expect(px(get("text-dialog"))).toBe(19);
    expect(px(get("text-lg"))).toBe(22);
    expect(px(get("text-display"))).toBe(25);
  });

  it("is serif-first: sans re-pointed at EB Garamond, CJK kept behind", () => {
    expect(get("font-ui")).toContain('"EB Garamond"');
    expect(get("font-flavor")).toContain('"IM Fell English"');
    expect(resolve("font-sans")).toBe(get("font-ui"));
    expect(resolve("font-serif")).toBe(get("font-flavor"));
    expect(resolve("font-mono")).toBe(get("font-ui"));
    expect(get("font-cjk")).toContain("Noto Sans CJK SC");
    expect(get("font-cjk")).not.toBe(get("font-ui"));
    expect(get("font-weight-bold")).toBe("700");
  });
});

describe("spacing scale (§2.4)", () => {
  it("uses the game's 5px-base rhythm, strictly ascending", () => {
    const vals = [1, 2, 3, 4, 5, 6, 7, 8].map((i) => parseFloat(decls.get(`space-${i}`)!));
    expect(vals.map(String)).toEqual(["2", "3", "4", "5", "8", "10", "15", "20"]);
  });
});

// ---- served refs (critique r4 carried item 2 — latent-404 guard) -----------

const publicDir = join(here, "..", "..", "public");

describe("served refs — every url() target exists on disk", () => {
  // critique-tokens-r4.mdx carried item 2: --tex-list-header{,-highlight} were
  // declared against binaries staged nowhere — a latent 404 nothing watched.
  // Both are now extracted + staged (EXTRACT-LOG 2026-08-25); this keeps the
  // zero-missing-refs property permanent for every texture and font the
  // contract declares, plus every file:// re-point the preview makes.
  const refsOf = (text: string) =>
    [...text.matchAll(/url\("([^"]+)"\)/g)].map((m) => m[1]);

  it("resolves each tokens.css url() under site/public", () => {
    const refs = refsOf(raw);
    expect(refs.length, "7 --tex-* + 5 @font-face refs expected").toBeGreaterThanOrEqual(12);
    const missing = refs.filter((href) => !existsSync(join(publicDir, href)));
    expect(missing, `missing from site/public: ${missing.join(", ")}`).toEqual([]);
  });

  it("resolves each preview url() from site/src/styles/", () => {
    const html = readFileSync(join(here, "tokens-preview.html"), "utf8");
    const refs = refsOf(
      html.replace(/<!--[\s\S]*?-->/g, "").replace(/\/\*[\s\S]*?\*\//g, "")
    );
    expect(refs.length, "5 font faces + 4 texture re-points expected").toBeGreaterThanOrEqual(9);
    const missing = refs
      .filter((href) => !href.startsWith("data:"))
      .filter((href) => !existsSync(join(here, href)));
    expect(missing, `missing beside the preview: ${missing.join(", ")}`).toEqual([]);
  });
});

// ---- --panel-alpha against real art (critique r1 gap 3 / r4 carried 1) -----

describe("--panel-alpha composited over shot-20 firelight", () => {
  // Oldest open gap r1→r4: the token layer only ever certified panels over
  // flat --bg-1. This exercises the claim the way the game ships it — the
  // well literal at the declared background-alpha, composited over real art —
  // by decoding shot-20 itself in-test. Sampled pool = brightest decile of
  // pixels: the firelight pool a panel plausibly floats over, excluding the
  // specular core (where even the game's own band top, α=0.8, is below AA for
  // the body voice — panels never sit on the flame itself).
  const SHOT = join(
    here, "..", "..", "..", "design", "sources", "shot-20-camp-firelight-texture.jpg"
  );
  const POOL_FRAC = 0.10;
  /** Mean RGB of the brightest `frac` fraction of pixels, deterministic. */
  function firelightPool(data: Uint8Array, w: number, h: number): [number, number, number] {
    const n = w * h;
    const hist = new Array<number>(256).fill(0);
    const ys = new Uint8Array(n);
    for (let i = 0; i < n; i++) {
      const y = Math.min(
        255,
        Math.round(0.2126 * data[i * 4] + 0.7152 * data[i * 4 + 1] + 0.0722 * data[i * 4 + 2])
      );
      ys[i] = y;
      hist[y]++;
    }
    let acc = 0;
    let cut = 255;
    const want = Math.max(1, Math.round(n * POOL_FRAC));
    for (let v = 255; v >= 0; v--) {
      acc += hist[v];
      if (acc >= want) { cut = v; break; }
    }
    let r = 0, g = 0, b = 0, m = 0;
    for (let i = 0; i < n; i++) {
      if (ys[i] >= cut) { r += data[i * 4]; g += data[i * 4 + 1]; b += data[i * 4 + 2]; m++; }
    }
    return [r / m, g / m, b / m];
  }
  const rgbOf = (hex: string): [number, number, number] => {
    const h = hex.replace("#", "");
    return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as [number, number, number];
  };
  /** WCAG contrast of a token color against an arbitrary rgb surface. */
  function contrastOver(fgHex: string, bgRgb: readonly number[]): number {
    const lin = (u: number) =>
      u <= 0.04045 ? u / 12.92 : Math.pow((u + 0.055) / 1.055, 2.4);
    const L = (c: readonly number[]) =>
      0.2126 * lin(c[0] / 255) + 0.7152 * lin(c[1] / 255) + 0.0722 * lin(c[2] / 255);
    const [a, b] = [L(rgbOf(fgHex)), L(bgRgb)].sort((x, y) => y - x);
    return (a + 0.05) / (b + 0.05);
  }

  it("stays inside the game's own background-alpha band 0.7–0.8", () => {
    const a = parseFloat(get("panel-alpha"));
    expect(a).toBeGreaterThanOrEqual(0.7);
    expect(a).toBeLessThanOrEqual(0.8);
  });

  it("holds AA for every body voice over the sampled firelight at the token value", () => {
    const img = jpeg.decode(readFileSync(SHOT), { useTArray: true });
    expect(img.width).toBeGreaterThan(1000);
    const pool = firelightPool(img.data as Uint8Array, img.width, img.height);
    const poolY = 0.2126 * pool[0] + 0.7152 * pool[1] + 0.0722 * pool[2];
    // guard the sampler against silently pooling shadow instead of firelight
    expect(poolY, "firelight pool must be genuinely bright art").toBeGreaterThanOrEqual(110);

    const alpha = parseFloat(get("panel-alpha"));
    const panelRgb = get("panel-well-rgb").split(/\s+/).map(Number);
    // css rgb(r g b / α) over the sampled art pixel
    const surface = panelRgb.map((c, i) => alpha * c + (1 - alpha) * pool[i]);
    // Measured at α=0.7 over this pool (PIL mirror): text-main 4.68,
    // text-desc 4.57 (tightest), text-emph 9.46 — all above the AA floor.
    for (const v of ["foreground", "text-emph", "text-desc", "text-bright", "text-muted"]) {
      expect(contrastOver(resolve(v), surface), `${v} over the firelit wash`).toBeGreaterThanOrEqual(4.5);
    }
  });
});
