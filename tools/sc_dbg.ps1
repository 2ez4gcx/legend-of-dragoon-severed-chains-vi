<#
sc_dbg.ps1 — điều khiển cửa sổ "Debugger" (F12) của Severed Chains qua UI Automation, để tới thẳng cảnh/trận cần kiểm.
Mở debugger trước: powershell -File tools/sc_ui.ps1 -Keys F12

Cách gọi:
  powershell -File tools/sc_dbg.ps1 -Warp 71            # nhảy tới cảnh (submap cut) 71, điểm vào 0 (tra số cảnh: tools/sc_cuts.py)
  powershell -File tools/sc_dbg.ps1 -Encounter 3        # bắt đầu trận số 3 (bảng LodEncounters.LEGACY) ở cảnh hiện tại
  powershell -File tools/sc_dbg.ps1 -Check "Save Anywhere" [-Uncheck]
  powershell -File tools/sc_dbg.ps1 -GetMap             # in số cảnh hiện tại
  powershell -File tools/sc_dbg.ps1 -ShowFlag2 "d0,e1,f5"          # in cờ cốt truyện (scriptReadGlobalFlag2)
  powershell -File tools/sc_dbg.ps1 -Flag2 "e1=1,f5=1,fe=0"        # đặt/xoá cờ (số hex), rồi Warp lại cảnh cho script đọc lại
  powershell -File tools/sc_dbg.ps1 -ShowFlag1 "be" / -Flag1 "be=1"  # như trên cho flags1 (scriptReadGlobalFlag1)
  powershell -File tools/sc_dbg.ps1 -SobjNear 11 [-Dx 30 -Dz 0]    # dời sobj 11 (NPC) tới cạnh người chơi để nói chuyện ngay
  powershell -File tools/sc_dbg.ps1 -SobjPos "0:126,-258,336"      # đặt vị trí sobj 0 (người chơi) — lấy toạ độ từ script cảnh
  powershell -File tools/sc_dbg.ps1 -ShowPlayer                    # in vị trí người chơi
  powershell -File tools/sc_dbg.ps1 -Chapter 0 -Warp 157           # đặt chương (0 = chương 1) rồi Warp: cảnh có bản "cuối game"
                                                                   # (NEWROOT lateGameFile) chỉ dùng bản đĩa 1 khi chương < đĩa bản cuối
Ô số (Spinner) của JavaFX chỉ nhận giá trị khi Enter/mất tiêu điểm: script đặt chữ vào ô, bấm Enter trong ô, rồi mới bấm nút.
Thứ tự Spinner trên cửa sổ: 0 Encounter, 1 Combat Stage, 2 Map, 3 VSync, 4 Game Speed.
Cờ sửa qua cửa sổ "GameState Editor" (menu Debuggers, tự mở), mỗi word 32 cờ: word = cờ >> 5, bit = cờ & 31.
  flags2 = GameState.scriptFlags2_bc (scriptReadGlobalFlag2, cờ cốt truyện, 32 word): hàng "Script Flags 1" (SC đặt tên ngược),
          ComboBox thứ 2 (0-based), nút Set thứ 22;
  flags1 = GameState.scriptFlags1_13c (scriptReadGlobalFlag1, 8 word; cảnh thường xoá 1..0x63 khi vào): hàng "Script Flags 2",
          ComboBox thứ 3, nút Set thứ 23.
