<#
build.ps1 — dựng out/sc-charfx.jar: jar THỬ (chỉ trên PC, không phát hành, không nằm trong sc-vi/src) ghi đè
legend.game.tmd.TmdObjLoader của Severed Chains affcef0 để ghi bit PN theo góc vào float cờ của từng đỉnh khi nạp mô hình
nhân vật (geometry shader PN-triangles đọc các bit này; shader do tools ngoài như sc_fx.ps1 tráo, không phải jar này).

Cách gọi:
  powershell -ExecutionPolicy Bypass -File tools/sc_charfx/java/build.ps1 [-Game game] [-Check]
    -Game   thư mục bản build SC (tương đối theo D:\LOD-SC hoặc tuyệt đối), mặc định "game"; chỉ ĐỌC, không sửa gì trong đó
    -Check  sau khi dựng, tự kiểm (exit 0 = đạt, 1 = lỗi):
            (a) javap: biên dịch TmdObjLoader GỐC từ clone Severed-Chains (phải đúng commit affcef0, tệp chưa sửa) ->
                out/sc_charfx_orig; so "javap -c -p -constants" (bỏ số hiệu hằng #n) của: bản gốc vừa dịch == lớp trong jar game
                (mọi thành viên); bản ghi đè == bản gốc ở mọi thành viên trừ fromObjTable(String, TmdObjTable1c, int, int, int);
                trong hàm đã sửa, dãy lệnh gốc (bỏ số khe biến cục bộ và đích nhảy) phải là dãy con của dãy lệnh mới, lệnh chèn
                thêm chỉ được gọi PnConfig
            (b) không cần GL: dịch tools/sc_charfx/java/test (GameEngine giả + CaptureApi + PnCheck) -> out/sc_charfx_test, chạy
                PnCheck dump với TmdObjLoader của jar game ("orig") và của out/sc-charfx.jar khi không đặt scvi.pn ("off"),
                scvi.pn=0, scvi.pn=4, scvi.pn=1 (kẹp về 2), scvi.pn=2 + scvi.pnStrength8=5; orig/off/pn0 phải giống từng byte,
                các bản có PN qua PnCheck pn (xem docstring PnCheck.java); tự kiểm bộ kiểm: "same" phải báo khác giữa orig
                và pn4, "selftest" sửa giả 9 kiểu lỗi trong pn4 và "pn" phải bắt đúng loại lỗi. Tệp dump (dữ liệu mô hình
                Sony) ghi vào work/upscale/sc_charfx_check (git bỏ qua).
Nguồn: tools/sc_charfx/java/src/legend/game/tmd/{TmdObjLoader,PnEdgeFlags,PnConfig}.java. Biên dịch javac --release 25 của
<Game>\jdk25 với classpath = lod-game-affcef0...jar (KHÔNG phải -sources.jar) + <Game>\libs\*; đóng gói bằng công cụ jar.
Chạy game với jar này: powershell -File tools/run_sc.ps1 -Pn 4   (thuộc tính: xem PnConfig.java)
#>
param([string]$Game = 'game', [switch]$Check)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $here))
if (-not [System.IO.Path]::IsPathRooted($Game)) { $Game = Join-Path $root $Game }
$jdk = Join-Path $Game 'jdk25\bin'
$javac = Join-Path $jdk 'javac.exe'
$java = Join-Path $jdk 'java.exe'
$jartool = Join-Path $jdk 'jar.exe'
$javap = Join-Path $jdk 'javap.exe'
$commit = 'affcef0cba71819515fdf05521c1fedb1d7a92f0'

$jar = Get-ChildItem $Game -Filter 'lod-game-*.jar' | Where-Object { $_.Name -notmatch '-sources' } | Select-Object -First 1
if (-not $jar) { throw "khong thay lod-game-*.jar trong $Game" }
if ($jar.Name -notlike "*$commit*") { throw "ban build SC $($jar.Name) khac commit affcef0 ma TmdObjLoader ghi de duoc chep tu do" }
$cp = "$($jar.FullName);$Game\libs\*"

# ---------- dựng ----------
$cls = Join-Path $root 'out\sc_charfx_classes'
if (Test-Path $cls) { Remove-Item $cls -Recurse -Force }
New-Item -ItemType Directory -Force $cls | Out-Null
$src = Get-ChildItem (Join-Path $here 'src') -Recurse -Filter *.java | ForEach-Object { $_.FullName }
& $javac -encoding UTF-8 --release 25 -nowarn -implicit:none -cp $cp -d $cls $src
if ($LASTEXITCODE) { throw 'javac loi (src)' }
$outJar = Join-Path $root 'out\sc-charfx.jar'
if (Test-Path $outJar) { Remove-Item $outJar -Force }
& $jartool --create --file $outJar -C $cls .
if ($LASTEXITCODE) { throw 'jar loi' }
$entries = & $jartool tf $outJar
$classes = @($entries | Where-Object { $_ -like '*.class' } | Sort-Object)
$want = @('legend/game/tmd/PnConfig.class', 'legend/game/tmd/PnEdgeFlags.class', 'legend/game/tmd/PnEdgeFlags$EdgeUse.class', 'legend/game/tmd/TmdObjLoader.class') | Sort-Object
if (($classes -join ',') -ne ($want -join ',')) { throw "jar co lop la/thieu: $($classes -join ', ')" }
Write-Output "Da dung $outJar ($($classes.Count) lop)"
if (-not $Check) { Write-Output 'DAT (chua tu kiem; them -Check)'; exit 0 }

