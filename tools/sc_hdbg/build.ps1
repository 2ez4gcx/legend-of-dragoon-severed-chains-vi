<#
build.ps1 — dựng out/sc-hdbg.jar (listener thử ảnh nền HD, tools/sc_hdbg/src) — chỉ để thử trên PC, không phát hành.

Cách gọi:  powershell -ExecutionPolicy Bypass -File tools/sc_hdbg/build.ps1 [-Game game]
Dùng công cụ jar của JDK (ghi mục thư mục legend/...): EventManager chỉ quét jar có mục "legend/" (ClasspathHelper.forPackage),
jar ghép bằng zipfile của Python (không có mục thư mục) bị bỏ qua mà không báo lỗi.
Chạy game có listener: powershell -File tools/run_sc.ps1 -HdBg work\upscale\hd
#>
param([string]$Game = 'game')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not [System.IO.Path]::IsPathRooted($Game)) { $Game = Join-Path $root $Game }
$jdk = Join-Path $Game 'jdk25\bin'
$jar = Get-ChildItem $Game -Filter 'lod-game-*.jar' | Where-Object { $_.Name -notmatch '-sources' } | Select-Object -First 1
if (-not $jar) { throw "khong thay lod-game-*.jar trong $Game" }
$cls = Join-Path $root 'out\hdbg_classes'
if (Test-Path $cls) { Remove-Item $cls -Recurse -Force }
New-Item -ItemType Directory -Force $cls | Out-Null
$src = Get-ChildItem (Join-Path $PSScriptRoot 'src') -Recurse -Filter *.java | ForEach-Object { $_.FullName }
& (Join-Path $jdk 'javac.exe') -encoding UTF-8 --release 25 -nowarn -cp "$($jar.FullName);$Game\libs\*" -d $cls $src
if ($LASTEXITCODE) { throw 'javac loi' }
$out = Join-Path $root 'out\sc-hdbg.jar'
if (Test-Path $out) { Remove-Item $out -Force }
& (Join-Path $jdk 'jar.exe') --create --file $out -C $cls .
if ($LASTEXITCODE) { throw 'jar loi' }
$entries = & (Join-Path $jdk 'jar.exe') tf $out
if ($entries -notcontains 'legend/' -or $entries -notcontains 'legend/scvi/hdbg/HdBackgrounds.class') { throw 'jar thieu muc legend/ hoac lop listener' }
Write-Output "DAT: $out"
