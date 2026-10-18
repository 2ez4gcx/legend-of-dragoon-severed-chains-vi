<#
build.ps1 - dựng out/remaster_tool/lodsc-remaster.jar: công cụ "Tạo mô hình HD" (Java Swing, tools/remaster_tool/src).

Cách gọi:
  powershell -ExecutionPolicy Bypass -File tools/remaster_tool/build.ps1 [-Game game] [-Out out\remaster_tool\lodsc-remaster.jar]
    -Game  thư mục bản build SC (tương đối theo D:\LOD-SC hoặc tuyệt đối), mặc định "game": lấy jdk25\bin (javac, jar) và
           libs\gson-*.jar (thư viện duy nhất công cụ dùng); chỉ ĐỌC, không sửa gì trong đó.
    -Out   đường dẫn jar ra.
Biên dịch: javac --release 25 -encoding UTF-8, classpath = gson; danh sách nguồn sắp theo tên.
Jar xác định: công cụ jar của JDK với --date cố định (mọi mục cùng thời điểm 2026-10-16T00:00:00Z), Main-Class
vn.lodsc.remaster.Tool, thư mục lớp dựng mới mỗi lần (out\remaster_tool_build\classes-<pid>, xoá sau khi dựng; không
để lại gì cạnh jar ra) -> hai lần dựng cùng JDK ra cùng SHA-256 (run_tests.ps1 kiểm).
In ra SHA-256 của jar. Exit 0 = đạt, 1 = lỗi.
Chạy thử: jdk25\bin\java -cp "out\remaster_tool\lodsc-remaster.jar;game\libs\gson-2.13.2.jar" vn.lodsc.remaster.Tool --game game
#>
param([string]$Game = 'game', [string]$Out = '')
$ErrorActionPreference = 'Stop'
try {
  $here = $PSScriptRoot
  $root = Split-Path -Parent (Split-Path -Parent $here)
  if (-not [System.IO.Path]::IsPathRooted($Game)) { $Game = Join-Path $root $Game }
  if (-not $Out) { $Out = Join-Path $root 'out\remaster_tool\lodsc-remaster.jar' }
  elseif (-not [System.IO.Path]::IsPathRooted($Out)) { $Out = Join-Path $root $Out }
  $jdk = Join-Path $Game 'jdk25\bin'
  $javac = Join-Path $jdk 'javac.exe'
  $jartool = Join-Path $jdk 'jar.exe'
  if (-not (Test-Path $javac)) { throw "khong thay $javac" }
  $gson = Get-ChildItem (Join-Path $Game 'libs') -Filter 'gson-*.jar' | Sort-Object Name | Select-Object -First 1
  if (-not $gson) { throw "khong thay libs\gson-*.jar trong $Game" }

  $outDir = Split-Path -Parent $Out
  New-Item -ItemType Directory -Force $outDir | Out-Null
  # thu muc lop tam ngoai thu muc jar ra (make_release co the dung -Out trong thu muc dong goi: khong de lai classes\)
  $cls = Join-Path $root ('out\remaster_tool_build\classes-' + $PID)
  if (Test-Path $cls) { Remove-Item $cls -Recurse -Force }
  New-Item -ItemType Directory -Force $cls | Out-Null

  $src = @(Get-ChildItem (Join-Path $here 'src') -Recurse -Filter *.java | Sort-Object FullName | ForEach-Object { $_.FullName })
  if ($src.Count -eq 0) { throw 'khong co nguon .java' }
  & $javac -encoding UTF-8 --release 25 -Xlint:-options -cp $gson.FullName -d $cls $src
  if ($LASTEXITCODE) { throw 'javac loi' }

  if (Test-Path $Out) { Remove-Item $Out -Force }
  & $jartool --create --file $Out --date '2026-10-16T00:00:00Z' --main-class vn.lodsc.remaster.Tool -C $cls .
  if ($LASTEXITCODE) { throw 'jar loi' }
  $entries = & $jartool tf $Out
  foreach ($need in @('META-INF/MANIFEST.MF', 'vn/lodsc/remaster/Tool.class', 'vn/lodsc/remaster/MainWindow.class', 'vn/lodsc/remaster/Cli.class')) {
    if ($entries -notcontains $need) { throw "jar thieu $need" }
  }
  $sha = (Get-FileHash $Out -Algorithm SHA256).Hash.ToLower()
  Write-Output "DAT: $Out"
  Write-Output "SHA-256: $sha"
  $rc = 0
} catch {
  Write-Output "LOI: $($_.Exception.Message)"
  $rc = 1
} finally {
  if ($cls -and (Test-Path $cls)) { Remove-Item $cls -Recurse -Force -ErrorAction SilentlyContinue }
  $bd = Join-Path $root 'out\remaster_tool_build'
  if ((Test-Path $bd) -and -not (Get-ChildItem $bd -Force)) { Remove-Item $bd -Force -ErrorAction SilentlyContinue }
}
exit $rc
