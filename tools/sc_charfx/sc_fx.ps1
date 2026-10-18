<#
sc_fx.ps1 — đổi shader TMD của game Severed Chains sang một bộ charfx để thử, và trả lại bản gốc, có kiểm SHA-256 từng file.
Chỉ chạm vào <Game>\gfx\shaders (5 file tmd.vsh, battle_tmd.vsh, tmd.gsh, tmd.fsh, battle_tmd.fsh khi -Apply; cả 13 file khi
-Restore) và thư mục sao lưu out\charfx_backup. Bản gốc luôn trả lại được đúng từng byte (băm của 13 file gốc ghi cứng bên dưới,
lấy từ bản build SC affcef0, LF; đã đối chiếu lại với game\gfx\shaders ngày 18/10/2026).

Cách gọi (powershell -ExecutionPolicy Bypass -File tools/sc_charfx/sc_fx.ps1 ...):
  -Verify                 game\gfx\shaders có đúng 13 shader gốc? (exit 1 nếu khác/thiếu/thừa)
  -Backup                 chép 13 shader gốc sang out\charfx_backup (chỉ khi chúng đúng là bản gốc)
  -Apply <bộ|thư mục>     chép 5 file của out\charfx_variants\<bộ> (hoặc một thư mục) đè lên game\gfx\shaders (LF, UTF-8 không
                          BOM); bộ phải có đủ 5 file, khớp SHA-256 trong manifest.json; phải -Backup trước
                          Game đang chạy: bấm F5 trong game (tools/sc_ui.ps1 -Keys F5) để nạp lại, rồi -CheckLog
  -Restore                trả 13 shader gốc từ bản sao lưu rồi kiểm SHA-256 (chạy được cả khi game đang chạy, sau đó F5)
  -Status                 đang dùng bộ nào (so băm với bản gốc và manifest.json)
  -LogMark                in số dòng hiện có của game\stdout.txt (mốc cho -CheckLog -From)
  -CheckLog [-From n] [-ExpectReload]
                          tìm lỗi biên dịch/link shader trong game\stdout.txt từ dòng n; -ExpectReload: phải thấy
                          "Reloading shaders" sau mốc (F5 đã được nhận)
Exit: 0 = đạt; 1 = lỗi; 3 = (-CheckLog -ExpectReload) chưa thấy dòng nạp lại sau mốc, thử lại sau.

Vì sao LF: khoá bộ đệm shader ES của bản Android = SHA-256("STAGE\0" + nguồn) của file LF trong game\gfx\shaders
(ShaderManager.cacheKey); bản clone Severed-Chains có bản CRLF, băm sẽ khác.
SC biên dịch shader từ gfx/shaders (tương đối theo thư mục game) lúc khởi động (RenderEngine.java:488-497 -> GlShader.reload) và
khi bấm F5 (debug_reload_shaders, CoreMod.java:349 -> RenderEngine.java:835-843). Không có thuộc tính đổi thư mục shader.
Khi đang tạm dừng (F11), SC vẽ lại hàng đợi mô hình cũ mỗi khung với shader hiện hành, nên F5 đổi hình ngay trên khung đứng yên.
RenderEngine giữ ShaderOptions (vị trí uniform) tạo lúc khởi động: bộ charfx không thêm uniform, check/run.ps1 kiểm vị trí
uniform của mọi bộ trùng bản gốc, nên đặt uniform sau F5 vẫn đúng.
#>
param(
  [switch]$Verify,
  [switch]$Backup,
  [string]$Apply = '',
  [switch]$Restore,
  [switch]$Status,
  [switch]$LogMark,
  [switch]$CheckLog,
  [int]$From = 0,
  [switch]$ExpectReload,
  [string]$Game = 'game'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not [System.IO.Path]::IsPathRooted($Game)) { $Game = Join-Path $root $Game }
$Sh = Join-Path $Game 'gfx\shaders'
$Bak = Join-Path $root 'out\charfx_backup'
$Variants = Join-Path $root 'out\charfx_variants'
$TMD = @('tmd.vsh', 'battle_tmd.vsh', 'tmd.gsh', 'tmd.fsh', 'battle_tmd.fsh')

