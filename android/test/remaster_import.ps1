<#
remaster_import.ps1 — thử nhập gói "Mô hình HD" (vn.lodsc.RemasterImport) và công tắc Bật/Tắt trên giả lập Android x86_64.

Dữ liệu thử: mô hình tổng hợp tools/sc_remaster/spec/synth_cube.py (KHÔNG phải dữ liệu Sony), đóng thành các gói .zip hợp lệ
và các gói gieo lỗi trong out/android/remaster_test/ (git bỏ qua). Ứng dụng phải là bản debuggable (make_apk.py --abi x86_64):
mỗi ca mở SetupActivity bằng `--ez setup true --es hd_test_zip hdtest/<ca>.zip` (lối thử chỉ có ở bản debuggable, không qua
trình chọn tệp) rồi đọc dòng log "LodscHd: result ..." và dòng trạng thái trên màn hình (uiautomator). KHÔNG mở game.

Kiểm:
  1. gói hợp lệ nhập được, cây game/remaster trên máy trùng SHA-1 từng tệp, remaster.properties đúng từng byte, không còn
     remaster.import / remaster.old;
  2. mỗi gói gieo lỗi ('../', đường dẫn tuyệt đối, '\', ':', tệp lạ, thư mục lạ, mục trùng, magic/version/khoá LRM sai,
     PNG sai tên/hỏng/không luỹ thừa 2, index.tsv sai, thiếu .lrm, manifest sai / lồng quá sâu / > 4 MB, quá 64 MB/mục,
     quá 1 GB tổng (giới hạn hạ bằng hd_test_total_cap), quá 4096 mục, thiếu chỗ (hd_test_reserve), tên mục không phải UTF-8,
     không phải zip, zip cụt, mục STORED có data descriptor, CRC sai, cờ mã hoá, tên mục Unicode lạ, .lrm là thư mục,
     DOC_TRUOC.txt trùng / chỉ có DOC_TRUOC.txt, zip rỗng, zip có phần đầu thừa, zip không trọn vẹn mà ZipInputStream vẫn
     đọc "hết": cắt đúng ranh giới trước PNG đầu, thiếu / cắt giữa mục lục, mục lục đếm sai, thừa byte sau EOCD) bị từ chối đúng mã, thông báo tiếng Việt
     (so với strings.xml) hiện trên màn hình, game/remaster + remaster.properties giữ nguyên, không tệp nào lọt ra ngoài,
     không còn remaster.import / remaster.old; gói hợp lệ ghi kiểu khác (STORED, luồng có data descriptor, tên tệp zip
     tiếng Việt, có chú thích zip) cũng nhập được;
  3. nút "Mô hình HD: Bật/Tắt" ghi remaster.properties (giữ textures/log theo đúng nghĩa runtime, kể cả giá trị lạ);
  4. khôi phục sau khi app bị tắt giữa lúc đổi chỗ (remaster.old -> remaster, dọn remaster.import);
  5. cài lại APK (adb install -r) và cập nhật APK (xoá files/payload.version -> app giải nén lại payload, xoá Payload.PROGRAM)
     giữ nguyên game/remaster và công tắc;
  6. android/make_apk.py --selftest-guards (chốt chặn dữ liệu mô hình HD trong payload) exit 0;
  7. (-Determinism) dựng APK x86_64 hai lần, cùng SHA-256;  (-Saf) một lần nhập thật qua nút + trình chọn tệp Android;
     (-RealUpdate) cập nhật thật: dựng APK x86_64 từ gói Windows v0.3 (versionCode 3001, payload khác) vào out/android, cài đè,
     app giải nén payload mới, dữ liệu mô hình HD + công tắc còn nguyên; rồi hạ lại APK đang thử (install -r -d).

Cách gọi (giả lập đang chạy, xem android/README.md; app đã cài hoặc dùng -Build):
  powershell -ExecutionPolicy Bypass -File android/test/remaster_import.ps1 [-Build] [-Determinism] [-NoInstall] [-Saf]
             [-NoUpdate] [-RealUpdate] [-Keep] [-Only <regex tên ca>]
Exit 0 = đạt, 1 = có lỗi. Dữ liệu mẫu trên máy bị xoá khi xong (trừ -Keep); game/remaster có sẵn trước khi thử được cất rồi trả lại.
#>
param([switch]$Build, [switch]$Determinism, [switch]$NoInstall, [switch]$Saf, [switch]$NoUpdate, [switch]$RealUpdate, [switch]$Keep,
      [string]$Only = '')
# Continue: stderr của adb/run-as không được làm dừng script (PowerShell 5.1 biến stderr thành lỗi khi chuyển hướng)
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$adb = Join-Path $env:LOCALAPPDATA 'Android\Sdk\platform-tools\adb.exe'
$work = Join-Path $root 'out\android\remaster_test'
$apk = Join-Path $root 'out\android\LoD-SC-VN-v0.2-android-x86_64.apk'
$pkg = 'vn.lodsc'
$env:PYTHONIOENCODING = 'utf-8'
$script:passes = 0
$script:fails = 0

function Pass([string]$m) { $script:passes++; Write-Output "DAT  $m" }
function Fail([string]$m) { $script:fails++; Write-Output "LOI  $m" }
function Check([bool]$ok, [string]$m) { if ($ok) { Pass $m } else { Fail $m } }

