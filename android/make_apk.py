"""Dựng APK Android (arm64-v8a) của bản Việt hoá The Legend of Dragoon chạy trên Severed Chains — không cần Gradle.

Cách gọi:
    python android/make_apk.py --version 0.2 [--build 1] [--zip release/LoD-SC-VN-v0.2-sc-affcef0-windows.zip]
Cần chạy trước: android/build_natives.ps1 (thư viện native), android/build_sc_android.ps1 (sc-android.jar + shader ES),
và có: deps/android/jre/jre25-android-arm64.tar.xz (JRE 25 Android của AngelAuraMC, kiểm SHA-256 bên dưới),
deps/android/maven/{ffmpeg-8.0.1-1.5.13,javacpp-1.5.13}-android-arm64.jar (Maven Central), Android SDK build-tools 36.1.0
+ platforms/android-36, JDK 17 (javac/d8/apksigner).

Nội dung APK:
    lib/arm64-v8a/*.so      SDL3, OpenAL Soft, Opus, LWJGL (core/opengles/stb), libsclauncher, FFmpeg+JavaCPP (bytedeco)
                            — không nén, căn 16 KB (zipalign -P 16); extractNativeLibs=true: LWJGL, JavaCPP và HotSpot tìm tệp .so trong nativeLibraryDir
    classes.dex             vn.lodsc.* (SetupActivity, VnGameActivity, TouchPad, Payload) + lớp Java của SDL3
    assets/payload.zip      (không nén lại) jre/ = JRE 25; game/ = gói Windows đã phát hành bỏ phần chỉ dùng cho Windows
                            (launch*.bat, launch.conf, updater.jar, natives Windows/Linux, FFmpeg Windows) + vi/sc-android.jar
                            + gfx/shaders_es + android-classpath.txt + vi/NGUON/android (mã nguồn phần Android, AGPL)
    assets/payload.version  SHA-256 của payload.zip (Payload.java giải nén lại khi khác)
Ký bằng khoá deps/android/keys/lodsc-release.jks (tạo lần đầu, mật khẩu ngẫu nhiên trong keystore.pass — SAO LƯU, mọi bản
cập nhật phải ký cùng khoá). Kết quả: release/LoD-SC-VN-v<ver>-android-arm64.apk (+ dòng trong release/SHA256SUMS.txt).
Xác định: cùng đầu vào -> cùng payload.zip (thời gian cố định, thứ tự cố định).

Mô hình HD (route B, tools/sc_remaster/SPEC.md): APK chỉ chở mã. Công cụ PC (TAO_MO_HINH_HD.bat, HUONG_DAN_MO_HINH_HD.txt,
vi/remaster/** trừ THIRD_PARTY.txt) bị bỏ khỏi payload; dữ liệu sinh từ đĩa người chơi được nhập trên máy bằng
SetupActivity/RemasterImport vào filesDir/game/remaster (+ game/remaster.properties). Chốt chặn (dừng dựng, "LOI (mo hinh HD)"):
    - không mục payload nào dưới game/remaster/, game/remaster.import|old/, game/remaster_work|tools|export/, không có
      remaster.properties, không còn vi/remaster/ (trừ THIRD_PARTY.txt), TAO_MO_HINH_HD.bat, HUONG_DAN_MO_HINH_HD.txt;
    - không tệp .lrm (trừ mẫu tổng hợp spec/sample_cube.lrm trong mã nguồn vi/NGUON), không PNG atlas (<sha1>.png,
      *_atlas*.png), không exe/dll/mô hình Real-ESRGAN hay exe Blender (mọi mẫu không phân biệt hoa thường);
    - Payload.PROGRAM (đọc từ Payload.java: các thư mục bị xoá khi cập nhật APK) không chứa "remaster" và không có mục trỏ
      tới cả game/ ("", ".", "./", thành phần "..").
Tự kiểm chốt chặn (không dựng APK, exit 0 = đạt):  python android/make_apk.py --selftest-guards
"""
import argparse
import hashlib
import io
import lzma
import os
import posixpath
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
AND = os.path.join(ROOT, 'android')
DEPS = os.path.join(ROOT, 'deps', 'android')
# Python cài dạng gói (MSIX) không đọc được %LOCALAPPDATA%\Android\Sdk -> dùng bản chép build-tools 36.1.0 + android.jar
# trong deps/android/sdk-tools (hoặc ANDROID_HOME)
SDK = os.environ.get('ANDROID_HOME', os.path.join(DEPS, 'sdk-tools'))
BT = os.path.join(SDK, 'build-tools', '36.1.0')
ANDROID_JAR = os.path.join(SDK, 'platforms', 'android-36', 'android.jar')
JDK17 = os.environ.get('JDK17', r'C:\Program Files\Eclipse Adoptium\jdk-17.0.20.8-hotspot')
# ABI -> (tên trong tệp JRE/bytedeco, SHA-256 JRE = digest GitHub của bản AngelAuraMC). x86_64 chỉ để thử trên giả lập.
ABIS = {
    'arm64-v8a': ('arm64', 'd3eb7afe2240c26728a1bb440502c5f18ac3883e932d202dd7f0c9bcbbce4c37'),
    'x86_64': ('x86_64', '7fca862ee1b2d5fe23cd9c9c3d9b7ad3c241947ad1a6cc9464ef2e674867105d'),
}
MAVEN = os.path.join(DEPS, 'maven')
SDL_JAVA = os.path.join(DEPS, 'out', 'sdl-java')
PKG = 'Severed Chains (VN)/'
FIXED = (2026, 10, 17, 0, 0, 0)
# Tệp của gói Windows không đưa vào bản Android
DROP_TOP = re.compile(r'^(launch[^/]*\.(bat|sh|command)|launch\.conf|updater\.jar|HUONG_DAN_VIET_HOA\.txt'
                      r'|TAO_MO_HINH_HD\.bat|HUONG_DAN_MO_HINH_HD\.txt)$')
