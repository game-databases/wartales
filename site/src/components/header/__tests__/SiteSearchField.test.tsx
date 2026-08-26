// F5 §9 suite 3 — SiteSearchField.test.tsx (jsdom project).
//
// Spec: docs/spec-f5-search.mdx §5 (DR-verbatim field contract), §7 (a11y),
// §8 (chrome seam); AC-10/AC-12/AC-14/AC-15 + AC-16's component legs.
//
// Laws under test, each traceable to a DR clause:
//   - closed = the localized word as a real control; open = a focused input
//     whose mount declares growth across the nav row (clause 2);
//   - the 2-normalized-char crossing hides `data-search-swap-root` IN PLACE
//     — never unmounts it (scroll + subtree + state survive), results render
//     into the vacated slot (clauses 3+4);
//   - exactly two restore paths — cleared (✕ control or emptied) and Escape
//     (which also collapses + refocuses the word); blur does NEITHER
//     (§5.2 recorded non-behavior);
//   - render cap 50 with FULL group counts (capping never lies, §5.4);
//   - zero state = `0` beside the echoed query, nothing else (no teaching
//     copy — DR-2026-08-22-copy-earns-its-place §3);
//   - input gate: zero `<form>`, zero `type="submit"` (gated DR clause);
//   - chrome seam: en values resolve; a PARTIAL injected dictionary falls
//     back to en per key without crashing (§8, AC-16).
//
// BLIND suite: written against the spec alone (parallel CodeWriter in
// flight). Discovery is tolerant — plausible export/prop spellings are probed
// and failures name every candidate tried. Data arrives through the §4.4
// contract surface: fetch("/data/search/<locale>.json"), stubbed here.
//
// The §5.1 fixture mounts BOTH F4-owned attributes itself ("Tests mount their
// own fixture roots carrying both attributes"), and every manually appended
// node is tracked + removed between tests — a leaked fixture would leave a
// STALE second `[data-search-swap-root]` in document.body and silently feed
// later tests the wrong element.

import { describe, expect, it, beforeAll, beforeEach, afterEach, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createElement, type ReactElement } from "react";

// (test-review M-8 hygiene: the dead `vi.mock("next/navigation")` shim is
// deleted — the field imports none of it; a mock for an unimported module
// only ever masked a future accidental import.)

// ---- fixture corpus (the artifact shape of §3.2) -----------------------------

type Row = { kind: string; id: string; name: string; href: string };

const pad = (n: number): string => String(n + 1).padStart(2, "0");

const CORPUS: Row[] = [
  ...Array.from({ length: 30 }, (_, i): Row => ({
    kind: "item",
    id: `i-alpha-${pad(i)}`,
    name: `Alpha Widget ${pad(i)}`,
    href: `/item/i-alpha-${pad(i)}`,
  })),
  ...Array.from({ length: 15 }, (_, i): Row => ({
    kind: "skill",
    id: `s-alpha-${pad(i)}`,
    name: `Alpha Technique ${pad(i)}`,
    href: `/skill/s-alpha-${pad(i)}`,
  })),
  ...Array.from({ length: 10 }, (_, i): Row => ({
    kind: "class",
    id: `c-alpha-${pad(i)}`,
    name: `Alpha Class ${pad(i)}`,
    href: `/class/c-alpha-${pad(i)}`,
  })),
  // A second facet slice so kind grouping is observable independently.
  { kind: "item", id: "i-zeta", name: "Zeta Blade", href: "/item/i-zeta" },
];
const ALPHA_TOTAL = 55; // hits for query "alpha"
const MAX_RENDERED = 50; // §5.4

function fakeResponse(url: string): { ok: boolean; status: number; json: () => Promise<unknown> } {
  const u = String(url);
  if (/manifest\.json$/.test(u)) {
    const locales = ["en", "fr", "de", "es", "pl", "pt-BR", "ru", "ko", "zh"];
    return {
      ok: true,
      status: 200,
      json: async () => ({
        schema: "wartales/search-index@1",
        buildId: "20318128",
        locales,
        kinds: ["item", "skill", "class"],
        rowCount: Object.fromEntries(locales.map((l) => [l, CORPUS.length])),
      }),
    };
  }
  return { ok: true, status: 200, json: async () => CORPUS };
}

// ---- component discovery -------------------------------------------------------

