$root = Split-Path -Parent $PSCommandPath
$logDirectory = Join-Path $root "runtime\logs"
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null

foreach ($port in 8000, 5173) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique |
        ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
}

Start-Process python -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000") `
    -WindowStyle Hidden -WorkingDirectory (Join-Path $root "backend") `
    -RedirectStandardOutput (Join-Path $logDirectory "api.log") `
    -RedirectStandardError (Join-Path $logDirectory "api.err.log")
Start-Process npm.cmd -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1") `
    -WindowStyle Hidden -WorkingDirectory (Join-Path $root "frontend") `
    -RedirectStandardOutput (Join-Path $logDirectory "vite.log") `
    -RedirectStandardError (Join-Path $logDirectory "vite.err.log")

Start-Sleep -Seconds 4
Write-Output "Frontend: http://127.0.0.1:5173"
Write-Output "Backend:  http://127.0.0.1:8000"
$frontend = Invoke-WebRequest -Uri 'http://127.0.0.1:5173' -UseBasicParsing -TimeoutSec 5
Write-Output "Frontend check: HTTP $($frontend.StatusCode)"
