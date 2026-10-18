<#
ab_scene.ps1 — chụp trước/sau các bộ shader charfx trên MỘT khung đứng yên của game đang chạy (F11 tạm dừng, F5 nạp lại
shader), kèm mặt nạ đỏ chỗ đổi, rồi luôn trả shader gốc. Chỉ gửi F11/F5 (không gửi phím xác nhận: an toàn khi đang thoại/trận).

Trình tự lệnh đầy đủ (từ D:\LOD-SC):
  python tools/sc_charfx/make_variants.py                        # out\charfx_variants\{z_off,pn,l2t,all} + manifest.json
  powershell -ExecutionPolicy Bypass -File tools/sc_charfx/lint.ps1          # dịch ES (Android) + check_iface.py
  powershell -ExecutionPolicy Bypass -File tools/sc_charfx/check/run.ps1     # link + so điểm ảnh trên GPU
  powershell -ExecutionPolicy Bypass -File tools/run_sc.ps1 [-Pn 3]          # chạy game; -Pn n = loader ghi bit PN (route B)
  ... đưa nhân vật vào cảnh muốn chụp, để cửa sổ game trên cùng ...
  powershell -ExecutionPolicy Bypass -File tools/sc_charfx/sc_fx.ps1 -Verify  # shader trong game = gốc
  powershell -ExecutionPolicy Bypass -File tools/sc_charfx/ab_scene.ps1 -Scene c11 [-Variants z_off,pn,l2t,all] [-PnActive]
                                                                  [-AlreadyPaused] [-Unpause]
Script tự làm: sc_fx -Verify, sc_fx -Backup, F11 (trừ -AlreadyPaused), chụp A0 rồi A (phải giống: đã đứng yên), với mỗi bộ:
  sc_fx -LogMark, sc_fx -Apply <bộ>, F5, chờ "Reloading shaders" trong game\stdout.txt, chờ -ReloadMs, sc_fx -CheckLog (lỗi
  biên dịch/link -> huỷ), chụp <Scene>_<bộ>.png + <Scene>_<bộ>_mask.png (cmp.py); cuối cùng (finally, kể cả khi lỗi):
  sc_fx -Restore, F5, chụp A2 (phải giống A), ghép <Scene>_sheet.png, F11 nếu -Unpause.
Kiểm tra:
  không -PnActive (loader chưa ghi bit PN): z_off == A, pn == A, l2t != A, all != A, all == l2t
  -PnActive (run_sc.ps1 -Pn n):            z_off == A (PN/L2/T tắt lúc chạy dù có bit PN), pn != A, l2t != A, all != l2t
  luôn: A2 == A (F5 + trả gốc cho lại đúng hình cũ; khác thì ảnh F5 không tin được, dùng khởi động lạnh)
Ảnh (có nền suy ra từ đĩa gốc, chỉ để trong work\upscale\, không commit): -Out (mặc định work\upscale\charfx_shots)\
  <Scene>_A0.png, <Scene>_A.png, <Scene>_<bộ>.png, <Scene>_<bộ>_mask.png, <Scene>_A2.png, <Scene>_sheet.png
Exit 0 = mọi kiểm tra đạt; 1 = huỷ (shader gốc đã được trả, xem dòng ABORT); 2 = chụp xong nhưng có kiểm tra không đạt.
Phím/ảnh qua tools/sc_ui.ps1 (cửa sổ SC phải ở trên cùng; mất tiêu điểm thì huỷ).
#>
param(
  [Parameter(Mandatory = $true)][string]$Scene,
  [string[]]$Variants = @('z_off', 'pn', 'l2t', 'all'),
  [string]$Out = '',
  [string]$Game = 'game',
  [int]$ReloadMs = 1500,
  [int]$ReloadTimeoutMs = 10000,
  [switch]$PnActive,
  [switch]$AlreadyPaused,
  [switch]$Unpause
)
$ErrorActionPreference = 'Continue'
# powershell -File truyen "a,b" thanh MOT chuoi: tach ra
$Variants = @($Variants | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not [System.IO.Path]::IsPathRooted($Game)) { $Game = Join-Path $root $Game }
if (-not $Out) { $Out = Join-Path $root 'work\upscale\charfx_shots' }
elseif (-not [System.IO.Path]::IsPathRooted($Out)) { $Out = Join-Path $root $Out }
$FX = Join-Path $PSScriptRoot 'sc_fx.ps1'
$UI = Join-Path $root 'tools\sc_ui.ps1'
$Cmp = Join-Path $PSScriptRoot 'cmp.py'
New-Item -ItemType Directory -Force $Out | Out-Null

