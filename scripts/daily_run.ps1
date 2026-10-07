# Daily factory-optimization run: data extraction -> transcription -> insights -> dashboard
# Scheduled via Task Scheduler (12:00 daily). Logs to logs/daily_run.log
param(
    [switch]$SkipOpencode   # deterministic steps only (no AI transcription/analysis)
)

$ErrorActionPreference = 'Continue'
$Repo = 'D:\pritam\wa-ingest'
Set-Location $Repo
$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
Write-Output "===== daily run start $stamp ====="

# Runs a command with a hard timeout (seconds); returns $true if completed
function Invoke-Step {
    param([string]$Name, [scriptblock]$Cmd, [int]$TimeoutSec = 240, $StepArgs = @())
    $job = Start-Job -ScriptBlock $Cmd -ArgumentList $StepArgs
    if (Wait-Job $job -Timeout $TimeoutSec) { $out = Receive-Job $job; $out | ForEach-Object { Write-Output $_ } }
    else { Stop-Job $job; Write-Output "[$Name] TIMEOUT after ${TimeoutSec}s — skipped" }
    Remove-Job $job -Force
}

# 1. Refresh analytics store from raw lake (adds latest messages; never mutates raw lake)
Invoke-Step -Name 'analyze' -TimeoutSec 300 -Cmd { param($repo) Set-Location $repo; python -m app.analyze --load-sqlite 2>&1 } -StepArgs $Repo

# 2. Backfill any missed history since yesterday (uses provider quota; time-bounded)
$since = (Get-Date).AddDays(-2).ToString('yyyy-MM-dd')
Invoke-Step -Name 'backfill' -TimeoutSec 180 -Cmd { param($repo, $d) Set-Location $repo; python scripts\backfill_history.py --since $d 2>&1 } -StepArgs @($Repo, $since)
Write-Output "backfill window since $since"

# 3. Re-run extraction into structured stores
Invoke-Step -Name 'prodreport' -TimeoutSec 120 -Cmd { param($repo) Set-Location $repo; python -m app.prodreport 2>&1 } -StepArgs $Repo

# 4. opencode: incremental transcription (grey + white sheets) + insights analysis
if (-not $SkipOpencode) {
    $prompt = Get-Content scripts\daily_insight_prompt.md -Raw
    Invoke-Step -Name 'opencode' -TimeoutSec 3600 -Cmd { param($repo, $p) Set-Location $repo; opencode run $p 2>&1 } -StepArgs @($Repo, $prompt)
}

# 4b. Transcribe new voice notes (local Whisper large-v3)
Invoke-Step -Name 'stt' -TimeoutSec 3600 -Cmd { param($repo) Set-Location $repo; $env:PYTHONIOENCODING = 'utf-8'; python -m app.stt 2>&1 } -Args $Repo

# 4c. VLM catch-up: any remaining pending contact sheets (backlog/failed retries), 3 workers
Invoke-Step -Name 'vlm_catchup' -TimeoutSec 3600 -Cmd { param($repo) Set-Location $repo; python scripts\vlm_extract.py --loop --workers 3 2>&1 } -Args $Repo

# 5. Regenerate structured CSVs (picks up any transcriptions opencode added)
Invoke-Step -Name 'emit_structured' -TimeoutSec 120 -Cmd { param($repo) Set-Location $repo; python scripts\emit_structured.py 2>&1 } -StepArgs $Repo

# 5b. PC sub-system: import sources, scan group events, export xlsx + PC page
Invoke-Step -Name 'pcsystem' -TimeoutSec 180 -Cmd { param($repo) Set-Location $repo; python scripts\pcsystem.py all 2>&1; python scripts\build_pc_dashboard.py 2>&1 } -StepArgs $Repo

# 6. Rebuild dashboard
Invoke-Step -Name 'dashboard' -TimeoutSec 120 -Cmd { param($repo) Set-Location $repo; python scripts\build_dashboard.py 2>&1 } -StepArgs $Repo

Write-Output "===== daily run end $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ====="


