import { getTranslations } from "next-intl/server";

/**
 * Locale-scoped not-found — MECHANISM ONLY (§1); PT17 brands it. Renders
 * inside [locale]/layout so chrome is localized and `<html lang>` carries
 * the requested locale's BCP-47 tag. Copy comes from the §4 chrome keys; no
 * theorizing about 404s beyond them.
 */
export default async function NotFound() {
  const t = await getTranslations("chrome");
  return (
    <section className="flex flex-1 flex-col justify-center gap-g5 py-g8">
      <h1 className="font-flavor text-lg text-text-emph">
        {t("notFound.title")}
      </h1>
      <p className="font-ui text-base text-text-main">{t("notFound.body")}</p>
    </section>
  );
}
