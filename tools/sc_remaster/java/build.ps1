<#
build.ps1 — bộ kiểm ĐỘC LẬP cho runtime "Mô hình HD" (gói R1: TmdObjLoader ghi đè + legend.scvi.remaster trong out/sc-vi.jar).
Viết từ tools/sc_remaster/SPEC.md (LRM spec 1), coi R1 là hộp đen (không đọc mã sc-vi/src/legend/scvi/remaster); chỉ gọi
TmdObjLoader.fromModel của jar trong JVM thử (GameEngine giả + CaptureApi, không mở game).

Cách gọi (từ gốc repo D:\LOD-SC):
  powershell -ExecutionPolicy Bypass -File tools/sc_remaster/java/build.ps1 [-Game game] [-Jar out/sc-vi.jar] -Check
             [-Mock] [-Full] [-NoGl] [-Jobs N] [-Fuzz N]
    -Game  thư mục bản build SC (tương đối theo gốc repo hoặc tuyệt đối), mặc định "game"; chỉ ĐỌC game/files (và game/vi/files)
    -Jar   jar sc-vi cần kiểm, mặc định out/sc-vi.jar (bản R1 dựng bằng tools/build_sc_vi.ps1)
    -Check chạy kiểm (không có -Check: chỉ dịch lớp thử vào out/sc_remaster_test)
    -Mock  thay runtime sc-vi bằng MockRuntime (kiểm chính bộ kiểm khi chưa có R1); (a) và các mục cần ATLAS: NOT RUN
    -Full  mọi mô hình trường chạy đủ UvAdjust ô 0 / NONE / PNG + tên WmapEntityModel + tên bị loại (mặc định: 1/4, 1/10, 1/25)
    -NoGl  không tạo ngữ cảnh OpenGL ẩn (khi đó (f) NOT RUN; FULL nạp atlas bằng lệnh GL trực tiếp)
    -Jobs  số JVM con chạy song song (mặc định min(4, nhân/2)); -Fuzz số đột biến (mặc định 2000; < 2000 -> (e) NOT RUN, exit 1)
    -Only  chỉ chạy một số mục (vd 'f,g'; để phát triển — mục khác NOT RUN nên exit 1)
  Exit 0 = mọi mục đạt; 1 = có lỗi (in từng lỗi).
  Khoá chạy: work\upscale\sc_remaster_check\run.lock (PID). Lần chạy thứ hai cùng gốc repo khi lần đầu còn sống bị từ chối
  (hai lần chạy dùng chung out\sc_remaster_test và thư mục work, sẽ xoá dữ liệu của nhau); muốn chạy song song thì chép
  tools\sc_remaster\{java,spec} sang một gốc khác (dưới work\upscale\sc_remaster_*, git bỏ qua) và đặt SC_ROOT.
  Giới hạn: java.exe / javac.exe trên Windows đọc tham số dòng lệnh theo bảng mã ANSI của hệ thống (sun.jnu.encoding, máy này
  Cp1252) nên đường dẫn có ký tự ngoài bảng mã đó (vd tiếng Việt có dấu) bị đổi thành '?'. Script dừng ngay với thông báo rõ
  nếu gốc repo / -Game / -Jar / SC_ROOT có ký tự như vậy (đặt repo ở đường dẫn ASCII, hoặc bật "Beta: Use Unicode UTF-8").

