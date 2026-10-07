# Light refresh: data extraction + dashboard rebuild (no AI analysis).
# Runs every 2 hours; the full AI analysis stays on the 12:00 daily job.
$ErrorActionPreference = 'Continue'
$Repo = 'D:\pritam\wa-ingest'
Set-Location $Repo

function Invoke-Step {
    param([string]$Name, [scriptblock]$Cmd, [int]$TimeoutSec = 240, $StepArgs = @())
    $job = Start-Job -ScriptBlock $Cmd -ArgumentList $StepArgs
    if (Wait-Job $job -Timeout $TimeoutSec) { Receive-Job $job | ForEach-Object { Write-Output $_ } }
    else { Stop-Job $job; Write-Output "[$Name] TIMEOUT after ${TimeoutSec}s — skipped" }
    Remove-Job $job -Force
}

Write-Output "===== light refresh start $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ====="
# 0. self-heal: ensure the dashboard server is listening on 8765
$srv = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
if (-not $srv) {
    Start-Process -WindowStyle Hidden python -ArgumentList 'scripts\pcserver.py' -WorkingDirectory $Repo
    Write-Output "dashboard server was down — restarted"
}
Invoke-Step -Name 'nas_scan' -TimeoutSec 1500 -Cmd { param($repo) Set-Location $repo; python scripts\nas_orders.py scan 2>&1 } -Args $Repo
# VLM extraction of contact sheets stored in the last day (fast pass, 3 workers)
$since = (Get-Date).AddDays(-1).ToString('yyyy-MM-dd')
Invoke-Step -Name 'vlm_new_sheets' -TimeoutSec 3000 -Cmd { param($repo, $d) Set-Location $repo; python scripts\vlm_extract.py --newer-than $d --workers 3 2>&1 } -Args @($Repo, $since)
Invoke-Step -Name 'analyze' -TimeoutSec 300 -Cmd { param($repo) Set-Location $repo; python -m app.analyze --load-sqlite 2>&1 } -Args $Repo
Invoke-Step -Name 'prodreport' -TimeoutSec 120 -Cmd { param($repo) Set-Location $repo; python -m app.prodreport 2>&1 } -Args $Repo
Invoke-Step -Name 'emit' -TimeoutSec 120 -Cmd { param($repo) Set-Location $repo; python scripts\emit_structured.py 2>&1 } -Args $Repo
Invoke-Step -Name 'pcsystem' -TimeoutSec 180 -Cmd { param($repo) Set-Location $repo; python scripts\pcsystem.py all 2>&1; python scripts\build_pc_dashboard.py 2>&1 } -Args $Repo
Invoke-Step -Name 'dashboard' -TimeoutSec 120 -Cmd { param($repo) Set-Location $repo; python scripts\build_dashboard.py 2>&1 } -Args $Repo
Write-Output "===== light refresh end $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ====="