# SHA-256 cua 13 shader goc (ban build SC affcef0, LF), doi chieu voi D:\LOD-SC\game\gfx\shaders ngay 18/10/2026
$ORIG = @{
  'battle_tmd.fsh' = '23e8531f98fa898678d3059eee3ea2fe7dd719ea8bf9bbf9a54bf669981b4d03'
  'battle_tmd.vsh' = '466cff5a65ac167baddf639da1f34539d9d4005140e4617fc27f8a2d32d5883f'
  'copy.fsh'       = 'cd6d0ebe2516ccc325fede23851aab656c04bfe3a728c218b800c01ab3679f4e'
  'copy.vsh'       = 'c74c7d616e5d01032d29dae9bc48ac684181349359be0c7c1544327a85ef0543'
  'post.vsh'       = '755faea4244b8cd530e4a33ac36dd2a3395d52f0a5d28c9172a3e3bc7d673742'
  'screen.fsh'     = '11dc52c024a41fbfb5c9faad00927f72eae62684f0ccbfc682d9cd8ca9a66c92'
  'simple.fsh'     = '5bbd2c2b4fbda70d5d81667924288a7dc2bc95c5d4a1ac0a251bd2b35865e632'
  'simple.vsh'     = 'c35c8aeb664bb295f70bd47aa978ed47c0c496e2b6f720dda6e471e49f3daaf3'
  'standard.fsh'   = '01b7ac1db9c242d635bcef9c184c2589d5f2f5146c20027f156341af8f2b8675'
  'standard.vsh'   = '7c58ec3c31d82a476f386b4cb5c96e5e3b5951421c9963917be03d1574771c07'
  'tmd.fsh'        = '71e1d69a94644e78eed06e9becca00d93d0efb67fc790e2053863ca34d150e5c'
  'tmd.gsh'        = '96b7ba7f5dfad00947f9780feffecacf98479f81b4afe3d70329b2cd48f6ee34'
  'tmd.vsh'        = '81b83e378d8fb1e2e09058b6d1badd1db6c0aa16e5f3cee89deca62ca302ad08'
}

function Hash([string]$f) { (Get-FileHash -Algorithm SHA256 -LiteralPath $f).Hash.ToLower() }

# Danh sach sai khac so voi 13 file goc (rong = dung ban goc)
function Check-Dir([string]$dir) {
  if (-not (Test-Path -LiteralPath $dir -PathType Container)) { return , @("thu muc $dir khong ton tai") }
  $bad = @()
  foreach ($k in $ORIG.Keys) {
    $f = Join-Path $dir $k
    if (-not (Test-Path -LiteralPath $f)) { $bad += "$k thieu"; continue }
    $h = Hash $f
    if ($h -ne $ORIG[$k]) { $bad += "$k $h (can $($ORIG[$k]))" }
  }
  foreach ($f in Get-ChildItem -LiteralPath $dir -File) { if (-not $ORIG.ContainsKey($f.Name)) { $bad += "$($f.Name) la file thua" } }
  return , $bad
}

function Game-Running {
  $pidFile = Join-Path $Game 'sc.pid'
  if (-not (Test-Path -LiteralPath $pidFile)) { return $false }
  $id = [int](Get-Content -LiteralPath $pidFile)
  return [bool](Get-Process -Id $id -ErrorAction SilentlyContinue)
}

function Manifest {
  $m = Join-Path $Variants 'manifest.json'
  if (-not (Test-Path -LiteralPath $m)) { return $null }
  return (Get-Content -LiteralPath $m -Raw | ConvertFrom-Json)
}

