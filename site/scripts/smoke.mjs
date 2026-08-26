#!/usr/bin/env node
// F4 §7.6 / §8 — scripts/smoke.mjs: the executable AC runner (exit-code
// verdict). Spec: docs/spec-f4-app-shell.mdx; brief:
// docs/briefs/testwriter-f4-shell.mdx.
//
//   node scripts/smoke.mjs [--live]
//
// ARMING (the documented env check): every leg that needs the dev server is
// guarded so bare offline invocations stay honest instead of hanging or
// failing spuriously —
//
//     WARTALES_SMOKE_LIVE=1   or the --live flag
//
// arms them: the runner boots `next dev` on a scratch port (cwd site/, never
// :3000), waits for readiness, curls the §8 matrix, scans the boot/request
// log — a compile error there is itself a FAIL, which is how AC 1 is
// DETECTED rather than asserted — then tears the server down. Disarmed,
// every server leg prints an explicit SKIP line (pack convention: the same
// honesty contract as the pipeline suites' --run-integration opt-in); the
// dev-server-free legs (the stage-assets --check pair, AC 12 fresh-clone)
// still execute either way. Exit code is nonzero iff any check FAILED.
//
//     WARTALES_SMOKE_BUILD=1   or the --build flag
//
// arms the AC 14 production-build leg (M-2 fix, review-f4-tests r1): runs
// `next build`, then asserts all nine locale homes prerendered STATIC in
// `.next/prerender-manifest.json` (dist-document fallback). It executes
// AFTER the dev server is torn down — a live `next dev` owns `.next` — and
// is disarmed by default so bare offline runs never pay build cost.
//
// r1 fix round (review-f4-tests): m-1 switch links scoped to the combobox
// row · m-2 empty-map guards on all absence legs · m-3 nav bound to live
// manifest rows · m-7 blocking verified teardown + port redraw · m-9
// invented F5 affordance guess removed.
//
// Prints one PASS/FAIL/SKIP line per check. Written against the spec alone
// (BLIND parallel with the CodeWriter): passes against a CONFORMANT F4,
// fails against a missing/nonconformant one.

