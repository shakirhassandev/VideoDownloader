$ErrorActionPreference = "Stop"
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Run start-windows.ps1 first to create the virtual environment." -ForegroundColor Yellow
    exit 1
}
& .\.venv\Scripts\python.exe -m pip install -U --pre "yt-dlp[default]"
Write-Host "yt-dlp and yt-dlp-ejs updated." -ForegroundColor Green
