# 一键启动前后端（Windows PowerShell）
# 用法：在项目根目录右键 "使用 PowerShell 运行"，或终端执行  .\start.ps1
#   .\start.ps1            正常启动
#   .\start.ps1 -Reload    后端开启热重载（开发用）

param(
    [switch]$Reload
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"

# --- 环境检查 ---
$venvPython = Join-Path $backend ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "[错误] 未找到后端虚拟环境：$venvPython" -ForegroundColor Red
    Write-Host "       请先在 backend 目录创建 venv 并安装依赖，见 README。" -ForegroundColor Yellow
    exit 1
}
if (-not (Test-Path (Join-Path $backend ".env"))) {
    Write-Host "[警告] backend\.env 不存在，后端可能因缺少 API Key 无法对话。" -ForegroundColor Yellow
}

# node 不在 PATH 时兜底加入（按需改成你的 node 目录）
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    $nodeDir = "D:\Dev\Nodejs"
    if (Test-Path (Join-Path $nodeDir "node.exe")) {
        $env:Path = "$nodeDir;$env:Path"
    } else {
        Write-Host "[错误] PATH 中找不到 node，且默认目录 $nodeDir 也没有。请先安装 Node.js。" -ForegroundColor Red
        exit 1
    }
}
if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    Write-Host "[警告] frontend\node_modules 不存在，前端窗口会先自动执行 npm install。" -ForegroundColor Yellow
}

# --- 启动后端（新窗口）---
# --reload-dir app 只监视源码目录，避免 .venv 里装包/缓存触发误重启
$reloadFlag = if ($Reload) { "--reload --reload-dir app" } else { "" }
$backendCmd = "Set-Location '$backend'; Write-Host '=== 后端 http://localhost:8123 ===' -ForegroundColor Cyan; & '$venvPython' -m uvicorn app.main:app --port 8123 $reloadFlag"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCmd

# --- 启动前端（新窗口）---
$frontendCmd = "Set-Location '$frontend'; Write-Host '=== 前端 http://localhost:5173 ===' -ForegroundColor Green; if (-not (Test-Path node_modules)) { npm install }; npm run dev"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCmd

Write-Host ""
Write-Host "已在两个新窗口分别启动：" -ForegroundColor Green
Write-Host "  后端    ->  http://localhost:8123  (health: /api/health)" -ForegroundColor Cyan
Write-Host "  前端    ->  http://localhost:5173" -ForegroundColor Cyan
if ($Reload) { Write-Host "  后端已开启 --reload 热重载" -ForegroundColor DarkGray }
Write-Host ""
Write-Host "关闭对应窗口即可停止服务。" -ForegroundColor DarkGray