import { spawn, spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "node:net";

const here = dirname(fileURLToPath(import.meta.url)); // site/scripts
const siteRoot = dirname(here);

// ---- §2 table ---------------------------------------------------------------

const LOCALES = [
  { id: "en", bcp47: "en", bare: true },
  { id: "fr", bcp47: "fr" },
  { id: "de", bcp47: "de" },
  { id: "es", bcp47: "es" },
  { id: "pl", bcp47: "pl" },
  { id: "pt-br", bcp47: "pt-BR" },
  { id: "ru", bcp47: "ru" },
  { id: "ko", bcp47: "ko" },
  { id: "zh", bcp47: "zh-Hans" },
];
const HOMES = LOCALES.map((l) => (l.bare ? "/" : `/${l.id}`));
const BCP47 = Object.fromEntries(LOCALES.map((l) => [l.bare ? "/" : `/${l.id}`, l.bcp47]));
const HOME_ID = Object.fromEntries(LOCALES.map((l) => [l.bare ? "/" : `/${l.id}`, l.id]));
const PREFIXED_IDS = LOCALES.filter((l) => !l.bare).map((l) => l.id);
const CHROME_KEY_LEAK = /chrome\.(nav|header|locale|a11y|footer|notFound)\./;

// ---- harness ----------------------------------------------------------------

const armed =
  process.env.WARTALES_SMOKE_LIVE === "1" || process.argv.includes("--live");
const buildArmed =
  process.env.WARTALES_SMOKE_BUILD === "1" || process.argv.includes("--build");

/** @type {{status:string,id:string,detail:string}[]} */
const results = [];
function record(status, id, detail) {
  results.push({ status, id, detail });
  console.log(`${status.padEnd(5)} ${id} — ${detail}`);
}
function skipLine(ref, why) {
  console.log(`SKIP        ${ref} — ${why}`);
}

async function fetchx(url, opts = {}, timeoutMs = 20000) {
  return fetch(url, { signal: AbortSignal.timeout(timeoutMs), ...opts });
}

function drawFreePort() {
  return new Promise((resolve, reject) => {
    const srv = createServer();
    srv.unref();
    srv.on("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

/** True iff the port can be bound again right now (m-7 tripwire). */
function portRebindable(port) {
  return new Promise((resolve) => {
    const srv = createServer();
    srv.unref();
    srv.once("error", () => resolve(false));
    srv.listen(port, "127.0.0.1", () => srv.close(() => resolve(true)));
  });
}

/**
 * m-7 fix (review-f4-tests r1): freePort had a bind→close→spawn TOCTOU —
 * between close and `next dev`'s bind another process can take the port.
 * Re-bind the drawn port as a tripwire and redraw on loss (best effort; the
 * residual window is inherent to not owning the socket).
 */
async function freePort() {
  for (let i = 0; i < 5; i++) {
    const port = await drawFreePort();
    if (await portRebindable(port)) return port;
  }
  throw new Error("could not draw a scratch port — lost the bind race 5×");
}

// ---- tiny HTML tooling (dependency-free, spec-derived only) -------------------

const stripTags = (s) => s.replace(/<[^>]*>/g, "");
const VOID_TAGS = new Set(["area","base","br","col","embed","hr","img","input","link","meta","source","track","wbr"]);
const OPEN_TAG = /<([a-zA-Z][a-zA-Z0-9-]*)((?:"[^"]*"|'[^']*'|[^>])*?)>/g;

function htmlLang(html) {
  const m = /<html\b[^>]*\blang\s*=\s*"([^"]*)"/i.exec(html);
  return m ? m[1] : null;
}

function escapeRx(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** First element whose opening tag carries `attr` (optionally `="value"`). */
function findElementByAttr(html, attr, value) {
  const probe = value
    ? new RegExp(`[\\s"']${escapeRx(attr)}\\s*=\\s*"${escapeRx(value)}"`)
    : new RegExp(`[\\s"']${escapeRx(attr)}(?:\\s*=|[\\s/>])`);
  OPEN_TAG.lastIndex = 0;
  let m;
  while ((m = OPEN_TAG.exec(html))) {
    if (!probe.test(m[2])) continue;
    const tagName = m[1];
    const start = m.index;
    const innerStart = start + m[0].length;
    if (VOID_TAGS.has(tagName.toLowerCase())) {
      return { tag: tagName, start, end: innerStart, inner: "" };
    }
    const scan = new RegExp(`<(/?)${escapeRx(tagName)}\\b(?:"[^"]*"|'[^']*'|[^>])*?>`, "gi");
    scan.lastIndex = start;
    let depth = 0;
    let c;
    while ((c = scan.exec(html))) {
      depth += c[1] ? -1 : 1;
      if (depth === 0) {
        return { tag: tagName, start, end: c.index + c[0].length, inner: html.slice(innerStart, c.index) };
      }
    }
    return { tag: tagName, start, end: html.length, inner: html.slice(innerStart) };
  }
  return null;
}

/** Every balanced <tag>…</tag> region (landmark counting, header/footer). */
function tagSpans(html, tagName) {
  const spans = [];
  const re = new RegExp(`<(/?)${escapeRx(tagName)}\\b(?:"[^"]*"|'[^']*'|[^>])*?>`, "gi");
  let open = null;
  let m;
  while ((m = re.exec(html))) {
    if (!open && !m[1]) open = { start: m.index, innerStart: m.index + m[0].length };
    else if (open && m[1]) {
      spans.push({ start: open.start, innerStart: open.innerStart, end: m.index, inner: html.slice(open.innerStart, m.index) });
      open = null;
    }
  }
  return spans;
}

function anchorsOf(html) {
  const out = [];
  const re = /<a\b([^>]*)>([\s\S]*?)<\/a>/gi;
  let m;
  while ((m = re.exec(html))) {
    const href = /href\s*=\s*"([^"]*)"/i.exec(m[1])?.[1] ?? "";
    out.push({ href, text: stripTags(m[2]).trim(), start: m.index, end: m.index + m[0].length });
  }
  return out;
}

/**
 * Direct children of an HTML fragment: [{kind:"el"}|{kind:"text",text}].
 * Whitespace-only text nodes are dropped — the emptiness law's noise floor.
 */
function topLevelChildren(inner) {
  const kids = [];
  const re = /<(\/?)([a-zA-Z][a-zA-Z0-9-]*)((?:"[^"]*"|'[^']*'|[^>])*?)(\/?)>/g;
  let depth = 0;
  let cursor = 0;
  let m;
  while ((m = re.exec(inner))) {
    const [full, close, tag, , selfClose] = m;
    if (depth === 0) {
      const between = inner.slice(cursor, m.index);
      if (between.trim() !== "") kids.push({ kind: "text", text: between });
    }
    if (close) {
      depth = Math.max(0, depth - 1);
    } else if (selfClose || VOID_TAGS.has(tag.toLowerCase())) {
      if (depth === 0) kids.push({ kind: "el" });
    } else {
      depth++;
      if (depth === 1) kids.push({ kind: "el" });
    }
    if (depth === 0) cursor = m.index + full.length;
  }
  const tail = inner.slice(cursor);
  if (tail.trim() !== "") kids.push({ kind: "text", text: tail });
  return kids;
}

function assetRefs(text) {
  return [...text.matchAll(/(\/fonts\/[^"'\s()>]+\.woff2|\/assets\/ui\/[^"'\s()>]+\.png)/g)].map(
    (m) => m[1]
  );
}

function stylesheetLinks(html) {
  const links = [];
  for (const m of html.matchAll(/<link\b([^>]*)>/gi)) {
    const attrs = m[1];
    links.push({
      rel: /rel\s*=\s*"([^"]*)"/i.exec(attrs)?.[1] ?? "",
      href: /href\s*=\s*"([^"]*)"/i.exec(attrs)?.[1] ?? "",
    });
  }
  return links;
}

// ---- armed-mode server control ------------------------------------------------

let devProc = null;
let devLog = "";

/**
 * m-7 fix (review-f4-tests r1): the kill is now BLOCKING (spawnSync, not a
 * fire-and-forget spawn) and the caller awaits actual process exit. The old
 * shape could leak the very server it tore down — and Next 16 allows one
 * dev server per directory, so a leak poisons every later armed run with a
 * boot-reachable FAIL.
 */
function killTree(proc) {
  try {
    if (process.platform === "win32") {
      return (
        spawnSync("taskkill", ["/PID", String(proc.pid), "/T", "/F"], {
          stdio: "ignore",
          timeout: 15000,
        }).status === 0
      );
    }
    proc.kill("SIGTERM");
    return true;
  } catch {
    return false; // already gone
  }
}

/** Resolves true once `proc` has exited, false on timeout. */
async function awaitExit(proc, ms) {
  const deadline = Date.now() + ms;
  while (proc.exitCode === null && Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 100));
  }
  return proc.exitCode !== null;
}

async function bootDev(port) {
  const bin = join(siteRoot, "node_modules", "next", "dist", "bin", "next");
  if (!existsSync(bin)) {
    throw new Error(
      "next is not installed (site/node_modules/next missing) — run `npm install` in site/ before arming the smoke run"
    );
  }
  devProc = spawn(process.execPath, [bin, "dev", "--port", String(port), "--hostname", "127.0.0.1"], {
    cwd: siteRoot,
    env: process.env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  devProc.stdout.on("data", (d) => (devLog += d.toString()));
  devProc.stderr.on("data", (d) => (devLog += d.toString()));
  devProc.on("exit", (code) => (devLog += `\n[next dev exited with ${code}]`));

  const base = `http://127.0.0.1:${port}`;
  const deadline = Date.now() + 240000;
  while (Date.now() < deadline) {
    if (devProc.exitCode !== null) break;
    try {
      await fetchx(`${base}/`, {}, 8000);
      return base; // answering — compiled or not, the legs judge from here
    } catch {
      /* not ready yet */
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(
    `next dev did not become reachable on :${port} within 240s\n--- boot log tail ---\n${devLog.slice(-2000)}`
      + `\n(hint: Next 16 allows ONE dev server per directory — an orphaned or foreign next dev holding site/ fails every boot here; check \`netstat -ano | findstr :${port}\` and the log tail above)`
  );
}

const COMPILE_ERRORS =
  /Failed to compile|Module not found|Syntax Error|Type error|Cannot find module|Unhandled Runtime Error/i;

// ---- contract loaders + guards (m-1/m-2/m-3 fixes) ------------------------------

/**
 * Live hrefs from src/lib/routes-manifest.ts (m-3): the nav-on-the-wire is
 * bound to the manifest's live rows, so smoke reads the same contract the
 * disk-level suite enforces. Tolerant flat-object scan; loud when nothing
 * qualifies.
 */
function manifestLiveHrefs() {
  const file = join(siteRoot, "src", "lib", "routes-manifest.ts");
  if (!existsSync(file)) throw new Error("site/src/lib/routes-manifest.ts missing");
  const out = [];
  for (const m of readFileSync(file, "utf8").matchAll(/\{[^{}]*\}/gs)) {
    if (!/\blive\s*:\s*true\b/.test(m[0])) continue;
    const href = /href\s*:\s*"([^"]+)"/.exec(m[0])?.[1];
    if (href) out.push(href);
  }
  if (out.length === 0) throw new Error("no live:true row with an href found in routes-manifest.ts");
  return out;
}

/** Resolves a locale-neutral manifest href onto a served page's home path. */
function resolveHome(home, href) {
  if (href === "/") return home;
  return home === "/" ? href : home.replace(/\/$/, "") + href;
}

/** chrome.locale.* label from a locale's own message file (§4 contract). */
function chromeMessage(id, key) {
  const file = join(siteRoot, "messages", `${id}.json`);
  let cursor = JSON.parse(readFileSync(file, "utf8"));
  for (const seg of ["chrome", ...key.split(".")]) {
    cursor = cursor?.[seg];
    if (cursor === undefined || cursor === null) {
      throw new Error(`messages/${id}.json lacks chrome.${key}`);
    }
  }
  return String(cursor);
}

/**
 * m-2 fix (review-f4-tests r1): absence laws refuse to PASS over an empty
 * pages map — if every root fetch died mid-run, a vacuous absence verdict
 * would be dishonest even though roots-nine still fails the overall exit.
 */
function pagesGuard(id) {
  if (pages.size > 0) return true;
  record("FAIL", id, "pages map empty — roots-nine already failed; refusing a vacuous absence PASS");
  return false;
}

// ---- legs ---------------------------------------------------------------------

/** @type {Map<string,{status:number,html:string}>} keyed by canonical home */
const pages = new Map();

async function legNineRoots(base) {
  let ok = 0;
  const bad = [];
  for (const home of HOMES) {
    try {
      const res = await fetchx(base + home, { redirect: "follow" }, 60000);
      const html = await res.text();
      pages.set(home, { status: res.status, html });
      if (res.status === 200) ok++;
      else bad.push(`${home}→${res.status}`);
    } catch (e) {
      bad.push(`${home}→${e.message}`);
    }
  }
  if (ok === HOMES.length) {
    record("PASS", "roots-nine", "all nine locale roots answered 200 (AC 2)");
  } else {
    record("FAIL", "roots-nine", `${ok}/${HOMES.length} answered 200: ${bad.join(", ")} (AC 2)`);
  }
}

function legLangAttrs() {
  const bad = [];
  for (const [home, page] of pages) {
    const got = htmlLang(page.html);
    if (got !== BCP47[home]) bad.push(`${home}→lang=${got} (want ${BCP47[home]})`);
  }
  if (pages.size > 0 && bad.length === 0) {
    record("PASS", "lang-attrs", "<html lang> takes the BCP-47 column ×9 (§3 rule 7)");
  } else {
    record("FAIL", "lang-attrs", bad.join("; "));
  }
}

async function legPivot301(base) {
  const targets = ["/en", ...PREFIXED_IDS.map((id) => `/en/${id}`)];
  const wantLoc = (t) => (t === "/en" ? "/" : t.slice("/en".length));
  const bad = [];
  for (const t of targets) {
    try {
      const res = await fetchx(base + t, { redirect: "manual" }, 30000);
      // Trailing-slash normalization must preserve the ROOT location "/":
      // /en's required Location IS "/", and stripping its slash to "" would
      // fail the comparison below against wantLoc("/en") === "/".
      const raw = res.headers.get("location") ?? "";
      const loc = raw.length > 1 && raw.endsWith("/") ? raw.slice(0, -1) : raw;
      if (res.status !== 301) bad.push(`${t}→${res.status} (want permanent 301)`);
      else if (loc !== wantLoc(t)) bad.push(`${t}→Location ${loc} (want ${wantLoc(t)})`);
    } catch (e) {
      bad.push(`${t}→${e.message}`);
    }
  }
  if (bad.length === 0) {
    record("PASS", "pivot-301", "/en + /en/<locale> answer permanent 301 to the unprefixed path ×9 (AC 3)");
  } else {
    record("FAIL", "pivot-301", `${bad.join("; ")} (AC 3)`);
  }
}

async function legNoNegotiation(base) {
  try {
    const res = await fetchx(base + "/", { headers: { "Accept-Language": "fr" }, redirect: "manual" });
    const loc = res.headers.get("location");
    const html = res.status === 200 ? await res.text() : "";
    if (res.status === 200 && !loc && htmlLang(html) === "en") {
      record("PASS", "no-negotiation", "`/` + Accept-Language: fr serves 200 EN at `/` (AC 4, §3 rule 4)");
    } else {
      record("FAIL", "no-negotiation", `status ${res.status}, Location ${loc}, lang ${htmlLang(html)} (AC 4)`);
    }
  } catch (e) {
    record("FAIL", "no-negotiation", `${e.message} (AC 4)`);
  }
}

async function legUnknownLocale404(base) {
  try {
    const res = await fetchx(base + "/xx/foo", { redirect: "manual" });
    const loc = res.headers.get("location");
    if (res.status === 404 && !loc) {
      record("PASS", "unknown-locale-404", "/xx/foo → 404, never a locale redirect (AC 4, §3 rule 5)");
    } else {
      record("FAIL", "unknown-locale-404", `status ${res.status}, Location ${loc} (AC 4)`);
    }
  } catch (e) {
    record("FAIL", "unknown-locale-404", e.message);
  }
}

async function legLocaleDeepMiss404(base) {
  try {
    const res = await fetchx(base + "/de/definitely-not-a-route", { redirect: "manual" });
    const html = await res.text();
    const problems = [];
    if (res.status !== 404) problems.push(`status ${res.status}`);
    if (htmlLang(html) !== "de") problems.push(`lang=${htmlLang(html)} (want de)`);
    if (!tagSpans(html, "footer").length && !/contentinfo/i.test(html)) problems.push("no footer landmark");
    if (CHROME_KEY_LEAK.test(stripTags(html))) problems.push("raw chrome.* keys leaked");
    if (problems.length === 0) {
      record("PASS", "deep-miss-404", '/de/<unknown> → 404 carrying localized chrome + <html lang="de"> (AC 14)');
    } else {
      record("FAIL", "deep-miss-404", `${problems.join("; ")} (AC 14)`);
    }
  } catch (e) {
    record("FAIL", "deep-miss-404", e.message);
  }
}

function legNoEnInternalHrefs() {
  if (!pagesGuard("no-en-hrefs")) return;
  const offenders = [];
  for (const [home, page] of pages) {
    for (const a of anchorsOf(page.html)) {
      if (a.href === "/en" || a.href.startsWith("/en/") || a.href.startsWith("/en?")) {
        offenders.push(`${home}: ${a.href}`);
      }
    }
  }
  if (offenders.length === 0) {
    record("PASS", "no-en-hrefs", "no served page emits an internal href=/en… (AC 3 grep half)");
  } else {
    record("FAIL", "no-en-hrefs", offenders.join(", "));
  }
}

function legNoChromeKeyLeak() {
  if (!pagesGuard("no-chrome-leak")) return;
  const offenders = [];
  for (const [home, page] of pages) {
    const m = CHROME_KEY_LEAK.exec(stripTags(page.html));
    if (m) offenders.push(`${home}: "${m[0]}…"`);
  }
  if (offenders.length === 0) {
    record("PASS", "no-chrome-leak", "no raw message keys leak into served HTML ×9 (AC 6)");
  } else {
    record("FAIL", "no-chrome-leak", `${offenders.join("; ")} (AC 6)`);
  }
}

function legCurlGreetable() {
  if (!pagesGuard("curl-greetable")) return;
  const bad = [];
  let manifestHrefs = null;
  try {
    manifestHrefs = manifestLiveHrefs();
  } catch (e) {
    bad.push(`routes-manifest unreadable: ${e.message}`);
  }
  for (const [home, page] of pages) {
    const headers = tagSpans(page.html, "header");
    const footers = tagSpans(page.html, "footer");
    if (headers.length !== 1) bad.push(`${home}: ${headers.length} <header> landmarks (want exactly 1 banner)`);
    if (footers.length !== 1) bad.push(`${home}: ${footers.length} <footer> landmarks (want exactly 1 contentinfo)`);
    if (headers.length === 1 && !headers[0].inner.includes("WARTALES")) {
      bad.push(`${home}: wordmark missing from the banner`);
    }
    if (footers.length === 1 && !footers[0].inner.includes("WARTALES")) {
      bad.push(`${home}: wordmark repeat missing from the footer`);
    }
    // m-3 fix (review-f4-tests r1): ≥1 nav anchor was never bound to the
    // manifest — a hardcoded wrong link passed. The union of section-nav
    // anchors must EQUAL the live rows' resolved hrefs (render-only-existing
    // judged on the wire). The combobox's sr-only cross-locale row is its
    // own <nav>, not section navigation — excluded by its listLabel.
    if (manifestHrefs) {
      let listLabel = null;
      try {
        listLabel = chromeMessage(HOME_ID[home], "locale.listLabel");
      } catch {
        /* label law owned by legSwitchLinks; don't double-report here */
      }
      const combo =
        listLabel != null ? findElementByAttr(page.html, "aria-label", listLabel) : null;
      const got = new Set();
      for (const span of tagSpans(page.html, "nav")) {
        if (combo && span.start === combo.start) continue;
        for (const a of anchorsOf(span.inner)) {
          const h = a.href.split(/[?#]/)[0];
          if (h && !h.startsWith("#") && !/^https?:/i.test(h)) got.add(h);
        }
      }
      const want = new Set(manifestHrefs.map((h) => resolveHome(home, h)));
      const extra = [...got].filter((h) => !want.has(h));
      const missing = [...want].filter((h) => !got.has(h));
      if (missing.length) bad.push(`${home}: nav misses live-row link(s) ${missing.join(", ")}`);
      if (extra.length) bad.push(`${home}: nav carries non-manifest link(s) ${extra.join(", ")}`);
    }
  }
  if (bad.length === 0) {
    record(
      "PASS",
      "curl-greetable",
      "wordmark + landmarks present ×9; section-nav anchors equal the live manifest rows, resolved per locale (AC 6, FRAMEWORK §2.14)"
    );
  } else {
    record("FAIL", "curl-greetable", bad.slice(0, 10).join("; "));
  }
}

async function legSwitchLinks(base) {
  const bad = [];
  if (!pagesGuard("switch-links")) return;
  const homes = new Set(HOMES);
  for (const [home, page] of pages) {
    // m-1 fix (review-f4-tests r1): the membership law is scoped to the
    // combobox's own server-rendered cross-locale row (<nav> carrying the
    // chrome.locale.listLabel label — Radix never SSRs the popover items).
    // The old page-wide anchor union stayed green when the combobox lost an
    // entry, because wordmark/nav/footer duplicates compensated. Membership
    // is EXACT: the row offers precisely the other eight locale homes.
    let listLabel = null;
    try {
      listLabel = chromeMessage(HOME_ID[home], "locale.listLabel");
    } catch (e) {
      bad.push(`${home}: ${e.message}`);
      continue;
    }
    const row = findElementByAttr(page.html, "aria-label", listLabel);
    if (!row || row.tag.toLowerCase() !== "nav") {
      bad.push(
        `${home}: combobox cross-locale row (<nav aria-label="${listLabel}">) absent from served HTML`
      );
      continue;
    }
    const offered = new Set(
      anchorsOf(row.inner).map((a) => a.href.split(/[?#]/)[0]).filter((h) => homes.has(h))
    );
    const expected = new Set(HOMES.filter((h) => h !== home));
    const missing = [...expected].filter((h) => !offered.has(h));
    const extra = [...offered].filter((h) => !expected.has(h));
    if (missing.length) bad.push(`${home}: combobox row lost switch link(s) to ${missing.join(", ")}`);
    if (extra.length) bad.push(`${home}: combobox row carries unexpected locale link(s) ${extra.join(", ")}`);
  }
  for (const target of HOMES) {
    try {
      const res = await fetchx(base + target, { redirect: "follow" }, 30000);
      if (res.status !== 200) bad.push(`switch target ${target}→${res.status}`);
    } catch (e) {
      bad.push(`switch target ${target}→${e.message}`);
    }
  }
  if (bad.length === 0) {
    record(
      "PASS",
      "switch-links",
      "combobox row offers exactly the other eight locale homes ×9; every switch target resolves 200 same-path (AC 5)"
    );
  } else {
    record("FAIL", "switch-links", `${bad.slice(0, 8).join("; ")} (AC 5)`);
  }
}

function legSearchSlotStaged() {
  if (!pagesGuard("search-slot-staged")) return;
  const bad = [];
  for (const [home, page] of pages) {
    const slot = findElementByAttr(page.html, "data-shell-slot", "search");
    if (!slot) {
      bad.push(`${home}: data-shell-slot="search" mount absent`);
      continue;
    }
    const inner = slot.inner.replace(/<!--[\s\S]*?-->/g, "");
    const kids = topLevelChildren(inner);
    const els = kids.filter((k) => k.kind === "el").length;
    if (els === 0) continue; // F4-only state: renders nothing (§5)
    // staged semantics (r2b): exactly the F5 search-field host and nothing
    // else. m-9 fix (review-f4-tests r1): the old branch additionally demanded
    // an <input>/<button> inside whatever F5 mounts — invented F5 internals
    // (a standing false-red once F5 lands); structural exactness is the
    // contract-level law and stays.
    if (els !== 1 || kids.some((k) => k.kind === "text")) {
      bad.push(`${home}: mounted slot holds ${els} element(s)/stray text, want exactly the one F5 field host`);
    }
  }
  if (bad.length === 0) {
    record("PASS", "search-slot-staged", "slot present ×9; EMPTY at F4-only time, else exactly one F5 field host, no stray text (AC 11 r2b — green both sides of the F5 mount)");
  } else {
    record("FAIL", "search-slot-staged", `${bad.slice(0, 8).join("; ")} (AC 11)`);
  }
}

function legSwapRoot() {
  if (!pagesGuard("swap-root")) return;
  const bad = [];
  for (const [home, page] of pages) {
    const el = findElementByAttr(page.html, "data-search-swap-root");
    if (!el) bad.push(`${home}: data-search-swap-root absent`);
    else if (el.tag.toLowerCase() !== "main") {
      bad.push(`${home}: swap root carried by <${el.tag}>, spec-f5 §5.1 requires the <main> wrapper`);
    }
  }
  if (bad.length === 0) {
    record("PASS", "swap-root", "data-search-swap-root on the <main> wrapper of every served page (F5 §13 H-3 inbound seam)");
  } else {
    record("FAIL", "swap-root", `${bad.join("; ")} (AC 11)`);
  }
}

function legSearchOwnership() {
  if (!pagesGuard("search-ownership")) return;
  const bad = [];
  for (const [home, page] of pages) {
    const slot = findElementByAttr(page.html, "data-shell-slot", "search");
    const inSlot = (pos) => !!slot && pos >= slot.start && pos <= slot.end;
    for (const m of page.html.matchAll(/<input\b([^>]*)>/gi)) {
      const type = /type\s*=\s*"([^"]*)"/i.exec(m[1])?.[1] ?? "";
      if (/^search$/i.test(type) && !inSlot(m.index)) {
        bad.push(`${home}: <input type="search"> rendered outside the F5-owned slot`);
      }
    }
    for (const m of page.html.matchAll(/<form\b([^>]*)>/gi)) {
      if (/role\s*=\s*"search"/i.test(m[1])) bad.push(`${home}: form role="search" outside the slot`);
    }
    for (const a of anchorsOf(page.html)) {
      if (!inSlot(a.start) && /^search$/i.test(a.text)) {
        bad.push(`${home}: "Search" word rendered outside the F5-owned slot`);
      }
      if (a.href.split(/[?#]/)[0] === "/search") {
        bad.push(`${home}: links to /search — no search route or link anywhere (AC 11)`);
      }
    }
  }
  if (bad.length === 0) {
    record("PASS", "search-ownership", "shell renders no search input or Search nav word beyond F5's mounted host; no /search link (AC 11 r2b ownership scope)");
  } else {
    record("FAIL", "search-ownership", `${[...new Set(bad)].slice(0, 8).join("; ")} (AC 11)`);
  }
}

async function legNoSearchRoute(base) {
  try {
    const res = await fetchx(base + "/search", { redirect: "manual" });
    record(res.status === 404 ? "PASS" : "FAIL", "no-search-route", `GET /search → ${res.status} (want 404; AC 11)`);
  } catch (e) {
    record("FAIL", "no-search-route", e.message);
  }
}

function legNotoCjk() {
  if (!pagesGuard("noto-cjk")) return;
  const bad = [];
  for (const [home, page] of pages) {
    const sheets = stylesheetLinks(page.html).filter(
      (l) => /stylesheet/i.test(l.rel) && /fonts\.googleapis\.com/.test(l.href)
    );
    const wantSc = home === "/zh";
    const wantKr = home === "/ko";
    const hasSc = sheets.some((l) => /Noto\+Sans\+SC/i.test(l.href));
    const hasKr = sheets.some((l) => /Noto\+Sans\+KR/i.test(l.href));
    if (wantSc && !hasSc) bad.push("/zh: missing the Noto Sans SC split-subset stylesheet link");
    if (wantKr && !hasKr) bad.push("/ko: missing the Noto Sans KR split-subset stylesheet link");
    if (!wantSc && !wantKr && sheets.length > 0) {
      bad.push(`${home}: CJK stylesheet emitted outside zh/ko (AC 13 discipline)`);
    }
  }
  if (bad.length === 0) {
    record("PASS", "noto-cjk", "Noto split-subset stylesheet PRESENT on /zh + /ko, ABSENT on the other seven (AC 13, fonts README pattern)");
  } else {
    record("FAIL", "noto-cjk", bad.join("; "));
  }
}

async function legAssetsResolve(base) {
  const refs = new Set();
  for (const [, page] of pages) {
    for (const r of assetRefs(page.html)) refs.add(r);
    for (const sheet of stylesheetLinks(page.html)) {
      if (!sheet.href || !/stylesheet/i.test(sheet.rel)) continue;
      try {
        const res = await fetchx(new URL(sheet.href, base + "/").toString(), {}, 20000);
        if (res.ok) for (const r of assetRefs(await res.text())) refs.add(r);
      } catch {
        /* unreachable stylesheet — roots legs already judge the page */
      }
    }
  }
  const staged = (ref) => existsSync(join(siteRoot, "public", ref));
  if (refs.size === 0) {
    const anyStaged =
      existsSync(join(siteRoot, "public", "fonts")) || existsSync(join(siteRoot, "public", "assets"));
    record(
      anyStaged ? "FAIL" : "SKIP",
      "assets-resolve",
      anyStaged
        ? "binaries staged locally yet served documents carry zero /fonts | /assets/ui refs — wiring defect (AC 12)"
        : "unstaged machine: documents declare no fetchable refs here — deferring to stage-check (AC 12)"
    );
    return;
  }
  const bad = [];
  const skipped = [];
  for (const ref of refs) {
    try {
      const res = await fetchx(base + encodeURI(ref), { method: "GET" }, 20000);
      if (res.status === 200) continue;
      if (!staged(ref)) skipped.push(ref);
      else bad.push(`${ref}→${res.status}`);
    } catch (e) {
      if (!staged(ref)) skipped.push(ref);
      else bad.push(`${ref}→${e.message}`);
    }
  }
  if (bad.length === 0) {
    record("PASS", "assets-resolve", `${refs.size}/fonts/*.woff2 + /assets/ui/*.png refs curl-200${skipped.length ? ` (${skipped.length} unstaged → SKIP below)` : ""} (AC 12 leg 1)`);
    for (const s of skipped.sort()) skipLine(s, "binary not staged locally; see site/public/{fonts,assets/ui}/README.md");
  } else {
    record("FAIL", "assets-resolve", `${bad.slice(0, 8).join("; ")} (AC 12)`);
  }
}

function legStageCheckPair() {
  const script = join(siteRoot, "scripts", "stage-assets.mjs");
  if (!existsSync(script)) {
    record("FAIL", "stage-check-pair", "scripts/stage-assets.mjs missing — AC 12's fresh-clone verifier cannot exist");
    return;
  }
  const run = spawnSync(process.execPath, [script, "--check"], { cwd: siteRoot, encoding: "utf8" });
  const out = `${run.stdout ?? ""}${run.stderr ?? ""}`;
  const listed = [...out.matchAll(/(\/fonts\/[^\s"']+\.woff2|\/assets\/ui\/[^\s"']+\.png)/g)].map((m) => m[1]);
  if (run.status === 0) {
    record("PASS", "stage-check-pair", "stage-assets --check exits 0 — zero missing refs (AC 12 fresh-clone leg, post-staging side)");
  } else if (listed.length > 0) {
    record("SKIP", "stage-check-pair", `--check exited nonzero naming ${listed.length} missing ref(s) — pre-staging state, honest defer (AC 12)`);
    for (const ref of [...new Set(listed)]) skipLine(ref, "stage per site/public/{fonts,assets/ui}/README.md");
  } else {
    record("FAIL", "stage-check-pair", `--check exited ${run.status} without naming missing refs:\n${out.slice(0, 800)}`);
  }
}

function legBootClean() {
  const m = COMPILE_ERRORS.exec(devLog);
  if (m) {
    const excerpt = devLog.slice(Math.max(0, m.index - 200), m.index + 800);
    record("FAIL", "boot-clean", `compile error detected in the dev log (AC 1 verified here): …${excerpt}…`);
  } else {
    record("PASS", "boot-clean", "zero build errors across the whole served sweep (AC 1)");
  }
}

/**
 * M-2 fix (review-f4-tests r1) — AC 14's production-build clause finally has
 * an executable assertion: `next build` must succeed AND all nine locale
 * homes must be proven prerendered static.
 *
 * Evidence law measured on Next 16.3.3: `.next/prerender-manifest.json`
 * carries `routes` — an OBJECT keyed by route (`routeType: "page"`,
 * `compute: "static"`) — and there is deliberately NO `"/"` key: the bare
 * pivot path is COMPOSED from the `/en` static artifact by the §3 pivot hop
 * (that hop is curl-proven live by the pivot-301 leg). So the nine homes are
 * proven via their nine locale-scoped artifacts `/{id}`. Fallback if a future
 * Next moves that shape: the emitted dist documents
 * `.next/server/app/<id>.html`. Never a silent pass either way. Guarded by
 * WARTALES_SMOKE_BUILD=1/--build; runs AFTER dev-server teardown (a live
 * `next dev` owns .next).
 */
function legProductionBuild() {
  const bin = join(siteRoot, "node_modules", "next", "dist", "bin", "next");
  if (!existsSync(bin)) {
    record("FAIL", "build-prerender", "next is not installed — run `npm ci` in site/ before arming WARTALES_SMOKE_BUILD");
    return;
  }
  console.log("build-prerender — running next build (AC 14; minutes, writes .next/)…");
  const run = spawnSync(process.execPath, [bin, "build"], {
    cwd: siteRoot,
    encoding: "utf8",
    timeout: 600000,
  });
  const out = `${run.stdout ?? ""}\n${run.stderr ?? ""}`;
  if (run.error || run.status !== 0) {
    record(
      "FAIL",
      "build-prerender",
      `next build exited ${run.status ?? run.error?.code ?? "?"}:\n${out.slice(-1200)}`
    );
    return;
  }
  let via = null;
  let routes = null;
  const mfPath = join(siteRoot, ".next", "prerender-manifest.json");
  try {
    routes = JSON.parse(readFileSync(mfPath, "utf8")).routes;
    if (routes && typeof routes === "object" && !Array.isArray(routes)) {
      via = ".next/prerender-manifest.json routes";
    } else {
      routes = null;
    }
  } catch {
    /* fall through to the dist-document fallback */
  }
  let missing;
  if (via) {
    // Bare "/" is composed from /en by the §3 pivot hop — prove the nine
    // locale-scoped artifacts instead.
    missing = LOCALES.filter((l) => {
      const r = routes[`/${l.id}`];
      return !r || r.routeType !== "page";
    }).map((l) => `/${l.id}`);
  } else {
    via = ".next/server/app/<id>.html dist documents";
    missing = LOCALES.filter(
      (l) => !existsSync(join(siteRoot, ".next", "server", "app", `${l.id}.html`))
    ).map((l) => `/${l.id}`);
  }
  if (missing.length === 0) {
    record("PASS", "build-prerender", `next build ok — all nine homes prerendered static (${via}; bare "/" composed from /en by the §3 hop, pivot-301-curl-proven) (AC 14)`);
  } else {
    record("FAIL", "build-prerender", `homes not proven static (${via}): ${missing.join(", ")}`);
  }
}

// ---- main ---------------------------------------------------------------------

async function main() {
  console.log(
    `F4 smoke — mode: ${armed ? "LIVE (WARTALES_SMOKE_LIVE armed)" : "disarmed (server legs SKIP; arm with WARTALES_SMOKE_LIVE=1 or --live)"}`
  );

  let base = null;
  if (armed) {
    try {
      base = await bootDev(await freePort());
      record("PASS", "boot-reachable", `next dev answering on scratch port (compile-error scan deferred to boot-clean)`);
    } catch (e) {
      record("FAIL", "boot-reachable", e.message);
    }
  }

  if (!armed) {
    const ids = [
      "boot-reachable", "roots-nine", "lang-attrs", "pivot-301",
      "no-negotiation", "unknown-locale-404", "deep-miss-404", "no-en-hrefs",
      "no-chrome-leak", "curl-greetable", "switch-links", "search-slot-staged",
      "swap-root", "search-ownership", "no-search-route", "noto-cjk",
      "assets-resolve", "boot-clean",
    ];
    for (const id of ids) {
      record("SKIP", id, "needs the dev server — arm with WARTALES_SMOKE_LIVE=1 (or --live)");
    }
  } else if (base) {
    await legNineRoots(base);
    legLangAttrs();
    await legPivot301(base);
    await legNoNegotiation(base);
    await legUnknownLocale404(base);
    await legLocaleDeepMiss404(base);
    legNoEnInternalHrefs();
    legNoChromeKeyLeak();
    legCurlGreetable();
    await legSwitchLinks(base);
    legSearchSlotStaged();
    legSwapRoot();
    legSearchOwnership();
    await legNoSearchRoute(base);
    legNotoCjk();
    await legAssetsResolve(base);
    legBootClean();
  }

  legStageCheckPair();

  if (devProc) {
    // m-7 fix: blocking kill + verified exit — a leaked server trips Next 16's
    // one-dev-server-per-dir lock on every later armed run.
    const killed = killTree(devProc);
    const exited = await awaitExit(devProc, 10000);
    if (!killed || !exited) {
      console.warn(
        `WARN teardown — dev server pid ${devProc.pid} ${killed ? "did not exit within 10s" : "kill failed"}; an orphan here blocks future boots (one dev server per directory)`
      );
    }
    await new Promise((r) => setTimeout(r, 500));
  }

  // M-2 (AC 14 build/prerender leg) — after teardown; a live `next dev`
  // owns .next while it runs.
  if (buildArmed) {
    legProductionBuild();
  } else {
    record(
      "SKIP",
      "build-prerender",
      "disarmed — arm with WARTALES_SMOKE_BUILD=1 (or --build) to run `next build` + assert nine static homes (AC 14)"
    );
  }

  const counts = { PASS: 0, FAIL: 0, SKIP: 0 };
  for (const r of results) counts[r.status]++;
  console.log(
    `smoke verdict: ${counts.FAIL > 0 ? "FAIL" : "PASS"} — ${counts.PASS} passed, ${counts.FAIL} failed, ${counts.SKIP} skipped`
  );
  process.exit(counts.FAIL > 0 ? 1 : 0);
}

main().catch((e) => {
  console.error(`smoke crashed: ${e && e.stack ? e.stack : e}`);
  if (devProc) killTree(devProc);
  process.exit(1);
});
