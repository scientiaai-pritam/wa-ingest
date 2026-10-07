# Night backfill: process pending NAS contact sheets (3 chunks of ~100 per night, until 06:00).
# Registered 23:00 daily. Logs: logs/backfill_night.log
$ErrorActionPreference = 'Continue'
$Repo = 'D:\pritam\wa-ingest'
Set-Location $Repo
$deadline = (Get-Date).Date.AddHours(30)   # 06:00 next morning

while ((Get-Date) -lt $deadline) {
    # remaining pending (jpg only, oldest first)
    python scripts\nas_orders.py pending *> $null
    $pend = Get-Content data\structured\print_orders_pending.json -Raw | ConvertFrom-Json
    if (-not $pend -or @($pend).Count -eq 0) { Write-Output "backfill complete - no pending sheets"; break }

    # slice next chunk of 100
    $chunk = @($pend | Select-Object -First 100)
    $chunkPath = 'data\structured\backfill\night_chunk.json'
    $chunk | ConvertTo-Json -Depth 5 | Set-Content $chunkPath -Encoding UTF8
    Write-Output "----- night chunk $(Get-Date -Format 'HH:mm:ss') entries=$($chunk.Count) remaining=$(@($pend).Count)"

    opencode run "Process the contact-sheet backfill chunk per scripts/backfill_night_prompt.md. Chunk file: D:\pritam\wa-ingest\$($chunkPath -replace '\\','/')"
    Write-Output "chunk done $(Get-Date -Format 'HH:mm:ss') (exit $LASTEXITCODE)"
}
Write-Output "===== night backfill end $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ====="