DROP_LIB = re.compile(r'natives-(windows|linux|macos)|-windows-x86_64\.jar$')
# công cụ "Tạo mô hình HD" chỉ chạy trên PC (jar Swing, worker Python, danh mục, pins); giữ ghi chú giấy phép
DROP_PATH = re.compile(r'^vi/remaster/(?!THIRD_PARTY\.txt$)')
PAYLOAD_JAVA = os.path.join(AND, 'app', 'java', 'vn', 'lodsc', 'Payload.java')
# mẫu tổng hợp của WP0 (không phải dữ liệu Sony) có thể đi theo mã nguồn AGPL trong vi/NGUON
LRM_OK = {'game/vi/NGUON/tools/sc_remaster/spec/sample_cube.lrm'}
# không phân biệt hoa thường: gói Windows dựng trên NTFS (Remaster/ = remaster/), và tệp X.LRM / atlas tên hex hoa vẫn là
# dữ liệu sinh từ đĩa dù runtime không đọc
FORBID = [(re.compile('(?i)' + rx), why) for rx, why in (
    (r'^game/remaster(/|$)', 'du lieu mo hinh HD game/remaster/ (sinh tu dia nguoi choi)'),
    (r'^game/remaster\.(import|old)(/|$)', 'thu muc tam cua RemasterImport'),
    (r'^game/remaster_(work|tools|export)(/|$)', 'thu muc cua cong cu PC (remaster_work/tools/export)'),
    (r'(^|/)remaster\.properties(\.tmp)?$', 'cong tac remaster.properties (cua nguoi choi)'),
    (r'^game/vi/remaster/(?!THIRD_PARTY\.txt$)', 'cong cu PC vi/remaster/ (chi giu THIRD_PARTY.txt)'),
    (r'^game/(TAO_MO_HINH_HD\.bat|HUONG_DAN_MO_HINH_HD\.txt)$', 'tep chi dung tren PC'),
    (r'\.lrm(\.tmp)?$', 'mo hinh .lrm'),
    (r'(^|/)[0-9a-f]{40}\.png$', 'atlas PNG <sha1>.png'),
    (r'_atlas(_pad|_4x|_2x|_x4)?\.png$', 'atlas PNG cua bo sinh'),
    (r'realesrgan[^/]*\.(exe|dll|bin|param)$|(^|/)vcomp140\.dll$', 'Real-ESRGAN (nguoi choi tu tai)'),
    (r'(^|/)blender[^/]*\.(exe|zip)$', 'Blender (nguoi choi tu tai)'),
)]


