import type { ReactNode } from "react";
import { notFound } from "next/navigation";
import { NextIntlClientProvider } from "next-intl";
import { getMessages, getTranslations, setRequestLocale } from "next-intl/server";
import GoogleAnalytics from "@/components/analytics/google-analytics";
import Footer from "@/components/shell/footer";
import Header from "@/components/shell/header";
import { LOCALES, bcp47Of, isLocaleId } from "@/i18n/locales";
import "../../styles/globals.css";

/**
 * §3 rule 7 (SSG): all nine ids prerender; every locale home is static HTML.
 */
export function generateStaticParams() {
  return LOCALES.map((l) => ({ locale: l.id }));
}

/**
 * AC 13: the /zh and /ko documents link Google's split-subset Noto CSS for
 * their CJK/KR fallback face (fonts README pattern) — the other seven emit
 * none. React hoists the <link> into <head>.
 */
function CjkFontLink({ locale }: { locale: string }) {
  if (locale !== "zh" && locale !== "ko") return null;
  const family = locale === "zh" ? "Noto+Sans+SC" : "Noto+Sans+KR";
  return (
    <link
      rel="stylesheet"
      href={`https://fonts.googleapis.com/css2?family=${family}:wght@400;700&display=swap`}
      precedence="default"
    />
  );
}

export default async function LocaleLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ locale: string }>;
}) {
  // §3 rule 5 (m5 r1): validate the resolved id against the §2 table and
  // call notFound() BEFORE anything localizes — an unknown-locale request
  // answers its 404 from the root boundary; there is no localizing a locale
  // that does not exist.
  const { locale } = await params;
  if (!isLocaleId(locale)) notFound();

  setRequestLocale(locale);

  const [messages, t] = await Promise.all([
    getMessages(),
    getTranslations("chrome"),
  ]);

  return (
    <html lang={bcp47Of(locale)}>
      <GoogleAnalytics />
      <body className="flex min-h-dvh flex-col font-ui">
        <CjkFontLink locale={locale} />
        <NextIntlClientProvider locale={locale} messages={messages}>
          {/* First focusable element: skip link */}
          <a
            href="#main"
            className={[
              "sr-only focus-visible:not-sr-only focus-visible:absolute focus-visible:left-g5 focus-visible:top-g5 focus-visible:z-50",
              "border border-border bg-bg-1 px-g5 py-g4 font-ui text-base text-text-emph",
              "focus-visible:[box-shadow:var(--effect-gold-highlight-ring)] focus-visible:[outline:none]",
            ].join(" ")}
          >
            {t("a11y.skipToContent")}
          </a>
          <Header locale={locale} />
          {/* F5 inbound seam (§5 r1): attribute placement only — F5's swap
              machinery touches this element exclusively from its own side. */}
          <main
            id="main"
            data-search-swap-root=""
            className="mx-auto flex w-full max-w-[1200px] flex-1 flex-col px-g7 py-g8"
          >
            {children}
          </main>
          <Footer />
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
