# proxy-via-adb.ps1 -- 用 adb reverse 把手机代理指到 PC 上的 Charles
#
# 适用：PC 与手机不同网段 / Windows 防火墙拦截入站 / 无管理员权限
#
# 用法：
#   .\proxy-via-adb.ps1                 建立隧道 + 设置代理
#   .\proxy-via-adb.ps1 -Port 8888      指定端口
#   .\proxy-via-adb.ps1 -Clear          撤销

param(
    [int]$Port = 8888,
    [string]$Serial = "",
    [switch]$Clear
)

$ErrorActionPreference = "Stop"

function Invoke-Adb([string[]]$AdbArgs) {
    $cmd = @("adb")
    if ($Serial) { $cmd += @("-s", $Serial) }
    $cmd += $AdbArgs
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $raw = & $cmd[0] $cmd[1..($cmd.Length - 1)] 2>&1
    $ErrorActionPreference = $prev
    return ($raw | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] }) -join "`n"
}

if (-not (Get-Command adb -ErrorAction SilentlyContinue)) {
    Write-Host "[X] 找不到 adb" -ForegroundColor Red
    exit 1
}

$devices = (adb devices) -split "`n" | Select-String "\sdevice$"
if (-not $devices) {
    Write-Host "[X] 没有已连接的设备" -ForegroundColor Red
    exit 1
}

if ($Clear) {
    Write-Host "== 撤销 ==" -ForegroundColor Yellow
    Invoke-Adb @("reverse", "--remove", "tcp:$Port") 2>$null | Out-Null
    Invoke-Adb @("shell", "su -c 'settings put global http_proxy :0'") | Out-Null
    Write-Host "  已移除 reverse tcp:$Port" -ForegroundColor Green
    Write-Host "  已清除系统代理" -ForegroundColor Green
    exit 0
}

Write-Host "== 建立 adb reverse 隧道 ==" -ForegroundColor Cyan
Invoke-Adb @("reverse", "--remove", "tcp:$Port") 2>$null | Out-Null
Invoke-Adb @("reverse", "tcp:$Port", "tcp:$Port") | Out-Null
$list = Invoke-Adb @("reverse", "--list")
if ($list -match "tcp:$Port") {
    Write-Host "  [OK] tcp:$Port -> PC:$Port" -ForegroundColor Green
} else {
    Write-Host "  [X] 隧道建立失败" -ForegroundColor Red
    exit 1
}

Write-Host "== 设置手机系统代理 ==" -ForegroundColor Cyan
Invoke-Adb @("shell", "su -c 'settings put global http_proxy 127.0.0.1:$Port'") | Out-Null
$proxy = (Invoke-Adb @("shell", "settings get global http_proxy")).Trim()
Write-Host "  当前代理: $proxy" -ForegroundColor Green

Write-Host "== 连通性自检 ==" -ForegroundColor Cyan
$sh = 'nc -w 5 127.0.0.1 ' + $Port + ' < /dev/null; echo rc=$?'
$tmp = Join-Path $env:TEMP "_proxy_check.sh"
[IO.File]::WriteAllText($tmp, $sh, [Text.Encoding]::ASCII)
Invoke-Adb @("push", $tmp, "/data/local/tmp/_proxy_check.sh") | Out-Null
$rc = Invoke-Adb @("shell", "sh /data/local/tmp/_proxy_check.sh")
if ($rc -match "rc=0") {
    Write-Host "  [OK] 手机能连到 127.0.0.1:$Port（Charles）" -ForegroundColor Green
} else {
    Write-Host "  [X] 连不上: $rc" -ForegroundColor Red
    Write-Host "      检查 Charles 是否在跑、端口是否一致" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "下一步：" -ForegroundColor Cyan
Write-Host "  1. Charles 确认录制按钮是开启状态"
Write-Host "  2. 清空 Charles session，然后在手机上刷一次"
Write-Host "  3. 撤销: .\proxy-via-adb.ps1 -Clear"
Write-Host ""
Write-Host "注意: USB 断开/重连、手机重启后隧道失效，需重新执行" -ForegroundColor Yellow