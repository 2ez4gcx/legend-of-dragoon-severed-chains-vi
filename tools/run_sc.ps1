<#
run_sc.ps1 — chạy Severed Chains (thư mục game) có/không có bản vá tiếng Việt sc-vi.jar.

Cách gọi:
  powershell -File tools/run_sc.ps1 [-Game game] [-NoVi] [-Install]
    -Game     thư mục game SC (tương đối theo D:\LOD-SC hoặc tuyệt đối), mặc định "game"
    -Install  chép out/lang/*.lang + dialogue.vi.tsv, tr_sc/*.lang, out/fonts/vietnamese.* và out/sc-vi.jar vào game
    -NoVi     chạy SC gốc (không thêm sc-vi.jar vào classpath)
Classpath lấy từ launch.bat của bản build (dòng gọi java), thêm sc-vi.jar lên đầu để lớp sửa đè lớp gốc.
Ghi PID vào <game>\sc.pid. Log của SC: <game>\logs\.
#>
param(
  [string]$Game = 'game',
  [switch]$NoVi,
  [switch]$Install
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not [System.IO.Path]::IsPathRooted($Game)) { $Game = Join-Path $root $Game }

if ($Install) {
  New-Item -ItemType Directory -Force (Join-Path $Game 'lang') | Out-Null
  Copy-Item (Join-Path $root 'out\lang\*') (Join-Path $Game 'lang') -Force
  Copy-Item (Join-Path $root 'tr_sc\*.lang') (Join-Path $Game 'lang') -Force
  Copy-Item (Join-Path $root 'out\fonts\vietnamese.*') (Join-Path $Game 'gfx\fonts') -Force
  Copy-Item (Join-Path $root 'out\sc-vi.jar') $Game -Force
  Write-Output "Da cai lang/font/sc-vi.jar vao $Game"
}

$bat = Get-Content (Join-Path $Game 'launch.bat') | Where-Object { $_ -match '\\jdk25\\bin\\java"' }
if (-not $bat) { throw 'khong tim thay dong java trong launch.bat' }
if ($bat -notmatch '-cp "([^"]+)"') { throw 'khong doc duoc classpath' }
$cp = $Matches[1]
if (-not $NoVi) { $cp = 'sc-vi.jar;' + $cp }

$javaArgs = @('-Djoml.fastmath', '-Djoml.sinLookup', '-Djoml.useMathFma', '-Dscvi.logMissing=true',
  '--add-opens', 'java.base/java.util=ALL-UNNAMED', '--add-exports', 'java.base/jdk.internal.misc=ALL-UNNAMED',
  '--enable-native-access=ALL-UNNAMED', '-Xmx3G', '-ea', '-cp', "`"$cp`"", 'legend.game.MainWindows')
$p = Start-Process -FilePath (Join-Path $Game 'jdk25\bin\java.exe') -ArgumentList $javaArgs -WorkingDirectory $Game -PassThru `
  -RedirectStandardOutput (Join-Path $Game 'stdout.txt') -RedirectStandardError (Join-Path $Game 'stderr.txt')
Set-Content (Join-Path $Game 'sc.pid') $p.Id
Write-Output "SC PID $($p.Id) (vi=$(-not $NoVi))"