# adb shell <lệnh>; lệnh không được chứa dấu nháy kép
function Sh([string]$cmd) { return @(& $adb shell "$cmd 2>&1") }
# chạy trong thư mục dữ liệu của app (bản debuggable); lệnh không được chứa nháy đơn
function RunAs([string]$cmd) { return @(& $adb shell "run-as $pkg sh -c '$cmd' 2>&1") }
function AdbQuiet([string]$line) { $null = cmd /c "`"$adb`" $line 2>&1"; return $LASTEXITCODE }

# SHA-1 mọi tệp của game/remaster*, game/remaster.properties (sắp xếp) — "ảnh chụp" trạng thái
function Snapshot {
  $l = RunAs 'cd files/game && find remaster remaster.properties remaster.import remaster.old -type f -exec sha1sum {} + 2>/dev/null; true'
  return (@($l | Where-Object { $_ -match '\S' } | ForEach-Object { $_.Trim() }) | Sort-Object) -join "`n"
}
function TreeOf([string]$snap) {
  return (@($snap -split "`n" | Where-Object { $_ -match '\s+remaster/' }) | Sort-Object) -join "`n"
}
function Props { return (@(RunAs 'cat files/game/remaster.properties 2>/dev/null; true') | Where-Object { $_ -ne '' }) -join "`n" }
function Leftovers {
  return @(RunAs 'cd files && find . -name evil* 2>/dev/null; ls -d game/remaster.import game/remaster.old 2>/dev/null; true' |
           Where-Object { $_ -match '\S' })
}

# chuỗi giao diện tiếng Việt lấy từ strings.xml (script giữ ASCII trong mã)
$strings = @{}
$sx = [xml](Get-Content (Join-Path $root 'android\app\res\values\strings.xml') -Raw -Encoding UTF8)
foreach ($s in $sx.resources.string) { $strings[$s.name] = ($s.InnerText -replace '\\n', "`n" -replace "\\'", "'" -replace '\\"', '"') }
function Prefix([string]$name) {
  $t = $strings[$name]
  if ($null -eq $t) { throw "thieu chuoi $name" }
  $i = $t.IndexOf('%')
  if ($i -ge 0) { $t = $t.Substring(0, $i) }
  return $t
}

