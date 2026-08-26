/**
 * Name normalization for the header search — ONE implementation, both
 * sides (spec-f5-search §4.3; DR-2026-08-22-search-is-not-a-page ¶5).
 *
 * The artifact ships NO normalized column: a Python + TypeScript pair of
 * normalizers would be a drift engine. This file is the whole guarantee —
 * server consumers and the client island import it identically.
 *
 * Environment purity (AC-11): this module touches nothing environmental —
 * no window/document/navigator/localStorage/fetch, no node: builtins, no
 * React. A guard test greps this file for exactly those tokens.
 *
 * Step order is load-bearing (§4.3): markup dies before NFKD so markup-
 * wrapped macros cannot survive as text; `ł→l` runs AFTER case-folding
 * because `Ł`.toLowerCase() is what produces the foldable form (U+0142 has
 * neither canonical nor compatibility decomposition, so steps 4–5 leave it
 * intact — the explicit step 7 is the only thing that folds it);
 * whitespace collapses last so stripped markup keeps words apart.
 */
export function normalizeName(s: string): string {
  return s
    .replace(/<[^>]*>/g, " ") // 1. Heaps rich-text tags (<b>, <item>…</item>) → space
    .replace(/\[[^\]]*\]/g, " ") // 2. bracket macros ([NAME], [VALUE(…)], [ASSIGN]) → space
    .replace(/::[A-Za-z0-9_]+::/g, " ") // 3. ::color:: spans (::value::, ::count::) → space
    .normalize("NFKD") // 4. canonical + compatibility decompose
    .replace(/\p{M}/gu, "") // 5. drop combining marks (ё→е, Épée→epee)
    .toLowerCase() // 6. case-fold equivalent for our scripts
    .replace(/ł/g, "l") // 7. explicit fold — U+0142 has NO Unicode decomposition
    .replace(/\s+/g, " ") // 8. collapse whitespace
    .trim();
}