Các mục:
  (a) javap: dịch TmdObjLoader GỐC từ clone Severed-Chains (đúng commit affcef0, tệp chưa sửa) -> out/sc_remaster_orig;
      bản gốc vừa dịch == lớp trong jar game (mọi thành viên); bản trong sc-vi.jar == bản gốc ở mọi thành viên trừ
      fromModel(String, Model124, int, int); trong fromModel dãy lệnh gốc (bỏ số khe biến, đích nhảy, số hằng #n) là dãy con của
      dãy lệnh mới và mọi lệnh invoke* chèn thêm chỉ gọi legend/scvi/remaster/*; sc-vi.jar không có lớp legend/game/tmd nào
      khác TmdObjLoader. Tự kiểm bộ gác: 3 bản sửa giả của nguồn gốc (gọi lớp lạ trong fromModel, sửa fromObjTable -> phải
      bị bắt; chỉ gọi legend.scvi.remaster.Probe trong fromModel -> phải qua).
  (b)-(g) RemasterCheck.java (xem docstring): same / identity / khoá / fuzz / FaceHash + sample_cube / tự kiểm.
Dữ liệu suy ra từ đĩa (file identity, dump, log JVM con) ghi vào work/upscale/sc_remaster_check (git bỏ qua); cây tổng hợp
sample_cube dựng lại bằng tools/sc_remaster/spec/synth_cube.py (write_out, không ghi đè file spec).
Nguồn thử: tools/sc_remaster/java/test/{scvi/remastercheck/*.java, stub/legend/core/GameEngine.java}; javac --release 25 của
<Game>\jdk25, classpath = lod-game-affcef0...jar + <Game>\libs\*. Không đóng gói gì vào sc-vi.jar.
#>
param([string]$Game = 'game', [string]$Jar = '', [switch]$Check, [switch]$Mock, [switch]$Full, [switch]$NoGl, [int]$Jobs = 0, [int]$Fuzz = 2000, [string[]]$Only = @())
$ErrorActionPreference = 'Stop'
# -Only f,g (khong nhay) la mang trong PowerShell; [string] se noi bang dau cach -> 'f g' -> moi muc NOT RUN
$Only = (@($Only) | ForEach-Object { $_ -split '[,\s]+' } | Where-Object { $_ }) -join ','
$t0 = Get-Date
# khoa chay (xem duoi): chi tra khoa do chinh lan chay nay giu; loi bat ky (throw) -> tra khoa roi dung nhu cu (exit 1)
$script:lockFile = $null
function Release-Lock { if ($script:lockFile -and (Test-Path $script:lockFile)) { Remove-Item $script:lockFile -Force -ErrorAction SilentlyContinue }; $script:lockFile = $null }
trap { Release-Lock; break }
$here = $PSScriptRoot
$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $here))
if (-not [System.IO.Path]::IsPathRooted($Game)) { $Game = Join-Path $root $Game }
if (-not $Jar) { $Jar = Join-Path $root 'out\sc-vi.jar' }
elseif (-not [System.IO.Path]::IsPathRooted($Jar)) { $Jar = Join-Path $root $Jar }
$jdk = Join-Path $Game 'jdk25\bin'
$javac = Join-Path $jdk 'javac.exe'
$java = Join-Path $jdk 'java.exe'
$jartool = Join-Path $jdk 'jar.exe'
$javap = Join-Path $jdk 'javap.exe'
$commit = 'affcef0cba71819515fdf05521c1fedb1d7a92f0'
$work = Join-Path $root 'work\upscale\sc_remaster_check'
$spec = Join-Path $root 'tools\sc_remaster\spec'
$scRoot = if ($env:SC_ROOT) { $env:SC_ROOT } else { Join-Path $root 'Severed-Chains' }

# java/javac/javap nhận tham số theo bảng mã ANSI (GetACP): ký tự ngoài bảng mã -> '?' -> JVM con không thấy tệp, lỗi khó hiểu.
$ansi = [System.Text.Encoding]::Default
try {
  $acp = [int](Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Nls\CodePage' -ErrorAction Stop).ACP
  $ansi = [System.Text.Encoding]::GetEncoding($acp)
} catch { }
foreach ($p in @($root, $Game, $Jar, $scRoot)) {
  if ($ansi.GetString($ansi.GetBytes($p)) -ne $p) {
    throw "duong dan '$p' co ky tu ngoai bang ma ANSI $($ansi.WebName) cua he thong: java.exe se doi chung thanh '?'. Dat repo / game o duong dan ASCII (hoac bat 'Beta: Use Unicode UTF-8')."
  }
}

# Khoá chạy: hai lần chạy cùng gốc repo dùng chung out\sc_remaster_test, out\sc_remaster_orig|guard và work\...\sc_remaster_check
# (lần sau xoá lớp thử / thư mục điều kiện của lần trước -> kết quả sai). Tệp khoá ghi PID; PID còn sống (khác tiến trình này) -> dừng.
New-Item -ItemType Directory -Force $work | Out-Null
$lf = Join-Path $work 'run.lock'
if (Test-Path $lf) {
  $old = 0
  try { $old = [int]((Get-Content $lf -TotalCount 1) -as [int]) } catch { $old = 0 }
  if ($old -gt 0 -and $old -ne $PID -and (Get-Process -Id $old -ErrorAction SilentlyContinue)) {
    throw "dang co mot lan chay khac (PID $old, $lf). Cho no xong (hoac xoa tep khoa neu PID do khong phai lan chay nay), hoac chay tu ban sao rieng cua tools\sc_remaster (goc repo khac)."
  }
}
Set-Content -Path $lf -Value $PID -Encoding Ascii
$script:lockFile = $lf

$gameJar = Get-ChildItem $Game -Filter 'lod-game-*.jar' | Where-Object { $_.Name -notmatch '-sources' } | Select-Object -First 1
if (-not $gameJar) { throw "khong thay lod-game-*.jar trong $Game" }
if ($gameJar.Name -notlike "*$commit*") { throw "ban build SC $($gameJar.Name) khac commit affcef0 ma TmdObjLoader ghi de duoc chep tu do" }
$cp = "$($gameJar.FullName);$Game\libs\*"

# ---------- dịch lớp thử ----------
$test = Join-Path $root 'out\sc_remaster_test'
if (Test-Path $test) { Remove-Item $test -Recurse -Force }
New-Item -ItemType Directory -Force $test | Out-Null
$tsrc = Get-ChildItem (Join-Path $here 'test') -Recurse -Filter *.java | ForEach-Object { $_.FullName }
& $javac -encoding UTF-8 --release 25 -nowarn -cp $cp -d $test $tsrc
if ($LASTEXITCODE) { throw 'javac loi (test)' }
Write-Output "Da dich $($tsrc.Count) tep thu -> $test"
if (-not $Check) { Release-Lock; Write-Output 'DAT (chua kiem; them -Check)'; exit 0 }

$fail = 0
function Fail([string]$msg) { Write-Output "LOI: $msg"; $script:fail++ }

# ---------- (a) javap ----------
function Get-Members([string]$classPath) {
  $text = & $javap -c -p -constants -cp $classPath legend.game.tmd.TmdObjLoader
  if ($LASTEXITCODE) { throw "javap loi: $classPath" }
  $members = [ordered]@{}
  $key = $null
  foreach ($line in $text) {
    if ($line -match '^\S.*\bclass legend\.game\.tmd\.TmdObjLoader\b') {
      # khai báo lớp (modifier, extends, implements) cũng phải trùng bản gốc
      $members['<class>'] = New-Object System.Collections.Generic.List[string]
      $members['<class>'].Add($line.Trim())
      $key = $null
    } elseif ($line -match '^  \S') {
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
$edited = 'public static void fromModel(java.lang.String, legend.game.types.Model124, int, int);'
# trả về danh sách lỗi của bộ gác cho một bản ghi đè (members) so với bản gốc
function Test-Guard($mOrig, $mOver, [string]$what) {
  $errs = New-Object System.Collections.Generic.List[string]
  if (($mOrig.Keys -join '|') -ne ($mOver.Keys -join '|')) { $errs.Add("$($what): danh sach thanh vien khac ban goc") }
  $diff = @($mOrig.Keys | Where-Object { -not $mOver.Contains($_) -or (($mOrig[$_] -join "`n") -ne ($mOver[$_] -join "`n")) })
  $other = @($diff | Where-Object { $_ -ne $edited })
  if ($other.Count) { $errs.Add("$($what): khac ban goc o thanh vien khac fromModel: $($other -join '; ')") }
  if ($mOver.Contains($edited)) {
    $opsOrig = @(Get-Ops $mOrig[$edited])
    $opsOver = @(Get-Ops $mOver[$edited])
    $i = 0
    $inserted = New-Object System.Collections.Generic.List[string]
    foreach ($op in $opsOver) {
      if ($i -lt $opsOrig.Count -and $op -eq $opsOrig[$i]) { $i++ } else { $inserted.Add($op) }
    }
    if ($i -ne $opsOrig.Count) { $errs.Add("$($what): fromModel: day lenh goc khong con la day con (khop $i/$($opsOrig.Count))") }
    $bad = @($inserted | Where-Object { $_ -match '^invoke' -and $_ -notmatch 'legend/scvi/remaster/' })
    if ($bad.Count) { $errs.Add("$($what): fromModel goi them ngoai legend/scvi/remaster: $($bad -join ' | ')") }
    $script:lastInserted = $inserted
  } else { $errs.Add("$($what): khong co fromModel(String, Model124, int, int)") }
  return ,$errs
}

$origSrc = Join-Path $scRoot 'src\main\java\legend\game\tmd\TmdObjLoader.java'
$aState = 'PASS'
if ($Mock) {
  $aState = 'NOT RUN (-Mock: khong kiem sc-vi.jar)'
} elseif (-not (Test-Path $origSrc)) {
  Fail "(a) khong co $origSrc (can clone Severed-Chains dung commit affcef0; SC_ROOT)"; $aState = 'FAIL'
} else {
  $head = (& git -C $scRoot rev-parse HEAD).Trim()
  if ($head -ne $commit) { Fail "(a) Severed-Chains HEAD $head khac $commit"; $aState = 'FAIL' }
  & git -C $scRoot diff --quiet HEAD -- 'src/main/java/legend/game/tmd/TmdObjLoader.java'
  if ($LASTEXITCODE) { Fail '(a) TmdObjLoader.java trong Severed-Chains da bi sua so voi HEAD'; $aState = 'FAIL' }

  $origCls = Join-Path $root 'out\sc_remaster_orig'
  if (Test-Path $origCls) { Remove-Item $origCls -Recurse -Force }
  New-Item -ItemType Directory -Force $origCls | Out-Null
  & $javac -encoding UTF-8 --release 25 -nowarn -implicit:none -cp $cp -d $origCls $origSrc
  if ($LASTEXITCODE) { throw 'javac loi (TmdObjLoader goc)' }
  $mOrig = Get-Members $origCls
  $mShip = Get-Members $gameJar.FullName
  $diffShip = @($mOrig.Keys | Where-Object { -not $mShip.Contains($_) -or (($mOrig[$_] -join "`n") -ne ($mShip[$_] -join "`n")) })
  if ((($mOrig.Keys -join '|') -ne ($mShip.Keys -join '|')) -or $diffShip.Count) { Fail "(a) TmdObjLoader goc vua dich khac lop trong jar game: $($diffShip -join '; ')"; $aState = 'FAIL' }
  else { Write-Output "(a) javap: TmdObjLoader goc (Severed-Chains affcef0, javac 25) == lop trong $($gameJar.Name): $($mOrig.Count - 1) thanh vien + khai bao lop" }

  # tự kiểm bộ gác: 3 bản sửa giả của nguồn gốc
  $selfDir = Join-Path $root 'out\sc_remaster_guard'
  if (Test-Path $selfDir) { Remove-Item $selfDir -Recurse -Force }
  $src0 = [System.IO.File]::ReadAllText($origSrc)
  $anchorModel = 'public static void fromModel(final String name, final Model124 model, final int textureWidth, final int textureHeight) {'
  $anchorTable = 'public static MeshObj fromObjTable(final String name, final TmdObjTable1c objTable, final int specialFlags, final int textureWidth, final int textureHeight) {'
  $anchorClass = 'public final class TmdObjLoader {'
  if (-not $src0.Contains($anchorModel) -or -not $src0.Contains($anchorTable) -or -not $src0.Contains($anchorClass)) { throw 'khong thay diem neo trong TmdObjLoader.java goc' }
  $probe = "package legend.scvi.remaster;`npublic final class Probe { private Probe() { } public static Object find(final Object o) { return null; } }`n"
  $variants = @(
    @{ n = 'good'; s = $src0.Replace($anchorModel, $anchorModel + "`n    if(legend.scvi.remaster.Probe.find(model) != null) { return; }"); ok = $true },
    @{ n = 'foreign'; s = $src0.Replace($anchorModel, $anchorModel + "`n    System.identityHashCode(model);"); ok = $false },
    @{ n = 'other'; s = $src0.Replace($anchorTable, $anchorTable + "`n    legend.scvi.remaster.Probe.find(objTable);"); ok = $false },
    @{ n = 'iface'; s = $src0.Replace($anchorClass, 'public final class TmdObjLoader implements java.io.Serializable {'); ok = $false }
  )
  foreach ($v in $variants) {
    $d = Join-Path $selfDir $v.n
    $sd = Join-Path $d 'src'
    New-Item -ItemType Directory -Force (Join-Path $sd 'legend\game\tmd'), (Join-Path $sd 'legend\scvi\remaster'), (Join-Path $d 'cls') | Out-Null
    [System.IO.File]::WriteAllText((Join-Path $sd 'legend\game\tmd\TmdObjLoader.java'), $v.s)
    [System.IO.File]::WriteAllText((Join-Path $sd 'legend\scvi\remaster\Probe.java'), $probe)
    & $javac -encoding UTF-8 --release 25 -nowarn -implicit:none -cp $cp -d (Join-Path $d 'cls') (Join-Path $sd 'legend\game\tmd\TmdObjLoader.java') (Join-Path $sd 'legend\scvi\remaster\Probe.java')
    if ($LASTEXITCODE) { throw "javac loi (tu kiem bo gac $($v.n))" }
    $e = Test-Guard $mOrig (Get-Members (Join-Path $d 'cls')) $v.n
    if ($v.ok -and $e.Count) { Fail "(a) tu kiem: ban sua hop le '$($v.n)' bi bo gac tu choi: $($e -join '; ')"; $aState = 'FAIL' }
    elseif (-not $v.ok -and -not $e.Count) { Fail "(a) tu kiem: ban sua sai '$($v.n)' KHONG bi bo gac bat"; $aState = 'FAIL' }
  }
  Write-Output '(a) tu kiem bo gac: ban goi legend.scvi.remaster trong fromModel qua; goi System trong fromModel / sua fromObjTable / them implements bi bat'

  if (-not (Test-Path $Jar)) { Fail "(a) khong co $Jar"; $aState = 'FAIL' }
  else {
    $entries = @(& $jartool tf $Jar)
    $tmd = @($entries | Where-Object { $_ -like 'legend/game/tmd/*' -and $_ -notlike '*/' })
    if (-not ($tmd -contains 'legend/game/tmd/TmdObjLoader.class')) {
      Fail "(a) $Jar khong co legend/game/tmd/TmdObjLoader.class (chua co ban ghi de cua R1)"; $aState = 'FAIL'
    } else {
      $others = @($tmd | Where-Object { $_ -ne 'legend/game/tmd/TmdObjLoader.class' })
      if ($others.Count) { Fail "(a) sc-vi.jar co lop legend/game/tmd khac: $($others -join ', ')"; $aState = 'FAIL' }
      $rem = @($entries | Where-Object { $_ -like 'legend/scvi/remaster/*.class' })
      Write-Output "(a) sc-vi.jar: TmdObjLoader + $($rem.Count) lop legend/scvi/remaster"
      $e = Test-Guard $mOrig (Get-Members $Jar) 'sc-vi.jar'
      if ($e.Count) { foreach ($x in $e) { Fail "(a) $x" }; $aState = 'FAIL' }
      else { Write-Output "(a) javap: ban ghi de == ban goc o khai bao lop + $($mOrig.Count - 2) thanh vien; fromModel giu nguyen day lenh goc, chen $($script:lastInserted.Count) lenh (invoke chi legend/scvi/remaster)" }
    }
  }
}