NPC bản đồ: số NPC trong bảng thoại của script = số sobj (danh sách "Submap Debugger"); sobj dời bằng -SobjNear giữ nguyên script.
#>
param(
  [int]$Warp = -1,
  [int]$Encounter = -1,
  [string]$Check = '',
  [switch]$Uncheck,
  [switch]$GetMap,
  [string]$Flag2 = '',
  [string]$ShowFlag2 = '',
  [string]$Flag1 = '',
  [string]$ShowFlag1 = '',
  [int]$SobjNear = -1,
  [string]$SobjPos = '',
  [switch]$ShowPlayer,
  [int]$Chapter = -1,
  [double]$Dx = 30,
  [double]$Dz = 0
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
# Cửa sổ con của Debugger (menu Debuggers -> $item), tự mở nếu chưa có
function Child-Window([string]$item, [string]$title) {
  $cond = New-Object System.Windows.Automation.PropertyCondition($AE::NameProperty, $title)
  $g = $root.FindFirst($TS::Children, $cond)
  if (-not $g) {
    Invoke ($w.FindFirst($TS::Descendants, (New-Object System.Windows.Automation.PropertyCondition($AE::NameProperty, 'Debuggers'))))
    Start-Sleep -Milliseconds 600
    Invoke ($w.FindFirst($TS::Descendants, (New-Object System.Windows.Automation.PropertyCondition($AE::NameProperty, $item))))
    for ($t = 0; $t -lt 20 -and -not $g; $t++) { Start-Sleep -Milliseconds 300; $g = $root.FindFirst($TS::Children, $cond) }
    if (-not $g) { throw "khong mo duoc $title" }
  }
  return $g
}
function Editor { Child-Window 'GameState Editor' 'GameState Editor' }
# Bộ cờ trong GameState Editor: flags2 -> ComboBox 2 + nút Set 22 (hàng "Script Flags 1"),
# flags1 -> ComboBox 3 + nút Set 23 (hàng "Script Flags 2")
$FLAGSETS = @{ 2 = @(2, 22); 1 = @(3, 23) }
# Word [word] của bộ cờ: chọn word ở ComboBox của hàng, trả ô chữ ngay sau nó
function Flags-Row($g, [int]$set, [int]$word) {
  $combo = $null; $edit = $null; $n = 0
  foreach ($e in $g.FindAll($TS::Children, [System.Windows.Automation.Condition]::TrueCondition)) {
    $type = $e.Current.ControlType
    if ($type -eq [System.Windows.Automation.ControlType]::ComboBox) { if ($n -eq $FLAGSETS[$set][0]) { $combo = $e }; $n++ }
    elseif ($combo -and $type -eq [System.Windows.Automation.ControlType]::Edit) { $edit = $e; break }
  }
  if (-not $edit) { throw "khong thay hang co flags$set" }
  $ec = $combo.GetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern)
  $ec.Expand(); Start-Sleep -Milliseconds 400
  # các mục chỉ có khi mở hộp chọn, nằm trong cửa sổ popup (con của cửa sổ editor), không phải con của ComboBox
  $item = $g.FindFirst($TS::Descendants, (New-Object System.Windows.Automation.AndCondition(
    (New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, [System.Windows.Automation.ControlType]::ListItem)),
    (New-Object System.Windows.Automation.PropertyCondition($AE::NameProperty, [string]$word)))))
  if (-not $item) { throw "khong thay word $word trong hop chon" }
  $item.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select(); Start-Sleep -Milliseconds 300
  $ec.Collapse(); Start-Sleep -Milliseconds 200
  $now = $combo.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value
  if ($now -ne [string]$word) { throw "hop chon word = '$now', can $word" }
  return $edit
}
function Read-Word($edit) { [Convert]::ToInt64(($edit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value -replace '^0x', ''), 16) }

