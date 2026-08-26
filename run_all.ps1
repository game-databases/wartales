# run_all.ps1 - Wartales pack extraction entrypoint (Windows host / NE8K).
#
# Doctrine: _foundation/extraction-doctrine.md "Reproducible single-entrypoint
# pipeline" [DR-2026-08-18-pipeline]. ONE discoverable entrypoint: fresh clone +
# fresh game copy + this file reproduces the full extracted/ output A->Z.
# Defaults (client path, buildid, paks, out dir, python) are read from
# EXTRACTION-LOG.md at the pack root - that log is the source these defaults
# come from; a tooling change or game patch updates log + entrypoint in the
# same commit (AGENTS.md rule 5).
#
# Usage:
#   run_all.ps1                       every stage in fixed order (stops at first failure)
#   run_all.ps1 <path-to-client>      every stage against the given client root
#   run_all.ps1 <stage>               one stage in isolation
#   run_all.ps1 <stage> --client <path>
#   run_all.ps1 --list                enumerate stages + resolved defaults
#   run_all.ps1 --dry-run [stage]     print the exact command(s) without running anything
#   run_all.ps1 -h | --help           this usage
#
# Stages in fixed order: harvest -> map -> decompile -> datasets -> relink -> emit.
# Only stages marked BUILT execute; NOT BUILT stages fail loudly (exit 3) and
# name the doc/tool that unblocks them. Each stage is idempotent and runnable
# in isolation.
#
# Stage 4-6 command chains (CDB/BUILDID/PYTHON defaults come from EXTRACTION-LOG.md):
#   datasets : cdb_emit wave1+wave2 -> data/_draft | cdb_verify GATE | promote_drafts --plane data | cdb_verify canonical
#   relink   : promote_drafts --plane relinks | cdb_verify canonical GATE | relink_catalog -> RELATIONS.md + relinks/matrix.json
#   emit     : locale_bridge_dig (availability regen) | validate_all -> validation-report.json + VALIDATION-REPORT.md
#
# Exit codes: 0 ok | 2 usage error | 3 not-built stub | otherwise the failing
# child's own code (harvest.py: 2 preflight/usage, 3 format/integrity,
# 4 output collision).

$ErrorActionPreference = 'Stop'
$PackRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $PackRoot

$LogName = 'EXTRACTION-LOG.md'
$BeginMark = 'RUN_ALL-DEFAULTS-BEGIN'
$EndMark = 'RUN_ALL-DEFAULTS-END'

$script:StageOrder = @('harvest', 'map', 'decompile', 'datasets', 'relink', 'emit')

$script:StageInfo = @{
    'harvest' = @{
        status = 'BUILT';
        desc = 'extract assets/content/map/res.pak byte-identically into OUT (pipeline/harvest.py)'
    };
    'map' = @{
        status = 'BUILT';
        desc = 'regenerate extracted/data/maps.json + contracts/maps.schema.json under schema validation (pipeline/map_tiles.py registry)';
    };
    'decompile' = @{
        status = 'NOT BUILT';
        desc = 'hlboot.dat bytecode -> decompiled corpus (structure layer done, decompiler pending)';
        stub = "stage 'decompile' not built - see docs/decompile-dig-1.mdx (hlboot.dat structure fully recovered in extracted/logic/hl-structure/; the operand-level disassembler + decompiler is the next build)";
    };
    'datasets' = @{
        status = 'BUILT';
        desc = 'data.cdb -> curated JSONL datasets: cdb_emit waves 1+2 into data/_draft, cdb_verify GATE, promote_drafts to extracted/data, canonical re-verify (spec-stages-datasets section 3)';
    };
    'relink' = @{
        status = 'BUILT';
        desc = 'promote the 51 pair seeds to extracted/relinks, canonical cdb_verify GATE, RELATIONS.md + relinks/matrix.json catalog (spec-stages-datasets section 4)';
    };
    'emit' = @{
        status = 'BUILT';
        desc = 'validation-only pass: locale availability regen (locale_bridge_dig) + validate_all -> validation-report.json + VALIDATION-REPORT.md reconciled to census 11,473 (spec-stages-datasets section 5)';
    };
}

function Write-UsageAndExit {
    Get-Content "$PackRoot\run_all.ps1" -TotalCount 36 -Encoding UTF8 |
        Where-Object { $_ -match '^#' } |
        ForEach-Object { $_.TrimStart('#').TrimStart() } |
        Select-Object -Skip 1
    exit 2
}

