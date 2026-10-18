<#
run_tests.ps1 - kiểm thử tự động công cụ "Tạo mô hình HD" (tools/remaster_tool) bằng worker giả, Real-ESRGAN giả,
Blender giả và máy chủ HTTP cục bộ. KHÔNG tải Blender/Real-ESRGAN thật, không đụng thư mục game thật (chỉ đọc
game\jdk25 và game\libs\gson-*.jar để dựng + chạy jar).

Cách gọi:
  powershell -ExecutionPolicy Bypass -File tools/remaster_tool/test/run_tests.ps1 [-Game game] [-Keep]
    -Game  bản build SC có jdk25 + libs (mặc định "game")
    -Keep  giữ thư mục thử out\remaster_tool_test (mặc định cũng giữ để xem log; lần chạy sau xoá đi làm lại)
Cần: python (3.x) trong PATH, PowerShell 5.1.
Kết quả: bảng PASS/FAIL theo tiêu chí T1 + mục bổ sung; log từng lần chạy CLI ở out\remaster_tool_test\logs\.
Exit 0 = mọi mục PASS, 1 = có mục FAIL.

Tiêu chí (kế hoạch T1):
  1  không có kết nối mạng trước khi đồng ý (CLI thiếu --yes-download, xem trước giao diện, URL http thiếu cờ kiểm thử,
     chuyển hướng sang máy ngoài danh sách)
  2  SHA-256 sai bị từ chối và file bị xoá (thử lại đúng 1 lần)
  3  tải dở được tải tiếp (Range + If-Range, 206)
  4  zip-slip bị từ chối (.., \, /tuyệt đối, ổ đĩa)
  5  file ngoài danh sách cho phép của Real-ESRGAN không được giải
  6  thư mục game có dấu tiếng Việt chạy được (staging ASCII cho Real-ESRGAN)
  7  Huỷ diệt fake_worker và tiến trình con; lần sau --resume chạy tiếp
  8  nội dung remaster.properties đúng từng byte
  9  Gỡ hết không còn mục remaster* (junction bên trong không làm mất dữ liệu ngoài)
  10 jar giống hệt SHA-256 qua hai lần dựng
  Bổ sung: chuyển hướng hợp lệ, xuất gói Android (+ gói sai bị xoá), chép từ thư mục cũ (+ dữ liệu hỏng bị từ chối),
  Real-ESRGAN treo (quá giờ -> diệt cây, chạy --no-ai), zip tự chọn không cần mạng, dòng @@ sai dạng (x6), .installed.json
  hỏng vẫn cài lại được (x7), textures lạ đọc như runtime (x8), Xoá mô hình tắt công tắc (x9), staging là junction bị bỏ
  qua và không xoá dữ liệu nơi khác (x10), pincheck.py --selftest + --offline (x11), worker thoát để lại con mồ côi
  giữ stdout -> công cụ diệt con và kết thúc (x12).
#>
param([string]$Game = 'game', [switch]$Keep)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$toolDir = Split-Path -Parent $here
$root = Split-Path -Parent (Split-Path -Parent $toolDir)
if (-not [System.IO.Path]::IsPathRooted($Game)) { $Game = Join-Path $root $Game }
$java = Join-Path $Game 'jdk25\bin\java.exe'
$gson = Get-ChildItem (Join-Path $Game 'libs') -Filter 'gson-*.jar' | Sort-Object Name | Select-Object -First 1
$py = (Get-Command python -ErrorAction Stop).Source
$T = Join-Path $root 'out\remaster_tool_test'
$utf8 = New-Object System.Text.UTF8Encoding $false

