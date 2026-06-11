# run_fetch.ps1 — 由 Windows 计划任务调用的启动脚本
# 功能：激活 Python 环境，运行本地抓取推送脚本
# 日志同时写入 logs\local_fetch.log（由 Python 脚本负责）

$RepoRoot = Split-Path -Parent $PSScriptRoot

# 切换到仓库根目录
Set-Location $RepoRoot

# 找到 Python 可执行文件（优先用 py 启动器，其次 python）
$PythonExe = $null
foreach ($candidate in @("py", "python", "python3")) {
    try {
        $ver = & $candidate --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            $PythonExe = $candidate
            break
        }
    } catch {}
}

if (-not $PythonExe) {
    $msg = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [ERROR] 找不到 Python，请确认已安装 Python 3.x"
    $msg | Out-File -Append -Encoding UTF8 "$RepoRoot\logs\local_fetch.log"
    exit 1
}

# 运行主脚本
& $PythonExe "$RepoRoot\scripts\run_local_fetch.py"
exit $LASTEXITCODE