type Comp = (props: Record<string, unknown>) => ReactElement | null;
let Field: Comp | null = null;
let loadError: Error | null = null;

beforeAll(async () => {
  try {
    const mod = (await import("../../header/SiteSearchField")) as unknown as Record<string, unknown>;
    const cand =
      (typeof mod.SiteSearchField === "function" && mod.SiteSearchField) ||
      (typeof mod.default === "function" && mod.default);
    if (typeof cand !== "function") {
      loadError = new Error(
        `SiteSearchField.tsx exports [${Object.keys(mod).join(", ")}] — wanted a component ` +
          `(named SiteSearchField or default); §5.1 pins this file`
      );
    } else {
      Field = cand as Comp;
    }
  } catch (e) {
    loadError = e as Error;
  }
});

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => fakeResponse(String(input))));
});
afterEach(() => {
  cleanup();
  purgeFixtures();
  currentContainer = null;
  vi.unstubAllGlobals();
});

function needField(): Comp {
  if (loadError) throw loadError;
  return Field as Comp;
}

// ---- the §5.1 fixture ----------------------------------------------------------

let manualNodes: HTMLElement[] = [];

function track(el: HTMLElement): HTMLElement {
  manualNodes.push(el);
  document.body.appendChild(el);
  return el;
}

function purgeFixtures(): void {
  for (const el of manualNodes) el.remove();
  manualNodes = [];
}

/**
 * F4's two attributes, mounted by the TEST: `data-shell-slot="search"` hosts
 * the field; `data-search-swap-root` wraps scrollable page content (a form
 * field holding typed state, so clause 4's state-survival is observable).
 */
function mountFixture(props: Record<string, unknown> = {}): {
  container: HTMLElement;
  root: HTMLElement;
  inner: HTMLElement;
} {
  purgeFixtures(); // never let a stale second swap root linger in body
  const root = document.createElement("div");
  root.setAttribute("data-search-swap-root", "");
  const inner = document.createElement("div");
  inner.setAttribute("data-page-content", "");
  inner.style.overflowY = "scroll";
  // State carriers deliberately avoid the textbox role — the field owns the
  // only textbox; a second one would blur every role query.
  inner.innerHTML =
    '<p>open tab: skills</p>' +
    '<details open id="fx-details"><summary>skills tab</summary><p>rows</p></details>' +
    '<label><input type="checkbox" id="fx-check" checked /> compare mode</label>';
  root.appendChild(inner);
  const main = document.createElement("main");
  main.appendChild(root);

  // Composed page order, as the shell lays it out: header slot first, the
  // field mounted inside it, THEN the page content (fix round r2 — the §7
  // Tab/DOM-order law is only meaningful in this order).
  const slot = track(document.createElement("div"));
  slot.setAttribute("data-shell-slot", "search");
  const fieldHost = track(document.createElement("div"));
  track(main);

  const container = render(createElement(needField(), props), {
    container: fieldHost,
  }).container;
  currentContainer = container;
  return { container, root, inner };
}

// Component queries are scoped to the RTL container: the fixture's page
// content lives in document.body and must never answer for the field.
let currentContainer: HTMLElement | null = null;

function scope(): ReturnType<typeof within> {
  if (!currentContainer) throw new Error("no live fixture — mountFixture() first");
  return within(currentContainer);
}
function getWordButton(): HTMLElement {
  return scope().getByRole("button", { name: "Search" });
}
function getClearButton(): HTMLElement {
  return scope().getByRole("button", { name: "Clear" });
}
function getInput(): HTMLInputElement {
  return scope().getByRole("textbox") as HTMLInputElement;
}
function queryTextbox(): HTMLInputElement | null {
  return currentContainer
    ? (within(currentContainer).queryByRole("textbox") as HTMLInputElement | null)
    : null;
}
function typeInto(value: string): void {
  fireEvent.change(getInput(), { target: { value } });
}
function resultLinks(): HTMLAnchorElement[] {
  return Array.from(document.querySelectorAll<HTMLAnchorElement>("a[href^='/']")).filter(
    (a) => CORPUS.some((r) => r.href === a.getAttribute("href"))
  );
}
/**
 * Pure-digit leaf elements — group counts and the live-region number render
 * as bare numbers in their own nodes (chip-word rules). textContent of the
 * whole body concatenates without boundaries ("Items 30Alpha…") and cannot
 * be word-regexed reliably.
 */
