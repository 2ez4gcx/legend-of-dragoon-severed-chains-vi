<#
build_sc_vi.ps1 — dựng toàn bộ bản thử tiếng Việt cho Severed Chains.

Cách gọi:  powershell -ExecutionPolicy Bypass -File tools/build_sc_vi.ps1 [-Game game]
Các bước:
  1. python tools/sc_lang.py      -> out/lang/lod.vi.lang       (vật phẩm/phép/đồ quý... ghép từ D:\LOD tr/vi)
  2. python tools/sc_dialogue.py  -> out/lang/dialogue.vi.tsv   (13k câu thoại, kiểu N/J/L)
  3. python tools/sc_font.py      -> out/fonts/vietnamese.json/.png + out/font_preview.png
  4. javac (JDK 25 trong <Game>\jdk25) các lớp sc-vi/src với classpath = jar + libs của bản build SC -> out/classes
     Lớp ghi đè PHẢI khớp đúng commit SC của bản build (tên jar lod-game-<commit>.jar; bản thử: affcef0).
  5. tự kiểm sc-vi/test/TagRoundTrip.java (khoá tag, ngắt dòng theo ô và theo điểm ảnh font Việt, bố cục như trong game:
     hộp chọn giữ số dòng, lưới đủ rộng, Funds, bí danh SC), lỗi thì dừng
  6. jar -> out/sc-vi.jar
  7. python tools/sc_core_diff.py -> sc-vi/patches/sc-core-affcef0.diff (nếu có clone Severed-Chains)
Exit 0 = đạt.
#>
param([string]$Game = 'game')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not [System.IO.Path]::IsPathRooted($Game)) { $Game = Join-Path $root $Game }
$env:PYTHONIOENCODING = 'utf-8'

python tools/sc_lang.py; if ($LASTEXITCODE) { exit 1 }
python tools/sc_dialogue.py; if ($LASTEXITCODE) { exit 1 }
python tools/sc_font.py; if ($LASTEXITCODE) { exit 1 }

$jar = Get-ChildItem $Game -Filter 'lod-game-*.jar' | Where-Object { $_.Name -notlike '*-sources.jar' } | Select-Object -First 1
if (-not $jar) { throw "khong thay lod-game-*.jar trong $Game" }
Write-Output "SC: $($jar.Name)"
if ($jar.Name -notlike '*affcef0cba71819515fdf05521c1fedb1d7a92f0*') {
  Write-Output 'CANH BAO: ban build SC khac commit affcef0 ma sc-vi/src duoc sua tu do. Phai ap lai sc-vi/patches/sc-core-affcef0.diff len ma nguon dung commit roi build lai.'
  exit 1
}
$cp = "$($jar.FullName);$Game\libs\*"
$javac = Join-Path $Game 'jdk25\bin\javac.exe'
$java = Join-Path $Game 'jdk25\bin\java.exe'
$jartool = Join-Path $Game 'jdk25\bin\jar.exe'

Remove-Item out\classes, out\test -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force out\classes, out\test | Out-Null
$src = Get-ChildItem sc-vi\src -Recurse -Filter *.java | ForEach-Object { $_.FullName }
& $javac -encoding UTF-8 --release 25 -nowarn -cp $cp -d out\classes $src; if ($LASTEXITCODE) { exit 1 }
& $javac -encoding UTF-8 -cp "out\classes;$cp" -d out\test sc-vi\test\TagRoundTrip.java; if ($LASTEXITCODE) { exit 1 }
& $java -cp "out\test;out\classes;$cp" TagRoundTrip out\lang\dialogue.vi.tsv out\fonts\vietnamese.json
if ($LASTEXITCODE) { Write-Output 'TU KIEM LOI'; exit 1 }

Remove-Item out\sc-vi.jar -ErrorAction SilentlyContinue
& $jartool --create --file out\sc-vi.jar -C out\classes .; if ($LASTEXITCODE) { exit 1 }

# diff gọn của phần sửa lõi (cần clone Severed-Chains đúng commit affcef0; SC_ROOT như sc_lang/sc_font/make_release)
$scRoot = if ($env:SC_ROOT) { $env:SC_ROOT } else { Join-Path $root 'Severed-Chains' }
if (Test-Path (Join-Path $scRoot '.git')) {
  python tools/sc_core_diff.py; if ($LASTEXITCODE) { exit 1 }
} else { Write-Output 'CANH BAO: khong co clone Severed-Chains, khong tao lai sc-vi/patches/sc-core-affcef0.diff' }
Write-Output 'DAT: out\sc-vi.jar (cai bang: powershell -File tools/run_sc.ps1 -Install)'
