# Fonts — self-host contract (F1, spec-tokens.mdx §1)

No font binaries are committed. Both faces are identifiable open fonts under
SIL OFL 1.1 (redistribution permitted), but per pack convention binaries stay
out of git: they are fetched into this directory at setup time under the
EXACT filenames that `src/styles/tokens.css`'s `@font-face` rules declare.
The served path contract is `/fonts/<file>.woff2` (site `public/` root).

## Faces (the game's own picks, confirmed by style.css `#defaultFonts`)

| File | Face | Weight/style | Game source |
|---|---|---|---|
| `eb-garamond-latin-400-normal.woff2` | EB Garamond | 400 | `eb_garamond_medium.fnt` 16 — all UI text |
| `eb-garamond-latin-700-normal.woff2` | EB Garamond | 700 | `eb_garamond_bold.fnt` 16 |
| `eb-garamond-latin-400-italic.woff2` | EB Garamond | 400 italic | `eb_garamond_italic.fnt` 16/19 — dialog body |
| `eb-garamond-latin-ext-400-normal.woff2` | EB Garamond | 400 | latin-ext companion of the medium face |
| `im-fell-english-latin-400-normal.woff2` | IM Fell English | 400 | `im_fell_english.fnt` 25 — display/unit names |

Subsets: latin + latin-ext only (the game's own latin faces; CJK/KR locales are
served by Noto, below). The `unicode-range`s in tokens.css match these two
subsets so browsers fetch at most one file per glyph run.

## Fetch (Google Fonts, OFL 1.1)

```sh
cd site/public/fonts
curl -LO "https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,700;1,400&family=IM+Fell+English&display=swap" -A "Mozilla/5.0"
# then download each woff2 URL from that CSS to the filenames above, or use
# google-webfonts-helper: https://gwfh.mranftl.com/api/fonts/eb-garamond?download=zip&subsets=latin,latin-ext&variants=regular,700,italic&formats=woff2
```

### The 700 is NOT downloadable as a file (variable-font trap, r3)

With a browser UA, Google's css2 serves EB Garamond as a **variable font**:
the `font-weight: 700` @font-face blocks point at the *same* woff2 URLs as
the 400 blocks, so per-URL download stages one byte-identical file under
both names — a synthetic-bold photocopy (this shipped in r2 and was caught
by critique r3's `cmp`). The rule: after fetching per route A, `cmp` every
two files whose contract names differ; if any pair collides, **instantiate
the missing weight from the VF** — download the colliding URL once, pin the
axis with `fonttools varLib.instancer` (`instantiateVariableFont(f,
{"wght": 700})`, then set name IDs 1/2/4/6 + head.macStyle bold +
OS/2.fsSelection bold), save as woff2 under the 700 contract name.
Route B (google-webfonts-helper) hands you true static instances instead;
its outlines are point-identical to the instanced cut. Verify before done:
byte-distinct from the 400 (`cmp`) *and* `usWeightClass == 700`.

## Fallback discipline

Stacks degrade to `serif` until files land (`--font-ui`, `--font-flavor`).
Never substitute a generic serif as the primary once files exist; never let
a sans carry latin chrome (serif-first canon — Noto Sans is CJK/KR fallback
only). No stack contains any named system face: latin chrome is EB Garamond
and IM Fell English only.

## CJK / KR locales (deferred)

`--font-cjk` = `"Noto Sans CJK SC", "Noto Sans KR", sans-serif`, kept behind
the serifs. Full CJK woff2 sets are multi-MB: when zh/kolocale pages ship,
link Google's split-subset CSS for Noto Sans SC/KR on those locale routes only
(locale lives in the URL per DR-2026-08-20-locale-urls) rather than self-hosting
up front. No @font-face for them in tokens.css yet — declared, not loaded.