function digitLeaves(scope: ParentNode): HTMLElement[] {
  return Array.from(scope.querySelectorAll("*")).filter(
    (el) => el.children.length === 0 && /^\d+$/.test((el.textContent ?? "").trim())
  ) as HTMLElement[];
}

describe("§5.3 clause 2 — closed word, open focused input", () => {
  it("renders the closed state as the localized word control, not a box", () => {
    mountFixture();
    expect(getWordButton().getAttribute("type")).toBe("button");
    expect(queryTextbox()).toBeNull();
  });

  it("activating swaps the word for a focused input on a host declaring growth", () => {
    mountFixture();
    fireEvent.click(getWordButton());
    expect(document.activeElement).toBe(getInput());
    const host = document.querySelector("[data-search-open]") as HTMLElement | null;
    expect(
      host,
      "§5.3.2: the open state sets data-search-open on its mount element — the " +
        "attribute is the pinned hook F5's stylesheet grows the nav row from"
    ).not.toBeNull();
    // m-5 (fix round r2): the growth claim is STRUCTURAL, not "some className
    // exists" — a regression keeping the input at word-width must fail. The
    // pinned geometry law: on open the mount breaks out of flow and spans
    // the nav band (absolute + inset-y/left/right), per the §5.3.2 hook.
    const GROWTH_CLASSES = [
      "md:data-[search-open]:absolute",
      "md:data-[search-open]:inset-y-0",
      "md:data-[search-open]:left-0",
      "md:data-[search-open]:right-0",
    ];
    for (const cls of GROWTH_CLASSES) {
      expect(
        (host as HTMLElement).classList.contains(cls),
        `open-state mount must carry the row-growth geometry class "${cls}"`
      ).toBe(true);
    }
  });
});

describe("§5.3 clauses 3+4 — the in-place swap (hidden, never unmounted)", () => {
  it("one character leaves the page content visible", () => {
    const { root } = mountFixture();
    fireEvent.click(getWordButton());
    typeInto("a");
    expect(root.hidden, "below the threshold nothing swaps").toBe(false);
    expect(root.hasAttribute("hidden")).toBe(false);
  });

  it("two normalized characters hide the root, keep subtree + scrollTop + state, render artifact links", async () => {
    const { root, inner } = mountFixture();
    inner.scrollTop = 123456; // scroll position that MUST survive the detour
    fireEvent.click(getWordButton());
    typeInto("a");
    typeInto("al");

    await waitFor(() => expect(root.hidden).toBe(true));
    expect(document.contains(root), "swap root stays in the DOM (clause 4)").toBe(true);
    expect(root.contains(inner), "content subtree intact").toBe(true);
    expect(inner.scrollTop, "scroll position survives").toBe(123456);
    expect(
      (root.querySelector("#fx-details") as HTMLDetailsElement).open,
      "open-tab state survives (nothing remounted)"
    ).toBe(true);
    expect(
      (root.querySelector("#fx-check") as HTMLInputElement).checked,
      "form-entry state survives"
    ).toBe(true);

    await waitFor(() =>
      expect(resultLinks().length, "results render as real <a href> to artifact hrefs").toBeGreaterThan(0)
    );
    for (const a of resultLinks()) {
      expect(a.getAttribute("href")?.includes("/search"), "no result links a search route").toBe(false);
      expect(a.textContent?.trim().length, "rows show the game's own names").toBeGreaterThan(0);
    }
  });

  it("caps rendering at 50 while group headers still carry the FULL counts (§5.4)", async () => {
    mountFixture();
    fireEvent.click(getWordButton());
    typeInto("alpha");
    await waitFor(() => expect(resultLinks().length).toBeGreaterThan(0));

    await waitFor(() => {
      const rendered = resultLinks().filter((a) => (a.getAttribute("href") ?? "").includes("alpha"));
      expect(rendered.length, "MAX_RENDERED_ROWS = 50 — a named constant, not a derivation").toBe(MAX_RENDERED);
    });
    // Full counts despite capping: item 30 + skill 15 + class 10 = 55, each a
    // bare number beside its kind label (chip-word rules).
    const counts = digitLeaves(document.body).map((el) => Number(el.textContent?.trim()));
    for (const [count, kind] of [[30, "item"], [15, "skill"], [10, "class"]] as const) {
      expect(
        counts.includes(count),
        `${kind} group header shows the FULL count ${count} (found bare numbers: ${counts.join(",")})`
      ).toBe(true);
    }
    expect(
      counts.reduce((a, b) => a + b, 0),
      "no invented numbers beyond the true group counts (+ the live-region total)"
    ).toBe(ALPHA_TOTAL * 2);
  });
});

