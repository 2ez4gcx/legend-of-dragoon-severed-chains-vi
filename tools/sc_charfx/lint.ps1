<#
lint.ps1 — dịch mọi bộ shader charfx qua đúng đường của bản Android (shaderc -> SPIR-V -> SPIRV-Cross GLSL ES 3.20) mà không
chạy game, rồi gọi check_iface.py so giao diện giữa các tầng.

Cách gọi:
  powershell -ExecutionPolicy Bypass -File tools/sc_charfx/lint.ps1 [-Game game] [-NoIface]
Trước đó: python tools/sc_charfx/make_variants.py (ghi out\charfx_variants\<bộ>\ + manifest.json)
          out\android\sc-android.jar phải có (dựng theo NGHIEN_CUU_ANDROID.md; chỉ dùng lớp ShaderCacheTool/ShaderManager).
Mỗi bộ (thêm "stock" = 13 shader gốc): out\charfx_lint\<bộ>\gfx\shaders = 13 shader gốc + 5 file của bộ, chạy
  java -cp sc-android.jar;lod-game-<commit>.jar;libs\* legend.core.renderer.ShaderCacheTool es_out
trong thư mục đó -> es_out\<khoá>.glsl (khoá = SHA-256 của "STAGE\0" + nguồn, như ShaderManager.cacheKey) và lint.txt
(dòng "<file> <STAGE> uniforms=N -> <khoá>.glsl"). Game trong <Game> chỉ được đọc (shader gốc, jar, libs, jdk25).
Exit 0 = mọi bộ dịch đủ 13 shader và check_iface.py đạt; 1 = lỗi (in 30 dòng cuối log của bộ lỗi).
#>
param(
  [string]$Game = 'game',
  [switch]$NoIface
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not [System.IO.Path]::IsPathRooted($Game)) { $Game = Join-Path $root $Game }
$stock = Join-Path $Game 'gfx\shaders'
$java = Join-Path $Game 'jdk25\bin\java.exe'
$android = Join-Path $root 'out\android\sc-android.jar'
$variants = Join-Path $root 'out\charfx_variants'
$lint = Join-Path $root 'out\charfx_lint'
foreach ($p in @($stock, $java, $android, $variants)) {
  if (-not (Test-Path -LiteralPath $p)) { Write-Output "LOI: thieu $p"; exit 1 }
}
$jar = Get-ChildItem -LiteralPath $Game -Filter 'lod-game-*.jar' | Where-Object { $_.Name -notmatch '-sources' } | Select-Object -First 1
if (-not $jar) { Write-Output "LOI: khong thay lod-game-*.jar trong $Game"; exit 1 }
$cp = "$android;$($jar.FullName);$Game\libs\*"
$natives = Join-Path $lint 'natives'
New-Item -ItemType Directory -Force $natives | Out-Null
# ket qua cu cua bo da xoa khong duoc nam lai (check_iface.py doc moi thu muc co lint.txt)
Get-ChildItem -LiteralPath $lint -Directory | Where-Object { $_.Name -ne 'natives' } | ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }

$names = @('stock') + @(Get-ChildItem -LiteralPath $variants -Directory | ForEach-Object { $_.Name } | Sort-Object)
$bad = 0
foreach ($v in $names) {
  $L = Join-Path $lint $v
  if (Test-Path -LiteralPath $L) { Remove-Item -LiteralPath $L -Recurse -Force }
  $sh = Join-Path $L 'gfx\shaders'
  New-Item -ItemType Directory -Force $sh | Out-Null
  Copy-Item (Join-Path $stock '*') $sh -Force
  if ($v -ne 'stock') { Copy-Item (Join-Path $variants "$v\*") $sh -Force }
  $n = @(Get-ChildItem -LiteralPath $sh -File).Count
  if ($n -ne 13) { Write-Output "LOI: $v co $n shader (can 13: bo thua/thieu file?)"; $bad++; continue }
  $log = Join-Path $L 'lint.txt'
  $err = Join-Path $L 'lint_err.txt'
  # Start-Process (PS 5.1) noi cac doi so bang dau cach ma khong tu them ngoac kep
  $jargs = @('--enable-native-access=ALL-UNNAMED', "-Dorg.lwjgl.system.SharedLibraryExtractPath=$natives", '-cp', $cp,
    'legend.core.renderer.ShaderCacheTool', 'es_out') | ForEach-Object { if ($_ -match ' ') { '"' + $_ + '"' } else { $_ } }
  $proc = Start-Process -FilePath $java -ArgumentList $jargs -WorkingDirectory $L -NoNewWindow -Wait -PassThru `
    -RedirectStandardOutput $log -RedirectStandardError $err
  $rc = $proc.ExitCode
  $es = @(Get-ChildItem -LiteralPath (Join-Path $L 'es_out') -Filter *.glsl -ErrorAction SilentlyContinue).Count
  Write-Output ('{0,-8} exit {1}  dich {2}/13' -f $v, $rc, $es)
  if ($rc -ne 0 -or $es -ne 13) {
    $bad++
    Get-Content -LiteralPath $log, $err -ErrorAction SilentlyContinue | Select-Object -Last 30 | ForEach-Object { Write-Output "    $_" }
  }
}
if ($bad) { Write-Output "LOI: $bad bo khong dich duoc"; exit 1 }
if ($NoIface) { Write-Output 'DAT (chua chay check_iface.py)'; exit 0 }
& python (Join-Path $PSScriptRoot 'check_iface.py')
if ($LASTEXITCODE -ne 0) { exit 1 }
exit 0
