param(
    [switch]$NoBrowser,
    [ValidateRange(1, 65535)]
    [int]$FrontendPort = 5173
)

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendPath = Join-Path $projectRoot 'backend'
$frontendPath = Join-Path $projectRoot 'frontend'

if (-not (Test-Path (Join-Path $backendPath '.env'))) {
    Write-Warning '未发现 backend/.env。请先复制 backend/.env.example 为 backend/.env，并填写 AUTH_SECRET、DATA_ENCRYPTION_KEY 和初始管理员信息；模型配置在 backend/data/config.json。'
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw '未找到 python；请安装 Python 3.11+ 并确保已加入 PATH。'
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw '未找到 npm；请安装 Node.js LTS 并确保已加入 PATH。'
}

Write-Host '正在分别启动后端和前端开发服务器…' -ForegroundColor Cyan
$backendRunning = [bool](Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)
$frontendRunning = [bool](Get-NetTCPConnection -LocalPort $FrontendPort -State Listen -ErrorAction SilentlyContinue)

if ($backendRunning) {
    Write-Host '后端已在 8000 端口运行，跳过重复启动。' -ForegroundColor Yellow
} else {
    Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -ArgumentList @(
        '-NoProfile', '-Command', "Set-Location -LiteralPath '$backendPath'; python -m uvicorn app.main:app --reload --port 8000"
    ) | Out-Null
}

if ($frontendRunning) {
    Write-Host "前端已在 $FrontendPort 端口运行，跳过重复启动。" -ForegroundColor Yellow
} else {
    Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -ArgumentList @(
        '-NoProfile', '-Command', "Set-Location -LiteralPath '$frontendPath'; npm run dev -- --port $FrontendPort"
    ) | Out-Null
}

Write-Host "后端：http://127.0.0.1:8000  前端：http://127.0.0.1:$FrontendPort" -ForegroundColor Green
if (-not $NoBrowser) {
    Start-Process "http://127.0.0.1:$FrontendPort"
}