describe("§5.3 clause 5 — exactly two restore paths", () => {
  it("the ✕ clear control restores content and keeps the field OPEN", async () => {
    const { root } = mountFixture();
    fireEvent.click(getWordButton());
    typeInto("al");
    await waitFor(() => expect(root.hidden).toBe(true));

    fireEvent.click(getClearButton());
    expect(root.hidden, "cleared → content restored").toBe(false);
    expect(queryTextbox(), "clearing does NOT close the field").not.toBeNull();
  });

  it("emptying the text restores content too (DR: 'cleared … restores')", async () => {
    const { root } = mountFixture();
    fireEvent.click(getWordButton());
    typeInto("al");
    await waitFor(() => expect(root.hidden).toBe(true));
    typeInto("");
    expect(root.hidden).toBe(false);
    expect(queryTextbox()).not.toBeNull();
  });

  it("Escape restores + collapses + refocuses the closed-word control", async () => {
    const { root } = mountFixture();
    fireEvent.click(getWordButton());
    typeInto("al");
    await waitFor(() => expect(root.hidden).toBe(true));

    fireEvent.keyDown(getInput(), { key: "Escape" });
    expect(root.hidden, "Escape restores").toBe(false);
    expect(queryTextbox(), "Escape collapses the field").toBeNull();
    expect(document.activeElement, "single stroke out lands focus on the word").toBe(getWordButton());
  });
});

describe("§5.2 recorded non-behavior — blur neither closes nor restores", () => {
  it("blur with results shown keeps them shown and the field open", async () => {
    const { root } = mountFixture();
    fireEvent.click(getWordButton());
    typeInto("al");
    await waitFor(() => expect(root.hidden).toBe(true));
    fireEvent.blur(getInput());
    expect(root.hidden).toBe(true);
    expect(queryTextbox()).not.toBeNull();
  });

  it("blur below the threshold changes nothing either", () => {
    const { root } = mountFixture();
    fireEvent.click(getWordButton());
    typeInto("a");
    fireEvent.blur(getInput());
    expect(root.hidden).toBe(false);
    expect(queryTextbox()).not.toBeNull();
  });
});

describe("zero state — a plain-word fact, no teaching (AC-15)", () => {
  it("shows count 0 beside the echoed query and NOTHING instructional", async () => {
    mountFixture();
    fireEvent.click(getWordButton());
    typeInto("qqqq");
    await waitFor(() => {
      expect(
        digitLeaves(document.body).some((el) => el.textContent?.trim() === "0"),
        "the count line renders 0 as its own bare number"
      ).toBe(true);
      expect(document.body.textContent?.includes("qqqq"), "the query is echoed").toBe(true);
    });
    const text = (document.body.textContent ?? "").toLowerCase();
    const BANNED: [RegExp, string][] = [
      [/how to/, "teaches how"],
      [/\bpress\b/, "key instruction"],
      [/to search/, "teaches how"],
      [/no results/, "absence apology"],
      [/did you mean/, "suggestions module"],
      [/try (a )?different/, "suggestion"],
      [/\bhelp\b/, "help copy"],
      [/start typing/, "teaches how"],
    ];
    for (const [re, why] of BANNED) {
      expect(re.test(text), `instructional copy banned (DR-2026-08-22-copy-earns-its-place §3): ${why}`).toBe(false);
    }
  });
});

describe("AC-12 — the input gate: reactive, never submitted", () => {
  it("renders zero <form> and zero [type=submit]; affordances are type=button", () => {
    const { container } = mountFixture();
    fireEvent.click(getWordButton());
    typeInto("al");
    // The whole mounted tree, fixture included: no form, no submit anywhere.
    expect(document.querySelectorAll("form")).toHaveLength(0);
    expect(document.querySelectorAll('[type="submit"]')).toHaveLength(0);
    const buttons = Array.from(container.querySelectorAll("button"));
    expect(buttons.length).toBeGreaterThan(0);
    for (const b of buttons) {
      expect(b.getAttribute("type"), `button "${b.textContent}" must be type=button`).toBe("button");
    }
  });
});