function Read-Defaults {
    # The machine-readable block inside EXTRACTION-LOG.md is the single source
    # of entrypoint defaults (DR-2026-08-18-pipeline). Keys: CLIENT, BUILDID,
    # PAKS, OUT, PYTHON. Block content is ASCII-only by contract.
    $logPath = Join-Path $PackRoot $LogName
    if (-not (Test-Path $logPath)) {
        Write-Host "ERROR: $LogName not found at pack root - it is the defaults source for this entrypoint."
        exit 2
    }
    $lines = Get-Content $logPath -Encoding UTF8
    $inside = $false
    $map = @{}
    foreach ($line in $lines) {
        if ($line -match [regex]::Escape($EndMark)) { break }
        if (-not $inside) {
            if ($line -match [regex]::Escape($BeginMark)) { $inside = $true }
            continue
        }
        if ($line -match '^\s*([A-Z]+)\s*:\s*(.+?)\s*$') {
            $map[$Matches[1]] = $Matches[2]
        }
    }
    foreach ($key in @('CLIENT', 'BUILDID', 'PAKS', 'OUT', 'CDB', 'PYTHON')) {
        if (-not $map.ContainsKey($key)) {
            Write-Host "ERROR: $LogName defaults block is missing key $key."
            exit 2
        }
    }
    return $map
}

function Invoke-Harvest {
    param([string]$Client, [string]$Out, [string]$BuildId, [string]$Python, [switch]$DryRun)

    # A rehearsal prints the exact command regardless of whether the client
    # root exists yet (e.g. planning a run on a fresh machine).
    if ($DryRun) {
        $hArgs = @('pipeline/harvest.py')
        foreach ($pak in ($script:Defaults['PAKS'] -split '\s+')) {
            $hArgs += @('--pak', (Join-Path $Client $pak))
        }
        $hArgs += @('--out', $Out, '--buildid', $BuildId)
        $quoted = foreach ($tok in (@($Python) + $hArgs)) {
            if ($tok -match '\s') { '"' + $tok + '"' } else { $tok }
        }
        Write-Host ("[dry-run] harvest would run: " + ($quoted -join ' '))
        return 0
    }

    if (-not (Test-Path $Client)) {
        Write-Host "ERROR: client root not found: $Client"
        Write-Host "Override with: run_all.ps1 harvest --client <path-to-game-files>  (or fix CLIENT in $LogName)"
        return 2
    }

    $hArgs = @('pipeline/harvest.py')
    foreach ($pak in ($script:Defaults['PAKS'] -split '\s+')) {
        $hArgs += @('--pak', (Join-Path $Client $pak))
    }
    $hArgs += @('--out', $Out, '--buildid', $BuildId)

    $quoted = foreach ($tok in (@($Python) + $hArgs)) {
        if ($tok -match '\s') { '"' + $tok + '"' } else { $tok }
    }
    Write-Host ("[harvest] " + ($quoted -join ' '))
    # native stdout flows into the function's RETURN stream in PowerShell —
    # route it to the host or $rc captures the child's output lines plus the
    # exit code and every PASS reads as FAILED
    & $Python @hArgs | Out-Host
    return $LASTEXITCODE
}

function Invoke-MapRegistry {
    param([string]$BuildId, [string]$Python, [switch]$DryRun)

    # The registry stage re-emits maps.json + the published schema copy under
    # JSON-Schema validation (spec-map-pipeline §6 AC6 "wired into run_all").
    # It cites only measurements this run produced, so rawproof + pyramid-ratio
    # must exist: run `pipeline/map_tiles.py run` for the full imagery pass.
    $mArgs = @('pipeline/map_tiles.py', 'registry', '--buildid', $BuildId)
    if ($DryRun) {
        Write-Host ("[dry-run] map would run: " + ((@($Python) + $mArgs) -join ' '))
        return 0
    }
    Write-Host ("[map] " + ((@($Python) + $mArgs) -join ' '))
    # same reason as harvest: keep python stdout out of the return stream
    & $Python @mArgs | Out-Host
    return $LASTEXITCODE
}