def keep(rel):
    """mục rel (tương đối trong gói Windows) có đưa vào payload Android không"""
    return not (DROP_TOP.match(rel) or (rel.startswith('libs/') and DROP_LIB.search(rel)) or DROP_PATH.match(rel))


def guard_payload(names):
    """dừng dựng nếu payload chở dữ liệu mô hình HD / công cụ PC (tên mục payload: game/..., jre/...)"""
    bad = []
    for n in names:
        for rx, why in FORBID:
            if rx.search(n) and not (n in LRM_OK and n.endswith('.lrm')):
                bad.append('%s (%s)' % (n, why))
                break
    if bad:
        sys.exit('LOI (mo hinh HD): payload khong duoc chua:\n  ' + '\n  '.join(bad[:20]))


def guard_program(text):
    """Payload.PROGRAM = thư mục/tệp bị xoá khi cập nhật APK: không được chứa remaster (dữ liệu + công tắc phải còn)"""
    m = re.search(r'PROGRAM\s*=\s*\{([^}]*)\}', text)
    items = re.findall(r'"([^"]*)"', m.group(1)) if m else []
    if not items:
        sys.exit('LOI (mo hinh HD): khong doc duoc Payload.PROGRAM trong Payload.java')
    # "remaster*" hoặc mục trỏ tới cả game/ hay ra ngoài ("", ".", "./", "..", có thành phần "..") -> Payload.deleteTree xoá
    # luôn dữ liệu người chơi
    def whole(i):
        parts = [p for p in re.split(r'[/\\]', i.strip()) if p not in ('', '.')]
        return not parts or '..' in parts
    bad = [i for i in items if 'remaster' in i.lower() or whole(i)]
    if bad:
        sys.exit('LOI (mo hinh HD): Payload.PROGRAM chua %s -> cap nhat APK se xoa mo hinh HD / cong tac' % bad)
    return items


NATIVE_LIBS = ['libSDL3.so', 'libopenal.so', 'libopus.so', 'liblwjgl.so', 'liblwjgl_opengles.so', 'liblwjgl_stb.so',
               'libsclauncher.so', 'libc++_shared.so']


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def run(*cmd, **kw):
    r = subprocess.run(list(cmd), capture_output=True, text=True, encoding='utf-8', errors='replace', **kw)
    if r.returncode:
        print(r.stdout[-4000:])
        print(r.stderr[-4000:])
        sys.exit('LOI: %s' % ' '.join(os.path.basename(str(c)) for c in cmd[:2]))
    return r.stdout


def classpath(launch_bat):
    """thứ tự classpath của launch.bat (-cp "a.jar;libs/b.jar;...") bỏ jar chỉ dùng cho Windows"""
    m = re.search(r'-cp "([^"]+)"', launch_bat)
    if not m:
        sys.exit('LOI: khong doc duoc classpath trong launch.bat')
    out = []
    for p in m.group(1).split(';'):
        p = p.strip().replace('\\', '/')
        if p and not DROP_LIB.search(p):
            out.append(p)
    return out