describe("§7 accessibility basics (AC-14)", () => {
  it("sits in a search landmark; the input carries its own aria-label", () => {
    mountFixture();
    expect(document.querySelector('[role="search"]'), "role=search landmark").not.toBeNull();
    fireEvent.click(getWordButton());
    expect(
      (getInput().getAttribute("aria-label") ?? "").length,
      "label independent of the vanished visible word"
    ).toBeGreaterThan(0);
  });

  it("announces the hit count through a polite live region", async () => {
    mountFixture();
    fireEvent.click(getWordButton());
    typeInto("alpha");
    const live = await waitFor(() => {
      const el = document.querySelector('[aria-live="polite"]');
      expect(el, "an aria-live=polite region must exist").not.toBeNull();
      return el as HTMLElement;
    });
    await waitFor(() =>
      expect(/\d/.test(live.textContent ?? ""), "live region announces the count as a bare number").toBe(true)
    );
  });

  it("ArrowDown reaches the first result link; ArrowUp returns to the input", async () => {
    mountFixture();
    fireEvent.click(getWordButton());
    typeInto("alpha");
    const firstLink = await waitFor(() => {
      const ls = resultLinks();
      expect(ls.length).toBeGreaterThan(0);
      return ls[0];
    });
    fireEvent.keyDown(getInput(), { key: "ArrowDown" });
    expect(document.activeElement, "ArrowDown → first rendered result").toBe(firstLink);
    fireEvent.keyDown(firstLink, { key: "ArrowUp" });
    expect(document.activeElement, "ArrowUp → back to the input").toBe(getInput());
  });

  it("Tab reaches results in DOM order — every link follows the field (§7, m-6)", async () => {
    mountFixture();
    fireEvent.click(getWordButton());
    typeInto("alpha");
    const links = await waitFor(() => {
      const ls = resultLinks();
      expect(ls.length, "results rendered").toBeGreaterThan(0);
      return ls;
    });
    // §7's law: "Tab reaches results in DOM order (they follow the header)."
    // Tab focus movement is native browser behavior over DOM order, so the
    // executable form is structural: every rendered link must sit AFTER the
    // input in document order, and consecutive links must preserve the
    // matcher's best-first order — then native Tab walks them in that order.
    const FOLLOWING = Node.DOCUMENT_POSITION_FOLLOWING;
    const input = getInput();
    for (const a of links) {
      expect(
        (input.compareDocumentPosition(a) & FOLLOWING) !== 0,
        `${a.getAttribute("href")} must follow the field input in document order`
      ).toBe(true);
    }
    for (let i = 1; i < links.length; i++) {
      expect(
        (links[i - 1].compareDocumentPosition(links[i]) & FOLLOWING) !== 0,
        `rendered results keep best-first order in the DOM (${links[i - 1].getAttribute("href")} → ${links[i].getAttribute("href")})`
      ).toBe(true);
    }
  });
});

