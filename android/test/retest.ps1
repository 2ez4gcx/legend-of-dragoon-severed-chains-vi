<#
retest.ps1 — dựng lại bản x86_64 (launcher + APK), cài lên giả lập đang chạy, mở app và in log của SC.

Cách gọi:  powershell -ExecutionPolicy Bypass -File android/test/retest.ps1 [-Natives launcher] [-Wait 45] [-Shot work/shots/and.png] [-NoBuild]
#>
param([string]$Natives = 'launcher', [int]$Wait = 45, [string]$Shot = 'work/shots/and_test.png', [switch]$NoBuild, [int]$Tail = 50)
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$adb = Join-Path $env:LOCALAPPDATA 'Android\Sdk\platform-tools\adb.exe'
if (-not $NoBuild) {
  if ($Natives) {
    powershell -ExecutionPolicy Bypass -File (Join-Path $root 'android\build_natives.ps1') -Abi x86_64 -Only $Natives *> (Join-Path $root 'deps\android\log_retest.txt')
    if ($LASTEXITCODE) { Write-Output 'LOI build_natives'; Get-Content (Join-Path $root 'deps\android\log_retest.txt') -Tail 15; exit 1 }
  }
  $env:PYTHONIOENCODING = 'utf-8'
  python (Join-Path $root 'android\make_apk.py') --version 0.2 --abi x86_64 2>&1 | Select-Object -Last 1
  cmd /c "`"$adb`" install -r `"$root\out\android\LoD-SC-VN-v0.2-android-x86_64.apk`" 2>&1" | Select-Object -Last 1
}
cmd /c "`"$adb`" shell am force-stop vn.lodsc & `"$adb`" logcat -c"
cmd /c "`"$adb`" shell am start -n vn.lodsc/.SetupActivity" | Out-Null
Start-Sleep -Seconds $Wait
cmd /c "`"$adb`" exec-out screencap -p > `"$(Join-Path $root $Shot)`""
cmd /c "`"$adb`" logcat -d -s SC:* AndroidRuntime:E DEBUG:F libc:F" | Where-Object { $_ -notmatch 's_glBindAttribLocation|JVM opt' } | Select-Object -Last $Tail
