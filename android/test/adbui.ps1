<#
adbui.ps1 — điều khiển giao diện Android qua adb + uiautomator (thử APK trên giả lập/máy thật).

Cách gọi:
  powershell -File android/test/adbui.ps1 -Dump                     # in các phần tử có chữ/mô tả + toạ độ
  powershell -File android/test/adbui.ps1 -Tap "Downloads"          # bấm phần tử có text/content-desc chứa chuỗi
  powershell -File android/test/adbui.ps1 -LongTap "LoD_disc1.bin"
  powershell -File android/test/adbui.ps1 -Shot work/shots/x.png    # chụp màn hình
#>
param([switch]$Dump, [string]$Tap = '', [string]$LongTap = '', [string]$Shot = '')
$ErrorActionPreference = 'Stop'
$adb = Join-Path $env:LOCALAPPDATA 'Android\Sdk\platform-tools\adb.exe'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

function Nodes {
  $tmp = Join-Path $env:TEMP 'adbui.xml'
  # adb in tiến độ ra stderr -> gọi qua cmd để PowerShell không coi là lỗi
  cmd /c "`"$adb`" shell uiautomator dump /sdcard/ui.xml >nul 2>&1 && `"$adb`" pull /sdcard/ui.xml `"$tmp`" >nul 2>&1"
  $x = [xml](Get-Content $tmp -Encoding utf8)
  return $x.SelectNodes('//node')
}

function Center([string]$bounds) {
  $m = [regex]::Match($bounds, '\[(\d+),(\d+)\]\[(\d+),(\d+)\]')
  return @((([int]$m.Groups[1].Value + [int]$m.Groups[3].Value) / 2), (([int]$m.Groups[2].Value + [int]$m.Groups[4].Value) / 2))
}

function Find([string]$s) {
  foreach ($n in Nodes) {
    if (($n.text -and $n.text -like "*$s*") -or ($n.'content-desc' -and $n.'content-desc' -like "*$s*")) { return $n }
  }
  throw "khong thay '$s'"
}

if ($Dump) {
  Nodes | Where-Object { $_.text -or $_.'content-desc' } | ForEach-Object { '{0} | {1} | {2}' -f $_.text, $_.'content-desc', $_.bounds }
}
if ($Tap) {
  $c = Center (Find $Tap).bounds
  & $adb shell input tap $c[0] $c[1]
  Write-Output "tap '$Tap' $($c[0]),$($c[1])"
}
if ($LongTap) {
  $c = Center (Find $LongTap).bounds
  & $adb shell input swipe $c[0] $c[1] $c[0] $c[1] 900
  Write-Output "longtap '$LongTap' $($c[0]),$($c[1])"
}
if ($Shot) {
  $p = if ([System.IO.Path]::IsPathRooted($Shot)) { $Shot } else { Join-Path $root $Shot }
  cmd /c "`"$adb`" exec-out screencap -p > `"$p`""
  Write-Output "chup $p"
}