describe("§8 chrome seam (AC-16) — en resolves; partial dictionaries fall back", () => {
  it("resolves every §8 key for en through the default dictionary", () => {
    mountFixture();
    expect(getWordButton().textContent?.trim()).toBe("Search"); // search.word
    fireEvent.click(getWordButton());
    expect(getInput().getAttribute("aria-label")).toBe("Search"); // search.fieldLabel
    expect(screen.getByRole("button", { name: "Clear" })).not.toBeNull(); // search.clear
  });

  it("injecting a PARTIAL dictionary overrides one key and falls back to en per key", () => {
    const DICT_SHAPES = [
      { search: { word: "Suchen" } }, // nested namespace shape
      { "search.word": "Suchen" }, // flat dotted-key shape
    ];
    const PROP_SPELLINGS = ["dictionary", "dict", "chrome", "i18n", "labels", "messages"];
    const attempts: string[] = [];
    for (const prop of PROP_SPELLINGS) {
      for (const dict of DICT_SHAPES) {
        attempts.push(`${prop}=${JSON.stringify(dict)}`);
        try {
          cleanup();
          purgeFixtures();
          mountFixture({ [prop]: dict });
          const localized = screen.queryByRole("button", { name: "Suchen" });
          if (!localized) continue; // spelling rejected — keep probing
          // Injection recognized: the PARTIAL dictionary overrode exactly one
          // key; everything else falls back to en (open → input labelled
          // "Search"), no crash anywhere in the detour.
          fireEvent.click(localized);
          expect(getInput().getAttribute("aria-label"), "non-overridden keys fall back to en").toBe("Search");
          expect(screen.getByRole("button", { name: "Clear" }), "search.clear fell back to en").not.toBeNull();
          return;
        } catch (e) {
          attempts.push(`(${prop} crashed: ${(e as Error).message.slice(0, 80)})`);
        }
      }
    }
    throw new Error(
      "no injected-dictionary seam recognized (AC-16): tried " +
        attempts.join("; ") +
        " — §8 pins a props/injected-dictionary resolver with per-key en fallback"
    );
  });

  it("self-hosts the §8 key inventory in the interim resolver module", async () => {
    let mod: Record<string, unknown>;
    try {
      mod = (await import("../../../lib/i18n/search-chrome")) as Record<string, unknown>;
    } catch (e) {
      throw new Error(
        `site/src/lib/i18n/search-chrome.ts missing/unreadable (§11 files-touched, §8 seam): ${(e as Error).message}`
      );
    }
    const seen = new Set<string>();
    const visit = (v: unknown): void => {
      if (typeof v === "string") seen.add(v);
      else if (v && typeof v === "object") {
        for (const x of Object.values(v as Record<string, unknown>)) visit(x);
      }
    };
    for (const v of Object.values(mod)) visit(v);
    for (const want of ["Search", "Clear", "{count}", "Items", "Skills", "Classes"]) {
      expect(seen.has(want), `§8 en value "${want}" must ship in the resolver dictionary`).toBe(true);
    }
  });

  it("unit: createSearchChrome resolves en, substitutes {count}, falls back per key (AC-16, m-6)", async () => {
    let mod: Record<string, unknown>;
    try {
      mod = (await import("../../../lib/i18n/search-chrome")) as Record<string, unknown>;
    } catch (e) {
      throw new Error(`search-chrome.ts unreadable: ${(e as Error).message}`);
    }
    const factory = mod.createSearchChrome as
      | ((injected?: Record<string, string>) => {
          (key: string): string;
          count(key: string, vars: { count: number | string }): string;
        })
      | undefined;
    if (typeof factory !== "function") {
      throw new Error(
        `search-chrome exports [${Object.keys(mod).join(", ")}] — wanted the ` +
          `createSearchChrome factory (§8 pins the props/injected-dictionary resolver)`
      );
    }
    const plain = factory();
    expect(plain("search.word"), "en word").toBe("Search");
    expect(plain("search.fieldLabel"), "en fieldLabel").toBe("Search");
    expect(plain("search.clear"), "en clear").toBe("Clear");
    expect(plain("search.resultHeading"), "en resultHeading").toBe("Search");
    expect(plain("search.kind.item"), "en facet item").toBe("Items");
    expect(plain("search.kind.skill"), "en facet skill").toBe("Skills");
    expect(plain("search.kind.class"), "en facet class").toBe("Classes");
    expect(plain.count("search.countTemplate", { count: 12 }), "{count} substituted").toBe("12");

    const partial = factory({ "search.word": "Suchen" });
    expect(partial("search.word"), "overridden key wins").toBe("Suchen");
    expect(partial("search.clear"), "non-overridden keys fall back to en").toBe("Clear");
    expect(partial("search.fieldLabel"), "fallback is PER KEY").toBe("Search");
    expect(partial.count("search.countTemplate", { count: 3 }), "template still substitutes under injection").toBe("3");
  });
});

// ---- fix round r2 -------------------------------------------------------------

/**
 * M-1 rig: point the field at a locale whose artifact 404s. Uses /ko/ (a
 * clientCode no other test in this file loads) so the module-level index
 * cache cannot answer for the failing leg; restores the pivot path after.
 */
function stubLocaleArtifactFailure(): void {
  window.history.pushState({}, "", "/ko/");
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const u = String(input);
      if (/\/data\/search\/ko\.json$/.test(u)) {
        return { ok: false, status: 404, json: async () => null };
      }
      return fakeResponse(u);
    })
  );
}

function backToPivotPath(): void {
  window.history.pushState({}, "", "/");
}