function Show-Flags([int]$set, [string]$list) {
  $g = Editor
  foreach ($f in $list.Split(',')) {
    $flag = [Convert]::ToInt32($f.Trim(), 16)
    $v = Read-Word (Flags-Row $g $set ($flag -shr 5))
    Write-Output ("flag{0} 0x{1:x} = {2} (word {3} = 0x{4:x})" -f $set, $flag, (($v -shr ($flag -band 31)) -band 1), ($flag -shr 5), $v)
  }
}
function Set-Flags([int]$set, [string]$list) {
  $g = Editor
  foreach ($f in $list.Split(',')) {
    $flag, $val = $f.Trim().Split('=')
    $flag = [Convert]::ToInt32($flag, 16)
    $edit = Flags-Row $g $set ($flag -shr 5)
    $v = Read-Word $edit
    $bit = [int64]1 -shl ($flag -band 31)
    $nv = if ([int]$val) { $v -bor $bit } else { $v -band (-bnot $bit) }
    $edit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue(('0x{0:x}' -f ($nv -band 0xffffffff)))
    Start-Sleep -Milliseconds 150
    Invoke ($g.FindAll($TS::Descendants, (New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, [System.Windows.Automation.ControlType]::Button)))[$FLAGSETS[$set][1]])
    Start-Sleep -Milliseconds 200
    # đọc lại: chọn word khác rồi chọn lại để ô chữ lấy giá trị từ GameState
    $back = Read-Word (Flags-Row $g $set ((($flag -shr 5) + 1) % 8))
    $back = Read-Word (Flags-Row $g $set ($flag -shr 5))
    if ($back -ne ($nv -band 0xffffffff)) { throw ("flag{0} 0x{1:x}: word = 0x{2:x}, can 0x{3:x}" -f $set, $flag, $back, $nv) }
    Write-Output ("flag{0} 0x{1:x} = {2} (word {3} = 0x{4:x})" -f $set, $flag, [int]$val, ($flag -shr 5), $back)
  }
}
if ($Chapter -ge 0) {
  # GameState Editor: ô Chapter = Edit thứ 3 (sau Script Data, Party, Gold), nút Set = Button thứ 7
  $g = Editor
  $edits = $g.FindAll($TS::Children, (New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, [System.Windows.Automation.ControlType]::Edit)))
  $edits[3].GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue([string]$Chapter); Start-Sleep -Milliseconds 150
  Invoke ($g.FindAll($TS::Children, (New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, [System.Windows.Automation.ControlType]::Button)))[7])
  Write-Output "chapter $Chapter (chapterIndex: 0 = chuong 1; SC chon ban do dau/cuoi game theo chuong va dia hien tai)"
}
if ($ShowFlag2) { Show-Flags 2 $ShowFlag2 }
if ($ShowFlag1) { Show-Flags 1 $ShowFlag1 }
if ($Flag2) { Set-Flags 2 $Flag2 }
if ($Flag1) { Set-Flags 1 $Flag1 }
if ($SobjNear -ge 0 -or $SobjPos -or $ShowPlayer) {
  # Submap Debugger: chọn sobj trong danh sách (0 = Player), 3 Spinner đầu = vị trí X/Y/Z, nút "Update" đầu = ghi vị trí
  $s = Child-Window 'Submap' 'Submap Debugger'
  $items = $s.FindAll($TS::Descendants, (New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, [System.Windows.Automation.ControlType]::ListItem)))
  function Pick([int]$i) {
    if ($i -ge $items.Count) { throw "khong co sobj $i (danh sach $($items.Count))" }
    # chọn mục khác trước: chọn lại đúng mục đang chọn thì ô vị trí không đọc lại giá trị mới
    $items[($i + 1) % $items.Count].GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select(); Start-Sleep -Milliseconds 200
    $items[$i].GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select(); Start-Sleep -Milliseconds 300
    $sp = $s.FindAll($TS::Descendants, (New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, [System.Windows.Automation.ControlType]::Spinner)))
    return @($sp[0], $sp[1], $sp[2])
  }
  function Num($sp) { [double]::Parse($sp.Current.Name, [Globalization.CultureInfo]::InvariantCulture) }
  $p = Pick 0
  $px, $py, $pz = (Num $p[0]), (Num $p[1]), (Num $p[2])
  Write-Output ("player {0} ({1}, {2}, {3})" -f $items[0].Current.Name, $px, $py, $pz)
  if ($ShowPlayer) { exit 0 }
  if ($SobjPos) {
    $idx, $xyz = $SobjPos.Split(':')
    $SobjNear = [int]$idx
    $vals = @($xyz.Split(',') | ForEach-Object { [double]::Parse($_, [Globalization.CultureInfo]::InvariantCulture) })
  } else {
    $vals = @(($px + $Dx), $py, ($pz + $Dz))
  }
  $o = Pick $SobjNear
  Write-Output ("sobj {0} '{1}' ({2}, {3}, {4})" -f $SobjNear, $items[$SobjNear].Current.Name, (Num $o[0]), (Num $o[1]), (Num $o[2]))
  for ($k = 0; $k -lt 3; $k++) {
    $edit = $o[$k].FindFirst($TS::Descendants, (New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, [System.Windows.Automation.ControlType]::Edit)))
    $edit.SetFocus(); Start-Sleep -Milliseconds 150
    $edit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue($vals[$k].ToString([Globalization.CultureInfo]::InvariantCulture))
    [System.Windows.Forms.SendKeys]::SendWait('{ENTER}'); Start-Sleep -Milliseconds 200
  }
  $upd = $null
  foreach ($b in $s.FindAll($TS::Descendants, (New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, [System.Windows.Automation.ControlType]::Button)))) {
    if ($b.Current.Name -eq 'Update') { $upd = $b; break }
  }
  Invoke $upd
  Write-Output ("sobj {0} -> ({1}, {2}, {3})" -f $SobjNear, (Num $o[0]), (Num $o[1]), (Num $o[2]))
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
