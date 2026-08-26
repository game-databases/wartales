"use client";

/**
 * The header search field — the F5 state machine (spec-f5-search §5;
 * DR-2026-08-22-search-is-not-a-page).
 *
 * States (§5.2): closed → open (click/Enter on the word) → swapped once
 * len(normalize(q)) ≥ 2. Restore paths are EXACTLY the DR's two — the
 * field is cleared, or Escape is pressed. Blur deliberately does NEITHER
 * (§5.2 recorded non-behavior; do not "fix" it).
 *
 * Seam ownership (§5.1): this component mounts INSIDE F4's reserved
 * `data-shell-slot="search"` element and CONSUMES F4's server-rendered
 * `data-search-swap-root` (the shell <main>). On swap it sets `hidden`
 * on that element — hidden, never unmounted: scroll position and
 * component state survive the detour — and portals the results view into
 * a container inserted immediately BEFORE it, so results occupy the
 * layout space the vacated content left. A missing swap root is a
 * composition error, not a degraded render mode; there is NO header
 * fallback.
 *
 * Open-state growth (§5.3.2) rides `data-search-open` on this mount
 * element — the attribute IS F5's stylesheet hook; no F4-owned shell
 * file is edited for the field to take over the nav row.
 *
 * Locale source: the page-plane segment is read from location.pathname
 * and resolved through THE §2 table (@/i18n/locales — no second mapping)
 * onto the artifact's client-code column (`/data/search/pt-BR.json`, not
 * `/pt-br…`). Reading the address bar rather than a provider context
 * keeps the field self-contained: the DR's field belongs to the header,
 * not to a provider subtree.
 *
 * Input gate (DR-2026-08-22-inputs-answer-as-you-type, gated clause): no
 * <form>, no type="submit" anywhere in this tree; typing drives
 * everything; Enter navigates to the current top hit through its real
 * anchor (link semantics, not submission).
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { LOCALES, PIVOT_LOCALE } from "../../i18n/locales";
import { MIN_QUERY_CHARS, searchRows } from "../../lib/search/searchRows";
import type { SearchRow } from "../../lib/search/searchRows";
import { normalizeName } from "../../lib/search/normalize";
import {
  createSearchChrome,
  type SearchChromeDictionary,
} from "../../lib/i18n/search-chrome";
import SearchResultsView from "./SearchResultsView";

/**
 * Artifact fetches are lazy (first field-open) and cached in-module
 * (§4.4). The published artifact is `{schema, locale, buildId, rows}`
 * (§3.2); a bare row array is tolerated defensively so a malformed or
 * legacy payload cannot crash the field — consumers never derive data.
 */
function rowsOf(doc: unknown): SearchRow[] {
  if (Array.isArray(doc)) return doc as SearchRow[];
  if (doc && typeof doc === "object" && Array.isArray((doc as { rows?: unknown }).rows)) {
    return (doc as { rows: SearchRow[] }).rows;
  }
  return [];
}

const indexCache = new Map<string, Promise<SearchRow[]>>();

function loadIndex(clientCode: string): Promise<SearchRow[]> {
  let cached = indexCache.get(clientCode);
  if (!cached) {
    cached = fetch(`/data/search/${clientCode}.json`)
      .then((res) => {
        if (!res.ok) throw new Error(`search index ${res.status} for ${clientCode}`);
        return res.json();
      })
      .then((doc) => rowsOf(doc));
    // A failed fetch must not cache-fail forever: drop the entry so the
    // next keystroke retries (the artifact is static and will resolve).
    cached.catch(() => indexCache.delete(clientCode));
    indexCache.set(clientCode, cached);
  }
  return cached;
}

/**
 * Page segment → client code, through THE locale table only. Pivot and
 * unknown segments fall back to the pivot (fail-closed, never invented).
 */
function segmentToClientCode(pathname: string): string {
  const seg = pathname.split("/").filter(Boolean)[0];
  const hit = seg ? LOCALES.find((l) => l.id === seg) : undefined;
  return hit ? hit.clientCode : PIVOT_LOCALE;
}

/**
 * Chrome override seam (§8/AC-16): a partial dictionary with per-key en
 * fallback. Both call-site shapes are accepted — the flat dotted form
 * (`{ "search.word": … }`) and the nested namespace form
 * (`{ search: { word: … } }`) — under any conventional prop spelling, so
 * the interim resolver stays injectable until the F4 merge deletes it.
 */
const DICTIONARY_PROP_SPELLINGS = [
  "chromeDictionary",
  "dictionary",
  "dict",
  "chrome",
  "i18n",
  "labels",
  "messages",
] as const;