$fail = 0
function Fail([string]$msg) { Write-Output "LOI: $msg"; $script:fail++ }

# ---------- (a) javap ----------
$scRoot = if ($env:SC_ROOT) { $env:SC_ROOT } else { Join-Path $root 'Severed-Chains' }
$origSrc = Join-Path $scRoot 'src\main\java\legend\game\tmd\TmdObjLoader.java'
if (-not (Test-Path $origSrc)) { throw "khong co $origSrc (can clone Severed-Chains dung commit affcef0; SC_ROOT)" }
$head = (& git -C $scRoot rev-parse HEAD).Trim()
if ($head -ne $commit) { Fail "Severed-Chains HEAD $head khac $commit" }
& git -C $scRoot diff --quiet HEAD -- 'src/main/java/legend/game/tmd/TmdObjLoader.java'
if ($LASTEXITCODE) { Fail 'TmdObjLoader.java trong Severed-Chains da bi sua so voi HEAD' }

$origCls = Join-Path $root 'out\sc_charfx_orig'
if (Test-Path $origCls) { Remove-Item $origCls -Recurse -Force }
New-Item -ItemType Directory -Force $origCls | Out-Null
& $javac -encoding UTF-8 --release 25 -nowarn -implicit:none -cp $cp -d $origCls $origSrc
if ($LASTEXITCODE) { throw 'javac loi (TmdObjLoader goc)' }

function Get-Members([string]$classPath) {
  $text = & $javap -c -p -constants -cp $classPath legend.game.tmd.TmdObjLoader
  if ($LASTEXITCODE) { throw "javap loi: $classPath" }
  $members = [ordered]@{}
  $key = $null
  foreach ($line in $text) {
    if ($line -match '^  \S') {
      $key = $line.Trim()
      $members[$key] = New-Object System.Collections.Generic.List[string]
    } elseif ($key -and $line -match '^\s{4,}\S') {
      $members[$key].Add((($line -replace '#\d+', '#') -replace '\s+', ' ').Trim())
    }
  }
  return $members
}
function Get-Ops($lines) {
  foreach ($l in $lines) {
    if ($l -match '^\d+: (\S+)(.*)$') {
      $op = $Matches[1] -replace '^([ailfd](load|store))_\d$', '$1'
      $rest = $Matches[2].Trim()
      if ($op -match '^[ailfd](load|store)$' -or $op -eq 'iinc' -or $op -match '^(if|goto)') { $rest = '' }
      ("$op $rest").Trim()
    }
  }
}

$mOrig = Get-Members $origCls
$mShip = Get-Members $jar.FullName
$mOver = Get-Members $cls
$edited = 'public static legend.core.renderer.MeshObj fromObjTable(java.lang.String, legend.game.tmd.TmdObjTable1c, int, int, int);'

if (($mOrig.Keys -join '|') -ne ($mShip.Keys -join '|')) { Fail 'thanh vien TmdObjLoader goc vua dich khac lop trong jar game' }
$diffShip = @($mOrig.Keys | Where-Object { -not $mShip.Contains($_) -or (($mOrig[$_] -join "`n") -ne ($mShip[$_] -join "`n")) })
if ($diffShip.Count) { Fail "TmdObjLoader goc vua dich khac jar game o: $($diffShip -join '; ')" }
else { Write-Output "javap: TmdObjLoader goc (Severed-Chains affcef0, javac 25) == lop trong $($jar.Name): $($mOrig.Count) thanh vien" }

if (($mOrig.Keys -join '|') -ne ($mOver.Keys -join '|')) { Fail "danh sach thanh vien ban ghi de khac ban goc: $($mOver.Keys -join '; ')" }
$diffOver = @($mOrig.Keys | Where-Object { -not $mOver.Contains($_) -or (($mOrig[$_] -join "`n") -ne ($mOver[$_] -join "`n")) })
if (($diffOver -join '|') -ne $edited) { Fail "ban ghi de khac ban goc o: $($diffOver -join '; ') (chi duoc khac o fromObjTable 5 tham so)" }
else { Write-Output "javap: ban ghi de == ban goc o $($mOrig.Count - 1) thanh vien, chi khac fromObjTable(String, TmdObjTable1c, int, int, int)" }

