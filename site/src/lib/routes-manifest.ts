/**
 * The single route registry (§5): header nav AND footer render from these
 * entries and can therefore never disagree. Section links render ONLY from
 * entries with `live: true` whose target route exists — unbuilt sections are
 * omitted, never captioned (copy-earns-its-place ¶2); each landing piece
 * flips its own row to `live: true`.
 *
 * Filename is the confirmed PT16 seam (§9): SEO generators import
 * locales/routes from THIS module — no `routes.ts` exists or will.
 */
export interface RouteEntry {
  readonly id: string;
  /** Page-plane href (§2 `id` column) — resolve through i18n/navigation. */
  readonly href: string;
  /**
   * Chrome key from the §4 thirteen-key inventory — no second vocabulary.
   */
  readonly labelKey: `chrome.${string}`;
  readonly live: boolean;
}

export const ROUTES: readonly RouteEntry[] = [
  {
    id: "home",
    href: "/",
    labelKey: "chrome.header.homeLabel",
    live: true,
  },
  // Dormant rows — flip `live` when the owning piece lands its route:
  { id: "database", href: "/db", labelKey: "chrome.nav.database", live: false },
  { id: "map", href: "/map", labelKey: "chrome.nav.map", live: false },
  { id: "guides", href: "/guides", labelKey: "chrome.nav.guides", live: false },
  { id: "news", href: "/news", labelKey: "chrome.nav.news", live: false },
  { id: "tools", href: "/tools", labelKey: "chrome.nav.tools", live: false },
];

/** Entries allowed to render — the only source of nav/footer links. */
export const liveRoutes: readonly RouteEntry[] = ROUTES.filter((r) => r.live);
