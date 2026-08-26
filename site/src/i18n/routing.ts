import { defineRouting } from "next-intl/routing";
import { LOCALES, PIVOT_LOCALE } from "./locales";

/**
 * THE segment law (§3). Ids are the §2 PAGE segments (id column) — /data/**
 * URLs compose from the §2 client-code column, never from these strings
 * (§2 r1b composition law).
 */
export const routing = defineRouting({
  locales: LOCALES.map((l) => l.id),
  defaultLocale: PIVOT_LOCALE, // pivot bare, others prefixed
  localePrefix: "as-needed",
  localeDetection: false, // explicit links only (NWG §9; seo-standard §1)
});