# dọn lần trước: mọi tiến trình có dòng lệnh chứa thư mục thử (worker giả, con, máy chủ, java) + ping của ESRGAN giả
# (+ con ngu cua fake_worker: dong lenh khong chua thu muc thu, nhan dang bang doan ma "while True: time.sleep(0.5)")
Get-CimInstance Win32_Process | Where-Object {
  ($_.CommandLine -and $_.CommandLine -like "*remaster_tool_test*") -or ($_.Name -eq 'ping.exe' -and $_.CommandLine -like '*-n 777*') -or
  ($_.Name -eq 'python.exe' -and $_.CommandLine -like '*while True: time.sleep(0.5)*')
} | ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }
Start-Sleep -Milliseconds 500
if (Test-Path $T) { cmd /c "rmdir /s /q `"$T`"" | Out-Null }
if (Test-Path $T) { Remove-Item $T -Recurse -Force }
New-Item -ItemType Directory -Force $T, (Join-Path $T 'logs') | Out-Null

$results = New-Object System.Collections.ArrayList
function Check([string]$id, [bool]$ok, [string]$detail) {
  [void]$results.Add([pscustomobject]@{ Id = $id; Result = $(if ($ok) { 'PASS' } else { 'FAIL' }); Detail = $detail })
  Write-Output ("{0,-5} {1,-4} {2}" -f $id, $(if ($ok) { 'PASS' } else { 'FAIL' }), $detail)
}

# quy tac argv cua Windows (CommandLineToArgvW / launcher Java): \ truoc " va \ cuoi phai nhan doi trong dau nhay
function Quote-Arg([string]$a) {
  if ($a -ne '' -and $a -notmatch '[\s"]') { return $a }
  $s = $a -replace '(\\*)"', '$1$1\"'
  $s = $s -replace '(\\+)$', '$1$1'
  return '"' + $s + '"'
}

$staging = Join-Path $T 'staging\realesrgan'
$script:jar = $null
function Invoke-Tool {
  param([string]$Cwd, [string[]]$ToolArgs, [hashtable]$EnvVars = @{}, [string[]]$Props = @(), [string]$Name,
        [switch]$NoTestHosts, [switch]$NoCli, [int]$TimeoutSec = 300)
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = $java
  $jp = @('-Dstdout.encoding=UTF-8', '-Dstderr.encoding=UTF-8', "-Dlodsc.remaster.staging=$staging",
          '-Dlodsc.remaster.selftestTimeout=30', '-Dlodsc.remaster.verifyTimeout=60')
  if (-not $NoTestHosts) { $jp += '-Dlodsc.remaster.testHosts=127.0.0.1' }
  $all = $jp + $Props + @('-cp', "$($script:jar);$($gson.FullName)", 'vn.lodsc.remaster.Tool')
  if (-not $NoCli) { $all += '--cli' }
  $all += $ToolArgs
  $psi.Arguments = ($all | ForEach-Object { Quote-Arg $_ }) -join ' '
  $psi.WorkingDirectory = $Cwd
  $psi.UseShellExecute = $false
  $psi.CreateNoWindow = $true
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true
  $psi.StandardOutputEncoding = $utf8
  $psi.StandardErrorEncoding = $utf8
  $psi.EnvironmentVariables['FAKE_WORKER_SAMPLE'] = (Join-Path $T 'synth')
  foreach ($k in $EnvVars.Keys) { $psi.EnvironmentVariables[$k] = [string]$EnvVars[$k] }
  $p = [System.Diagnostics.Process]::Start($psi)
  $o = $p.StandardOutput.ReadToEndAsync()
  $e = $p.StandardError.ReadToEndAsync()
  if (-not $p.WaitForExit($TimeoutSec * 1000)) { $p.Kill(); throw "qua gio: $Name" }
  # khong dung WaitForExit() khong tham so: tien trinh con mo coi ke thua stdout cua java se lam no cho mai
  [void]$o.Wait(30000); [void]$e.Wait(30000)
  $out = $(if ($o.IsCompleted) { $o.Result } else { '<stdout java chua dong: con mo coi giu ong>' }) + $(if ($e.IsCompleted) { $e.Result } else { '' })
  [System.IO.File]::WriteAllText((Join-Path $T "logs\$Name.txt"), "exit $($p.ExitCode)`r`n$out", $utf8)
  return [pscustomobject]@{ Exit = $p.ExitCode; Out = $out }
}

function Http-Log {
  $f = Join-Path $T 'http.log'
  if (-not (Test-Path $f)) { return @() }
  return @([System.IO.File]::ReadAllLines($f, $utf8) | Where-Object { $_ } | ForEach-Object { $_ | ConvertFrom-Json })
}

function Read-Exact([string]$path) {
  if (-not (Test-Path -LiteralPath $path)) { return '<khong co file>' }
  return [System.Text.Encoding]::ASCII.GetString([System.IO.File]::ReadAllBytes($path))
}

function Last-Call([string]$gameDir) {
  $f = Join-Path $gameDir 'remaster_work\fake_calls.jsonl'
  if (-not (Test-Path -LiteralPath $f)) { return $null }
  $lines = @([System.IO.File]::ReadAllLines($f, $utf8) | Where-Object { $_ })
  return ($lines[-1] | ConvertFrom-Json)
}

function Arg-After($call, [string]$name) {
  $a = @($call.argv)
  for ($i = 0; $i -lt $a.Count - 1; $i++) { if ($a[$i] -eq $name) { return $a[$i + 1] } }
  return $null
}

$server = $null
try {
  # ---------------------------------------------------------------- 10: jar xác định
  $b1 = & powershell -ExecutionPolicy Bypass -File (Join-Path $toolDir 'build.ps1') -Game $Game -Out (Join-Path $T 'jar1\lodsc-remaster.jar')
  $b2 = & powershell -ExecutionPolicy Bypass -File (Join-Path $toolDir 'build.ps1') -Game $Game -Out (Join-Path $T 'jar2\lodsc-remaster.jar')
  $h1 = (Get-FileHash (Join-Path $T 'jar1\lodsc-remaster.jar') -Algorithm SHA256).Hash
  $h2 = (Get-FileHash (Join-Path $T 'jar2\lodsc-remaster.jar') -Algorithm SHA256).Hash
  Check '10' ($h1 -eq $h2) "jar SHA-256 lan 1 = lan 2 = $($h1.ToLower())"
  $script:jar = Join-Path $T 'jar1\lodsc-remaster.jar'

  # ---------------------------------------------------------------- dữ liệu giả + máy chủ
  & $py (Join-Path $root 'tools\sc_remaster\spec\synth_cube.py') --out (Join-Path $T 'synth') | Out-Null
  if ($LASTEXITCODE) { throw 'synth_cube.py loi' }
  $portFile = Join-Path $T 'port.txt'
  $server = Start-Process -FilePath $py -PassThru -WindowStyle Hidden -ArgumentList @('-I', "`"$here\http_server.py`"",
    '--root', "`"$T\srv`"", '--port-file', "`"$portFile`"", '--log', "`"$T\http.log`"",
    '--cut', '/cut/blender-5.2.2-windows-x64.zip:30000:2')
  for ($i = 0; $i -lt 100 -and -not (Test-Path $portFile); $i++) { Start-Sleep -Milliseconds 100 }
  $port = [int](Get-Content $portFile)
  & $py -I (Join-Path $here 'make_fakes.py') --out $T --port $port --python $py --fake-esrgan (Join-Path $here 'fake_esrgan.cmd') --fake-worker (Join-Path $here 'fake_worker.py') | Out-Null
  if ($LASTEXITCODE) { throw 'make_fakes.py loi' }
  $uniName = [System.IO.File]::ReadAllText((Join-Path $T 'unicode_name.txt'), $utf8)
  $gUni = Join-Path $T $uniName
  $gA = Join-Path $T 'game_ascii'
  $pinsOk = Join-Path $T 'pins_ok.json'
  $env1 = @{ FAKE_WORKER_JOBS = '6'; FAKE_WORKER_DELAY = '0.05' }

  # ---------------------------------------------------------------- 1: không mạng trước khi đồng ý
  $r = Invoke-Tool -Cwd $gA -Name '1a_no_consent' -ToolArgs @('--game', '.', '--pins', $pinsOk, '--scope', 'v1', '--texture', 'hd')
  $n = @(Http-Log).Count
  Check '1a' ($r.Exit -eq 3 -and $n -eq 0 -and $r.Out -match '--yes-download') "CLI khong --yes-download: exit $($r.Exit) (can 3), yeu cau HTTP = $n"
  $r = Invoke-Tool -Cwd $gA -Name '1b_render' -NoCli -ToolArgs @('--render-screens', (Join-Path $T 'screens'), '--game', '.', '--pins', $pinsOk) -Props @('-Djava.awt.headless=true')
  $pngs = @(Get-ChildItem (Join-Path $T 'screens') -Filter '*.png' -ErrorAction SilentlyContinue).Count
  $n = @(Http-Log).Count
  Check '1b' ($r.Exit -eq 0 -and $pngs -eq 6 -and $n -eq 0) "ve 6 man giao dien (khong cua so): exit $($r.Exit), $pngs PNG, yeu cau HTTP = $n"
  $r = Invoke-Tool -Cwd $gA -Name '1c_https_only' -NoTestHosts -ToolArgs @('--game', '.', '--pins', $pinsOk, '--yes-download', '--install-only', '--no-ai')
  $n = @(Http-Log).Count
  Check '1c' ($r.Exit -eq 1 -and $n -eq 0 -and $r.Out -match 'https') "URL http khi khong bat may kiem thu bi tu choi: exit $($r.Exit), yeu cau HTTP = $n"
  $gR = Join-Path $T 'game_redirect'
  $r = Invoke-Tool -Cwd $gR -Name '1d_redirect_bad' -ToolArgs @('--game', '.', '--pins', (Join-Path $T 'pins_redirect_bad.json'), '--yes-download', '--install-only', '--no-ai')
  $log = @(Http-Log)
  $n = $log.Count
  Check '1d' ($r.Exit -eq 1 -and $n -eq 1 -and $log[0].path -like '/redirect-bad/*' -and $r.Out -match 'evil\.invalid') "chuyen huong sang may ngoai danh sach bi tu choi truoc khi ket noi: exit $($r.Exit), yeu cau HTTP = $n"

  # ---------------------------------------------------------------- bổ sung: chuyển hướng hợp lệ
  $before = @(Http-Log).Count
  $r = Invoke-Tool -Cwd $gR -Name 'x_redirect_ok' -ToolArgs @('--game', '.', '--pins', (Join-Path $T 'pins_redirect.json'), '--yes-download', '--install-only', '--no-ai')
  $new = @(@(Http-Log) | Select-Object -Skip $before)
  $ok = $r.Exit -eq 0 -and $new.Count -eq 2 -and $new[0].status -eq 302 -and $new[1].status -eq 200 -and (Test-Path (Join-Path $gR 'remaster_tools\blender-5.2.2-windows-x64\.installed.json'))
  Check 'x1' $ok "chuyen huong cung may (302 -> 200) roi cai Blender gia: exit $($r.Exit)"

  # ---------------------------------------------------------------- 2: SHA-256 sai
  $before = @(Http-Log).Count
  $r = Invoke-Tool -Cwd $gA -Name '2_badsha' -ToolArgs @('--game', '.', '--pins', (Join-Path $T 'pins_badsha.json'), '--yes-download', '--install-only', '--no-ai')
  $new = @(@(Http-Log) | Select-Object -Skip $before)
  $left = @(Get-ChildItem (Join-Path $gA 'remaster_tools\dl') -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'blender*' }).Count
  $noInst = -not (Test-Path (Join-Path $gA 'remaster_tools\blender-5.2.2-windows-x64'))
  Check '2' ($r.Exit -eq 1 -and $r.Out -match 'SHA-256' -and $left -eq 0 -and $new.Count -eq 2 -and $noInst) "SHA sai: exit $($r.Exit), so lan tai = $($new.Count) (can 2), file con lai trong dl = $left, khong cai = $noInst"

  # ---------------------------------------------------------------- 3: tải tiếp
  $pinsCut = Join-Path $T 'pins_cut.json'
  $before = @(Http-Log).Count
  $r1 = Invoke-Tool -Cwd $gA -Name '3a_cut' -ToolArgs @('--game', '.', '--pins', $pinsCut, '--yes-download', '--install-only', '--no-ai')
  $part = Join-Path $gA 'remaster_tools\dl\blender-5.2.2-windows-x64.zip.part'
  $partSize = $(if (Test-Path $part) { (Get-Item $part).Length } else { -1 })
  $r2 = Invoke-Tool -Cwd $gA -Name '3b_resume' -ToolArgs @('--game', '.', '--pins', $pinsCut, '--yes-download', '--install-only', '--no-ai')
  $new = @(@(Http-Log) | Select-Object -Skip $before)
  $resumed = @($new | Where-Object { $_.range -eq "bytes=$partSize-" -and $_.status -eq 206 -and $_.if_range -and -not $_.cut }).Count
  $inst = Test-Path (Join-Path $gA 'remaster_tools\blender-5.2.2-windows-x64\.installed.json')
  $zipGone = -not (Test-Path (Join-Path $gA 'remaster_tools\dl\blender-5.2.2-windows-x64.zip'))
  Check '3' ($r1.Exit -eq 1 -and $partSize -eq 60000 -and $r2.Exit -eq 0 -and $resumed -eq 1 -and $inst -and $zipGone) "lan 1 bi cat: exit $($r1.Exit), .part = $partSize byte; lan 2: exit $($r2.Exit), Range bytes=$partSize- + If-Range -> 206: $resumed; da cai = $inst, zip da xoa = $zipGone"

  # ---------------------------------------------------------------- 4: zip-slip
  foreach ($v in @('dotdot', 'backslash', 'abs', 'drive')) {
    $gS = Join-Path $T "game_slip_$v"
    Copy-Item (Join-Path $T 'game_manual') $gS -Recurse
    $r = Invoke-Tool -Cwd $gS -Name "4_slip_$v" -ToolArgs @('--game', '.', '--pins', (Join-Path $T "pins_slip_$v.json"), '--yes-download', '--install-only', '--no-ai')
    $evil = @(Get-ChildItem $T -Recurse -Filter 'evil_slip*' -ErrorAction SilentlyContinue).Count + @(Get-ChildItem 'C:\' -Filter 'evil_slip*' -ErrorAction SilentlyContinue).Count
    $noDir = -not (Test-Path (Join-Path $gS 'remaster_tools\blender-5.2.2-windows-x64')) -and -not (Test-Path (Join-Path $gS 'remaster_tools\blender-5.2.2-windows-x64.tmp'))
    Check "4$v" ($r.Exit -eq 1 -and $evil -eq 0 -and $noDir -and $r.Out -match 'zip') "zip-slip ($v): exit $($r.Exit), file evil tao ra = $evil, khong de lai thu muc cai = $noDir"
  }

  # ---------------------------------------------------------------- 5: danh sách cho phép của Real-ESRGAN
  $r = Invoke-Tool -Cwd $gA -Name '5_esrgan' -ToolArgs @('--game', '.', '--pins', $pinsOk, '--yes-download', '--install-only', '--texture', 'hd')
  $ed = Join-Path $gA 'remaster_tools\realesrgan'
  $files = @(Get-ChildItem $ed -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName.Substring($ed.Length + 1).Replace('\', '/') } | Sort-Object)
  $want = @('.installed.json', 'models/realesrgan-x4plus-anime.bin', 'models/realesrgan-x4plus-anime.param', 'models/realesrgan-x4plus.bin',
            'models/realesrgan-x4plus.param', 'realesrgan-ncnn-vulkan.cmd', 'vcomp140.dll') | Sort-Object
  $st = Get-Content (Join-Path $gA 'remaster_tools\esrgan_staging.json') -Raw | ConvertFrom-Json
  $same = ($files -join '|') -eq ($want -join '|')
  Check '5' ($r.Exit -eq 0 -and $same -and $st.ai_ok -and $st.dir -eq $ed) "chi giai danh sach cho phep: exit $($r.Exit), file = [$($files -join ', ')]; staging = thu muc cong cu (ASCII), tu kiem = $($st.ai_ok)"

  # ---------------------------------------------------------------- 7: Huỷ diệt cây tiến trình, lần sau chạy tiếp
  $envC = @{ FAKE_WORKER_JOBS = '10'; FAKE_WORKER_DELAY = '0.4' }
  $r1 = Invoke-Tool -Cwd $gA -Name '7a_cancel' -EnvVars $envC -ToolArgs @('--game', '.', '--pins', $pinsOk, '--texture', 'hd', '--test-cancel-after', '3')
  $pids = @(Get-Content (Join-Path $gA 'remaster_work\fake_pids.txt') | Where-Object { $_ } | ForEach-Object { [int]$_ })
  Start-Sleep -Milliseconds 500
  $alive = @($pids | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue }).Count
  $c1 = Last-Call $gA
  $r2 = Invoke-Tool -Cwd $gA -Name '7b_resume' -EnvVars $envC -ToolArgs @('--game', '.', '--pins', $pinsOk, '--texture', 'hd')
  $c2 = Last-Call $gA
  $state = Get-Content (Join-Path $gA 'remaster_work\state.json') -Raw | ConvertFrom-Json
  $resumeFlag = @($c2.argv) -contains '--resume'
  $fresh1 = -not (@($c1.argv) -contains '--resume')
  $esr = Arg-After $c1 '--esrgan'
  $ok = $fresh1 -and $r1.Exit -eq 4 -and $pids.Count -eq 2 -and $alive -eq 0 -and $r2.Exit -eq 0 -and $resumeFlag -and $c2.resumed_from -ge 2 -and @($state.done).Count -eq 10 -and (Test-Path (Join-Path $gA 'remaster\index.tsv'))
  Check '7' $ok "lan dau khong --resume = $fresh1; huy: exit $($r1.Exit) (can 4), worker + con con song = $alive/$($pids.Count); lan sau: exit $($r2.Exit), --resume = $resumeFlag, tiep tu job $($c2.resumed_from), xong $(@($state.done).Count)/10; --esrgan = $esr"

  # ---------------------------------------------------------------- 8: remaster.properties đúng từng byte
  $props = Join-Path $gA 'remaster.properties'
  $r = Invoke-Tool -Cwd $gA -Name '8a_on' -ToolArgs @('--game', '.', '--pins', $pinsOk, '--toggle', 'on')
  $a1 = Read-Exact $props
  $r = Invoke-Tool -Cwd $gA -Name '8b_off' -ToolArgs @('--game', '.', '--pins', $pinsOk, '--toggle', 'off')
  $a2 = Read-Exact $props
  [System.IO.File]::WriteAllText($props, "enabled=false`ntextures=hd`nlog=true`n", $utf8)
  $r = Invoke-Tool -Cwd $gA -Name '8c_retail' -ToolArgs @('--game', '.', '--pins', $pinsOk, '--toggle', 'on', '--texture', 'retail')
  $a3 = Read-Exact $props
  $ok = $a1 -ceq "enabled=true`ntextures=hd`nlog=false`n" -and $a2 -ceq "enabled=false`ntextures=hd`nlog=false`n" -and $a3 -ceq "enabled=true`ntextures=retail`nlog=true`n"
  Check '8' $ok ("bat / tat / bat+retail (giu log=true): " + (($a1, $a2, $a3 | ForEach-Object { $_.Replace("`n", '\n') }) -join ' | '))

  # ---------------------------------------------------------------- bổ sung: gói Android
  $okZip = Join-Path $T 'export_ok.zip'
  $r1 = Invoke-Tool -Cwd $gA -Name 'x2a_export' -ToolArgs @('--game', '.', '--pins', $pinsOk, '--export-android', '--out', $okZip)
  $badZip = Join-Path $T 'export_bad.zip'
  $r2 = Invoke-Tool -Cwd $gA -Name 'x2b_export_bad' -EnvVars @{ FAKE_WORKER_BADZIP = '1' } -ToolArgs @('--game', '.', '--pins', $pinsOk, '--export-android', '--out', $badZip)
  Check 'x2' ($r1.Exit -eq 0 -and (Test-Path $okZip) -and $r2.Exit -eq 1 -and -not (Test-Path $badZip)) "xuat goi Android: exit $($r1.Exit); goi co muc la bi tu choi + xoa: exit $($r2.Exit), con file = $(Test-Path $badZip)"

  # ---------------------------------------------------------------- bổ sung: chép từ thư mục cũ
  $gN = Join-Path $T 'game_new'
  $r = Invoke-Tool -Cwd $gN -Name 'x3a_copy' -ToolArgs @('--game', '.', '--pins', $pinsOk, '--copy-from', $gA)
  $s = Invoke-Tool -Cwd $gN -Name 'x3a_status' -ToolArgs @('--game', '.', '--pins', $pinsOk, '--status')
  $ok = $r.Exit -eq 0 -and (Test-Path (Join-Path $gN 'remaster\index.tsv')) -and (Test-Path (Join-Path $gN 'remaster_tools\blender-5.2.2-windows-x64\.installed.json')) -and (Test-Path (Join-Path $gN 'remaster_tools\realesrgan\.installed.json')) -and (Test-Path (Join-Path $gN 'remaster_tools\esrgan_staging.json'))
  $gB = Join-Path $T 'game_bad'
  Copy-Item (Join-Path $gA 'remaster') (Join-Path $gB 'remaster') -Recurse
  $png = Get-ChildItem (Join-Path $gB 'remaster\textures') -Filter '*.png' | Select-Object -First 1
  $bytes = [System.IO.File]::ReadAllBytes($png.FullName); $bytes[$bytes.Length - 20] = $bytes[$bytes.Length - 20] -bxor 0xFF; [System.IO.File]::WriteAllBytes($png.FullName, $bytes)
  $gN2 = Join-Path $T 'game_new2'
  $r2 = Invoke-Tool -Cwd $gN2 -Name 'x3b_copy_bad' -ToolArgs @('--game', '.', '--pins', $pinsOk, '--copy-from', $gB)
  $ok2 = $r2.Exit -eq 1 -and -not (Test-Path (Join-Path $gN2 'remaster')) -and -not (Test-Path (Join-Path $gN2 'remaster.import')) -and $r2.Out -match 'SHA-1'
  Check 'x3' ($ok -and $ok2) "chep tu thu muc cu + kiem lai: exit $($r.Exit); nguon co PNG hong bi tu choi: exit $($r2.Exit)"

  # ---------------------------------------------------------------- bổ sung: Real-ESRGAN treo
  $gH = Join-Path $T 'game_hang'
  $r = Invoke-Tool -Cwd $gH -Name 'x4_hang' -EnvVars @{ FAKE_ESRGAN_MODE = 'hang' } -Props @('-Dlodsc.remaster.selftestTimeout=4') -ToolArgs @('--game', '.', '--pins', $pinsOk, '--yes-download', '--texture', 'hd')
  $stH = Get-Content (Join-Path $gH 'remaster_tools\esrgan_staging.json') -Raw | ConvertFrom-Json
  $cH = Last-Call $gH
  $ping = @(Get-CimInstance Win32_Process -Filter "Name='ping.exe'" | Where-Object { $_.CommandLine -like '*-n 777*' }).Count
  $ok = $r.Exit -eq 0 -and -not $stH.ai_ok -and (@($cH.argv) -contains '--no-ai') -and -not (@($cH.argv) -contains '--esrgan') -and $ping -eq 0
  Check 'x4' $ok "ESRGAN treo: qua gio -> diet cay (ping con song = $ping), ai_ok = $($stH.ai_ok), worker chay --no-ai: exit $($r.Exit)"

  # ---------------------------------------------------------------- bổ sung: zip tự chọn, không mạng
  $gM = Join-Path $T 'game_manual'
  $before = @(Http-Log).Count
  $src = Join-Path $T 'srv\blender-5.2.2-windows-x64.zip'
  $r = Invoke-Tool -Cwd $gM -Name 'x5_manual' -ToolArgs @('--game', '.', '--pins', $pinsOk, '--blender-zip', $src, '--install-only', '--no-ai')
  $n = @(Http-Log).Count - $before
  Check 'x5' ($r.Exit -eq 0 -and $n -eq 0 -and (Test-Path $src) -and (Test-Path (Join-Path $gM 'remaster_tools\blender-5.2.2-windows-x64\.installed.json'))) "cai tu zip tu chon: exit $($r.Exit), yeu cau HTTP = $n, giu file cua nguoi choi = $(Test-Path $src)"

  # ---------------------------------------------------------------- bổ sung: dòng @@ sai dạng không làm ngã công cụ
  $r = Invoke-Tool -Cwd $gR -Name 'x6_bad_lines' -EnvVars @{ FAKE_WORKER_BAD_LINES = '1'; FAKE_WORKER_JOBS = '2' } -ToolArgs @('--game', '.', '--pins', (Join-Path $T 'pins_redirect.json'), '--no-ai')
  $pids6 = @(Get-Content (Join-Path $gR 'remaster_work\fake_pids.txt') | Where-Object { $_ } | ForEach-Object { [int]$_ })
  $alive6 = @($pids6 | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue }).Count
  Check 'x6' ($r.Exit -eq 0 -and $r.Out -match 'xong 2, ' -and $alive6 -eq 0) "worker in dong @@P/@@E/@@DONE hong (minutes la chu, JSON sai): exit $($r.Exit) (can 0), tong ket dung = $($r.Out -match 'xong 2, '), tien trinh con song = $alive6"

  # ---------------------------------------------------------------- bổ sung: worker thoát để lại con mồ côi giữ stdout
  $sw12 = [System.Diagnostics.Stopwatch]::StartNew()
  $r = Invoke-Tool -Cwd $gR -Name 'x12_orphan' -TimeoutSec 90 -EnvVars @{ FAKE_WORKER_ORPHAN = '1'; FAKE_WORKER_JOBS = '2' } -ToolArgs @('--game', '.', '--pins', (Join-Path $T 'pins_redirect.json'), '--no-ai')
  $sec12 = [int]$sw12.Elapsed.TotalSeconds
  $pids12 = @(Get-Content (Join-Path $gR 'remaster_work\fake_pids.txt') | Where-Object { $_ } | ForEach-Object { [int]$_ })
  $alive12 = @($pids12 | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue }).Count
  Check 'x12' ($r.Exit -eq 0 -and $alive12 -eq 0 -and $sec12 -lt 60) "worker thoat, con mo coi giu stdout: exit $($r.Exit) sau $sec12 s (can < 60), tien trinh con song = $alive12"

  # ---------------------------------------------------------------- bổ sung: textures lạ đọc như runtime (retail)
  [System.IO.File]::WriteAllText((Join-Path $gR 'remaster.properties'), "enabled=TRUE`ntextures=foo`nlog=yes`n", $utf8)
  $r = Invoke-Tool -Cwd $gR -Name 'x8_toggle_parity' -ToolArgs @('--game', '.', '--pins', (Join-Path $T 'pins_redirect.json'), '--status')
  $want8 = 'B' + [char]0x1EAC + 'T, textures=retail'   # 'BAT' co dau: viet bang ma ky tu (file nay ASCII)
  $ok8 = $r.Exit -eq 0 -and $r.Out.Contains($want8)
  Check 'x8' $ok8 "remaster.properties enabled=TRUE textures=foo: cong cu doc nhu RemasterConfig (bat, retail) = $ok8"

  # ---------------------------------------------------------------- bổ sung: .installed.json hỏng không chặn cài lại
  $ijM = Join-Path $gM 'remaster_tools\blender-5.2.2-windows-x64\.installed.json'
  [System.IO.File]::WriteAllText($ijM, '{"tool": "blender", "zip_sha256": ', $utf8)
  $r = Invoke-Tool -Cwd $gM -Name 'x7_corrupt_installed' -ToolArgs @('--game', '.', '--pins', $pinsOk, '--yes-download', '--install-only', '--no-ai')
  $ijOk = $false
  try { $ijOk = ((Get-Content $ijM -Raw | ConvertFrom-Json).verified -eq $true) } catch { $ijOk = $false }
  Check 'x7' ($r.Exit -eq 0 -and $ijOk) ".installed.json hong -> --yes-download cai lai duoc: exit $($r.Exit) (can 0), .installed.json moi verified = $ijOk"

  # ---------------------------------------------------------------- bổ sung: pincheck tự kiểm + kiểm tĩnh pins.json thật
  $pc1 = & $py -I (Join-Path $toolDir 'pincheck.py') --selftest 2>&1
  $pc1x = $LASTEXITCODE
  $pc2 = & $py -I (Join-Path $toolDir 'pincheck.py') --offline 2>&1
  $pc2x = $LASTEXITCODE
  [System.IO.File]::WriteAllText((Join-Path $T 'logs\x11_pincheck.txt'), (($pc1 + $pc2) -join "`r`n"), $utf8)
  Check 'x11' ($pc1x -eq 0 -and $pc2x -eq 0) "pincheck.py --selftest (10 ca tong hop): exit $pc1x; --offline tren pins.json that: exit $pc2x"

  # ---------------------------------------------------------------- 6: thư mục game có dấu
  $r = Invoke-Tool -Cwd $gUni -Name '6_unicode' -EnvVars $env1 -ToolArgs @('--game', '.', '--pins', $pinsOk, '--yes-download', '--texture', 'hd', '--enable')
  $cU = Last-Call $gUni
  $gArg = Arg-After $cU '--game'
  $eArg = Arg-After $cU '--esrgan'
  $marker = Test-Path (Join-Path $staging '.lodsc-staging')
  $tog = Read-Exact (Join-Path $gUni 'remaster.properties')
  $u8 = ($cU.utf8_mode -eq 1) -and ($cU.isolated -eq 1)
  $ok = $r.Exit -eq 0 -and $gArg -eq $gUni -and $eArg -eq $staging -and $marker -and $u8 -and (Test-Path -LiteralPath (Join-Path $gUni 'remaster\index.tsv')) -and $tog -ceq "enabled=true`ntextures=hd`nlog=false`n"
  Check '6' $ok "thu muc co dau: exit $($r.Exit); worker nhan --game dung = $($gArg -eq $gUni); python -I -X utf8 = $u8; --esrgan = $eArg (staging ASCII, co danh dau = $marker); remaster.properties dung = $($tog -ceq "enabled=true`ntextures=hd`nlog=false`n")"

  # ---------------------------------------------------------------- bổ sung: staging là junction -> bỏ qua, không xoá dữ liệu nơi khác
  $victim = Join-Path $T 'victim'
  New-Item -ItemType Directory -Force $victim | Out-Null
  Set-Content (Join-Path $victim 'sentinel.txt') 'du lieu nguoi dung'
  $linkParent = Join-Path $T 'staging_link'
  New-Item -ItemType Directory -Force $linkParent | Out-Null
  $link = Join-Path $linkParent 'realesrgan'
  New-Item -ItemType Junction -Path $link -Target $victim | Out-Null
  Remove-Item -LiteralPath (Join-Path $gUni 'remaster_tools\esrgan_staging.json') -Force
  $r = Invoke-Tool -Cwd $gUni -Name 'x10_staging_junction' -EnvVars $env1 -Props @("-Dlodsc.remaster.staging=$link") -ToolArgs @('--game', '.', '--pins', $pinsOk, '--texture', 'hd')
  $cJ = Last-Call $gUni
  $victimFiles = @(Get-ChildItem -LiteralPath $victim -Force | ForEach-Object { $_.Name })
  $ok = $r.Exit -eq 0 -and ($victimFiles -join '|') -eq 'sentinel.txt' -and (@($cJ.argv) -contains '--no-ai') -and $r.Out -match 'junction'
  Check 'x10' $ok "thu muc staging la junction sang thu muc khac: exit $($r.Exit); thu muc dich con dung [$($victimFiles -join ', ')] (can chi sentinel.txt); worker --no-ai = $(@($cJ.argv) -contains '--no-ai')"
  cmd /c "rmdir `"$link`"" | Out-Null

  # ---------------------------------------------------------------- bổ sung: Xoá mô hình tắt công tắc, giữ textures/log + công cụ
  $r = Invoke-Tool -Cwd $gA -Name 'x9_delete_models' -ToolArgs @('--game', '.', '--pins', $pinsOk, '--uninstall', 'models')
  $p9 = Read-Exact (Join-Path $gA 'remaster.properties')
  $ok = $r.Exit -eq 0 -and $p9 -ceq "enabled=false`ntextures=retail`nlog=true`n" -and -not (Test-Path (Join-Path $gA 'remaster')) -and -not (Test-Path (Join-Path $gA 'remaster_work')) -and (Test-Path (Join-Path $gA 'remaster_tools\blender-5.2.2-windows-x64\.installed.json'))
  Check 'x9' $ok ("xoa mo hinh: exit $($r.Exit); remaster.properties = " + $p9.Replace("`n", '\n') + " (can enabled=false, giu textures/log); remaster\, remaster_work\ da xoa, cong cu giu nguyen")

  # ---------------------------------------------------------------- 9: gỡ hết
  $outside = Join-Path $T 'outside'
  New-Item -ItemType Directory -Force $outside | Out-Null
  Set-Content (Join-Path $outside 'sentinel.txt') 'giu nguyen'
  New-Item -ItemType Junction -Path (Join-Path $gUni 'remaster_work\link_ra_ngoai') -Target $outside | Out-Null
  New-Item -ItemType Directory -Force (Join-Path $gUni 'remaster_export') | Out-Null
  $r = Invoke-Tool -Cwd $gUni -Name '9a_uninstall_uni' -ToolArgs @('--game', '.', '--pins', $pinsOk, '--uninstall', 'all')
  $leftU = @(Get-ChildItem -LiteralPath $gUni -Filter 'remaster*' -Force).Count
  $r2 = Invoke-Tool -Cwd $gA -Name '9b_uninstall_ascii' -ToolArgs @('--game', '.', '--pins', $pinsOk, '--uninstall', 'all')
  $leftA = @(Get-ChildItem -LiteralPath $gA -Filter 'remaster*' -Force).Count
  $ok = $r.Exit -eq 0 -and $r2.Exit -eq 0 -and $leftU -eq 0 -and $leftA -eq 0 -and -not (Test-Path $staging) -and (Test-Path (Join-Path $outside 'sentinel.txt')) -and (Test-Path -LiteralPath (Join-Path $gUni 'vi\remaster\py\worker.py'))
  Check '9' $ok "go het: con muc remaster* = $leftU (co dau) / $leftA (ASCII); staging ngoai da xoa = $(-not (Test-Path $staging)); du lieu sau junction con = $(Test-Path (Join-Path $outside 'sentinel.txt')); vi\remaster giu nguyen"
} catch {
  Check 'ERR' $false ("loi bo kiem: " + $_.Exception.Message + " @ " + $_.InvocationInfo.ScriptLineNumber)
} finally {
  if ($server) { try { Stop-Process -Id $server.Id -Force -ErrorAction Stop } catch {} }
}

$fail = @($results | Where-Object { $_.Result -ne 'PASS' }).Count
Write-Output ''
Write-Output ("Tong: {0} muc, {1} FAIL. Log: {2}" -f $results.Count, $fail, (Join-Path $T 'logs'))
if ($fail) { exit 1 } else { exit 0 }
