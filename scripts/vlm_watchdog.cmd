@echo off
cd /d D:\pritam\wa-ingest
REM 12-hourly extraction run: only if VLM is up and no extractor already running
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://localhost:8080/v1/models' -UseBasicParsing -TimeoutSec 10; if ($r.StatusCode -ne 200) { exit 1 } } catch { exit 1 }"
if %ERRORLEVEL%==1 (
  echo [%date% %time%] VLM on 8080 is DOWN - skipping batch, opencode daily run will extract newest itself >> data\logs\vlm_extract.log
  goto :done
)
powershell -NoProfile -Command "if (Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'vlm_extract' }) { exit 1 }"
if %ERRORLEVEL%==1 goto :done
echo [%date% %time%] 12h extraction batch starting >> data\logs\vlm_extract.log
start /b "" C:\ProgramData\miniconda3\python.exe scripts\vlm_extract.py --workers 3 >> data\logs\vlm_extract.log 2>&1
:done
