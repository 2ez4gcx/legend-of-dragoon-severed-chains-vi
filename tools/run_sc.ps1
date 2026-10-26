<#
run_sc.ps1 — chạy Severed Chains (thư mục game) có/không có bản vá tiếng Việt sc-vi.jar.

Cách gọi:
  powershell -File tools/run_sc.ps1 [-Game game] [-NoVi] [-Install]
    -Game     thư mục game SC (tương đối theo D:\LOD-SC hoặc tuyệt đối), mặc định "game"
    -Install  chép out/lang/*.lang + dialogue.vi.tsv, tr_sc/*.lang, out/fonts/vietnamese.*, out/sc-vi.jar và out/vi_files
              (lớp phủ đồ hoạ -> <game>/vi/files) vào game
    -NoVi     chạy SC gốc (không thêm sc-vi.jar vào classpath)
    -Gles     thử đường OpenGL ES của bản Android (out/android/sc-android.jar + shader ES, ES 3.2 qua WGL, heap 1,5 GB)
Classpath lấy từ launch.bat của bản build (dòng gọi java), thêm sc-vi.jar lên đầu để lớp sửa đè lớp gốc.
Ghi PID vào <game>\sc.pid. Log của SC: <game>\logs\.
CHÚ Ý: gọi thành lệnh độc lập, KHÔNG bắt đầu ra (| Out-Null, $x = ..., Start-Job): java thừa hưởng handle của pipe nên
lệnh gọi treo đến khi game thoát.
#>
param(
  [string]$Game = 'game',
  [switch]$NoVi,
  [switch]$Install,
  [switch]$Gles
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
  $vf = Join-Path $Game 'vi/files'
  if (Test-Path $vf) { Remove-Item $vf -Recurse -Force }
  New-Item -ItemType Directory -Force (Join-Path $Game 'vi') | Out-Null
  Copy-Item (Join-Path $root 'out/vi_files') $vf -Recurse -Force
  Copy-Item (Join-Path $root 'out/gfx/ui/title_menu.vi.*') (Join-Path $Game 'gfx/ui') -Force
  Copy-Item (Join-Path $root 'out/gfx/textures/icon.vi.png') (Join-Path $Game 'gfx/textures') -Force
  Write-Output "Da cai lang/font/sc-vi.jar vao $Game"
}

$bat = Get-Content (Join-Path $Game 'launch.bat') | Where-Object { $_ -match '\\jdk25\\bin\\java"' }
if (-not $bat) { throw 'khong tim thay dong java trong launch.bat' }
if ($bat -notmatch '-cp "([^"]+)"') { throw 'khong doc duoc classpath' }
$cp = $Matches[1]
if (-not $NoVi) { $cp = 'sc-vi.jar;' + $cp }

$extra = @('-Xmx3G')
if ($Gles) {
  # Thử đường OpenGL ES của bản Android ngay trên máy tính: lớp đè android (SdlWindow vào thẳng ES 3.2, shader ES dịch sẵn,
  # GlesTexture, IsoReader), ES 3.2 qua WGL của driver (NVIDIA), heap như điện thoại
  $cp = (Join-Path $root 'out\android\sc-android.jar') + ';' + $cp
  $es = Join-Path $Game 'gfx\shaders_es'
  if (Test-Path $es) { Remove-Item $es -Recurse -Force }
  Copy-Item (Join-Path $root 'out\android\shaders_es') $es -Recurse
  $extra = @('-Xmx1536m', '-Dscvi.android=true', '-Dorg.lwjgl.opengles.libname=opengl32.dll', '-Dorg.lwjgl.opengles.contextAPI=native',
    '--add-opens', 'java.base/java.io=ALL-UNNAMED')
}
$javaArgs = @('-Djoml.fastmath', '-Djoml.sinLookup', '-Djoml.useMathFma', '-Dscvi.logMissing=true',
  '--add-opens', 'java.base/java.util=ALL-UNNAMED', '--add-exports', 'java.base/jdk.internal.misc=ALL-UNNAMED',
  '--enable-native-access=ALL-UNNAMED') + $extra + @('-ea', '-cp', "`"$cp`"", 'legend.game.MainWindows')
$p = Start-Process -FilePath (Join-Path $Game 'jdk25\bin\java.exe') -ArgumentList $javaArgs -WorkingDirectory $Game -PassThru `
  -RedirectStandardOutput (Join-Path $Game 'stdout.txt') -RedirectStandardError (Join-Path $Game 'stderr.txt')
Set-Content (Join-Path $Game 'sc.pid') $p.Id
Write-Output "SC PID $($p.Id) (vi=$(-not $NoVi))"
