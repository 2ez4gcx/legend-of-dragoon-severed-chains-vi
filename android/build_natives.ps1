<#
build_natives.ps1 — dựng thư viện native cho bản Android của Severed Chains (Windows + Android NDK).

Cách gọi:
  powershell -ExecutionPolicy Bypass -File android/build_natives.ps1 [-Abi arm64-v8a|x86_64] [-Only sdl3,openal,opus,lwjgl,launcher] [-Clean]
    -Abi  arm64-v8a (mặc định, bản phát hành) hoặc x86_64 (chỉ để thử trên giả lập Android của máy tính)
Cần: Android SDK (%LOCALAPPDATA%\Android\Sdk hoặc ANDROID_HOME) có ndk;28.2.13676358 và cmake;3.31.6; mã nguồn chính thức
     giải nén trong deps/android/src (android/README.md): SDL3 3.4.14 và LWJGL 3.4.3 (đúng bản mà build SC affcef0 dùng),
     libffi 3.8.0, Opus 1.5.2, OpenAL Soft 1.24.3 (1.25 cần C++20 mới hơn NDK r28; LWJGL gọi qua con trỏ hàm nên dùng được).
Kết quả: deps/android/out/<abi>/*.so (libSDL3, libopenal, libopus, liblwjgl, liblwjgl_opengles, liblwjgl_stb, libsclauncher;
         đã strip, căn trang 16 KB) và deps/android/out/sdl-java (lớp Java SDLActivity... của SDL3).
#>
param(
  [ValidateSet('arm64-v8a', 'x86_64')][string]$Abi = 'arm64-v8a',
  [string[]]$Only = @('sdl3', 'openal', 'opus', 'lwjgl', 'launcher'),
  [switch]$Clean
)
$ErrorActionPreference = 'Stop'
$Only = @($Only | ForEach-Object { $_ -split ',' } | Where-Object { $_ })   # -File truyền "a,b" thành một chuỗi
$root = Split-Path -Parent $PSScriptRoot
$sdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
$ndk = Join-Path $sdk 'ndk\28.2.13676358'
$cmakeBin = Join-Path $sdk 'cmake\3.31.6\bin'
$cmake = Join-Path $cmakeBin 'cmake.exe'
$ninja = Join-Path $cmakeBin 'ninja.exe'
$toolchain = Join-Path $ndk 'build\cmake\android.toolchain.cmake'
$src = Join-Path $root 'deps\android\src'
$bld = Join-Path $root "deps\android\build\$Abi"
$out = Join-Path $root "deps\android\out\$Abi"
$api = 29   # Android 10
foreach ($p in $ndk, $cmake, $ninja, $toolchain) { if (-not (Test-Path $p)) { throw "thieu $p" } }
New-Item -ItemType Directory -Force $bld, $out | Out-Null
$fwd = { param($p) $p -replace '\\', '/' }   # CMake hiểu "\" trong chuỗi là ký tự thoát

function CMakeBuild([string]$name, [string]$source, [string[]]$extra) {
  $b = Join-Path $bld $name
  if ($Clean -and (Test-Path $b)) { Remove-Item $b -Recurse -Force }
  $args = @('-G', 'Ninja', '-S', $source, '-B', $b, "-DCMAKE_MAKE_PROGRAM=$ninja", "-DCMAKE_TOOLCHAIN_FILE=$toolchain",
    "-DANDROID_ABI=$Abi", "-DANDROID_PLATFORM=android-$api", '-DCMAKE_BUILD_TYPE=Release',
    '-DANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON') + $extra
  & $cmake @args | Out-Host
  if ($LASTEXITCODE) { throw "cmake configure $name loi" }
  & $cmake --build $b --parallel | Out-Host
  if ($LASTEXITCODE) { throw "cmake build $name loi" }
  return $b
}

if ($Only -contains 'sdl3') {
  $b = CMakeBuild 'sdl3' (Join-Path $src 'SDL3-3.4.14') @('-DSDL_SHARED=ON', '-DSDL_STATIC=OFF', '-DSDL_TEST_LIBRARY=OFF', '-DSDL_TESTS=OFF', '-DSDL_EXAMPLES=OFF')
  Copy-Item (Join-Path $b 'libSDL3.so') $out -Force
  $java = Join-Path $root 'deps\android\out\sdl-java'
  if (Test-Path $java) { Remove-Item $java -Recurse -Force }
  Copy-Item (Join-Path $src 'SDL3-3.4.14\android-project\app\src\main\java') $java -Recurse
  Write-Output 'DAT sdl3'
}

if ($Only -contains 'openal') {
  # LWJGL nạp "libopenal.so" (Platform.mapLibraryNameBundled("openal")); OpenAL Soft dùng OpenSL ES trên Android
  $b = CMakeBuild 'openal' (Join-Path $src 'openal-soft-1.24.3') @('-DALSOFT_UTILS=OFF', '-DALSOFT_EXAMPLES=OFF', '-DALSOFT_TESTS=OFF',
    '-DALSOFT_INSTALL=OFF', '-DLIBTYPE=SHARED')
  Copy-Item (Join-Path $b 'libopenal.so') $out -Force
  Write-Output 'DAT openal'
}

if ($Only -contains 'opus') {
  $b = CMakeBuild 'opus' (Join-Path $src 'opus-1.5.2') @('-DBUILD_SHARED_LIBS=ON', '-DOPUS_BUILD_PROGRAMS=OFF', '-DOPUS_BUILD_TESTING=OFF',
    '-DCMAKE_POLICY_VERSION_MINIMUM=3.5')
  Copy-Item (Join-Path $b 'libopus.so') $out -Force
  Write-Output 'DAT opus'
}

if ($Only -contains 'lwjgl') {
  $ffiInc = Join-Path $bld 'ffi-include'
  python (Join-Path $PSScriptRoot 'natives\gen_ffi_headers.py') (Join-Path $src 'libffi-3.8.0') $ffiInc $Abi
  if ($LASTEXITCODE) { throw 'gen_ffi_headers loi' }
  $b = CMakeBuild 'lwjgl' (Join-Path $PSScriptRoot 'natives') @("-DLWJGL_SRC=$(& $fwd (Join-Path $src 'lwjgl3-3.4.3'))",
    "-DFFI_SRC=$(& $fwd (Join-Path $src 'libffi-3.8.0'))", "-DFFI_INC=$(& $fwd $ffiInc)")
  foreach ($so in 'liblwjgl.so', 'liblwjgl_opengles.so', 'liblwjgl_stb.so') { Copy-Item (Join-Path $b $so) $out -Force }
  Write-Output 'DAT lwjgl'
}

if ($Only -contains 'launcher') {
  $b = CMakeBuild 'launcher' (Join-Path $PSScriptRoot 'launcher') @("-DSDL_INCLUDE=$(& $fwd (Join-Path $src 'SDL3-3.4.14\include'))",
    "-DSDL_LIB=$(& $fwd (Join-Path $out 'libSDL3.so'))")
  Copy-Item (Join-Path $b 'libsclauncher.so') $out -Force
  Write-Output 'DAT launcher'
}

# Bỏ thông tin gỡ lỗi (APK nhỏ hơn); bản chưa strip giữ trong deps/android/build
$strip = Join-Path $ndk 'toolchains\llvm\prebuilt\windows-x86_64\bin\llvm-strip.exe'
foreach ($so in Get-ChildItem $out -Filter *.so) { & $strip --strip-unneeded $so.FullName }