# stdout.txt dang bi java ghi: mo voi FileShare.ReadWrite
function Log-Lines {
  $log = Join-Path $Game 'stdout.txt'
  if (-not (Test-Path -LiteralPath $log)) { return , @() }
  $fs = [System.IO.File]::Open($log, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
  try {
    $sr = New-Object System.IO.StreamReader($fs, [System.Text.Encoding]::UTF8)
    $lines = $sr.ReadToEnd() -split "`r?`n"
  } finally { $fs.Dispose() }
  return , $lines
}

$rc = 0
if ($Verify) {
  $bad = Check-Dir $Sh
  if ($bad.Count) { $bad | ForEach-Object { Write-Output "KHAC: $_" }; exit 1 }
  Write-Output "OK: $Sh = 13 shader goc (SHA-256 khop)"
}

if ($Backup) {
  $bad = Check-Dir $Sh
  if ($bad.Count) { $bad | ForEach-Object { Write-Output "KHAC: $_" }; Write-Output 'LOI: shader hien tai khong phai ban goc, khong sao luu'; exit 1 }
  New-Item -ItemType Directory -Force $Bak | Out-Null
  foreach ($k in $ORIG.Keys) { Copy-Item -LiteralPath (Join-Path $Sh $k) -Destination (Join-Path $Bak $k) -Force }
  $bad = Check-Dir $Bak
  if ($bad.Count) { $bad | ForEach-Object { Write-Output "KHAC: $_" }; Write-Output 'LOI: ban sao luu sai'; exit 1 }
  Write-Output "OK: sao luu 13 shader goc -> $Bak"
}

if ($Apply) {
  $bad = Check-Dir $Bak
  if ($bad.Count) { Write-Output "LOI: chua -Backup (hoac $Bak khong con dung ban goc)"; exit 1 }
  $dir = $Apply
  if (-not [System.IO.Path]::IsPathRooted($dir) -and $dir -notmatch '[\\/]') { $dir = Join-Path $Variants $dir }
  elseif (-not [System.IO.Path]::IsPathRooted($dir)) { $dir = Join-Path $root $dir }
  # chuan hoa (".\", "/", "\" cuoi) de bo trong out\charfx_variants luon duoc so voi manifest.json
  $dir = [System.IO.Path]::GetFullPath($dir).TrimEnd('\', '/')
  if (-not (Test-Path -LiteralPath $dir -PathType Container)) { Write-Output "LOI: khong co thu muc bo $dir"; exit 1 }
  $files = @(Get-ChildItem -LiteralPath $dir -File | Where-Object { $_.Extension -in '.vsh', '.gsh', '.fsh' })
  $names = @($files | ForEach-Object { $_.Name } | Sort-Object)
  if (($names -join ',') -ne (($TMD | Sort-Object) -join ',')) {
    Write-Output "LOI: bo phai co dung 5 file $($TMD -join ', ') (co: $($names -join ', '))"; exit 1
  }
  foreach ($f in Get-ChildItem -LiteralPath $Sh -File) {
    if (-not $ORIG.ContainsKey($f.Name)) { Write-Output "LOI: $Sh co file thua $($f.Name)"; exit 1 }
  }
  $name = Split-Path -Leaf $dir
  $man = Manifest
  $want = $null
  if ($man -and $man.variants.PSObject.Properties.Name -contains $name -and $dir -eq [System.IO.Path]::GetFullPath((Join-Path $Variants $name))) {
    $want = $man.variants.$name.sha256
  }
  $utf8 = New-Object System.Text.UTF8Encoding $false
  foreach ($f in $files) {
    $text = [System.IO.File]::ReadAllText($f.FullName) -replace "`r`n", "`n"
    $dst = Join-Path $Sh $f.Name
    [System.IO.File]::WriteAllText($dst, $text, $utf8)
    $h = Hash $dst
    if ($want -and $want.($f.Name) -ne $h) {
      Write-Output "LOI: $($f.Name) sau khi ap co SHA-256 $h, manifest.json ghi $($want.($f.Name)) (chay lai make_variants.py)"
      $rc = 1
    }
    Write-Output ("ap {0,-15} {1}" -f $f.Name, $h)
  }
  if ($rc) { Write-Output 'LOI: ap khong khop manifest; tra ban goc bang -Restore'; exit 1 }
  Write-Output "OK: da ap bo $name ($(if ($want) { 'khop manifest.json' } else { 'thu muc ngoai manifest' }))"
  if (Game-Running) { Write-Output 'game dang chay: bam F5 (tools/sc_ui.ps1 -Keys F5) roi -CheckLog' }
}

if ($Restore) {
  $bad = Check-Dir $Bak
  if ($bad.Count) { $bad | ForEach-Object { Write-Output "KHAC: $_" }; Write-Output "LOI: $Bak khong phai 13 shader goc, khong khoi phuc duoc tu day"; exit 1 }
  foreach ($k in $ORIG.Keys) { Copy-Item -LiteralPath (Join-Path $Bak $k) -Destination (Join-Path $Sh $k) -Force }
  $bad = Check-Dir $Sh
  if ($bad.Count) { $bad | ForEach-Object { Write-Output "KHAC: $_" }; Write-Output 'LOI: khoi phuc chua dung'; exit 1 }
  Write-Output 'OK: da khoi phuc 13 shader goc (SHA-256 khop)'
  if (Game-Running) { Write-Output 'game dang chay: bam F5 de nap lai shader goc' }
}

if ($Status) {
  $bad = Check-Dir $Sh
  if (-not $bad.Count) { Write-Output 'dang dung: ban goc (13 file khop)' }
  else {
    $man = Manifest
    $cur = @{}
    foreach ($f in $TMD) { $p = Join-Path $Sh $f; if (Test-Path -LiteralPath $p) { $cur[$f] = Hash $p } }
    $hit = ''
    if ($man) {
      foreach ($v in $man.variants.PSObject.Properties) {
        $ok = $true
        foreach ($f in $TMD) { if ($v.Value.sha256.$f -ne $cur[$f]) { $ok = $false } }
        if ($ok) { $hit = $v.Name }
      }
    }
    $other = @($bad | Where-Object { $_ -notmatch '^(tmd|battle_tmd)\.(vsh|gsh|fsh) ' })
    if ($hit -and -not $other.Count) { Write-Output "dang dung: bo $hit (manifest.json), 8 shader khac = goc" }
    else { $bad | ForEach-Object { Write-Output "KHAC: $_" }; Write-Output 'dang dung: khong ro (khong khop bo nao trong manifest.json)'; $rc = 1 }
  }
}

if ($LogMark) {
  # chi so cua dong cuoi (co the dang ghi do / rong): dong moi bat dau tu day, doc lai dong do cung vo hai
  Write-Output ([Math]::Max(0, (Log-Lines).Count - 1))
}

if ($CheckLog) {
  $lines = Log-Lines
  $new = @()
  if ($From -lt $lines.Count) { $new = @($lines[$From..($lines.Count - 1)]) }
  $hits = @($new | Where-Object { $_ -match 'Shader compile error|Program link error|Uniform block .* not found|Uniform .* not found|Failed to reload shaders|Reloading shaders' })
  $hits | ForEach-Object { Write-Output $_ }
  if ($hits | Where-Object { $_ -match 'error|not found|Failed' }) { Write-Output 'LOI: shader loi trong stdout.txt'; exit 1 }
  if ($ExpectReload -and -not ($hits | Where-Object { $_ -match 'Reloading shaders' })) { Write-Output "chua thay 'Reloading shaders' sau dong $From"; exit 3 }
}
exit $rc
