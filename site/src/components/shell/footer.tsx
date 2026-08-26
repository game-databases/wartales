import { getTranslations } from "next-intl/server";
import { Link } from "@/i18n/navigation";
import { liveRoutes } from "@/lib/routes-manifest";
import { Wordmark } from "./header";

const NS = "chrome." as const;

/**
 * Footer — `contentinfo` landmark (§5). Same manifest-driven law as the
 * header: wordmark repeat plus section link columns fed by the same
 * `routes-manifest.ts` (they deepen automatically when PT02's taxonomy menu
 * lands — NWG dbMenu pattern). No invented legal lines, no absence copy.
 */
export default async function Footer() {
  const t = await getTranslations("chrome");
  return (
    <footer
      aria-label={t("footer.label")}
      className="border-t border-border bg-bg-1"
    >
      <div className="mx-auto flex w-full max-w-[1200px] flex-col gap-g6 px-g7 py-g8">
        <div>
          <Wordmark />
        </div>
        <nav aria-label={t("footer.sections")}>
          <ul className="flex list-none flex-wrap gap-g2">
            {liveRoutes.map((route) => (
              <li key={route.id}>
                <Link
                  href={route.href}
                  className={[
                    "flex items-center px-g4 py-g3 font-ui text-sm text-text-main",
                    "transition-[color,box-shadow] duration-[var(--duration-fast)] ease-[var(--ease-state)]",
                    "outline-none focus-visible:[box-shadow:var(--effect-gold-highlight-ring)]",
                    "hover:text-accent-foreground hover:[box-shadow:var(--effect-hover-outline)]",
                  ].join(" ")}
                >
                  {t(route.labelKey.slice(NS.length))}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </div>
    </footer>
  );
}
