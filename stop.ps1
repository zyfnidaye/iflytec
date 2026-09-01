# 停止前后端（按端口关闭占用进程，含子进程 / --reload worker）
# 用法： .\stop.ps1

$ports = @(8123, 5173)

# 收集某个 PID 关联的子进程：普通子进程(ParentProcessId) +
# uvicorn --reload 用 multiprocessing spawn 出来的 worker(命令行含 parent_pid=<pid>)。
function Get-Descendants($parentId) {
    $result = @()
    $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue
    foreach ($p in $procs) {
        if ($p.ParentProcessId -eq $parentId) { $result += $p.ProcessId }
        elseif ($p.CommandLine -and $p.CommandLine -match "parent_pid=$parentId\b") { $result += $p.ProcessId }
    }
    return $result | Select-Object -Unique
}

function Stop-One($procId, $label) {
    try {
        Stop-Process -Id $procId -Force -ErrorAction Stop
        Write-Host "  已停止 $label (PID $procId)" -ForegroundColor Green
    } catch {
        Write-Host "  无法停止 PID $procId : $_" -ForegroundColor Yellow
    }
}

foreach ($port in $ports) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) {
        Write-Host "端口 $port 未被占用" -ForegroundColor DarkGray
        continue
    }
    foreach ($ownerId in ($conns.OwningProcess | Select-Object -Unique)) {
        Write-Host "端口 $port ->" -ForegroundColor Cyan
        # 先杀子进程 / reload worker，再杀端口持有者本身
        foreach ($childId in (Get-Descendants $ownerId)) { Stop-One $childId "子进程" }
        Stop-One $ownerId "端口持有者"
    }
}

# 兜底：清理仍残留的、真正占着端口的进程（Windows 有时把已退出的父 PID 报成持有者）
Start-Sleep -Milliseconds 800
foreach ($port in $ports) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conns) {
        foreach ($ownerId in ($conns.OwningProcess | Select-Object -Unique)) {
            $alive = Get-Process -Id $ownerId -ErrorAction SilentlyContinue
            if ($alive) { Stop-One $ownerId "端口 $port 残留" }
            else { Write-Host "端口 $port 仍显示已退出的 PID $ownerId（socket 内核回收中，稍候自动释放）" -ForegroundColor DarkGray }
        }
    }
}