function UiNodes {
  $tmp = Join-Path $work 'ui.xml'
  for ($i = 0; $i -lt 6; $i++) {
    if (Test-Path $tmp) { Remove-Item $tmp }
    $null = AdbQuiet 'shell uiautomator dump /sdcard/hd_ui.xml'
    $null = AdbQuiet "pull /sdcard/hd_ui.xml `"$tmp`""
    if (Test-Path $tmp) {
      try { return @(([xml](Get-Content $tmp -Raw -Encoding UTF8)).SelectNodes('//node')) } catch { }
    }
    Start-Sleep -Milliseconds 800
  }
  return @()
}
function FindNode($nodes, [string]$text) {
  foreach ($n in $nodes) { if ($n.text -and $n.text.ToLowerInvariant() -eq $text.ToLowerInvariant()) { return $n } }
  return $null
}
function TapNode($n) {
  $m = [regex]::Match($n.bounds, '\[(\d+),(\d+)\]\[(\d+),(\d+)\]')
  $x = ([int]$m.Groups[1].Value + [int]$m.Groups[3].Value) / 2
  $y = ([int]$m.Groups[2].Value + [int]$m.Groups[4].Value) / 2
  $null = Sh "input tap $x $y"
}

# mở SetupActivity (dừng app trước), không bao giờ tự vào game
function StartSetup([string[]]$extra) {
  $null = AdbQuiet 'logcat -c'
  $a = @('shell', 'am', 'start', '-S', '-W', '-n', "$pkg/.SetupActivity", '--ez', 'setup', 'true') + $extra
  $null = & $adb @a
}
function WaitResult([int]$sec) {
  $end = (Get-Date).AddSeconds($sec)
  while ((Get-Date) -lt $end) {
    $log = @(& $adb logcat -d -s 'LodscHd:*')
    foreach ($l in $log) {
      $m = [regex]::Match($l, 'result (ok models=\d+|fail code=\S+)')
      if ($m.Success) { return $m.Groups[1].Value }
    }
    Start-Sleep -Milliseconds 500
  }
  return 'TIMEOUT'
}
# chờ màn hình cài đặt sẵn sàng (nút nhập bật); trả về các nút
function WaitSetupReady([int]$sec) {
  $end = (Get-Date).AddSeconds($sec)
  while ((Get-Date) -lt $end) {
    $nodes = UiNodes
    $b = FindNode $nodes $strings['hd_import']
    if ($b -and $b.enabled -eq 'true') { return $nodes }
    Start-Sleep -Seconds 2
  }
  return $null
}
function WaitShell([string]$cmd, [int]$sec) {
  $end = (Get-Date).AddSeconds($sec)
  while ((Get-Date) -lt $end) {
    if ((RunAs "$cmd && echo YES; true") -contains 'YES') { return $true }
    Start-Sleep -Seconds 2
  }
  return $false
}

# ---------------------------------------------------------------- 0. máy
if ((Sh 'getprop sys.boot_completed') -notcontains '1') { Write-Output 'LOI: khong co gia lap/may Android san sang (adb)'; exit 1 }
New-Item -ItemType Directory -Force $work | Out-Null

# ---------------------------------------------------------------- 1. sinh các gói thử (Python, dữ liệu tổng hợp)
$gen = @'
import hashlib, io, json, os, shutil, struct, sys, warnings, zipfile, zlib
warnings.simplefilter('ignore')
ROOT, OUT = sys.argv[1], sys.argv[2]
sys.path.insert(0, os.path.join(ROOT, 'tools', 'sc_remaster', 'spec'))
import synth_cube as S
res = S.build()
tree = os.path.join(OUT, 'tree')
zips = os.path.join(OUT, 'zips')
for d in (tree, zips):
    shutil.rmtree(d, ignore_errors=True)
os.makedirs(zips)
S.write_out(res, tree)
rem = os.path.join(tree, 'remaster')
key = res['key']
rd = lambda p: open(p, 'rb').read()
sha1 = lambda b: hashlib.sha1(b).hexdigest()
index = rd(os.path.join(rem, 'index.tsv'))
lrm = rd(os.path.join(rem, 'models', key + '.lrm'))
texs = sorted(os.listdir(os.path.join(rem, 'textures')))
pngs = [('remaster/textures/' + n, rd(os.path.join(rem, 'textures', n))) for n in texs]
def manifest(tag):
    return json.dumps({'format': 1, 'tool': 'remaster_import.ps1', 'pipeline': tag, 'quality': 'mobile',
                       'models': [{'key': key, 'label': 'sample_cube'}], 'failed': []}, sort_keys=True).encode()
DIRS = [('remaster/', b''), ('remaster/models/', b''), ('remaster/textures/', b'')]
DOC = ('DOC_TRUOC.txt', b'Goi tong hop de thu RemasterImport (khong phai du lieu Sony).\r\n')
def base(idx=index, man=manifest('test')):
    out = [('remaster/index.tsv', idx)]
    if man is not None:
        out.append(('remaster/manifest.json', man))
    return out + [('remaster/models/%s.lrm' % key, lrm)] + pngs
FULL = DIRS + base() + [DOC]
def png(w, h):
    raw = b''.join(b'\x00' + b'\x00\x00\x00\xff' * w for _ in range(h))
    ch = lambda t, d: struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + ch(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)) + ch(b'IDAT', zlib.compress(raw))
            + ch(b'IEND', b''))
def lrm_head(k):
    return b'LRM1' + struct.pack('<HH', 1, 0) + bytes.fromhex(k) + struct.pack('<HHIB3x', 1, 0, 0, 0) + b'synthetic'.ljust(24, b'\0')
class NoSeek(io.RawIOBase):
    def __init__(self, f):
        self.f = f
    def writable(self):
        return True
    def write(self, b):
        self.f.write(b)
        return len(b)
def mkzip(path, entries, stream=False, ctype=zipfile.ZIP_DEFLATED):
    with open(path, 'wb') as f:
        with zipfile.ZipFile(NoSeek(f) if stream else f, 'w') as z:
            for name, data in entries:
                zi = zipfile.ZipInfo('x', (2026, 10, 19, 0, 0, 0))
                zi.filename = name   # giu nguyen ten la ('\\', '/' dau, '..')
                if name.endswith('/'):
                    zi.external_attr = (0o40755 << 16) | 0x10
                else:
                    zi.compress_type = ctype
                    zi.external_attr = 0o644 << 16
                z.writestr(zi, data)
cases = []
def tree_lines(entries):
    return sorted('%s  %s' % (sha1(d), n) for n, d in entries if n.startswith('remaster/') and not n.endswith('/'))
# extras: file = ten tep zip tren may (mac dinh <ten ca>.zip), total_cap / reserve = gioi han thu
def ok(name, entries, models, stream=False, ctype=zipfile.ZIP_DEFLATED, **extras):
    mkzip(os.path.join(zips, extras.get('file', name + '.zip')), entries, stream, ctype)
    cases.append(dict(name=name, expect='ok models=%d' % models, tree=tree_lines(entries), extras=extras))
def bad(name, entries, code, stream=False, raw=None, patch=None, ctype=zipfile.ZIP_DEFLATED, mutate=None, **extras):
    p = os.path.join(zips, name + '.zip')
    if raw is not None:
        open(p, 'wb').write(raw)
    else:
        mkzip(p, entries, stream, ctype)
    if patch is not None:
        b = open(p, 'rb').read()
        assert b.count(patch[0]) == 2 and len(patch[0]) == len(patch[1])
        open(p, 'wb').write(b.replace(patch[0], patch[1]))
    if mutate is not None:
        b = mutate(open(p, 'rb').read())
        open(p, 'wb').write(b)
    cases.append(dict(name=name, expect='fail code=' + code, tree=None, extras=extras))
def repl(entries, name, data):
    return [(n, data if n == name else d) for n, d in entries]
k2 = 'cd' * 20
ok('valid', FULL, 1)
bad('dotdot', FULL + [('../evil.txt', b'x')], 'bad_zip/unsafe')
bad('dotdot_inner', FULL + [('remaster/../../evil.txt', b'x')], 'bad_zip/unsafe')
bad('absolute', FULL + [('/data/data/vn.lodsc/files/evil.txt', b'x')], 'bad_zip/unsafe')
bad('backslash', FULL + [('remaster\\..\\evil.txt', b'x')], 'bad_zip/unsafe')
bad('colon', FULL + [('remaster/models/C:evil.lrm', b'x')], 'bad_zip/unsafe')
bad('dot_segment', [('./remaster/index.tsv', index)] + FULL, 'bad_zip/unsafe')
bad('empty_segment', FULL + [('remaster//evil.txt', b'x')], 'bad_zip/unsafe')
bad('extra_in_remaster', FULL + [('remaster/extra.txt', b'x')], 'wrong_format/extra')
bad('extra_root', FULL + [('readme.txt', b'x')], 'wrong_format/extra')
bad('extra_dir', FULL + [('remaster/other/', b'')], 'wrong_format/extra')
bad('nested_folder', [('LoDHD/' + n, d) for n, d in FULL], 'wrong_format/extra')
bad('upper_hex', DIRS + base() + [('remaster/models/%s.lrm' % key.upper(), lrm)], 'wrong_format/extra')
bad('dup_entry', FULL + [('remaster/index.tsv', index)], 'bad_zip/dup')
bad('lrm_magic', repl(FULL, 'remaster/models/%s.lrm' % key, b'LRM2' + lrm[4:]), 'wrong_format/lrm')
bad('lrm_version', repl(FULL, 'remaster/models/%s.lrm' % key, lrm[:4] + b'\x02\x00' + lrm[6:]), 'wrong_format/lrm')
bad('lrm_short', repl(FULL, 'remaster/models/%s.lrm' % key, lrm[:32]), 'wrong_format/lrm')
bad('lrm_key_mismatch', DIRS + [('remaster/index.tsv', b'LRMINDEX\t1\n%s\tmodels/%s.lrm\tx\n' % (k2.encode(), k2.encode())),
                                ('remaster/models/%s.lrm' % k2, lrm)] + pngs, 'wrong_format/lrm')
bad('png_wrong_name', FULL + [('remaster/textures/%s.png' % k2, pngs[0][1])], 'wrong_format/png')
junk = b'not a png at all, but named by its sha1'
bad('png_not_png', FULL + [('remaster/textures/%s.png' % sha1(junk), junk)], 'wrong_format/png')
p100 = png(100, 64)
bad('png_not_pow2', FULL + [('remaster/textures/%s.png' % sha1(p100), p100)], 'wrong_format/png')
p4k = png(4096, 1)
bad('png_too_big', FULL + [('remaster/textures/%s.png' % sha1(p4k), p4k)], 'wrong_format/png')
bad('index_header', repl(FULL, 'remaster/index.tsv', index.replace(b'LRMINDEX\t1', b'LRMINDEX\t2')), 'wrong_format/index')
bad('index_crlf', repl(FULL, 'remaster/index.tsv', index.replace(b'\n', b'\r\n')), 'wrong_format/index')
bad('index_bom', repl(FULL, 'remaster/index.tsv', b'\xef\xbb\xbf' + index), 'wrong_format/index')
bad('index_path', repl(FULL, 'remaster/index.tsv', b'LRMINDEX\t1\n%s\tmodels/%s.lrm\tx\n' % (key.encode(), k2.encode())),
    'wrong_format/index')
bad('index_dup', repl(FULL, 'remaster/index.tsv', index + index.split(b'\n', 1)[1]), 'wrong_format/index')
bad('index_fields', repl(FULL, 'remaster/index.tsv', b'LRMINDEX\t1\n%s\tmodels/%s.lrm\n' % (key.encode(), key.encode())),
    'wrong_format/index')
bad('index_utf8', repl(FULL, 'remaster/index.tsv', b'LRMINDEX\t1\n%s\tmodels/%s.lrm\t\xff\n' % (key.encode(), key.encode())),
    'wrong_format/index')
bad('no_index', [e for e in FULL if e[0] != 'remaster/index.tsv'], 'wrong_format/noindex')
bad('missing_lrm', [e for e in FULL if not e[0].endswith('.lrm')], 'wrong_format/missing')
bad('manifest_format2', repl(FULL, 'remaster/manifest.json', b'{"format": 2}'), 'wrong_format/manifest')
bad('manifest_not_json', repl(FULL, 'remaster/manifest.json', b'not json'), 'wrong_format/manifest')
bad('big_declared', repl(FULL, 'remaster/manifest.json', b' ' * ((64 << 20) + 1)), 'bad_zip/big')
# luong khong tua (data descriptor, khong khai co truoc): bo muc thu muc vi ZipInputStream chi nhan descriptor cho muc DEFLATED
bad('big_stream', repl(base() + [DOC], 'remaster/manifest.json', b' ' * ((64 << 20) + 1)), 'bad_zip/big', stream=True)
bad('index_big', repl(FULL, 'remaster/index.tsv', index + b'\n' * (4 << 20)), 'bad_zip/big')
bad('manifest_big', repl(FULL, 'remaster/manifest.json', b' ' * ((4 << 20) + 1)), 'bad_zip/big')
# JSON long qua sau: org.json doc de quy -> StackOverflowError phai thanh loi dinh dang, khong de lai remaster.import
bad('manifest_deep', repl(FULL, 'remaster/manifest.json', b'[' * (3 << 20)), 'wrong_format/manifest')
# ten muc khong phai UTF-8 (byte 0xff, co EFS = 0): ZipInputStream nem IllegalArgumentException
bad('name_not_utf8', FULL + [('remaster/xZ.txt', b'x')], 'bad_zip/corrupt', patch=(b'remaster/xZ.txt', b'remaster/x\xff.txt'))
bad('total_cap', FULL, 'bad_zip/total', total_cap=100000)
bad('too_many', DIRS + base() + [('remaster/models/%040x.lrm' % i, lrm_head('%040x' % i)) for i in range(1, 4095)],
    'bad_zip/many')
bad('no_space', FULL, 'no_space', reserve=1 << 50)
bad('not_zip', None, 'bad_zip/empty', raw=os.urandom(4096))
whole = open(os.path.join(zips, 'valid.zip'), 'rb').read()
bad('truncated', None, 'bad_zip/corrupt', raw=whole[:len(whole) // 2])
# --- them (kiem doc lap): cach ghi zip khac, ten Unicode, CRC sai, ma hoa, zip rong, phan dau thua
# muc STORED ghi vao luong khong tua -> co data descriptor: JDK may tinh nem ZipException, ZipInputStream cua Android
# doc lech (muc rong) roi dung som -> phai bi bat o buoc kiem muc luc cuoi zip
bad('stored_stream', base() + [DOC], 'bad_zip/incomplete', stream=True, ctype=zipfile.ZIP_STORED)
def flip_lrm(b):
    i = b.find(lrm)
    assert i > 0 and b.count(lrm) == 1 and len(lrm) > 0x80
    b = bytearray(b)
    b[i + len(lrm) // 2] ^= 0xff   # sau header 0x40: chi CRC cua muc phat hien
    return bytes(b)
bad('crc_bad', FULL, 'bad_zip/corrupt', ctype=zipfile.ZIP_STORED, mutate=flip_lrm)
def encrypt_first(b):
    assert b[:4] == b'PK\x03\x04'
    b = bytearray(b)
    b[6] |= 1   # co "ma hoa" o muc dau
    return bytes(b)
bad('encrypted', FULL, 'bad_zip/corrupt', mutate=encrypt_first)
bad('unicode_entry', FULL + [('remaster/textures/\u1ea3nh_m\u00f4_h\u00ecnh.png', pngs[0][1])], 'wrong_format/extra')
bad('lrm_as_dir', FULL + [('remaster/models/%s.lrm/' % k2, b'')], 'wrong_format/extra')
bad('dup_note', FULL + [DOC], 'bad_zip/dup')
bad('note_only', [DOC], 'wrong_format/noindex')
bad('empty_zip', [], 'bad_zip/empty')
bad('preamble', None, 'bad_zip/empty', raw=b'MZ' * 512 + whole)
# zip khong tron ven ma ZipInputStream van doc "het" binh thuong: cat dung ranh gioi truoc PNG dau (index + .lrm du, thieu
# texture), cat ngay dau muc luc (du moi muc, khong co muc luc), cat giua muc luc, muc luc dem sai, du lieu thua sau EOCD
zi_png = [i for i in zipfile.ZipFile(io.BytesIO(whole)).infolist() if i.filename.endswith('.png')][0]
eocd = whole.rfind(b'PK\x05\x06')
cd_off = struct.unpack('<I', whole[eocd + 16:eocd + 20])[0]
cd_n = struct.unpack('<H', whole[eocd + 10:eocd + 12])[0]
assert 0 < zi_png.header_offset < cd_off < eocd and eocd + 22 == len(whole)
bad('cut_boundary', None, 'bad_zip/incomplete', raw=whole[:zi_png.header_offset])
bad('no_cd', None, 'bad_zip/incomplete', raw=whole[:cd_off])
bad('cut_in_cd', None, 'bad_zip/incomplete', raw=whole[:(cd_off + eocd) // 2])
bad('cd_count', None, 'bad_zip/incomplete',
    raw=whole[:eocd + 8] + struct.pack('<HH', cd_n - 1, cd_n - 1) + whole[eocd + 12:])
bad('trailing_junk', None, 'bad_zip/incomplete', raw=whole + b'\0' * 64)
def with_comment(path, entries):
    mkzip(path, entries)
    with zipfile.ZipFile(path, 'a') as z:
        z.comment = b'LoD SC VN mo hinh HD ' * 100
ok('valid_comment', FULL, 1, file='valid_comment.zip')
with_comment(os.path.join(zips, 'valid_comment.zip'), FULL)
ok('minimal', base(man=None), 1)
ok('valid_stored', FULL, 1, ctype=zipfile.ZIP_STORED)
ok('valid_stream', base() + [DOC], 1, stream=True)
ok('valid_unicode_file', FULL, 1, file='M\u00f4H\u00ecnhHD_\u0111\u00e3_xu\u1ea5t.zip')
idx2 = index.replace('sample_cube'.encode(), b'sample_cube v2')
ok('valid2', DIRS + base(idx=idx2, man=manifest('v2')) + [DOC], 1)
json.dump(cases, open(os.path.join(OUT, 'cases.json'), 'w'), indent=1)
print('%d ca, modelKey %s' % (len(cases), key))
'@
$genPy = Join-Path $work 'gen_cases.py'
Set-Content -Path $genPy -Value $gen -Encoding Ascii
$out = & python $genPy $root $work
if ($LASTEXITCODE) { Write-Output $out; Write-Output 'LOI: khong sinh duoc goi thu'; exit 1 }
Write-Output "goi thu: $($out | Select-Object -Last 1)"
$cases = Get-Content (Join-Path $work 'cases.json') -Raw | ConvertFrom-Json
$cases = @($cases | ForEach-Object { $_ })   # PowerShell 5.1: ConvertFrom-Json trả mảng như một phần tử

# ---------------------------------------------------------------- 2. chốt chặn make_apk + dựng APK
$guard = & python (Join-Path $root 'android\make_apk.py') --selftest-guards
Check ($LASTEXITCODE -eq 0) "make_apk.py --selftest-guards ($($guard | Select-Object -Last 1))"
if ($Build -or $Determinism) {
  $hashes = @()
  $n = 1
  if ($Determinism) { $n = 2 }
  for ($i = 0; $i -lt $n; $i++) {
    $b = & python (Join-Path $root 'android\make_apk.py') --version 0.2 --abi x86_64
    if ($LASTEXITCODE) { Write-Output $b; Write-Output 'LOI: make_apk.py'; exit 1 }
    $hashes += (Get-FileHash $apk -Algorithm SHA256).Hash
    Write-Output "dung APK: $($b | Select-Object -Last 1)"
  }
  if ($Determinism) { Check ($hashes[0] -eq $hashes[1]) "dung 2 lan cung SHA-256 ($($hashes[0]) / $($hashes[1]))" }
}
if (-not $NoInstall) {
  $r = cmd /c "`"$adb`" install -r `"$apk`" 2>&1"
  Check (($r | Out-String) -match 'Success') "cai APK (adb install -r, giu du lieu)"
}
$flags = (Sh "dumpsys package $pkg") -match 'flags=\[.*DEBUGGABLE'
if (-not $flags) { Write-Output 'LOI: app khong phai ban debuggable (can make_apk.py --abi x86_64)'; exit 1 }

# ---------------------------------------------------------------- 3. đẩy gói lên máy, cất dữ liệu có sẵn
$null = AdbQuiet 'shell rm -rf /data/local/tmp/hdzips'
$null = AdbQuiet "push `"$(Join-Path $work 'zips')`" /data/local/tmp/hdzips"
# lần thử trước bị ngắt giữa chừng: trả dữ liệu đã cất về game/ trước
$rest = RunAs 'cd files && if ls -A hdtest_backup 2>/dev/null | grep -q . ; then for f in remaster remaster.properties; do if [ -e hdtest_backup/$f ]; then rm -rf game/$f && mv hdtest_backup/$f game/; fi; done; echo RESTORED; fi'
if ($rest -contains 'RESTORED') { Write-Output 'tra lai du lieu da cat tu lan thu truoc bi ngat' }
$null = RunAs 'rm -rf files/hdtest && mkdir -p files/hdtest files/hdtest_backup && cp /data/local/tmp/hdzips/*.zip files/hdtest/'
$null = AdbQuiet 'shell rm -rf /data/local/tmp/hdzips'
$had = (RunAs 'cd files/game && ls -d remaster remaster.properties 2>/dev/null; true') | Where-Object { $_ -match '\S' }
if ($had) {
  Write-Output "cat du lieu co san: $($had -join ', ')"
  $null = RunAs 'cd files/game && for f in remaster remaster.properties; do if [ -e $f ]; then mv $f ../hdtest_backup/; fi; done'
}
$null = RunAs 'cd files/game && rm -rf remaster remaster.import remaster.old remaster.properties remaster.properties.tmp'

# ---------------------------------------------------------------- 4. các ca nhập
$okProps = "enabled=true`ntextures=hd`nlog=false"
foreach ($c in $cases) {
  if ($Only -and $c.name -notmatch $Only) { continue }
  $before = Snapshot
  $file = "$($c.name).zip"
  if ($c.extras.file) { $file = [string]$c.extras.file }   # ten tep Unicode (khong dau cach: adb shell tach theo dau cach)
  $extra = @('--es', 'hd_test_zip', "hdtest/$file")
  if ($c.extras.total_cap) { $extra += @('--el', 'hd_test_total_cap', [string]$c.extras.total_cap) }
  if ($c.extras.reserve) { $extra += @('--el', 'hd_test_reserve', [string]$c.extras.reserve) }
  StartSetup $extra
  $res = WaitResult 180
  $nodes = UiNodes
  $texts = @($nodes | ForEach-Object { $_.text } | Where-Object { $_ })
  $after = Snapshot
  $left = Leftovers
  if ($c.expect -like 'ok*') {
    $want = (@($c.tree) | Sort-Object) -join "`n"
    $prefix = Prefix 'hd_ok'
    $ui = @($texts | Where-Object { $_.StartsWith($prefix) }).Count -gt 0
    $good = ($res -eq $c.expect) -and ((TreeOf $after) -eq $want) -and ((Props) -eq $okProps) -and ($left.Count -eq 0) -and $ui
    Check $good "$($c.name): $res (cay remaster $(if ((TreeOf $after) -eq $want) {'trung'} else {'KHAC'}), properties $(if ((Props) -eq $okProps) {'dung'} else {'SAI'}), con sot $($left.Count), thong bao $(if ($ui) {'co'} else {'KHONG'}))"
  } else {
    $code = $c.expect.Substring('fail code='.Length)
    $kind = ($code -split '/')[0]
    $why = ''
    if ($code.Contains('/')) { $why = ($code -split '/')[1] }
    $kp = Prefix ("hd_$kind")
    $wp = ''
    if ($why) { $wp = Prefix ("hd_why_$why") }
    $ui = @($texts | Where-Object { $_.StartsWith($kp) -and $_.Contains($wp) }).Count -gt 0
    $same = $after -eq $before
    $good = ($res -eq $c.expect) -and $same -and ($left.Count -eq 0) -and $ui
    Check $good "$($c.name): $res (mong $($c.expect); remaster $(if ($same) {'giu nguyen'} else {'BI DOI'}), con sot $($left.Count) $($left -join ' '), thong bao tieng Viet $(if ($ui) {'co'} else {'KHONG'}))"
  }
}
if ($Only) {
  Write-Output "(chi chay ca khop '$Only')"
}

