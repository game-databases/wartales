#!/bin/sh
# Wartales pack extraction entrypoint - POSIX thin wrapper.
# The real entrypoint is run_all.ps1 (Windows host / NE8K); this wrapper only
# forwards every argument to it. Defaults come from EXTRACTION-LOG.md
# [DR-2026-08-18-pipeline]. See: ./run_all.sh --help
dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec powershell -NoProfile -ExecutionPolicy Bypass -File "$dir/run_all.ps1" "$@"
