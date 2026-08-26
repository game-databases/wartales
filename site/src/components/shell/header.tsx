import { getTranslations } from "next-intl/server";
import LocaleCombobox from "./locale-combobox";
import NavRow from "./nav-row";

/**
 * The wordmark lockup — IM Fell English over the canon display step. Links
 * to `/`, the BARE pivot path from every locale: one product, one home
 * (§5; DR-2026-08-20-locale-urls ¶1). Deliberately a plain anchor, not the
 * locale-aware Link — it must never gain a locale prefix.
 */
export function Wordmark() {
  return (
    <a
      href="/"
      className={[
        "font-flavor text-display tracking-[0.08em] text-text-emph",
        "transition-[color,text-shadow] duration-[var(--duration-fast)] ease-[var(--ease-state)]",
        "hover:text-accent-foreground hover:[text-shadow:var(--text-shadow-over-art)]",
        "outline-none focus-visible:text-accent-foreground focus-visible:[box-shadow:var(--effect-gold-highlight-ring)]",
        "px-g3 py-g2",
      ].join(" ")}
    >
      WARTALES
    </a>
  );
}

/**
 * Sticky header — `banner` landmark, opaque `--bg-1` surface with the bottom
 * bevel `--border`. Left: wordmark · center/left: nav row (manifest-driven)
 * with F5's reserved search mount at its right region · right: locale
 * combobox. No search input, no "Search" word — that field is F5's.
 */
export default async function Header({ locale }: { locale: string }) {
  const t = await getTranslations("chrome");
  return (
    <header className="sticky top-0 z-40 border-b border-border bg-bg-1">
      <div className="mx-auto flex w-full max-w-[1200px] items-center gap-g7 px-g7 py-g3">
        <Wordmark />
        <NavRow />
        <LocaleCombobox currentLocale={locale} />
      </div>
    </header>
  );
}
