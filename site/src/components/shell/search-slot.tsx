/**
 * F5's reserved mount (F4 §5; DR-2026-08-22-search-is-not-a-page).
 *
 * Renders NOTHING at F4 — no input, no "Search" word, no disabled control
 * (omitted, not captioned). Contract handed to F5: the mount occupies the
 * nav row's right region; closed-state "word in the nav", open-state
 * grow-across-the-row, 2-char trigger and in-place swap are F5's behaviors.
 *
 * Integration is one composition edit: this stub renders F5's field host
 * inside this element instead of nothing — the `data-shell-slot="search"`
 * attribute survives F5's takeover, and there is no `/search` route and no
 * search link anywhere in F4 output.
 */
export default function SearchSlot() {
  return <div data-shell-slot="search" />;
}
