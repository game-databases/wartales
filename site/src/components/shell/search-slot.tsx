/**
 * F5's reserved mount (F4 §5; DR-2026-08-22-search-is-not-a-page).
 *
 * Landed state (spec-f5-search §5.1): the element still owns the nav
 * row's right region and carries `data-shell-slot="search"` — F4's smoke
 * greps for the attribute — and now hosts F5's field inside it: closed
 * "Search" word, open input, 2-char in-place swap. The swap machinery
 * consumes F4's server-rendered `data-search-swap-root` from this
 * component's own side; no search code lives anywhere else in shell.
 *
 * There is no `/search` route and no search link anywhere in F4 output
 * (spec-f5 §6).
 */
import SiteSearchField from "../header/SiteSearchField";

export default function SearchSlot() {
  return (
    <div data-shell-slot="search">
      <SiteSearchField />
    </div>
  );
}
