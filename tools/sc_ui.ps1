<#
sc_ui.ps1 — điều khiển cửa sổ Severed Chains: gửi phím (keybd_event) và chụp ảnh cửa sổ (CopyFromScreen).
Cửa sổ SC PHẢI ở trên cùng: script tự đưa lên, kiểm lại trước MỖI lần bấm, mất tiêu điểm thì huỷ.

Cách gọi:
  powershell -File tools/sc_ui.ps1 [-Game game] [-Keys "Return,Down*3,S"] [-Ms 90] [-Gap 350] [-Shot out\x.png] [-Info]
Phím mặc định SC: mũi tên = D-pad, Return = Start, Space = Select, W/A/S/D = các nút hình (S = X/xác nhận theo bố trí PS:
  W tam giác, A vuông, S X, D tròn — kiểm lại trong menu Controls), Q/E = L1/R1, F11 tạm dừng, Tab = xem VRAM.
Ký hiệu "Phím*n" = bấm n lần; "wait:ms" = chờ.
#>
param(
  [string]$Game = 'game',
  [string]$Keys = '',
  [int]$Ms = 90,
  [int]$Gap = 350,
  [string]$Shot = '',
  [switch]$Info
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not [System.IO.Path]::IsPathRooted($Game)) { $Game = Join-Path $root $Game }
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices; using System.Text;
public class SCW {
 [DllImport("user32.dll")] public static extern void keybd_event(byte k, byte s, uint f, UIntPtr e);
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
 [DllImport("user32.dll")] public static extern uint MapVirtualKey(uint c, uint t);
 [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out R r);
 [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref P p);
 [DllImport("user32.dll")] public static extern bool GetCursorPos(out P p);
 [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
 public struct R { public int L, T, Ri, B; }
 public struct P { public int X, Y; }
}
"@
$scpid = [int](Get-Content (Join-Path $Game 'sc.pid'))
$p = Get-Process -Id $scpid -ErrorAction SilentlyContinue
if (-not $p) { Write-Output "ABORT: SC (PID $scpid) khong chay"; exit 1 }
$p.Refresh()
# Cửa sổ game (lớp SDL_app) — không lấy MainWindowHandle vì khi mở Debugger (F12) đó có thể là cửa sổ JavaFX
Add-Type -AssemblyName UIAutomationClient
$AE = [System.Windows.Automation.AutomationElement]
$cond = New-Object System.Windows.Automation.AndCondition(
  (New-Object System.Windows.Automation.PropertyCondition($AE::ProcessIdProperty, $scpid)),
  (New-Object System.Windows.Automation.PropertyCondition($AE::ClassNameProperty, 'SDL_app')))
$sdl = $AE::RootElement.FindFirst([System.Windows.Automation.TreeScope]::Children, $cond)
$h = if ($sdl) { [IntPtr]$sdl.Current.NativeWindowHandle } else { $p.MainWindowHandle }
if ($h -eq 0) { Write-Output "ABORT: SC chua co cua so"; exit 1 }
if ($Info) { Write-Output "cua so: '$($p.MainWindowTitle)' handle $h"; }

function Focus {
  for ($t = 0; $t -lt 6 -and [SCW]::GetForegroundWindow() -ne $h; $t++) {
    [SCW]::keybd_event(0x12, 0, 0, [UIntPtr]::Zero); [SCW]::keybd_event(0x12, 0, 2, [UIntPtr]::Zero)
    [SCW]::ShowWindow($h, 9) | Out-Null; [SCW]::SetForegroundWindow($h) | Out-Null; Start-Sleep -Milliseconds 250
  }
  return ([SCW]::GetForegroundWindow() -eq $h)
}

# Menu SC chọn mục theo vị trí chuột: con trỏ nằm trên cửa sổ (vd trên "Quit" ở màn tựa) thì Enter chọn nhầm mục đó.
# Trước khi bấm phím, nếu con trỏ ở trong vùng client thì dời nó ra ngay dưới mép trái cửa sổ.
function MouseAway {
  $r = New-Object SCW+R; [SCW]::GetClientRect($h, [ref]$r) | Out-Null
  $o = New-Object SCW+P; [SCW]::ClientToScreen($h, [ref]$o) | Out-Null
  $c = New-Object SCW+P; [SCW]::GetCursorPos([ref]$c) | Out-Null
  if ($c.X -ge $o.X -and $c.X -lt $o.X + $r.Ri -and $c.Y -ge $o.Y -and $c.Y -lt $o.Y + $r.B) {
    [SCW]::SetCursorPos($o.X, $o.Y + $r.B + 40) | Out-Null
  }
}

$map = @{Up = 0x26; Down = 0x28; Left = 0x25; Right = 0x27; Return = 0x0D; Escape = 0x1B; Space = 0x20; Tab = 0x09;
  W = 0x57; A = 0x41; S = 0x53; D = 0x44; Q = 0x51; E = 0x45; F11 = 0x7A; F12 = 0x7B; Back = 0x08}
if ($Keys) {
  if (-not (Focus)) { Write-Output 'ABORT: SC khong o tren cung'; exit 1 }
  MouseAway
  foreach ($tok in $Keys.Split(',')) {
    $tok = $tok.Trim(); if (-not $tok) { continue }
    if ($tok -like 'wait:*') { Start-Sleep -Milliseconds ([int]$tok.Substring(5)); continue }
    $n = 1; if ($tok -match '^(\w+)\*(\d+)$') { $tok = $Matches[1]; $n = [int]$Matches[2] }
    if (-not $map.ContainsKey($tok)) { Write-Output "ABORT: phim la $tok"; exit 1 }
    $vk = $map[$tok]; $ext = 0; if ($tok -in @('Up', 'Down', 'Left', 'Right')) { $ext = 1 }
    for ($i = 0; $i -lt $n; $i++) {
      if ([SCW]::GetForegroundWindow() -ne $h) { Write-Output 'ABORT: mat tieu diem'; exit 1 }
      $sc = [byte][SCW]::MapVirtualKey($vk, 0)
      [SCW]::keybd_event($vk, $sc, $ext, [UIntPtr]::Zero); Start-Sleep -Milliseconds $Ms
      [SCW]::keybd_event($vk, $sc, (2 -bor $ext), [UIntPtr]::Zero); Start-Sleep -Milliseconds $Gap
    }
  }
  Write-Output "da gui: $Keys"
}
if ($Shot) {
  if (-not (Focus)) { Write-Output 'ABORT: SC khong o tren cung (chup)'; exit 1 }
  Start-Sleep -Milliseconds 150
  $r = New-Object SCW+R; [SCW]::GetClientRect($h, [ref]$r) | Out-Null
  $pt = New-Object SCW+P; [SCW]::ClientToScreen($h, [ref]$pt) | Out-Null
  $w = $r.Ri - $r.L; $hh = $r.B - $r.T
  $bmp = New-Object System.Drawing.Bitmap $w, $hh; $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($pt.X, $pt.Y, 0, 0, $bmp.Size)
  if (-not [System.IO.Path]::IsPathRooted($Shot)) { $Shot = Join-Path $root $Shot }
  New-Item -ItemType Directory -Force (Split-Path -Parent $Shot) | Out-Null
  $bmp.Save($Shot); Write-Output "chup $Shot ${w}x$hh"
}
