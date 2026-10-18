<#
run.ps1 — dịch và chạy ShaderCheck.java: link mọi bộ shader charfx trên GPU thật (OpenGL 3.3 core, cửa sổ SDL ẩn), báo ngân
sách đầu ra GS, kiểm đường hình học bằng transform feedback và so điểm ảnh với bản gốc; link bản GLSL ES của lint.ps1.
Không chạy game, không ghi gì vào thư mục game.

Cách gọi:
  powershell -ExecutionPolicy Bypass -File tools/sc_charfx/check/run.ps1 [-Game game]
Trước đó: python tools/sc_charfx/make_variants.py ; powershell -File tools/sc_charfx/lint.ps1
Dùng JDK 25 + jar LWJGL (opengl, sdl) trong <Game>; lớp dịch ra out\charfx_check\classes, thư viện native giải nén vào
out\charfx_check\natives. Exit 0 = đạt (ShaderCheck in "DAT"), 1 = lỗi.
#>
param([string]$Game = 'game')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
if (-not [System.IO.Path]::IsPathRooted($Game)) { $Game = Join-Path $root $Game }
$jdk = Join-Path $Game 'jdk25\bin'
$out = Join-Path $root 'out\charfx_check'
$cls = Join-Path $out 'classes'
$natives = Join-Path $out 'natives'
if (Test-Path -LiteralPath $cls) { Remove-Item -LiteralPath $cls -Recurse -Force }
New-Item -ItemType Directory -Force $cls, $natives | Out-Null
$cp = "$Game\libs\*"
& (Join-Path $jdk 'javac.exe') -encoding UTF-8 --release 25 -nowarn -cp $cp -d $cls (Join-Path $PSScriptRoot 'ShaderCheck.java')
if ($LASTEXITCODE) { Write-Output 'LOI: javac'; exit 1 }
# java ghi canh bao JDK ra stderr; PS 5.1 se bien no thanh loi neu de 'Stop'
$ErrorActionPreference = 'Continue'
& (Join-Path $jdk 'java.exe') --enable-native-access=ALL-UNNAMED "-Dorg.lwjgl.system.SharedLibraryExtractPath=$natives" `
  -cp "$cls;$cp" ShaderCheck $root $Game 2>&1 | ForEach-Object { "$_" }
$rc = $LASTEXITCODE
if ($rc -ne 0) { Write-Output "LOI: ShaderCheck exit $rc"; exit 1 }
exit 0