# Dau ra cua lenh con in qua Write-Host de ham chi tra ve gia tri trang thai
function Fx([string[]]$a) {
  & powershell -NoProfile -ExecutionPolicy Bypass -File $FX -Game $Game @a | ForEach-Object { Write-Host "  [fx] $_" }
  return [int]$LASTEXITCODE
}
function LogMark {
  $o = @(& powershell -NoProfile -ExecutionPolicy Bypass -File $FX -Game $Game -LogMark)
  if ($LASTEXITCODE -ne 0 -or -not $o.Count) { throw 'sc_fx -LogMark loi' }
  return [int]$o[-1]
}
function Ui([string[]]$a) {
  & powershell -NoProfile -ExecutionPolicy Bypass -File $UI -Game $Game @a | ForEach-Object { Write-Host "  [ui] $_" }
  if ($LASTEXITCODE -ne 0) { throw "sc_ui loi: $a" }
}
function Shot([string]$name) { Ui @('-Shot', (Join-Path $Out "$name.png")) }
function Same([string]$a, [string]$b, [string]$mask = '') {
  $p = @($Cmp, (Join-Path $Out "$a.png"), (Join-Path $Out "$b.png"))
  if ($mask) { $p += @('--mask', (Join-Path $Out "$mask.png")) }
  & python @p | ForEach-Object { Write-Host "  [cmp $a / $b] $_" }
  if ($LASTEXITCODE -eq 1) { throw "cmp.py loi ($a / $b)" }
  return ($LASTEXITCODE -eq 0)
}
# Cho F5 duoc nhan ("Reloading shaders" sau moc), cho shader bien dich xong, roi kiem loi
function Wait-Reload([int]$mark) {
  $t0 = Get-Date
  while ($true) {
    $rc = Fx @('-CheckLog', '-From', "$mark", '-ExpectReload')
    if ($rc -eq 0) { break }
    if ($rc -eq 1) { throw 'shader loi bien dich/link sau F5 (xem game\stdout.txt)' }
    if (((Get-Date) - $t0).TotalMilliseconds -gt $ReloadTimeoutMs) { throw "F5 khong duoc nhan: khong thay 'Reloading shaders' sau $ReloadTimeoutMs ms" }
    Start-Sleep -Milliseconds 300
  }
  Start-Sleep -Milliseconds $ReloadMs
  if ((Fx @('-CheckLog', '-From', "$mark")) -ne 0) { throw 'shader loi bien dich/link sau F5 (xem game\stdout.txt)' }
}

$pidFile = Join-Path $Game 'sc.pid'
if (-not (Test-Path -LiteralPath $pidFile) -or -not (Get-Process -Id ([int](Get-Content -LiteralPath $pidFile)) -ErrorAction SilentlyContinue)) {
  Write-Host 'ABORT: game khong chay (tools/run_sc.ps1)'; exit 1
}
foreach ($v in $Variants) {
  if (-not (Test-Path -LiteralPath (Join-Path $root "out\charfx_variants\$v") -PathType Container)) {
    Write-Host "ABORT: khong co bo $v (python tools/sc_charfx/make_variants.py)"; exit 1
  }
}
if ((Fx @('-Verify')) -ne 0) { Write-Host 'ABORT: game\gfx\shaders khong phai bo goc (chay tools/sc_charfx/sc_fx.ps1 -Restore truoc)'; exit 1 }
if ((Fx @('-Backup')) -ne 0) { Write-Host 'ABORT: sao luu shader goc loi'; exit 1 }