# ---------- cây tổng hợp sample_cube (không phải dữ liệu Sony) ----------
$synth = Join-Path $work 'synth'
New-Item -ItemType Directory -Force $work | Out-Null
$env:PYTHONIOENCODING = 'utf-8'
$py = "import sys; sys.path.insert(0, r'$spec'); import synth_cube as S; S.write_out(S.build(), r'$synth')"
& python -c $py
if ($LASTEXITCODE) { Fail 'khong dung duoc cay tong hop sample_cube (python synth_cube.write_out)' }

# ---------- (b)-(g) ----------
$jarArg = if ($Mock) { '-' } else { $Jar }
$a = @('-Xmx1536m', "-XX:ErrorFile=$work\hs_err_%p.log", "-XX:ReplayDataFile=$work\replay_%p.log", '--enable-native-access=ALL-UNNAMED', '-Dfile.encoding=UTF-8', '-Dstdout.encoding=UTF-8', '-Dlog4j2.level=warn',
  '-cp', "$test;$cp", 'scvi.remastercheck.RemasterCheck', 'all', '--game', $Game, '--work', $work, '--spec', $spec, '--synth', $synth,
  '--test', $test, '--cp', $cp, '--java', $java, '--jar', $jarArg, '--fuzz', "$Fuzz")
if ($Mock) { $a += '--mock' }
if ($Full) { $a += '--full' }
if ($NoGl) { $a += '--nogl' }
if ($Jobs -gt 0) { $a += @('--jobs', "$Jobs") }
if ($Only) { $a += @('--only', $Only) }
Push-Location $work  # tệp sự cố JVM (nếu có) nằm trong work, không rơi vào thư mục hiện hành
try { & $java @a | Out-Host; $rc = $LASTEXITCODE } finally { Pop-Location }
if ($rc) { Fail "RemasterCheck (b)-(g) rc=$rc" }

Write-Output "(a): $aState"
$secs = [int]((Get-Date) - $t0).TotalSeconds
Release-Lock
if ($fail) { Write-Output "KHONG DAT: $fail loi ($secs s)"; exit 1 }
Write-Output "DAT ($secs s; du lieu o $work)"
exit 0