describe("fix round r2 M-1 — failed artifact fetch: plain-word absence, never fake zeros", () => {
  afterEach(backToPivotPath);

  it("a 404 artifact does NOT produce `0` — the absence state renders instead", async () => {
    stubLocaleArtifactFailure();
    mountFixture();
    fireEvent.click(getWordButton());
    typeInto("alpha");
    await waitFor(() =>
      expect(
        document.body.textContent ?? "",
        "the plain-word absence state replaces the results"
      ).toContain("Search is unavailable for this language")
    );
    // Results still replaced the page content IN PLACE (DR clause 3)…
    expect(
      document.querySelector("[data-search-swap-root]")?.hasAttribute("hidden"),
      "swap still happens — the absence surface occupies the page slot"
    ).toBe(true);
    // …but what occupies it names the absence in words, never a count.
    const live = document.querySelector('[aria-live="polite"]');
    expect(live?.textContent ?? "").toContain("Search is unavailable for this language");
    expect(
      /\d/.test(live?.textContent ?? ""),
      "live region announces words, not a fabricated number"
    ).toBe(false);
    // The exact defect M-1 forbids: ANY bare `0` digit leaf while rows are
    // not really loaded — including for an exact tier-1 query like "alpha".
    for (const el of digitLeaves(document.body)) {
      expect(
        el.textContent?.trim(),
        "no digit leaf may render while the artifact is unavailable"
      ).not.toBe("0");
    }
    // Retry affordance exists while the field stays open, and submits nothing.
    const retry = screen.getByRole("button", { name: "Retry" });
    expect(retry.getAttribute("type"), "retry is type=button (input gate)").toBe("button");
  });

  it("retry re-fetches while the field is open and recovers to real hits", async () => {
    stubLocaleArtifactFailure();
    mountFixture();
    fireEvent.click(getWordButton());
    typeInto("alpha");
    await waitFor(() =>
      expect(document.body.textContent ?? "").toContain("Search is unavailable for this language")
    );
    // The artifact "arrives": flip the stub to success BEFORE retrying —
    // the failed cache entry dropped itself, so retry must genuinely refetch.
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => fakeResponse(String(input))));
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() =>
      expect(
        resultLinks().length,
        "recovery renders the real hits without close+reopen"
      ).toBeGreaterThan(0)
    );
    expect(
      document.body.textContent ?? "",
      "absence copy gone once rows really loaded"
    ).not.toContain("Search is unavailable for this language");
  });
});

describe("fix round r2 m-8 — out-of-vocabulary kinds are surfaced, not dropped", () => {
  afterEach(backToPivotPath);

  it("renders an unknown-kind group (self-labelled, full count) with its real link", async () => {
    // /de/ is a clientCode nothing else in this file loads, so the module-level
    // index cache cannot answer for the fixture; the stub serves the extended
    // corpus for it.
    window.history.pushState({}, "", "/de/");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const u = String(input);
        if (/manifest\.json$/.test(u)) return fakeResponse(u);
        return {
          ok: true,
          status: 200,
          json: async () => [
            ...CORPUS,
            { kind: "beast", id: "b1", name: "Alpha Beast", href: "/beast/b1" },
          ],
        };
      })
    );
    mountFixture();
    fireEvent.click(getWordButton());
    // Query a term ONLY the out-of-vocabulary row answers — under "alpha" the
    // 50-row render cap would correctly swallow the trailing beast slice
    // (headers keep the full counts either way).
    typeInto("beast");
    await waitFor(() =>
      expect(
        Array.from(document.querySelectorAll("h2")).some((h) =>
          (h.textContent ?? "").trim().startsWith("beast")
        ),
        "the beast group renders"
      ).toBe(true)
    );

    const headers = Array.from(document.querySelectorAll("h2"));
    const beast = headers.find((h) => (h.textContent ?? "").trim().startsWith("beast"));
    expect(
      beast,
      `unknown-kind hit must get its own trailing group (found headers: ${headers.map((h) => h.textContent?.trim()).join(" | ")})`
    ).toBeDefined();
    expect(
      digitLeaves(beast as HTMLElement).map((el) => el.textContent?.trim()),
      "the unknown-kind group carries its FULL count"
    ).toEqual(["1"]);
    const link = document.querySelector<HTMLAnchorElement>('a[href="/beast/b1"]');
    expect(link, "the out-of-vocabulary hit ships as a real <a href>").not.toBeNull();
    expect(link?.textContent?.trim()).toBe("Alpha Beast");
  });
});