$failed = @()
$aborted = ''
$shot = @{}
try {
  if (-not $AlreadyPaused) { Ui @('-Keys', 'F11,wait:800') }
  Shot "${Scene}_A0"
  Start-Sleep -Milliseconds 1200
  Shot "${Scene}_A"
  if (-not (Same "${Scene}_A0" "${Scene}_A")) { throw 'khung van dang chay (chua tam dung? bam F11 bang tay roi chay lai voi -AlreadyPaused)' }

  foreach ($v in $Variants) {
    $mark = LogMark
    if ((Fx @('-Apply', $v)) -ne 0) { throw "ap bo $v loi" }
    Ui @('-Keys', 'F5')
    Wait-Reload $mark
    Shot "${Scene}_$v"
    $shot[$v] = Same "${Scene}_A" "${Scene}_$v" "${Scene}_${v}_mask"
  }
} catch {
  $aborted = "$_"
} finally {
  try {
    $mark = LogMark
    if ((Fx @('-Restore')) -ne 0) { Write-Host 'LOI: khoi phuc shader goc loi - chay tools/sc_charfx/sc_fx.ps1 -Restore bang tay NGAY' }
    Ui @('-Keys', 'F5')
    Wait-Reload $mark
  } catch {
    Write-Host "LOI khi tra shader goc / F5: $_ (kiem tra lai bang sc_fx.ps1 -Verify, bam F5 bang tay)"
    if (-not $aborted) { $aborted = "tra shader goc: $_" }
  }
}
# A2 cu cua lan chay truoc khong duoc thay cho A2 lan nay
$a2 = Join-Path $Out "${Scene}_A2.png"
if (Test-Path -LiteralPath $a2) { Remove-Item -LiteralPath $a2 -Force }
try { Shot "${Scene}_A2" } catch { Write-Host "chup A2 loi: $_" }
if ($aborted) { Write-Host "ABORT: $aborted (shader goc da tra lai)"; exit 1 }

# so sanh theo ky vong (cmp.py loi -> ghi thanh kiem tra khong dat, khong dung giua chung)
function Expect([string]$v, [bool]$wantSame, [string]$why) {
  if (-not $shot.ContainsKey($v)) { return }
  if ($shot[$v] -ne $wantSame) { $script:failed += "$v $(if ($wantSame) { 'khac' } else { 'giong' }) ban goc: $why" }
}
function Pair([string]$a, [string]$b, [bool]$wantSame, [string]$why) {
  if (-not ($shot.ContainsKey($a) -and $shot.ContainsKey($b))) { return }
  try { $s = Same "${Scene}_$a" "${Scene}_$b" } catch { $script:failed += "so $a / $b loi: $_"; return }
  if ($s -ne $wantSame) { $script:failed += "$a $(if ($wantSame) { 'khac' } else { 'giong' }) $($b): $why" }
}
if ($PnActive) {
  Expect 'z_off' $true 'co bit PN nhung PN/L2/T cua z_off tat luc chay (backgroundColour.w = 0) -> phai giong ban goc tung diem anh'
  Expect 'pn' $false 'loader ghi bit PN thi pn phai doi hinh'
  Pair 'l2t' 'all' $false 'all giong l2t du co bit PN (PN khong chay trong all?)'
} else {
  Expect 'z_off' $true 'duong tat luc chay phai giong ban goc tung diem anh'
  Expect 'pn' $true 'khong co bit PN thi pn phai giong ban goc (neu da chay run_sc.ps1 -Pn n thi them -PnActive)'
  Pair 'l2t' 'all' $true 'all khac l2t du khong co bit PN (vector mat tinh o GS lech VS?)'
}
Expect 'l2t' $false 'L2/T ep bat cho moi mo hinh lit phai doi hinh (F5 khong nap?)'
Expect 'all' $false 'L2/T ep bat phai doi hinh'
if (-not (Test-Path -LiteralPath $a2)) { $failed += 'khong chup duoc A2: chua kiem duoc F5 + tra goc cho lai dung hinh cu' }
else {
  try { if (-not (Same "${Scene}_A" "${Scene}_A2")) { $failed += 'A2 khac A: F5/tra goc lam doi hinh, khong tin duoc anh F5 (dung khoi dong lanh)' } }
  catch { $failed += "so A / A2 loi: $_" }
}

$sheet = @((Join-Path $Out "${Scene}_A.png"), (Join-Path $Out "${Scene}_A2.png"))
foreach ($v in $Variants) { $sheet += @((Join-Path $Out "${Scene}_$v.png"), (Join-Path $Out "${Scene}_${v}_mask.png")) }
& python $Cmp --sheet (Join-Path $Out "${Scene}_sheet.png") @sheet --cols 2 | ForEach-Object { Write-Host "  [sheet] $_" }

if ($Unpause) { try { Ui @('-Keys', 'F11') } catch { Write-Host "F11 loi: $_" } }
if ($failed.Count) { $failed | ForEach-Object { Write-Host "KIEM TRA KHONG DAT: $_" }; exit 2 }
Write-Host "OK: $Scene da chup ($($Variants -join ', ')), shader goc da tra lai; anh trong $Out"
exit 0