def payload(zip_path, version, abi):
    entries = []   # (tên, bytes)
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        launch = z.read(PKG + 'launch.bat').decode('utf-8')
        for n in names:
            if not n.startswith(PKG) or n.endswith('/'):
                continue
            rel = n[len(PKG):]
            if not keep(rel):
                continue
            entries.append(('game/' + rel, z.read(n)))
    guard_payload(e[0] for e in entries)   # dừng sớm, trước khi đọc JRE
    cp = ['vi/sc-android.jar', 'vi/sc-vi.jar'] + classpath(launch)
    present = {e[0][len('game/'):] for e in entries}
    missing = [p for p in cp if p not in present and p != 'vi/sc-android.jar']
    if missing:
        sys.exit('LOI: classpath thieu %s' % missing)
    entries.append(('game/android-classpath.txt', ('\n'.join(cp) + '\n').encode()))
    # legend.core.Config (config.conf): giải nén đĩa kiểu ít bộ nhớ ngay từ đầu (heap Java trên điện thoại chỉ 1–2 GB;
    # kiểu thường hết bộ nhớ, SC chuyển sang kiểu này rồi bắt chơi lại)
    entries.append(('game/config.conf', b'low_memory_unpacker=true\n'))
    entries.append(('game/vi/sc-android.jar', open(os.path.join(ROOT, 'out', 'android', 'sc-android.jar'), 'rb').read()))
    es = os.path.join(ROOT, 'out', 'android', 'shaders_es')
    for f in sorted(os.listdir(es)):
        entries.append(('game/gfx/shaders_es/' + f, open(os.path.join(es, f), 'rb').read()))
    # mã nguồn phần Android (AGPL-3.0 như SC): app Java, launcher C, lớp đè SC, script dựng
    for base, _, files in os.walk(AND):
        for f in sorted(files):
            p = os.path.join(base, f)
            rel = os.path.relpath(p, AND).replace('\\', '/')
            if rel.startswith(('app/res/mipmap')) or f.endswith('.pyc'):
                continue
            entries.append(('game/vi/NGUON/android/' + rel, open(p, 'rb').read()))
    entries.append(('game/vi/VERSION-android.txt', ('viet_hoa=%s\nandroid=1\nlod_sc_commit=%s\n' % (
        version, run('git', '-C', ROOT, 'rev-parse', 'HEAD').strip())).encode()))

    jre_txz = os.path.join(DEPS, 'jre', 'jre25-android-%s.tar.xz' % ABIS[abi][0])
    data = open(jre_txz, 'rb').read()
    if sha256(data) != ABIS[abi][1]:
        sys.exit('LOI: %s khong dung SHA-256' % jre_txz)
    with tarfile.open(fileobj=io.BytesIO(lzma.decompress(data))) as t:
        def norm(n):
            return posixpath.normpath(n[2:] if n.startswith('./') else n)
        members = {norm(m.name): m for m in t.getmembers()}
        for name, m in sorted(members.items()):
            target = m
            for _ in range(8):   # symlink (chủ yếu legal/*/ASSEMBLY_EXCEPTION...) -> chép nội dung tệp đích
                if not target.issym():
                    break
                target = members.get(posixpath.normpath(posixpath.join(posixpath.dirname(norm(target.name)), target.linkname)))
                if target is None:
                    sys.exit('LOI: JRE symlink hong %s' % name)
            if target.isfile():
                entries.append(('jre/' + name, t.extractfile(target).read()))

    guard_payload(e[0] for e in entries)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, b in sorted(entries):
            zi = zipfile.ZipInfo(name, FIXED)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, b)
    return buf.getvalue(), len(entries)


def keystore():
    d = os.path.join(DEPS, 'keys')
    ks = os.path.join(d, 'lodsc-release.jks')
    pw = os.path.join(d, 'keystore.pass')
    if not os.path.exists(ks):
        os.makedirs(d, exist_ok=True)
        password = secrets.token_urlsafe(24)
        open(pw, 'w', encoding='ascii').write(password)
        run(os.path.join(JDK17, 'bin', 'keytool.exe'), '-genkeypair', '-keystore', ks, '-alias', 'lodsc', '-keyalg', 'RSA',
            '-keysize', '4096', '-validity', '18250', '-storepass', password, '-keypass', password,
            '-dname', 'CN=LoD tieng Viet (Severed Chains), O=KhuongKid')
        print('tao khoa ky moi: %s (SAO LUU ca keystore.pass)' % ks)
    return ks, pw


