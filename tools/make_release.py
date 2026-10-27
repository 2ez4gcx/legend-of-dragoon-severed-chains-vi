"""Đóng gói bản tiếng Việt The Legend of Dragoon cho Severed Chains (Windows), ghim theo commit SC.

Cách gọi:
    python tools/make_release.py --version 0.1 [--sc-zip dl/Severed_Chains_Windows.zip] [--game game] [--no-build]

Gói ra: release/LoD-SC-VN-v<ver>-sc-<commit7>-windows.zip (+ release/SHA256SUMS.txt) chứa một thư mục
"Severed Chains (VN)/" gồm:
    - NGUYÊN bản build SC Windows đúng commit SC_COMMIT (lấy từ zip đã lưu, kiểm SHA-256 SC_ZIP_SHA) — GitHub chỉ giữ
      bản devbuild cuốn chiếu nên phải kèm bản build để ghim; mã nguồn SC có sẵn trong lod-game-<commit>-sources.jar.
    - vi/sc-vi.jar (lớp sửa lõi), vi/NGUON/ (mã nguồn sc-vi + diff + tự kiểm + công cụ sinh dữ liệu, theo AGPL-3.0),
      vi/VERSION.txt (commit D:\\LOD-SC, D:\\LOD, SC), vi/LICENSE (AGPL-3.0 của SC).
    - lang/lod.vi.lang, lang/scvi.vi.lang, lang/core.vi.lang, lang/unpacker.vi.lang, lang/turnorder.vi.lang,
      lang/scvi_ui.vi.lang (mục tùy chọn sc-vi thêm: Tốc độ game, Tự bỏ khung hình, Tiết kiệm pin),
      lang/dialogue.vi.tsv, gfx/fonts/vietnamese.json/.png, gfx/ui/title_menu.vi.png/.widths (menu màn tựa),
      gfx/textures/icon.vi.png (biểu tượng cửa sổ game, tranh chú rồng; không đè icon.png của SC),
      vi/files/ (lớp phủ đồ hoạ tiếng Việt: ảnh đã duyệt của bản PS1, Loader đọc thay files/)
    - config.dcnf tối giản: ngôn ngữ = vi, phông chữ = vietnamese.json (mọi mục khác để SC tự đặt mặc định)
    - launch-vi.bat (sinh từ launch.bat của bản build: tự tải JDK 25 như bản gốc, kiểm đúng jar commit, thêm vi/sc-vi.jar
      vào ĐẦU classpath), HUONG_DAN_VIET_HOA.txt.
Không chứa: ảnh đĩa, BIOS, JDK, files/ (SC tự giải nén từ đĩa của người chơi).

Nguồn dựng: commit HEAD của repo D:\\LOD-SC (git archive — không lấy thay đổi chưa commit), dữ liệu dịch D:\\LOD
(biến LOD_ROOT). Biên dịch bằng tools/build_sc_vi.ps1 (JDK 25 + jar của thư mục --game, phải đúng commit).
Kết quả xác định: mọi mục trong zip có thời gian cố định, thứ tự cố định; sc-vi.jar đóng bằng zipfile (không dùng công cụ jar).
"""
import argparse
import hashlib
import io
import os
import shutil
import struct
import subprocess
import sys
import tarfile
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
LOD = os.environ.get('LOD_ROOT', os.path.join(ROOT, '..', 'LOD'))

SC_COMMIT = 'affcef0cba71819515fdf05521c1fedb1d7a92f0'
SC_ZIP_SHA = '88abbfb28492400168070fdc03ddfdff4b4e4781277d2de0195d17445bbf0800'
SC_JAR = 'lod-game-%s.jar' % SC_COMMIT
PKG = 'Severed Chains (VN)'
FIXED_TIME = (2026, 10, 16, 0, 0, 0)


# biểu tượng cửa sổ game: build_sc_vi.ps1 chạy android/gen_icon.py --windows trên bản xuất từ HEAD
ICON_SRC = ('android/gen_icon.py', 'android/icon_rong.webp')


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def git(*args, cwd=ROOT):
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True).stdout


