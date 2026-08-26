# _refs/upstream — fetched reference sources (provenance)

All fetched 2026-08-24 from GitHub for the hlboot.dat dig
([decompile-dig-1](../../../docs/decompile-dig-1.mdx)). Reference material
only — our parser is `../hlboot_probe.py`.

- `opcodes.h`, `opcodes-1.12.h` — HaxeFoundation/hashlink tags **1.13** and
  **1.12**, `src/opcodes.h` (v4-era opcode tables; verified identical to
  each other, 99 ops). Fetched via codeload tarballs.
- `hl.h`, `hlmodule.h` (parent dir) — hashlink headers carrying the
  type-kind enum family this build uses (HDYN=9…HGUID=23); matches the
  shipped `libhl.dll` export surface (`hlt_dynobj`, `hl_guid_str`).
- crashlink — N3rdL0rd/crashlink @ master (pure-Python HashLink toolkit,
  MIT; same author as the pack's PAKTool cross-verifier). Used ONLY as an
  independent second implementation for element-wise cross-checking
  (`_crosscheck.py`) and for pinning the fork-family opcodes 99–101
  (`Prefetch`, `Asm`, `Catch`). Not vendored into the repo; re-fetch with:
  `curl -L https://codeload.github.com/N3rdL0rd/crashlink/tar.gz/refs/heads/main`.
  Note: its deserialiser does NOT assert EOF alignment; our zero-slack
  walk is the stricter of the two proofs.
- hl-rev / hlbc were surveyed (010 template / Rust tooling) but not used;
  hlbc release binaries fail on this build's kind numbering.
