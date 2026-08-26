import { notFound } from "next/navigation";
import { setRequestLocale } from "next-intl/server";
import { isLocaleId } from "@/i18n/locales";

/**
 * B1 r1 — the catch-all whose ONLY body is notFound(). This is the mechanism
 * that makes the locale-scoped not-found fire for unmatched URLs: a nested
 * not-found file alone never matches a URL, but a matched route calling
 * notFound() renders `[locale]/not-found.tsx` inside this layout — localized
 * chrome, `<html lang>` of the requested locale (AC 14).
 */
export default async function CatchAll({
  params,
}: {
  params: Promise<{ locale: string; rest?: string[] }>;
}) {
  const { locale } = await params;
  if (!isLocaleId(locale)) notFound();
  setRequestLocale(locale);
  notFound();
}