def config_dcnf():
    """legend.game.saves.ConfigStorage: u32 số mục; mục = mã (độ dài 3 byte LE + ASCII) + u32 độ dài + giá trị."""
    def ascii3(s):
        b = s.encode('ascii')
        return len(b).to_bytes(3, 'little') + b

    def rec(key, value):
        return ascii3(key) + struct.pack('<I', len(value)) + value

    lang = bytes([2]) + b'vi'                             # LanguageConfigEntry: writeAscii(lang, 1)
    font = struct.pack('<H', len('vietnamese.json')) + b'vietnamese.json'   # StringConfigEntry: độ dài u16
    return struct.pack('<I', 2) + rec('lod_core:language', lang) + rec('lod_core:retail_font', font)


def launch_vi(launch_bat):
    """launch-vi.bat từ launch.bat của bản build: giữ nguyên phần tải JDK, thêm kiểm jar + vi/sc-vi.jar.

    Đường dẫn có chữ ngoài bảng mã ANSI của Windows (ví dụ "Giả lập" trên Windows tiếng Anh): java.exe tìm thư mục của chính
    nó bằng API ANSI nên báo "could not find java.dll" dù tệp vẫn ở đó. Khi đó tạm gán một ổ ảo (subst, không cần quyền
    admin) cho thư mục game, chạy từ ổ đó và gỡ ổ khi thoát; không gán được thì báo cách khắc phục.
    """
    src = launch_bat.replace('\r\n', '\n')
    lines = src.split('\n')
    out = []
    java_seen = False
    java_line = False
    for ln in lines:
        if ln.strip() == 'if exist ".\\jdk25\\bin\\java.exe" (' and not java_seen:
            out += [
                'if not exist "%SC_JAR%" goto WRONG_SC',
                'if not exist "vi\\sc-vi.jar" goto NO_VI',
                '',
            ]
            java_seen = True
        if java_line and ln.strip() == 'exit 0':
            out.append('call :VI_UNSUBST')
        java_line = False
        if ln.startswith('".\\jdk25\\bin\\java"'):
            assert '-cp "lod-game-' in ln, 'dong java khong nhu mong doi'
            ln = ln.replace('-cp "', '-cp "vi/sc-vi.jar;', 1)
            java_line = True
        if ln.strip() == 'exit 2':
            out.append('call :VI_UNSUBST')   # tải Java lỗi
        out.append(ln)
        if ln.strip() == '@echo off':
            out += [
                'chcp 65001 >nul',
                'cd /d "%~dp0"',
                'rem Bản Việt hoá The Legend of Dragoon cho Severed Chains — chỉ chạy với SC commit ' + SC_COMMIT[:7],
                'set "SC_JAR=' + SC_JAR + '"',
                '',
                'rem Đường dẫn có chữ mà bảng mã ANSI của Windows không có (ví dụ "Giả lập" trên Windows tiếng Anh): java.exe báo',
                'rem "could not find java.dll". Tạm gán ổ ảo cho thư mục game rồi chạy từ đó (gỡ khi thoát).',
                'set "VI_HOME=%CD%"',
                'set "VI_DRIVE="',
                'powershell -NoProfile -Command "$p=(Get-Location).Path; $e=[Text.Encoding]::Default; '
                'if ($e.GetString($e.GetBytes($p)) -ne $p) { exit 1 }"',
                'if errorlevel 1 call :VI_SUBST',
                'if errorlevel 1 goto VI_PATH_FAILED',
            ]
    assert java_seen, 'khong tim thay cho kiem JDK trong launch.bat'
    assert any(ln == 'call :VI_UNSUBST' for ln in out), 'khong tim thay dong exit sau lenh java'
    while out and not out[-1].strip():
        out.pop()
    out += [
        '',
        ': WRONG_SC',
        'call :VI_UNSUBST',
        'echo Không thấy %SC_JAR%.',
        'echo Severed Chains đã được cập nhật (nút Update) hoặc đây không phải thư mục của gói Việt hoá.',
        'echo Bản Việt hoá này chỉ chạy với Severed Chains commit ' + SC_COMMIT[:7] + '.',
        'echo Hãy giải nén lại gói Việt hoá vào thư mục mới (chép sang isos, saves nếu muốn giữ).',
        'echo Vẫn có thể chơi bản tiếng Anh bằng launch.bat.',
        'pause',
        'exit 1',
        '',
        ': NO_VI',
        'call :VI_UNSUBST',
        'echo Thiếu vi\\sc-vi.jar. Hãy giải nén lại gói Việt hoá.',
        'pause',
        'exit 1',
        '',
        ': VI_PATH_FAILED',
        'echo Thư mục game có chữ có dấu (hoặc ký tự đặc biệt) nên Java không chạy được:',
        'echo   %VI_HOME%',
        'echo Hãy chuyển cả thư mục "Severed Chains (VN)" tới chỗ chỉ có chữ không dấu, ví dụ C:\\Games\\LoD-VN, rồi chạy lại.',
        'pause',
        'exit 1',
        '',
        'rem Gán ổ ảo còn trống (Z: lùi về P:) cho thư mục game và chuyển vào đó',
        ':VI_SUBST',
        'for %%D in (Z Y X W V U T S R Q P) do if not defined VI_DRIVE if not exist %%D:\\ set "VI_DRIVE=%%D:"',
        'if not defined VI_DRIVE exit /b 1',
        'subst %VI_DRIVE% "%VI_HOME%" >nul 2>&1 || (set "VI_DRIVE=" & exit /b 1)',
        'cd /d %VI_DRIVE%\\',
        'echo Thư mục game có chữ có dấu nên Java không mở được trực tiếp. Tạm dùng ổ %VI_DRIVE% cho thư mục này trong lúc',
        'echo chơi (tự gỡ khi thoát game). Muốn khỏi bước này: chuyển thư mục tới chỗ chỉ có chữ không dấu.',
        'exit /b 0',
        '',
        ':VI_UNSUBST',
        'if not defined VI_DRIVE exit /b 0',
        'cd /d "%VI_HOME%"',
        'subst %VI_DRIVE% /d >nul 2>&1',
        'set "VI_DRIVE="',
        'exit /b 0',
        '',
    ]
    return '\r\n'.join(out).encode('utf-8')


