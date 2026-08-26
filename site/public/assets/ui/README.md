# Element textures — served 9-slice chrome contract (F1)

The seven extracted element binaries `site/src/styles/tokens.css`'s served
contract (`--tex-*`, `/assets/ui/<file>.png`) needs. Copied byte-exact from
`design/extracted-ui/` (adler32-verified against the game pak — see
`design/extracted-ui/EXTRACT-LOG.mdx`) at setup time; **binaries are not
committed** (game-derived data stays local per AGENTS.md rule 5, same
convention as `site/public/fonts/`). Re-stage after a fresh clone:

```sh
cp design/extracted-ui/{dialogBg,HeaderBg,SmallEntryBG,buttonBg,RarityBackground,ListHeader,ListHeaderHighlight}.png \
   site/public/assets/ui/
```

| File | Served token | Slice | Role |
|---|---|---|---|
| `dialogBg.png` | `--tex-dialog-bg` | 20 | dialogs / chips / tooltip card |
| `HeaderBg.png` | `--tex-header-bg` | 10 | section band h35 |
| `SmallEntryBG.png` | `--tex-small-entry` | 10 | section body (tucks −10px) |
| `buttonBg.png` | `--tex-button` | 25 5 | button vgrid 3 (normal/hover/pressed) |
| `RarityBackground.png` | `--tex-rarity` | hgrid 3 | slot frames: uncommon/rare/legendary |
| `ListHeader.png` | `--tex-list-header` | — (stretch) | list row band 332×18 (`.itemLine` normal) |
| `ListHeaderHighlight.png` | `--tex-list-header-highlight` | — (stretch) | same band `:hover` / `.selected` |

Every `/assets/ui/*.png` and `/fonts/*.woff2` path declared in tokens.css is
guarded by a vitest test (`site/src/styles/tokens.test.ts` § served refs):
a token whose binary is missing from this directory fails `npm test`, so a
latent 404 cannot ship again.
