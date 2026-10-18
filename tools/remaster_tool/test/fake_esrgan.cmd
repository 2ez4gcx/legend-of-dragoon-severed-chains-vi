@echo off
rem fake_esrgan.cmd - Real-ESRGAN GIA cho kiem thu cong cu "Tao mo hinh HD" (run_tests.ps1).
rem Nhan tham so nhu realesrgan-ncnn-vulkan.exe: -i <vao> -o <ra> -m <models> -n <model> -s 4 -f png [-t 64].
rem Duong dan tuong doi theo thu muc lam viec (staging ASCII). Che do theo bien FAKE_ESRGAN_MODE:
rem   (trong) / ok : phong to anh vao 4 lan bang System.Drawing (PowerShell), ghi PNG ra, ma 0
rem   fail         : gia lap may khong co Vulkan: in loi, ma 3
rem   hang         : treo (ping -n 777, mot tien trinh con) de kiem "qua gio -> diet ca cay tien trinh"
rem Chi dung trong kiem thu; make_fakes.py dat file nay vao zip Real-ESRGAN gia voi ten realesrgan-ncnn-vulkan.cmd.
setlocal EnableExtensions
set "IN="
set "OUT="
:args
if "%~1"=="" goto run
if /i "%~1"=="-i" set "IN=%~2"
if /i "%~1"=="-o" set "OUT=%~2"
shift
goto args
:run
if /i "%FAKE_ESRGAN_MODE%"=="fail" goto fail
if /i "%FAKE_ESRGAN_MODE%"=="hang" goto hang
if "%IN%"=="" exit /b 2
if "%OUT%"=="" exit /b 2
powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.Drawing; $i = [System.Drawing.Image]::FromFile((Join-Path (Get-Location) $env:IN)); $o = New-Object System.Drawing.Bitmap($i, ($i.Width * 4), ($i.Height * 4)); $o.Save((Join-Path (Get-Location) $env:OUT), [System.Drawing.Imaging.ImageFormat]::Png); $i.Dispose(); $o.Dispose()"
exit /b %ERRORLEVEL%
:fail
echo [0 fake] vkCreateInstance failed -9 1>&2
echo invalid gpu device 1>&2
exit /b 3
:hang
ping -n 777 127.0.0.1 >nul
exit /b 0