$opsOrig = @(Get-Ops $mOrig[$edited])
$opsOver = @(Get-Ops $mOver[$edited])
$i = 0
$inserted = New-Object System.Collections.Generic.List[string]
foreach ($op in $opsOver) {
  if ($i -lt $opsOrig.Count -and $op -eq $opsOrig[$i]) { $i++ } else { $inserted.Add($op) }
}
if ($i -ne $opsOrig.Count) { Fail "fromObjTable: day lenh goc khong con la day con cua ban ghi de (khop $i/$($opsOrig.Count))" }
else {
  $calls = @($inserted | Where-Object { $_ -match '//' })
  $bad = @($calls | Where-Object { $_ -notmatch 'legend/game/tmd/PnConfig\.cornerFlags' })
  if ($bad.Count) { Fail "lenh chen them goi ngoai PnConfig: $($bad -join '; ')" }
  Write-Output "javap: fromObjTable giu nguyen $($opsOrig.Count) lenh goc theo thu tu, chen them $($inserted.Count) lenh: $($inserted -join ' | ')"
}
try { & git --no-pager diff --no-index --stat -- $origSrc (Join-Path $here 'src\legend\game\tmd\TmdObjLoader.java') } catch { }

# ---------- (b) không cần GL ----------
$test = Join-Path $root 'out\sc_charfx_test'
if (Test-Path $test) { Remove-Item $test -Recurse -Force }
New-Item -ItemType Directory -Force $test | Out-Null
$tsrc = Get-ChildItem (Join-Path $here 'test') -Recurse -Filter *.java | ForEach-Object { $_.FullName }
& $javac -encoding UTF-8 --release 25 -nowarn -implicit:none -cp "$cls;$cp" -d $test $tsrc
if ($LASTEXITCODE) { throw 'javac loi (test)' }
$files = Join-Path $Game 'files'
$work = Join-Path $root 'work\upscale\sc_charfx_check'
New-Item -ItemType Directory -Force $work | Out-Null

function Invoke-Dump([string]$name, [string]$prefix, [string[]]$props) {
  $bin = Join-Path $work "$name.bin"
  if (Test-Path $bin) { Remove-Item $bin -Force }
  $a = @($props) + @('-cp', "$test;$prefix$cp", 'scvi.pncheck.PnCheck', 'dump', $bin, $files)
  & $java @a | Out-Host  # không để đầu ra của java lẫn vào giá trị trả về của hàm
  if ($LASTEXITCODE) { Fail "PnCheck dump $name" }
  return $bin
}
function Invoke-PnCheck([string[]]$a, [string]$what) {
  & $java -cp "$test;$cls;$cp" scvi.pncheck.PnCheck @a
  if ($LASTEXITCODE) { Fail $what }
}
$orig = Invoke-Dump 'orig' '' @()
$off = Invoke-Dump 'off' "$outJar;" @()
$pn0 = Invoke-Dump 'pn0' "$outJar;" @('-Dscvi.pn=0')
$pn4 = Invoke-Dump 'pn4' "$outJar;" @('-Dscvi.pn=4')
$pn1 = Invoke-Dump 'pn1' "$outJar;" @('-Dscvi.pn=1')
$pn2s5 = Invoke-Dump 'pn2s5' "$outJar;" @('-Dscvi.pn=2', '-Dscvi.pnStrength8=5')
Invoke-PnCheck @('same', $orig, $off) 'scvi.pn khong dat: du lieu dinh khac ban goc'
Invoke-PnCheck @('same', $orig, $pn0) 'scvi.pn=0: du lieu dinh khac ban goc'
Write-Output 'PN muc 4, do manh 8/8:'
Invoke-PnCheck @('pn', $orig, $pn4, '4', '8') 'scvi.pn=4'
Write-Output 'PN scvi.pn=1 (kep ve muc 2):'
Invoke-PnCheck @('pn', $orig, $pn1, '2', '8') 'scvi.pn=1'
Write-Output 'PN muc 2, do manh 5/8:'
Invoke-PnCheck @('pn', $orig, $pn2s5, '2', '5') 'scvi.pn=2 scvi.pnStrength8=5'
# Bộ kiểm phải bắt được lỗi: "same" phải báo khác khi có PN; "pn" phải bắt 9 lỗi giả (PnCheck selftest)
& $java -cp "$test;$cls;$cp" scvi.pncheck.PnCheck same $orig $pn4 | Out-Null
if ($LASTEXITCODE -ne 1) { Fail 'tu kiem: PnCheck same khong bao khac giua ban goc va ban PN' } else { Write-Output 'tu kiem: PnCheck same bao khac giua ban goc va ban PN (dung)' }
Invoke-PnCheck @('selftest', $orig, $pn4) 'tu kiem PnCheck pn'

if ($fail) { Write-Output "KHONG DAT: $fail loi"; exit 1 }
Write-Output "DAT: $outJar (javap + du lieu dinh that; dump o $work)"
exit 0
