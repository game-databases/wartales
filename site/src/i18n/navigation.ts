import { createNavigation } from "next-intl/navigation";
import { routing } from "./routing";

/**
 * Locale-aware navigation (§3): Link/redirect/usePathname keep the current
 * path and swap only the locale segment — the deep-path switching law of
 * localization-architecture §4. Every internal <a> goes through here so no
 * link ever emits a /en prefix (DR-2026-08-20-locale-urls ¶1).
 */
export const { Link, redirect, usePathname, useRouter, getPathname } =
  createNavigation(routing);
