"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import {
  Command,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { LOCALES, PIVOT_LOCALE, type LocaleRecord } from "@/i18n/locales";
import { Link, usePathname } from "@/i18n/navigation";

/**
 * The locale combobox (§5) — Radix Popover + Command upgraded per F1 §4:
 * the closed chip shows the current page-segment code (`DE`), the list shows
 * native names from the §2 table, typed filtering is accepted, focus rides
 * the gold `--ring` recipe and the selected row carries the white glow.
 *
 * Items are real `<a href>`s (server-renderable link graph, seo-standard §2):
 * prefixed locales go through i18n/navigation Link — the path is preserved
 * and only the locale segment changes (deep-path switching law,
 * localization-architecture §4; at F4 every page is its locale root, so every
 * switch resolves). The PIVOT target is a plain anchor to `/`: bare paths are
 * its canonical form and `/en` never exists (§3 rules 1–2), while an explicit
 * `locale` prop would force-prefix it.
 */
function SwitchLink({
  target: locale,
  href,
  active,
  className,
  children,
}: {
  target: LocaleRecord;
  href: string;
  active?: boolean;
  className?: string;
  children: ReactNode;
}) {
  const shared = {
    "aria-current": active || undefined,
    className,
    // N1 fix (review-f4-code r1): hreflang takes the §2 BCP-47 column
    // (`pt-BR`), never the URL segment id (`pt-br`) — same source the
    // <html lang> law reads.
    hrefLang: locale.bcp47,
  } as const;

  if (locale.id === PIVOT_LOCALE) {
    return (
      <a href="/" {...shared}>
        {children}
      </a>
    );
  }
  return (
    <Link href={href} locale={locale.id} {...shared}>
      {children}
    </Link>
  );
}

export default function LocaleCombobox({
  currentLocale,
}: {
  currentLocale: string;
}) {
  const t = useTranslations("chrome");
  const pathname = usePathname();
  const current = LOCALES.find((l) => l.id === currentLocale);
  const target = pathname ?? "/";

  return (
    <div className="relative flex items-center">
      {/* Server-rendered link graph (seo-standard §2): the same-path switch
          targets as real <a href>s for the OTHER locales (cross-locale row,
          localization-architecture §2), hidden until focused (skip-link
          pattern) because Radix portals never SSR their content. */}
      <nav aria-label={t("locale.listLabel")} className="contents">
        {LOCALES.filter((l) => l.id !== currentLocale).map((l) => (
          <SwitchLink
            key={l.id}
            target={l}
            href={target}
            className={[
              "sr-only",
              "focus-visible:not-sr-only focus-visible:absolute focus-visible:right-0 focus-visible:top-full focus-visible:z-50",
              "border border-border bg-bg-1 px-g5 py-g4 font-ui text-base text-text-emph",
            ].join(" ")}
          >
            {l.nativeName}
          </SwitchLink>
        ))}
      </nav>
      <Popover>
        <PopoverTrigger
          aria-label={t("locale.triggerLabel")}
          className={[
            "inline-flex h-[35px] min-w-[52px] items-center justify-center px-g5",
            "border border-input bg-bg-4 font-ui text-sm tracking-[0.08em] text-text-bright",
            "transition-[color,box-shadow] duration-[var(--duration-fast)] ease-[var(--ease-state)]",
            "hover:[box-shadow:var(--effect-hover-outline)] hover:text-accent-foreground",
            "outline-none focus-visible:[box-shadow:var(--effect-gold-highlight-ring)]",
            "data-[state=open]:[box-shadow:var(--effect-gold-highlight-ring)] data-[state=open]:text-accent-foreground",
          ].join(" ")}
        >
          {(current?.id ?? currentLocale).toUpperCase()}
        </PopoverTrigger>
        <PopoverContent align="end" className="w-[240px] p-g3">
          <Command>
            <CommandInput aria-label={t("locale.listLabel")} placeholder="" />
            <CommandList>
              <CommandGroup>
                {LOCALES.map((l) => {
                  const active = l.id === currentLocale;
                  return (
                    <CommandItem key={l.id} asChild value={`${l.nativeName} ${l.id}`}>
                      <SwitchLink
                        target={l}
                        href={target}
                        active={active}
                        className="font-ui text-base"
                      >
                        {l.nativeName}
                      </SwitchLink>
                    </CommandItem>
                  );
                })}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
}
