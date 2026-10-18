<#
run_sc.ps1 — chạy Severed Chains (thư mục game) có/không có bản vá tiếng Việt sc-vi.jar.

Cách gọi:
  powershell -File tools/run_sc.ps1 [-Game game] [-NoVi] [-Install]
    -Game     thư mục game SC (tương đối theo D:\LOD-SC hoặc tuyệt đối), mặc định "game"
    -Install  chép out/lang/*.lang + dialogue.vi.tsv, tr_sc/*.lang, out/fonts/vietnamese.*, out/sc-vi.jar và out/vi_files
              (lớp phủ đồ hoạ -> <game>/vi/files) vào game
    -NoVi     chạy SC gốc (không thêm sc-vi.jar vào classpath)
    -Gles     thử đường OpenGL ES của bản Android (out/android/sc-android.jar + shader ES, ES 3.2 qua WGL, heap 1,5 GB)
    -HdBg     thử ảnh nền HD: thêm out/sc-hdbg.jar (tools/sc_hdbg/build.ps1) và -Dscvi.hdbg=<thư mục PNG của tools/sc_hd_layers.py>
    -Pn n     thử làm mịn mô hình nhân vật (PN-triangles): thêm out/sc-charfx.jar (tools/sc_charfx/java/build.ps1, TmdObjLoader
              ghi bit PN theo góc vào cờ đỉnh; thiếu jar thì báo lỗi) LÊN ĐẦU classpath và -Dscvi.pn=n (0 = tắt, 1..4 -> mức 2..4).
              Mặc định -1 = không dùng jar. Script này KHÔNG tráo shader: shader PN do bộ thử ngoài (sc_fx.ps1) chép vào
              <game>\gfx\shaders; với shader gốc các bit thêm bị bỏ qua.
    -CharFx   thêm out/sc-charfx.jar như -Pn nhưng để PN tắt (-Dscvi.pn=0, trừ khi có -Pn): kiểm bản ghi đè không đổi gì
    -PnStrength8 s   độ phồng PN theo phần tám 1..8 (-Dscvi.pnStrength8=s; mặc định của jar = 8); chỉ dùng kèm -Pn/-CharFx
Classpath lấy từ launch.bat của bản build (dòng gọi java), thêm sc-vi.jar lên đầu để lớp sửa đè lớp gốc.
Ghi PID vào <game>\sc.pid. Log của SC: <game>\debug.log (ghi đè mỗi lần chạy, ghi trễ — đóng cửa sổ bằng CloseMainWindow
trước khi đọc); trong lúc chạy đọc <game>\stdout.txt.
CHÚ Ý: gọi thành lệnh độc lập, KHÔNG bắt đầu ra (| Out-Null, $x = ..., Start-Job): java thừa hưởng handle của pipe nên
lệnh gọi treo đến khi game thoát.
#>
param(
  [string]$Game = 'game',
  [switch]$NoVi,
  [switch]$Install,
  [switch]$Gles,
  [string]$HdBg = '',
  [int]$Pn = -1,
  [switch]$CharFx,
  [int]$PnStrength8 = 0
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
if ($HdBg) {
  if (-not [System.IO.Path]::IsPathRooted($HdBg)) { $HdBg = Join-Path $root $HdBg }
  $HdBg = [System.IO.Path]::GetFullPath($HdBg)
  if (-not (Test-Path -LiteralPath $HdBg -PathType Container)) { throw "khong co thu muc HdBg: $HdBg" }
  $hdJar = Join-Path $root 'out\sc-hdbg.jar'
  if (-not (Test-Path -LiteralPath $hdJar)) { throw "chua dung $hdJar (tools/sc_hdbg/build.ps1)" }
  $cp = $hdJar + ';' + $cp
  # Start-Process không tự thoát ký tự: "...\hd\" thành \" (dấu nháy thật) và nuốt cả -cp/lớp main -> nhân đôi \ cuối
  $v = "-Dscvi.hdbg=$HdBg"
  if ($v -match '(\\+)$') { $v += $Matches[1] }
  $extra += "`"$v`""
}
if ($CharFx -or $Pn -ge 0) {
  # Jar thử TmdObjLoader ghi bit PN (tools/sc_charfx/java); đứng đầu classpath để đè lớp gốc
  $fxJar = Join-Path $root 'out\sc-charfx.jar'
  if (-not (Test-Path -LiteralPath $fxJar)) { throw "chua dung $fxJar (tools/sc_charfx/java/build.ps1)" }
  $cp = $fxJar + ';' + $cp
  $extra += "-Dscvi.pn=$([Math]::Max($Pn, 0))"
  if ($PnStrength8 -gt 0) { $extra += "-Dscvi.pnStrength8=$PnStrength8" }
} elseif ($PnStrength8 -gt 0) {
  throw '-PnStrength8 chi dung kem -Pn hoac -CharFx'
}
$javaArgs = @('-Djoml.fastmath', '-Djoml.sinLookup', '-Djoml.useMathFma', '-Dscvi.logMissing=true',
  '--add-opens', 'java.base/java.util=ALL-UNNAMED', '--add-exports', 'java.base/jdk.internal.misc=ALL-UNNAMED',
  '--enable-native-access=ALL-UNNAMED') + $extra + @('-ea', '-cp', "`"$cp`"", 'legend.game.MainWindows')
$p = Start-Process -FilePath (Join-Path $Game 'jdk25\bin\java.exe') -ArgumentList $javaArgs -WorkingDirectory $Game -PassThru `
  -RedirectStandardOutput (Join-Path $Game 'stdout.txt') -RedirectStandardError (Join-Path $Game 'stderr.txt')
Set-Content (Join-Path $Game 'sc.pid') $p.Id
$pnInfo = ''
if ($CharFx -or $Pn -ge 0) { $pnInfo = ', pn=' + [Math]::Max($Pn, 0) }
Write-Output "SC PID $($p.Id) (vi=$(-not $NoVi)$pnInfo)"