def selftest_guards():
    """gieo từng vi phạm, kiểm chốt chặn dừng đúng chỗ; gói sạch và Payload.java thật phải qua. exit 0 = đạt"""
    import tempfile
    results = []

    def fires(fn):
        try:
            fn()
        except SystemExit as e:
            return str(e)
        return None

    def check(desc, ok, note=''):
        results.append(ok)
        print('%-4s %s%s' % ('DAT' if ok else 'LOI', desc, (' -> ' + note.splitlines()[0]) if note else ''))

    k = 'ab' * 20
    clean = ['jre/bin/java', 'game/vi/sc-vi.jar', 'game/vi/remaster/THIRD_PARTY.txt', 'game/files/.keep',
             'game/vi/NGUON/tools/sc_remaster/spec/sample_cube.lrm', 'game/vi/NGUON/tools/sc_remaster/worker.py',
             'game/vi/NGUON/tools/sc_remaster/blender/geom_job.py', 'game/vi/NGUON/android/test/remaster_import.ps1',
             'game/vi/NGUON/android/app/java/vn/lodsc/RemasterImport.java', 'game/gfx/shaders_es/tmd.fsh',
             'game/vi/NGUON/tools/sc_remaster/SPEC.md', 'game/vi/NGUON/tools/remaster_tool/TAO_MO_HINH_HD.bat.in',
             'game/vi/NGUON/tools/remaster_tool/src/vn/lodsc/remaster/Toggle.java',
             'game/vi/NGUON/sc-vi/src/legend/scvi/remaster/RemasterConfig.java']
    msg = fires(lambda: guard_payload(clean))
    check('payload sach khong bi chan', msg is None, msg or '')
    seeded = ['game/remaster/index.tsv', 'game/remaster/manifest.json', 'game/remaster/models/%s.lrm' % k,
              'game/remaster/textures/%s.png' % k, 'game/remaster', 'game/remaster.properties',
              'game/remaster.import/remaster/index.tsv', 'game/remaster.old/index.tsv', 'game/remaster_work/scan.json',
              'game/remaster_tools/realesrgan/realesrgan-ncnn-vulkan.exe', 'game/remaster_export/LoD-HD.zip',
              'game/vi/remaster/lodsc-remaster.jar', 'game/vi/remaster/py/worker.py', 'game/vi/remaster/catalog_v1.json',
              'game/vi/remaster/pins.json', 'game/TAO_MO_HINH_HD.bat', 'game/HUONG_DAN_MO_HINH_HD.txt',
              'game/vi/NGUON/tools/sc_remaster/work/%s.lrm' % k, 'game/vi/x.lrm', 'game/files/%s.png' % k,
              'game/vi/NGUON/tools/sc_remodel/out/dart_atlas_4x.png', 'game/vi/dart_atlas.png',
              'game/vi/models/realesrgan-x4plus-anime.bin', 'game/x/vcomp140.dll', 'game/x/blender.exe',
              # hoa thường khác (NTFS không phân biệt) và tệp tạm của bộ sinh / công tắc
              'game/Remaster/index.tsv', 'game/REMASTER.PROPERTIES', 'game/vi/X.LRM', 'game/vi/%s.PNG' % k.upper(),
              'game/vi/Remaster/pins.json', 'game/vi/Dart_ATLAS_4x.png', 'game/remaster.properties.tmp',
              'game/vi/NGUON/x/%s.lrm.tmp' % k]
    for s in seeded:
        msg = fires(lambda: guard_payload(clean + [s]))
        check('chan %s' % s, msg is not None and msg.startswith('LOI (mo hinh HD)'), msg or 'KHONG CHAN')

    real = open(PAYLOAD_JAVA, encoding='utf-8').read()
    msg = fires(lambda: guard_program(real))
    check('Payload.java hien tai qua (PROGRAM = %s)' % (guard_program(real) if msg is None else '?'), msg is None, msg or '')
    for desc, text in (('PROGRAM co "remaster"', real.replace('"patches"', '"patches", "remaster"')),
                       ('PROGRAM co "remaster.properties"', real.replace('"lang"', '"remaster.properties", "lang"')),
                       ('PROGRAM co "Remaster"', real.replace('"gfx"', '"Remaster", "gfx"')),
                       ('PROGRAM co "" (ca game/)', real.replace('"gfx"', '"", "gfx"')),
                       ('PROGRAM co "./"', real.replace('"gfx"', '"./", "gfx"')),
                       ('PROGRAM co "../game"', real.replace('"gfx"', '"../game", "gfx"')),
                       ('khong co PROGRAM', 'final class Payload { }')):
        msg = fires(lambda: guard_program(text))
        check('chan ' + desc, msg is not None and msg.startswith('LOI (mo hinh HD)'), msg or 'KHONG CHAN')

    for rel, want in (('TAO_MO_HINH_HD.bat', False), ('HUONG_DAN_MO_HINH_HD.txt', False),
                      ('vi/remaster/lodsc-remaster.jar', False), ('vi/remaster/py/worker.py', False),
                      ('vi/remaster/py/lib/lrm.py', False), ('vi/remaster/catalog_v1.json', False),
                      ('vi/remaster/pins.json', False), ('vi/remaster/THIRD_PARTY.txt', True), ('vi/sc-vi.jar', True),
                      ('launch-vi.bat', False), ('vi/NGUON/tools/sc_remaster/worker.py', True),
                      ('HUONG_DAN_VIET_HOA.txt', False), ('README.txt', True)):
        check('loc goi Windows: %s -> %s' % (rel, 'giu' if want else 'bo'), keep(rel) == want)

    # đầu-cuối: payload() trên gói Windows giả có gieo vi phạm phải dừng ở chốt chặn (trước khi đọc JRE)
    with tempfile.TemporaryDirectory() as d:
        for s in ('remaster/index.tsv', 'remaster.properties', 'remaster/models/%s.lrm' % k, 'remaster_work/scan.json'):
            zp = os.path.join(d, 'fake.zip')
            with zipfile.ZipFile(zp, 'w') as z:
                z.writestr(PKG + 'launch.bat', 'java -cp "vi/sc-vi.jar;libs/a.jar" legend.game.Main\r\n')
                z.writestr(PKG + 'vi/sc-vi.jar', b'')
                z.writestr(PKG + 'libs/a.jar', b'')
                z.writestr(PKG + 'vi/remaster/lodsc-remaster.jar', b'')   # bị lọc, không phải vi phạm
                z.writestr(PKG + s, b'x')
            msg = fires(lambda: payload(zp, '0.0', 'x86_64'))
            check('payload() dung voi %s trong goi Windows' % s, msg is not None and msg.startswith('LOI (mo hinh HD)'),
                  msg or 'KHONG DUNG')
    bad = results.count(False)
    print('%s: %d/%d' % ('DAT' if not bad else 'KHONG DAT', len(results) - bad, len(results)))
    return 0 if not bad else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--version')
    ap.add_argument('--build', type=int, default=1)
    ap.add_argument('--zip')
    ap.add_argument('--abi', default='arm64-v8a', choices=sorted(ABIS))
    ap.add_argument('--selftest-guards', action='store_true', help='chi tu kiem chot chan mo hinh HD, khong dung APK')
    a = ap.parse_args()
    if a.selftest_guards:
        sys.exit(selftest_guards())
    if not a.version:
        ap.error('can --version')
    guard_program(open(PAYLOAD_JAVA, encoding='utf-8').read())
    zip_path = a.zip or os.path.join(ROOT, 'release', 'LoD-SC-VN-v%s-sc-affcef0-windows.zip' % a.version)
    major, minor = (int(x) for x in a.version.split('.')[:2])
    version_code = major * 100000 + minor * 1000 + a.build
    version_name = '%s-android%d' % (a.version, a.build)

    work = os.path.join(ROOT, 'out', 'android', 'apk')
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)

    print('payload...')
    pay, count = payload(zip_path, a.version, a.abi)
    pay_ver = sha256(pay)[:32]
    print('payload.zip %.1f MB, %d tep' % (len(pay) / 1e6, count))

    print('aapt2...')
    manifest = open(os.path.join(AND, 'app', 'AndroidManifest.xml'), encoding='utf-8').read()
    manifest = manifest.replace('@VERSION_CODE@', str(version_code)).replace('@VERSION_NAME@', version_name)
    mpath = os.path.join(work, 'AndroidManifest.xml')
    open(mpath, 'w', encoding='utf-8').write(manifest)
    aapt2 = os.path.join(BT, 'aapt2.exe')
    run(aapt2, 'compile', '--dir', os.path.join(AND, 'app', 'res'), '-o', os.path.join(work, 'res.zip'))
    gen = os.path.join(work, 'gen')
    os.makedirs(gen)
    # bản x86_64 (thử trên giả lập) bật debuggable để dùng được "adb shell run-as vn.lodsc" xem tệp/log
    run(aapt2, 'link', '-o', os.path.join(work, 'base.apk'), '-I', ANDROID_JAR, '--manifest', mpath,
        os.path.join(work, 'res.zip'), '--java', gen, '--auto-add-overlay', *([] if a.abi == 'arm64-v8a' else ['--debug-mode']))

    print('javac + d8...')
    srcs = []
    for d in (os.path.join(AND, 'app', 'java'), SDL_JAVA, gen):
        for base, _, files in os.walk(d):
            srcs += [os.path.join(base, f) for f in files if f.endswith('.java')]
    cls = os.path.join(work, 'classes')
    os.makedirs(cls)
    argfile = os.path.join(work, 'srcs.txt')
    open(argfile, 'w', encoding='utf-8').write('\n'.join('"%s"' % s.replace('\\', '/') for s in srcs))
    run(os.path.join(JDK17, 'bin', 'javac.exe'), '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-nowarn', '-Xlint:-options',
        '-bootclasspath', ANDROID_JAR + os.pathsep + os.path.join(BT, 'core-lambda-stubs.jar'), '-d', cls, '@' + argfile)
    classes = []
    for base, _, files in os.walk(cls):
        classes += [os.path.join(base, f) for f in files if f.endswith('.class')]
    dex = os.path.join(work, 'dex')
    os.makedirs(dex)
    env = dict(os.environ, JAVA_HOME=JDK17)
    cargs = os.path.join(work, 'classes.txt')
    open(cargs, 'w', encoding='utf-8').write('\n'.join(c.replace('\\', '/') for c in classes))
    run(os.path.join(BT, 'd8.bat'), '--release', '--min-api', '29', '--lib', ANDROID_JAR, '--output', dex, '@' + cargs, env=env)

    print('ghep APK...')
    # thư viện khởi chạy phải được dựng từ đúng mã nguồn hiện tại cho ABI này (lỗi 17/10: bản arm64 cũ thiếu
    # --add-opens java.base/java.io -> SC không đọc được đĩa); build_natives.ps1 ghi dấu SHA-256 của nguồn
    src_hash = hashlib.sha256(open(os.path.join(AND, 'launcher', 'sclauncher.c'), 'rb').read()
                              + open(os.path.join(AND, 'launcher', 'CMakeLists.txt'), 'rb').read()).hexdigest()
    stamp = os.path.join(DEPS, 'out', a.abi, 'libsclauncher.src.sha256')
    if not os.path.exists(stamp) or open(stamp, encoding='ascii').read().strip() != src_hash:
        sys.exit('LOI: libsclauncher.so (%s) khong khop sclauncher.c: chay android/build_natives.ps1 -Abi %s -Only launcher'
                 % (a.abi, a.abi))
    libs = {}
    for n in NATIVE_LIBS:
        libs[n] = open(os.path.join(DEPS, 'out', a.abi, n), 'rb').read()
    tag = ABIS[a.abi][0]
    for j in ('ffmpeg-8.0.1-1.5.13-android-%s.jar' % tag, 'javacpp-1.5.13-android-%s.jar' % tag):
        with zipfile.ZipFile(os.path.join(MAVEN, j)) as z:
            for n in z.namelist():
                if n.startswith('lib/%s/' % a.abi) and n.endswith('.so'):
                    libs[os.path.basename(n)] = z.read(n)
    unaligned = os.path.join(work, 'unaligned.apk')
    with zipfile.ZipFile(os.path.join(work, 'base.apk')) as base, zipfile.ZipFile(unaligned, 'w') as out:
        for info in base.infolist():
            zi = zipfile.ZipInfo(info.filename, FIXED)
            zi.compress_type = zipfile.ZIP_STORED if info.filename == 'resources.arsc' or info.filename.endswith('.png') \
                else zipfile.ZIP_DEFLATED
            out.writestr(zi, base.read(info.filename))
        zi = zipfile.ZipInfo('classes.dex', FIXED)
        zi.compress_type = zipfile.ZIP_DEFLATED
        out.writestr(zi, open(os.path.join(dex, 'classes.dex'), 'rb').read())
        for n in sorted(libs):
            zi = zipfile.ZipInfo('lib/%s/' % a.abi + n, FIXED)
            zi.compress_type = zipfile.ZIP_STORED
            out.writestr(zi, libs[n])
        zi = zipfile.ZipInfo('assets/payload.zip', FIXED)
        zi.compress_type = zipfile.ZIP_STORED
        out.writestr(zi, pay)
        zi = zipfile.ZipInfo('assets/payload.version', FIXED)
        zi.compress_type = zipfile.ZIP_DEFLATED
        out.writestr(zi, pay_ver.encode())

    aligned = os.path.join(work, 'aligned.apk')
    run(os.path.join(BT, 'zipalign.exe'), '-f', '-P', '16', '4', unaligned, aligned)
    run(os.path.join(BT, 'zipalign.exe'), '-c', '-P', '16', '4', aligned)
    ks, pw = keystore()
    release = a.abi == 'arm64-v8a'   # bản x86_64 chỉ để thử trên giả lập: ra out/android, không ghi SHA256SUMS
    dest = os.path.join(ROOT, 'release') if release else os.path.join(ROOT, 'out', 'android')
    os.makedirs(dest, exist_ok=True)
    name = 'LoD-SC-VN-v%s-android-%s.apk' % (a.version, ABIS[a.abi][0])
    final = os.path.join(dest, name)
    sign_env = dict(env, LODSC_KS_PASS=open(pw, encoding='ascii').read().strip())
    run(os.path.join(BT, 'apksigner.bat'), 'sign', '--ks', ks, '--ks-key-alias', 'lodsc', '--ks-pass', 'env:LODSC_KS_PASS',
        '--key-pass', 'env:LODSC_KS_PASS', '--min-sdk-version', '29', '--out', final, aligned, env=sign_env)
    run(os.path.join(BT, 'apksigner.bat'), 'verify', '--min-sdk-version', '29', final, env=env)

    digest = sha256(open(final, 'rb').read())
    if release:
        sums = os.path.join(ROOT, 'release', 'SHA256SUMS.txt')
        old = [l for l in open(sums, encoding='ascii')] if os.path.exists(sums) else []
        with open(sums, 'w', encoding='ascii', newline='\n') as f:
            f.writelines(l for l in old if not l.rstrip().endswith('  ' + name))
            f.write('%s  %s\n' % (digest, name))
    print('APK: %s (%.1f MB) versionCode %d, SHA-256 %s' % (os.path.relpath(final, ROOT), os.path.getsize(final) / 1e6,
                                                         version_code, digest))


if __name__ == '__main__':
    main()