function Join-QuotedArgs {
    param([string[]]$Tokens)
    ($tokens | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join ' '
}

function Invoke-PipelineSteps {
    # Shared runner for stages 4-6 (map-stage pattern): a rehearsal prints
    # EVERY step's exact vector; live mode routes native stdout with
    # | Out-Host (the return-stream bug, EXTRACTION-LOG §6 — load-bearing)
    # and stops on the first nonzero child exit code.
    param([string]$Stage, [string]$Python, [object[]]$Steps, [switch]$DryRun)
    $n = $Steps.Count
    for ($i = 0; $i -lt $n; $i++) {
        if ($DryRun) {
            Write-Host ("[dry-run] {0} {1}/{2} would run: {3}" -f `
                $Stage, ($i + 1), $n,
                (Join-QuotedArgs (@($Python) + @($Steps[$i]))))
            continue
        }
        Write-Host ("[{0}] {1}" -f $Stage,
            (Join-QuotedArgs (@($Python) + @($Steps[$i]))))
        & $Python @($Steps[$i]) | Out-Host
        if ($LASTEXITCODE -ne 0) { return $LASTEXITCODE }
    }
    return 0
}

function Test-RelinkPreconditions {
    # spec-stages-datasets §4.1 equality preconditions (arbiter F11): canonical
    # data holds EXACTLY the 40 managed kinds AND data/_draft holds EXACTLY 51
    # pair files. Checked before any child runs; failure names the owner.
    param([string]$Python)
$code = @'
import os, sys
sys.path.insert(0, 'pipeline/tools')
import wave_kinds as W
DATA, DRAFT_REL = 'extracted/data', 'extracted/relinks/_draft'
OWNER = 'run_all.ps1 datasets'
if not os.path.isdir(DATA):
    print('ERROR: %s missing - owning stage: %s' % (DATA, OWNER)); sys.exit(2)
have = sorted(f[:-6] for f in os.listdir(DATA) if f.endswith('.jsonl'))
want = sorted(W.MANAGED_KINDS)
missing = [k for k in want if k not in have]
extra = [k for k in have if k not in want]
if missing or extra:
    print('ERROR: %s does not hold exactly the %d managed kinds - owning stage: %s' % (DATA, len(want), OWNER))
    if missing: print('  missing: ' + ', '.join(missing))
    if extra: print('  unexpected: ' + ', '.join(extra))
    sys.exit(2)
pairs = sorted(f for f in os.listdir(DRAFT_REL) if W.is_pair_name(f)) if os.path.isdir(DRAFT_REL) else []
if len(pairs) != W.EXPECTED_PAIR_FILES:
    print('ERROR: %s holds %d pair files, expected exactly %d - owning stage: %s' % (DRAFT_REL, len(pairs), W.EXPECTED_PAIR_FILES, OWNER)); sys.exit(2)
'@
    & $Python -c $code | Out-Host
    return $LASTEXITCODE
}

function Test-EmitPreconditions {
    # spec-stages-datasets §5.1 preconditions; locale_availability.jsonl is
    # deliberately NOT one (emit's own step 1 produces it — arbiter F6).
    param([string]$Python)
$code = @'
import os, sys
sys.path.insert(0, 'pipeline/tools')
import wave_kinds as W
DATA, CANON_REL = 'extracted/data', 'extracted/relinks'
if os.path.isdir(DATA):
    have = sorted(f[:-6] for f in os.listdir(DATA) if f.endswith('.jsonl'))
    want = sorted(W.MANAGED_KINDS)
    missing = [k for k in want if k not in have]
    extra = [k for k in have if k not in want]
    if missing or extra:
        print('ERROR: %s does not hold exactly the %d managed kinds - owning stage: run_all.ps1 datasets' % (DATA, len(want)))
        if missing: print('  missing: ' + ', '.join(missing))
        if extra: print('  unexpected: ' + ', '.join(extra))
        sys.exit(2)
else:
    print('ERROR: %s missing - owning stage: run_all.ps1 datasets' % DATA); sys.exit(2)
pairs = sorted(f for f in os.listdir(CANON_REL) if W.is_pair_name(f)) if os.path.isdir(CANON_REL) else []
if len(pairs) != W.EXPECTED_PAIR_FILES:
    print('ERROR: %s holds %d pair files, expected exactly %d - owning stage: run_all.ps1 relink' % (CANON_REL, len(pairs), W.EXPECTED_PAIR_FILES)); sys.exit(2)
if not os.path.isfile('extracted/RELATIONS.md'):
    print('ERROR: extracted/RELATIONS.md missing - owning stage: run_all.ps1 relink'); sys.exit(2)
for kind in ('item', 'skill', 'class'):
    p = 'extracted/data/_draft/%s.jsonl' % kind
    if not os.path.isfile(p):
        print('ERROR: %s missing - owning stage: run_all.ps1 datasets' % p); sys.exit(2)
'@
    & $Python -c $code | Out-Host
    return $LASTEXITCODE
}

function Invoke-Datasets {
    param([string]$Cdb, [string]$BuildId, [string]$Python, [switch]$DryRun)

    # spec-stages-datasets §3.1: regenerate drafts -> verifier GATE ->
    # promote (the only canonical write) -> re-verify the promoted plane.
    $emit = @('pipeline/tools/cdb_emit.py', $Cdb,
              '--outdir', 'extracted/data/_draft',
              '--reldir', 'extracted/relinks/_draft',
              '--buildid', $BuildId)
    $steps = @(
        ,($emit + @('--wave', 'wave1'))
        ,($emit + @('--wave', 'wave2'))
        ,@('pipeline/tools/cdb_verify.py', $Cdb,
           '--datadir', 'extracted/data/_draft',
           '--reldir', 'extracted/relinks/_draft', '--buildid', $BuildId)
        ,@('pipeline/tools/promote_drafts.py', '--plane', 'data',
           '--datadir', 'extracted/data/_draft',
           '--reldir', 'extracted/relinks/_draft',
           '--out-data', 'extracted/data', '--buildid', $BuildId)
        ,@('pipeline/tools/cdb_verify.py', $Cdb,
           '--datadir', 'extracted/data',
           '--reldir', 'extracted/relinks/_draft', '--buildid', $BuildId)
    )
    return Invoke-PipelineSteps -Stage 'datasets' -Python $Python `
        -Steps $steps -DryRun:$DryRun
}

function Invoke-Relink {
    param([string]$Cdb, [string]$BuildId, [string]$Python, [switch]$DryRun)

    if (-not $DryRun) {
        $rc = Test-RelinkPreconditions -Python $Python
        if ($rc -ne 0) { return 2 }
    }
    # spec-stages-datasets §4.1: promote seeds -> re-verify BOTH planes ->
    # derive catalog from the canonical bytes (no extraction, no invented edges).
    $steps = @(
        ,@('pipeline/tools/promote_drafts.py', '--plane', 'relinks',
           '--datadir', 'extracted/data/_draft',
           '--reldir', 'extracted/relinks/_draft',
           '--out-relinks', 'extracted/relinks', '--buildid', $BuildId)
        ,@('pipeline/tools/cdb_verify.py', $Cdb,
           '--datadir', 'extracted/data',
           '--reldir', 'extracted/relinks', '--buildid', $BuildId)
        ,@('pipeline/tools/relink_catalog.py',
           '--datadir', 'extracted/data',
           '--reldir', 'extracted/relinks',
           '--bridge', 'extracted/harvest/_lang-bridge/export_en.xml',
           '--out-md', 'extracted/RELATIONS.md',
           '--out-json', 'extracted/relinks/matrix.json')
    )
    return Invoke-PipelineSteps -Stage 'relink' -Python $Python `
        -Steps $steps -DryRun:$DryRun
}

function Invoke-Emit {
    param([string]$Cdb, [string]$BuildId, [string]$Python, [switch]$DryRun)

    if (-not $DryRun) {
        $rc = Test-EmitPreconditions -Python $Python
        if ($rc -ne 0) { return 2 }
    }
    # spec-stages-datasets §5.1: availability regen (deterministic, unchanged
    # tool) + the validation pass landing validation-report.json/-md.
    $steps = @(
        ,@('pipeline/tools/locale_bridge_dig.py')
        ,@('pipeline/tools/validate_all.py', '--cdb', $Cdb,
           '--buildid', $BuildId, '--datadir', 'extracted/data',
           '--reldir', 'extracted/relinks',
           '--report', 'extracted/validation-report.json',
           '--md', 'extracted/VALIDATION-REPORT.md')
    )
    return Invoke-PipelineSteps -Stage 'emit' -Python $Python `
        -Steps $steps -DryRun:$DryRun
}

function Invoke-StubStage {
    param([string]$Stage, [switch]$DryRun)
    if ($DryRun) {
        Write-Host ("[dry-run] {0} would FAIL LOUDLY (not built): {1}" -f $Stage, $script:StageInfo[$Stage].stub)
        return 0
    }
    Write-Host ("FAIL: " + $script:StageInfo[$Stage].stub)
    return 3
}

# ---- argument parsing -------------------------------------------------------

$list = $false
$dryRun = $false
$clientOverride = $null
$positional = @()

$tokens = @($args)
$i = 0
while ($i -lt $tokens.Count) {
    $t = $tokens[$i]
    switch -Regex ($t) {
        '^(-h|--help)$' { Write-UsageAndExit }
        '^--list$' { $list = $true; break }
        '^--dry-run$' { $dryRun = $true; break }
        '^--client$' {
            if ($i + 1 -ge $tokens.Count) { Write-Host 'ERROR: --client needs a path argument.'; exit 2 }
            $clientOverride = $tokens[$i + 1]
            $i++
            break
        }
        '^-.*' { Write-Host "ERROR: unknown flag: $t"; Write-Host ''; Write-UsageAndExit }
        default { $positional += $t }
    }
    $i++
}

if ($positional.Count -gt 1) {
    Write-Host 'ERROR: at most one positional argument (a stage name or a client path).'
    Write-Host ''
    Write-UsageAndExit
}

$script:Defaults = Read-Defaults

if ($clientOverride) { $script:Defaults['CLIENT'] = $clientOverride }

if ($list) {
    Write-Host 'Wartales extraction pipeline - stages in fixed order:'
    $n = 0
    foreach ($stage in $script:StageOrder) {
        $n++
        $info = $script:StageInfo[$stage]
        Write-Host ("  {0}. {1,-10} {2,-9} {3}" -f $n, $stage, $info.status, $info.desc)
    }
    Write-Host ''
    Write-Host "Defaults source: $LogName (DR-2026-08-18-pipeline)"
    Write-Host ("  CLIENT  = {0}" -f $script:Defaults['CLIENT'])
    Write-Host ("  BUILDID = {0}" -f $script:Defaults['BUILDID'])
    Write-Host ("  PAKS    = {0}" -f $script:Defaults['PAKS'])
    Write-Host ("  OUT     = {0}" -f $script:Defaults['OUT'])
    Write-Host ("  CDB     = {0}" -f $script:Defaults['CDB'])
    Write-Host ("  PYTHON  = {0}" -f $script:Defaults['PYTHON'])
    exit 0
}

if ($positional.Count -eq 1) {
    $sel = $positional[0]
    if ($script:StageInfo.ContainsKey($sel)) {
        $stages = @($sel)
    }
    else {
        # Not a stage name -> treat as the path to the game's files (doctrine form).
        $script:Defaults['CLIENT'] = $sel
        $stages = $script:StageOrder
    }
}
else {
    $stages = $script:StageOrder
}

# ---- dispatch ---------------------------------------------------------------

$failed = 0
foreach ($stage in $stages) {
    if ($stage -eq 'harvest') {
        $rc = Invoke-Harvest -Client $script:Defaults['CLIENT'] `
            -Out $script:Defaults['OUT'] `
            -BuildId $script:Defaults['BUILDID'] `
            -Python $script:Defaults['PYTHON'] `
            -DryRun:$dryRun
    }
    elseif ($stage -eq 'map') {
        $rc = Invoke-MapRegistry -BuildId $script:Defaults['BUILDID'] `
            -Python $script:Defaults['PYTHON'] `
            -DryRun:$dryRun
    }
    elseif ($stage -eq 'datasets') {
        $rc = Invoke-Datasets -Cdb $script:Defaults['CDB'] `
            -BuildId $script:Defaults['BUILDID'] `
            -Python $script:Defaults['PYTHON'] `
            -DryRun:$dryRun
    }
    elseif ($stage -eq 'relink') {
        $rc = Invoke-Relink -Cdb $script:Defaults['CDB'] `
            -BuildId $script:Defaults['BUILDID'] `
            -Python $script:Defaults['PYTHON'] `
            -DryRun:$dryRun
    }
    elseif ($stage -eq 'emit') {
        $rc = Invoke-Emit -Cdb $script:Defaults['CDB'] `
            -BuildId $script:Defaults['BUILDID'] `
            -Python $script:Defaults['PYTHON'] `
            -DryRun:$dryRun
    }
    else {
        $rc = Invoke-StubStage -Stage $stage -DryRun:$dryRun
    }

    if ($dryRun) { continue }

    if ($rc -eq 0) {
        Write-Host "[$stage] PASS"
    }
    else {
        Write-Host "[$stage] FAILED (exit $rc)"
        $failed = $rc
        break
    }
}

exit $failed