# ---------------------------------------------------------------- 5. công tắc Bật/Tắt
if ((RunAs 'test -f files/game/remaster/index.tsv && echo YES; true') -notcontains 'YES') {
  StartSetup @('--es', 'hd_test_zip', 'hdtest/valid.zip')   # cần có dữ liệu (ví dụ khi chạy -Only)
  $null = WaitResult 60
}
$null = RunAs 'cd files/game && echo enabled=true > remaster.properties && echo textures=retail >> remaster.properties && echo log=true >> remaster.properties'
StartSetup @()
$nodes = WaitSetupReady 60
$on = $null
if ($nodes) { $on = FindNode $nodes $strings['hd_on'] }
Check ($null -ne $on -and $on.enabled -eq 'true') "nut '$($strings['hd_on'])' hien va bam duoc khi enabled=true"
if ($on) {
  TapNode $on
  Start-Sleep -Seconds 2
  Check ((Props) -eq "enabled=false`ntextures=retail`nlog=true") "bam lan 1 -> enabled=false, giu textures=retail, log=true"
  $off = FindNode (UiNodes) $strings['hd_off']
  Check ($null -ne $off) "nut doi thanh '$($strings['hd_off'])'"
  if ($off) {
    TapNode $off
    Start-Sleep -Seconds 2
    Check ((Props) -eq "enabled=true`ntextures=retail`nlog=true") "bam lan 2 -> enabled=true"
  }
}
# giá trị lạ / hoa thường: giữ đúng nghĩa runtime (sc-vi RemasterConfig: textures lạ -> retail, log TRUE -> true)
$null = RunAs 'cd files/game && echo enabled=false > remaster.properties && echo textures=Foo >> remaster.properties && echo log=TRUE >> remaster.properties'
StartSetup @()
$nodes = WaitSetupReady 60
$off = $null
if ($nodes) { $off = FindNode $nodes $strings['hd_off'] }
if ($off) {
  TapNode $off
  Start-Sleep -Seconds 2
}
Check ((Props) -eq "enabled=true`ntextures=retail`nlog=true") "textures=Foo, log=TRUE -> bam Bat ghi textures=retail, log=true (nhu runtime)"
# BOM UTF-8 ở đầu remaster.properties: runtime bỏ BOM (enabled=true vẫn là bật) -> app cũng phải hiện "Bật" và ghi lại không BOM
$null = RunAs 'cd files/game && printf \\357\\273\\277enabled=true\\ntextures=retail\\nlog=false\\n > remaster.properties'
StartSetup @()
$nodes = WaitSetupReady 60
$on = $null
if ($nodes) { $on = FindNode $nodes $strings['hd_on'] }
Check ($null -ne $on) "remaster.properties co BOM + enabled=true -> nut '$($strings['hd_on'])' (nhu runtime)"
if ($on) {
  TapNode $on
  Start-Sleep -Seconds 2
}
$raw = @(RunAs 'od -An -c files/game/remaster.properties | head -1') -join ' '
Check (((Props) -eq "enabled=false`ntextures=retail`nlog=false") -and ($raw -notmatch '357')) "bam Tat voi tep co BOM -> enabled=false, textures=retail, log=false, khong con BOM"
$null = RunAs 'cd files/game && echo enabled=true > remaster.properties && echo textures=hd >> remaster.properties && echo log=false >> remaster.properties'
$state = Snapshot

