Write-Host "Video Downloader Plus - system check" -ForegroundColor Cyan
Write-Host ""

try {
    $py = py --version 2>&1
    Write-Host "Python launcher: $py" -ForegroundColor Green
} catch {
    Write-Host "Python launcher (py) not found." -ForegroundColor Red
}

try {
    $node = node --version 2>&1
    Write-Host "Node: $node" -ForegroundColor Green
    $major = [int](($node -replace '^v','').Split('.')[0])
    if ($major -lt 22) {
        Write-Host "  Node 22+ is recommended for yt-dlp EJS. Install Deno instead or upgrade Node." -ForegroundColor Yellow
    }
} catch {
    Write-Host "Node not found. This is fine if Deno is installed." -ForegroundColor Yellow
}

try {
    $deno = deno --version 2>&1 | Select-Object -First 1
    Write-Host "Deno: $deno" -ForegroundColor Green
} catch {
    Write-Host "Deno not found. Deno 2.3+ is the recommended JS runtime for current yt-dlp YouTube support." -ForegroundColor Yellow
}

if (Test-Path ".venv\Scripts\python.exe") {
    Write-Host "Virtual environment: present" -ForegroundColor Green
} else {
    Write-Host "Virtual environment: not created yet" -ForegroundColor Yellow
}
