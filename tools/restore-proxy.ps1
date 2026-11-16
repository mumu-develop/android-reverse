# 抓包环境一键恢复 / 清理
#
# 用途：手机重启、拔插 USB、adb 重启之后，adb reverse 会丢，
#       但系统代理设置还留着 —— 结果所有 App 报"网络错误"。
#       跑这个脚本把链路恢复（或彻底清掉）。
#
# 用法：
#   .\restore-proxy.ps1              # 恢复链路（建 reverse + 设代理）
#   .\restore-proxy.ps1 -Clear       # 清理（清代理 + 删 reverse）
#   .\restore-proxy.ps1 -Status      # 只看状态
#   .\restore-proxy.ps1 -Port 8889   # 换端口

param(
    [int]$Port = 8888,
    [switch]$Clear,
    [switch]$Status,
    [string]$Device = ""
)

$ErrorActionPreference = "Stop"

function Get-Dev {
    if ($Device) { return $Device }
    $lines = @(adb devices | Where-Object { $_ -match "^\S+\s+device$" })
    if ($lines.Count -eq 0) { throw "没有已连接的设备" }
    return ($lines[0] -split "\s+")[0]
}

function Show-Status($dev) {
    Write-Host "=== 设备 $dev ===" -ForegroundColor Cyan
    Write-Host "系统代理: " -NoNewline
    $p = adb -s $dev shell "settings get global http_proxy" 2>&1
    Write-Host $p.Trim()
    Write-Host "adb reverse: " -NoNewline
    $r = adb -s $dev reverse --list 2>&1
    if ($r) {
        Write-Host ""
        $r | ForEach-Object { Write-Host "  $_" }
    } else {
        Write-Host "（空）" -ForegroundColor Yellow
    }

    $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($c) {
        $ownerPid = ($c.OwningProcess | Select-Object -First 1)
        $name = "pid $ownerPid"
        try {
            $proc = Get-Process -Id $ownerPid -ErrorAction Stop
            if ($proc.ProcessName) { $name = $proc.ProcessName }
        } catch { }
        Write-Host "PC 端口 ${Port}: 监听中 (${name})"
    } else {
        Write-Host "PC 端口 ${Port}: 无监听" -ForegroundColor Yellow
    }
}

$dev = Get-Dev

if ($Status) {
    Show-Status $dev
    exit 0
}

if ($Clear) {
    Write-Host "清理抓包配置..." -ForegroundColor Yellow
    adb -s $dev shell "settings put global http_proxy :0" | Out-Null
    adb -s $dev reverse --remove "tcp:${Port}" 2>&1 | Out-Null
    Write-Host "已清除系统代理与 reverse" -ForegroundColor Green
    Show-Status $dev
    exit 0
}

Write-Host "恢复抓包链路（端口 ${Port}）..." -ForegroundColor Cyan

$listen = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $listen) {
    Write-Host "  [!] PC 上 ${Port} 没有进程监听，先启动 Charles" -ForegroundColor Yellow
}

adb -s $dev reverse "tcp:${Port}" "tcp:${Port}" | Out-Null
Write-Host "  [OK] adb reverse 已建立" -ForegroundColor Green

adb -s $dev shell "settings put global http_proxy 127.0.0.1:${Port}" | Out-Null
Write-Host "  [OK] 系统代理已设为 127.0.0.1:${Port}" -ForegroundColor Green

Start-Sleep -Milliseconds 500
Show-Status $dev

Write-Host ""
Write-Host "验证：手机浏览器打开 http://neverssl.com，Charles 应立刻出现记录" -ForegroundColor Cyan
Write-Host "清理：.\restore-proxy.ps1 -Clear" -ForegroundColor DarkGray