# ---------------------------------------------------------------- 6. khôi phục sau khi bị tắt giữa lúc đổi chỗ
$null = RunAs 'cd files/game && mv remaster remaster.old && mkdir -p remaster.import/remaster && echo x > remaster.import/remaster/junk'
StartSetup @()
$ok1 = WaitShell 'cd files/game && test -d remaster && ! test -e remaster.import && ! test -e remaster.old' 60
Check ($ok1 -and ((Snapshot) -eq $state)) 'khoi phuc: remaster.old -> remaster, xoa remaster.import (du lieu trung truoc)'
$null = RunAs 'cd files/game && cp -r remaster remaster.old'
StartSetup @()
$ok2 = WaitShell 'cd files/game && ! test -e remaster.old' 60
Check ($ok2 -and ((Snapshot) -eq $state)) 'khoi phuc: co ca remaster va remaster.old -> xoa remaster.old'

# ---------------------------------------------------------------- 7. cài lại / cập nhật APK
$r = cmd /c "`"$adb`" install -r `"$apk`" 2>&1"
Check ((($r | Out-String) -match 'Success') -and ((Snapshot) -eq $state)) 'cai lai APK: giu game/remaster va remaster.properties'
StartSetup @()
$null = WaitSetupReady 120
Check ((Snapshot) -eq $state) 'mo app sau khi cai lai: du lieu giu nguyen'
if (-not $NoUpdate) {
  $null = RunAs 'echo stale > files/game/vi/hd_stale_marker.txt && rm files/payload.version'
  StartSetup @()
  $ok3 = WaitShell 'test -f files/payload.version && ! test -e files/game/vi/hd_stale_marker.txt' 600
  $null = WaitSetupReady 120
  Check ($ok3 -and ((Snapshot) -eq $state)) 'cap nhat APK (giai nen lai payload, xoa Payload.PROGRAM): giu game/remaster va remaster.properties'
}
# cập nhật thật: APK x86_64 dựng từ gói Windows v0.3 (versionCode cao hơn, payload khác) cài đè, rồi hạ lại bản đang thử (-d)
if ($RealUpdate) {
  $apk3 = Join-Path $root 'out\android\LoD-SC-VN-v0.3-android-x86_64.apk'
  $b = & python (Join-Path $root 'android\make_apk.py') --version 0.3 --abi x86_64
  if ($LASTEXITCODE) { Write-Output $b; Fail 'dung APK x86_64 tu goi v0.3' } else {
    $v0 = @(RunAs 'cat files/payload.version')[0].Trim()
    $r = cmd /c "`"$adb`" install -r `"$apk3`" 2>&1"
    $vc = @(Sh "dumpsys package $pkg") -match 'versionCode=3001\b'
    StartSetup @()
    $ok4 = WaitShell "test -f files/payload.version && test `$(cat files/payload.version) != $v0" 600
    $null = WaitSetupReady 120
    Check ((($r | Out-String) -match 'Success') -and $vc -and $ok4 -and ((Snapshot) -eq $state)) "cap nhat that len v0.3 (versionCode 3001, giai nen payload moi): giu game/remaster va remaster.properties"
    $r = cmd /c "`"$adb`" install -r -d `"$apk`" 2>&1"
    StartSetup @()
    $ok5 = WaitShell "test -f files/payload.version && test `$(cat files/payload.version) = $v0" 600
    $null = WaitSetupReady 120
    Check ((($r | Out-String) -match 'Success') -and $ok5 -and ((Snapshot) -eq $state)) "ha lai ban dang thu (install -r -d): giu game/remaster va remaster.properties"
  }
}

