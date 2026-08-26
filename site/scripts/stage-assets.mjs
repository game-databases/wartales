#!/usr/bin/env node
/**
 * F4 §7 — fonts/texture staging per the two public/ READMEs, plus the r1
 * missing-ref reporter.
 *
 *   node scripts/stage-assets.mjs --check   # report missing refs, exit code verdict
 *   node scripts/stage-assets.mjs           # stage what can be staged
 *
 * The served contract is parsed from src/styles/tokens.css itself (single
 * source): every url("/fonts/*.woff2") and url("/assets/ui/*.png") must
 * exist under site/public/. AC 12's fresh-clone leg is THIS script's
 * `--check` pair: exits nonzero before staging, zero after.
 *
 * Binaries are never committed (pack convention); textures are copied from
 * design/extracted-ui/ byte-exact (assets/ui README), fonts are fetched from
 * Google Fonts under the exact @font-face filenames (fonts README). The EB
 * Garamond 700 variable-font trap (fonts README §"NOT downloadable as a
 * file") is DETECTED here (byte-collide against the 400) and reported with
 * the README's instancing procedure rather than silently shipping a
 * synthetic-bold photocopy.
 */

import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const siteRoot = join(here, "..");
const tokensCss = readFileSync(join(siteRoot, "src", "styles", "tokens.css"), "utf8");
const publicDir = join(siteRoot, "public");

const FONT_RE = /^\/fonts\/[a-z0-9-]+\.woff2$/;
const TEX_RE = /^\/assets\/ui\/[A-Za-z0-9]+\.png$/;

