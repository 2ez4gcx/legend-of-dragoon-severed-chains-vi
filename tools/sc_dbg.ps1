<#
sc_dbg.ps1 — điều khiển cửa sổ "Debugger" (F12) của Severed Chains qua UI Automation, để tới thẳng cảnh/trận cần kiểm.
Mở debugger trước: powershell -File tools/sc_ui.ps1 -Keys F12

Cách gọi:
  powershell -File tools/sc_dbg.ps1 -Warp 71            # nhảy tới cảnh (submap cut) 71, điểm vào 0 (tra số cảnh: tools/sc_cuts.py)
  powershell -File tools/sc_dbg.ps1 -Encounter 3        # bắt đầu trận số 3 (bảng LodEncounters.LEGACY) ở cảnh hiện tại
  powershell -File tools/sc_dbg.ps1 -Check "Save Anywhere" [-Uncheck]
  powershell -File tools/sc_dbg.ps1 -GetMap             # in số cảnh hiện tại
Ô số (Spinner) của JavaFX chỉ nhận giá trị khi Enter/mất tiêu điểm: script đặt chữ vào ô, bấm Enter trong ô, rồi mới bấm nút.
Thứ tự Spinner trên cửa sổ: 0 Encounter, 1 Combat Stage, 2 Map, 3 VSync, 4 Game Speed.
#>
param(
  [int]$Warp = -1,
  [int]$Encounter = -1,
  [string]$Check = '',
  [switch]$Uncheck,
  [switch]$GetMap
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Windows.Forms
$AE = [System.Windows.Automation.AutomationElement]
$TS = [System.Windows.Automation.TreeScope]
$root = $AE::RootElement
$w = $root.FindFirst($TS::Children, (New-Object System.Windows.Automation.PropertyCondition($AE::NameProperty, 'Debugger')))
if (-not $w) { Write-Output 'ABORT: chua mo Debugger (F12)'; exit 1 }

function Find-All($type) {
  $w.FindAll($TS::Descendants, (New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, $type)))
}
function Button($name) {
  foreach ($b in (Find-All ([System.Windows.Automation.ControlType]::Button))) { if ($b.Current.Name -eq $name) { return $b } }
  throw "khong thay nut $name"
}
function Invoke($e) { $e.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke() }
function Set-Spinner([int]$index, [int]$value) {
  $sp = (Find-All ([System.Windows.Automation.ControlType]::Spinner))[$index]
  $edit = $sp.FindFirst($TS::Descendants, (New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, [System.Windows.Automation.ControlType]::Edit)))
  $edit.SetFocus(); Start-Sleep -Milliseconds 150
  $edit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue([string]$value)
  Start-Sleep -Milliseconds 100
  [System.Windows.Forms.SendKeys]::SendWait('{ENTER}'); Start-Sleep -Milliseconds 200
  $now = $sp.Current.Name
  if ($now -ne [string]$value) { throw "Spinner $index = '$now', can $value" }
}

if ($GetMap) {
  Invoke (Find-All ([System.Windows.Automation.ControlType]::Button) | Where-Object { $_.Current.Name -eq 'Get' })[2]
  Start-Sleep -Milliseconds 200
  Write-Output ("map " + (Find-All ([System.Windows.Automation.ControlType]::Spinner))[2].Current.Name)
}
if ($Check) {
  $cb = $null
  foreach ($e in (Find-All ([System.Windows.Automation.ControlType]::CheckBox))) { if ($e.Current.Name.Trim() -eq $Check) { $cb = $e } }
  if (-not $cb) { throw "khong thay o $Check" }
  $tp = $cb.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
  $want = if ($Uncheck) { 'Off' } else { 'On' }
  if ([string]$tp.Current.ToggleState -ne $want) { $tp.Toggle() }
  Write-Output "$Check = $($tp.Current.ToggleState)"
}
if ($Warp -ge 0) {
  Set-Spinner 2 $Warp
  Invoke (Button 'Warp')
  Write-Output "warp $Warp"
}
if ($Encounter -ge 0) {
  Set-Spinner 0 $Encounter
  Invoke (Button 'Start')
  Write-Output "encounter $Encounter"
}