# ---------------------------------------------------------------- 8. nhập thật qua trình chọn tệp (SAF)
if ($Saf) {
  $safName = 'LoDHD_saf_test.zip'
  $null = AdbQuiet "push `"$(Join-Path $work 'zips\valid.zip')`" /sdcard/Download/$safName"
  StartSetup @()
  $nodes = WaitSetupReady 60
  $btn = $null
  if ($nodes) { $btn = FindNode $nodes $strings['hd_import'] }
  $res = 'KHONG BAM DUOC'
  if ($btn) {
    TapNode $btn
    Start-Sleep -Seconds 4
    $file = $null
    for ($i = 0; $i -lt 3 -and -not $file; $i++) {
      $ns = UiNodes
      foreach ($n in $ns) { if ($n.text -eq $safName) { $file = $n } }
      if (-not $file) {
        $roots = $null
        foreach ($n in $ns) { if ($n.'content-desc' -eq 'Show roots') { $roots = $n } }
        if ($roots) { TapNode $roots; Start-Sleep -Seconds 2 }
        foreach ($n in (UiNodes)) { if ($n.text -eq 'Downloads') { TapNode $n; Start-Sleep -Seconds 3; break } }
      }
    }
    if ($file) {
      $null = AdbQuiet 'logcat -c'
      TapNode $file
      $res = WaitResult 120
    } else { $res = 'KHONG THAY TEP TRONG TRINH CHON' }
  }
  $want = (@(($cases | Where-Object { $_.name -eq 'valid' }).tree) | Sort-Object) -join "`n"
  Check (($res -eq 'ok models=1') -and ((TreeOf (Snapshot)) -eq $want)) "nhap qua nut + trinh chon tep Android: $res"
  $null = AdbQuiet "shell rm -f /sdcard/Download/$safName"
}

# ---------------------------------------------------------------- 9. dọn
$null = Sh "am force-stop $pkg"
$null = RunAs 'rm -rf files/hdtest'
if (-not $Keep) {
  $null = RunAs 'cd files/game && rm -rf remaster remaster.import remaster.old remaster.properties remaster.properties.tmp'
  if ($had) { $null = RunAs 'cd files/hdtest_backup && for f in remaster remaster.properties; do if [ -e $f ]; then mv $f ../game/; fi; done' }
}
$null = RunAs 'rmdir files/hdtest_backup 2>/dev/null; true'
$null = AdbQuiet 'shell rm -f /sdcard/hd_ui.xml'

Write-Output ''
if ($script:fails -eq 0) { Write-Output "DAT: $($script:passes) muc" ; exit 0 }
Write-Output "KHONG DAT: $($script:fails) loi / $($script:passes + $script:fails) muc"
exit 1