const refs = [...tokensCss.matchAll(/url\("([^"]+)"\)/g)]
  .map((m) => m[1])
  .filter((href) => FONT_RE.test(href) || TEX_RE.test(href));

const fontRefs = refs.filter((r) => r.startsWith("/fonts/"));
const texRefs = refs.filter((r) => r.startsWith("/assets/ui/"));

const missing = () => refs.filter((href) => !existsSync(join(publicDir, href)));

const FETCH_HINTS = {
  "/fonts/": [
    "# Fonts README route A (Google Fonts css2, OFL 1.1):",
    'curl -LO "https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,700;1,400&family=IM+Fell+English&display=swap" -A "Mozilla/5.0"',
    "# download each woff2 to site/public/fonts/ under its contract name;",
    "# see site/public/fonts/README.md (incl. the 700 instancing rule).",
  ],
  "/assets/ui/": [
    "# Textures README (byte-exact copies from the extracted UI set):",
    "cp design/extracted-ui/{dialogBg,HeaderBg,SmallEntryBG,buttonBg,RarityBackground,ListHeader,ListHeaderHighlight}.png site/public/assets/ui/",
  ],
};

function reportCheck() {
  const gone = missing();
  if (gone.length === 0) {
    console.log(`OK all ${refs.length} declared refs staged (${fontRefs.length} fonts, ${texRefs.length} textures)`);
    return 0;
  }
  console.log(`MISSING ${gone.length} of ${refs.length} declared refs:`);
  for (const href of gone) {
    console.log(`  MISSING ${href}`);
    const family = href.startsWith("/fonts/") ? "/fonts/" : "/assets/ui/";
    for (const line of FETCH_HINTS[family]) console.log("    " + line);
  }
  return 1;
}

/* ------------------------------ staging ---------------------------------- */

async function fetchBuffer(url, headers) {
  const res = await fetch(url, { headers });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${url}`);
  return Buffer.from(await res.arrayBuffer());
}

/** Pull one woff2 URL out of Google's css2 response for a face. */
function pickFontUrl(css, { family, weight, style, latinExt }) {
  const blocks = css.split("@font-face").slice(1);
  for (const block of blocks) {
    const fam = /font-family:\s*'([^']+)'/.exec(block)?.[1];
    const wght = /font-weight:\s*(\d+)/.exec(block)?.[1];
    const styl = /font-style:\s*(\w+)/.exec(block)?.[1];
    const range = /unicode-range:\s*([^;]+)/.exec(block)?.[1] ?? "";
    const url = /url\((https:[^)]+\.woff2)\)/.exec(block)?.[1];
    if (!url) continue;
    if (fam !== family || String(wght) !== String(weight) || styl !== style) continue;
    const isExt = range.includes("U+0100");
    if (latinExt !== undefined && isExt !== latinExt) continue;
    if (latinExt === undefined && isExt) continue;
    return url;
  }
  return null;
}

async function stageFonts() {
  const dir = join(publicDir, "fonts");
  mkdirSync(dir, { recursive: true });
  const ua = { "User-Agent": "Mozilla/5.0" };
  const cssUrl =
    "https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,700;1,400&family=IM+Fell+English&display=swap";
  console.log(`fetching font CSS ${cssUrl}`);
  const css = (await fetchBuffer(cssUrl, ua)).toString("utf8");

  const plan = [
    { file: "eb-garamond-latin-400-normal.woff2", fam: "EB Garamond", w: 400, s: "normal", ext: false },
    { file: "eb-garamond-latin-ext-400-normal.woff2", fam: "EB Garamond", w: 400, s: "normal", ext: true },
    { file: "eb-garamond-latin-700-normal.woff2", fam: "EB Garamond", w: 700, s: "normal", ext: false },
    { file: "eb-garamond-latin-400-italic.woff2", fam: "EB Garamond", w: 400, s: "italic", ext: false },
    { file: "im-fell-english-latin-400-normal.woff2", fam: "IM Fell English", w: 400, s: "normal", ext: false },
  ];

  const buffers = new Map();
  for (const p of plan) {
    const url = pickFontUrl(css, { family: p.fam, weight: p.w, style: p.s, latinExt: p.ext });
    if (!url) throw new Error(`no css2 block matched ${p.file}`);
    const buf = await fetchBuffer(url, ua);
    buffers.set(p.file, buf);
    writeFileSync(join(dir, p.file), buf);
    console.log(`staged /fonts/${p.file} (${buf.length} bytes)`);
  }

  // Variable-font trap (fonts README): the css2 700 must be a DISTINCT cut,
  // not the same VF file photocopied under a second name.
  const w400 = buffers.get("eb-garamond-latin-400-normal.woff2");
  const w700 = buffers.get("eb-garamond-latin-700-normal.woff2");
  if (w400 && w700 && w400.equals(w700)) {
    console.error(
      [
        "COLLISION: eb-garamond-latin-700-normal.woff2 is byte-identical to the 400",
        "(variable-font trap). Instantiate the 700 per site/public/fonts/README.md:",
        '  fonttools varLib.instancer -> instantiateVariableFont(f, {"wght": 700}),',
        "  fix name IDs 1/2/4/6 + head.macStyle + OS/2.fsSelection, save as woff2.",
        "Verify before done: byte-distinct from the 400 and usWeightClass == 700.",
      ].join("\n"),
    );
    return false;
  }
  return true;
}

function stageTextures() {
  const dir = join(publicDir, "assets", "ui");
  mkdirSync(dir, { recursive: true });
  const srcDir = join(siteRoot, "..", "design", "extracted-ui");
  let ok = true;
  for (const ref of texRefs) {
    const name = ref.slice("/assets/ui/".length);
    const src = join(srcDir, name);
    const dst = join(dir, name);
    if (existsSync(dst)) {
      console.log(`/assets/ui/${name} already staged`);
      continue;
    }
    if (existsSync(src)) {
      copyFileSync(src, dst);
      console.log(`staged /assets/ui/${name} <- design/extracted-ui/${name}`);
    } else {
      console.error(`cannot stage /assets/ui/${name}: ${src} not found on this machine`);
      ok = false;
    }
  }
  return ok;
}

const checkOnly = process.argv.includes("--check");
if (checkOnly) {
  process.exit(reportCheck());
}

let staged = true;
if (texRefs.length > 0) staged = stageTextures() && staged;
if (fontRefs.length > 0 && fontRefs.some((r) => missing().includes(r))) {
  try {
    staged = (await stageFonts()) && staged;
  } catch (err) {
    console.error(`font fetch failed: ${err.message}`);
    for (const line of FETCH_HINTS["/fonts/"]) console.error(line);
    staged = false;
  }
}
process.exit(reportCheck());
