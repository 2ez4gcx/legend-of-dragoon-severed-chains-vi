<#
build_sc_android.ps1 — biên dịch lớp đè chỉ dùng cho Android (android/sc-android/src) thành out/android/sc-android.jar,
rồi sinh bộ đệm shader GLSL ES dịch sẵn out/android/shaders_es (chạy ShaderCacheTool trên máy tính, cần natives Windows
của lwjgl-shaderc/spvc có sẵn trong game/libs).

Cách gọi:  powershell -ExecutionPolicy Bypass -File android/build_sc_android.ps1 [-Game game]
Kiểm trước khi sửa: mã nguồn gốc của SdlWindow/ShaderManager (Severed-Chains đúng commit) biên dịch ra trùng lớp trong jar
(-CheckOriginal).
#>
param([string]$Game = 'game', [switch]$CheckOriginal)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not [System.IO.Path]::IsPathRooted($Game)) { $Game = Join-Path $root $Game }
$jar = Get-ChildItem $Game -Filter 'lod-game-*.jar' | Where-Object { $_.Name -notlike '*-sources.jar' } | Select-Object -First 1
if ($jar.Name -notlike '*affcef0cba71819515fdf05521c1fedb1d7a92f0*') { throw "can ban build SC affcef0, co $($jar.Name)" }
$cp = "$($jar.FullName);$Game\libs\*"
$jdk = Join-Path $Game 'jdk25\bin'
$out = Join-Path $root 'out\android'
$cls = Join-Path $out 'classes'
Remove-Item $cls -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $cls | Out-Null

if ($CheckOriginal) {
  $orig = Join-Path $out 'orig'
  Remove-Item $orig -Recurse -Force -ErrorAction SilentlyContinue
  New-Item -ItemType Directory -Force $orig | Out-Null
  $sc = Join-Path $root 'Severed-Chains\src\main\java'
  & "$jdk\javac.exe" -encoding UTF-8 --release 25 -nowarn -cp $cp -d $orig "$sc\legend\core\platform\SdlWindow.java" "$sc\legend\core\renderer\ShaderManager.java"
  if ($LASTEXITCODE) { throw 'javac goc loi' }
  $x = Join-Path $out 'jarx'
  Remove-Item $x -Recurse -Force -ErrorAction SilentlyContinue
  New-Item -ItemType Directory -Force $x | Out-Null
  Push-Location $x
  & "$jdk\jar.exe" xf $jar.FullName legend/core/platform/SdlWindow.class legend/core/renderer/ShaderManager.class
  Pop-Location
  foreach ($c in 'legend\core\platform\SdlWindow', 'legend\core\renderer\ShaderManager') {
    $a = & "$jdk\javap.exe" -p -c (Join-Path $orig "$c.class") | Out-String
    $b = & "$jdk\javap.exe" -p -c (Join-Path $x "$c.class") | Out-String
    if ($a -ne $b) { throw "$c goc KHAC lop trong jar" }
    Write-Output "khop: $c"
  }
}

$src = Get-ChildItem (Join-Path $PSScriptRoot 'sc-android\src') -Recurse -Filter *.java | ForEach-Object { $_.FullName }
& "$jdk\javac.exe" -encoding UTF-8 --release 25 -nowarn -cp $cp -d $cls $src
if ($LASTEXITCODE) { throw 'javac sc-android loi' }
$scjar = Join-Path $out 'sc-android.jar'
Remove-Item $scjar -ErrorAction SilentlyContinue
& "$jdk\jar.exe" --create --file $scjar -C $cls .
if ($LASTEXITCODE) { throw 'jar loi' }
Write-Output "DAT: $scjar"

# Bộ đệm shader: chạy trong thư mục game (gfx/shaders), ghi ra out/android/shaders_es
$es = Join-Path $out 'shaders_es'
Remove-Item $es -Recurse -Force -ErrorAction SilentlyContinue
Push-Location $Game
& "$jdk\java.exe" --enable-native-access=ALL-UNNAMED -cp "$scjar;$cp" legend.core.renderer.ShaderCacheTool $es
$rc = $LASTEXITCODE
Pop-Location
if ($rc) { throw 'ShaderCacheTool loi' }
Write-Output "DAT: $es"