function resolveDictionary(props: Record<string, unknown>): SearchChromeDictionary | undefined {
  for (const spelling of DICTIONARY_PROP_SPELLINGS) {
    const raw = props[spelling];
    if (!raw || typeof raw !== "object") continue;
    const out: Record<string, string> = {};
    for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
      if (key === "search" && value && typeof value === "object") {
        for (const [leaf, val] of Object.entries(value as Record<string, unknown>)) {
          if (typeof val === "string") out[`search.${leaf}`] = val;
        }
      } else if (typeof value === "string") {
        out[key] = value;
      }
    }
    return out as SearchChromeDictionary;
  }
  return undefined;
}

export interface SiteSearchFieldProps {
  /** Partial chrome dictionary — missing keys fall back to en (AC-16). */
  chromeDictionary?: SearchChromeDictionary;
}

type LooseProps = SiteSearchFieldProps & Record<string, unknown>;

export default function SiteSearchField(props: LooseProps) {
  const chrome = useMemo(
    () => createSearchChrome(resolveDictionary(props)),
    // The dictionary seam is an injectable literal resolved once per mount;
    // call sites pass it as a stable literal or memoized value.
    // (deps intentionally omitted)
    []
  );

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [clientCode, setClientCode] = useState<string>(PIVOT_LOCALE);
  const [rows, setRows] = useState<readonly SearchRow[]>([]);
  /**
   * Artifact load state (fix round r2, code M-1): a failed fetch is a
   * MEASURED absence and renders as one in plain words
   * ([DR-2026-08-22-numbers-stand-alone] §1) — never as the zero-match
   * state, which would fabricate `0` for whatever the reader typed.
   */
  const [loadState, setLoadState] = useState<
    "loading" | "ready" | "unavailable"
  >("loading");
  const [portalEl, setPortalEl] = useState<HTMLElement | null>(null);

  const wordRef = useRef<HTMLButtonElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  /** The results container inserted before the swap root. */
  const hostRef = useRef<HTMLDivElement | null>(null);
  /** Where focus should land once the state flip has committed. */
  const focusIntent = useRef<null | "input" | "word">(null);

  const normalizedLen = normalizeName(query).length;
  const swapped = open && normalizedLen >= MIN_QUERY_CHARS;

  // Client-side identity + lazy artifact load on first open (§4.4),
  // cached in-module afterwards. A rejected fetch lands in the
  // "unavailable" state: plain-word absence + a retry affordance while
  // the field stays open — recovery never requires close+reopen.
  useEffect(() => {
    setClientCode(segmentToClientCode(window.location.pathname));
  }, []);
  const settleIndex = useCallback(
    (code: string, guard: { alive: boolean }) => {
      setLoadState("loading");
      loadIndex(code)
        .then((loaded) => {
          if (!guard.alive) return;
          setRows(loaded);
          setLoadState("ready");
        })
        .catch(() => {
          // Fail-closed (M-1): no rows AND no fabricated count — the results
          // surface shows the absence message until a retry succeeds.
          if (!guard.alive) return;
          setRows([]);
          setLoadState("unavailable");
        });
    },
    []
  );
  useEffect(() => {
    if (!open) return;
    const guard = { alive: true };
    settleIndex(clientCode, guard);
    return () => {
      guard.alive = false;
    };
  }, [open, clientCode, settleIndex]);
  /** Retry affordance: re-fetch now (the cache self-drops on failure). */
  const retryLoad = useCallback(() => {
    settleIndex(clientCode, { alive: true });
  }, [clientCode, settleIndex]);

  // Deferred focus (the control mounts with the state flip).
  useEffect(() => {
    if (focusIntent.current === "input" && open) {
      focusIntent.current = null;
      inputRef.current?.focus();
    } else if (focusIntent.current === "word" && !open) {
      focusIntent.current = null;
      wordRef.current?.focus();
    }
  }, [open]);

  const activate = useCallback(() => {
    focusIntent.current = "input";
    setOpen(true);
  }, []);

  const restoreContent = useCallback(() => {
    document
      .querySelector<HTMLElement>("[data-search-swap-root]")
      ?.removeAttribute("hidden");
  }, []);

  /** Escape: single stroke out — query dropped, restored, collapsed (§5.2). */
  const collapseAndRestore = useCallback(() => {
    focusIntent.current = "word";
    setQuery("");
    setOpen(false);
    restoreContent();
    hostRef.current?.remove();
    hostRef.current = null;
    setPortalEl(null);
  }, [restoreContent]);

  /** Clear: content returns, the field STAYS open (DR: "cleared … restores"). */
  const clearOnly = useCallback(() => {
    setQuery("");
    inputRef.current?.focus();
  }, []);

  const hits = useMemo(
    () => (swapped ? searchRows(rows, query) : []),
    [swapped, rows, query]
  );

  // The swap: hide the page's own content IN PLACE, insert the results
  // host immediately BEFORE the vacated element (DR clause 3). Idempotent
  // under re-runs; unmount cleanup below guarantees restoration.
  useEffect(() => {
    if (!swapped) {
      if (!hostRef.current) return;
      restoreContent();
      hostRef.current.remove();
      hostRef.current = null;
      setPortalEl(null);
      return;
    }
    const root = document.querySelector<HTMLElement>("[data-search-swap-root]");
    if (!root || !root.parentNode) {
      // Composition error (§5.1): there is NO degraded render mode.
      throw new Error(
        "SiteSearchField: no [data-search-swap-root] in the document — " +
          "F4 must server-render it on the shell <main> of every page"
      );
    }
    root.setAttribute("hidden", "");
    let host = hostRef.current;
    if (!host) {
      host = document.createElement("div");
      host.setAttribute("data-search-results-host", "");
      host.className =
        "mx-auto flex w-full max-w-[1200px] flex-1 flex-col px-g7 py-g8";
      root.parentNode.insertBefore(host, root);
      hostRef.current = host;
      setPortalEl(host);
    }
  }, [swapped, restoreContent]);

  // Unmount hygiene: the page is never left hidden because of us.
  useEffect(() => {
    return () => {
      document
        .querySelector<HTMLElement>("[data-search-swap-root]")
        ?.removeAttribute("hidden");
      hostRef.current?.remove();
      hostRef.current = null;
    };
  }, []);

  const focusFirstResult = () => {
    hostRef.current?.querySelector<HTMLAnchorElement>("a[href]")?.focus();
  };

  return (
    <div
      role="search"
      data-search-open={open ? "" : undefined}
      className={[
        "relative",
        "md:data-[search-open]:absolute md:data-[search-open]:inset-y-0",
        "md:data-[search-open]:left-0 md:data-[search-open]:right-0",
        "md:data-[search-open]:z-50",
      ].join(" ")}
    >
      {/* Closed: "Search" is a word in the nav — a real control occupying
          only its word-width. No icon-only ghost, no box (DR clause 2). */}
      {!open && (
        <button
          ref={wordRef}
          type="button"
          onClick={activate}
          className={[
            "flex h-[44px] items-center px-g5 font-ui text-sm text-text-main",
            "transition-[color,box-shadow] duration-[var(--duration-fast)] ease-[var(--ease-state)]",
            "hover:text-accent-foreground hover:[box-shadow:var(--effect-hover-outline)]",
            "outline-none focus-visible:text-accent-foreground focus-visible:[box-shadow:var(--effect-gold-highlight-ring)]",
          ].join(" ")}
        >
          {chrome("search.word")}
        </button>
      )}

      {/* Open: an input growing across the row the nav was using — the
          mount takes the header band via its data-search-open geometry. */}
      {open && (
        <div className="mx-auto flex h-full w-full max-w-[1200px] items-center gap-g5 border-b border-border bg-bg-1 px-g7">
          <input
            ref={inputRef}
            type="text"
            value={query}
            aria-label={chrome("search.fieldLabel")}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                e.preventDefault();
                collapseAndRestore();
              } else if (e.key === "ArrowDown") {
                e.preventDefault();
                focusFirstResult();
              } else if (e.key === "Enter") {
                e.preventDefault();
                hostRef.current
                  ?.querySelector<HTMLAnchorElement>("a[href]")
                  ?.click();
              }
            }}
            className={[
              "h-[44px] w-full min-w-0 flex-1 border border-input bg-bg-2 px-g4",
              "font-ui text-base text-text-emph",
              "outline-none focus-visible:[box-shadow:var(--effect-gold-highlight-ring)]",
            ].join(" ")}
          />
          {/* The clear affordance is type="button" — never submit (§5.5). */}
          <button
            type="button"
            aria-label={chrome("search.clear")}
            onClick={clearOnly}
            className={[
              "flex h-[44px] items-center px-g4 font-ui text-sm text-text-main",
              "transition-[color,box-shadow] duration-[var(--duration-fast)] ease-[var(--ease-state)]",
              "hover:text-accent-foreground hover:[box-shadow:var(--effect-hover-outline)]",
              "outline-none focus-visible:text-accent-foreground focus-visible:[box-shadow:var(--effect-gold-highlight-ring)]",
            ].join(" ")}
          >
            {chrome("search.clear")}
          </button>
        </div>
      )}

      {/* Live region: the hit count as a bare number after each
          keystroke-driven change (§7). Plain words; no enum vocabulary.
          A failed artifact load announces the absence in words instead —
          a fabricated `0` here is exactly the M-1 defect class. */}
      <span className="sr-only" aria-live="polite">
        {swapped
          ? loadState === "unavailable"
            ? chrome("search.unavailable")
            : chrome.count("search.countTemplate", { count: hits.length })
          : ""}
      </span>

      {/* Results replace the page content in place, immediately before
          the hidden swap root — outside this React tree by design. */}
      {portalEl
        ? createPortal(
            <SearchResultsView
              hits={hits}
              query={query}
              chrome={chrome}
              unavailable={loadState === "unavailable"}
              onRetry={retryLoad}
              onArrowUp={() => inputRef.current?.focus()}
              onEscape={collapseAndRestore}
            />,
            portalEl
          )
        : null}
    </div>
  );
}