def zip_dir_deterministic(src_dir, prefix=''):
    """[(tên trong zip, bytes)] sắp xếp theo tên."""
    items = []
    for dp, dn, fn in os.walk(src_dir):
        dn.sort()
        for f in sorted(fn):
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, src_dir).replace(os.sep, '/')
            items.append((prefix + rel, open(p, 'rb').read()))
    return sorted(items)


def jar_bytes(classes_dir):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        zi = zipfile.ZipInfo('META-INF/MANIFEST.MF', FIXED_TIME)
        zi.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(zi, 'Manifest-Version: 1.0\r\nCreated-By: LoD-SC-VN make_release.py\r\n\r\n')
        for name, data in zip_dir_deterministic(classes_dir):
            zi = zipfile.ZipInfo(name, FIXED_TIME)
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, data)
    return buf.getvalue()


def huong_dan(version, src_commit, lod_commit):
    return ('''BẢN VIỆT HOÁ THE LEGEND OF DRAGOON CHO SEVERED CHAINS — v{v} (thử nghiệm)
======================================================================

Severed Chains (SC) là bản chuyển The Legend of Dragoon sang PC (Java) của nhóm Legend of Dragoon Modding:
https://github.com/Legend-of-Dragoon-Modding/Severed-Chains — gói này kèm NGUYÊN bản build SC commit {sc7}
và phần Việt hoá. Không kèm dữ liệu game: bạn cần đĩa gốc của mình.

CẦN CÓ
- Windows 64-bit, card đồ hoạ hỗ trợ OpenGL 3.3, mạng Internet ở lần chạy đầu (tự tải Java 25, ~220 MB).
- Đủ 4 đĩa The Legend of Dragoon bản MỸ (NA, SCUS-94491/94584/94585/94586), file BIN (2352 byte/sector).
  Dùng đĩa GỐC, KHÔNG dùng đĩa đã vá tiếng Việt bản PS1 (SC sẽ báo "Patching failed").

CÀI ĐẶT
1. Giải nén cả thư mục "{pkg}" ra chỗ không có dấu chấm phẩy (;) trong đường dẫn,
   không đặt trong Program Files. Nên dùng đường dẫn chỉ có chữ không dấu (ví dụ C:\\Games\\LoD-VN): nếu đường dẫn có chữ
   có dấu (ví dụ "Giả lập"), launch-vi.bat tự tạm gán một ổ ảo (Z: hoặc ổ trống khác) cho thư mục game trong lúc chơi.
2. Chép 4 file .bin vào thư mục isos (tên file tuỳ ý).
3. Chạy launch-vi.bat (KHÔNG chạy launch.bat — đó là bản tiếng Anh).
   Lần đầu: tải Java, rồi SC giải nén tài nguyên từ đĩa (~1,4 GB vào thư mục files, khoảng 1 phút).
4. Ngôn ngữ và phông chữ đã đặt sẵn tiếng Việt. Nếu cần chỉnh: Tùy chọn → Tùy chọn chung → Giao diện →
   Phông chữ = "Tiếng Việt (pixel)", Ngôn ngữ = Vietnamese.

PHÍM MẶC ĐỊNH: mũi tên di chuyển, Enter/Space xác nhận/nói chuyện, Escape quay lại, E mở menu,
Enter 2 lần bỏ qua phim. Có thể đổi trong Tùy chọn → Tùy chọn chung → Điều khiển. Tay cầm được hỗ trợ sẵn.

TỐC ĐỘ VÀ HIỆU NĂNG (từ v0.3)
- Tùy chọn → Tùy chọn chung → Lối chơi → Tốc độ game: Bình thường, Nhanh gấp 2/3/4 (tăng tốc cả game, nhạc nền giữ
  nguyên). Phím tắt có sẵn của SC: "=" tăng, "-" giảm tốc độ.
- Tùy chọn → Tùy chọn chung → Đồ họa → "Tự bỏ khung hình khi máy chậm" (mặc định bật): máy vẽ không kịp thì bỏ bớt
  khung hình để game vẫn đúng tốc độ, không bị chậm như quay chậm. Máy yếu nên hạ Độ phân giải xuống 720p hoặc 480p.
- Tùy chọn → Tùy chọn chung → Đồ họa → "Tiết kiệm pin (30 khung/giây)" (từ v0.4, mặc định tắt): chỉ vẽ tối đa 30 khung
  hình mỗi giây, game vẫn đúng tốc độ; đỡ tốn pin máy xách tay, đi lại kém mượt hơn một chút.
- Từ v0.4: thu nhỏ cửa sổ thì game ngừng vẽ (game và nhạc vẫn chạy); khi tua nhanh hoặc khi im lặng game tốn ít máy hơn.

LƯU Ý QUAN TRỌNG
- Gói ghim theo một bản build SC nên đã tắt kiểm tra cập nhật (không hiện "Update Available"). Đừng cập nhật SC
  bằng cách khác: bản mới sẽ thay mã game và mất phần Việt hoá. Nếu lỡ cập nhật, launch-vi.bat sẽ báo; hãy giải nén
  lại gói này (giữ isos, saves).
- Đã tiếng Việt: lời thoại, vật phẩm, phép, đồ quý, menu, tuỳ chọn và giao diện riêng của SC, tên quái, địa danh,
  tên chương, trạng thái, màn tựa, chữ vẽ trong ảnh (Vàng, Bụi Sao, nhãn menu, thẻ tiêu đề chương, tên vùng bản đồ).
  Tên người, tên trang bị và tên Liên Kích giữ tiếng Anh (như bản PS1).
- Chuyển về tiếng Anh: Tùy chọn → Tùy chọn chung → Giao diện → Ngôn ngữ = English. Chữ vẽ trong ảnh (thư mục
  vi/files) vẫn tiếng Việt; muốn đúng bản gốc thì chạy launch.bat và chọn Ngôn ngữ = English.
- Lưu game: SC lưu không giới hạn ô trong thư mục saves. Save thẻ nhớ PS1/giả lập chép vào saves để SC chuyển đổi.

GIẤY PHÉP VÀ MÃ NGUỒN
Severed Chains và phần sửa mã trong vi/sc-vi.jar theo GNU AGPL-3.0 (vi/LICENSE). Mã nguồn:
- Severed Chains: lod-game-{sc}-sources.jar trong gói, hoặc
  https://github.com/Legend-of-Dragoon-Modding/Severed-Chains/tree/{sc}
- Phần Việt hoá: thư mục vi/NGUON (lớp Java đã sửa, bản diff so với SC, tự kiểm, công cụ sinh dữ liệu).
The Legend of Dragoon © Sony Interactive Entertainment. Đây là bản dịch phi lợi nhuận của người hâm mộ.

PHIÊN BẢN
- Việt hoá: v{v} (LoD-SC commit {src}, dữ liệu dịch: dự án bản vá PS1 commit {lod})
- Severed Chains: 3.0.0 devbuild commit {sc}
'''.format(v=version, sc=SC_COMMIT, sc7=SC_COMMIT[:7], pkg=PKG, src=src_commit[:7], lod=lod_commit[:7]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--version', required=True)
    ap.add_argument('--sc-zip', default=os.path.join(ROOT, 'dl', 'Severed_Chains_Windows.zip'))
    ap.add_argument('--game', default=os.path.join(ROOT, 'game'))
    ap.add_argument('--no-build', action='store_true', help='dung lai out/rel/src da dung (chi dong goi)')
    a = ap.parse_args()

    print('kiem SHA-256 ban build SC...')
    if sha256(a.sc_zip) != SC_ZIP_SHA:
        sys.exit('LOI: %s khong dung ban build SC %s' % (a.sc_zip, SC_COMMIT[:7]))

    sc_src = os.path.join(ROOT, 'Severed-Chains')
    if git('rev-parse', 'HEAD', cwd=sc_src).decode().strip() != SC_COMMIT:
        sys.exit('LOI: clone %s khong o commit %s (sc_lang/sc_font doc en.lang va font goc tu day)' % (sc_src, SC_COMMIT[:7]))
    src_commit = git('rev-parse', 'HEAD').decode().strip()
    # LOD_ROOT có thể là bản sao (thư mục nối tới D:\LOD khi đĩa trong D:\LOD đang nén) nằm trong repo này: git sẽ trả commit
    # của LoD-SC. Khi đó phải ghi commit của D:\LOD qua biến LOD_COMMIT.
    lod_top = git('rev-parse', '--show-toplevel', cwd=LOD).decode().strip()
    if os.path.normcase(os.path.abspath(lod_top)) == os.path.normcase(os.path.abspath(LOD)):
        lod_commit = git('rev-parse', 'HEAD', cwd=LOD).decode().strip()
    elif os.environ.get('LOD_COMMIT'):
        lod_commit = git('rev-parse', os.environ['LOD_COMMIT'], cwd=os.path.join(ROOT, '..', 'LOD')).decode().strip()
    else:
        sys.exit('LOI: %s khong phai goc repo git (ban sao?) — dat LOD_COMMIT = commit cua D:\\LOD' % LOD)
    dirty =git('status', '--porcelain', '--', 'sc-vi', 'tools', 'tr_sc', *ICON_SRC).decode().strip()
    if dirty:
        print('canh bao: co thay doi chua commit trong sc-vi/tools/tr_sc/icon — goi dung tu HEAD %s, KHONG gom thay doi do' % src_commit[:7])

    rel = os.path.join(ROOT, 'out', 'rel')
    src = os.path.join(rel, 'src')
    if not a.no_build:
        shutil.rmtree(rel, ignore_errors=True)
        os.makedirs(src)
        tar = git('archive', '--format=tar', 'HEAD', 'sc-vi', 'tools', 'tr_sc', *ICON_SRC)
        with tarfile.open(fileobj=io.BytesIO(tar)) as t:
            t.extractall(src, filter='data')
        env = dict(os.environ, LOD_ROOT=os.path.abspath(LOD), SC_ROOT=sc_src, PYTHONIOENCODING='utf-8')
        r = subprocess.run(['powershell', '-ExecutionPolicy', 'Bypass', '-File', os.path.join(src, 'tools', 'build_sc_vi.ps1'),
                            '-Game', os.path.abspath(a.game)], cwd=src, env=env, capture_output=True, text=True, encoding='utf-8')
        print('\n'.join(l for l in r.stdout.splitlines() if 'khop' not in l and 'canh bao' not in l))
        if r.returncode != 0:
            print(r.stderr)
            sys.exit('LOI: build_sc_vi.ps1 that bai')

    out = os.path.join(src, 'out')
    files = []   # (tên trong thư mục gói, bytes)
    files.append(('vi/sc-vi.jar', jar_bytes(os.path.join(out, 'classes'))))
    for name, data in zip_dir_deterministic(os.path.join(out, 'vi_files'), 'vi/files/'):
        files.append((name, data))
    for name, data in zip_dir_deterministic(os.path.join(src, 'sc-vi'), 'vi/NGUON/sc-vi/'):
        files.append((name, data))
    for f in ('sc_lang.py', 'sc_hardcoded.py', 'sc_lang_check.py', 'sc_gfx.py', 'sc_title_menu.py', 'sc_dialogue.py', 'sc_font.py',
              'sc_core_diff.py', 'build_sc_vi.ps1'):
        files.append(('vi/NGUON/tools/' + f, open(os.path.join(src, 'tools', f), 'rb').read()))
    files.append(('lang/lod.vi.lang', open(os.path.join(out, 'lang', 'lod.vi.lang'), 'rb').read()))
    files.append(('lang/dialogue.vi.tsv', open(os.path.join(out, 'lang', 'dialogue.vi.tsv'), 'rb').read()))
    files.append(('lang/scvi.vi.lang', open(os.path.join(out, 'lang', 'scvi.vi.lang'), 'rb').read()))
    for f in ('core.vi.lang', 'unpacker.vi.lang', 'turnorder.vi.lang', 'scvi_ui.vi.lang'):
        files.append(('lang/' + f, open(os.path.join(src, 'tr_sc', f), 'rb').read()))
    files.append(('gfx/fonts/vietnamese.json', open(os.path.join(out, 'fonts', 'vietnamese.json'), 'rb').read()))
    files.append(('gfx/fonts/vietnamese.png', open(os.path.join(out, 'fonts', 'vietnamese.png'), 'rb').read()))
    for f in ('title_menu.vi.png', 'title_menu.vi.widths'):
        files.append(('gfx/ui/' + f, open(os.path.join(out, 'gfx', 'ui', f), 'rb').read()))
    # biểu tượng cửa sổ game (SdlWindow của sc-vi dùng thay gfx/textures/icon.png của SC)
    files.append(('gfx/textures/icon.vi.png', open(os.path.join(out, 'gfx', 'textures', 'icon.vi.png'), 'rb').read()))
    for f in ('gen_icon.py', 'icon_rong.webp'):
        files.append(('vi/NGUON/android/' + f, open(os.path.join(src, 'android', f), 'rb').read()))
    files.append(('config.dcnf', config_dcnf()))
    files.append(('vi/VERSION.txt', ('viet_hoa=%s\nlod_sc_commit=%s\nlod_commit=%s\nsc_commit=%s\nsc_zip_sha256=%s\n' % (
        a.version, src_commit, lod_commit, SC_COMMIT, SC_ZIP_SHA)).encode()))
    hd = huong_dan(a.version, src_commit, lod_commit)
    files.append(('HUONG_DAN_VIET_HOA.txt', b'\xef\xbb\xbf' + hd.replace('\n', '\r\n').encode('utf-8')))

    with zipfile.ZipFile(a.sc_zip) as sc:
        names = sc.namelist()
        launch = sc.read('launch.bat').decode('utf-8')
        if SC_JAR not in names:
            sys.exit('LOI: zip SC khong co %s' % SC_JAR)
        files.append(('launch-vi.bat', launch_vi(launch)))
        files.append(('vi/LICENSE', sc.read('LICENSE')))
        ours = {n for n, _ in files}
        clash = [n for n in names if n in ours]
        if clash:
            sys.exit('LOI: trung ten voi file cua SC: %s' % clash)

        os.makedirs(os.path.join(ROOT, 'release'), exist_ok=True)
        zname = 'LoD-SC-VN-v%s-sc-%s-windows.zip' % (a.version, SC_COMMIT[:7])
        zpath = os.path.join(ROOT, 'release', zname)
        with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as z:
            for info in sorted(sc.infolist(), key=lambda i: i.filename):
                zi = zipfile.ZipInfo(PKG + '/' + info.filename, info.date_time)
                zi.external_attr = info.external_attr
                zi.compress_type = zipfile.ZIP_STORED if info.is_dir() else zipfile.ZIP_DEFLATED
                z.writestr(zi, b'' if info.is_dir() else sc.read(info.filename))
            for name, data in sorted(files):
                zi = zipfile.ZipInfo(PKG + '/' + name, FIXED_TIME)
                zi.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(zi, data)

    digest = sha256(zpath)
    sums = os.path.join(ROOT, 'release', 'SHA256SUMS.txt')
    old = [l for l in open(sums, encoding='ascii')] if os.path.exists(sums) else []
    with open(sums, 'w', encoding='ascii', newline='\n') as f:
        f.writelines(l for l in old if not l.rstrip().endswith('  ' + zname))
        f.write('%s  %s\n' % (digest, zname))
    print('goi: release/%s (%.1f MB)\nSHA-256 %s' % (zname, os.path.getsize(zpath) / 1e6, digest))


if __name__ == '__main__':
    main()
