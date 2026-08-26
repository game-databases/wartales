"use client";

import { useTranslations } from "next-intl";
import { Link, usePathname } from "@/i18n/navigation";
import { liveRoutes } from "@/lib/routes-manifest";
import SearchSlot from "./search-slot";

const NS = "chrome." as const;

/**
 * The header's nav row (§5). Links render ONLY from routes-manifest live
 * rows, resolved through i18n/navigation so each lands on the current
 * locale's canonical form. Hover = white outline + brighten; active section
 * = white glow. Below the narrow breakpoint the row collapses into a
 * disclosure sheet (native <details>/<summary>, same chrome recipes,
 * comfortable touch targets, 12px floor intact).
 */
export default function NavRow() {
  const t = useTranslations("chrome");
  const pathname = usePathname();

  return (
    <div className="flex min-w-0 flex-1 items-center gap-g6">
      {/* Desktop: links ride the HeaderBg band (h35, slice 10, −3px offset) */}
      <nav className="hidden md:block">
        <ul className="wt-band-header flex list-none items-stretch gap-g2">
          {liveRoutes.map((route) => {
            const active = pathname === route.href;
            return (
              <li key={route.id} className="flex items-stretch">
                <Link
                  href={route.href}
                  aria-current={active ? "page" : undefined}
                  className={[
                    "wt-title-offset flex items-center px-g5",
                    "font-ui text-sm transition-[color,box-shadow] duration-[var(--duration-fast)] ease-[var(--ease-state)]",
                    "outline-none focus-visible:[box-shadow:var(--effect-gold-highlight-ring)]",
                    active
                      ? "[box-shadow:var(--effect-selected-glow)] text-accent-foreground"
                      : "text-text-main hover:text-accent-foreground hover:[box-shadow:var(--effect-hover-outline)]",
                  ].join(" ")}
                >
                  {t(route.labelKey.slice(NS.length))}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="ml-auto flex items-center gap-g5">
        <SearchSlot />

        {/* Narrow viewport disclosure — native semantics, no JS state */}
        <details className="group relative md:hidden">
          <summary
            aria-label={t("footer.sections")}
            className={[
              "flex h-[44px] w-[44px] cursor-pointer list-none items-center justify-center",
              "border border-border bg-bg-4 text-text-bright",
              "transition-[color,box-shadow] duration-[var(--duration-fast)] ease-[var(--ease-state)]",
              "hover:[box-shadow:var(--effect-hover-outline)] hover:text-accent-foreground",
              "focus-visible:[outline:none] focus-visible:[box-shadow:var(--effect-gold-highlight-ring)]",
              "[&::-webkit-details-marker]:hidden",
            ].join(" ")}
          >
            <span aria-hidden="true" className="flex flex-col gap-g2">
              <span className="block h-px w-[20px] bg-current" />
              <span className="block h-px w-[20px] bg-current" />
              <span className="block h-px w-[20px] bg-current" />
            </span>
          </summary>
          <div
            id="shell-nav-sheet"
            className="wt-panel absolute right-0 top-[calc(100%+var(--space-5))] z-50 flex min-w-[200px] flex-col border border-border bg-bg-1 p-g4"
          >
            {liveRoutes.map((route) => {
              const active = pathname === route.href;
              return (
                <Link
                  key={route.id}
                  href={route.href}
                  aria-current={active ? "page" : undefined}
                  className={[
                    "flex min-h-[44px] items-center px-g5 py-g4 font-ui text-base",
                    "transition-[color,box-shadow] duration-[var(--duration-fast)] ease-[var(--ease-state)]",
                    "outline-none focus-visible:[box-shadow:var(--effect-gold-highlight-ring)]",
                    active
                      ? "[box-shadow:var(--effect-selected-glow)] text-accent-foreground"
                      : "text-text-main hover:bg-accent hover:text-accent-foreground hover:[box-shadow:var(--effect-hover-outline)]",
                  ].join(" ")}
                >
                  {t(route.labelKey.slice(NS.length))}
                </Link>
              );
            })}
          </div>
        </details>
      </div>
    </div>
  );
}
