<#
save_transfer_test.ps1 — kiểm phần xuất/nhập bản lưu của app (android/app/java/vn/lodsc/SaveTransfer.java) trên máy tính.

Cách gọi:  powershell -ExecutionPolicy Bypass -File android/test/save_transfer_test.ps1
Biên dịch SaveTransfer + SaveTransferTest bằng JDK 17, -source 8, classpath android.jar (như make_apk.py) vào out/android/test,
rồi chạy SaveTransferTest (android.jar chỉ để nạp lớp; phần được kiểm không gọi API Android). Exit 0 = đạt.
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$jdk = if ($env:JDK17) { $env:JDK17 } else { 'C:\Program Files\Eclipse Adoptium\jdk-17.0.20.8-hotspot' }
$androidJar = Join-Path $env:LOCALAPPDATA 'Android\Sdk\platforms\android-36\android.jar'
$out = Join-Path $root 'out\android\test'
Remove-Item $out -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $out | Out-Null
$app = Join-Path $root 'android\app\java\vn\lodsc'
& "$jdk\bin\javac.exe" -encoding UTF-8 -source 8 -target 8 -nowarn -Xlint:-options -cp $androidJar -d $out `
  "$app\SaveTransfer.java" "$app\Payload.java" (Join-Path $PSScriptRoot 'SaveTransferTest.java')
if ($LASTEXITCODE) { Write-Output 'LOI javac'; exit 1 }
& "$jdk\bin\java.exe" -cp "$out;$androidJar" vn.lodsc.SaveTransferTest
exit $LASTEXITCODE
