<#
test_cai.ps1 — thử cài sạch gói phát hành như người chơi: giải nén zip vào thư mục trống, gắn 4 đĩa gốc (hard link,
chỉ đọc), chạy launch-vi.bat của gói, chờ SC giải nén xong và lên màn tựa.

Cách gọi:
  powershell -ExecutionPolicy Bypass -File tools/test_cai.ps1 -Zip release\LoD-SC-VN-v0.1-sc-affcef0-windows.zip [-TaiJdk]
    -Zip     gói cần thử
    -TaiJdk  để launch-vi.bat tự tải JDK 25 như người chơi lần đầu (mặc định: chép jdk25 từ thư mục game cho nhanh)
    -Dia     4 file BIN gốc (mặc định: đĩa trong D:\LOD theo paths.json của dự án đó)
Kết quả: test_cai\Severed Chains (VN)\ (sc.pid = tiến trình java, dùng với tools/sc_ui.ps1 -Game <thư mục>).
Exit 0 = lên tới màn tựa, không có "Patch failed"/Exception trong debug.log, classpath có vi/sc-vi.jar đứng đầu.
#>
param(
  [Parameter(Mandatory = $true)][string]$Zip,
  [switch]$TaiJdk,
  [switch]$Choi,
  [string[]]$Dia = @(1, 2, 3, 4 | ForEach-Object { "D:\LOD\Legend of Dragoon The (USA) (Disc $_)\Legend of Dragoon, The (USA) (Disc $_).bin" })
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not [System.IO.Path]::IsPathRooted($Zip)) { $Zip = Join-Path $root $Zip }
$base = Join-Path $root 'test_cai'
$g = Join-Path $base 'Severed Chains (VN)'

# dọn lần trước: java của thư mục thử + cửa sổ cmd của launch-vi.bat (SC gốc "|| pause" giữ thư mục)
Get-CimInstance Win32_Process | Where-Object {
  ($_.Name -eq 'java.exe' -and $_.ExecutablePath -like "$base*") -or ($_.Name -eq 'cmd.exe' -and $_.CommandLine -like '*test_cai*')
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep -Seconds 2
if (Test-Path $base) { Remove-Item $base -Recurse -Force }
New-Item -ItemType Directory $base | Out-Null

python -I -c "import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" $Zip $base
if ($LASTEXITCODE) { throw 'giai nen loi' }
if (-not $TaiJdk) { Copy-Item (Join-Path $root 'game\jdk25') (Join-Path $g 'jdk25') -Recurse }
for ($i = 0; $i -lt 4; $i++) {
  New-Item -ItemType HardLink -Path (Join-Path $g "isos\Disc$($i + 1).bin") -Target $Dia[$i] | Out-Null
}

Start-Process -FilePath cmd.exe -ArgumentList '/c', "`"$g\launch-vi.bat`"" -WorkingDirectory $g | Out-Null
$t0 = Get-Date
$j = @()
while (((Get-Date) - $t0).TotalSeconds -lt 900 -and $j.Count -eq 0) {
  Start-Sleep -Seconds 3
  $j = @(Get-CimInstance Win32_Process -Filter "Name='java.exe'" | Where-Object { $_.ExecutablePath -like "$g*" })
}
if ($j.Count -eq 0) { Write-Output 'LOI: java khong khoi dong'; exit 1 }
Set-Content (Join-Path $g 'sc.pid') $j[0].ProcessId
$cpOk = $j[0].CommandLine -match '-cp "vi/sc-vi.jar;lod-game-'
# Giải nén + vá script xong thì SC nạp âm thanh menu (loadMenuSounds) rồi chiếu phim intro, sau đó tới màn tựa.
# Phim chỉ chạy khi cửa sổ game ở trên cùng, và debug.log ghi theo lô (không dùng để biết đã tới màn tựa) →
# đưa cửa sổ lên mỗi 5 giây trong ~40 giây, rồi chụp ảnh test_cai\man_tua.png để người kiểm xác nhận.
while (((Get-Date) - $t0).TotalSeconds -lt 900) {
  $log = Get-Content (Join-Path $g 'debug.log') -Raw -ErrorAction SilentlyContinue
  if ($log -match 'loadMenuSounds|Patch failed|PatchFailedException') { break }
  Start-Sleep -Seconds 3
}
$ui = Join-Path $PSScriptRoot 'sc_ui.ps1'
for ($k = 0; $k -lt 8; $k++) {
  & powershell -ExecutionPolicy Bypass -File $ui -Game $g -Shot (Join-Path $base 'man_tua.png') | Out-Null
  Start-Sleep -Seconds 5
}
& powershell -ExecutionPolicy Bypass -File $ui -Game $g -Shot (Join-Path $base 'man_tua.png') | Out-Null
$log = Get-Content (Join-Path $g 'debug.log') -Raw -ErrorAction SilentlyContinue
$bad = $log -match 'Patch failed|PatchFailedException|Exception in thread'
$alive = [bool](Get-Process -Id $j[0].ProcessId -ErrorAction SilentlyContinue)
Write-Output ("{0}s; classpath vi/sc-vi.jar dau: {1}; loi trong log: {2}; game con chay: {3}; anh: test_cai\man_tua.png" -f [int]((Get-Date) - $t0).TotalSeconds, $cpOk, $bad, $alive)
if (-not $cpOk -or $bad -or -not $alive) { exit 1 }

if ($Choi) {
  # -Choi: kịch bản chơi cố định, ảnh ở test_cai\choi_*.png (xem bằng mắt):
  #   01 màn tựa, 02 Tùy chọn→Giao diện (Ngôn ngữ/Phông chữ phải tiếng Việt), 03 lời thoại đầu,
  #   04..07 vài hộp thoại sau, 08 menu trong game (E), 09 danh sách vật phẩm.
  function K([string]$keys, [string]$shot = '') {
    $a = @('-ExecutionPolicy', 'Bypass', '-File', $ui, '-Game', $g, '-Keys', $keys)
    if ($shot) { $a += @('-Shot', (Join-Path $base $shot)) }
    & powershell @a | Out-Null
  }
  K 'Return,wait:300,Return,wait:9000' 'choi_01_tua.png'                       # bỏ phim intro, chờ menu hiện hẳn
  K 'Down,Return,wait:1800,Return,wait:1500,Down*3,Return,wait:1500' 'choi_02_tuychon.png'
  K 'Escape,wait:1200,Escape,wait:1200,Escape,wait:9000'
  K 'Return,wait:2000,Down*6,Return,wait:5000,Return,wait:300,Return,wait:5000,Return,wait:300,Return,wait:20000' 'choi_03_thoai_dau.png'
  $n = 4
  for ($i = 1; $i -le 70; $i++) {
    if ($i -in 12, 20, 40, 60) { K 'wait:900,Return,wait:1000' ('choi_{0:D2}.png' -f $n); $n++ } else { K 'wait:900,Return,wait:1000' }
  }
  K 'wait:3000,E,wait:2500' 'choi_08_menu.png'                                # chờ hết hộp thoại/biểu tượng "!" rồi mới mở menu
  K 'Down*2,Return,wait:1800' 'choi_09_vat_pham.png'
  Write-Output 'choi: xem anh test_cai\choi_*.png'
}
exit 0
