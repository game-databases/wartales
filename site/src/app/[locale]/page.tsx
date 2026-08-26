import { notFound } from "next/navigation";
import { setRequestLocale } from "next-intl/server";
import { isLocaleId } from "@/i18n/locales";

/**
 * Smoke home (§5): the wordmark lockup over `--bg-1`, nothing else — no
 * tagline, no data claims, no "coming soon" prose (anti-slop). PT01 replaces
 * this file wholesale in its own commit.
 */
export default async function LocaleHome({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!isLocaleId(locale)) notFound();
  setRequestLocale(locale);

  return (
    <section className="flex flex-1 items-center justify-center py-g8">
      <h1 className="font-flavor text-display tracking-[0.12em] text-text-emph">
        WARTALES
      </h1>
    </section>
  );
}
